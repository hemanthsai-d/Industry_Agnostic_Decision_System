from __future__ import annotations

from scripts.configure_alertmanager_prod import _is_placeholder


def test_is_placeholder_detects_example_domain() -> None:
    assert _is_placeholder('https://pager.example.invalid/webhook')


def test_is_placeholder_detects_markers() -> None:
    assert _is_placeholder('https://hooks.slack.com/services/<replace-me>')
    assert _is_placeholder('https://api.example.com/changeme')


def test_is_placeholder_allows_real_url_shape() -> None:
    assert not _is_placeholder('https://events.pagerduty.com/v2/enqueue')
