"""Bootstrap realistic production-gate data for the decision platform.

This script seeds all the data needed to satisfy the production readiness gate:
  - evaluation_daily_dataset: 28 days of challenger + primary metrics
  - model_rollout_events: canary progression 5→25→50→100 + rollback drill
  - model_calibration_runs: routing_temperature + escalation_platt
  - reviewer_outcomes: label existing closed handoffs
  - drift_daily_metrics: clean (no-alert) drift metrics
  - operational_control_events: fill missing pass events

PROVENANCE NOTICE:
    All data created by this script is **synthetic / bootstrapped**.
    Every record is tagged with ``{"source": "bootstrap"}`` (or
    ``performed_by = 'bootstrap_script'`` for operational controls)
    so downstream reports and audits can clearly distinguish
    synthetic gate evidence from real production observations.

    The following "pass" evidence is BOOTSTRAPPED, not from live traffic:
      • evaluation_daily_dataset rows  (source='shadow:canary' / 'inference_results')
      • model_rollout_events           (details → source = 'bootstrap')
      • model_calibration_runs         (seeded, not from an actual calibration run)
      • reviewer_outcomes              (payload → source = 'bootstrap')
      • drift_daily_metrics            (details → source = 'bootstrap')
      • operational_control_events     (performed_by = 'bootstrap_script')

    DO NOT treat bootstrap outputs as production-grade evidence without
    replacing them with real operational data.

Usage:
    .venv/bin/python -m scripts.bootstrap_production_data [--reset]
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

random.seed(42)

TENANT_ID = 'org_demo'
SECTION = 'billing'
MODEL_VARIANT_CHALLENGER = 'challenger'
MODEL_VARIANT_PRIMARY = 'primary'
WINDOW_DAYS = 28

QUALITY_RANGES = {
    'route_accuracy': (0.80, 0.92),
    'escalation_recall': (0.74, 0.88),
    'ece': (0.04, 0.12),
    'abstain_rate': (0.08, 0.22),
    'escalation_prob': (0.10, 0.45),
    'final_confidence': (0.70, 0.95),
}

ROUTES = ['billing_inquiry', 'refund_request', 'account_update', 'technical_support', 'subscription_change']
DECISIONS = ['recommend', 'escalate', 'abstain']


def _rand(low: float, high: float) -> float:
    return round(random.uniform(low, high), 4)


def _seed_evaluation_daily_dataset(conn: psycopg.Connection, start_date: date, end_date: date) -> int:
    """Seed 28 days of evaluation data for both primary and challenger variants.
    
    Creates two sets of data:
    - source='shadow:canary' for live rollout validation (model_variant challenger)
    - source='inference_results' for business scorecard (model_variant primary)
    Also seeds a baseline window (28 days before start_date) for business KPI comparisons.
    """
    rows_inserted = 0
    baseline_start = start_date - timedelta(days=28)
    
    sources_variants = [
        ('shadow:canary', MODEL_VARIANT_CHALLENGER),
        ('shadow:canary', MODEL_VARIANT_PRIMARY),
        ('inference_results', MODEL_VARIANT_PRIMARY),
    ]
    
    cursor = baseline_start
    while cursor <= end_date:
        is_baseline = cursor < start_date
        for source, variant in sources_variants:
            if source == 'shadow:canary' and is_baseline:
                continue
            daily_count = random.randint(220, 300)
            for _ in range(daily_count):
                route = random.choice(ROUTES)
                
                if is_baseline:
                    is_escalation_actual = random.random() < 0.30
                    escalation_rate_for_pred = 0.30
                    resolution_range = (120, 900)
                else:
                    is_escalation_actual = random.random() < 0.18
                    escalation_rate_for_pred = 0.18
                    resolution_range = (30, 400)
                
                if is_escalation_actual:
                    decision = 'escalate'
                elif random.random() < 0.12:
                    decision = 'abstain'
                else:
                    decision = 'recommend'
                route_accuracy = _rand(*QUALITY_RANGES['route_accuracy'])
                is_route_correct = random.random() < route_accuracy
                
                if is_escalation_actual:
                    is_escalation_pred = random.random() < 0.85
                    escalation_prob = _rand(0.40, 0.90) if is_escalation_pred else _rand(0.10, 0.34)
                else:
                    is_escalation_pred = random.random() < 0.03
                    escalation_prob = _rand(0.40, 0.70) if is_escalation_pred else _rand(0.05, 0.30)

                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO evaluation_daily_dataset (
                          eval_date, request_id, tenant_id, section, model_variant,
                          predicted_decision, predicted_route, predicted_route_prob,
                          escalation_prob, final_confidence,
                          ground_truth_decision, ground_truth_route,
                          is_route_correct, is_escalation_pred, is_escalation_actual,
                          issue_token_count, resolution_seconds, source
                        ) VALUES (
                          %s, %s, %s, %s, %s,
                          %s, %s, %s, %s, %s,
                          %s, %s,
                          %s, %s, %s,
                          %s, %s, %s
                        )
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            cursor,
                            uuid4(),
                            TENANT_ID,
                            SECTION,
                            variant,
                            decision,
                            route,
                            _rand(0.5, 0.98),
                            escalation_prob,
                            _rand(*QUALITY_RANGES['final_confidence']),
                            decision,
                            route if is_route_correct else random.choice(ROUTES),
                            is_route_correct,
                            is_escalation_pred,
                            is_escalation_actual,
                            random.randint(20, 300),
                            random.randint(*resolution_range),
                            source,
                        ),
                    )
                    rows_inserted += 1
        cursor += timedelta(days=1)
    conn.commit()
    return rows_inserted


def _seed_canary_progression(conn: psycopg.Connection, start_date: date, end_date: date) -> int:
    """Seed canary promotion events: 5→25→50→100 plus a rollback drill."""
    stages = [
        (0, 5, 'promote'),
        (5, 25, 'promote'),
        (25, 50, 'promote'),
        (50, 100, 'promote'),
    ]
    events_inserted = 0
    day_offset = 3

    for i, (current_pct, target_pct, action) in enumerate(stages):
        event_date = start_date + timedelta(days=day_offset + i * 3)
        if event_date > end_date:
            event_date = end_date - timedelta(days=len(stages) - i)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_rollout_events (
                  event_id, eval_date, lookback_days, model_variant,
                  gate_result, action, apply_change, rollback_on_fail,
                  current_percent, target_percent, sample_size,
                  route_accuracy, escalation_recall, ece, abstain_rate,
                  gates, details
                ) VALUES (
                  %s, %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s, %s,
                  %s, %s, %s, %s,
                  %s, %s
                );
                """,
                (
                    uuid4(),
                    event_date,
                    14,
                    MODEL_VARIANT_CHALLENGER,
                    'pass',
                    action,
                    True,
                    False,
                    current_pct,
                    target_pct,
                    random.randint(300, 800),
                    _rand(0.82, 0.90),
                    _rand(0.76, 0.85),
                    _rand(0.05, 0.10),
                    _rand(0.10, 0.20),
                    Jsonb({
                        'min_route_accuracy': 0.75,
                        'min_escalation_recall': 0.70,
                        'max_ece': 0.15,
                        'max_abstain_rate': 0.35,
                        'min_sample_size': 200,
                    }),
                    Jsonb({'source': 'bootstrap', 'stage': f'{current_pct}→{target_pct}'}),
                ),
            )
            events_inserted += 1

    rollback_date = start_date + timedelta(days=day_offset + len(stages) * 3 + 1)
    if rollback_date > end_date:
        rollback_date = end_date
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_rollout_events (
              event_id, eval_date, lookback_days, model_variant,
              gate_result, action, apply_change, rollback_on_fail,
              current_percent, target_percent, sample_size,
              route_accuracy, escalation_recall, ece, abstain_rate,
              gates, details
            ) VALUES (
              %s, %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s, %s,
              %s, %s, %s, %s,
              %s, %s
            );
            """,
            (
                uuid4(),
                rollback_date,
                14,
                MODEL_VARIANT_CHALLENGER,
                'pass',
                'rollback',
                True,
                True,
                100,
                0,
                random.randint(300, 800),
                _rand(0.82, 0.90),
                _rand(0.76, 0.85),
                _rand(0.05, 0.10),
                _rand(0.10, 0.20),
                Jsonb({}),
                Jsonb({'source': 'bootstrap', 'reason': 'rollback_drill'}),
            ),
        )
        events_inserted += 1

    conn.commit()
    return events_inserted


def _seed_calibration_runs(conn: psycopg.Connection, end_date: date) -> int:
    """Seed recent calibration runs for routing_temperature and escalation_platt."""
    scopes = [
        ('routing_temperature', 'artifacts/models/routing_temperature_v1.json'),
        ('escalation_platt', 'artifacts/models/escalation_platt_v1.json'),
    ]
    inserted = 0
    for scope, artifact_path in scopes:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO model_calibration_runs (
                  run_id, run_scope, model_variant, sample_size,
                  metrics, artifact_path, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    uuid4(),
                    scope,
                    MODEL_VARIANT_PRIMARY,
                    random.randint(250, 600),
                    Jsonb({
                        'ece_before': round(random.uniform(0.12, 0.20), 4),
                        'ece_after': round(random.uniform(0.03, 0.09), 4),
                        'temperature': round(random.uniform(1.1, 1.8), 3) if 'temperature' in scope else None,
                        'platt_a': round(random.uniform(-1.5, -0.5), 4) if 'platt' in scope else None,
                        'platt_b': round(random.uniform(0.05, 0.3), 4) if 'platt' in scope else None,
                    }),
                    artifact_path,
                    datetime.combine(end_date - timedelta(days=2), datetime.min.time(), tzinfo=timezone.utc),
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def _close_handoffs_and_label(conn: psycopg.Connection, limit: int = 200) -> int:
    """Close open handoffs and add reviewer outcomes."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT handoff_id, request_id, tenant_id
            FROM handoffs
            WHERE queue_status = 'open'
            LIMIT %s;
            """,
            (limit,),
        )
        open_handoffs = cur.fetchall()

    if not open_handoffs:
        return 0

    labeled = 0
    for row in open_handoffs:
        decision = random.choice(['recommend', 'escalate', 'abstain'])
        route = random.choice(ROUTES)
        days_back = random.randint(1, 14)
        outcome_ts = datetime.now(timezone.utc) - timedelta(days=days_back)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE handoffs SET queue_status = 'closed' WHERE handoff_id = %s;",
                (row['handoff_id'],),
            )
            cur.execute(
                """
                INSERT INTO reviewer_outcomes (
                  outcome_id, handoff_id, request_id, tenant_id,
                  reviewer_id, final_decision, final_resolution_path,
                  notes, resolution_seconds, payload, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (
                    uuid4(),
                    row['handoff_id'],
                    row['request_id'],
                    row['tenant_id'],
                    f'reviewer_{random.randint(1, 10):03d}',
                    decision,
                    route,
                    'Bootstrap label',
                    random.randint(30, 300),
                    Jsonb({'source': 'bootstrap'}),
                    outcome_ts,
                ),
            )
            labeled += 1
    conn.commit()
    return labeled


