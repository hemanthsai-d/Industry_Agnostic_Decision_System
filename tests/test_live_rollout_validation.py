from __future__ import annotations

from datetime import date

from scripts.validate_live_rollout import _normalize_optional_filter, stage_progression_complete, trailing_stable_days


def test_stage_progression_complete_requires_full_sequence():
    assert stage_progression_complete([5, 25, 50, 100]) is True
    assert stage_progression_complete([5, 25, 100]) is False


def test_stage_progression_complete_ignores_extra_points():
    assert stage_progression_complete([0, 5, 5, 25, 25, 50, 100, 100]) is True


def test_trailing_stable_days_counts_only_contiguous_days():
    end = date(2026, 2, 16)
    pass_map = {
        date(2026, 2, 16): True,
        date(2026, 2, 15): True,
        date(2026, 2, 14): False,
        date(2026, 2, 13): True,
    }
    assert trailing_stable_days(end_date=end, daily_pass_map=pass_map, max_days=28) == 2


def test_trailing_stable_days_respects_max_days():
    end = date(2026, 2, 16)
    pass_map = {
        date(2026, 2, 16): True,
        date(2026, 2, 15): True,
        date(2026, 2, 14): True,
    }
    assert trailing_stable_days(end_date=end, daily_pass_map=pass_map, max_days=2) == 2


def test_normalize_optional_filter():
    assert _normalize_optional_filter('') is None
    assert _normalize_optional_filter('__all__') is None
    assert _normalize_optional_filter(' all ') is None
    assert _normalize_optional_filter('billing') == 'billing'
