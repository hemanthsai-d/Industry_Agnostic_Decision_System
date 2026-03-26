from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app as api_app
from app.security.auth import AuthService
from app.security.deps import get_auth_service
from model_server.app import app as model_app


def _no_auth_service():
    return AuthService(Settings(AUTH_ENABLED=False, JWT_SECRET_KEY='test-secret'))


def test_api_sets_request_id_header_and_exposes_metrics():
    with TestClient(api_app) as client:
        health = client.get('/health', headers={'x-request-id': 'req-observe-1'})
        metrics = client.get('/metrics')

    assert health.status_code == 200
    assert health.headers.get('x-request-id') == 'req-observe-1'

    assert metrics.status_code == 200
    assert 'assist_http_requests_total' in metrics.text
    assert 'assist_http_request_duration_seconds' in metrics.text


def test_decide_path_emits_decision_metrics():
    api_app.dependency_overrides[get_auth_service] = _no_auth_service
    try:
        with TestClient(api_app) as client:
            decide = client.post(
                '/v1/assist/decide',
                json={
                    'tenant_id': 'org_demo',
                    'section': 'billing',
                    'issue_text': 'Customer was charged twice and asks for a refund.',
                },
            )
            metrics = client.get('/metrics')

        assert decide.status_code == 200
        assert 'assist_decisions_total' in metrics.text
    finally:
        api_app.dependency_overrides.clear()


def test_model_server_exposes_metrics():
    with TestClient(model_app) as client:
        predict = client.post(
            '/v1/models/routing:predict',
            json={
                'issue_text': 'Customer was charged twice and asks for a refund.',
                'route_labels': [
                    'refund_duplicate_charge',
                    'account_access_recovery',
                    'shipping_delay_resolution',
                    'technical_bug_triage',
                    'general_support_triage',
                ],
                'features': {'evidence_count': 1, 'top_evidence_score': 0.9},
            },
        )
        metrics = client.get('/metrics')

    assert predict.status_code == 200
    assert metrics.status_code == 200
    assert 'assist_http_requests_total' in metrics.text
