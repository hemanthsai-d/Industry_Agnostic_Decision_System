from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


@dataclass
class DriftPoint:
    tenant_id: str
    section: str
    baseline_value: float
    current_value: float


def _default_drift_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def _fetch_points(
    conn: psycopg.Connection,
    *,
    current_sql: str,
    baseline_sql: str,
    current_params: tuple,
    baseline_params: tuple,
) -> list[DriftPoint]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(current_sql, current_params)
        current_rows = cur.fetchall()
        cur.execute(baseline_sql, baseline_params)
        baseline_rows = cur.fetchall()

    current_map = {
        (str(row['tenant_id']), str(row['section_key'])): float(row['value'])
        for row in current_rows
        if row['value'] is not None
    }
    baseline_map = {
        (str(row['tenant_id']), str(row['section_key'])): float(row['value'])
        for row in baseline_rows
        if row['value'] is not None
    }

    keys = set(current_map).union(baseline_map)
    points: list[DriftPoint] = []
    for key in sorted(keys):
        baseline_value = baseline_map.get(key)
        current_value = current_map.get(key)
        if current_value is None:
            continue
        if baseline_value is None:
            baseline_value = current_value
        points.append(
            DriftPoint(
                tenant_id=key[0],
                section=key[1],
                baseline_value=float(baseline_value),
                current_value=float(current_value),
            )
        )
    return points


def _store_metric(
    cur: psycopg.Cursor,
    *,
    drift_date: str,
    tenant_id: str,
    section: str,
    metric_name: str,
    baseline_value: float,
    current_value: float,
    delta_value: float,
    threshold: float,
    is_alert: bool,
    details: dict,
) -> None:
    cur.execute(
        """
        INSERT INTO drift_daily_metrics (
          drift_date,
          tenant_id,
          section,
          metric_name,
          baseline_value,
          current_value,
          delta_value,
          threshold,
          is_alert,
          details
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (drift_date, tenant_id, section, metric_name)
        DO UPDATE SET
          baseline_value = EXCLUDED.baseline_value,
          current_value = EXCLUDED.current_value,
          delta_value = EXCLUDED.delta_value,
          threshold = EXCLUDED.threshold,
          is_alert = EXCLUDED.is_alert,
          details = EXCLUDED.details,
          created_at = now();
        """,
        (
            drift_date,
            tenant_id,
            section,
            metric_name,
            baseline_value,
            current_value,
            delta_value,
            threshold,
            is_alert,
            Jsonb(details),
        ),
    )


