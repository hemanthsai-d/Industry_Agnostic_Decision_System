from __future__ import annotations

import pytest

from app.models.schemas import DecideRequest, DecisionType, PolicyResult
from app.services.generation import GenerationResult
from app.services.handoff import HandoffService
from app.services.orchestrator import DecisionOrchestrator
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService


class RecommendPolicyService:
    async def evaluate(self, **kwargs):
        return PolicyResult(
            allow_auto_response=True,
            final_decision=DecisionType.recommend,
            reason_codes=[],
        )


class SpyGenerationService:
    def __init__(self, result: GenerationResult) -> None:
        self.result = result
        self.last_context = None

    def build_grounded_response(self, issue_text, route_probs, evidence_pack, context=None):
        self.last_context = context
        return self.result


@pytest.mark.asyncio
async def test_orchestrator_uses_generation_text_and_context() -> None:
    generation = SpyGenerationService(
        GenerationResult(text='Custom response [billing_001]', ok=True, backend='custom')
    )
    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=RecommendPolicyService(),
        generation_service=generation,
        handoff_service=HandoffService(),
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer charged twice and asks for a refund',
        context={'customer_name': 'Asha'},
    )
    res = await orchestrator.decide(req)

    assert res.decision == DecisionType.recommend
    assert isinstance(res.draft_response, str)
    assert 'Custom response' in (res.draft_response or '')
    assert generation.last_context == req.context


@pytest.mark.asyncio
async def test_orchestrator_escalates_when_generation_fails() -> None:
    generation = SpyGenerationService(
        GenerationResult(text=None, ok=False, reason_code='generation_backend_unavailable', backend='custom')
    )
    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=RecommendPolicyService(),
        generation_service=generation,
        handoff_service=HandoffService(),
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer charged twice and asks for a refund',
        context={'customer_name': 'Asha'},
    )
    res = await orchestrator.decide(req)

    assert res.decision == DecisionType.escalate
    assert res.handoff_payload is not None
    assert 'generation_backend_unavailable' in res.policy_result.reason_codes
