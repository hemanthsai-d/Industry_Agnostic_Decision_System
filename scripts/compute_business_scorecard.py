from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import sys
from typing import Any

import psycopg
from psycopg.rows import dict_row

from app.core.config import get_settings
from app.storage.postgres_store import to_psycopg_dsn


SCORECARD_SQL = """
WITH params AS (
  SELECT
    %(window_start)s::date AS window_start,
    %(window_end)s::date AS window_end,
    %(baseline_start)s::date AS baseline_start,
    %(baseline_end)s::date AS baseline_end,
    GREATEST((%(window_end)s::date - INTERVAL '6 day')::date, %(window_start)s::date) AS wau_start,
    %(tenant_id)s::text AS tenant_filter,
    %(section)s::text AS section_filter,
    %(model_variant)s::text AS model_variant
),
targets AS (
  SELECT
    kpi_name,
    comparator,
    target_value,
    unit,
    description
  FROM business_kpi_targets
),
current_assist AS (
  SELECT COUNT(*)::DOUBLE PRECISION AS n
  FROM inference_requests ir
  JOIN inference_results res
    ON res.request_id = ir.request_id
  JOIN params p
    ON TRUE
  WHERE ir.created_at::date BETWEEN p.window_start AND p.window_end
    AND res.model_variant = p.model_variant
    AND (p.tenant_filter IS NULL OR ir.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(ir.section, '__all__') = p.section_filter)
),
eligible_total AS (
  SELECT SUM(owd.eligible_tickets_total)::DOUBLE PRECISION AS n
  FROM ops_workload_daily owd
  JOIN params p
    ON TRUE
  WHERE owd.metric_date BETWEEN p.window_start AND p.window_end
    AND (p.tenant_filter IS NULL OR owd.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR owd.section = p.section_filter)
),
active_reviewers AS (
  SELECT COUNT(DISTINCT ro.reviewer_id)::DOUBLE PRECISION AS n
  FROM reviewer_outcomes ro
  JOIN inference_requests ir
    ON ir.request_id = ro.request_id
   AND ir.tenant_id = ro.tenant_id
  JOIN params p
    ON TRUE
  WHERE ro.created_at::date BETWEEN p.wau_start AND p.window_end
    AND (p.tenant_filter IS NULL OR ro.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(ir.section, '__all__') = p.section_filter)
),
active_agents AS (
  SELECT MAX(owd.active_agents_total)::DOUBLE PRECISION AS n
  FROM ops_workload_daily owd
  JOIN params p
    ON TRUE
  WHERE owd.metric_date BETWEEN p.wau_start AND p.window_end
    AND (p.tenant_filter IS NULL OR owd.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR owd.section = p.section_filter)
),
closed_handoffs AS (
  SELECT COUNT(*)::DOUBLE PRECISION AS closed_total
  FROM handoffs h
  JOIN inference_requests ir
    ON ir.request_id = h.request_id
  JOIN params p
    ON TRUE
  WHERE h.queue_status = 'closed'
    AND ir.created_at::date BETWEEN p.window_start AND p.window_end
    AND (p.tenant_filter IS NULL OR h.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(ir.section, '__all__') = p.section_filter)
),
closed_handoffs_with_outcome AS (
  SELECT COUNT(*)::DOUBLE PRECISION AS n
  FROM handoffs h
  JOIN inference_requests ir
    ON ir.request_id = h.request_id
  JOIN params p
    ON TRUE
  WHERE h.queue_status = 'closed'
    AND ir.created_at::date BETWEEN p.window_start AND p.window_end
    AND (p.tenant_filter IS NULL OR h.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(ir.section, '__all__') = p.section_filter)
    AND EXISTS (
      SELECT 1
      FROM reviewer_outcomes ro
      WHERE ro.handoff_id = h.handoff_id
    )
),
labeled_current AS (
  SELECT
    edd.predicted_decision,
    edd.is_route_correct,
    edd.is_escalation_pred,
    edd.is_escalation_actual,
    edd.final_confidence,
    edd.resolution_seconds
  FROM evaluation_daily_dataset edd
  JOIN params p
    ON TRUE
  WHERE edd.eval_date BETWEEN p.window_start AND p.window_end
    AND edd.source = 'inference_results'
    AND edd.model_variant = p.model_variant
    AND edd.ground_truth_decision IS NOT NULL
    AND (p.tenant_filter IS NULL OR edd.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(edd.section, '__all__') = p.section_filter)
),
labeled_baseline AS (
  SELECT
    edd.predicted_decision,
    edd.is_route_correct,
    edd.is_escalation_pred,
    edd.is_escalation_actual,
    edd.resolution_seconds
  FROM evaluation_daily_dataset edd
  JOIN params p
    ON TRUE
  WHERE edd.eval_date BETWEEN p.baseline_start AND p.baseline_end
    AND edd.source = 'inference_results'
    AND edd.model_variant = p.model_variant
    AND edd.ground_truth_decision IS NOT NULL
    AND (p.tenant_filter IS NULL OR edd.tenant_id = p.tenant_filter)
    AND (p.section_filter IS NULL OR COALESCE(edd.section, '__all__') = p.section_filter)
),
current_escalation_rate AS (
  SELECT AVG(CASE WHEN predicted_decision = 'escalate' THEN 1.0 ELSE 0.0 END) AS v
  FROM labeled_current
),
baseline_escalation_rate AS (
  SELECT AVG(CASE WHEN predicted_decision = 'escalate' THEN 1.0 ELSE 0.0 END) AS v
  FROM labeled_baseline
),
current_handling AS (
  SELECT
    percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_seconds::DOUBLE PRECISION) AS p50,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_seconds::DOUBLE PRECISION) AS p90
  FROM labeled_current
  WHERE resolution_seconds IS NOT NULL
),
baseline_handling AS (
  SELECT
    percentile_cont(0.5) WITHIN GROUP (ORDER BY resolution_seconds::DOUBLE PRECISION) AS p50,
    percentile_cont(0.9) WITHIN GROUP (ORDER BY resolution_seconds::DOUBLE PRECISION) AS p90
  FROM labeled_baseline
  WHERE resolution_seconds IS NOT NULL
),
ece_bins AS (
  SELECT
    width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10) AS bin_id,
    COUNT(*) AS n_bin,
    AVG(COALESCE(final_confidence, 0.0)) AS avg_conf,
    AVG(CASE WHEN is_route_correct THEN 1.0 ELSE 0.0 END) AS avg_acc
  FROM labeled_current
  WHERE is_route_correct IS NOT NULL
  GROUP BY width_bucket(COALESCE(final_confidence, 0.0), 0.0, 1.0, 10)
),
ece_value AS (
  SELECT
    SUM(ABS(COALESCE(avg_acc, 0.0) - COALESCE(avg_conf, 0.0)) * n_bin)::DOUBLE PRECISION
    / NULLIF(SUM(n_bin), 0)::DOUBLE PRECISION AS v
  FROM ece_bins
),
kpis AS (
  SELECT
    'assisted_coverage_pct'::text AS kpi_name,
    CASE
      WHEN COALESCE((SELECT n FROM eligible_total), 0) = 0 THEN NULL
      ELSE (SELECT n FROM current_assist) / NULLIF((SELECT n FROM eligible_total), 0)
    END AS actual_value,
    jsonb_build_object(
      'assisted_requests', (SELECT n FROM current_assist),
      'eligible_tickets', (SELECT n FROM eligible_total)
    ) AS details

  UNION ALL

  SELECT
    'agent_weekly_active_usage_pct',
    CASE
      WHEN COALESCE((SELECT n FROM active_agents), 0) = 0 THEN NULL
      ELSE (SELECT n FROM active_reviewers) / NULLIF((SELECT n FROM active_agents), 0)
    END,
    jsonb_build_object(
      'active_reviewers_7d', (SELECT n FROM active_reviewers),
      'active_agents_7d', (SELECT n FROM active_agents)
    )

  UNION ALL

  SELECT
    'feedback_completeness_pct',
    CASE
      WHEN COALESCE((SELECT closed_total FROM closed_handoffs), 0) = 0 THEN NULL
      ELSE (SELECT n FROM closed_handoffs_with_outcome) / NULLIF((SELECT closed_total FROM closed_handoffs), 0)
    END,
    jsonb_build_object(
      'closed_handoffs', (SELECT closed_total FROM closed_handoffs),
      'closed_with_outcome', (SELECT n FROM closed_handoffs_with_outcome)
    )

  UNION ALL

  SELECT
    'top1_route_accuracy_pct',
    AVG(CASE WHEN is_route_correct IS NULL THEN NULL WHEN is_route_correct THEN 1.0 ELSE 0.0 END),
    jsonb_build_object('labeled_samples', COUNT(*))
  FROM labeled_current

  UNION ALL

  SELECT
    'escalation_precision_pct',
    CASE
      WHEN SUM(CASE WHEN is_escalation_pred THEN 1 ELSE 0 END) = 0 THEN NULL
      ELSE
        SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
        / NULLIF(SUM(CASE WHEN is_escalation_pred THEN 1 ELSE 0 END)::DOUBLE PRECISION, 0)
    END,
    jsonb_build_object(
      'predicted_escalations', SUM(CASE WHEN is_escalation_pred THEN 1 ELSE 0 END),
      'true_positive_escalations', SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)
    )
  FROM labeled_current

  UNION ALL

  SELECT
    'escalation_recall_pct',
    CASE
      WHEN SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END) = 0 THEN NULL
      ELSE
        SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION
        / NULLIF(SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END)::DOUBLE PRECISION, 0)
    END,
    jsonb_build_object(
      'actual_escalations', SUM(CASE WHEN is_escalation_actual THEN 1 ELSE 0 END),
      'true_positive_escalations', SUM(CASE WHEN is_escalation_pred AND is_escalation_actual THEN 1 ELSE 0 END)
    )
  FROM labeled_current

  UNION ALL

  SELECT
    'ece',
    (SELECT v FROM ece_value),
    jsonb_build_object('ece_bins', (SELECT COUNT(*) FROM ece_bins))

  UNION ALL

  SELECT
    'escalation_rate_reduction_pct',
    CASE
      WHEN COALESCE((SELECT v FROM baseline_escalation_rate), 0.0) = 0.0 THEN NULL
      ELSE ((SELECT v FROM baseline_escalation_rate) - (SELECT v FROM current_escalation_rate))
        / NULLIF((SELECT v FROM baseline_escalation_rate), 0.0)
    END,
    jsonb_build_object(
      'current_escalation_rate', (SELECT v FROM current_escalation_rate),
      'baseline_escalation_rate', (SELECT v FROM baseline_escalation_rate)
    )

  UNION ALL

  SELECT
    'median_handling_time_reduction_pct',
    CASE
      WHEN COALESCE((SELECT p50 FROM baseline_handling), 0.0) = 0.0 THEN NULL
      ELSE ((SELECT p50 FROM baseline_handling) - (SELECT p50 FROM current_handling))
        / NULLIF((SELECT p50 FROM baseline_handling), 0.0)
    END,
    jsonb_build_object(
      'current_p50_seconds', (SELECT p50 FROM current_handling),
      'baseline_p50_seconds', (SELECT p50 FROM baseline_handling)
    )

  UNION ALL

  SELECT
    'p90_handling_time_reduction_pct',
    CASE
      WHEN COALESCE((SELECT p90 FROM baseline_handling), 0.0) = 0.0 THEN NULL
      ELSE ((SELECT p90 FROM baseline_handling) - (SELECT p90 FROM current_handling))
        / NULLIF((SELECT p90 FROM baseline_handling), 0.0)
    END,
    jsonb_build_object(
      'current_p90_seconds', (SELECT p90 FROM current_handling),
      'baseline_p90_seconds', (SELECT p90 FROM baseline_handling)
    )
)
SELECT
  t.kpi_name,
  t.comparator,
  t.target_value,
  t.unit,
  t.description,
  k.actual_value,
  CASE
    WHEN k.actual_value IS NULL THEN 'insufficient_data'
    WHEN t.comparator = 'gte' AND k.actual_value >= t.target_value THEN 'pass'
    WHEN t.comparator = 'lte' AND k.actual_value <= t.target_value THEN 'pass'
    ELSE 'fail'
  END AS status,
  k.details
FROM targets t
LEFT JOIN kpis k
  ON k.kpi_name = t.kpi_name
ORDER BY t.kpi_name;
"""


