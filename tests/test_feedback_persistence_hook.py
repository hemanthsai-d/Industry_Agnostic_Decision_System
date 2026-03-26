from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_feedback_store
from app.core.config import Settings
from app.main import app
from app.security.auth import AuthService
from app.security.deps import get_auth_service


def _no_auth_service():
    return AuthService(Settings(AUTH_ENABLED=False, JWT_SECRET_KEY='test-secret'))


class SpyFeedbackStore:
    def __init__(self) -> None:
        self.persisted = []

    def persist(self, req) -> None:
        self.persisted.append(req)


def test_feedback_endpoint_persists_event():
    spy = SpyFeedbackStore()
    app.dependency_overrides[get_feedback_store] = lambda: spy
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.post(
                "/v1/assist/feedback",
                json={
                    "request_id": "abc-feedback-1",
                    "tenant_id": "org_demo",
                    "accepted_decision": "abstain",
                    "corrected_resolution_path": "refund_duplicate_charge",
                    "notes": "Agent confirmed duplicate charge flow.",
                },
            )
        assert res.status_code == 200
        assert res.json()["status"] == "accepted"
        assert len(spy.persisted) == 1
        assert spy.persisted[0].tenant_id == "org_demo"
        assert spy.persisted[0].request_id == "abc-feedback-1"
    finally:
        app.dependency_overrides.clear()

