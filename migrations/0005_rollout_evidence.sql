CREATE TABLE IF NOT EXISTS model_rollout_events (
  event_id UUID PRIMARY KEY,
  eval_date DATE NOT NULL,
  lookback_days INTEGER NOT NULL CHECK (lookback_days > 0),
  model_variant TEXT NOT NULL DEFAULT 'challenger',
  gate_result TEXT NOT NULL CHECK (gate_result IN ('pass', 'blocked')),
  action TEXT NOT NULL CHECK (action IN ('promote', 'rollback', 'hold')),
  apply_change BOOLEAN NOT NULL DEFAULT FALSE,
  rollback_on_fail BOOLEAN NOT NULL DEFAULT FALSE,
  current_percent INTEGER NOT NULL CHECK (current_percent >= 0 AND current_percent <= 100),
  target_percent INTEGER NOT NULL CHECK (target_percent >= 0 AND target_percent <= 100),
  sample_size INTEGER NOT NULL DEFAULT 0 CHECK (sample_size >= 0),
  route_accuracy DOUBLE PRECISION,
  escalation_recall DOUBLE PRECISION,
  ece DOUBLE PRECISION,
  abstain_rate DOUBLE PRECISION,
  gates JSONB NOT NULL DEFAULT '{}'::jsonb,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_rollout_events_created
  ON model_rollout_events (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_rollout_events_eval_date
  ON model_rollout_events (eval_date DESC);

CREATE TABLE IF NOT EXISTS rollout_validation_reports (
  report_id UUID PRIMARY KEY,
  window_start DATE NOT NULL,
  window_end DATE NOT NULL,
  stable_days_required INTEGER NOT NULL CHECK (stable_days_required >= 1),
  stable_days_observed INTEGER NOT NULL CHECK (stable_days_observed >= 0),
  min_daily_samples INTEGER NOT NULL CHECK (min_daily_samples >= 1),
  quality_passed BOOLEAN NOT NULL,
  drift_passed BOOLEAN NOT NULL,
  labeling_passed BOOLEAN NOT NULL,
  slo_passed BOOLEAN NOT NULL,
  canary_passed BOOLEAN NOT NULL,
  rollback_drill_passed BOOLEAN NOT NULL,
  calibration_passed BOOLEAN NOT NULL,
  overall_passed BOOLEAN NOT NULL,
  blocking_reasons JSONB NOT NULL DEFAULT '[]'::jsonb,
  summary JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rollout_validation_reports_created
  ON rollout_validation_reports (created_at DESC);
