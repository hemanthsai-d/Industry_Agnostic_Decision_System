CREATE TABLE IF NOT EXISTS feedback_events (
  event_id UUID PRIMARY KEY,
  request_id_text TEXT NOT NULL,
  request_id_uuid UUID,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  accepted_decision TEXT CHECK (accepted_decision IN ('recommend','abstain','escalate')),
  corrected_resolution_path TEXT,
  notes TEXT,
  payload JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feedback_events_tenant_created
  ON feedback_events (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_feedback_events_request_text
  ON feedback_events (request_id_text);

