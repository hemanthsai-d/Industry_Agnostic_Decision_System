from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.schemas import DecideRequest, DecisionType, EvidenceChunk, ResolutionProb
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.orchestrator import DecisionOrchestrator
from app.services.policy import PolicyService
from app.services.retrieval import RetrievalService


class FixedRoutingService:
    def __init__(
        self,
        *,
        top_label: str,
        top_prob: float,
        escalation_prob: float,
        used_fallback: bool = False,
    ) -> None:
        self._top_label = top_label
        self._top_prob = top_prob
        self._escalation_prob = escalation_prob
        self._used_fallback = used_fallback

    def predict_with_metadata(self, issue_text: str, evidence_pack: list[EvidenceChunk]):
        probs = [
            ResolutionProb(label=self._top_label, prob=self._top_prob),
            ResolutionProb(label='general_support_triage', prob=max(0.0, 1.0 - self._top_prob)),
        ]
        return probs, self._escalation_prob, 0.1, 0.02, {'used_fallback': self._used_fallback}


class SpyModelOpsStore:
    def __init__(self, canary_percent: int = 0) -> None:
        self.persist_calls = []
        self._canary_percent = canary_percent

    def persist_shadow_prediction(self, **kwargs) -> None:
        self.persist_calls.append(kwargs)

    class _Config:
        def __init__(self, canary_percent: int) -> None:
            self.canary_percent = canary_percent

    def get_rollout_config(self):
        return self._Config(canary_percent=self._canary_percent)


def _settings() -> Settings:
    return Settings(
        APP_NAME='test',
        APP_ENV='test',
        USE_OPA=False,
        BASE_CONFIDENCE_THRESHOLD=0.60,
        MAX_AUTO_ESCALATION_PROB=0.55,
    )


@pytest.mark.asyncio
async def test_shadow_predictions_logged_without_affecting_primary_decision():
    settings = _settings()
    model_ops = SpyModelOpsStore(canary_percent=0)

    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=FixedRoutingService(
            top_label='refund_duplicate_charge',
            top_prob=0.92,
            escalation_prob=0.12,
        ),
        shadow_routing_service=FixedRoutingService(
            top_label='technical_bug_triage',
            top_prob=0.88,
            escalation_prob=0.30,
        ),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        model_ops_store=model_ops,
        canary_rollout_enabled=False,
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer was charged twice and asks for refund.',
    )
    res = await orchestrator.decide(req)

    assert res.model_variant == 'primary'
    assert model_ops.persist_calls
    assert model_ops.persist_calls[0]['traffic_bucket'] == 'shadow'


@pytest.mark.asyncio
async def test_canary_traffic_uses_challenger_variant_when_bucket_selected():
    settings = _settings()
    model_ops = SpyModelOpsStore(canary_percent=100)

    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=FixedRoutingService(
            top_label='refund_duplicate_charge',
            top_prob=0.93,
            escalation_prob=0.10,
        ),
        shadow_routing_service=FixedRoutingService(
            top_label='technical_bug_triage',
            top_prob=0.91,
            escalation_prob=0.11,
        ),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        model_ops_store=model_ops,
        canary_rollout_enabled=True,
        canary_traffic_percent=100,
        rollout_from_db=False,
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='App is crashing while applying refund.',
    )
    res = await orchestrator.decide(req)

    assert res.model_variant == 'challenger'
    assert res.resolution_path_probs[0].label == 'technical_bug_triage'
    assert model_ops.persist_calls
    assert model_ops.persist_calls[0]['traffic_bucket'] == 'canary'


@pytest.mark.asyncio
async def test_guardrail_forces_handoff_when_model_backend_falls_back():
    settings = _settings()
    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=FixedRoutingService(
            top_label='refund_duplicate_charge',
            top_prob=0.94,
            escalation_prob=0.05,
            used_fallback=True,
        ),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        model_guardrail_force_handoff_on_fallback=True,
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer charged twice.',
    )
    res = await orchestrator.decide(req)

    assert res.decision == DecisionType.escalate
    assert res.handoff_payload is not None
    assert 'model_backend_fallback' in res.policy_result.reason_codes
