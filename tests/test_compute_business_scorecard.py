from __future__ import annotations

from scripts.compute_business_scorecard import _format_value, _to_row


def test_format_value_ratio_uses_percent() -> None:
    assert _format_value('ratio', 0.125) == '12.50%'


def test_format_value_handles_none() -> None:
    assert _format_value('ratio', None) == 'n/a'


def test_to_row_parses_nullable_fields() -> None:
    row = _to_row(
        {
            'kpi_name': 'top1_route_accuracy_pct',
            'comparator': 'gte',
            'target_value': 0.85,
            'unit': 'ratio',
            'description': 'Top-1 route accuracy',
            'actual_value': None,
            'status': 'insufficient_data',
            'details': {'labeled_samples': 0},
        }
    )
    assert row.kpi_name == 'top1_route_accuracy_pct'
    assert row.actual_value is None
    assert row.details == {'labeled_samples': 0}