@dataclass
class ScorecardRow:
    kpi_name: str
    comparator: str
    target_value: float
    unit: str
    description: str
    actual_value: float | None
    status: str
    details: dict[str, Any]


def _default_window_end() -> date:
    return datetime.now(timezone.utc).date() - timedelta(days=1)


def _build_output_paths(window_end: date) -> tuple[Path, Path]:
    stamp = window_end.isoformat()
    json_path = Path(f'artifacts/reports/business_scorecard_{stamp}.json')
    md_path = Path(f'artifacts/reports/business_scorecard_{stamp}.md')
    return json_path, md_path


def _format_pct(value: float | None) -> str:
    if value is None:
        return 'n/a'
    return f'{value * 100:.2f}%'


def _format_ratio(value: float | None) -> str:
    if value is None:
        return 'n/a'
    return f'{value:.4f}'


def _format_value(unit: str, value: float | None) -> str:
    if unit == 'ratio':
        return _format_pct(value)
    return _format_ratio(value)


def _to_row(raw: dict[str, Any]) -> ScorecardRow:
    details = raw.get('details')
    return ScorecardRow(
        kpi_name=str(raw.get('kpi_name', '')),
        comparator=str(raw.get('comparator', '')),
        target_value=float(raw.get('target_value', 0.0)),
        unit=str(raw.get('unit', 'ratio')),
        description=str(raw.get('description', '')),
        actual_value=float(raw['actual_value']) if raw.get('actual_value') is not None else None,
        status=str(raw.get('status', 'insufficient_data')),
        details=dict(details) if isinstance(details, dict) else {},
    )


