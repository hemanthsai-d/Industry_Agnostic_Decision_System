from __future__ import annotations

import asyncio
import logging
from time import perf_counter
from typing import Any

import httpx
import psycopg

from app.core.config import Settings
from app.services.routing import RoutingService
from app.storage.postgres_store import to_psycopg_dsn

logger = logging.getLogger(__name__)


class ReadinessService:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def check(self) -> dict[str, Any]:
        checks = {
            'database': await self._check_database(),
            'redis': await self._check_redis(),
            'model_serving': await self._check_model_serving(),
        }

        ready = all(check['status'] == 'ok' for check in checks.values() if check['enabled'])
        return {
            'status': 'ready' if ready else 'not_ready',
            'checks': checks,
        }

    async def _check_database(self) -> dict[str, Any]:
        if not self._settings.use_postgres:
            return self._skipped('USE_POSTGRES=false')

        started_at = perf_counter()
        try:
            await asyncio.to_thread(self._ping_postgres)
            return self._ok(started_at)
        except Exception as exc:
            logger.exception('Database readiness check failed.')
            return self._failed(
                started_at,
                detail='Database connectivity check failed.',
                error_type=type(exc).__name__,
            )

    async def _check_redis(self) -> dict[str, Any]:
        if not self._settings.use_redis:
            return self._skipped('USE_REDIS=false')

        started_at = perf_counter()
        try:
            await self._ping_redis()
            return self._ok(started_at)
        except Exception as exc:
            logger.exception('Redis readiness check failed.')
            return self._failed(
                started_at,
                detail='Redis connectivity check failed.',
                error_type=type(exc).__name__,
            )

    async def _check_model_serving(self) -> dict[str, Any]:
        backend = self._settings.routing_model_backend.strip().lower()
        if backend != 'http':
            return self._skipped(f'ROUTING_MODEL_BACKEND={backend or "unset"}')

        started_at = perf_counter()
        try:
            await self._probe_model_serving()
            return self._ok(started_at)
        except Exception as exc:
            logger.exception('Model-serving readiness check failed.')
            return self._failed(
                started_at,
                detail='Model-serving dependency check failed.',
                error_type=type(exc).__name__,
            )

    def _ping_postgres(self) -> None:
        with psycopg.connect(to_psycopg_dsn(self._settings.postgres_dsn), connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute('SELECT 1;')
                cur.fetchone()

    async def _ping_redis(self) -> None:
        from redis.asyncio import Redis

        client = Redis.from_url(self._settings.redis_url, encoding='utf-8', decode_responses=True)
        try:
            await client.ping()
        finally:
            await client.aclose()

    async def _probe_model_serving(self) -> None:
        headers: dict[str, str] = {}
        if self._settings.model_serving_api_key.strip():
            headers['Authorization'] = f'Bearer {self._settings.model_serving_api_key.strip()}'

        payload = {
            'issue_text': 'readiness probe',
            'route_labels': list(RoutingService.DEFAULT_ROUTE_LABELS),
            'features': {
                'evidence_count': 0,
                'top_evidence_score': 0.0,
            },
        }

        timeout = max(0.1, float(self._settings.model_serving_timeout_seconds))
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self._settings.model_serving_url, json=payload, headers=headers)
            response.raise_for_status()
            body = response.json()

        self._validate_model_serving_response(body)

    @staticmethod
    def _validate_model_serving_response(body: Any) -> None:
        if not isinstance(body, dict):
            raise RuntimeError('Model-serving response must be a JSON object.')

        route_probabilities = body.get('route_probabilities')
        if not isinstance(route_probabilities, dict) or not route_probabilities:
            raise RuntimeError("Model-serving response missing route_probabilities.")

        for label, probability in route_probabilities.items():
            if not isinstance(label, str):
                raise RuntimeError('Model-serving route labels must be strings.')
            try:
                float(probability)
            except (TypeError, ValueError) as exc:
                raise RuntimeError('Model-serving probabilities must be numeric.') from exc

        escalation_prob = body.get('escalation_prob')
        if escalation_prob is not None:
            try:
                float(escalation_prob)
            except (TypeError, ValueError) as exc:
                raise RuntimeError('Model-serving escalation_prob must be numeric.') from exc

    @staticmethod
    def _latency_ms(started_at: float) -> float:
        return round((perf_counter() - started_at) * 1000, 2)

    def _ok(self, started_at: float) -> dict[str, Any]:
        return {
            'enabled': True,
            'status': 'ok',
            'latency_ms': self._latency_ms(started_at),
        }

    def _failed(self, started_at: float, *, detail: str, error_type: str) -> dict[str, Any]:
        return {
            'enabled': True,
            'status': 'failed',
            'latency_ms': self._latency_ms(started_at),
            'detail': detail,
            'error_type': error_type,
        }

    @staticmethod
    def _skipped(detail: str) -> dict[str, Any]:
        return {
            'enabled': False,
            'status': 'skipped',
            'detail': detail,
        }
