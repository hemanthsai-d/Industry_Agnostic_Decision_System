from __future__ import annotations

from scripts.run_nonfunctional_validation import _is_success_status, _percentile


def test_percentile_returns_none_on_empty() -> None:
    assert _percentile([], 95.0) is None


def test_percentile_returns_expected_rank() -> None:
    values = [10.0, 20.0, 30.0, 40.0, 50.0]
    assert _percentile(values, 50.0) == 30.0
    assert _percentile(values, 95.0) == 50.0


def test_is_success_status_only_accepts_2xx() -> None:
    assert _is_success_status(200) is True
    assert _is_success_status(204) is True
    assert _is_success_status(299) is True
    assert _is_success_status(300) is False
    assert _is_success_status(401) is False
    assert _is_success_status(500) is False
