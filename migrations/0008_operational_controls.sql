CREATE TABLE IF NOT EXISTS operational_control_events (
  event_id UUID PRIMARY KEY,
  control_type TEXT NOT NULL CHECK (
    control_type IN (
      'incident_endpoint_verification',
      'oncall_schedule_audit',
      'secret_rotation',
      'access_review',
      'incident_drill',
      'rollback_drill',
      'load_test',
      'soak_test',
      'failure_test'
    )
  ),
  status TEXT NOT NULL CHECK (status IN ('pass', 'fail', 'waived')),
  control_scope TEXT NOT NULL DEFAULT 'global',
  performed_at TIMESTAMPTZ NOT NULL,
  performed_by TEXT NOT NULL,
  evidence_uri TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_operational_control_events_type_performed
  ON operational_control_events (control_type, performed_at DESC);

CREATE INDEX IF NOT EXISTS idx_operational_control_events_scope_performed
  ON operational_control_events (control_scope, performed_at DESC);
