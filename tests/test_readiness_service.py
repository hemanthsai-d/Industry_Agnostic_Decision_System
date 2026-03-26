from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.readiness import ReadinessService


@pytest.mark.asyncio
async def test_readiness_service_skips_checks_when_dependencies_disabled():
    settings = Settings(USE_POSTGRES=False, USE_REDIS=False, RATE_LIMIT_ENABLED=False, ROUTING_MODEL_BACKEND='artifact')
    service = ReadinessService(settings=settings)

    payload = await service.check()

    assert payload['status'] == 'ready'
    assert payload['checks']['database']['status'] == 'skipped'
    assert payload['checks']['redis']['status'] == 'skipped'
    assert payload['checks']['model_serving']['status'] == 'skipped'


@pytest.mark.asyncio
async def test_readiness_service_marks_not_ready_when_db_ping_fails(monkeypatch):
    settings = Settings(USE_POSTGRES=True, USE_REDIS=False, RATE_LIMIT_ENABLED=False, ROUTING_MODEL_BACKEND='artifact')
    service = ReadinessService(settings=settings)

    def _fail_ping() -> None:
        raise RuntimeError('db is down')

    monkeypatch.setattr(service, '_ping_postgres', _fail_ping)

    payload = await service.check()

    assert payload['status'] == 'not_ready'
    db_check = payload['checks']['database']
    assert db_check['enabled'] is True
    assert db_check['status'] == 'failed'
    assert db_check['error_type'] == 'RuntimeError'


@pytest.mark.asyncio
async def test_readiness_service_marks_ready_when_required_dependencies_pass(monkeypatch):
    settings = Settings(
        USE_POSTGRES=True,
        USE_REDIS=True,
        ROUTING_MODEL_BACKEND='http',
        MODEL_SERVING_URL='http://model-serving.local/v1/models/routing:predict',
    )
    service = ReadinessService(settings=settings)

    monkeypatch.setattr(service, '_ping_postgres', lambda: None)

    async def _ok_redis() -> None:
        return

    async def _ok_model_serving() -> None:
        return

    monkeypatch.setattr(service, '_ping_redis', _ok_redis)
    monkeypatch.setattr(service, '_probe_model_serving', _ok_model_serving)

    payload = await service.check()

    assert payload['status'] == 'ready'
    assert payload['checks']['database']['status'] == 'ok'
    assert payload['checks']['redis']['status'] == 'ok'
    assert payload['checks']['model_serving']['status'] == 'ok'
