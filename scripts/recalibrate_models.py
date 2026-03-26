from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


def _clip_probability(value: float) -> float:
    return max(1e-6, min(1.0 - 1e-6, float(value)))


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _logit(probability: float) -> float:
    p = _clip_probability(probability)
    return math.log(p / (1.0 - p))


def _log_loss(samples: list[tuple[float, int]]) -> float:
    if not samples:
        return 0.0
    total = 0.0
    for prob, label in samples:
        p = _clip_probability(prob)
        y = 1 if int(label) else 0
        total += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return total / len(samples)


def _frange(start: float, stop: float, step: float) -> list[float]:
    values: list[float] = []
    value = start
    while value <= stop + (step / 2.0):
        values.append(round(value, 10))
        value += step
    return values


@dataclass
class TemperatureFit:
    temperature: float
    loss: float
    sample_size: int


@dataclass
class PlattFit:
    a: float
    b: float
    loss: float
    sample_size: int


def fit_temperature(samples: list[tuple[float, int]]) -> TemperatureFit:
    if not samples:
        return TemperatureFit(temperature=1.0, loss=0.0, sample_size=0)

    best_temperature = 1.0
    best_loss = float('inf')

    for temperature in _frange(0.5, 3.0, 0.05):
        calibrated = [(_sigmoid(_logit(prob) / temperature), label) for prob, label in samples]
        loss = _log_loss(calibrated)
        if loss < best_loss:
            best_loss = loss
            best_temperature = temperature

    return TemperatureFit(temperature=best_temperature, loss=best_loss, sample_size=len(samples))


def fit_platt(samples: list[tuple[float, int]]) -> PlattFit:
    if not samples:
        return PlattFit(a=1.0, b=0.0, loss=0.0, sample_size=0)

    best_a = 1.0
    best_b = 0.0
    best_loss = float('inf')

    a_values = _frange(0.4, 3.0, 0.1)
    b_values = _frange(-2.0, 2.0, 0.1)

    for a in a_values:
        for b in b_values:
            calibrated = [(_sigmoid((a * _logit(prob)) + b), label) for prob, label in samples]
            loss = _log_loss(calibrated)
            if loss < best_loss:
                best_loss = loss
                best_a = a
                best_b = b

    return PlattFit(a=best_a, b=best_b, loss=best_loss, sample_size=len(samples))


def _write_json(path: str, payload: dict) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')


def _query_samples(
    conn: psycopg.Connection,
    *,
    start_date: str,
    end_date: str,
    model_variant: str,
) -> tuple[list[tuple[float, int]], list[tuple[float, int]]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            SELECT predicted_route_prob, is_route_correct
            FROM evaluation_daily_dataset
            WHERE eval_date >= %s::date
              AND eval_date < %s::date
              AND model_variant = %s
              AND predicted_route_prob IS NOT NULL
              AND is_route_correct IS NOT NULL;
            """,
            (start_date, end_date, model_variant),
        )
        routing_rows = cur.fetchall()

        cur.execute(
            """
            SELECT escalation_prob, is_escalation_actual
            FROM evaluation_daily_dataset
            WHERE eval_date >= %s::date
              AND eval_date < %s::date
              AND model_variant = %s
              AND escalation_prob IS NOT NULL
              AND is_escalation_actual IS NOT NULL;
            """,
            (start_date, end_date, model_variant),
        )
        escalation_rows = cur.fetchall()

    routing_samples = [
        (float(row['predicted_route_prob']), 1 if bool(row['is_route_correct']) else 0)
        for row in routing_rows
    ]
    escalation_samples = [
        (float(row['escalation_prob']), 1 if bool(row['is_escalation_actual']) else 0)
        for row in escalation_rows
    ]
    return routing_samples, escalation_samples


def _persist_calibration_run(
    conn: psycopg.Connection,
    *,
    run_scope: str,
    model_variant: str,
    sample_size: int,
    metrics: dict,
    artifact_path: str,
) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_calibration_runs (
              run_id,
              run_scope,
              model_variant,
              sample_size,
              metrics,
              artifact_path
            )
            VALUES (%s, %s, %s, %s, %s, %s);
            """,
            (
                uuid4(),
                run_scope,
                model_variant,
                sample_size,
                Jsonb(metrics),
                artifact_path,
            ),
        )


def recalibrate(
    *,
    dsn: str,
    lookback_days: int,
    model_variant: str,
    routing_output: str,
    escalation_output: str,
) -> tuple[TemperatureFit, PlattFit]:
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days)

    with psycopg.connect(dsn) as conn:
        routing_samples, escalation_samples = _query_samples(
            conn,
            start_date=start.isoformat(),
            end_date=today.isoformat(),
            model_variant=model_variant,
        )

        routing_fit = fit_temperature(routing_samples)
        escalation_fit = fit_platt(escalation_samples)

        routing_payload = {
            'temperature': routing_fit.temperature,
            'min_probability': 0.0001,
            'max_probability': 0.9999,
            'fitted_on_utc': datetime.now(timezone.utc).isoformat(),
            'sample_size': routing_fit.sample_size,
            'lookback_days': lookback_days,
            'model_variant': model_variant,
            'log_loss': routing_fit.loss,
        }
        escalation_payload = {
            'a': escalation_fit.a,
            'b': escalation_fit.b,
            'min_probability': 0.0001,
            'max_probability': 0.9999,
            'fitted_on_utc': datetime.now(timezone.utc).isoformat(),
            'sample_size': escalation_fit.sample_size,
            'lookback_days': lookback_days,
            'model_variant': model_variant,
            'log_loss': escalation_fit.loss,
        }

        _write_json(routing_output, routing_payload)
        _write_json(escalation_output, escalation_payload)

        _persist_calibration_run(
            conn,
            run_scope='routing_temperature',
            model_variant=model_variant,
            sample_size=routing_fit.sample_size,
            metrics={'log_loss': routing_fit.loss, 'temperature': routing_fit.temperature},
            artifact_path=str(Path(routing_output)),
        )
        _persist_calibration_run(
            conn,
            run_scope='escalation_platt',
            model_variant=model_variant,
            sample_size=escalation_fit.sample_size,
            metrics={'log_loss': escalation_fit.loss, 'a': escalation_fit.a, 'b': escalation_fit.b},
            artifact_path=str(Path(escalation_output)),
        )
        conn.commit()

    return routing_fit, escalation_fit


def main() -> None:
    parser = argparse.ArgumentParser(description='Recalibrate routing/escalation probabilities from labeled traffic.')
    parser.add_argument('--lookback-days', type=int, default=30)
    parser.add_argument('--model-variant', default='primary')
    parser.add_argument(
        '--routing-output',
        default='artifacts/models/routing_temperature_latest.json',
        help='Output path for routing temperature calibration JSON.',
    )
    parser.add_argument(
        '--escalation-output',
        default='artifacts/models/escalation_platt_latest.json',
        help='Output path for escalation platt calibration JSON.',
    )
    args = parser.parse_args()

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    try:
        routing_fit, escalation_fit = recalibrate(
            dsn=dsn,
            lookback_days=max(1, int(args.lookback_days)),
            model_variant=args.model_variant,
            routing_output=args.routing_output,
            escalation_output=args.escalation_output,
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while recalibrating models. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    print(
        'Recalibration complete. '
        f'Routing samples={routing_fit.sample_size}, temperature={routing_fit.temperature:.3f}, '
        f'Escalation samples={escalation_fit.sample_size}, a={escalation_fit.a:.3f}, b={escalation_fit.b:.3f}'
    )


if __name__ == '__main__':
    main()
