from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.schemas import DecideRequest, DecisionType
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.orchestrator import DecisionOrchestrator
from app.services.policy import PolicyService
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService


def build_orchestrator() -> DecisionOrchestrator:
    settings = Settings(
        APP_NAME="test",
        APP_ENV="test",
        USE_OPA=False,
        BASE_CONFIDENCE_THRESHOLD=0.60,
        MAX_AUTO_ESCALATION_PROB=0.55,
    )
    return DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
    )


@pytest.mark.asyncio
async def test_recommend_duplicate_charge():
    orchestrator = build_orchestrator()
    req = DecideRequest(
        tenant_id="org_demo",
        section="billing",
        issue_text="Customer was charged twice and asks for a refund.",
    )
    res = await orchestrator.decide(req)
    assert res.decision in {DecisionType.recommend, DecisionType.abstain}
    if res.decision == DecisionType.recommend:
        assert res.draft_response is not None
        assert "[" in res.draft_response


@pytest.mark.asyncio
async def test_escalate_high_risk():
    orchestrator = build_orchestrator()
    req = DecideRequest(
        tenant_id="org_demo",
        section="billing",
        issue_text="Customer threatens legal lawsuit over fraud and security breach.",
    )
    res = await orchestrator.decide(req)
    assert res.decision == DecisionType.escalate
    assert res.handoff_payload is not None

