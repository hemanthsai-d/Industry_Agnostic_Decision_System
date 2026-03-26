from __future__ import annotations

import pytest

from app.core.config import Settings
from app.integrations.event_bus import EventMessage, RetryingEventBus
from app.integrations.workflow import RetryingHandoffWorkflowEngine
from app.models.schemas import DecideRequest, HandoffPayload
from app.services.generation import GenerationService
from app.services.handoff import HandoffService
from app.services.orchestrator import DecisionOrchestrator
from app.services.policy import PolicyService
from app.services.retrieval import RetrievalService
from app.services.routing import RoutingService


class SpyEventBus:
    def __init__(self) -> None:
        self.events: list[EventMessage] = []

    async def publish(self, event: EventMessage) -> None:
        self.events.append(event)


class SpyWorkflowEngine:
    def __init__(self) -> None:
        self.calls = []

    async def start_handoff(self, *, tenant_id: str, request_id: str, trace_id: str, handoff_payload: HandoffPayload):
        self.calls.append((tenant_id, request_id, trace_id, handoff_payload))
        return f'wf-{handoff_payload.handoff_id}'


class FlakyEventBus:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.attempts = 0

    async def publish(self, event: EventMessage) -> None:
        self.attempts += 1
        if self.attempts <= self.failures_before_success:
            raise RuntimeError('transient event bus failure')


class FlakyWorkflowEngine:
    def __init__(self, failures_before_success: int) -> None:
        self.failures_before_success = failures_before_success
        self.attempts = 0

    async def start_handoff(
        self,
        *,
        tenant_id: str,
        request_id: str,
        trace_id: str,
        handoff_payload: HandoffPayload,
    ) -> str | None:
        self.attempts += 1
        if self.attempts <= self.failures_before_success:
            raise RuntimeError('transient workflow start failure')
        return f'workflow-{handoff_payload.handoff_id}'


@pytest.mark.asyncio
async def test_orchestrator_publishes_events_and_starts_handoff_workflow():
    settings = Settings(
        APP_NAME='test',
        APP_ENV='test',
        USE_OPA=False,
        BASE_CONFIDENCE_THRESHOLD=0.60,
        MAX_AUTO_ESCALATION_PROB=0.55,
    )
    event_bus = SpyEventBus()
    workflow_engine = SpyWorkflowEngine()

    orchestrator = DecisionOrchestrator(
        retrieval_service=RetrievalService(),
        routing_service=RoutingService(),
        policy_service=PolicyService(settings=settings),
        generation_service=GenerationService(),
        handoff_service=HandoffService(),
        event_bus=event_bus,
        workflow_engine=workflow_engine,
    )

    req = DecideRequest(
        tenant_id='org_demo',
        section='billing',
        issue_text='Customer threatens legal lawsuit over fraud and security breach.',
    )
    res = await orchestrator.decide(req)

    assert res.handoff_payload is not None
    assert len(workflow_engine.calls) == 1

    assert len(event_bus.events) == 2
    assert event_bus.events[0].event_type == 'assist.inference.completed'
    assert event_bus.events[1].event_type == 'assist.handoff.created'
    assert event_bus.events[0].payload['handoff_created'] is True
    assert event_bus.events[0].payload['workflow_id'] is not None


@pytest.mark.asyncio
async def test_retrying_event_bus_retries_before_success():
    flaky = FlakyEventBus(failures_before_success=1)
    bus = RetryingEventBus(delegate=flaky, retry_attempts=3, retry_backoff_seconds=0.0)

    await bus.publish(
        EventMessage(
            event_type='assist.inference.completed',
            tenant_id='org_demo',
            request_id='rq_1',
            trace_id='trace_1',
            payload={'ok': True},
        )
    )

    assert flaky.attempts == 2


@pytest.mark.asyncio
async def test_retrying_workflow_engine_retries_before_success():
    flaky = FlakyWorkflowEngine(failures_before_success=1)
    workflow = RetryingHandoffWorkflowEngine(delegate=flaky, retry_attempts=3, retry_backoff_seconds=0.0)

    handoff_payload = HandoffPayload(
        handoff_id='hf_1',
        reason_codes=['low_confidence'],
        summary='manual review needed',
        evidence_pack=[],
        route_probs=[],
        escalation_prob=0.72,
    )

    workflow_id = await workflow.start_handoff(
        tenant_id='org_demo',
        request_id='rq_1',
        trace_id='trace_1',
        handoff_payload=handoff_payload,
    )

    assert workflow_id == 'workflow-hf_1'
    assert flaky.attempts == 2
