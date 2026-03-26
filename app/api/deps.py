import logging
from functools import lru_cache

from app.core.config import Settings, get_settings
from app.integrations.event_bus import NoopEventBus, PubSubEventBus, RetryingEventBus
from app.integrations.workflow import (
    NoopHandoffWorkflowEngine,
    RetryingHandoffWorkflowEngine,
    TemporalHandoffWorkflowEngine,
)
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.model_serving import (
    ArtifactRoutingModelEngine,
    FallbackRoutingModelEngine,
    HeuristicRoutingModelEngine,
    HttpRoutingModelEngine,
)
from app.services.orchestrator import DecisionOrchestrator
from app.services.policy import PolicyService
from app.services.readiness import ReadinessService
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService
from app.security.rate_limit import NoopRateLimiter, RedisRateLimiter
from app.storage.feedback_store import NoopFeedbackStore, PostgresFeedbackStore
from app.storage.handoff_store import NoopHandoffStore, PostgresHandoffStore
from app.storage.inference_store import NoopInferenceStore, PostgresInferenceStore
from app.storage.model_ops_store import NoopModelOpsStore, PostgresModelOpsStore, RolloutConfig
from app.storage.postgres_store import PostgresRetrievalStore

logger = logging.getLogger(__name__)


def _build_event_bus(settings: Settings):
    backend = settings.event_bus_backend.strip().lower()
    if backend == 'pubsub':
        if not settings.pubsub_project_id:
            logger.warning('EVENT_BUS_BACKEND=pubsub requires PUBSUB_PROJECT_ID. Falling back to noop event bus.')
            delegate = NoopEventBus()
        else:
            delegate = PubSubEventBus(
                project_id=settings.pubsub_project_id,
                topic=settings.pubsub_topic,
                publish_timeout_seconds=settings.pubsub_publish_timeout_seconds,
            )
    else:
        delegate = NoopEventBus()

    return RetryingEventBus(
        delegate=delegate,
        retry_attempts=settings.event_bus_retry_attempts,
        retry_backoff_seconds=settings.event_bus_retry_backoff_seconds,
    )


def _build_workflow_engine(settings: Settings):
    backend = settings.workflow_backend.strip().lower()
    if backend == 'temporal':
        delegate = TemporalHandoffWorkflowEngine(
            target_host=settings.temporal_target_host,
            namespace=settings.temporal_namespace,
            task_queue=settings.temporal_task_queue,
            workflow_name=settings.temporal_workflow_name,
            workflow_retry_attempts=settings.temporal_workflow_retry_attempts,
            workflow_retry_initial_interval_seconds=settings.temporal_workflow_retry_initial_interval_seconds,
        )
    else:
        delegate = NoopHandoffWorkflowEngine()

    return RetryingHandoffWorkflowEngine(
        delegate=delegate,
        retry_attempts=settings.workflow_retry_attempts,
        retry_backoff_seconds=settings.workflow_retry_backoff_seconds,
    )


def _build_routing_service(settings: Settings) -> RoutingService:
    fallback_engine = HeuristicRoutingModelEngine()
    backend = settings.routing_model_backend.strip().lower()

    if backend == 'artifact':
        try:
            primary_engine = ArtifactRoutingModelEngine(
                routing_model_path=settings.routing_model_artifact_path,
                routing_calibration_path=settings.routing_calibration_artifact_path,
                escalation_model_path=settings.escalation_model_artifact_path,
                escalation_calibration_path=settings.escalation_calibration_artifact_path,
            )
            model_engine = FallbackRoutingModelEngine(primary=primary_engine, fallback=fallback_engine)
        except Exception:
            logger.exception('Failed to initialize artifact model backend. Falling back to heuristic routing.')
            model_engine = fallback_engine
    elif backend == 'http':
        if not settings.model_serving_url.strip():
            logger.warning('ROUTING_MODEL_BACKEND=http requires MODEL_SERVING_URL. Falling back to heuristic routing.')
            model_engine = fallback_engine
        else:
            primary_engine = HttpRoutingModelEngine(
                endpoint_url=settings.model_serving_url,
                timeout_seconds=settings.model_serving_timeout_seconds,
                api_key=settings.model_serving_api_key,
            )
            model_engine = FallbackRoutingModelEngine(primary=primary_engine, fallback=fallback_engine)
    else:
        model_engine = fallback_engine

    return RoutingService(model_engine=model_engine)


