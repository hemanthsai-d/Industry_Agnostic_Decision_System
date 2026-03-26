ALTER TABLE model_rollout_config
  ADD COLUMN IF NOT EXISTS quality_gate_min_sample_size INTEGER NOT NULL DEFAULT 200
  CHECK (quality_gate_min_sample_size >= 1);
