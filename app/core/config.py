from functools import lru_cache

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8', extra='ignore')

    app_name: str = Field(default='decision-platform', alias='APP_NAME')
    app_env: str = Field(default='local', alias='APP_ENV')
    app_host: str = Field(default='0.0.0.0', alias='APP_HOST')
    app_port: int = Field(default=8000, alias='APP_PORT')
    log_level: str = Field(default='INFO', alias='LOG_LEVEL')

    observability_log_format: str = Field(default='json', alias='OBSERVABILITY_LOG_FORMAT')
    observability_service_name: str = Field(default='decision-api', alias='OBSERVABILITY_SERVICE_NAME')
    metrics_enabled: bool = Field(default=True, alias='METRICS_ENABLED')
    tracing_enabled: bool = Field(default=False, alias='TRACING_ENABLED')
    otlp_endpoint: str = Field(default='http://localhost:4317', alias='OTLP_ENDPOINT')
    otlp_insecure: bool = Field(default=True, alias='OTLP_INSECURE')
    trace_sample_ratio: float = Field(default=1.0, ge=0.0, le=1.0, alias='TRACE_SAMPLE_RATIO')

    base_confidence_threshold: float = Field(default=0.65, alias='BASE_CONFIDENCE_THRESHOLD')
    max_auto_escalation_prob: float = Field(default=0.55, alias='MAX_AUTO_ESCALATION_PROB')

    use_postgres: bool = Field(default=False, alias='USE_POSTGRES')
    postgres_dsn: str = Field(
        default='postgresql+psycopg://postgres:postgres@localhost:5432/decision_db',
        alias='POSTGRES_DSN',
    )
    retrieval_vector_dim: int = Field(default=64, alias='RETRIEVAL_VECTOR_DIM')
    retrieval_rrf_k: int = Field(default=60, alias='RETRIEVAL_RRF_K')

    use_redis: bool = Field(default=False, alias='USE_REDIS')
    redis_url: str = Field(default='redis://localhost:6379/0', alias='REDIS_URL')
    rate_limit_enabled: bool = Field(default=False, alias='RATE_LIMIT_ENABLED')
    rate_limit_window_seconds: int = Field(default=60, ge=1, alias='RATE_LIMIT_WINDOW_SECONDS')
    rate_limit_tenant_requests_per_window: int = Field(
        default=120,
        ge=1,
        alias='RATE_LIMIT_TENANT_REQUESTS_PER_WINDOW',
    )
    rate_limit_user_requests_per_window: int = Field(
        default=60,
        ge=1,
        alias='RATE_LIMIT_USER_REQUESTS_PER_WINDOW',
    )
    rate_limit_fail_open: bool = Field(default=True, alias='RATE_LIMIT_FAIL_OPEN')
    rate_limit_key_prefix: str = Field(default='assist:ratelimit', alias='RATE_LIMIT_KEY_PREFIX')

    use_opa: bool = Field(default=False, alias='USE_OPA')
    opa_url: str = Field(default='http://localhost:8181/v1/data/assist/decision', alias='OPA_URL')

    auth_enabled: bool = Field(default=False, alias='AUTH_ENABLED')
    jwt_secret_key: str = Field(default='change-me-local-dev-secret', alias='JWT_SECRET_KEY')
    jwt_algorithm: str = Field(default='HS256', alias='JWT_ALGORITHM')
    jwt_issuer: str = Field(default='decision-platform', alias='JWT_ISSUER')
    jwt_audience: str = Field(default='decision-platform-api', alias='JWT_AUDIENCE')

    routing_model_backend: str = Field(default='artifact', alias='ROUTING_MODEL_BACKEND')
    routing_model_artifact_path: str = Field(
        default='artifacts/models/routing_linear_v1.json',
        alias='ROUTING_MODEL_ARTIFACT_PATH',
    )
    routing_calibration_artifact_path: str = Field(
        default='artifacts/models/routing_temperature_v1.json',
        alias='ROUTING_CALIBRATION_ARTIFACT_PATH',
    )
    escalation_model_artifact_path: str = Field(
        default='artifacts/models/escalation_linear_v1.json',
        alias='ESCALATION_MODEL_ARTIFACT_PATH',
    )
    escalation_calibration_artifact_path: str = Field(
        default='artifacts/models/escalation_platt_v1.json',
        alias='ESCALATION_CALIBRATION_ARTIFACT_PATH',
    )
    model_serving_url: str = Field(
        default='http://localhost:9000/v1/models/routing:predict',
        alias='MODEL_SERVING_URL',
    )
    model_serving_timeout_seconds: float = Field(default=2.0, ge=0.1, alias='MODEL_SERVING_TIMEOUT_SECONDS')
    model_serving_api_key: str = Field(default='', alias='MODEL_SERVING_API_KEY')

    generation_backend: str = Field(default='ollama', alias='GENERATION_BACKEND')
    generation_model: str = Field(default='qwen2.5:7b-instruct', alias='GENERATION_MODEL')
    generation_ollama_base_url: str = Field(default='http://localhost:11434', alias='GENERATION_OLLAMA_BASE_URL')
    generation_timeout_seconds: float = Field(default=15.0, ge=0.1, alias='GENERATION_TIMEOUT_SECONDS')
    generation_temperature: float = Field(default=0.3, ge=0.0, le=2.0, alias='GENERATION_TEMPERATURE')
    generation_max_tokens: int = Field(default=512, ge=32, le=4096, alias='GENERATION_MAX_TOKENS')

    knowledge_chunks_path: str = Field(
        default='artifacts/datasets/knowledge_chunks.json',
        alias='KNOWLEDGE_CHUNKS_PATH',
    )
    generation_max_history_turns: int = Field(default=8, ge=1, le=50, alias='GENERATION_MAX_HISTORY_TURNS')
    generation_similarity_threshold: float = Field(
        default=0.82,
        ge=0.5,
        le=0.99,
        alias='GENERATION_SIMILARITY_THRESHOLD',
    )
    generation_fail_open: bool = Field(default=True, alias='GENERATION_FAIL_OPEN')
    generation_style_examples_path: str = Field(
        default='artifacts/datasets/style_examples.jsonl',
        alias='GENERATION_STYLE_EXAMPLES_PATH',
    )
    generation_max_style_examples_per_prompt: int = Field(
        default=2,
        ge=0,
        le=6,
        alias='GENERATION_MAX_STYLE_EXAMPLES_PER_PROMPT',
    )

    model_shadow_enabled: bool = Field(default=True, alias='MODEL_SHADOW_ENABLED')
    challenger_model_name: str = Field(default='challenger-routing', alias='CHALLENGER_MODEL_NAME')
    challenger_model_version: str = Field(default='v1', alias='CHALLENGER_MODEL_VERSION')
    challenger_routing_model_backend: str = Field(default='heuristic', alias='CHALLENGER_ROUTING_MODEL_BACKEND')
    challenger_routing_model_artifact_path: str = Field(
        default='artifacts/models/routing_linear_v1.json',
        alias='CHALLENGER_ROUTING_MODEL_ARTIFACT_PATH',
    )
    challenger_routing_calibration_artifact_path: str = Field(
        default='artifacts/models/routing_temperature_v1.json',
        alias='CHALLENGER_ROUTING_CALIBRATION_ARTIFACT_PATH',
    )
    challenger_escalation_model_artifact_path: str = Field(
        default='artifacts/models/escalation_linear_v1.json',
        alias='CHALLENGER_ESCALATION_MODEL_ARTIFACT_PATH',
    )
    challenger_escalation_calibration_artifact_path: str = Field(
        default='artifacts/models/escalation_platt_v1.json',
        alias='CHALLENGER_ESCALATION_CALIBRATION_ARTIFACT_PATH',
    )
    challenger_model_serving_url: str = Field(
        default='http://localhost:9000/v1/models/routing:predict',
        alias='CHALLENGER_MODEL_SERVING_URL',
    )
    challenger_model_serving_timeout_seconds: float = Field(
        default=2.0,
        ge=0.1,
        alias='CHALLENGER_MODEL_SERVING_TIMEOUT_SECONDS',
    )
    challenger_model_serving_api_key: str = Field(default='', alias='CHALLENGER_MODEL_SERVING_API_KEY')

    canary_rollout_enabled: bool = Field(default=False, alias='CANARY_ROLLOUT_ENABLED')
    canary_traffic_percent: int = Field(default=0, ge=0, le=100, alias='CANARY_TRAFFIC_PERCENT')
    model_ops_rollout_from_db: bool = Field(default=True, alias='MODEL_OPS_ROLLOUT_FROM_DB')
    model_ops_quality_gate_min_route_accuracy: float = Field(
        default=0.75,
        ge=0.0,
        le=1.0,
        alias='MODEL_OPS_QUALITY_GATE_MIN_ROUTE_ACCURACY',
    )
    model_ops_quality_gate_min_escalation_recall: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        alias='MODEL_OPS_QUALITY_GATE_MIN_ESCALATION_RECALL',
    )
    model_ops_quality_gate_max_ece: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        alias='MODEL_OPS_QUALITY_GATE_MAX_ECE',
    )
    model_ops_quality_gate_max_abstain_rate: float = Field(
        default=0.35,
        ge=0.0,
        le=1.0,
        alias='MODEL_OPS_QUALITY_GATE_MAX_ABSTAIN_RATE',
    )
    model_ops_quality_gate_min_sample_size: int = Field(
        default=200,
        ge=1,
        alias='MODEL_OPS_QUALITY_GATE_MIN_SAMPLE_SIZE',
    )

    model_guardrail_force_handoff_on_fallback: bool = Field(
        default=True,
        alias='MODEL_GUARDRAIL_FORCE_HANDOFF_ON_FALLBACK',
    )
    model_guardrail_confidence_lower_bound: float = Field(
        default=0.05,
        ge=0.0,
        le=1.0,
        alias='MODEL_GUARDRAIL_CONFIDENCE_LOWER_BOUND',
    )
    model_guardrail_confidence_upper_bound: float = Field(
        default=0.98,
        ge=0.0,
        le=1.0,
        alias='MODEL_GUARDRAIL_CONFIDENCE_UPPER_BOUND',
    )

    evaluation_baseline_days: int = Field(default=14, ge=3, alias='EVALUATION_BASELINE_DAYS')
    drift_input_threshold: float = Field(default=0.30, ge=0.0, alias='DRIFT_INPUT_THRESHOLD')
    drift_confidence_threshold: float = Field(default=0.12, ge=0.0, alias='DRIFT_CONFIDENCE_THRESHOLD')
    drift_outcome_threshold: float = Field(default=0.10, ge=0.0, alias='DRIFT_OUTCOME_THRESHOLD')

    pii_redaction_enabled: bool = Field(default=True, alias='PII_REDACTION_ENABLED')
    use_expanded_taxonomy: bool = Field(default=False, alias='USE_EXPANDED_TAXONOMY')
    retrieval_enable_reranking: bool = Field(default=True, alias='RETRIEVAL_ENABLE_RERANKING')
    retrieval_enable_dedup: bool = Field(default=True, alias='RETRIEVAL_ENABLE_DEDUP')
    retrieval_stale_penalty_days: int = Field(default=180, ge=0, alias='RETRIEVAL_STALE_PENALTY_DAYS')

    # --- Embedding backend ---
    embedding_backend: str = Field(default='local', alias='EMBEDDING_BACKEND')
    embedding_model_name: str = Field(default='all-MiniLM-L6-v2', alias='EMBEDDING_MODEL_NAME')
    embedding_api_url: str = Field(default='', alias='EMBEDDING_API_URL')
    embedding_api_key: str = Field(default='', alias='EMBEDDING_API_KEY')

    # --- Prompt injection defense ---
    prompt_injection_enabled: bool = Field(default=True, alias='PROMPT_INJECTION_ENABLED')
    prompt_injection_block_threshold: float = Field(default=0.7, ge=0.0, le=1.0, alias='PROMPT_INJECTION_BLOCK_THRESHOLD')
    prompt_injection_evidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0, alias='PROMPT_INJECTION_EVIDENCE_THRESHOLD')

    # --- Secrets backend ---
    secrets_backend: str = Field(default='env', alias='SECRETS_BACKEND')
    vault_addr: str = Field(default='', alias='VAULT_ADDR')

    # --- Circuit breaker ---
    circuit_breaker_failure_threshold: int = Field(default=5, ge=1, alias='CIRCUIT_BREAKER_FAILURE_THRESHOLD')
    circuit_breaker_recovery_seconds: float = Field(default=30.0, ge=1.0, alias='CIRCUIT_BREAKER_RECOVERY_SECONDS')
    backpressure_max_concurrent: int = Field(default=50, ge=1, alias='BACKPRESSURE_MAX_CONCURRENT')
    backpressure_timeout_seconds: float = Field(default=5.0, ge=0.1, alias='BACKPRESSURE_TIMEOUT_SECONDS')

    # --- Data retention ---
    data_retention_enabled: bool = Field(default=False, alias='DATA_RETENTION_ENABLED')
    rls_enabled: bool = Field(default=False, alias='RLS_ENABLED')

    event_bus_backend: str = Field(default='noop', alias='EVENT_BUS_BACKEND')
    event_bus_retry_attempts: int = Field(default=3, ge=1, alias='EVENT_BUS_RETRY_ATTEMPTS')
    event_bus_retry_backoff_seconds: float = Field(default=0.25, ge=0.0, alias='EVENT_BUS_RETRY_BACKOFF_SECONDS')

    pubsub_project_id: str = Field(default='', alias='PUBSUB_PROJECT_ID')
    pubsub_topic: str = Field(default='assist-events', alias='PUBSUB_TOPIC')
    pubsub_publish_timeout_seconds: float = Field(default=5.0, ge=0.1, alias='PUBSUB_PUBLISH_TIMEOUT_SECONDS')

    workflow_backend: str = Field(default='noop', alias='WORKFLOW_BACKEND')
    workflow_retry_attempts: int = Field(default=3, ge=1, alias='WORKFLOW_RETRY_ATTEMPTS')
    workflow_retry_backoff_seconds: float = Field(default=0.5, ge=0.0, alias='WORKFLOW_RETRY_BACKOFF_SECONDS')

    temporal_target_host: str = Field(default='localhost:7233', alias='TEMPORAL_TARGET_HOST')
    temporal_namespace: str = Field(default='default', alias='TEMPORAL_NAMESPACE')
    temporal_task_queue: str = Field(default='assist-handoffs', alias='TEMPORAL_TASK_QUEUE')
    temporal_workflow_name: str = Field(default='AssistHandoffWorkflow', alias='TEMPORAL_WORKFLOW_NAME')
    temporal_workflow_retry_attempts: int = Field(default=5, ge=1, alias='TEMPORAL_WORKFLOW_RETRY_ATTEMPTS')
    temporal_workflow_retry_initial_interval_seconds: float = Field(
        default=1.0,
        ge=0.1,
        alias='TEMPORAL_WORKFLOW_RETRY_INITIAL_INTERVAL_SECONDS',
    )

    @model_validator(mode='after')
    def _validate_runtime_guards(self) -> 'Settings':
        jwt_secret = self.jwt_secret_key.strip()
        if self.auth_enabled and not jwt_secret:
            raise ValueError('JWT_SECRET_KEY must be set when AUTH_ENABLED=true.')

        if self.auth_enabled and jwt_secret.lower() in {'change-me-local-dev-secret', 'changeme', 'change-me', 'default'}:
            raise ValueError('JWT_SECRET_KEY cannot use a development default when AUTH_ENABLED=true.')

        if self.routing_model_backend.strip().lower() == 'http' and not self.model_serving_url.strip():
            raise ValueError('MODEL_SERVING_URL is required when ROUTING_MODEL_BACKEND=http.')

        generation_backend = self.generation_backend.strip().lower()
        if generation_backend not in {'template', 'ollama'}:
            raise ValueError('GENERATION_BACKEND must be one of: template, ollama.')

        if generation_backend == 'ollama' and not self.generation_ollama_base_url.strip():
            raise ValueError('GENERATION_OLLAMA_BASE_URL is required when GENERATION_BACKEND=ollama.')

        if self.model_shadow_enabled and self.challenger_routing_model_backend.strip().lower() == 'http':
            if not self.challenger_model_serving_url.strip():
                raise ValueError(
                    'CHALLENGER_MODEL_SERVING_URL is required when CHALLENGER_ROUTING_MODEL_BACKEND=http.',
                )

        if self.canary_rollout_enabled and not self.model_shadow_enabled:
            raise ValueError('MODEL_SHADOW_ENABLED must be true when CANARY_ROLLOUT_ENABLED=true.')

        if self.model_guardrail_confidence_lower_bound >= self.model_guardrail_confidence_upper_bound:
            raise ValueError(
                'MODEL_GUARDRAIL_CONFIDENCE_LOWER_BOUND must be smaller than MODEL_GUARDRAIL_CONFIDENCE_UPPER_BOUND.',
            )

        if self.event_bus_backend.strip().lower() == 'pubsub' and not self.pubsub_project_id.strip():
            raise ValueError('PUBSUB_PROJECT_ID is required when EVENT_BUS_BACKEND=pubsub.')

        if self.workflow_backend.strip().lower() == 'temporal' and not self.temporal_target_host.strip():
            raise ValueError('TEMPORAL_TARGET_HOST is required when WORKFLOW_BACKEND=temporal.')

        if self.rate_limit_enabled and not self.use_redis:
            raise ValueError('USE_REDIS must be true when RATE_LIMIT_ENABLED=true.')

        # ── Production-environment hardening guards ─────────────────────
        if self.app_env.strip().lower() == 'production':
            _INSECURE_DSN_PASSWORDS = {'postgres', 'password', 'changeme', 'test', ''}
            dsn_lower = self.postgres_dsn.lower()
            for weak_pw in _INSECURE_DSN_PASSWORDS:
                if f':{weak_pw}@' in dsn_lower:
                    raise ValueError(
                        f'POSTGRES_DSN contains an insecure password ("{weak_pw}") in production. '
                        'Use a strong, rotated credential via Vault/KMS.'
                    )

            if self.embedding_backend.strip().lower() == 'local':
                raise ValueError(
                    'EMBEDDING_BACKEND=local (hash embeddings) is not suitable for production. '
                    'Set EMBEDDING_BACKEND=sentence-transformer or EMBEDDING_BACKEND=api.'
                )

            if not self.auth_enabled:
                raise ValueError('AUTH_ENABLED must be true in production.')

            if not self.use_postgres:
                raise ValueError('USE_POSTGRES must be true in production.')

            if not self.rate_limit_enabled:
                raise ValueError('RATE_LIMIT_ENABLED must be true in production.')

            if not self.pii_redaction_enabled:
                raise ValueError('PII_REDACTION_ENABLED must be true in production.')

            if not self.metrics_enabled:
                raise ValueError('METRICS_ENABLED must be true in production.')

            _LOCALHOST_PATTERNS = {'localhost', '127.0.0.1', '0.0.0.0'}
            if self.secrets_backend.strip().lower() == 'vault' and not self.vault_addr.strip():
                raise ValueError('VAULT_ADDR is required when SECRETS_BACKEND=vault.')

        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
