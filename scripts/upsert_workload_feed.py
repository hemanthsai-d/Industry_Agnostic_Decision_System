from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


@dataclass
class WorkloadRow:
    metric_date: date
    tenant_id: str
    section: str
    eligible_tickets_total: int
    active_agents_total: int
    source: str


def _tenant_display_name(tenant_id: str) -> str:
    clean = tenant_id.replace('_', ' ').replace('-', ' ').strip()
    return clean.title() if clean else tenant_id


def _parse_row(raw: dict[str, str], line_num: int) -> WorkloadRow:
    metric_date = date.fromisoformat((raw.get('metric_date') or '').strip())
    tenant_id = (raw.get('tenant_id') or '').strip()
    section = (raw.get('section') or '__all__').strip() or '__all__'
    source = (raw.get('source') or 'manual').strip() or 'manual'
    if not tenant_id:
        raise ValueError(f'line {line_num}: tenant_id is required.')
    eligible = int((raw.get('eligible_tickets_total') or '').strip())
    agents = int((raw.get('active_agents_total') or '').strip())
    if eligible < 0 or agents < 0:
        raise ValueError(f'line {line_num}: workload counts must be non-negative.')
    return WorkloadRow(
        metric_date=metric_date,
        tenant_id=tenant_id,
        section=section,
        eligible_tickets_total=eligible,
        active_agents_total=agents,
        source=source,
    )


def load_csv(path: Path) -> list[WorkloadRow]:
    if not path.exists():
        raise FileNotFoundError(f'CSV not found: {path}')
    rows: list[WorkloadRow] = []
    with path.open('r', encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        expected = {
            'metric_date',
            'tenant_id',
            'section',
            'eligible_tickets_total',
            'active_agents_total',
            'source',
        }
        missing = expected - set(reader.fieldnames or [])
        if missing:
            missing_cols = ', '.join(sorted(missing))
            raise ValueError(f'Missing CSV columns: {missing_cols}')
        for idx, raw in enumerate(reader, start=2):
            rows.append(_parse_row(raw, idx))
    return rows


def upsert_rows(dsn: str, rows: list[WorkloadRow]) -> int:
    if not rows:
        return 0
    sql = """
    INSERT INTO ops_workload_daily (
      metric_date,
      tenant_id,
      section,
      eligible_tickets_total,
      active_agents_total,
      source,
      updated_at
    )
    VALUES (%s, %s, %s, %s, %s, %s, now())
    ON CONFLICT (metric_date, tenant_id, section)
    DO UPDATE SET
      eligible_tickets_total = EXCLUDED.eligible_tickets_total,
      active_agents_total = EXCLUDED.active_agents_total,
      source = EXCLUDED.source,
      updated_at = now();
    """
    payload = [
        (
            row.metric_date,
            row.tenant_id,
            row.section,
            row.eligible_tickets_total,
            row.active_agents_total,
            row.source,
        )
        for row in rows
    ]
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.executemany(sql, payload)
        conn.commit()
    return len(payload)


def ensure_tenants_exist(dsn: str, rows: list[WorkloadRow]) -> int:
    if not rows:
        return 0

    tenant_ids = sorted({row.tenant_id for row in rows if row.tenant_id.strip()})
    if not tenant_ids:
        return 0

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT tenant_id FROM tenants WHERE tenant_id = ANY(%s);", (tenant_ids,))
            existing = {row[0] for row in cur.fetchall()}
            missing = [tenant_id for tenant_id in tenant_ids if tenant_id not in existing]
            if missing:
                payload = [(tenant_id, _tenant_display_name(tenant_id)) for tenant_id in missing]
                cur.executemany(
                    """
                    INSERT INTO tenants (tenant_id, name, status)
                    VALUES (%s, %s, 'active')
                    ON CONFLICT (tenant_id) DO NOTHING;
                    """,
                    payload,
                )
        conn.commit()
    return len(missing)


def check_gaps(
    dsn: str,
    *,
    tenant_id: str | None,
    section: str | None,
    start_date: date,
    end_date: date,
) -> tuple[bool, list[str]]:
    expected_dates: set[date] = set()
    cursor = start_date
    while cursor <= end_date:
        expected_dates.add(cursor)
        cursor += timedelta(days=1)

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT metric_date
                FROM ops_workload_daily
                WHERE metric_date >= %s::date
                  AND metric_date <= %s::date
                  AND (%s::text IS NULL OR tenant_id = %s::text)
                  AND (%s::text IS NULL OR section = %s::text);
                """,
                (
                    start_date.isoformat(),
                    end_date.isoformat(),
                    tenant_id,
                    tenant_id,
                    section,
                    section,
                ),
            )
            actual = {row[0] for row in cur.fetchall()}

    missing = sorted(expected_dates - actual)
    missing_str = [d.isoformat() for d in missing]
    return len(missing) == 0, missing_str


def main() -> None:
    parser = argparse.ArgumentParser(description='Upsert daily workload denominator feed into ops_workload_daily.')
    parser.add_argument('--csv', required=True, help='CSV path with workload rows.')
    parser.add_argument('--check-gaps-days', type=int, default=0, help='If >0, verify no missing days in trailing window.')
    parser.add_argument('--tenant-id', default='', help='Optional tenant filter for gap check.')
    parser.add_argument('--section', default='', help='Optional section filter for gap check.')
    parser.add_argument('--fail-on-gaps', action='store_true', help='Exit non-zero if gap check finds missing days.')
    parser.add_argument(
        '--ensure-tenants',
        action='store_true',
        help='Create missing tenant rows from CSV tenant_id values before upsert.',
    )
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        rows = load_csv(Path(args.csv))
    except (ValueError, FileNotFoundError) as exc:
        print(f'Input error: {exc}')
        sys.exit(1)

    try:
        if args.ensure_tenants:
            created = ensure_tenants_exist(dsn, rows)
            print(f'Ensured tenant rows. Newly created: {created}')
        written = upsert_rows(dsn, rows)
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while upserting workload feed. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)
    except psycopg.errors.UndefinedTable as exc:
        print(
            'Required table is missing while preparing workload feed. '
            'Run migrations first.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    print(f'Upserted workload rows: {written}')

    if args.check_gaps_days > 0:
        window_end = datetime.now(timezone.utc).date() - timedelta(days=1)
        window_start = window_end - timedelta(days=max(0, args.check_gaps_days - 1))
        tenant = args.tenant_id.strip() or None
        section = args.section.strip() or None
        ok, missing = check_gaps(
            dsn,
            tenant_id=tenant,
            section=section,
            start_date=window_start,
            end_date=window_end,
        )
        print(
            f'Gap check window: {window_start.isoformat()} -> {window_end.isoformat()}, '
            f'tenant={tenant or "__all__"}, section={section or "__all__"}'
        )
        if ok:
            print('Gap check passed: no missing workload dates.')
        else:
            print(f'Gap check failed: missing dates ({len(missing)}): {", ".join(missing)}')
            if args.fail_on_gaps:
                sys.exit(2)


if __name__ == '__main__':
    main()
