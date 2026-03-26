from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import sys

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn
from scripts.build_daily_evaluation import build_daily_dataset
from scripts.compute_daily_metrics import compute_daily_metrics
from scripts.compute_drift_metrics import compute_drift_metrics


def _default_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description='Run full daily model-ops evaluation pipeline.')
    parser.add_argument('--date', default=_default_date(), help='Evaluation date in YYYY-MM-DD format.')
    parser.add_argument('--fail-on-drift-alert', action='store_true', help='Exit non-zero when drift alerts are raised.')
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    dataset_rows = build_daily_dataset(dsn=dsn, eval_date=args.date)
    metric_rows = compute_daily_metrics(dsn=dsn, eval_date=args.date)
    drift_alerts = compute_drift_metrics(
        dsn=dsn,
        drift_date_raw=args.date,
        baseline_days=settings.evaluation_baseline_days,
        input_threshold=settings.drift_input_threshold,
        confidence_threshold=settings.drift_confidence_threshold,
        outcome_threshold=settings.drift_outcome_threshold,
    )

    print(
        f'Model-ops daily pipeline complete for {args.date}. '
        f'dataset_rows={dataset_rows}, metric_rows={metric_rows}, drift_alerts={drift_alerts}'
    )

    if args.fail_on_drift_alert and drift_alerts > 0:
        sys.exit(2)


if __name__ == '__main__':
    main()
