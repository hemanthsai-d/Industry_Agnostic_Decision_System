from __future__ import annotations

from fastapi.testclient import TestClient

from app.api.deps import get_readiness_service
from app.main import app


class StaticReadinessService:
    def __init__(self, payload: dict):
        self._payload = payload

    async def check(self) -> dict:
        return self._payload


def test_ready_endpoint_returns_200_when_dependencies_are_ready():
    payload = {
        'status': 'ready',
        'checks': {
            'database': {'enabled': False, 'status': 'skipped', 'detail': 'USE_POSTGRES=false'},
            'redis': {'enabled': False, 'status': 'skipped', 'detail': 'USE_REDIS=false'},
            'model_serving': {'enabled': False, 'status': 'skipped', 'detail': 'ROUTING_MODEL_BACKEND=artifact'},
        },
    }
    app.dependency_overrides[get_readiness_service] = lambda: StaticReadinessService(payload)

    try:
        with TestClient(app) as client:
            res = client.get('/ready')
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 200
    assert res.json() == payload


def test_ready_endpoint_returns_503_when_required_dependency_is_unhealthy():
    payload = {
        'status': 'not_ready',
        'checks': {
            'database': {
                'enabled': True,
                'status': 'failed',
                'latency_ms': 10.0,
                'detail': 'Database connectivity check failed.',
                'error_type': 'OperationalError',
            },
            'redis': {'enabled': False, 'status': 'skipped', 'detail': 'USE_REDIS=false'},
            'model_serving': {'enabled': False, 'status': 'skipped', 'detail': 'ROUTING_MODEL_BACKEND=artifact'},
        },
    }
    app.dependency_overrides[get_readiness_service] = lambda: StaticReadinessService(payload)

    try:
        with TestClient(app) as client:
            res = client.get('/ready')
    finally:
        app.dependency_overrides.clear()

    assert res.status_code == 503
    assert res.json() == payload
