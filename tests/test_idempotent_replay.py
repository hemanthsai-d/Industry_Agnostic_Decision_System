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


class ReplayInferenceStore:
    def __init__(self, cached_response):
        self._cached_response = cached_response
        self.fetch_calls = 0
        self.persist_calls = 0

    def fetch(self, req):
        self.fetch_calls += 1
        return self._cached_response

    def persist(self, req, res):
        self.persist_calls += 1


class MissInferenceStore:
    def __init__(self):
        self.fetch_calls = 0
        self.persist_calls = 0

    def fetch(self, req):
        self.fetch_calls += 1
        return None

    def persist(self, req, res):
        self.persist_calls += 1


class FailingRetrievalService:
    def retrieve(self, tenant_id: str, issue_text: str, section: str | None = None, top_k: int = 5):
        raise AssertionError('Retrieval should not run when idempotent cache replay succeeds.')


def _settings() -> Settings:
    return Settings(
        APP_NAME='test',
        APP_ENV='test',
        USE_OPA=False,
        BASE_CONFIDENCE_THRESHOLD=0.60,
        MAX_AUTO_ESCALATION_PROB=0.55,
    )


@pytest.mark.asyncio
async def test_orchestrator_replays_cached_result_without_recompute():
    settings = _settings()
    req = DecideRequest(
        request_id='rq_idempotent_replay',
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer charged twice and asks for refund.',
    )

    seed_orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
    )
    cached_response = await seed_orchestrator.decide(req)
    replay_store = ReplayInferenceStore(cached_response)

    replay_orchestrator = DecisionOrchestrator(
        retrieval_service=FailingRetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        inference_store=replay_store,
    )

    replayed = await replay_orchestrator.decide(req)
    assert replayed.model_dump(mode='json') == cached_response.model_dump(mode='json')
    assert replay_store.fetch_calls == 1
    assert replay_store.persist_calls == 0


@pytest.mark.asyncio
async def test_orchestrator_computes_and_persists_on_cache_miss():
    settings = _settings()
    miss_store = MissInferenceStore()
    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        inference_store=miss_store,
    )

    req = DecideRequest(
        request_id='rq_idempotent_miss',
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer charged twice and asks for refund.',
    )
    res = await orchestrator.decide(req)

    assert res.request_id == req.request_id
    assert miss_store.fetch_calls == 1
    assert miss_store.persist_calls == 1
