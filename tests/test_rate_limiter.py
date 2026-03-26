from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.security.rate_limit import RedisRateLimiter


class FakeScript:
    """Simulates a Redis Lua script for the token-bucket algorithm."""

    def __init__(self, store: dict[str, dict]):
        self._store = store

    async def __call__(self, *, keys, args):
        key = keys[0]
        max_tokens = int(args[0])
        refill_us = int(args[1])
        now_us = int(args[2])

        bucket = self._store.get(key)
        if bucket is None:
            tokens = max_tokens
            last = now_us
        else:
            tokens = bucket['tokens']
            last = bucket['last']

        elapsed = max(0, now_us - last)
        refill = elapsed // refill_us
        if refill > 0:
            tokens = min(max_tokens, tokens + refill)
            last = last + refill * refill_us

        allowed = 0
        if tokens > 0:
            tokens -= 1
            allowed = 1

        self._store[key] = {'tokens': tokens, 'last': last}
        return [allowed, tokens]


class FakeRedisClient:
    def __init__(self):
        self.store: dict[str, dict] = {}

    def register_script(self, script_text: str):
        return FakeScript(self.store)


class BrokenScript:
    async def __call__(self, *, keys, args):
        raise RuntimeError('redis unavailable')


class BrokenRedisClient:
    def register_script(self, script_text: str):
        return BrokenScript()


@pytest.mark.asyncio
async def test_tenant_limit_enforced():
    limiter = RedisRateLimiter(
        redis_url='redis://unused',
        window_seconds=60,
        tenant_limit=1,
        user_limit=100,
        fail_open=False,
        redis_client=FakeRedisClient(),
    )

    await limiter.enforce(tenant_id='org_demo', user_id='u1', action='assist:decide')
    with pytest.raises(HTTPException) as exc:
        await limiter.enforce(tenant_id='org_demo', user_id='u2', action='assist:decide')

    assert exc.value.status_code == 429
    assert 'Tenant rate limit exceeded' in str(exc.value.detail)
    assert int(exc.value.headers['Retry-After']) >= 1


@pytest.mark.asyncio
async def test_user_limit_enforced():
    limiter = RedisRateLimiter(
        redis_url='redis://unused',
        window_seconds=60,
        tenant_limit=100,
        user_limit=1,
        fail_open=False,
        redis_client=FakeRedisClient(),
    )

    await limiter.enforce(tenant_id='org_demo', user_id='user_1', action='assist:feedback')
    with pytest.raises(HTTPException) as exc:
        await limiter.enforce(tenant_id='org_demo', user_id='user_1', action='assist:feedback')

    assert exc.value.status_code == 429
    assert 'User rate limit exceeded' in str(exc.value.detail)


@pytest.mark.asyncio
async def test_fail_open_on_redis_outage():
    limiter = RedisRateLimiter(
        redis_url='redis://unused',
        window_seconds=60,
        tenant_limit=1,
        user_limit=1,
        fail_open=True,
        redis_client=BrokenRedisClient(),
    )

    await limiter.enforce(tenant_id='org_demo', user_id='user_1', action='assist:decide')


@pytest.mark.asyncio
async def test_fail_closed_on_redis_outage():
    limiter = RedisRateLimiter(
        redis_url='redis://unused',
        window_seconds=60,
        tenant_limit=1,
        user_limit=1,
        fail_open=False,
        redis_client=BrokenRedisClient(),
    )

    with pytest.raises(HTTPException) as exc:
        await limiter.enforce(tenant_id='org_demo', user_id='user_1', action='assist:decide')

    assert exc.value.status_code == 503
