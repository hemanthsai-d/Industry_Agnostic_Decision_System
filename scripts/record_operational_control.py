from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import sys
from uuid import uuid4

import psycopg
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

CONTROL_TYPES = {
    'incident_endpoint_verification',
    'oncall_schedule_audit',
    'secret_rotation',
    'access_review',
    'incident_drill',
    'rollback_drill',
    'load_test',
    'soak_test',
    'failure_test',
}

STATUSES = {'pass', 'fail', 'waived'}


def record_control_event(
    *,
    dsn: str,
    control_type: str,
    status: str,
    control_scope: str,
    performed_by: str,
    evidence_uri: str,
    details: dict,
    performed_at: datetime | None = None,
) -> str:
    control_type_norm = control_type.strip().lower()
    status_norm = status.strip().lower()
    if control_type_norm not in CONTROL_TYPES:
        raise ValueError(f'Unsupported control_type: {control_type}')
    if status_norm not in STATUSES:
        raise ValueError(f'Unsupported status: {status}')
    if not performed_by.strip():
        raise ValueError('performed_by is required.')
    if not evidence_uri.strip():
        raise ValueError('evidence_uri is required.')
    scope = control_scope.strip() or 'global'
    ts = performed_at or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    event_id = str(uuid4())
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO operational_control_events (
                  event_id,
                  control_type,
                  status,
                  control_scope,
                  performed_at,
                  performed_by,
                  evidence_uri,
                  details
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    event_id,
                    control_type_norm,
                    status_norm,
                    scope,
                    ts,
                    performed_by.strip(),
                    evidence_uri.strip(),
                    Jsonb(details),
                ),
            )
        conn.commit()
    return event_id


def main() -> None:
    parser = argparse.ArgumentParser(description='Record an operational control event for production evidence.')
    parser.add_argument('--control-type', required=True, choices=sorted(CONTROL_TYPES))
    parser.add_argument('--status', required=True, choices=sorted(STATUSES))
    parser.add_argument('--scope', default='global', help='Control scope (tenant/team/global).')
    parser.add_argument('--performed-by', required=True, help='User or service performing this control.')
    parser.add_argument('--evidence-uri', required=True, help='Evidence link/path (ticket URL, screenshot path, report path).')
    parser.add_argument('--performed-at', default='', help='Optional ISO timestamp (UTC preferred).')
    parser.add_argument('--details-json', default='{}', help='Optional JSON object with extra context.')
    args = parser.parse_args()

    performed_at = None
    if args.performed_at.strip():
        performed_at = datetime.fromisoformat(args.performed_at.strip().replace('Z', '+00:00'))

    try:
        details = json.loads(args.details_json)
    except json.JSONDecodeError as exc:
        print(f'Invalid --details-json: {exc}')
        sys.exit(1)
    if not isinstance(details, dict):
        print('--details-json must be a JSON object.')
        sys.exit(1)

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        event_id = record_control_event(
            dsn=dsn,
            control_type=args.control_type,
            status=args.status,
            control_scope=args.scope,
            performed_by=args.performed_by,
            evidence_uri=args.evidence_uri,
            details=details,
            performed_at=performed_at,
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while recording operational control event. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)
    except ValueError as exc:
        print(f'Validation error: {exc}')
        sys.exit(1)

    print(f'Recorded operational control event: {event_id}')


if __name__ == '__main__':
    main()
