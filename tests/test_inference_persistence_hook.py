from __future__ import annotations

import pytest

from app.core.config import Settings
from app.models.schemas import DecideRequest
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.orchestrator import DecisionOrchestrator
from app.services.policy import PolicyService
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService


class SpyInferenceStore:
    def __init__(self) -> None:
        self.calls = []

    def persist(self, req, res) -> None:
        self.calls.append((req, res))


@pytest.mark.asyncio
async def test_orchestrator_persists_decision_result():
    settings = Settings(
        APP_NAME="test",
        APP_ENV="test",
        USE_OPA=False,
        BASE_CONFIDENCE_THRESHOLD=0.60,
        MAX_AUTO_ESCALATION_PROB=0.55,
    )
    spy = SpyInferenceStore()
    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        inference_store=spy,
    )
    req = DecideRequest(
        tenant_id="org_demo",
        section="billing",
        issue_text="Customer was charged twice and requests a refund.",
    )
    res = await orchestrator.decide(req)
    assert len(spy.calls) == 1
    persisted_req, persisted_res = spy.calls[0]
    assert persisted_req.request_id == req.request_id
    assert persisted_res.request_id == res.request_id

