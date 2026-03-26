from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.record_operational_control import record_control_event

REQUIRED_TEAMS = {'platform_oncall', 'model_oncall'}
REQUIRED_ESCALATION_MINUTES = [5, 15, 30]


def _load_config(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f'On-call config file not found: {path}')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('On-call config must be a JSON object.')
    return data


def _validate_contact(contact: dict, path: str, errors: list[str]) -> None:
    if not isinstance(contact, dict):
        errors.append(f'{path} must be an object.')
        return
    name = str(contact.get('name', '')).strip()
    timezone_name = str(contact.get('timezone', '')).strip()
    email = str(contact.get('email', '')).strip()
    phone = str(contact.get('phone', '')).strip()
    if not name:
        errors.append(f'{path}.name is required.')
    if not timezone_name:
        errors.append(f'{path}.timezone is required.')
    if not email and not phone:
        errors.append(f'{path} requires at least one contact method (email or phone).')
    if email and ('example.com' in email.lower() or 'test' in email.lower()):
        errors.append(f'{path}.email appears placeholder-like.')
    if phone and ('555' in phone or '0000' in phone):
        errors.append(f'{path}.phone appears placeholder-like.')


def audit_config(config: dict) -> tuple[bool, list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []

    teams = config.get('teams')
    if not isinstance(teams, dict):
        errors.append('teams object is required.')
        return False, errors, warnings

    missing_teams = REQUIRED_TEAMS - set(teams)
    for team in sorted(missing_teams):
        errors.append(f'teams.{team} is missing.')

    for team_name in sorted(REQUIRED_TEAMS & set(teams)):
        team_obj = teams.get(team_name)
        if not isinstance(team_obj, dict):
            errors.append(f'teams.{team_name} must be an object.')
            continue
        for role in ['primary', 'backup']:
            roster = team_obj.get(role)
            if not isinstance(roster, list) or not roster:
                errors.append(f'teams.{team_name}.{role} must be a non-empty array.')
                continue
            for idx, contact in enumerate(roster):
                _validate_contact(contact, f'teams.{team_name}.{role}[{idx}]', errors)

    escalation = config.get('escalation_policy')
    if not isinstance(escalation, list) or not escalation:
        errors.append('escalation_policy must be a non-empty array.')
    else:
        after_values = []
        for idx, item in enumerate(escalation):
            if not isinstance(item, dict):
                errors.append(f'escalation_policy[{idx}] must be an object.')
                continue
            after_raw = item.get('after_minutes')
            try:
                after = int(after_raw)
            except (TypeError, ValueError):
                errors.append(f'escalation_policy[{idx}].after_minutes must be an integer.')
                continue
            after_values.append(after)
            targets = item.get('targets')
            if not isinstance(targets, list) or not targets:
                errors.append(f'escalation_policy[{idx}].targets must be a non-empty array.')

        for required_min in REQUIRED_ESCALATION_MINUTES:
            if required_min not in after_values:
                errors.append(f'escalation_policy missing required tier at {required_min} minutes.')

    if not errors:
        generated_at = str(config.get('generated_at_utc', '')).strip()
        if not generated_at:
            warnings.append('generated_at_utc is missing; add generation timestamp for audit traceability.')

    return len(errors) == 0, errors, warnings


def write_report(
    *,
    output_path: Path,
    config_path: Path,
    passed: bool,
    errors: list[str],
    warnings: list[str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    status = 'PASS' if passed else 'FAIL'
    lines = [
        f'# On-Call Audit Report ({status})',
        '',
        f'- Generated at (UTC): {datetime.now(timezone.utc).isoformat()}',
        f'- Config path: {config_path}',
        '',
        '## Errors',
    ]
    if errors:
        lines.extend([f'- {err}' for err in errors])
    else:
        lines.append('- none')
    lines.extend(['', '## Warnings'])
    if warnings:
        lines.extend([f'- {warn}' for warn in warnings])
    else:
        lines.append('- none')
    output_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Audit production on-call roster and escalation config.')
    parser.add_argument('--config', default='ops/oncall.production.json', help='Path to on-call JSON config.')
    parser.add_argument('--output', default='', help='Optional report markdown output path.')
    parser.add_argument('--record-event', action='store_true', help='Record PASS/FAIL into operational_control_events.')
    parser.add_argument('--performed-by', default='', help='Required with --record-event.')
    parser.add_argument('--evidence-uri', default='', help='Required with --record-event.')
    parser.add_argument('--scope', default='global', help='Control scope for recorded event.')
    parser.add_argument('--fail-on-warning', action='store_true', help='Fail audit if warnings are present.')
    args = parser.parse_args()

    config_path = Path(args.config)
    try:
        config = _load_config(config_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f'Config load error: {exc}')
        sys.exit(1)

    passed, errors, warnings = audit_config(config)
    if args.fail_on_warning and warnings:
        passed = False
        errors.append('Warnings are treated as failures (--fail-on-warning).')

    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    output_path = Path(args.output) if args.output.strip() else Path(f'artifacts/reports/oncall_audit_{stamp}.md')
    write_report(
        output_path=output_path,
        config_path=config_path,
        passed=passed,
        errors=errors,
        warnings=warnings,
    )

    print(f'On-call audit report: {output_path}')
    print(f'Status: {"PASS" if passed else "FAIL"}')
    if errors:
        for err in errors:
            print(f'  - ERROR: {err}')
    if warnings:
        for warn in warnings:
            print(f'  - WARN : {warn}')

    if args.record_event:
        performed_by = args.performed_by.strip()
        evidence_uri = args.evidence_uri.strip() or str(output_path)
        if not performed_by:
            print('--performed-by is required when --record-event is used.')
            sys.exit(1)
        settings = get_settings()
        dsn = to_psycopg_dsn(settings.postgres_dsn)
        details = {
            'config_path': str(config_path),
            'report_path': str(output_path),
            'errors': errors,
            'warnings': warnings,
        }
        try:
            event_id = record_control_event(
                dsn=dsn,
                control_type='oncall_schedule_audit',
                status='pass' if passed else 'fail',
                control_scope=args.scope,
                performed_by=performed_by,
                evidence_uri=evidence_uri,
                details=details,
            )
            print(f'Recorded control event: {event_id}')
        except psycopg.OperationalError as exc:
            print(
                'Database connection failed while recording on-call audit event. '
                'Ensure Postgres is running and migrations are applied.\n'
                f'Details: {exc}'
            )
            sys.exit(1)

    if not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
