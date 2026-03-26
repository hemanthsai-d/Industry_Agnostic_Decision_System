CREATE TABLE IF NOT EXISTS inference_requests (
  request_id UUID PRIMARY KEY,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  section TEXT,
  issue_text TEXT NOT NULL,
  risk_level TEXT NOT NULL,
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS inference_results (
  request_id UUID PRIMARY KEY REFERENCES inference_requests(request_id) ON DELETE CASCADE,
  decision TEXT NOT NULL CHECK (decision IN ('recommend','abstain','escalate')),
  top_resolution_path TEXT,
  top_resolution_prob DOUBLE PRECISION,
  escalation_prob DOUBLE PRECISION NOT NULL,
  final_confidence DOUBLE PRECISION NOT NULL,
  trace_id TEXT NOT NULL,
  policy_result JSONB NOT NULL,
  response_payload JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS handoffs (
  handoff_id UUID PRIMARY KEY,
  request_id UUID NOT NULL REFERENCES inference_requests(request_id) ON DELETE CASCADE,
  tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
  reason_codes TEXT[] NOT NULL,
  handoff_payload JSONB NOT NULL,
  queue_status TEXT NOT NULL DEFAULT 'open',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_inference_requests_tenant_created
  ON inference_requests (tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_handoffs_tenant_status
  ON handoffs (tenant_id, queue_status, created_at DESC);