def _build_shadow_routing_service(settings: Settings) -> RoutingService | None:
    if not settings.model_shadow_enabled:
        return None

    fallback_engine = HeuristicRoutingModelEngine()
    backend = settings.challenger_routing_model_backend.strip().lower()

    if backend == 'artifact':
        try:
            primary_engine = ArtifactRoutingModelEngine(
                routing_model_path=settings.challenger_routing_model_artifact_path,
                routing_calibration_path=settings.challenger_routing_calibration_artifact_path,
                escalation_model_path=settings.challenger_escalation_model_artifact_path,
                escalation_calibration_path=settings.challenger_escalation_calibration_artifact_path,
            )
            model_engine = FallbackRoutingModelEngine(primary=primary_engine, fallback=fallback_engine)
        except Exception:
            logger.exception('Failed to initialize challenger artifact backend. Falling back to heuristic routing.')
            model_engine = fallback_engine
    elif backend == 'http':
        if not settings.challenger_model_serving_url.strip():
            logger.warning(
                'CHALLENGER_ROUTING_MODEL_BACKEND=http requires CHALLENGER_MODEL_SERVING_URL. '
                'Falling back to heuristic routing.',
            )
            model_engine = fallback_engine
        else:
            primary_engine = HttpRoutingModelEngine(
                endpoint_url=settings.challenger_model_serving_url,
                timeout_seconds=settings.challenger_model_serving_timeout_seconds,
                api_key=settings.challenger_model_serving_api_key,
            )
            model_engine = FallbackRoutingModelEngine(primary=primary_engine, fallback=fallback_engine)
    else:
        model_engine = fallback_engine

    return RoutingService(model_engine=model_engine)


def _default_rollout_config(settings: Settings) -> RolloutConfig:
    return RolloutConfig(
        config_id='primary',
        challenger_model_name=settings.challenger_model_name,
        challenger_model_version=settings.challenger_model_version,
        canary_percent=settings.canary_traffic_percent,
        quality_gate_min_route_accuracy=settings.model_ops_quality_gate_min_route_accuracy,
        quality_gate_min_escalation_recall=settings.model_ops_quality_gate_min_escalation_recall,
        quality_gate_max_ece=settings.model_ops_quality_gate_max_ece,
        quality_gate_max_abstain_rate=settings.model_ops_quality_gate_max_abstain_rate,
        quality_gate_min_sample_size=settings.model_ops_quality_gate_min_sample_size,
    )


@lru_cache(maxsize=1)
def get_model_ops_store():
    settings = get_settings()
    default_rollout = _default_rollout_config(settings)
    if settings.use_postgres:
        return PostgresModelOpsStore(settings.postgres_dsn, default_rollout_config=default_rollout)
    return NoopModelOpsStore(
        challenger_model_name=default_rollout.challenger_model_name,
        challenger_model_version=default_rollout.challenger_model_version,
        canary_percent=default_rollout.canary_percent,
        quality_gate_min_route_accuracy=default_rollout.quality_gate_min_route_accuracy,
        quality_gate_min_escalation_recall=default_rollout.quality_gate_min_escalation_recall,
        quality_gate_max_ece=default_rollout.quality_gate_max_ece,
        quality_gate_max_abstain_rate=default_rollout.quality_gate_max_abstain_rate,
        quality_gate_min_sample_size=default_rollout.quality_gate_min_sample_size,
    )


