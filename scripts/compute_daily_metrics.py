from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys

import psycopg

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


def _default_eval_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def compute_daily_metrics(dsn: str, eval_date: str) -> int:
    sql = """
    WITH base AS (
      SELECT
        tenant_id,
        COALESCE(section, '__all__') AS section_key,
        model_variant,
        predicted_decision,
        is_route_correct,
        is_escalation_pred,
        is_escalation_actual,
        final_confidence,
        resolution_seconds
      FROM evaluation_daily_dataset
      WHERE eval_date = %(eval_date)s::date
    ),
    agg AS (
      SELECT
        tenant_id,
        section_key,
        model_variant,
        COUNT(*) AS sample_size,
        AVG(CASE WHEN is_route_correct IS NULL THEN NULL WHEN is_route_correct THEN 1.0 ELSE 0.0 END) AS route_accuracy,
        CASE
          WHEN SUM(CASE WHEN is_escalation_pred THEN 1 ELSE 0 END) = 0 THEN NULL
          ELSE
            SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
            /
            SUM(CASE WHEN is_escalation_pred THEN 1 ELSE 0 END)::DOUBLE PRECISION
        END AS escalation_precision,
        CASE
          WHEN SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END) = 0 THEN NULL
          ELSE
            SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
            /
            SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
        END AS escalation_recall,
        AVG(CASE WHEN predicted_decision = 'abstain' THEN 1.0 ELSE 0.0 END) AS abstain_rate,
        AVG(resolution_seconds::DOUBLE PRECISION) AS avg_time_to_resolution_seconds
      FROM base
      GROUP BY tenant_id, section_key, model_variant
    ),
    ece_bins AS (
      SELECT
        tenant_id,
        section_key,
        model_variant,
        width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10) AS bin_id,
        COUNT(*) AS n_bin,
        AVG(COALESCE(final_confidence, 0.0)) AS avg_conf,
        AVG(CASE WHEN is_route_correct THEN 1.0 ELSE 0.0 END) AS avg_acc
      FROM base
      WHERE is_route_correct IS NOT NULL
      GROUP BY tenant_id, section_key, model_variant, width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10)
    ),
    ece AS (
      SELECT
        tenant_id,
        section_key,
        model_variant,
        SUM(ABS(COALESCE(avg_acc, 0.0) - COALESCE(avg_conf, 0.0)) * n_bin)::DOUBLE PRECISION
        / NULLIF(SUM(n_bin), 0)::DOUBLE PRECISION AS ece
      FROM ece_bins
      GROUP BY tenant_id, section_key, model_variant
    )
    INSERT INTO evaluation_daily_metrics (
      eval_date,
      tenant_id,
      section,
      model_variant,
      sample_size,
      route_accuracy,
      escalation_precision,
      escalation_recall,
      ece,
      abstain_rate,
      avg_time_to_resolution_seconds,
      computed_at
    )
    SELECT
      %(eval_date)s::date,
      agg.tenant_id,
      agg.section_key,
      agg.model_variant,
      agg.sample_size,
      agg.route_accuracy,
      agg.escalation_precision,
      agg.escalation_recall,
      ece.ece,
      agg.abstain_rate,
      agg.avg_time_to_resolution_seconds,
      now()
    FROM agg
    LEFT JOIN ece
      ON ece.tenant_id = agg.tenant_id
      AND ece.section_key = agg.section_key
      AND ece.model_variant = agg.model_variant
    ON CONFLICT (eval_date, tenant_id, section, model_variant)
    DO UPDATE SET
      sample_size = EXCLUDED.sample_size,
      route_accuracy = EXCLUDED.route_accuracy,
      escalation_precision = EXCLUDED.escalation_precision,
      escalation_recall = EXCLUDED.escalation_recall,
      ece = EXCLUDED.ece,
      abstain_rate = EXCLUDED.abstain_rate,
      avg_time_to_resolution_seconds = EXCLUDED.avg_time_to_resolution_seconds,
      computed_at = now();
    """

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                'DELETE FROM evaluation_daily_metrics WHERE eval_date = %s::date;',
                (eval_date,),
            )
            cur.execute(sql, {'eval_date': eval_date})
            upserted = cur.rowcount or 0
        conn.commit()
    return upserted


def main() -> None:
    parser = argparse.ArgumentParser(description='Compute daily quality metrics from evaluation_daily_dataset.')
    parser.add_argument('--date', default=_default_eval_date(), help='Evaluation date in YYYY-MM-DD format.')
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        upserted = compute_daily_metrics(dsn=dsn, eval_date=args.date)
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while computing daily metrics. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    print(f'Computed evaluation_daily_metrics for {args.date}. Rows upserted: {upserted}')


if __name__ == '__main__':
    main()
