from __future__ import annotations

import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from redis import Redis

from app.api.deps import get_rate_limiter
from app.main import app
from app.security.rate_limit import RedisRateLimiter

pytestmark = pytest.mark.integration


@pytest.fixture(scope='module')
def integration_enabled():
    run_flag = os.getenv('DECISION_PLATFORM_RUN_REDIS_RATE_LIMIT_E2E', '').strip().lower() in {'1', 'true', 'yes'}
    if not run_flag:
        pytest.skip('Set DECISION_PLATFORM_RUN_REDIS_RATE_LIMIT_E2E=1 to run Redis E2E integration tests.')
    return True


@pytest.fixture(scope='module')
def redis_url() -> str:
    return os.getenv('REDIS_URL', 'redis://127.0.0.1:6379/0')


@pytest.fixture(scope='module')
def redis_client(integration_enabled: bool, redis_url: str) -> Redis:
    client = Redis.from_url(redis_url, decode_responses=True)
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover - only for unavailable local redis
        pytest.fail(f'Redis integration test requires a reachable Redis at {redis_url}. Error: {exc}')
    yield client
    client.close()


def _cleanup_keys_with_prefix(client: Redis, key_prefix: str) -> None:
    keys = list(client.scan_iter(match=f'{key_prefix}:*'))
    if keys:
        client.delete(*keys)


def _feedback_payload(counter: int, tenant_id: str = 'org_demo') -> dict:
    return {
        'request_id': f'rq-rate-e2e-{counter}-{uuid4().hex[:8]}',
        'tenant_id': tenant_id,
        'accepted_decision': 'abstain',
    }


def test_redis_e2e_tenant_limit_crossing_returns_429(redis_client: Redis, redis_url: str):
    key_prefix = f'assist:ratelimit:e2e:tenant:{uuid4().hex}'
    _cleanup_keys_with_prefix(redis_client, key_prefix)

    limiter = RedisRateLimiter(
        redis_url=redis_url,
        window_seconds=60,
        tenant_limit=2,
        user_limit=100,
        fail_open=False,
        key_prefix=key_prefix,
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        with TestClient(app) as client:
            ok1 = client.post('/v1/assist/feedback', json=_feedback_payload(1))
            ok2 = client.post('/v1/assist/feedback', json=_feedback_payload(2))
            blocked = client.post('/v1/assist/feedback', json=_feedback_payload(3))

        assert ok1.status_code == 200
        assert ok2.status_code == 200
        assert blocked.status_code == 429
        assert blocked.json().get('detail') == 'Tenant rate limit exceeded.'
        assert int(blocked.headers.get('retry-after', '0')) >= 1
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)
        _cleanup_keys_with_prefix(redis_client, key_prefix)


def test_redis_e2e_user_limit_crossing_returns_429(redis_client: Redis, redis_url: str):
    key_prefix = f'assist:ratelimit:e2e:user:{uuid4().hex}'
    _cleanup_keys_with_prefix(redis_client, key_prefix)

    limiter = RedisRateLimiter(
        redis_url=redis_url,
        window_seconds=60,
        tenant_limit=100,
        user_limit=1,
        fail_open=False,
        key_prefix=key_prefix,
    )
    app.dependency_overrides[get_rate_limiter] = lambda: limiter

    try:
        with TestClient(app) as client:
            ok = client.post('/v1/assist/feedback', json=_feedback_payload(1))
            blocked = client.post('/v1/assist/feedback', json=_feedback_payload(2))

        assert ok.status_code == 200
        assert blocked.status_code == 429
        assert blocked.json().get('detail') == 'User rate limit exceeded.'
        assert int(blocked.headers.get('retry-after', '0')) >= 1
    finally:
        app.dependency_overrides.pop(get_rate_limiter, None)
        _cleanup_keys_with_prefix(redis_client, key_prefix)