def compute_business_scorecard(
    dsn: str,
    window_start: date,
    window_end: date,
    baseline_start: date,
    baseline_end: date,
    tenant_id: str | None,
    section: str | None,
    model_variant: str,
) -> list[ScorecardRow]:
    payload = {
        'window_start': window_start.isoformat(),
        'window_end': window_end.isoformat(),
        'baseline_start': baseline_start.isoformat(),
        'baseline_end': baseline_end.isoformat(),
        'tenant_id': tenant_id,
        'section': section,
        'model_variant': model_variant,
    }
    with psycopg.connect(dsn, row_factory=dict_row) as conn:
        with conn.cursor() as cur:
            cur.execute(SCORECARD_SQL, payload)
            rows = cur.fetchall()
    return [_to_row(dict(row)) for row in rows]


def write_reports(
    rows: list[ScorecardRow],
    window_start: date,
    window_end: date,
    baseline_start: date,
    baseline_end: date,
    tenant_id: str | None,
    section: str | None,
    model_variant: str,
    json_path: Path,
    md_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'window': {
            'current_start': window_start.isoformat(),
            'current_end': window_end.isoformat(),
            'baseline_start': baseline_start.isoformat(),
            'baseline_end': baseline_end.isoformat(),
        },
        'filters': {
            'tenant_id': tenant_id,
            'section': section,
            'model_variant': model_variant,
        },
        'rows': [
            {
                'kpi_name': row.kpi_name,
                'comparator': row.comparator,
                'target_value': row.target_value,
                'unit': row.unit,
                'description': row.description,
                'actual_value': row.actual_value,
                'status': row.status,
                'details': row.details,
            }
            for row in rows
        ],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

    lines = [
        '# Business KPI Scorecard',
        '',
        f"- Generated at (UTC): {payload['generated_at_utc']}",
        f"- Current window: {window_start.isoformat()} -> {window_end.isoformat()}",
        f"- Baseline window: {baseline_start.isoformat()} -> {baseline_end.isoformat()}",
        f"- Tenant filter: {tenant_id or '__all__'}",
        f"- Section filter: {section or '__all__'}",
        f"- Model variant: {model_variant}",
        '',
        '| KPI | Target | Actual | Status |',
        '|---|---:|---:|---|',
    ]
    for row in rows:
        comparator = '>=' if row.comparator == 'gte' else '<='
        lines.append(
            f"| `{row.kpi_name}` | {comparator} {_format_value(row.unit, row.target_value)} | "
            f"{_format_value(row.unit, row.actual_value)} | `{row.status}` |"
        )

    lines.extend(['', '## KPI Details'])
    for row in rows:
        lines.append('')
        lines.append(f"### `{row.kpi_name}`")
        lines.append(f"- Description: {row.description}")
        lines.append(f"- Details: `{json.dumps(row.details, separators=(',', ':'))}`")

    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def main() -> None:
    parser = argparse.ArgumentParser(description='Compute business adoption and impact KPI scorecard.')
    parser.add_argument('--window-start', help='Current window start date (YYYY-MM-DD). Defaults to 28-day trailing window.')
    parser.add_argument('--window-end', help='Current window end date (YYYY-MM-DD). Defaults to yesterday UTC.')
    parser.add_argument('--baseline-start', help='Baseline window start date (YYYY-MM-DD). Defaults to prior 28-day window.')
    parser.add_argument('--baseline-end', help='Baseline window end date (YYYY-MM-DD). Defaults to day before current window.')
    parser.add_argument('--tenant-id', default='', help='Optional tenant filter.')
    parser.add_argument('--section', default='', help='Optional section filter.')
    parser.add_argument('--model-variant', default='primary', help='Model variant filter.')
    parser.add_argument('--output-json', default='', help='Optional output JSON path.')
    parser.add_argument('--output-markdown', default='', help='Optional output Markdown path.')
    parser.add_argument('--fail-on-miss', action='store_true', help='Exit with code 2 when any KPI fails or lacks data.')
    args = parser.parse_args()

    today_end = _default_window_end()
    window_end = date.fromisoformat(args.window_end) if args.window_end else today_end
    window_start = date.fromisoformat(args.window_start) if args.window_start else (window_end - timedelta(days=27))
    baseline_end = date.fromisoformat(args.baseline_end) if args.baseline_end else (window_start - timedelta(days=1))
    baseline_start = (
        date.fromisoformat(args.baseline_start)
        if args.baseline_start
        else (baseline_end - timedelta(days=(window_end - window_start).days))
    )

    if window_start > window_end:
        raise ValueError('window-start must be <= window-end')
    if baseline_start > baseline_end:
        raise ValueError('baseline-start must be <= baseline-end')

    settings = get_settings()
    dsn = to_psycopg_dsn(settings.postgres_dsn)
    tenant_id = args.tenant_id.strip() or None
    section = args.section.strip() or None

    try:
        rows = compute_business_scorecard(
            dsn=dsn,
            window_start=window_start,
            window_end=window_end,
            baseline_start=baseline_start,
            baseline_end=baseline_end,
            tenant_id=tenant_id,
            section=section,
            model_variant=args.model_variant.strip(),
        )
    except psycopg.OperationalError as exc:
        print(
            'Database connection failed while computing business scorecard. '
            'Ensure Postgres is running and migrations are applied.\n'
            f'Details: {exc}'
        )
        sys.exit(1)

    default_json, default_md = _build_output_paths(window_end)
    json_path = Path(args.output_json) if args.output_json else default_json
    md_path = Path(args.output_markdown) if args.output_markdown else default_md
    write_reports(
        rows=rows,
        window_start=window_start,
        window_end=window_end,
        baseline_start=baseline_start,
        baseline_end=baseline_end,
        tenant_id=tenant_id,
        section=section,
        model_variant=args.model_variant.strip(),
        json_path=json_path,
        md_path=md_path,
    )

    failed = [row for row in rows if row.status != 'pass']
    print(
        'Business scorecard complete. '
        f'rows={len(rows)}, failed_or_missing={len(failed)}, '
        f'json={json_path}, markdown={md_path}'
    )
    for row in rows:
        print(
            f"- {row.kpi_name}: target={row.comparator} {row.target_value:.4f}, "
            f"actual={row.actual_value if row.actual_value is not None else 'n/a'}, status={row.status}"
        )

    if args.fail_on_miss and failed:
        sys.exit(2)


if __name__ == '__main__':
    main()
