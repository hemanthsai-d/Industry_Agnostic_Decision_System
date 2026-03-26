from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.api.deps import get_handoff_store
from app.core.config import Settings
from app.main import app
from app.security.auth import AuthService
from app.security.deps import get_auth_service


def _no_auth_service():
    return AuthService(Settings(AUTH_ENABLED=False, JWT_SECRET_KEY='test-secret'))
from app.models.schemas import (
    EvidenceChunk,
    HandoffListResponse,
    HandoffPayload,
    HandoffQueueItem,
    HandoffQueueStatus,
    ResolutionProb,
)


def _handoff_item(status: HandoffQueueStatus = HandoffQueueStatus.open) -> HandoffQueueItem:
    return HandoffQueueItem(
        handoff_id='9bc1f361-0ea8-455c-aadf-bc418b026c72',
        request_id='3e3a24bc-bfbf-40d0-ad5a-cbcedd4106f2',
        tenant_id='org_demo',
        queue_status=status,
        reason_codes=['low_confidence'],
        handoff_payload=HandoffPayload(
            handoff_id='9bc1f361-0ea8-455c-aadf-bc418b026c72',
            reason_codes=['low_confidence'],
            summary='Manual reviewer handoff',
            evidence_pack=[
                EvidenceChunk(
                    chunk_id='billing_001',
                    doc_id='billing_doc',
                    score=0.81,
                    rank=1,
                    source='internal_wiki',
                    updated_at='2025-12-09',
                    text='Verify duplicate charge and issue refund.',
                    section='billing',
                    tenant_id='org_demo',
                )
            ],
            route_probs=[ResolutionProb(label='refund_duplicate_charge', prob=0.91)],
            escalation_prob=0.42,
            created_at=datetime.now(timezone.utc).isoformat(),
        ),
        created_at=datetime.now(timezone.utc).isoformat(),
    )


class SpyHandoffStore:
    def __init__(self) -> None:
        self.list_calls = []
        self.update_calls = []
        self._item = _handoff_item()

    def list_handoffs(self, tenant_id: str, queue_status: HandoffQueueStatus | None = None, limit: int = 50):
        self.list_calls.append((tenant_id, queue_status, limit))
        return HandoffListResponse(items=[self._item])

    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision=None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ):
        self.update_calls.append(
            (tenant_id, handoff_id, queue_status, reviewer_id, final_decision, final_resolution_path, notes)
        )
        ground_truth_recorded = bool(queue_status in {HandoffQueueStatus.resolved, HandoffQueueStatus.closed} and reviewer_id and final_decision and final_resolution_path)
        return (
            _handoff_item(status=queue_status).model_copy(update={'handoff_id': handoff_id, 'tenant_id': tenant_id}),
            ground_truth_recorded,
        )


class MissingHandoffStore:
    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision=None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ):
        return None, False

    def list_handoffs(self, tenant_id: str, queue_status: HandoffQueueStatus | None = None, limit: int = 50):
        return HandoffListResponse(items=[])


class EnforcingHandoffStore:
    def update_queue_status(
        self,
        tenant_id: str,
        handoff_id: str,
        queue_status: HandoffQueueStatus,
        reviewer_id: str | None = None,
        final_decision=None,
        final_resolution_path: str | None = None,
        notes: str | None = None,
    ):
        if queue_status == HandoffQueueStatus.closed and not (reviewer_id and final_decision and final_resolution_path):
            raise ValueError('Closing a ticket requires reviewer ground-truth fields.')
        return _handoff_item(status=queue_status), True

    def list_handoffs(self, tenant_id: str, queue_status: HandoffQueueStatus | None = None, limit: int = 50):
        return HandoffListResponse(items=[])


def test_handoff_list_endpoint_returns_items():
    spy = SpyHandoffStore()
    app.dependency_overrides[get_handoff_store] = lambda: spy
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.get('/v1/assist/handoffs', params={'tenant_id': 'org_demo', 'queue_status': 'open', 'limit': 25})

        assert res.status_code == 200
        body = res.json()
        assert len(body['items']) == 1
        assert body['items'][0]['handoff_id'] == '9bc1f361-0ea8-455c-aadf-bc418b026c72'
        assert spy.list_calls == [('org_demo', HandoffQueueStatus.open, 25)]
    finally:
        app.dependency_overrides.clear()


def test_handoff_update_endpoint_updates_status():
    spy = SpyHandoffStore()
    app.dependency_overrides[get_handoff_store] = lambda: spy
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.patch(
                '/v1/assist/handoffs/9bc1f361-0ea8-455c-aadf-bc418b026c72/status',
                json={'tenant_id': 'org_demo', 'queue_status': 'in_review'},
            )

        assert res.status_code == 200
        body = res.json()
        assert body['handoff_id'] == '9bc1f361-0ea8-455c-aadf-bc418b026c72'
        assert body['tenant_id'] == 'org_demo'
        assert body['queue_status'] == 'in_review'
        assert body['ground_truth_recorded'] is False
        assert spy.update_calls == [
            (
                'org_demo',
                '9bc1f361-0ea8-455c-aadf-bc418b026c72',
                HandoffQueueStatus.in_review,
                None,
                None,
                None,
                None,
            )
        ]
    finally:
        app.dependency_overrides.clear()


def test_handoff_update_returns_404_when_missing():
    app.dependency_overrides[get_handoff_store] = lambda: MissingHandoffStore()
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.patch(
                '/v1/assist/handoffs/00000000-0000-0000-0000-000000000000/status',
                json={'tenant_id': 'org_demo', 'queue_status': 'resolved'},
            )
        assert res.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_handoff_update_requires_ground_truth_fields_when_closing():
    app.dependency_overrides[get_handoff_store] = lambda: EnforcingHandoffStore()
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.patch(
                '/v1/assist/handoffs/9bc1f361-0ea8-455c-aadf-bc418b026c72/status',
                json={'tenant_id': 'org_demo', 'queue_status': 'closed'},
            )

        assert res.status_code == 422
        assert 'ground-truth' in res.text.lower()
    finally:
        app.dependency_overrides.clear()


def test_handoff_close_records_ground_truth_when_fields_present():
    spy = SpyHandoffStore()
    app.dependency_overrides[get_handoff_store] = lambda: spy
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.patch(
                '/v1/assist/handoffs/9bc1f361-0ea8-455c-aadf-bc418b026c72/status',
                json={
                    'tenant_id': 'org_demo',
                    'queue_status': 'closed',
                    'reviewer_id': 'agent_42',
                    'final_decision': 'recommend',
                    'final_resolution_path': 'refund_duplicate_charge',
                    'notes': 'Verified and resolved.',
                },
            )
        assert res.status_code == 200
        assert res.json()['ground_truth_recorded'] is True
    finally:
        app.dependency_overrides.clear()
