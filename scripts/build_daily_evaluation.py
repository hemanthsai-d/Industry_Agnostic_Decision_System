from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


def _default_eval_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def build_daily_dataset(dsn: str, eval_date: str) -> int:
    sql = """
    INSERT INTO evaluation_daily_dataset (
      eval_date,
      request_id,
      tenant_id,
      section,
      model_variant,
      predicted_decision,
      predicted_route,
      predicted_route_prob,
      escalation_prob,
      final_confidence,
      ground_truth_decision,
      ground_truth_route,
      is_route_correct,
      is_escalation_pred,
      is_escalation_actual,
      issue_token_count,
      resolution_seconds,
      source
    )
    SELECT
      events.eval_date,
      events.request_id,
      events.tenant_id,
      events.section,
      events.model_variant,
      events.predicted_decision,
      events.predicted_route,
      events.predicted_route_prob,
      events.escalation_prob,
      events.final_confidence,
      gt.ground_truth_decision,
      gt.ground_truth_route,
      CASE
        WHEN gt.ground_truth_route IS NULL OR events.predicted_route IS NULL THEN NULL
        WHEN events.predicted_route = gt.ground_truth_route THEN TRUE
        ELSE FALSE
      END AS is_route_correct,
      CASE WHEN events.predicted_decision = 'escalate' THEN TRUE ELSE FALSE END AS is_escalation_pred,
      CASE WHEN gt.ground_truth_decision = 'escalate' THEN TRUE ELSE FALSE END AS is_escalation_actual,
      GREATEST(1, COALESCE(array_length(regexp_split_to_array(trim(events.issue_text), '\\s+'), 1), 1)) AS issue_token_count,
      gt.resolution_seconds,
      events.source
    FROM vw_model_prediction_events events
    LEFT JOIN vw_latest_ground_truth gt
      ON gt.request_id = events.request_id
      AND gt.tenant_id = events.tenant_id
    WHERE events.eval_date = %(eval_date)s::date
    ON CONFLICT (eval_date, request_id, model_variant)
    DO UPDATE SET
      predicted_decision = EXCLUDED.predicted_decision,
      predicted_route = EXCLUDED.predicted_route,
      predicted_route_prob = EXCLUDED.predicted_route_prob,
      escalation_prob = EXCLUDED.escalation_prob,
      final_confidence = EXCLUDED.final_confidence,
      ground_truth_decision = EXCLUDED.ground_truth_decision,
      ground_truth_route = EXCLUDED.ground_truth_route,
      is_route_correct = EXCLUDED.is_route_correct,
      is_escalation_pred = EXCLUDED.is_escalation_pred,
      is_escalation_actual = EXCLUDED.is_escalation_actual,
      issue_token_count = EXCLUDED.issue_token_count,
      resolution_seconds = EXCLUDED.resolution_seconds,
      source = EXCLUDED.source,
      created_at = now();
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM evaluation_daily_dataset WHERE eval_date = %s::date;',
                (eval_date,),
            )
            cur.execute(sql, {'eval_date': eval_date})
            inserted = cur.rowcount or 0
        conn.commit()
    return inserted


def main() -> None:
    parser = argparse.ArgumentParser(description='Build daily joined evaluation dataset from production inference + outcomes.')
    parser.add_argument('--date', default=_default_eval_date(), help='Evaluation date in YYYY-MM-DD format.')
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        inserted = build_daily_dataset(dsn=dsn, eval_date=args.date)
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while building evaluation dataset. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    print(f'Built evaluation_daily_dataset for {args.date}. Rows upserted: {inserted}')


if __name__ == '__main__':
    main()
