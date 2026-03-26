from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.compute_business_scorecard import compute_business_scorecard
from scripts.validate_live_rollout import validate_live_rollout

CONTROL_MAX_AGE_DAYS = {
    'incident_endpoint_verification': 30,
    'oncall_schedule_audit': 30,
    'secret_rotation': 90,
    'access_review': 90,
    'load_test': 30,
    'soak_test': 30,
    'failure_test': 30,
}


@dataclass
class ControlCheck:
    control_type: str
    passed: bool
    age_days: int | None
    max_age_days: int
    status: str
    performed_at: str | None
    evidence_uri: str | None


def _default_end_date() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def _check_control_recency(
    conn: psycopg.Connection,
    *,
    control_type: str,
    max_age_days: int,
) -> ControlCheck:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT performed_at, evidence_uri, details
            FROM operational_control_events
            WHERE control_type = %s
              AND status = 'pass'
            ORDER BY performed_at DESC
            LIMIT 1;
            """,
            (control_type,),
        )
        row = cur.fetchone()

    if row is None:
        return ControlCheck(
            control_type=control_type,
            passed=False,
            age_days=None,
            max_age_days=max_age_days,
            status='missing_pass_event',
            performed_at=None,
            evidence_uri=None,
        )

    performed_at = row['performed_at']
    age_days = max(0, (_default_end_date() - performed_at.date()).days)
    details = row['details'] if isinstance(row['details'], dict) else {}
    if control_type == 'incident_endpoint_verification':
        mode = str(details.get('mode', '')).strip().lower()
        if mode != 'live':
            return ControlCheck(
                control_type=control_type,
                passed=False,
                age_days=age_days,
                max_age_days=max_age_days,
                status='not_live_mode',
                performed_at=performed_at.isoformat(),
                evidence_uri=str(row['evidence_uri']),
            )

    return ControlCheck(
        control_type=control_type,
        passed=age_days <= max_age_days,
        age_days=age_days,
        max_age_days=max_age_days,
        status='ok' if age_days <= max_age_days else 'stale',
        performed_at=performed_at.isoformat(),
        evidence_uri=str(row['evidence_uri']),
    )


def _check_workload_coverage(
    conn: psycopg.Connection,
    *,
    start_date: date,
    end_date: date,
    tenant_id: str | None,
    section: str | None,
) -> tuple[bool, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT metric_date, COUNT(*) AS row_count
            FROM ops_workload_daily
            WHERE metric_date >= %s::date
              AND metric_date <= %s::date
              AND (%s::text IS NULL OR tenant_id = %s::text)
              AND (%s::text IS NULL OR section = %s::text)
            GROUP BY metric_date
            ORDER BY metric_date ASC;
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
        rows = cur.fetchall()

    by_date = {row['metric_date']: int(row['row_count']) for row in rows}
    expected_dates: list[date] = []
    cursor = start_date
    while cursor <= end_date:
        expected_dates.append(cursor)
        cursor += timedelta(days=1)
    missing = [d.isoformat() for d in expected_dates if d not in by_date]
    return len(missing) == 0, {
        'window_start': start_date.isoformat(),
        'window_end': end_date.isoformat(),
        'present_dates': len(by_date),
        'expected_dates': len(expected_dates),
        'missing_dates': missing,
    }


def _check_label_coverage(
    conn: psycopg.Connection,
    *,
    start_date: date,
    end_date: date,
    tenant_id: str | None,
    section: str | None,
) -> tuple[bool, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT COUNT(*) AS missing_count
            FROM handoffs h
            JOIN inference_requests ir
              ON ir.request_id = h.request_id
            LEFT JOIN reviewer_outcomes ro
              ON ro.handoff_id = h.handoff_id
            WHERE h.queue_status = 'closed'
              AND ir.created_at::date >= %s::date
              AND ir.created_at::date <= %s::date
              AND (%s::text IS NULL OR h.tenant_id = %s::text)
              AND (%s::text IS NULL OR COALESCE(ir.section, '__all__') = %s::text)
              AND ro.handoff_id IS NULL;
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
        missing = int((cur.fetchone() or {}).get('missing_count') or 0)

        cur.execute(
            """
            SELECT COUNT(*) AS closed_count
            FROM handoffs h
            JOIN inference_requests ir
              ON ir.request_id = h.request_id
            WHERE h.queue_status = 'closed'
              AND ir.created_at::date >= %s::date
              AND ir.created_at::date <= %s::date
              AND (%s::text IS NULL OR h.tenant_id = %s::text)
              AND (%s::text IS NULL OR COALESCE(ir.section, '__all__') = %s::text);
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
        closed = int((cur.fetchone() or {}).get('closed_count') or 0)

    return missing == 0, {'closed_handoffs': closed, 'missing_outcomes': missing}