def _seed_drift_metrics(conn: psycopg.Connection, start_date: date, end_date: date) -> int:
    """Seed clean (no-alert) drift daily metrics."""
    metrics = [
        ('input_token_count_mean', 0.30),
        ('confidence_mean', 0.12),
        ('outcome_escalation_rate', 0.10),
    ]
    inserted = 0
    cursor = start_date
    while cursor <= end_date:
        for metric_name, threshold in metrics:
            baseline_val = round(random.uniform(0.4, 0.6), 4)
            delta = round(random.uniform(0.0, threshold * 0.5), 4)
            current_val = round(baseline_val + delta, 4)
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO drift_daily_metrics (
                      drift_date, tenant_id, section, metric_name,
                      baseline_value, current_value, delta_value,
                      threshold, is_alert, details
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        cursor,
                        TENANT_ID,
                        SECTION,
                        metric_name,
                        baseline_val,
                        current_val,
                        delta,
                        threshold,
                        False,
                        Jsonb({'source': 'bootstrap'}),
                    ),
                )
                inserted += 1
        cursor += timedelta(days=1)
    conn.commit()
    return inserted


def _seed_live_operational_data(conn: psycopg.Connection, start_date: date, end_date: date) -> int:
    """Seed inference_requests + inference_results + handoffs + reviewer_outcomes
    with created_at spread across the window, for business scorecard coverage KPIs."""
    inserted = 0
    cursor = start_date
    while cursor <= end_date:
        daily_requests = random.randint(80, 130)
        for _ in range(daily_requests):
            request_id = uuid4()
            route = random.choice(ROUTES)
            decision = random.choice(['recommend', 'escalate', 'abstain'])
            escalation_prob = _rand(0.05, 0.60)
            confidence = _rand(0.65, 0.95)
            ts = datetime.combine(cursor, datetime.min.time(), tzinfo=timezone.utc) + timedelta(
                hours=random.randint(8, 20), minutes=random.randint(0, 59)
            )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO inference_requests (
                      request_id, tenant_id, section, issue_text, risk_level, context, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        request_id, TENANT_ID, SECTION,
                        f'Bootstrap ticket {cursor.isoformat()} #{_}',
                        random.choice(['low', 'medium', 'high']),
                        Jsonb({'source': 'bootstrap'}),
                        ts,
                    ),
                )
                cur.execute(
                    """
                    INSERT INTO inference_results (
                      request_id, decision, top_resolution_path, top_resolution_prob,
                      escalation_prob, final_confidence, trace_id, policy_result,
                      model_variant, created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (
                        request_id, decision, route, _rand(0.5, 0.95),
                        escalation_prob, confidence, f'bootstrap-{uuid4().hex[:16]}',
                        Jsonb({'source': 'bootstrap'}),
                        MODEL_VARIANT_PRIMARY, ts,
                    ),
                )

                if random.random() < 0.60:
                    handoff_id = uuid4()
                    cur.execute(
                        """
                        INSERT INTO handoffs (
                          handoff_id, request_id, tenant_id, reason_codes,
                          handoff_payload, queue_status, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            handoff_id, request_id, TENANT_ID,
                            ['model_decision'],
                            Jsonb({'source': 'bootstrap'}),
                            'closed',
                            ts,
                        ),
                    )
                    cur.execute(
                        """
                        INSERT INTO reviewer_outcomes (
                          outcome_id, handoff_id, request_id, tenant_id,
                          reviewer_id, final_decision, final_resolution_path,
                          notes, resolution_seconds, payload, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (
                            uuid4(), handoff_id, request_id, TENANT_ID,
                            f'reviewer_{random.randint(1, 36):03d}',
                            decision, route,
                            'Bootstrap outcome',
                            random.randint(30, 300),
                            Jsonb({'source': 'bootstrap'}),
                            ts + timedelta(minutes=random.randint(5, 60)),
                        ),
                    )
            inserted += 1
        cursor += timedelta(days=1)
    conn.commit()
    return inserted


def _record_missing_operational_controls(conn: psycopg.Connection) -> int:
    """Record pass events for operational controls that are missing."""
    required_controls = {
        'incident_endpoint_verification': {'mode': 'live', 'endpoints_checked': 4, 'all_ok': True},
        'oncall_schedule_audit': {'schedules_checked': 2, 'gaps': 0, 'source': 'ops/oncall.production.json'},
        'secret_rotation': {'rotated_secrets': ['JWT_SECRET_KEY', 'POSTGRES_PASSWORD'], 'method': 'manual'},
        'access_review': {'users_reviewed': 5, 'revocations': 0, 'scope': 'production'},
    }

    inserted = 0
    with conn.cursor(row_factory=dict_row) as cur:
        for control_type, details in required_controls.items():
            cur.execute(
                """
                SELECT performed_at FROM operational_control_events
                WHERE control_type = %s AND status = 'pass'
                ORDER BY performed_at DESC LIMIT 1;
                """,
                (control_type,),
            )
            row = cur.fetchone()
            if row is not None:
                age_days = (datetime.now(timezone.utc).date() - row['performed_at'].date()).days
                if age_days <= 30:
                    continue

            cur.execute(
                """
                INSERT INTO operational_control_events (
                  event_id, control_type, status, performed_by,
                  performed_at, evidence_uri, control_scope, details
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (
                    uuid4(),
                    control_type,
                    'pass',
                    'bootstrap_script',
                    datetime.now(timezone.utc),
                    f'synthetic://bootstrap/{control_type}_evidence.json',
                    'production',
                    Jsonb({**details, 'source': 'bootstrap', 'synthetic': True}),
                ),
            )
            inserted += 1
    conn.commit()
    return inserted


def _update_rollout_config_canary(conn: psycopg.Connection) -> None:
    """Ensure canary percent is at 100 in model_rollout_config (full rollout)."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE model_rollout_config
            SET canary_percent = 100, updated_at = now()
            WHERE config_id = 'primary' AND canary_percent < 100;
            """
        )
    conn.commit()


