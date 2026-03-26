from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from uuid import uuid4

from app.integrations.event_bus import EventBus, EventMessage
from app.integrations.workflow import HandoffWorkflowEngine
from app.models.schemas import ConfidenceBreakdown, DecideRequest, DecideResponse, DecisionType, PolicyResult
from app.observability.metrics import (
    observe_decision,
    observe_decision_cache_hit,
    observe_decision_confidence,
    observe_handoff,
    observe_injection_detection,
    observe_issue_text_tokens,
    observe_model_guardrail_fallback,
    observe_pipeline_stage,
    observe_pipeline_total,
    observe_rag_citation_coverage,
    observe_rag_faithfulness,
    observe_rag_hallucination,
    observe_request_cost,
    observe_retrieval_evidence_score,
    observe_shadow_prediction,
    track_inflight,
)
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.policy import PolicyService
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService
from app.storage.inference_store import InferenceStore
from app.storage.model_ops_store import ModelOpsStore
from app.utils.confidence import compute_evidence_score, compute_final_confidence
from app.utils.pii_redaction import redact_pii
from app.security.prompt_injection import scan_for_injection
from app.security.output_validation import validate_and_sanitize
from app.utils.rag_eval import compute_generation_quality

logger = logging.getLogger(__name__)


class DecisionOrchestrator:
    def __init__(
        self,
        retrieval_service: RetrievalService,
        routing_service: RoutingService,
        policy_service: PolicyService,
        generation_service: GenerationService,
        handoff_service: HandoffService,
        inference_store: InferenceStore | None = None,
        event_bus: EventBus | None = None,
        workflow_engine: HandoffWorkflowEngine | None = None,
        shadow_routing_service: RoutingService | None = None,
        model_ops_store: ModelOpsStore | None = None,
        canary_rollout_enabled: bool = False,
        canary_traffic_percent: int = 0,
        rollout_from_db: bool = True,
        challenger_model_name: str = 'challenger-routing',
        challenger_model_version: str = 'v1',
        model_guardrail_force_handoff_on_fallback: bool = True,
        model_guardrail_confidence_lower_bound: float = 0.05,
        model_guardrail_confidence_upper_bound: float = 0.98,
        pii_redaction_enabled: bool = True,
    ) -> None:
        self.retrieval_service = retrieval_service
        self.routing_service = routing_service
        self.policy_service = policy_service
        self.generation_service = generation_service
        self.handoff_service = handoff_service
        self.inference_store = inference_store
        self.event_bus = event_bus
        self.workflow_engine = workflow_engine
        self.shadow_routing_service = shadow_routing_service
        self.model_ops_store = model_ops_store

        self.canary_rollout_enabled = bool(canary_rollout_enabled)
        self.canary_traffic_percent = max(0, min(100, int(canary_traffic_percent)))
        self.rollout_from_db = bool(rollout_from_db)
        self.challenger_model_name = challenger_model_name
        self.challenger_model_version = challenger_model_version

        self.model_guardrail_force_handoff_on_fallback = bool(model_guardrail_force_handoff_on_fallback)
        self.model_guardrail_confidence_lower_bound = max(0.0, min(1.0, float(model_guardrail_confidence_lower_bound)))
        self.model_guardrail_confidence_upper_bound = max(0.0, min(1.0, float(model_guardrail_confidence_upper_bound)))
        self.pii_redaction_enabled = bool(pii_redaction_enabled)

        self._rollout_cache_percent = self.canary_traffic_percent
        self._rollout_cache_updated_at = 0.0
        self._rollout_cache_ttl_seconds = 15.0

    async def decide(self, req: DecideRequest) -> DecideResponse:
        pipeline_start = time.monotonic()
        track_inflight(1)
        try:
            return await self._decide_impl(req, pipeline_start)
        finally:
            track_inflight(-1)
            observe_pipeline_total(time.monotonic() - pipeline_start)

    async def _decide_impl(self, req: DecideRequest, pipeline_start: float) -> DecideResponse:
        observe_issue_text_tokens(req.issue_text)

        pii_redacted = False
        if self.pii_redaction_enabled:
            t0 = time.monotonic()
            redaction = redact_pii(req.issue_text)
            observe_pipeline_stage('pii_redaction', time.monotonic() - t0)
            if redaction.redacted_count > 0:
                logger.info(
                    'PII redacted from issue text.',
                    extra={
                        'tenant_id': req.tenant_id,
                        'request_id': req.request_id,
                        'redacted_count': redaction.redacted_count,
                        'entity_types': list(redaction.entity_types),
                    },
                )
                pii_redacted = True

        # --- Prompt injection defense ---
        t0 = time.monotonic()
        injection_scan = scan_for_injection(req.issue_text)
        observe_pipeline_stage('injection_scan', time.monotonic() - t0)
        if injection_scan.risk_score >= 0.7:
            observe_injection_detection('user_input', 'blocked')
            logger.warning(
                'High-risk prompt injection detected — forcing escalation.',
                extra={
                    'tenant_id': req.tenant_id,
                    'request_id': req.request_id,
                    'risk_score': injection_scan.risk_score,
                    'triggered_rules': injection_scan.triggered_rules,
                },
            )

        cached_response = await self._load_cached_response(req)
        if cached_response is not None:
            observe_decision_cache_hit()
            observe_decision(cached_response.decision.value)
            observe_decision_confidence(
                confidence=float(cached_response.confidence.final),
                model_variant=cached_response.model_variant,
            )
            if cached_response.handoff_payload is not None:
                observe_handoff(workflow_started=True)
            return cached_response

        t0 = time.monotonic()
        evidence_pack = await asyncio.to_thread(
            self.retrieval_service.retrieve,
            req.tenant_id,
            req.issue_text,
            req.section,
            req.max_evidence_chunks,
        )
        observe_pipeline_stage('retrieval', time.monotonic() - t0)
        if evidence_pack:
            mean_ev_score = sum(e.score for e in evidence_pack) / len(evidence_pack)
            observe_retrieval_evidence_score(mean_ev_score)

        # --- Scan evidence for indirect prompt injection ---
        t0 = time.monotonic()
        for evi in evidence_pack:
            evi_scan = scan_for_injection(evi.text)
            if evi_scan.risk_score >= 0.5:
                observe_injection_detection('evidence_chunk', 'filtered')
                logger.warning(
                    'Indirect prompt injection in evidence — filtering chunk.',
                    extra={'chunk_id': evi.chunk_id, 'risk_score': evi_scan.risk_score},
                )
        evidence_pack = [
            e for e in evidence_pack
            if scan_for_injection(e.text).risk_score < 0.5
        ]
        observe_pipeline_stage('evidence_injection_filter', time.monotonic() - t0)

        t0 = time.monotonic()
        primary_route_probs, primary_escalation_prob, primary_ood_score, primary_contradiction_score, primary_meta = (
            self.routing_service.predict_with_metadata(
                issue_text=req.issue_text,
                evidence_pack=evidence_pack,
            )
        )
        observe_pipeline_stage('routing', time.monotonic() - t0)
        primary_confidence = self._build_confidence(
            route_probs=primary_route_probs,
            escalation_prob=primary_escalation_prob,
            ood_score=primary_ood_score,
            contradiction_score=primary_contradiction_score,
            evidence_pack=evidence_pack,
        )

        selected_model_variant = 'primary'
        selected_meta = dict(primary_meta)
        route_probs = primary_route_probs
        escalation_prob = primary_escalation_prob
        confidence = primary_confidence

        if self.shadow_routing_service is not None:
            shadow_route_probs, shadow_escalation_prob, shadow_ood_score, shadow_contradiction_score, shadow_meta = (
                self.shadow_routing_service.predict_with_metadata(
                    issue_text=req.issue_text,
                    evidence_pack=evidence_pack,
                )
            )
            shadow_confidence = self._build_confidence(
                route_probs=shadow_route_probs,
                escalation_prob=shadow_escalation_prob,
                ood_score=shadow_ood_score,
                contradiction_score=shadow_contradiction_score,
                evidence_pack=evidence_pack,
            )

            canary_percent = await self._resolve_canary_percent()
            is_canary = self._request_in_canary_bucket(req=req, canary_percent=canary_percent)
            traffic_bucket = 'canary' if is_canary else 'shadow'

            observe_shadow_prediction(model_variant='challenger', traffic_bucket=traffic_bucket)
            await self._persist_shadow_prediction(
                req=req,
                route_probs=shadow_route_probs,
                escalation_prob=shadow_escalation_prob,
                final_confidence=shadow_confidence.final,
                decision=None,
                model_backend_fallback=bool(shadow_meta.get('used_fallback', False)),
                traffic_bucket=traffic_bucket,
                metadata={
                    'ood_score': float(shadow_ood_score),
                    'contradiction_score': float(shadow_contradiction_score),
                },
            )

            if is_canary:
                selected_model_variant = 'challenger'
                selected_meta = dict(shadow_meta)
                route_probs = shadow_route_probs
                escalation_prob = shadow_escalation_prob
                confidence = shadow_confidence

        policy_result = await self.policy_service.evaluate(
            issue_text=req.issue_text,
            risk_level=req.risk_level,
            final_confidence=confidence.final,
            escalation_prob=escalation_prob,
        )

        guardrail_reasons = self._guardrail_reasons(
            used_model_fallback=bool(selected_meta.get('used_fallback', False)),
            final_confidence=float(confidence.final),
        )
        if guardrail_reasons:
            merged_reason_codes = list(policy_result.reason_codes)
            for reason in guardrail_reasons:
                if reason not in merged_reason_codes:
                    merged_reason_codes.append(reason)
                observe_model_guardrail_fallback(reason=reason, model_variant=selected_model_variant)
            policy_result = PolicyResult(
                allow_auto_response=False,
                final_decision=DecisionType.escalate,
                reason_codes=merged_reason_codes,
            )

        trace_id = str(uuid4()).replace('-', '')[:16]
        decision = policy_result.final_decision

        draft_response = None
        handoff_payload = None
        workflow_id = None

        if decision == DecisionType.recommend and policy_result.allow_auto_response:
            t0 = time.monotonic()
            generation_result = self.generation_service.build_grounded_response(
                issue_text=req.issue_text,
                route_probs=route_probs,
                evidence_pack=evidence_pack,
                context=req.context,
            )
            if generation_result.ok and generation_result.text:
                observe_pipeline_stage('generation', time.monotonic() - t0)
                draft_response = generation_result.text
                # --- RAG quality metrics (logged + observed) ---
                try:
                    rag_quality = compute_generation_quality(
                        answer=draft_response,
                        query=req.issue_text,
                        evidence_texts=[e.text for e in evidence_pack],
                    )
                    observe_rag_faithfulness(rag_quality.faithfulness)
                    observe_rag_hallucination(rag_quality.hallucination_ratio)
                    observe_rag_citation_coverage(rag_quality.citation_coverage)
                    logger.info(
                        'RAG generation quality metrics.',
                        extra={
                            'tenant_id': req.tenant_id,
                            'request_id': req.request_id,
                            'faithfulness': rag_quality.faithfulness,
                            'relevance': rag_quality.relevance,
                            'citation_coverage': rag_quality.citation_coverage,
                            'hallucination_ratio': rag_quality.hallucination_ratio,
                        },
                    )
                except Exception:
                    logger.debug('RAG quality metrics computation skipped.')
                # --- Output validation: schema + PII re-check ---
                sanitized, output_violations = validate_and_sanitize(
                    draft_response, require_citations=True,
                )
                if output_violations:
                    logger.warning(
                        'Output validation violations.',
                        extra={
                            'request_id': req.request_id,
                            'violations': output_violations,
                        },
                    )
                    draft_response = sanitized
            else:
                decision = DecisionType.escalate
                merged_reason_codes = list(policy_result.reason_codes)
                generation_reason = generation_result.reason_code or 'generation_unavailable'
                if generation_reason not in merged_reason_codes:
                    merged_reason_codes.append(generation_reason)
                policy_result = PolicyResult(
                    allow_auto_response=False,
                    final_decision=DecisionType.escalate,
                    reason_codes=merged_reason_codes,
                )
                handoff_payload = self.handoff_service.build_payload(
                    issue_text=req.issue_text,
                    reason_codes=policy_result.reason_codes,
                    evidence_pack=evidence_pack,
                    route_probs=route_probs,
                    escalation_prob=escalation_prob,
                )
                workflow_id = await self._start_handoff_workflow(req, trace_id, handoff_payload)
        else:
            if decision == DecisionType.abstain and escalation_prob > 0.8:
                decision = DecisionType.escalate
            handoff_payload = self.handoff_service.build_payload(
                issue_text=req.issue_text,
                reason_codes=policy_result.reason_codes,
                evidence_pack=evidence_pack,
                route_probs=route_probs,
                escalation_prob=escalation_prob,
            )
            workflow_id = await self._start_handoff_workflow(req, trace_id, handoff_payload)

        _detected_intents = selected_meta.get('detected_intents') or []
        _top_intent = _detected_intents[0][0] if _detected_intents else None
        _detected_category = selected_meta.get('detected_category') or None

        response = DecideResponse(
            decision=decision,
            resolution_path_probs=route_probs,
            escalation_prob=escalation_prob,
            confidence=confidence,
            evidence_pack=evidence_pack,
            draft_response=draft_response,
            policy_result=policy_result,
            handoff_payload=handoff_payload,
            trace_id=trace_id,
            request_id=req.request_id,
            model_variant=selected_model_variant,
            model_backend_fallback=bool(selected_meta.get('used_fallback', False)),
            detected_intent=_top_intent,
            detected_category=_detected_category,
            pii_redacted=pii_redacted,
        )
        if self.inference_store is not None:
            await asyncio.to_thread(self.inference_store.persist, req, response)

        observe_decision(response.decision.value)
        observe_decision_confidence(confidence=float(response.confidence.final), model_variant=response.model_variant)
        if response.handoff_payload is not None:
            observe_handoff(workflow_started=workflow_id is not None)

        # --- Cost estimation per request ---
        gen_backend = 'template'
        cost_usd = 0.0
        if draft_response:
            gen_backend = selected_meta.get('generation_backend', 'template')
            token_count = len(draft_response.split())
            if gen_backend == 'ollama':
                cost_usd = token_count * 0.000002  # ~$0.002/1k output tokens self-hosted
            else:
                cost_usd = 0.0  # template is free
        cost_usd += 0.00005  # base infra cost (retrieval + routing + network)
        observe_request_cost(cost_usd, generation_backend=gen_backend)

        await self._publish_events(req, response, workflow_id)
        return response

    def _build_confidence(
        self,
        *,
        route_probs,
        escalation_prob: float,
        ood_score: float,
        contradiction_score: float,
        evidence_pack,
    ) -> ConfidenceBreakdown:
        route_conf = route_probs[0].prob if route_probs else 0.0
        evidence_score = compute_evidence_score([e.score for e in evidence_pack])
        final_conf = compute_final_confidence(
            route_conf=route_conf,
            evidence_score=evidence_score,
            escalation_prob=escalation_prob,
            ood_score=ood_score,
            contradiction_score=contradiction_score,
        )
        return ConfidenceBreakdown(
            final=final_conf,
            route_conf=route_conf,
            evidence_score=evidence_score,
            ood_score=ood_score,
            contradiction_score=contradiction_score,
        )

    async def _load_cached_response(self, req: DecideRequest) -> DecideResponse | None:
        if self.inference_store is None:
            return None

        fetch_fn = getattr(self.inference_store, 'fetch', None)
        if not callable(fetch_fn):
            return None

        try:
            return await asyncio.to_thread(fetch_fn, req)
        except Exception:
            logger.exception(
                'Failed to load cached response.',
                extra={'tenant_id': req.tenant_id, 'request_id': req.request_id},
            )
            return None

    async def _resolve_canary_percent(self) -> int:
        if not self.canary_rollout_enabled:
            return 0

        if not self.rollout_from_db or self.model_ops_store is None:
            return self.canary_traffic_percent

        now = time.monotonic()
        if (now - self._rollout_cache_updated_at) <= self._rollout_cache_ttl_seconds:
            return self._rollout_cache_percent

        get_rollout_config = getattr(self.model_ops_store, 'get_rollout_config', None)
        if not callable(get_rollout_config):
            return self.canary_traffic_percent

        try:
            config = await asyncio.to_thread(get_rollout_config)
            self._rollout_cache_percent = max(0, min(100, int(config.canary_percent)))
            self._rollout_cache_updated_at = now
            return self._rollout_cache_percent
        except Exception:
            logger.exception('Failed to resolve canary rollout percentage from model ops store.')
            return self.canary_traffic_percent

    def _request_in_canary_bucket(self, req: DecideRequest, canary_percent: int) -> bool:
        safe_percent = max(0, min(100, int(canary_percent)))
        if safe_percent <= 0:
            return False
        if safe_percent >= 100:
            return True

        key = f'{req.tenant_id}:{req.request_id}'
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()
        bucket = int(digest[:8], 16) % 100
        return bucket < safe_percent

    def _guardrail_reasons(self, *, used_model_fallback: bool, final_confidence: float) -> list[str]:
        reasons: list[str] = []
        if self.model_guardrail_force_handoff_on_fallback and used_model_fallback:
            reasons.append('model_backend_fallback')

        if (
            final_confidence < self.model_guardrail_confidence_lower_bound
            or final_confidence > self.model_guardrail_confidence_upper_bound
        ):
            reasons.append('confidence_out_of_band')
        return reasons

    async def _persist_shadow_prediction(
        self,
        *,
        req: DecideRequest,
        route_probs,
        escalation_prob: float,
        final_confidence: float,
        decision: DecisionType | None,
        model_backend_fallback: bool,
        traffic_bucket: str,
        metadata: dict,
    ) -> None:
        if self.model_ops_store is None:
            return

        persist_fn = getattr(self.model_ops_store, 'persist_shadow_prediction', None)
        if not callable(persist_fn):
            return

        try:
            await asyncio.to_thread(
                persist_fn,
                request_id=req.request_id,
                tenant_id=req.tenant_id,
                model_name=self.challenger_model_name,
                model_version=self.challenger_model_version,
                model_variant='challenger',
                traffic_bucket=traffic_bucket,
                route_probabilities=route_probs,
                escalation_prob=escalation_prob,
                final_confidence=final_confidence,
                decision=decision,
                model_backend_fallback=model_backend_fallback,
                metadata=metadata,
            )
        except Exception:
            logger.exception(
                'Failed to persist shadow prediction.',
                extra={'tenant_id': req.tenant_id, 'request_id': req.request_id},
            )

    async def _start_handoff_workflow(self, req: DecideRequest, trace_id: str, handoff_payload) -> str | None:
        if self.workflow_engine is None:
            return None
        try:
            return await self.workflow_engine.start_handoff(
                tenant_id=req.tenant_id,
                request_id=req.request_id,
                trace_id=trace_id,
                handoff_payload=handoff_payload,
            )
        except Exception:
            logger.exception(
                'Failed to start handoff workflow',
                extra={
                    'tenant_id': req.tenant_id,
                    'request_id': req.request_id,
                    'trace_id': trace_id,
                },
            )
            return None

    async def _publish_events(self, req: DecideRequest, res: DecideResponse, workflow_id: str | None) -> None:
        if self.event_bus is None:
            return

        inference_event = EventMessage(
            event_type='assist.inference.completed',
            tenant_id=req.tenant_id,
            request_id=req.request_id,
            trace_id=res.trace_id,
            payload={
                'decision': res.decision.value,
                'escalation_prob': float(res.escalation_prob),
                'final_confidence': float(res.confidence.final),
                'top_resolution_path': (
                    res.resolution_path_probs[0].label if res.resolution_path_probs else None
                ),
                'top_resolution_prob': (
                    float(res.resolution_path_probs[0].prob) if res.resolution_path_probs else None
                ),
                'handoff_created': res.handoff_payload is not None,
                'workflow_id': workflow_id,
                'model_variant': res.model_variant,
                'model_backend_fallback': bool(res.model_backend_fallback),
            },
        )
        await self._safe_publish(inference_event)

        if res.handoff_payload is not None:
            handoff_event = EventMessage(
                event_type='assist.handoff.created',
                tenant_id=req.tenant_id,
                request_id=req.request_id,
                trace_id=res.trace_id,
                payload={
                    'workflow_id': workflow_id,
                    'handoff': res.handoff_payload.model_dump(mode='json'),
                    'model_variant': res.model_variant,
                },
            )
            await self._safe_publish(handoff_event)

    async def _safe_publish(self, event: EventMessage) -> None:
        if self.event_bus is None:
            return
        try:
            await self.event_bus.publish(event)
        except Exception:
            logger.exception(
                'Failed to publish event',
                extra={
                    'event_type': event.event_type,
                    'tenant_id': event.tenant_id,
                    'request_id': event.request_id,
                    'trace_id': event.trace_id,
                },
            )