@lru_cache(maxsize=1)
def get_orchestrator() -> DecisionOrchestrator:
    settings = get_settings()
    postgres_store = (
        PostgresRetrievalStore(
            dsn=settings.postgres_dsn,
            vector_dim=settings.retrieval_vector_dim,
            rrf_k=settings.retrieval_rrf_k,
            embedding_backend=settings.embedding_backend,
        )
        if settings.use_postgres
        else None
    )
    retrieval = RetrievalService(
        postgres_store=postgres_store,
        enable_reranking=settings.retrieval_enable_reranking,
        enable_dedup=settings.retrieval_enable_dedup,
        stale_penalty_days=settings.retrieval_stale_penalty_days,
    )
    routing = _build_routing_service(settings)
    shadow_routing = _build_shadow_routing_service(settings)
    policy = PolicyService(settings=settings)
    generation = GenerationService(
        backend=settings.generation_backend,
        model=settings.generation_model,
        ollama_base_url=settings.generation_ollama_base_url,
        timeout_seconds=settings.generation_timeout_seconds,
        temperature=settings.generation_temperature,
        max_tokens=settings.generation_max_tokens,
        max_history_turns=settings.generation_max_history_turns,
        similarity_threshold=settings.generation_similarity_threshold,
        fail_open=settings.generation_fail_open,
        style_examples_path=settings.generation_style_examples_path,
        max_style_examples_per_prompt=settings.generation_max_style_examples_per_prompt,
    )
    handoff = HandoffService()
    inference_store = PostgresInferenceStore(settings.postgres_dsn) if settings.use_postgres else NoopInferenceStore()
    event_bus = _build_event_bus(settings)
    workflow_engine = _build_workflow_engine(settings)
    model_ops_store = get_model_ops_store()

    return DecisionOrchestrator(
        retrieval_service=retrieval,
        routing_service=routing,
        policy_service=policy,
        generation_service=generation,
        handoff_service=handoff,
        inference_store=inference_store,
        event_bus=event_bus,
        workflow_engine=workflow_engine,
        shadow_routing_service=shadow_routing,
        model_ops_store=model_ops_store,
        canary_rollout_enabled=settings.canary_rollout_enabled,
        canary_traffic_percent=settings.canary_traffic_percent,
        rollout_from_db=settings.model_ops_rollout_from_db,
        challenger_model_name=settings.challenger_model_name,
        challenger_model_version=settings.challenger_model_version,
        model_guardrail_force_handoff_on_fallback=settings.model_guardrail_force_handoff_on_fallback,
        model_guardrail_confidence_lower_bound=settings.model_guardrail_confidence_lower_bound,
        model_guardrail_confidence_upper_bound=settings.model_guardrail_confidence_upper_bound,
        pii_redaction_enabled=settings.pii_redaction_enabled,
    )


@lru_cache(maxsize=1)
def get_feedback_store():
    settings = get_settings()
    if settings.use_postgres:
        return PostgresFeedbackStore(settings.postgres_dsn)
    return NoopFeedbackStore()


@lru_cache(maxsize=1)
def get_handoff_store():
    settings = get_settings()
    if settings.use_postgres:
        return PostgresHandoffStore(settings.postgres_dsn)
    return NoopHandoffStore()


@lru_cache(maxsize=1)
def get_rate_limiter():
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return NoopRateLimiter()
    return RedisRateLimiter(
        redis_url=settings.redis_url,
        window_seconds=settings.rate_limit_window_seconds,
        tenant_limit=settings.rate_limit_tenant_requests_per_window,
        user_limit=settings.rate_limit_user_requests_per_window,
        fail_open=settings.rate_limit_fail_open,
        key_prefix=settings.rate_limit_key_prefix,
    )


@lru_cache(maxsize=1)
def get_readiness_service() -> ReadinessService:
    settings = get_settings()
    return ReadinessService(settings=settings)