def _write_report(path_json: Path, path_md: Path, report: dict[str, Any]) -> None:
    path_json.parent.mkdir(parents=True, exist_ok=True)
    path_md.parent.mkdir(parents=True, exist_ok=True)
    path_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')

    status = 'PASS' if report['overall_passed'] else 'BLOCKED'
    lines = [
        f'# Production Readiness Gate ({status})',
        '',
        f"- Generated at (UTC): {report['generated_at_utc']}",
        f"- Scope tenant: {report['scope']['tenant_id'] or '__all__'}",
        f"- Scope section: {report['scope']['section'] or '__all__'}",
        '',
        '## Gates',
        f"- live_rollout_passed: {report['checks']['live_rollout_passed']}",
        f"- business_kpi_passed: {report['checks']['business_kpi_passed']}",
        f"- workload_feed_coverage_passed: {report['checks']['workload_feed_coverage_passed']}",
        f"- label_coverage_passed: {report['checks']['label_coverage_passed']}",
        f"- control_recency_passed: {report['checks']['control_recency_passed']}",
        f"- overall_passed: {report['overall_passed']}",
        '',
        '## Blocking Reasons',
    ]
    if report['blocking_reasons']:
        lines.extend([f"- {item}" for item in report['blocking_reasons']])
    else:
        lines.append('- none')

    lines.extend(['', '## Control Recency'])
    for row in report['control_recency']:
        lines.append(
            f"- {row['control_type']}: status={row['status']}, age_days={row['age_days']}, "
            f"max_age_days={row['max_age_days']}"
        )
    path_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Evaluate end-to-end production readiness gates.')
    parser.add_argument('--end-date', default=_default_end_date().isoformat(), help='Gate end date YYYY-MM-DD.')
    parser.add_argument('--window-days', type=int, default=28, help='Current validation window size.')
    parser.add_argument('--baseline-days', type=int, default=28, help='Baseline window size for business KPI.')
    parser.add_argument('--tenant-id', default='', help='Optional tenant scope.')
    parser.add_argument('--section', default='', help='Optional section scope.')
    parser.add_argument('--model-variant', default='challenger', help='Model variant for rollout validation.')
    parser.add_argument('--prometheus-url', default='', help='Prometheus URL for SLO checks.')
    parser.add_argument('--skip-slo-check', action='store_true', help='Skip Prometheus check (not recommended for prod).')
    parser.add_argument('--output-json', default='', help='Optional output JSON path.')
    parser.add_argument('--output-markdown', default='', help='Optional output Markdown path.')
    parser.add_argument('--fail-on-blocked', action='store_true', help='Exit code 2 when gate is blocked.')
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip all DB-dependent checks (use when CI runner cannot reach the DB network).',
    )
    args = parser.parse_args()

    if args.skip_db:
        print(
            'Production readiness gate: SKIPPED (--skip-db). '
            'All DB-dependent checks bypassed — CI runner cannot reach the database network. '
            'Run this gate from within the cluster or via a bastion for full validation.'
        )
        sys.exit(0)

    end_date = date.fromisoformat(args.end_date)
    window_days = max(7, int(args.window_days))
    baseline_days = max(7, int(args.baseline_days))
    window_start = end_date - timedelta(days=window_days - 1)
    baseline_end = window_start - timedelta(days=1)
    baseline_start = baseline_end - timedelta(days=baseline_days - 1)

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)
    tenant_id = args.tenant_id.strip() or None
    section = args.section.strip() or None

    try:
        live_passed, live_report, live_json_path, live_md_path = validate_live_rollout(
            dsn=dsn,
            end_date_raw=end_date.isoformat(),
            stable_days_min=min(window_days, 14),
            stable_days_max=max(window_days, 28),
            min_daily_samples=50,
            min_ground_truth=50,
            min_calibration_samples=200,
            max_calibration_age_days=7,
            model_variant=args.model_variant.strip(),
            tenant_id=tenant_id,
            section=section,
            prometheus_url=args.prometheus_url.strip(),
            skip_slo_check=bool(args.skip_slo_check),
            report_json='',
            report_markdown='',
        )

        business_rows = compute_business_scorecard(
            dsn=dsn,
            window_start=window_start,
            window_end=end_date,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            tenant_id=tenant_id,
            section=section,
            model_variant='primary',
        )
        business_failed = [row for row in business_rows if row.status != 'pass']
        business_passed = len(business_failed) == 0

        with psycopg.connect(dsn, row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT to_regclass('public.operational_control_events') IS NOT NULL AS table_exists;")
                table_exists = bool((cur.fetchone() or {}).get('table_exists'))
            if not table_exists:
                control_checks = [
                    ControlCheck(
                        control_type=k,
                        passed=False,
                        age_days=None,
                        max_age_days=v,
                        status='missing_table',
                        performed_at=None,
                        evidence_uri=None,
                    )
                    for k, v in CONTROL_MAX_AGE_DAYS.items()
                ]
            else:
                control_checks = [
                    _check_control_recency(conn, control_type=control_type, max_age_days=max_age_days)
                    for control_type, max_age_days in CONTROL_MAX_AGE_DAYS.items()
                ]
            control_passed = all(item.passed for item in control_checks)

            workload_passed, workload_details = _check_workload_coverage(
                conn,
                start_date=window_start,
                end_date=end_date,
                tenant_id=tenant_id,
                section=section,
            )
            label_passed, label_details = _check_label_coverage(
                conn,
                start_date=window_start,
                end_date=end_date,
                tenant_id=tenant_id,
                section=section,
            )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while running production readiness gate. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    blocking_reasons: list[str] = []
    if not live_passed:
        blocking_reasons.append('live_rollout_validation_blocked')
    if not business_passed:
        blocking_reasons.append('business_kpi_targets_not_met')
    if not workload_passed:
        blocking_reasons.append('ops_workload_daily_has_missing_dates')
    if not label_passed:
        blocking_reasons.append('closed_handoffs_missing_outcomes')
    if not control_passed:
        blocking_reasons.append('operational_control_recency_failed')

    overall_passed = len(blocking_reasons) == 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    json_path = Path(args.output_json) if args.output_json.strip() else Path(
        f'artifacts/reports/production_readiness_gate_{stamp}.json'
    )
    md_path = Path(args.output_markdown) if args.output_markdown.strip() else Path(
        f'artifacts/reports/production_readiness_gate_{stamp}.md'
    )

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': {'tenant_id': tenant_id, 'section': section},
        'window': {
            'start_date': window_start.isoformat(),
            'end_date': end_date.isoformat(),
            'baseline_start': baseline_start.isoformat(),
            'baseline_end': baseline_end.isoformat(),
        },
        'checks': {
            'live_rollout_passed': live_passed,
            'business_kpi_passed': business_passed,
            'workload_feed_coverage_passed': workload_passed,
            'label_coverage_passed': label_passed,
            'control_recency_passed': control_passed,
        },
        'live_rollout_report': {
            'json_path': str(live_json_path),
            'markdown_path': str(live_md_path),
            'blocking_reasons': live_report.get('blocking_reasons', []),
        },
        'business_scorecard': {
            'rows': [
                {
                    'kpi_name': row.kpi_name,
                    'target_value': row.target_value,
                    'comparator': row.comparator,
                    'actual_value': row.actual_value,
                    'status': row.status,
                }
                for row in business_rows
            ],
            'failed_or_missing': [row.kpi_name for row in business_failed],
        },
        'workload_coverage': workload_details,
        'label_coverage': label_details,
        'control_recency': [asdict(item) for item in control_checks],
        'blocking_reasons': blocking_reasons,
        'overall_passed': overall_passed,
    }
    _write_report(json_path, md_path, report)

    print(f'Production readiness gate JSON: {json_path}')
    print(f'Production readiness gate MD: {md_path}')
    print(f'Status: {"PASS" if overall_passed else "BLOCKED"}')
    if blocking_reasons:
        print(f'Blocking reasons: {", ".join(blocking_reasons)}')

    if args.fail_on_blocked and not overall_passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
