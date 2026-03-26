from __future__ import annotations

from pathlib import Path

import pytest

from scripts.upsert_workload_feed import load_csv


def test_load_csv_parses_rows(tmp_path: Path) -> None:
    csv_path = tmp_path / 'workload.csv'
    csv_path.write_text(
        '\n'.join(
            [
                'metric_date,tenant_id,section,eligible_tickets_total,active_agents_total,source',
                '2026-02-16,org_demo,billing,120,42,ops_export',
            ]
        )
        + '\n',
        encoding='utf-8',
    )
    rows = load_csv(csv_path)
    assert len(rows) == 1
    assert rows[0].tenant_id == 'org_demo'
    assert rows[0].eligible_tickets_total == 120


def test_load_csv_fails_when_columns_missing(tmp_path: Path) -> None:
    csv_path = tmp_path / 'bad.csv'
    csv_path.write_text('metric_date,tenant_id\n2026-02-16,org_demo\n', encoding='utf-8')
    with pytest.raises(ValueError):
        load_csv(csv_path)
