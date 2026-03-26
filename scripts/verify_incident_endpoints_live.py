from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.configure_alertmanager_prod import _is_placeholder
from scripts.record_operational_control import record_control_event

ENDPOINT_ENV_KEYS = {
    'pager': 'ALERTMANAGER_PAGER_WEBHOOK_URL',
    'model_oncall': 'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL',
    'platform_oncall': 'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL',
    'ticket': 'ALERTMANAGER_TICKET_WEBHOOK_URL',
}


def _resolve_endpoint(key: str) -> str:
    return str(os.environ.get(key, '')).strip()


def _run_live_drill(mode: str) -> tuple[int, str]:
    cmd = f'ALERT_E2E_MODE={mode} ./scripts/run_alertmanager_e2e.sh'
    proc = subprocess.run(
        ['/bin/zsh', '-lc', cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    output = (proc.stdout or '') + (proc.stderr or '')
    return proc.returncode, output.strip()


def _write_report(
    *,
    output_path: Path,
    mode: str,
    passed: bool,
    endpoint_map: dict[str, str],
    drill_exit_code: int | None,
    drill_output: str,
    evidence_links: dict[str, str],
    errors: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status = 'PASS' if passed else 'FAIL'
    lines = [
        f'# Incident Endpoint Verification ({status})',
        '',
        f'- Generated at (UTC): {datetime.now(timezone.utc).isoformat()}',
        f'- Mode: {mode}',
        '',
        '## Endpoint Status',
    ]
    for route in ['pager', 'model_oncall', 'platform_oncall', 'ticket']:
        endpoint = endpoint_map.get(route, '')
        redacted = endpoint
        if endpoint.startswith('http'):
            redacted = endpoint.split('?', 1)[0]
        lines.append(f'- {route}: `{redacted or "missing"}`')

    lines.extend(['', '## Evidence Links'])
    for route in ['pager', 'model_oncall', 'platform_oncall', 'ticket']:
        lines.append(f"- {route}: `{evidence_links.get(route, '') or 'missing'}`")

    lines.extend(['', '## Drill Result'])
    if drill_exit_code is None:
        lines.append('- drill execution: skipped')
    else:
        lines.append(f'- drill exit code: {drill_exit_code}')
        lines.append('')
        lines.append('```text')
        lines.append(drill_output[:5000] if drill_output else '(no output)')
        lines.append('```')

    lines.extend(['', '## Errors'])
    if errors:
        lines.extend([f'- {err}' for err in errors])
    else:
        lines.append('- none')

    output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Verify real incident endpoints and optionally run live Alertmanager drill.')
    parser.add_argument('--mode', default='live', choices=['live', 'local'], help='Alert drill mode.')
    parser.add_argument('--run-drill', action='store_true', help='Run Alertmanager E2E drill command.')
    parser.add_argument('--output', default='', help='Optional report markdown path.')
    parser.add_argument('--record-event', action='store_true', help='Record result into operational_control_events.')
    parser.add_argument('--performed-by', default='', help='Required with --record-event.')
    parser.add_argument('--scope', default='global', help='Control scope for recorded event.')
    parser.add_argument('--evidence-pager', default='', help='Ticket/link/screenshot proving pager endpoint delivery.')
    parser.add_argument('--evidence-model-oncall', default='', help='Evidence link for model on-call route.')
    parser.add_argument('--evidence-platform-oncall', default='', help='Evidence link for platform on-call route.')
    parser.add_argument('--evidence-ticket', default='', help='Evidence link for ticket route.')
    args = parser.parse_args()

    endpoint_map = {route: _resolve_endpoint(env_key) for route, env_key in ENDPOINT_ENV_KEYS.items()}
    errors: list[str] = []
    for route, value in endpoint_map.items():
        if not value:
            errors.append(f'{ENDPOINT_ENV_KEYS[route]} is missing.')
        elif _is_placeholder(value):
            errors.append(f'{ENDPOINT_ENV_KEYS[route]} is still placeholder-like.')

    evidence_links = {
        'pager': args.evidence_pager.strip(),
        'model_oncall': args.evidence_model_oncall.strip(),
        'platform_oncall': args.evidence_platform_oncall.strip(),
        'ticket': args.evidence_ticket.strip(),
    }
    if args.mode == 'live':
        for route, link in evidence_links.items():
            if not link:
                errors.append(f'Evidence link missing for {route} route.')

    drill_exit_code: int | None = None
    drill_output = ''
    if args.run_drill:
        drill_exit_code, drill_output = _run_live_drill(args.mode)
        if drill_exit_code != 0:
            errors.append(f'Alertmanager E2E drill failed with exit code {drill_exit_code}.')

    passed = len(errors) == 0
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_path = Path(args.output) if args.output.strip() else Path(f'artifacts/reports/incident_endpoint_verify_{stamp}.md')
    _write_report(
        output_path=output_path,
        mode=args.mode,
        passed=passed,
        endpoint_map=endpoint_map,
        drill_exit_code=drill_exit_code,
        drill_output=drill_output,
        evidence_links=evidence_links,
        errors=errors,
    )

    print(f'Incident endpoint report: {output_path}')
    print(f'Status: {"PASS" if passed else "FAIL"}')
    if errors:
        for err in errors:
            print(f'  - ERROR: {err}')

    if args.record_event:
        performed_by = args.performed_by.strip()
        if not performed_by:
            print('--performed-by is required when --record-event is used.')
            sys.exit(1)
        settings = get_settings()
        dsn = to_psycopg_dsn(settings.postgres_dsn)
        details = {
            'mode': args.mode,
            'run_drill': bool(args.run_drill),
            'endpoints': endpoint_map,
            'evidence_links': evidence_links,
            'errors': errors,
            'report_path': str(output_path),
        }
        try:
            event_id = record_control_event(
                dsn=dsn,
                control_type='incident_endpoint_verification',
                status='pass' if passed else 'fail',
                control_scope=args.scope,
                performed_by=performed_by,
                evidence_uri=str(output_path),
                details=details,
            )
            print(f'Recorded control event: {event_id}')
        except psycopg.OperationalError as exc:
            print(
                'Database connection failed while recording endpoint verification event. '
                'Ensure Postgres is running and migrations are applied.\n'
                f'Details: {exc}'
            )
            sys.exit(1)

    if not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