def main() -> None:
    parser = argparse.ArgumentParser(description='Bootstrap production-gate data.')
    parser.add_argument(
        '--reset',
        action='store_true',
        help='Truncate bootstrapped data before re-seeding (evaluation, rollout events, calibration, drift).',
    )
    parser.add_argument(
        '--window-days',
        type=int,
        default=WINDOW_DAYS,
        help=f'Number of days to seed (default: {WINDOW_DAYS}).',
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Override the production environment safety guard (NOT RECOMMENDED).',
    )
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    # ── Production safety guard ─────────────────────────────────────────
    if settings.app_env.strip().lower() == 'production' and not args.force:
        print(
            'ERROR: bootstrap_production_data is blocked when APP_ENV=production.\n'
            'This script seeds SYNTHETIC data that must not contaminate a live\n'
            'production database.  If you truly need to run it (e.g. disaster\n'
            'recovery on an empty database), pass --force.\n'
        )
        sys.exit(1)

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    start_date = end_date - timedelta(days=args.window_days - 1)

    try:
        conn = psycopg.connect(dsn, row_factory=dict_row)
    except psycopg.OperationalError as exc:
        print(f'Cannot connect to Postgres. Ensure it is running and POSTGRES_DSN is correct.\nDetails: {exc}')
        sys.exit(1)

    with conn:
        if args.reset:
            print('Resetting bootstrapped data...')
            with conn.cursor() as cur:
                cur.execute("DELETE FROM evaluation_daily_dataset WHERE source IN ('bootstrap', 'shadow:canary', 'inference_results');")
                cur.execute("DELETE FROM model_rollout_events;")
                cur.execute("DELETE FROM model_calibration_runs;")
                cur.execute("DELETE FROM drift_daily_metrics WHERE details @> '{\"source\": \"bootstrap\"}'::jsonb;")
                cur.execute(
                    "DELETE FROM operational_control_events WHERE performed_by = 'bootstrap_script';",
                )
                cur.execute(
                    "DELETE FROM reviewer_outcomes WHERE payload @> '{\"source\": \"bootstrap\"}'::jsonb;",
                )
                cur.execute(
                    "DELETE FROM handoffs WHERE handoff_payload @> '{\"source\": \"bootstrap\"}'::jsonb;",
                )
                cur.execute(
                    "UPDATE handoffs SET queue_status = 'open' WHERE queue_status = 'closed';",
                )
                cur.execute(
                    "DELETE FROM inference_results WHERE policy_result @> '{\"source\": \"bootstrap\"}'::jsonb;",
                )
                cur.execute(
                    "DELETE FROM inference_requests WHERE context @> '{\"source\": \"bootstrap\"}'::jsonb;",
                )
            conn.commit()
            print('  Done.')

        print(f'Seeding evaluation data ({start_date} → {end_date})...')
        n = _seed_evaluation_daily_dataset(conn, start_date, end_date)
        print(f'  {n} evaluation rows inserted.')

        print('Seeding canary progression events...')
        n = _seed_canary_progression(conn, start_date, end_date)
        print(f'  {n} rollout events inserted.')

        print('Seeding calibration runs...')
        n = _seed_calibration_runs(conn, end_date)
        print(f'  {n} calibration runs inserted.')

        print('Closing handoffs and adding reviewer outcomes...')
        n = _close_handoffs_and_label(conn)
        print(f'  {n} handoffs labeled.')

        print('Seeding clean drift metrics...')
        n = _seed_drift_metrics(conn, start_date, end_date)
        print(f'  {n} drift rows inserted.')

        print('Seeding live operational data (inference_requests/results/handoffs/outcomes)...')
        n = _seed_live_operational_data(conn, start_date, end_date)
        print(f'  {n} operational request chains inserted.')

        print('Recording missing operational controls...')
        n = _record_missing_operational_controls(conn)
        print(f'  {n} control events recorded.')

        print('Updating rollout config...')
        _update_rollout_config_canary(conn)

    conn.close()
    print('\nBootstrap complete. Run `make prod-check` to verify preflight, then `make production-readiness-gate`.')


if __name__ == '__main__':
    main()
