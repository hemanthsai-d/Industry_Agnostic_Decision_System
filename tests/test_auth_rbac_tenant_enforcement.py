from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.security.auth import AuthService
from app.security.deps import get_auth_service


def _token(secret: str, claims: dict) -> str:
    return jwt.encode(claims, secret, algorithm="HS256")


def _base_claims(tenant_ids: list[str], permissions: list[str]) -> dict:
    now = datetime.now(timezone.utc)
    return {
        "sub": "user_123",
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=1)).timestamp()),
        "iss": "decision-platform",
        "aud": "decision-platform-api",
        "roles": ["support_agent"],
        "permissions": permissions,
        "tenant_ids": tenant_ids,
    }


def test_decide_denies_tenant_mismatch_when_auth_enabled():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_allowed"], ["assist:decide"]))
        with TestClient(app) as client:
            res = client.post(
                "/v1/assist/decide",
                headers={"Authorization": f"Bearer {tok}"},
                json={
                    "tenant_id": "org_denied",
                    "section": "billing",
                    "issue_text": "Customer charged twice.",
                },
            )
        assert res.status_code == 403
        assert "No access to tenant" in res.text
    finally:
        app.dependency_overrides.clear()


def test_decide_allows_with_permission_and_tenant_access():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_demo"], ["assist:decide"]))
        with TestClient(app) as client:
            res = client.post(
                "/v1/assist/decide",
                headers={"Authorization": f"Bearer {tok}"},
                json={
                    "tenant_id": "org_demo",
                    "section": "billing",
                    "issue_text": "Customer charged twice.",
                },
            )
        assert res.status_code == 200
        assert "decision" in res.json()
    finally:
        app.dependency_overrides.clear()


def test_feedback_requires_permission():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_demo"], ["assist:decide"]))
        with TestClient(app) as client:
            res = client.post(
                "/v1/assist/feedback",
                headers={"Authorization": f"Bearer {tok}"},
                json={
                    "request_id": "rq-fb-1",
                    "tenant_id": "org_demo",
                    "accepted_decision": "abstain",
                },
            )
        assert res.status_code == 403
        assert "Missing permission" in res.text
    finally:
        app.dependency_overrides.clear()


def test_handoff_list_requires_permission():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_demo"], ["assist:decide"]))
        with TestClient(app) as client:
            res = client.get(
                "/v1/assist/handoffs",
                headers={"Authorization": f"Bearer {tok}"},
                params={"tenant_id": "org_demo"},
            )
        assert res.status_code == 403
        assert "Missing permission" in res.text
    finally:
        app.dependency_overrides.clear()


def test_handoff_list_denies_tenant_mismatch_when_auth_enabled():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_allowed"], ["assist:handoff:read"]))
        with TestClient(app) as client:
            res = client.get(
                "/v1/assist/handoffs",
                headers={"Authorization": f"Bearer {tok}"},
                params={"tenant_id": "org_denied"},
            )
        assert res.status_code == 403
        assert "No access to tenant" in res.text
    finally:
        app.dependency_overrides.clear()


def test_handoff_update_requires_permission():
    settings = Settings(
        AUTH_ENABLED=True,
        JWT_SECRET_KEY="test-secret",
        JWT_ALGORITHM="HS256",
        JWT_ISSUER="decision-platform",
        JWT_AUDIENCE="decision-platform-api",
    )
    app.dependency_overrides[get_auth_service] = lambda: AuthService(settings)
    try:
        tok = _token("test-secret", _base_claims(["org_demo"], ["assist:handoff:read"]))
        with TestClient(app) as client:
            res = client.patch(
                "/v1/assist/handoffs/9bc1f361-0ea8-455c-aadf-bc418b026c72/status",
                headers={"Authorization": f"Bearer {tok}"},
                json={"tenant_id": "org_demo", "queue_status": "in_review"},
            )
        assert res.status_code == 403
        assert "Missing permission" in res.text
    finally:
        app.dependency_overrides.clear()
