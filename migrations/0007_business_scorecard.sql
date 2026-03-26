CREATE TABLE IF NOT EXISTS ops_workload_daily (
  metric_date DATE NOT NULL,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  section TEXT NOT NULL DEFAULT '__all__',
  eligible_tickets_total INTEGER NOT NULL CHECK (eligible_tickets_total >= 0),
  active_agents_total INTEGER NOT NULL CHECK (active_agents_total >= 0),
  source TEXT NOT NULL DEFAULT 'manual',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (metric_date, tenant_id, section)
);

CREATE INDEX IF NOT EXISTS idx_ops_workload_daily_tenant_date
  ON ops_workload_daily (tenant_id, metric_date DESC);

CREATE TABLE IF NOT EXISTS business_kpi_targets (
  kpi_name TEXT PRIMARY KEY,
  comparator TEXT NOT NULL CHECK (comparator IN ('gte', 'lte')),
  target_value DOUBLE PRECISION NOT NULL,
  unit TEXT NOT NULL,
  description TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO business_kpi_targets (kpi_name, comparator, target_value, unit, description)
VALUES
  ('assisted_coverage_pct', 'gte', 0.80, 'ratio', 'Assisted coverage = assisted eligible tickets / eligible tickets'),
  ('agent_weekly_active_usage_pct', 'gte', 0.70, 'ratio', 'Weekly active usage = active reviewers / active agents'),
  ('feedback_completeness_pct', 'gte', 0.95, 'ratio', 'Closed handoffs with reviewer outcomes'),
  ('top1_route_accuracy_pct', 'gte', 0.85, 'ratio', 'Top-1 route accuracy for labeled decisions'),
  ('escalation_precision_pct', 'gte', 0.80, 'ratio', 'Escalation precision for labeled decisions'),
  ('escalation_recall_pct', 'gte', 0.75, 'ratio', 'Escalation recall for labeled decisions'),
  ('ece', 'lte', 0.10, 'ratio', 'Expected Calibration Error'),
  ('escalation_rate_reduction_pct', 'gte', 0.20, 'ratio', 'Escalation rate reduction vs baseline window'),
  ('median_handling_time_reduction_pct', 'gte', 0.25, 'ratio', 'Median handling time reduction vs baseline'),
  ('p90_handling_time_reduction_pct', 'gte', 0.15, 'ratio', 'P90 handling time reduction vs baseline')
ON CONFLICT (kpi_name) DO UPDATE SET
  comparator = EXCLUDED.comparator,
  target_value = EXCLUDED.target_value,
  unit = EXCLUDED.unit,
  description = EXCLUDED.description,
  updated_at = now();
