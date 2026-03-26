from __future__ import annotations

from scripts.promote_canary import _build_blocking_reasons


def test_build_blocking_reasons_happy_path():
    reasons = _build_blocking_reasons(
        source_scope='canary_only',
        sample_size=100,
        min_sample_size=50,
        route_accuracy=0.9,
        escalation_recall=0.8,
        ece=0.05,
        abstain_rate=0.1,
        gates={
            'min_route_accuracy': 0.75,
            'min_escalation_recall': 0.7,
            'max_ece': 0.15,
            'max_abstain_rate': 0.35,
        },
    )
    assert reasons == []


def test_build_blocking_reasons_collects_all_failures():
    reasons = _build_blocking_reasons(
        source_scope='canary_only',
        sample_size=0,
        min_sample_size=50,
        route_accuracy=0.4,
        escalation_recall=None,
        ece=0.3,
        abstain_rate=0.6,
        gates={
            'min_route_accuracy': 0.75,
            'min_escalation_recall': 0.7,
            'max_ece': 0.15,
            'max_abstain_rate': 0.35,
        },
    )
    assert 'no_canary_samples' in reasons
    assert 'sample_size_below_gate' in reasons
    assert 'route_accuracy_below_gate' in reasons
    assert 'missing_escalation_recall' in reasons
    assert 'ece_above_gate' in reasons
    assert 'abstain_rate_above_gate' in reasons
