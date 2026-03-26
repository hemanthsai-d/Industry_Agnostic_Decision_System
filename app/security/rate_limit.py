from __future__ import annotations

import logging
import time
from typing import Protocol

from fastapi import HTTPException, status

from app.observability.metrics import observe_rate_limit_exceeded

logger = logging.getLogger(__name__)


class RateLimiter(Protocol):
    async def enforce(self, *, tenant_id: str, user_id: str, action: str) -> None:
        ...


class NoopRateLimiter:
    async def enforce(self, *, tenant_id: str, user_id: str, action: str) -> None:
        return


class RedisRateLimiter:
    """Token-bucket rate limiter backed by Redis.

    Each key holds two hash fields: ``tokens`` (remaining) and ``last`` (last
    refill timestamp in microseconds).  A single Lua script atomically refills
    and decrements the bucket, so the operation is both race-free and requires
    only one round-trip per check.

    Constructor parameters are intentionally kept backward-compatible with the
    previous fixed-window implementation so existing callers (deps.py, tests)
    continue to work unchanged.
    """

    # Lua script: KEYS[1]=bucket key, ARGV[1]=max_tokens, ARGV[2]=refill_period_us, ARGV[3]=now_us
    _TOKEN_BUCKET_LUA = """
    local key = KEYS[1]
    local max_tokens = tonumber(ARGV[1])
    local refill_us  = tonumber(ARGV[2])
    local now_us     = tonumber(ARGV[3])

    local data = redis.call('HMGET', key, 'tokens', 'last')
    local tokens = tonumber(data[1])
    local last   = tonumber(data[2])

    if tokens == nil then
        tokens = max_tokens
        last   = now_us
    end

    -- refill
    local elapsed = math.max(0, now_us - last)
    local refill  = math.floor(elapsed / refill_us)
    if refill > 0 then
        tokens = math.min(max_tokens, tokens + refill)
        last   = last + refill * refill_us
    end

    local allowed = 0
    if tokens > 0 then
        tokens  = tokens - 1
        allowed = 1
    end

    redis.call('HSET', key, 'tokens', tokens, 'last', last)
    redis.call('EXPIRE', key, math.ceil(max_tokens * refill_us / 1000000) + 1)
    return { allowed, tokens }
    """

    def __init__(
        self,
        *,
        redis_url: str,
        window_seconds: int,
        tenant_limit: int,
        user_limit: int,
        fail_open: bool = True,
        key_prefix: str = 'assist:ratelimit',
        redis_client=None,
    ) -> None:
        # Refill period: one token is added every (window / limit) seconds,
        # allowing `limit` requests per `window` on average (bursty up to limit).
        self._window_seconds = max(1, int(window_seconds))
        self._tenant_limit = max(1, int(tenant_limit))
        self._user_limit = max(1, int(user_limit))
        self._tenant_refill_us = int(self._window_seconds * 1_000_000 / self._tenant_limit)
        self._user_refill_us = int(self._window_seconds * 1_000_000 / self._user_limit)
        self._fail_open = bool(fail_open)
        self._key_prefix = str(key_prefix or 'assist:ratelimit')

        if redis_client is not None:
            self._redis = redis_client
        else:
            from redis.asyncio import Redis
            self._redis = Redis.from_url(redis_url, encoding='utf-8', decode_responses=True)

        self._script = self._redis.register_script(self._TOKEN_BUCKET_LUA)

    async def enforce(self, *, tenant_id: str, user_id: str, action: str) -> None:
        clean_tenant = (tenant_id or '').strip()
        clean_user = (user_id or 'anonymous').strip() or 'anonymous'
        clean_action = (action or 'unknown').strip() or 'unknown'

        if not clean_tenant:
            return

        now_us = int(time.time() * 1_000_000)
        retry_after = max(1, self._window_seconds)

        tenant_key = f'{self._key_prefix}:tb:tenant:{clean_tenant}:{clean_action}'
        user_key = f'{self._key_prefix}:tb:user:{clean_tenant}:{clean_user}:{clean_action}'

        try:
            allowed, _remaining = await self._script(
                keys=[tenant_key],
                args=[self._tenant_limit, self._tenant_refill_us, now_us],
            )
            if not int(allowed):
                observe_rate_limit_exceeded(scope='tenant', action=clean_action)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail='Tenant rate limit exceeded.',
                    headers={'Retry-After': str(retry_after)},
                )

            allowed, _remaining = await self._script(
                keys=[user_key],
                args=[self._user_limit, self._user_refill_us, now_us],
            )
            if not int(allowed):
                observe_rate_limit_exceeded(scope='user', action=clean_action)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail='User rate limit exceeded.',
                    headers={'Retry-After': str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception:
            if self._fail_open:
                logger.exception(
                    'Rate limiter backend unavailable. Continuing due to fail-open.',
                    extra={'tenant_id': clean_tenant, 'user_id': clean_user, 'action': clean_action},
                )
                return
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail='Rate limiter unavailable.',
            )
