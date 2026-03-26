from __future__ import annotations

from scripts.audit_oncall_config import audit_config


def _valid_config() -> dict:
    return {
        'generated_at_utc': '2026-02-17T00:00:00Z',
        'teams': {
            'platform_oncall': {
                'primary': [{'name': 'A', 'email': 'a@company.org', 'timezone': 'UTC'}],
                'backup': [{'name': 'B', 'phone': '+1-800-7001', 'timezone': 'UTC'}],
            },
            'model_oncall': {
                'primary': [{'name': 'C', 'email': 'c@company.org', 'timezone': 'UTC'}],
                'backup': [{'name': 'D', 'phone': '+1-800-7002', 'timezone': 'UTC'}],
            },
        },
        'escalation_policy': [
            {'after_minutes': 5, 'targets': ['backup_oncall']},
            {'after_minutes': 15, 'targets': ['incident_commander']},
            {'after_minutes': 30, 'targets': ['leadership']},
        ],
    }


def test_audit_config_passes_for_valid_payload() -> None:
    passed, errors, warnings = audit_config(_valid_config())
    assert passed
    assert errors == []
    assert warnings == []


def test_audit_config_fails_when_required_tier_missing() -> None:
    payload = _valid_config()
    payload['escalation_policy'] = [
        {'after_minutes': 5, 'targets': ['backup_oncall']},
        {'after_minutes': 30, 'targets': ['leadership']},
    ]
    passed, errors, _ = audit_config(payload)
    assert not passed
    assert any('15 minutes' in item for item in errors)
