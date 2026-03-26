from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sys
from typing import Any
from uuid import uuid4

import httpx
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn

REQUIRED_CANARY_STAGES = [5, 25, 50, 100]
SLO_ALERTS = [
    'DecisionApiHighErrorRate',
    'DecisionApiHighLatencyP95',
    'ModelServingHighErrorRate',
]


@dataclass
class DailyMetricStatus:
    eval_date: date
    sample_size: int
    route_accuracy: float | None
    escalation_recall: float | None
    ece: float | None
    abstain_rate: float | None
    passed: bool
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            'eval_date': self.eval_date.isoformat(),
            'sample_size': self.sample_size,
            'route_accuracy': self.route_accuracy,
            'escalation_recall': self.escalation_recall,
            'ece': self.ece,
            'abstain_rate': self.abstain_rate,
            'passed': self.passed,
            'reasons': self.reasons,
        }


def _default_end_date() -> str:
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _parse_date(raw: str) -> date:
    return date.fromisoformat(raw)


def _normalize_optional_filter(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    if value.lower() in {'all', '__all__', '*'}:
        return None
    return value


def stage_progression_complete(
    promoted_targets: list[int],
    required_stages: list[int] | None = None,
) -> bool:
    required = required_stages or REQUIRED_CANARY_STAGES
    next_stage_index = 0
    for target in promoted_targets:
        if next_stage_index >= len(required):
            break
        if int(target) == int(required[next_stage_index]):
            next_stage_index += 1
    return next_stage_index == len(required)


def trailing_stable_days(
    *,
    end_date: date,
    daily_pass_map: dict[date, bool],
    max_days: int,
) -> int:
    stable = 0
    cursor = end_date
    while stable < max(1, int(max_days)):
        if not daily_pass_map.get(cursor, False):
            break
        stable += 1
        cursor -= timedelta(days=1)
    return stable


def _safe_weighted(row: dict[str, Any], key: str) -> float | None:
    value = row.get(key)
    return float(value) if value is not None else None


def _evaluate_daily_row(
    *,
    row: dict[str, Any],
    gates: dict[str, float],
    min_daily_samples: int,
) -> DailyMetricStatus:
    sample_size = int(row.get('sample_size') or 0)
    route_accuracy = _safe_weighted(row, 'route_accuracy')
    escalation_recall = _safe_weighted(row, 'escalation_recall')
    ece = _safe_weighted(row, 'ece')
    abstain_rate = _safe_weighted(row, 'abstain_rate')

    reasons: list[str] = []
    if sample_size < min_daily_samples:
        reasons.append('sample_size_below_min_daily')
    if route_accuracy is None or route_accuracy < gates['min_route_accuracy']:
        reasons.append('route_accuracy_below_gate')
    if escalation_recall is None or escalation_recall < gates['min_escalation_recall']:
        reasons.append('escalation_recall_below_gate')
    if ece is None or ece > gates['max_ece']:
        reasons.append('ece_above_gate')
    if abstain_rate is not None and abstain_rate > gates['max_abstain_rate']:
        reasons.append('abstain_rate_above_gate')

    return DailyMetricStatus(
        eval_date=row['eval_date'],
        sample_size=sample_size,
        route_accuracy=route_accuracy,
        escalation_recall=escalation_recall,
        ece=ece,
        abstain_rate=abstain_rate,
        passed=len(reasons) == 0,
        reasons=reasons,
    )


def _prometheus_query_scalar(
    *,
    base_url: str,
    query: str,
    eval_time: datetime,
    timeout_seconds: float = 10.0,
) -> float:
    response = httpx.get(
        f"{base_url.rstrip('/')}/api/v1/query",
        params={
            'query': query,
            'time': eval_time.isoformat(),
        },
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get('status') != 'success':
        raise RuntimeError(f'Prometheus query failed: {payload}')
    results = payload.get('data', {}).get('result', [])
    if not results:
        return 0.0
    values: list[float] = []
    for result in results:
        value_payload = result.get('value')
        if not isinstance(value_payload, list) or len(value_payload) < 2:
            continue
        try:
            values.append(float(value_payload[1]))
        except (TypeError, ValueError):
            continue
    if not values:
        return 0.0
    return max(values)


def _to_markdown(report: dict[str, Any]) -> str:
    status = 'PASS' if report['checks']['overall_passed'] else 'BLOCKED'
    lines = [
        f"# Live Rollout Validation ({status})",
        '',
        f"- Generated at (UTC): {report['generated_at_utc']}",
        f"- Validation window: {report['window']['start_date']} -> {report['window']['end_date']}",
        f"- Stable days required: {report['window']['stable_days_required']}",
        f"- Stable days observed: {report['window']['stable_days_observed']}",
        '',
        '## Checks',
        f"- quality_window_passed: {report['checks']['quality_passed']}",
        f"- drift_passed: {report['checks']['drift_passed']}",
        f"- labeling_passed: {report['checks']['labeling_passed']}",
        f"- slo_passed: {report['checks']['slo_passed']}",
        f"- canary_passed: {report['checks']['canary_passed']}",
        f"- rollback_drill_passed: {report['checks']['rollback_drill_passed']}",
        f"- calibration_passed: {report['checks']['calibration_passed']}",
        f"- overall_passed: {report['checks']['overall_passed']}",
        '',
        '## Blocking Reasons',
    ]
    reasons = report.get('blocking_reasons') or []
    if reasons:
        lines.extend([f'- {reason}' for reason in reasons])
    else:
        lines.append('- none')
    return '\n'.join(lines) + '\n'


def _persist_validation_report(
    conn: psycopg.Connection,
    *,
    report: dict[str, Any],
    blocking_reasons: list[str],
) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.rollout_validation_reports') IS NOT NULL AS table_exists;")
        row = cur.fetchone()
        exists = bool(row['table_exists']) if row is not None else False
        if not exists:
            return

        cur.execute(
            """
            INSERT INTO rollout_validation_reports (
              report_id,
              window_start,
              window_end,
              stable_days_required,
              stable_days_observed,
              min_daily_samples,
              quality_passed,
              drift_passed,
              labeling_passed,
              slo_passed,
              canary_passed,
              rollback_drill_passed,
              calibration_passed,
              overall_passed,
              blocking_reasons,
              summary
            )
            VALUES (
              %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            );
            """,
            (
                uuid4(),
                report['window']['start_date'],
                report['window']['end_date'],
                int(report['window']['stable_days_required']),
                int(report['window']['stable_days_observed']),
                int(report['window']['min_daily_samples']),
                bool(report['checks']['quality_passed']),
                bool(report['checks']['drift_passed']),
                bool(report['checks']['labeling_passed']),
                bool(report['checks']['slo_passed']),
                bool(report['checks']['canary_passed']),
                bool(report['checks']['rollback_drill_passed']),
                bool(report['checks']['calibration_passed']),
                bool(report['checks']['overall_passed']),
                Jsonb(blocking_reasons),
                Jsonb(report),
            ),
        )


def _build_report_paths(
    *,
    end_date: str,
    report_json: str,
    report_markdown: str,
) -> tuple[Path, Path]:
    base_dir = Path('artifacts/reports')
    if report_json.strip():
        json_path = Path(report_json.strip())
    else:
        json_path = base_dir / f'live_rollout_validation_{end_date}.json'
    if report_markdown.strip():
        markdown_path = Path(report_markdown.strip())
    else:
        markdown_path = base_dir / f'live_rollout_validation_{end_date}.md'
    return json_path, markdown_path


def validate_live_rollout(
    *,
    dsn: str,
    end_date_raw: str,
    stable_days_min: int,
    stable_days_max: int,
    min_daily_samples: int,
    min_ground_truth: int,
    min_calibration_samples: int,
    max_calibration_age_days: int,
    model_variant: str,
    tenant_id: str | None,
    section: str | None,
    prometheus_url: str,
    skip_slo_check: bool,
    report_json: str,
    report_markdown: str,
) -> tuple[bool, dict[str, Any], Path, Path]:
    end_date = _parse_date(end_date_raw)
    quality_window_days = max(1, int(stable_days_min))
    history_window_days = max(quality_window_days, int(stable_days_max))
    history_start = end_date - timedelta(days=history_window_days - 1)
    quality_start = end_date - timedelta(days=quality_window_days - 1)

    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                  quality_gate_min_route_accuracy,
                  quality_gate_min_escalation_recall,
                  quality_gate_max_ece,
                  quality_gate_max_abstain_rate,
                  quality_gate_min_sample_size,
                  canary_percent
                FROM model_rollout_config
                WHERE config_id = 'primary'
                LIMIT 1;
                """
            )
            gate_row = cur.fetchone()
            if gate_row is None:
                raise RuntimeError('model_rollout_config row with config_id=primary is missing. Apply migrations first.')

            gates = {
                'min_route_accuracy': float(gate_row['quality_gate_min_route_accuracy']),
                'min_escalation_recall': float(gate_row['quality_gate_min_escalation_recall']),
                'max_ece': float(gate_row['quality_gate_max_ece']),
                'max_abstain_rate': float(gate_row['quality_gate_max_abstain_rate']),
                'min_sample_size': max(1, int(gate_row['quality_gate_min_sample_size'])),
            }
            current_canary_percent = int(gate_row['canary_percent'])

            cur.execute(
                """
                WITH base AS (
                  SELECT
                    eval_date,
                    predicted_decision,
                    is_route_correct,
                    is_escalation_actual,
                    final_confidence
                  FROM evaluation_daily_dataset
                  WHERE eval_date >= %s::date
                    AND eval_date <= %s::date
                    AND model_variant = %s
                    AND source = 'shadow:canary'
                    AND (%s::text IS NULL OR tenant_id = %s::text)
                    AND (%s::text IS NULL OR section = %s::text)
                ),
                agg AS (
                  SELECT
                    eval_date,
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
                  GROUP BY eval_date
                ),
                ece_bins AS (
                  SELECT
                    eval_date,
                    width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10) AS bin_id,
                    COUNT(*) AS n_bin,
                    AVG(COALESCE(final_confidence, 0.0)) AS avg_conf,
                    AVG(CASE WHEN is_route_correct THEN 1.0 ELSE 0.0 END) AS avg_acc
                  FROM base
                  WHERE is_route_correct IS NOT NULL
                  GROUP BY eval_date, width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10)
                ),
                ece AS (
                  SELECT
                    eval_date,
                    SUM(ABS(COALESCE(avg_acc, 0.0) - COALESCE(avg_conf, 0.0)) * n_bin)::DOUBLE PRECISION
                    /
                    NULLIF(SUM(n_bin), 0)::DOUBLE PRECISION AS ece
                  FROM ece_bins
                  GROUP BY eval_date
                )
                SELECT
                  agg.eval_date,
                  agg.sample_size,
                  agg.route_accuracy,
                  agg.escalation_recall,
                  ece.ece,
                  agg.abstain_rate
                FROM agg
                LEFT JOIN ece
                  ON ece.eval_date = agg.eval_date
                ORDER BY agg.eval_date ASC;
                """,
                (
                    history_start.isoformat(),
                    end_date.isoformat(),
                    model_variant,
                    tenant_id,
                    tenant_id,
                    section,
                    section,
                ),
            )
            daily_rows = cur.fetchall()

            effective_min_daily_samples = max(int(min_daily_samples), int(gates['min_sample_size']))
            daily_statuses = [
                _evaluate_daily_row(
                    row=row,
                    gates=gates,
                    min_daily_samples=effective_min_daily_samples,
                )
                for row in daily_rows
            ]
            daily_pass_map = {status.eval_date: status.passed for status in daily_statuses}
            stable_days_observed = trailing_stable_days(
                end_date=end_date,
                daily_pass_map=daily_pass_map,
                max_days=history_window_days,
            )
            quality_passed = stable_days_observed >= quality_window_days

            cur.execute(
                """
                SELECT
                  COUNT(*) AS total_rows,
                  COUNT(*) FILTER (WHERE is_alert) AS alert_rows
                FROM drift_daily_metrics
                WHERE drift_date >= %s::date
                  AND drift_date <= %s::date
                  AND (%s::text IS NULL OR tenant_id = %s::text)
                  AND (%s::text IS NULL OR section = %s::text);
                """,
                (
                    quality_start.isoformat(),
                    end_date.isoformat(),
                    tenant_id,
                    tenant_id,
                    section,
                    section,
                ),
            )
            drift_row = cur.fetchone()
            drift_total_rows = int(drift_row['total_rows'] or 0)
            drift_alert_rows = int(drift_row['alert_rows'] or 0)
            drift_passed = drift_total_rows > 0 and drift_alert_rows == 0

            cur.execute(
                """
                SELECT COUNT(*) AS missing_count
                FROM handoffs h
                LEFT JOIN reviewer_outcomes ro
                  ON ro.handoff_id = h.handoff_id
                WHERE h.queue_status = 'closed'
                  AND ro.handoff_id IS NULL
                  AND (%s::text IS NULL OR h.tenant_id = %s::text);
                """,
                (
                    tenant_id,
                    tenant_id,
                ),
            )
            missing_closed = int((cur.fetchone() or {}).get('missing_count') or 0)

            cur.execute(
                """
                SELECT COUNT(*) AS labeled_count
                FROM reviewer_outcomes
                WHERE created_at::date >= %s::date
                  AND created_at::date <= %s::date
                  AND (%s::text IS NULL OR tenant_id = %s::text);
                """,
                (
                    quality_start.isoformat(),
                    end_date.isoformat(),
                    tenant_id,
                    tenant_id,
                ),
            )
            labeled_count = int((cur.fetchone() or {}).get('labeled_count') or 0)
            labeling_passed = missing_closed == 0 and labeled_count >= int(min_ground_truth)

            cur.execute("SELECT to_regclass('public.model_rollout_events') IS NOT NULL AS table_exists;")
            rollout_events_row = cur.fetchone()
            rollout_events_table_exists = bool(rollout_events_row['table_exists']) if rollout_events_row else False

            promoted_targets: list[int] = []
            rollback_apply_count = 0
            recent_events: list[dict[str, Any]] = []
            canary_started_eval_date: str | None = None
            full_rollout_eval_date: str | None = None
            if rollout_events_table_exists:
                cur.execute(
                    """
                    SELECT
                      created_at,
                      eval_date,
                      action,
                      apply_change,
                      current_percent,
                      target_percent,
                      gate_result,
                      sample_size,
                      details
                    FROM model_rollout_events
                    WHERE eval_date <= %s::date
                    ORDER BY created_at ASC;
                    """,
                    (end_date.isoformat(),),
                )
                for row in cur.fetchall():
                    recent_events.append(
                        {
                            'created_at': row['created_at'].isoformat(),
                            'eval_date': row['eval_date'].isoformat(),
                            'action': str(row['action']),
                            'apply_change': bool(row['apply_change']),
                            'current_percent': int(row['current_percent']),
                            'target_percent': int(row['target_percent']),
                            'gate_result': str(row['gate_result']),
                            'sample_size': int(row['sample_size'] or 0),
                            'details': row['details'] if isinstance(row['details'], dict) else {},
                        }
                    )
                    if bool(row['apply_change']) and str(row['action']) == 'promote':
                        target_percent = int(row['target_percent'])
                        promoted_targets.append(target_percent)
                        if target_percent >= 5 and canary_started_eval_date is None:
                            canary_started_eval_date = row['eval_date'].isoformat()
                        if target_percent >= 100:
                            full_rollout_eval_date = row['eval_date'].isoformat()
                    if bool(row['apply_change']) and str(row['action']) == 'rollback':
                        rollback_apply_count += 1

            canary_progression_ok = stage_progression_complete(promoted_targets)
            canary_passed = (
                rollout_events_table_exists
                and canary_progression_ok
                and current_canary_percent == 100
                and full_rollout_eval_date is not None
            )
            rollback_drill_passed = rollout_events_table_exists and rollback_apply_count > 0

            cur.execute(
                """
                SELECT DISTINCT ON (run_scope)
                  run_scope,
                  sample_size,
                  created_at
                FROM model_calibration_runs
                WHERE model_variant = %s
                ORDER BY run_scope, created_at DESC;
                """,
                ('primary',),
            )
            calibration_rows = cur.fetchall()
            latest_calibration_by_scope = {
                str(row['run_scope']): {
                    'sample_size': int(row['sample_size'] or 0),
                    'created_at': row['created_at'],
                }
                for row in calibration_rows
            }
            expected_scopes = {'routing_temperature', 'escalation_platt'}
            has_all_scopes = expected_scopes.issubset(set(latest_calibration_by_scope))
            latest_calibration_at = None
            calibration_age_days: int | None = None
            calibration_passed = False
            if has_all_scopes:
                latest_calibration_at = max(
                    latest_calibration_by_scope['routing_temperature']['created_at'],
                    latest_calibration_by_scope['escalation_platt']['created_at'],
                )
                calibration_age_days = max(0, (end_date - latest_calibration_at.date()).days)
                enough_samples = all(
                    latest_calibration_by_scope[scope]['sample_size'] >= int(min_calibration_samples)
                    for scope in expected_scopes
                )
                calibration_passed = calibration_age_days <= int(max_calibration_age_days) and enough_samples

            breached_alerts: list[str] = []
            slo_query_error = ''
            if skip_slo_check:
                slo_passed = True
            else:
                if not prometheus_url.strip():
                    slo_passed = False
                    slo_query_error = 'prometheus_url_missing'
                else:
                    eval_time = datetime.combine(end_date, time(hour=23, minute=59, second=59), tzinfo=timezone.utc)
                    try:
                        for alert_name in SLO_ALERTS:
                            query = (
                                f'max_over_time(ALERTS{{alertname="{alert_name}",alertstate="firing"}}'
                                f'[{quality_window_days}d])'
                            )
                            value = _prometheus_query_scalar(
                                base_url=prometheus_url,
                                query=query,
                                eval_time=eval_time,
                            )
                            if value > 0:
                                breached_alerts.append(alert_name)
                        slo_passed = len(breached_alerts) == 0
                    except Exception as exc:  # pragma: no cover - exercised in integration environments
                        slo_passed = False
                        slo_query_error = str(exc)

            blocking_reasons: list[str] = []
            if not quality_passed:
                blocking_reasons.append('insufficient_stable_canary_window')
            if not drift_passed:
                blocking_reasons.append('drift_alerts_or_missing_drift_rows')
            if not labeling_passed:
                blocking_reasons.append('labeling_integrity_not_met')
            if not slo_passed:
                blocking_reasons.append('slo_breach_or_slo_check_unavailable')
            if not canary_passed:
                blocking_reasons.append('canary_progression_not_complete_to_100')
            if not rollback_drill_passed:
                blocking_reasons.append('rollback_drill_not_recorded')
            if not calibration_passed:
                blocking_reasons.append('calibration_requirements_not_met')

            overall_passed = len(blocking_reasons) == 0
            report = {
                'generated_at_utc': datetime.now(timezone.utc).isoformat(),
                'window': {
                    'start_date': history_start.isoformat(),
                    'quality_start_date': quality_start.isoformat(),
                    'end_date': end_date.isoformat(),
                    'stable_days_required': quality_window_days,
                    'stable_days_observed': stable_days_observed,
                    'min_daily_samples': int(effective_min_daily_samples),
                },
                'scope': {
                    'model_variant': model_variant,
                    'tenant_id': tenant_id,
                    'section': section,
                },
                'gates': gates,
                'rollout': {
                    'current_canary_percent': current_canary_percent,
                    'required_stage_sequence': REQUIRED_CANARY_STAGES,
                    'promoted_targets': promoted_targets,
                    'canary_started_eval_date': canary_started_eval_date,
                    'full_rollout_eval_date': full_rollout_eval_date,
                    'recent_events': recent_events,
                },
                'quality_daily': [status.to_dict() for status in daily_statuses],
                'drift': {
                    'rows': drift_total_rows,
                    'alert_rows': drift_alert_rows,
                },
                'labeling': {
                    'missing_closed_without_outcome': missing_closed,
                    'labeled_count_in_quality_window': labeled_count,
                    'min_ground_truth_required': int(min_ground_truth),
                },
                'slo': {
                    'skipped': bool(skip_slo_check),
                    'breached_alerts': breached_alerts,
                    'query_error': slo_query_error,
                },
                'calibration': {
                    'latest_calibration_at': latest_calibration_at.isoformat() if latest_calibration_at else None,
                    'calibration_age_days': calibration_age_days,
                    'max_calibration_age_days': int(max_calibration_age_days),
                    'min_calibration_samples': int(min_calibration_samples),
                    'latest_by_scope': {
                        scope: {
                            'sample_size': latest_calibration_by_scope[scope]['sample_size'],
                            'created_at': latest_calibration_by_scope[scope]['created_at'].isoformat(),
                        }
                        for scope in sorted(latest_calibration_by_scope)
                    },
                },
                'checks': {
                    'quality_passed': quality_passed,
                    'drift_passed': drift_passed,
                    'labeling_passed': labeling_passed,
                    'slo_passed': slo_passed,
                    'canary_passed': canary_passed,
                    'rollback_drill_passed': rollback_drill_passed,
                    'calibration_passed': calibration_passed,
                    'overall_passed': overall_passed,
                },
                'blocking_reasons': blocking_reasons,
            }

            json_path, markdown_path = _build_report_paths(
                end_date=end_date.isoformat(),
                report_json=report_json,
                report_markdown=report_markdown,
            )
            json_path.parent.mkdir(parents=True, exist_ok=True)
            markdown_path.parent.mkdir(parents=True, exist_ok=True)
            json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf-8')
            markdown_path.write_text(_to_markdown(report), encoding='utf-8')

            _persist_validation_report(
                conn,
                report=report,
                blocking_reasons=blocking_reasons,
            )
            conn.commit()

    return overall_passed, report, json_path, markdown_path


def main() -> None:
    parser = argparse.ArgumentParser(description='Validate live production rollout criteria and write evidence artifacts.')
    parser.add_argument('--end-date', default=_default_end_date(), help='Validation end date (YYYY-MM-DD).')
    parser.add_argument('--stable-days-min', type=int, default=14, help='Minimum required stable trailing days.')
    parser.add_argument('--stable-days-max', type=int, default=28, help='Maximum historical window days to scan.')
    parser.add_argument('--min-daily-samples', type=int, default=50, help='Minimum daily challenger sample size.')
    parser.add_argument('--min-ground-truth', type=int, default=50, help='Minimum reviewer outcomes in quality window.')
    parser.add_argument(
        '--min-calibration-samples',
        type=int,
        default=200,
        help='Minimum labeled samples required per calibration scope.',
    )
    parser.add_argument('--max-calibration-age-days', type=int, default=7, help='Maximum allowed calibration age.')
    parser.add_argument('--model-variant', default='challenger')
    parser.add_argument('--tenant-id', default='', help='Optional tenant filter.')
    parser.add_argument('--section', default='', help='Optional section filter. Empty means all sections.')
    parser.add_argument('--prometheus-url', default='', help='Prometheus base URL for historical SLO checks.')
    parser.add_argument('--skip-slo-check', action='store_true', help='Skip Prometheus SLO breach validation.')
    parser.add_argument('--report-json', default='', help='Optional JSON report output path.')
    parser.add_argument('--report-markdown', default='', help='Optional Markdown report output path.')
    parser.add_argument('--fail-on-blocked', action='store_true', help='Exit non-zero when rollout criteria are blocked.')
    parser.add_argument(
        '--skip-db',
        action='store_true',
        help='Skip all DB-dependent checks (use when CI runner cannot reach the DB network).',
    )
    args = parser.parse_args()

    if args.skip_db:
        print(
            'Live rollout validation: SKIPPED (--skip-db). '
            'All DB-dependent checks bypassed — CI runner cannot reach the database network. '
            'Run this validation from within the cluster or via a bastion for full checks.'
        )
        sys.exit(0)

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)

    tenant_id = _normalize_optional_filter(args.tenant_id)
    section = _normalize_optional_filter(args.section)

    try:
        passed, report, json_path, markdown_path = validate_live_rollout(
            dsn=dsn,
            end_date_raw=args.end_date,
            stable_days_min=max(1, int(args.stable_days_min)),
            stable_days_max=max(1, int(args.stable_days_max)),
            min_daily_samples=max(1, int(args.min_daily_samples)),
            min_ground_truth=max(0, int(args.min_ground_truth)),
            min_calibration_samples=max(1, int(args.min_calibration_samples)),
            max_calibration_age_days=max(0, int(args.max_calibration_age_days)),
            model_variant=args.model_variant,
            tenant_id=tenant_id,
            section=section,
            prometheus_url=args.prometheus_url,
            skip_slo_check=bool(args.skip_slo_check),
            report_json=args.report_json,
            report_markdown=args.report_markdown,
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while validating live rollout. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    status = 'PASS' if passed else 'BLOCKED'
    print(
        f'Live rollout validation: {status}. '
        f"stable_days={report['window']['stable_days_observed']}/{report['window']['stable_days_required']}, "
        f"canary_percent={report['rollout']['current_canary_percent']}, "
        f"drift_alert_rows={report['drift']['alert_rows']}, "
        f"labeled_count={report['labeling']['labeled_count_in_quality_window']}"
    )
    print(f'Report JSON: {json_path}')
    print(f'Report Markdown: {markdown_path}')
    if report.get('blocking_reasons'):
        print(f"Blocking reasons: {', '.join(report['blocking_reasons'])}")

    if args.fail_on_blocked and not passed:
        sys.exit(2)


if __name__ == '__main__':
    main()
