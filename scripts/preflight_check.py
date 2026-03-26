from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

_DEFAULT_OR_INSECURE_SECRETS = {
    '',
    'change-me-local-dev-secret',
    'changeme',
    'change-me',
    'default',
}


def _is_prod_env(value: str) -> bool:
    return value.strip().lower() in {'prod', 'production'}


def _is_placeholder(value: str) -> bool:
    lowered = value.lower()
    return (
        'example.invalid' in lowered
        or '<' in lowered
        or 'changeme' in lowered
        or 'replace-me' in lowered
    )


def main() -> None:
    parser = argparse.ArgumentParser(description='Production preflight checks for decision platform')
    parser.add_argument(
        '--env',
        default='production',
        help='Target environment expectation (default: production)',
    )
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip Postgres connectivity check (use when CI runner cannot reach the DB network).',
    )
    args = parser.parse_args()

    try:
        settings = get_settings()
    except Exception as exc:
        print('Preflight check failed:')
        print(f'  - ERROR: Invalid configuration: {exc}')
        sys.exit(1)
    target_is_prod = _is_prod_env(args.env)

    errors: list[str] = []
    warnings: list[str] = []

    if target_is_prod and not _is_prod_env(settings.app_env):
        errors.append('APP_ENV must be set to production/prod for production deployment checks.')

    if target_is_prod and not settings.auth_enabled:
        errors.append('AUTH_ENABLED must be true in production.')

    if target_is_prod:
        jwt_secret = settings.jwt_secret_key.strip()
        if jwt_secret.lower() in _DEFAULT_OR_INSECURE_SECRETS or len(jwt_secret) < 24:
            errors.append('JWT_SECRET_KEY must be a strong non-default secret (>=24 chars) in production.')

    if target_is_prod and not settings.use_postgres:
        errors.append('USE_POSTGRES must be true in production.')

    if target_is_prod and settings.use_postgres:
        dsn = settings.postgres_dsn.lower()
        if 'postgres:postgres@' in dsn:
            warnings.append('POSTGRES_DSN still uses default postgres credentials.')

    if settings.rate_limit_enabled and not settings.use_redis:
        errors.append('RATE_LIMIT_ENABLED=true requires USE_REDIS=true.')

    if target_is_prod and not settings.rate_limit_enabled:
        warnings.append('RATE_LIMIT_ENABLED=false; tenant/user throttling is disabled in production.')

    if target_is_prod and settings.model_shadow_enabled and not settings.use_postgres:
        warnings.append('MODEL_SHADOW_ENABLED=true but USE_POSTGRES=false; shadow/canary telemetry will not persist.')

    if settings.canary_rollout_enabled and not settings.model_shadow_enabled:
        errors.append('CANARY_ROLLOUT_ENABLED=true requires MODEL_SHADOW_ENABLED=true.')

    if settings.canary_rollout_enabled and settings.canary_traffic_percent <= 0 and not settings.model_ops_rollout_from_db:
        warnings.append('CANARY_ROLLOUT_ENABLED=true but CANARY_TRAFFIC_PERCENT=0 and DB rollout control is disabled.')

    if settings.tracing_enabled and not settings.otlp_endpoint.strip():
        errors.append('TRACING_ENABLED=true requires OTLP_ENDPOINT.')

    if target_is_prod and settings.tracing_enabled and settings.otlp_insecure:
        warnings.append('OTLP_INSECURE=true is not recommended for production tracing transport.')

    if target_is_prod:
        required_webhooks = [
            'ALERTMANAGER_PAGER_WEBHOOK_URL',
            'ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL',
            'ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL',
            'ALERTMANAGER_TICKET_WEBHOOK_URL',
        ]
        for key in required_webhooks:
            value = str(os.environ.get(key, '')).strip()
            if not value:
                warnings.append(f'{key} is not set in environment.')
            elif _is_placeholder(value):
                errors.append(f'{key} appears placeholder-like.')

        oncall_path = Path('ops/oncall.production.json')
        if not oncall_path.exists():
            warnings.append(f'{oncall_path} is missing (required for on-call audit automation).')

    if settings.routing_model_backend.strip().lower() == 'http' and not settings.model_serving_url.strip():
        errors.append('ROUTING_MODEL_BACKEND=http requires MODEL_SERVING_URL.')

    if target_is_prod and settings.model_ops_quality_gate_min_sample_size < 50:
        warnings.append(
            'MODEL_OPS_QUALITY_GATE_MIN_SAMPLE_SIZE is below 50; canary promotion may be statistically weak.',
        )

    if settings.event_bus_backend.strip().lower() == 'pubsub' and not settings.pubsub_project_id.strip():
        errors.append('EVENT_BUS_BACKEND=pubsub requires PUBSUB_PROJECT_ID.')

    if settings.workflow_backend.strip().lower() == 'temporal' and not settings.temporal_target_host.strip():
        errors.append('WORKFLOW_BACKEND=temporal requires TEMPORAL_TARGET_HOST.')

    if target_is_prod and settings.use_postgres and not args.skip_db:
        try:
            dsn = to_psycopg_dsn(settings.postgres_dsn)
            with psycopg.connect(dsn, connect_timeout=5) as conn:
                with conn.cursor() as cur:
                    cur.execute('SELECT 1;')
        except Exception as exc:
            errors.append(f'Cannot connect to Postgres (check POSTGRES_DSN / port): {exc}')
        else:
            try:
                with psycopg.connect(dsn, connect_timeout=5) as conn:
                    with conn.cursor() as cur:
                        missing_tables = []
                        for table in (
                            'tenants', 'inference_requests', 'inference_results',
                            'handoffs', 'evaluation_daily_dataset', 'operational_control_events',
                            'ops_workload_daily', 'model_rollout_config', 'business_kpi_targets',
                        ):
                            cur.execute(
                                "SELECT to_regclass(%s) IS NOT NULL AS exists;",
                                (f'public.{table}',),
                            )
                            row = cur.fetchone()
                            if not (row and row[0]):
                                missing_tables.append(table)
                        if missing_tables:
                            errors.append(
                                f'Database is missing required tables (run migrations): {", ".join(missing_tables)}'
                            )
            except Exception:
                pass
    elif target_is_prod and settings.use_postgres and args.skip_db:
        warnings.append('Postgres connectivity check skipped (--skip-db). Validate DB access from the deployed pods.')

    if settings.observability_log_format.strip().lower() != 'json':
        warnings.append('OBSERVABILITY_LOG_FORMAT is not json.')

    if not settings.metrics_enabled:
        warnings.append('METRICS_ENABLED=false may break monitoring dashboards/alerts.')

    if errors:
        print('Preflight check failed:')
        for item in errors:
            print(f'  - ERROR: {item}')
        for item in warnings:
            print(f'  - WARN : {item}')
        sys.exit(1)

    print('Preflight check passed.')
    for item in warnings:
        print(f'  - WARN : {item}')


if __name__ == '__main__':
    main()
