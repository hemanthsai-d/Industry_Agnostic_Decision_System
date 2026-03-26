from __future__ import annotations

from fastapi.testclient import TestClient

from model_server.app import app


def test_model_server_predict_contract_shape():
    with TestClient(app) as client:
        response = client.post(
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
                'features': {'evidence_count': 2, 'top_evidence_score': 0.82},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert 'route_probabilities' in payload
    assert 'escalation_prob' in payload
    assert 'backend' in payload

    probs = payload['route_probabilities']
    assert isinstance(probs, dict)
    assert len(probs) == 5
    assert abs(sum(probs.values()) - 1.0) < 1e-5
    assert 0.0 <= payload['escalation_prob'] <= 1.0


def test_model_server_risk_language_has_higher_escalation_than_basic_refund():
    with TestClient(app) as client:
        base = client.post(
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
        risk = client.post(
            '/v1/models/routing:predict',
            json={
                'issue_text': 'Customer threatens legal lawsuit over fraud and security breach.',
                'route_labels': [
                    'refund_duplicate_charge',
                    'account_access_recovery',
                    'shipping_delay_resolution',
                    'technical_bug_triage',
                    'general_support_triage',
                ],
                'features': {'evidence_count': 1, 'top_evidence_score': 0.6},
            },
        )

    assert base.status_code == 200
    assert risk.status_code == 200
    assert risk.json()['escalation_prob'] > base.json()['escalation_prob']
