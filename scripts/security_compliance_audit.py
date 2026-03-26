from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.configure_alertmanager_prod import _is_placeholder

CONTROL_RECENCY_DEFAULTS = {
    'secret_rotation': 90,
    'access_review': 90,
    'oncall_schedule_audit': 30,
    'incident_endpoint_verification': 30,
}


def _is_prod_env(value: str) -> bool:
    return value.strip().lower() in {'prod', 'production'}


def _check_control_recency(
    conn: psycopg.Connection,
    *,
    control_type: str,
    max_age_days: int,
) -> tuple[bool, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT to_regclass('public.operational_control_events') IS NOT NULL AS table_exists;")
        row = cur.fetchone()
        if not row or not bool(row['table_exists']):
            return False, {
                'control_type': control_type,
                'status': 'missing_table',
                'max_age_days': max_age_days,
            }
        cur.execute(
            """
            SELECT performed_at, performed_by, evidence_uri, details
            FROM operational_control_events
            WHERE control_type = %s
              AND status = 'pass'
            ORDER BY performed_at DESC
            LIMIT 1;
            """,
            (control_type,),
        )
        latest = cur.fetchone()
    if latest is None:
        return False, {
            'control_type': control_type,
            'status': 'missing_pass_event',
            'max_age_days': max_age_days,
        }

    performed_at = latest['performed_at']
    age_days = max(0, (date.today() - performed_at.date()).days)
    details = latest['details'] if isinstance(latest.get('details'), dict) else {}
    if control_type == 'incident_endpoint_verification':
        mode = str(details.get('mode', '')).strip().lower()
        if mode != 'live':
            return False, {
                'control_type': control_type,
                'status': 'not_live_mode',
                'max_age_days': max_age_days,
                'age_days': age_days,
                'performed_at': performed_at.isoformat(),
                'performed_by': str(latest['performed_by']),
                'evidence_uri': str(latest['evidence_uri']),
            }

    return age_days <= max_age_days, {
        'control_type': control_type,
        'status': 'ok' if age_days <= max_age_days else 'stale',
        'max_age_days': max_age_days,
        'age_days': age_days,
        'performed_at': performed_at.isoformat(),
        'performed_by': str(latest['performed_by']),
        'evidence_uri': str(latest['evidence_uri']),
    }


def _write_report(
    *,
    output_json: Path,
    output_md: Path,
    report: dict[str, Any],
) -> None:
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_md.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')

    status = 'PASS' if report['passed'] else 'FAIL'
    lines = [
        f'# Security And Compliance Audit ({status})',
        '',
        f"- Generated at (UTC): {report['generated_at_utc']}",
        '',
        '## Errors',
    ]
    if report['errors']:
        lines.extend([f"- {item}" for item in report['errors']])
    else:
        lines.append('- none')

    lines.extend(['', '## Warnings'])
    if report['warnings']:
        lines.extend([f"- {item}" for item in report['warnings']])
    else:
        lines.append('- none')

    lines.extend(['', '## Control Recency'])
    for item in report['control_recency']:
        lines.append(
            f"- {item['control_type']}: status={item['status']}, "
            f"age_days={item.get('age_days', 'n/a')}, max_age_days={item['max_age_days']}"
        )

    output_md.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Run security/compliance hardening audit checks.')
    parser.add_argument('--env', default='production', help='Expected environment (production/prod).')
    parser.add_argument('--require-production', action='store_true', help='Fail if APP_ENV is not prod/prod.')
    parser.add_argument(
        '--secret-rotation-max-days',
        type=int,
        default=CONTROL_RECENCY_DEFAULTS['secret_rotation'],
    )
    parser.add_argument(
        '--access-review-max-days',
        type=int,
        default=CONTROL_RECENCY_DEFAULTS['access_review'],
    )
    parser.add_argument(
        '--oncall-audit-max-days',
        type=int,
        default=CONTROL_RECENCY_DEFAULTS['oncall_schedule_audit'],
    )
    parser.add_argument(
        '--endpoint-verify-max-days',
        type=int,
        default=CONTROL_RECENCY_DEFAULTS['incident_endpoint_verification'],
    )
    parser.add_argument('--output-json', default='', help='Optional JSON report output.')
    parser.add_argument('--output-markdown', default='', help='Optional Markdown report output.')
    parser.add_argument('--fail-on-warning', action='store_true', help='Treat warnings as errors.')
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    errors: list[str] = []
    warnings: list[str] = []

    target_prod = _is_prod_env(args.env)
    if args.require_production and not _is_prod_env(settings.app_env):
        errors.append('APP_ENV must be production/prod.')
    elif target_prod and not _is_prod_env(settings.app_env):
        warnings.append('APP_ENV is not production/prod.')

    if target_prod and not settings.auth_enabled:
        errors.append('AUTH_ENABLED must be true.')
    if target_prod and settings.jwt_secret_key.strip().lower() in {'', 'change-me-local-dev-secret', 'changeme'}:
        errors.append('JWT_SECRET_KEY is insecure/default.')
    if target_prod and not settings.rate_limit_enabled:
        warnings.append('RATE_LIMIT_ENABLED is false in production expectation.')
    if target_prod and not settings.use_redis:
        warnings.append('USE_REDIS is false; rate-limit and queue protections may be degraded.')
    if target_prod and not settings.use_postgres:
        errors.append('USE_POSTGRES must be true.')

    for env_key in [
        'ALERTMANAGER_PAGER_WEBHOOK_URL',
        'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL',
        'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL',
        'ALERTMANAGER_TICKET_WEBHOOK_URL',
    ]:
        raw = str(os.environ.get(env_key, '')).strip()
        if not raw:
            warnings.append(f'{env_key} is not present in environment for this audit process.')
        elif _is_placeholder(raw):
            errors.append(f'{env_key} appears placeholder-like.')

    control_recency: list[dict[str, Any]] = []
    control_checks = [
        ('secret_rotation', max(1, int(args.secret_rotation_max_days))),
        ('access_review', max(1, int(args.access_review_max_days))),
        ('oncall_schedule_audit', max(1, int(args.oncall_audit_max_days))),
        ('incident_endpoint_verification', max(1, int(args.endpoint_verify_max_days))),
    ]
    try:
        with psycopg.connect(dsn) as conn:
            for control_type, max_age_days in control_checks:
                ok, detail = _check_control_recency(
                    conn,
                    control_type=control_type,
                    max_age_days=max_age_days,
                )
                control_recency.append(detail)
                if not ok:
                    errors.append(
                        f'Control recency check failed for {control_type}: status={detail.get("status")}, '
                        f'max_age_days={max_age_days}.'
                    )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while running security/compliance audit. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    if args.fail_on_warning and warnings:
        errors.append('Warnings are treated as failures (--fail-on-warning).')

    passed = len(errors) == 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_json = Path(args.output_json) if args.output_json.strip() else Path(f'artifacts/reports/security_audit_{stamp}.json')
    output_md = (
        Path(args.output_markdown)
        if args.output_markdown.strip()
        else Path(f'artifacts/reports/security_audit_{stamp}.md')
    )
    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'passed': passed,
        'errors': errors,
        'warnings': warnings,
        'control_recency': control_recency,
        'environment': {
            'app_env': settings.app_env,
            'auth_enabled': settings.auth_enabled,
            'use_postgres': settings.use_postgres,
            'use_redis': settings.use_redis,
            'rate_limit_enabled': settings.rate_limit_enabled,
        },
    }
    _write_report(output_json=output_json, output_md=output_md, report=report)

    print(f'Security audit report JSON: {output_json}')
    print(f'Security audit report MD: {output_md}')
    print(f'Status: {"PASS" if passed else "FAIL"}')
    if errors:
        for err in errors:
            print(f'  - ERROR: {err}')
    if warnings:
        for warn in warnings:
            print(f'  - WARN : {warn}')

    if not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
