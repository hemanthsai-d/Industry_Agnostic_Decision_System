ALTER TABLE inference_results
  ADD COLUMN IF NOT EXISTS model_variant TEXT NOT NULL DEFAULT 'primary';

ALTER TABLE inference_results
  ADD COLUMN IF NOT EXISTS model_backend_fallback BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS reviewer_outcomes (
  outcome_id UUID PRIMARY KEY,
  handoff_id UUID NOT NULL REFERENCES handoffs(handoff_id) ON DELETE CASCADE,
  request_id UUID NOT NULL REFERENCES inference_requests(request_id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  reviewer_id TEXT NOT NULL,
  final_decision TEXT NOT NULL CHECK (final_decision IN ('recommend','abstain','escalate')),
  final_resolution_path TEXT NOT NULL,
  notes TEXT,
  resolution_seconds INTEGER CHECK (resolution_seconds IS NULL OR resolution_seconds >= 0),
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_reviewer_outcomes_tenant_created
  ON reviewer_outcomes (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_reviewer_outcomes_request_created
  ON reviewer_outcomes (request_id, created_at DESC);

CREATE TABLE IF NOT EXISTS model_shadow_predictions (
  shadow_id UUID PRIMARY KEY,
  request_id UUID NOT NULL REFERENCES inference_requests(request_id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  model_name TEXT NOT NULL,
  model_version TEXT NOT NULL,
  model_variant TEXT NOT NULL DEFAULT 'challenger',
  traffic_bucket TEXT NOT NULL CHECK (traffic_bucket IN ('shadow','canary')),
  route_probabilities JSONB NOT NULL,
  top_resolution_path TEXT,
  top_resolution_prob DOUBLE PRECISION,
  escalation_prob DOUBLE PRECISION NOT NULL,
  final_confidence DOUBLE PRECISION,
  decision TEXT CHECK (decision IN ('recommend','abstain','escalate')),
  model_backend_fallback BOOLEAN NOT NULL DEFAULT FALSE,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_model_shadow_predictions_tenant_created
  ON model_shadow_predictions (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_model_shadow_predictions_variant_created
  ON model_shadow_predictions (model_variant, traffic_bucket, created_at DESC);

CREATE TABLE IF NOT EXISTS model_rollout_config (
  config_id TEXT PRIMARY KEY,
  challenger_model_name TEXT NOT NULL,
  challenger_model_version TEXT NOT NULL,
  canary_percent INTEGER NOT NULL DEFAULT 0 CHECK (canary_percent >= 0 AND canary_percent <= 100),
  quality_gate_min_route_accuracy DOUBLE PRECISION NOT NULL DEFAULT 0.75,
  quality_gate_min_escalation_recall DOUBLE PRECISION NOT NULL DEFAULT 0.70,
  quality_gate_max_ece DOUBLE PRECISION NOT NULL DEFAULT 0.15,
  quality_gate_max_abstain_rate DOUBLE PRECISION NOT NULL DEFAULT 0.35,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO model_rollout_config (
  config_id,
  challenger_model_name,
  challenger_model_version,
  canary_percent,
  quality_gate_min_route_accuracy,
  quality_gate_min_escalation_recall,
  quality_gate_max_ece,
  quality_gate_max_abstain_rate
)
VALUES (
  'primary',
  'challenger-routing',
  'v1',
  0,
  0.75,
  0.70,
  0.15,
  0.35
)
ON CONFLICT (config_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS evaluation_daily_dataset (
  eval_date DATE NOT NULL,
  request_id UUID NOT NULL,
  tenant_id TEXT NOT NULL,
  section TEXT,
  model_variant TEXT NOT NULL,
  predicted_decision TEXT,
  predicted_route TEXT,
  predicted_route_prob DOUBLE PRECISION,
  escalation_prob DOUBLE PRECISION,
  final_confidence DOUBLE PRECISION,
  ground_truth_decision TEXT,
  ground_truth_route TEXT,
  is_route_correct BOOLEAN,
  is_escalation_pred BOOLEAN,
  is_escalation_actual BOOLEAN,
  issue_token_count INTEGER,
  resolution_seconds INTEGER,
  source TEXT NOT NULL DEFAULT 'inference_results',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (eval_date, request_id, model_variant)
);

CREATE INDEX IF NOT EXISTS idx_evaluation_daily_dataset_tenant_section
  ON evaluation_daily_dataset (eval_date, tenant_id, section, model_variant);

CREATE TABLE IF NOT EXISTS evaluation_daily_metrics (
  eval_date DATE NOT NULL,
  tenant_id TEXT NOT NULL,
  section TEXT NOT NULL,
  model_variant TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  route_accuracy DOUBLE PRECISION,
  escalation_precision DOUBLE PRECISION,
  escalation_recall DOUBLE PRECISION,
  ece DOUBLE PRECISION,
  abstain_rate DOUBLE PRECISION,
  avg_time_to_resolution_seconds DOUBLE PRECISION,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (eval_date, tenant_id, section, model_variant)
);

CREATE TABLE IF NOT EXISTS drift_daily_metrics (
  drift_date DATE NOT NULL,
  tenant_id TEXT NOT NULL,
  section TEXT NOT NULL,
  metric_name TEXT NOT NULL,
  baseline_value DOUBLE PRECISION NOT NULL,
  current_value DOUBLE PRECISION NOT NULL,
  delta_value DOUBLE PRECISION NOT NULL,
  threshold DOUBLE PRECISION NOT NULL,
  is_alert BOOLEAN NOT NULL DEFAULT FALSE,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (drift_date, tenant_id, section, metric_name)
);

CREATE TABLE IF NOT EXISTS model_calibration_runs (
  run_id UUID PRIMARY KEY,
  run_scope TEXT NOT NULL CHECK (run_scope IN ('routing_temperature','escalation_platt')),
  model_variant TEXT NOT NULL,
  sample_size INTEGER NOT NULL,
  metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
  artifact_path TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE OR REPLACE VIEW vw_latest_ground_truth AS
WITH latest_feedback AS (
  SELECT
    ranked.request_id_uuid AS request_id,
    ranked.tenant_id,
    ranked.accepted_decision,
    ranked.corrected_resolution_path,
    ranked.notes,
    ranked.created_at
  FROM (
    SELECT
      request_id_uuid,
      tenant_id,
      accepted_decision,
      corrected_resolution_path,
      notes,
      created_at,
      ROW_NUMBER() OVER (
        PARTITION BY request_id_uuid, tenant_id
        ORDER BY created_at DESC
      ) AS rn
    FROM feedback_events
    WHERE request_id_uuid IS NOT NULL
  ) AS ranked
  WHERE ranked.rn = 1
),
latest_reviewer AS (
  SELECT
    ranked.request_id,
    ranked.tenant_id,
    ranked.final_decision,
    ranked.final_resolution_path,
    ranked.notes,
    ranked.resolution_seconds,
    ranked.created_at
  FROM (
    SELECT
      request_id,
      tenant_id,
      final_decision,
      final_resolution_path,
      notes,
      resolution_seconds,
      created_at,
      ROW_NUMBER() OVER (
        PARTITION BY request_id, tenant_id
        ORDER BY created_at DESC
      ) AS rn
    FROM reviewer_outcomes
  ) AS ranked
  WHERE ranked.rn = 1
)
SELECT
  COALESCE(lr.request_id, lf.request_id) AS request_id,
  COALESCE(lr.tenant_id, lf.tenant_id) AS tenant_id,
  lr.final_decision AS reviewer_final_decision,
  lr.final_resolution_path AS reviewer_final_resolution_path,
  lf.accepted_decision AS feedback_decision,
  lf.corrected_resolution_path AS feedback_resolution_path,
  COALESCE(lr.final_decision, lf.accepted_decision) AS ground_truth_decision,
  COALESCE(lr.final_resolution_path, lf.corrected_resolution_path) AS ground_truth_route,
  lr.resolution_seconds,
  COALESCE(lr.created_at, lf.created_at) AS ground_truth_created_at
FROM latest_reviewer lr
FULL OUTER JOIN latest_feedback lf
  ON lr.request_id = lf.request_id
  AND lr.tenant_id = lf.tenant_id;

CREATE OR REPLACE VIEW vw_model_prediction_events AS
SELECT
  ir.created_at::date AS eval_date,
  ir.request_id,
  ir.tenant_id,
  ir.section,
  ir.issue_text,
  res.model_variant,
  res.decision AS predicted_decision,
  res.top_resolution_path AS predicted_route,
  res.top_resolution_prob AS predicted_route_prob,
  res.escalation_prob,
  res.final_confidence,
  res.model_backend_fallback,
  'inference_results'::text AS source
FROM inference_requests ir
JOIN inference_results res
  ON res.request_id = ir.request_id

UNION ALL

SELECT
  sp.created_at::date AS eval_date,
  sp.request_id,
  sp.tenant_id,
  ir.section,
  ir.issue_text,
  sp.model_variant,
  COALESCE(sp.decision, CASE WHEN sp.escalation_prob >= 0.5 THEN 'escalate' ELSE 'recommend' END) AS predicted_decision,
  sp.top_resolution_path AS predicted_route,
  sp.top_resolution_prob AS predicted_route_prob,
  sp.escalation_prob,
  sp.final_confidence,
  sp.model_backend_fallback,
  ('shadow:' || sp.traffic_bucket)::text AS source
FROM model_shadow_predictions sp
JOIN inference_requests ir
  ON ir.request_id = sp.request_id
  AND ir.tenant_id = sp.tenant_id;
