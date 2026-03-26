from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

STAGES = [0, 5, 25, 50, 100]


def _default_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _next_stage(current_percent: int) -> int:
    safe_current = max(0, min(100, int(current_percent)))
    for stage in STAGES:
        if stage > safe_current:
            return stage
    return safe_current


def _previous_stage(current_percent: int) -> int:
    safe_current = max(0, min(100, int(current_percent)))
    prev = 0
    for stage in STAGES:
        if stage >= safe_current:
            return prev
        prev = stage
    return prev


def _resolve_source_scope(current_percent: int) -> str:
    if int(current_percent) <= 0:
        return 'shadow_or_canary'
    return 'canary_only'


def _compute_window_metrics(
    *,
    cur: psycopg.Cursor,
    start_date: str,
    end_date: str,
    source_scope: str,
) -> dict:
    cur.execute(
        """
        WITH base AS (
          SELECT
            predicted_decision,
            is_route_correct,
            is_escalation_actual,
            final_confidence
          FROM evaluation_daily_dataset
          WHERE eval_date >= %(start_date)s::date
            AND eval_date < %(end_date)s::date
            AND model_variant = 'challenger'
            AND (
              (%(source_scope)s = 'shadow_or_canary' AND source LIKE 'shadow:%%')
              OR
              (%(source_scope)s = 'canary_only' AND source = 'shadow:canary')
            )
        ),
        agg AS (
          SELECT
            COUNT(*) AS sample_size,
            AVG(
              CASE
                WHEN is_route_correct IS NULL THEN NULL
                WHEN is_route_correct THEN 1.0
                ELSE 0.0
              END
            ) AS route_accuracy,
            CASE
              WHEN SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END) = 0 THEN NULL
              ELSE
                SUM(CASE WHEN predicted_decision = 'escalate' AND is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
                /
                SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
            END AS escalation_recall,
            AVG(CASE WHEN predicted_decision = 'abstain' THEN 1.0 ELSE 0.0 END) AS abstain_rate
          FROM base
        ),
        ece_bins AS (
          SELECT
            width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10) AS bin_id,
            COUNT(*) AS n_bin,
            AVG(COALESCE(final_confidence, 0.0)) AS avg_conf,
            AVG(CASE WHEN is_route_correct THEN 1.0 ELSE 0.0 END) AS avg_acc
          FROM base
          WHERE is_route_correct IS NOT NULL
          GROUP BY width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10)
        ),
        ece AS (
          SELECT
            SUM(ABS(COALESCE(avg_acc, 0.0) - COALESCE(avg_conf, 0.0)) * n_bin)::DOUBLE PRECISION
            /
            NULLIF(SUM(n_bin), 0)::DOUBLE PRECISION AS ece
          FROM ece_bins
        )
        SELECT
          COALESCE(agg.sample_size, 0) AS sample_size,
          agg.route_accuracy,
          agg.escalation_recall,
          agg.abstain_rate,
          ece.ece
        FROM agg
        LEFT JOIN ece ON TRUE;
        """,
        {
            'start_date': start_date,
            'end_date': end_date,
            'source_scope': source_scope,
        },
    )
    row = cur.fetchone()
    if row is None:
        return {
            'sample_size': 0,
            'route_accuracy': None,
            'escalation_recall': None,
            'ece': None,
            'abstain_rate': None,
        }
    return {
        'sample_size': int(row['sample_size'] or 0),
        'route_accuracy': float(row['route_accuracy']) if row['route_accuracy'] is not None else None,
        'escalation_recall': float(row['escalation_recall']) if row['escalation_recall'] is not None else None,
        'ece': float(row['ece']) if row['ece'] is not None else None,
        'abstain_rate': float(row['abstain_rate']) if row['abstain_rate'] is not None else None,
    }