def compute_drift_metrics(
    *,
    dsn: str,
    drift_date_raw: str,
    baseline_days: int,
    input_threshold: float,
    confidence_threshold: float,
    outcome_threshold: float,
) -> int:
    drift_date = _parse_date(drift_date_raw)
    baseline_start = drift_date - timedelta(days=baseline_days)

    input_current_sql = """
    SELECT tenant_id, COALESCE(section, '__all__') AS section_key, AVG(issue_token_count::DOUBLE PRECISION) AS value
    FROM evaluation_daily_dataset
    WHERE eval_date = %s::date
    GROUP BY tenant_id, COALESCE(section, '__all__');
    """
    input_baseline_sql = """
    SELECT tenant_id, COALESCE(section, '__all__') AS section_key, AVG(issue_token_count::DOUBLE PRECISION) AS value
    FROM evaluation_daily_dataset
    WHERE eval_date >= %s::date
      AND eval_date < %s::date
    GROUP BY tenant_id, COALESCE(section, '__all__');
    """

    conf_current_sql = """
    SELECT tenant_id, COALESCE(section, '__all__') AS section_key, AVG(final_confidence::DOUBLE PRECISION) AS value
    FROM evaluation_daily_dataset
    WHERE eval_date = %s::date
    GROUP BY tenant_id, COALESCE(section, '__all__');
    """
    conf_baseline_sql = """
    SELECT tenant_id, COALESCE(section, '__all__') AS section_key, AVG(final_confidence::DOUBLE PRECISION) AS value
    FROM evaluation_daily_dataset
    WHERE eval_date >= %s::date
      AND eval_date < %s::date
    GROUP BY tenant_id, COALESCE(section, '__all__');
    """

    outcome_current_sql = """
    SELECT tenant_id, section AS section_key, AVG(route_accuracy::DOUBLE PRECISION) AS value
    FROM evaluation_daily_metrics
    WHERE eval_date = %s::date
      AND model_variant = 'primary'
    GROUP BY tenant_id, section;
    """
    outcome_baseline_sql = """
    SELECT tenant_id, section AS section_key, AVG(route_accuracy::DOUBLE PRECISION) AS value
    FROM evaluation_daily_metrics
    WHERE eval_date >= %s::date
      AND eval_date < %s::date
      AND model_variant = 'primary'
    GROUP BY tenant_id, section;
    """

    alert_count = 0

    with psycopg.connect(dsn) as conn:
        input_points = _fetch_points(
            conn,
            current_sql=input_current_sql,
            baseline_sql=input_baseline_sql,
            current_params=(drift_date_raw,),
            baseline_params=(baseline_start.isoformat(), drift_date_raw),
        )
        confidence_points = _fetch_points(
            conn,
            current_sql=conf_current_sql,
            baseline_sql=conf_baseline_sql,
            current_params=(drift_date_raw,),
            baseline_params=(baseline_start.isoformat(), drift_date_raw),
        )
        outcome_points = _fetch_points(
            conn,
            current_sql=outcome_current_sql,
            baseline_sql=outcome_baseline_sql,
            current_params=(drift_date_raw,),
            baseline_params=(baseline_start.isoformat(), drift_date_raw),
        )

        with conn.cursor() as cur:
            cur.execute('DELETE FROM drift_daily_metrics WHERE drift_date = %s::date;', (drift_date_raw,))

            for point in input_points:
                denominator = max(abs(point.baseline_value), 1.0)
                delta = abs(point.current_value - point.baseline_value) / denominator
                is_alert = delta > input_threshold
                alert_count += 1 if is_alert else 0
                _store_metric(
                    cur,
                    drift_date=drift_date_raw,
                    tenant_id=point.tenant_id,
                    section=point.section,
                    metric_name='input_token_mean_relative_delta',
                    baseline_value=point.baseline_value,
                    current_value=point.current_value,
                    delta_value=delta,
                    threshold=input_threshold,
                    is_alert=is_alert,
                    details={'baseline_days': baseline_days},
                )

            for point in confidence_points:
                delta = abs(point.current_value - point.baseline_value)
                is_alert = delta > confidence_threshold
                alert_count += 1 if is_alert else 0
                _store_metric(
                    cur,
                    drift_date=drift_date_raw,
                    tenant_id=point.tenant_id,
                    section=point.section,
                    metric_name='confidence_mean_abs_delta',
                    baseline_value=point.baseline_value,
                    current_value=point.current_value,
                    delta_value=delta,
                    threshold=confidence_threshold,
                    is_alert=is_alert,
                    details={'baseline_days': baseline_days},
                )

            for point in outcome_points:
                delta = abs(point.current_value - point.baseline_value)
                is_alert = delta > outcome_threshold
                alert_count += 1 if is_alert else 0
                _store_metric(
                    cur,
                    drift_date=drift_date_raw,
                    tenant_id=point.tenant_id,
                    section=point.section,
                    metric_name='route_accuracy_abs_delta',
                    baseline_value=point.baseline_value,
                    current_value=point.current_value,
                    delta_value=delta,
                    threshold=outcome_threshold,
                    is_alert=is_alert,
                    details={'baseline_days': baseline_days},
                )

        conn.commit()

    return alert_count


def main() -> None:
    parser = argparse.ArgumentParser(description='Compute daily drift metrics and alerts.')
    parser.add_argument('--date', default=_default_drift_date(), help='Drift date in YYYY-MM-DD format.')
    parser.add_argument('--baseline-days', type=int, default=None, help='Baseline lookback window in days.')
    parser.add_argument('--fail-on-alert', action='store_true', help='Exit non-zero when drift alerts are detected.')
    args = parser.parse_args()

    settings = get_settings()
    baseline_days = args.baseline_days or settings.evaluation_baseline_days
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        alerts = compute_drift_metrics(
            dsn=dsn,
            drift_date_raw=args.date,
            baseline_days=baseline_days,
            input_threshold=settings.drift_input_threshold,
            confidence_threshold=settings.drift_confidence_threshold,
            outcome_threshold=settings.drift_outcome_threshold,
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while computing drift metrics. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    print(f'Computed drift metrics for {args.date}. Alert rows: {alerts}')
    if args.fail_on_alert and alerts > 0:
        sys.exit(2)


if __name__ == '__main__':
    main()
