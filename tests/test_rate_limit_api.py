from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.deps import get_rate_limiter
from app.core.config import Settings
from app.main import app
from app.security.auth import AuthService
from app.security.deps import get_auth_service


def _no_auth_service():
    return AuthService(Settings(AUTH_ENABLED=False, JWT_SECRET_KEY='test-secret'))


class RecordingRateLimiter:
    def __init__(self):
        self.calls: list[tuple[str, str, str]] = []

    async def enforce(self, *, tenant_id: str, user_id: str, action: str) -> None:
        self.calls.append((tenant_id, user_id, action))


class AlwaysLimitedRateLimiter:
    async def enforce(self, *, tenant_id: str, user_id: str, action: str) -> None:
        raise HTTPException(
            status_code=429,
            detail='Tenant rate limit exceeded.',
            headers={'Retry-After': '60'},
        )


def test_rate_limiter_receives_tenant_user_and_action_on_decide():
    limiter = RecordingRateLimiter()
    app.dependency_overrides[get_rate_limiter] = lambda: limiter
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.post(
                '/v1/assist/decide',
                json={
                    'tenant_id': 'org_demo',
                    'section': 'billing',
                    'issue_text': 'Customer charged twice.',
                },
            )
        assert res.status_code == 200
        assert limiter.calls == [('org_demo', 'dev-local', 'assist:decide')]
    finally:
        app.dependency_overrides.clear()


def test_rate_limiter_429_bubbles_to_api_response():
    app.dependency_overrides[get_rate_limiter] = lambda: AlwaysLimitedRateLimiter()
    app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(app) as client:
            res = client.post(
                '/v1/assist/feedback',
                json={
                    'request_id': 'rq-rate-limit-1',
                    'tenant_id': 'org_demo',
                    'accepted_decision': 'abstain',
                },
            )
        assert res.status_code == 429
        assert 'rate limit exceeded' in res.text.lower()
        assert res.headers.get('retry-after') == '60'
    finally:
        app.dependency_overrides.clear()