def _build_blocking_reasons(
    *,
    source_scope: str,
    sample_size: int,
    min_sample_size: int,
    route_accuracy: float | None,
    escalation_recall: float | None,
    ece: float | None,
    abstain_rate: float | None,
    gates: dict[str, float],
) -> list[str]:
    reasons: list[str] = []
    if sample_size <= 0:
        if source_scope == 'canary_only':
            reasons.append('no_canary_samples')
        else:
            reasons.append('no_challenger_samples')
    if sample_size < int(min_sample_size):
        reasons.append('sample_size_below_gate')
    if route_accuracy is None:
        reasons.append('missing_route_accuracy')
    elif route_accuracy < gates['min_route_accuracy']:
        reasons.append('route_accuracy_below_gate')
    if escalation_recall is None:
        reasons.append('missing_escalation_recall')
    elif escalation_recall < gates['min_escalation_recall']:
        reasons.append('escalation_recall_below_gate')
    if ece is None:
        reasons.append('missing_ece')
    elif ece > gates['max_ece']:
        reasons.append('ece_above_gate')
    if abstain_rate is not None and abstain_rate > gates['max_abstain_rate']:
        reasons.append('abstain_rate_above_gate')
    return reasons


def _persist_rollout_event(
    cur: psycopg.Cursor,
    *,
    eval_date: str,
    lookback_days: int,
    gate_result: str,
    action: str,
    apply_change: bool,
    rollback_on_fail: bool,
    current_percent: int,
    target_percent: int,
    summary: dict,
    blocking_reasons: list[str],
) -> None:
    cur.execute("SELECT to_regclass('public.model_rollout_events') IS NOT NULL AS table_exists;")
    row = cur.fetchone()
    exists = bool(row['table_exists']) if row is not None else False
    if not exists:
        return

    cur.execute(
        """
        INSERT INTO model_rollout_events (
          event_id,
          eval_date,
          lookback_days,
          model_variant,
          gate_result,
          action,
          apply_change,
          rollback_on_fail,
          current_percent,
          target_percent,
          sample_size,
          route_accuracy,
          escalation_recall,
          ece,
          abstain_rate,
          gates,
          details
        )
        VALUES (
          %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
        );
        """,
        (
            uuid4(),
            eval_date,
            int(lookback_days),
            'challenger',
            gate_result,
            action,
            bool(apply_change),
            bool(rollback_on_fail),
            int(current_percent),
            int(target_percent),
            int(summary['sample_size']),
            summary['route_accuracy'],
            summary['escalation_recall'],
            summary['ece'],
            summary['abstain_rate'],
            Jsonb(summary['gates']),
            Jsonb({'blocking_reasons': blocking_reasons, 'source_scope': summary['source_scope']}),
        ),
    )


def evaluate_and_promote(
    *,
    dsn: str,
    eval_date: str,
    lookback_days: int,
    apply: bool,
    rollback_on_fail: bool,
) -> tuple[bool, int, int, dict]:
    end_date = datetime.fromisoformat(eval_date).date() + timedelta(days=1)
    start_date = end_date - timedelta(days=lookback_days)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  config_id,
                  challenger_model_name,
                  challenger_model_version,
                  canary_percent,
                  quality_gate_min_route_accuracy,
                  quality_gate_min_escalation_recall,
                  quality_gate_max_ece,
                  quality_gate_max_abstain_rate,
                  quality_gate_min_sample_size
                FROM model_rollout_config
                WHERE config_id = 'primary'
                LIMIT 1;
                """
            )
            config = cur.fetchone()

            if config is None:
                raise RuntimeError('model_rollout_config row with config_id=primary is missing. Apply migrations first.')

            gates = {
                'min_route_accuracy': float(config['quality_gate_min_route_accuracy']),
                'min_escalation_recall': float(config['quality_gate_min_escalation_recall']),
                'max_ece': float(config['quality_gate_max_ece']),
                'max_abstain_rate': float(config['quality_gate_max_abstain_rate']),
                'min_sample_size': max(1, int(config['quality_gate_min_sample_size'])),
            }

            current_percent = int(config['canary_percent'])
            source_scope = _resolve_source_scope(current_percent)
            stats = _compute_window_metrics(
                cur=cur,
                start_date=start_date.isoformat(),
                end_date=end_date.isoformat(),
                source_scope=source_scope,
            )
            sample_size = int(stats['sample_size'])
            route_accuracy = stats['route_accuracy']
            escalation_recall = stats['escalation_recall']
            ece = stats['ece']
            abstain_rate = stats['abstain_rate']

            blocking_reasons = _build_blocking_reasons(
                source_scope=source_scope,
                sample_size=sample_size,
                min_sample_size=gates['min_sample_size'],
                route_accuracy=route_accuracy,
                escalation_recall=escalation_recall,
                ece=ece,
                abstain_rate=abstain_rate,
                gates=gates,
            )
            passed = len(blocking_reasons) == 0

            target_percent = current_percent
            action = 'hold'
            if passed:
                target_percent = _next_stage(current_percent)
                if target_percent > current_percent:
                    action = 'promote'
            elif rollback_on_fail and current_percent > 0:
                target_percent = _previous_stage(current_percent)
                if target_percent < current_percent:
                    action = 'rollback'

            applied_change = bool(apply and target_percent != current_percent)
            if applied_change:
                cur.execute(
                    """
                    UPDATE model_rollout_config
                    SET canary_percent = %s,
                        updated_at = now()
                    WHERE config_id = 'primary';
                    """,
                    (target_percent,),
                )

            summary = {
                'sample_size': sample_size,
                'route_accuracy': route_accuracy,
                'escalation_recall': escalation_recall,
                'ece': ece,
                'abstain_rate': abstain_rate,
                'gates': gates,
                'source_scope': source_scope,
            }
            _persist_rollout_event(
                cur,
                eval_date=eval_date,
                lookback_days=lookback_days,
                gate_result='pass' if passed else 'blocked',
                action=action,
                apply_change=applied_change,
                rollback_on_fail=rollback_on_fail,
                current_percent=current_percent,
                target_percent=target_percent,
                summary=summary,
                blocking_reasons=blocking_reasons,
            )
            conn.commit()

    summary = {
        'sample_size': sample_size,
        'route_accuracy': route_accuracy,
        'escalation_recall': escalation_recall,
        'ece': ece,
        'abstain_rate': abstain_rate,
        'gates': gates,
        'blocking_reasons': blocking_reasons,
        'source_scope': source_scope,
    }
    return passed, current_percent, target_percent, summary


def main() -> None:
    parser = argparse.ArgumentParser(description='Promote challenger canary stage only when quality gates pass.')
    parser.add_argument('--date', default=_default_date(), help='Anchor date (YYYY-MM-DD) for lookback window end.')
    parser.add_argument('--lookback-days', type=int, default=14, help='Stability window used for promotion checks.')
    parser.add_argument('--apply', action='store_true', help='Apply promotion/rollback update to model_rollout_config.')
    parser.add_argument('--rollback-on-fail', action='store_true', help='Rollback one stage when gates fail.')
    parser.add_argument('--fail-on-blocked', action='store_true', help='Exit non-zero if promotion gates fail.')
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        passed, current_percent, target_percent, summary = evaluate_and_promote(
            dsn=dsn,
            eval_date=args.date,
            lookback_days=max(1, int(args.lookback_days)),
            apply=args.apply,
            rollback_on_fail=args.rollback_on_fail,
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while evaluating canary promotion. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    status = 'PASS' if passed else 'BLOCKED'
    action = 'unchanged'
    if target_percent > current_percent:
        action = f'promote to {target_percent}%'
    elif target_percent < current_percent:
        action = f'rollback to {target_percent}%'

    print(
        f'Canary gate result: {status}. Current={current_percent}%, target={target_percent}% ({action}). '
        f"samples={summary['sample_size']}, route_acc={summary['route_accuracy']}, "
        f"escalation_recall={summary['escalation_recall']}, ece={summary['ece']}, "
        f"abstain_rate={summary['abstain_rate']}, source_scope={summary['source_scope']}"
    )
    if summary.get('blocking_reasons'):
        print(f"Blocking reasons: {', '.join(summary['blocking_reasons'])}")

    if args.fail_on_blocked and not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
