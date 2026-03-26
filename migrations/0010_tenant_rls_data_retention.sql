-- Migration 0010: tenant isolation (RLS), data retention, GDPR support
--
-- Enterprise requirements:
--   1. Row-Level Security (RLS) on all tenant-scoped tables
--   2. Data retention policies with automated soft-delete
--   3. GDPR right-to-erasure support (hard delete per tenant)
--   4. Encryption-at-rest markers for sensitive columns
--   5. Audit trail for data lifecycle events

-- ========================================================================
-- 1. ROW-LEVEL SECURITY (RLS) — enforce tenant isolation at DB level
-- ========================================================================
-- PostgreSQL RLS ensures that even if app-level bugs skip tenant filtering,
-- the database itself rejects cross-tenant access.
--
-- The app must SET app.current_tenant = '<tenant_id>' per connection/transaction.
-- A platform_admin role bypasses RLS.

-- Enable RLS on all tenant-scoped tables
ALTER TABLE doc_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE doc_chunks FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_requests FORCE ROW LEVEL SECURITY;
ALTER TABLE inference_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE inference_results FORCE ROW LEVEL SECURITY;
ALTER TABLE handoffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE handoffs FORCE ROW LEVEL SECURITY;
ALTER TABLE feedback_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE feedback_events FORCE ROW LEVEL SECURITY;
ALTER TABLE pii_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE pii_audit_events FORCE ROW LEVEL SECURITY;

-- Tenant isolation policies
CREATE POLICY tenant_isolation_doc_chunks ON doc_chunks
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_inference_requests ON inference_requests
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_inference_results ON inference_results
    USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_handoffs ON handoffs
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_feedback ON feedback_events
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_pii_audit ON pii_audit_events
    USING (tenant_id = current_setting('app.current_tenant', true));

-- Platform admin bypass (superuser role)
CREATE POLICY platform_admin_bypass_doc_chunks ON doc_chunks
    TO platform_admin USING (true) WITH CHECK (true);

CREATE POLICY platform_admin_bypass_inference_requests ON inference_requests
    TO platform_admin USING (true) WITH CHECK (true);

CREATE POLICY platform_admin_bypass_handoffs ON handoffs
    TO platform_admin USING (true) WITH CHECK (true);

-- ========================================================================
-- 2. DATA RETENTION POLICIES
-- ========================================================================
-- Soft-delete via `deleted_at` column + retention period tracking.
-- A background job purges rows where deleted_at < now() - retention_period.

CREATE TABLE IF NOT EXISTS data_retention_policies (
    policy_id       TEXT PRIMARY KEY,
    table_name      TEXT NOT NULL,
    retention_days  INTEGER NOT NULL DEFAULT 365,
    action          TEXT NOT NULL DEFAULT 'soft_delete'
                    CHECK (action IN ('soft_delete', 'hard_delete', 'anonymize')),
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Default retention policies — adjust per compliance framework
INSERT INTO data_retention_policies (policy_id, table_name, retention_days, action) VALUES
    ('ret_inference_requests', 'inference_requests', 365, 'anonymize'),
    ('ret_inference_results',  'inference_results',  365, 'anonymize'),
    ('ret_handoffs',           'handoffs',           180, 'soft_delete'),
    ('ret_feedback_events',    'feedback_events',    365, 'soft_delete'),
    ('ret_pii_audit_events',   'pii_audit_events',    90, 'hard_delete'),
    ('ret_shadow_predictions', 'model_shadow_predictions', 180, 'hard_delete')
ON CONFLICT (policy_id) DO NOTHING;

-- Add soft-delete columns where not present
ALTER TABLE inference_requests ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE inference_results  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE handoffs           ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE feedback_events    ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Index for efficient retention queries
CREATE INDEX IF NOT EXISTS idx_inference_requests_deleted
    ON inference_requests (deleted_at) WHERE deleted_at IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_handoffs_deleted
    ON handoffs (deleted_at) WHERE deleted_at IS NOT NULL;

-- ========================================================================
-- 3. GDPR RIGHT-TO-ERASURE
-- ========================================================================
-- Records erasure requests and tracks compliance.

CREATE TABLE IF NOT EXISTS erasure_requests (
    erasure_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL,
    requested_by    TEXT NOT NULL,
    reason          TEXT NOT NULL DEFAULT 'gdpr_right_to_erasure',
    status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending', 'in_progress', 'completed', 'failed')),
    tables_affected JSONB NOT NULL DEFAULT '[]',
    records_deleted INTEGER NOT NULL DEFAULT 0,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    error_message   TEXT
);

CREATE INDEX IF NOT EXISTS idx_erasure_requests_tenant
    ON erasure_requests (tenant_id, requested_at DESC);

-- ========================================================================
-- 4. DATA LIFECYCLE AUDIT
-- ========================================================================

CREATE TABLE IF NOT EXISTS data_lifecycle_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL
                    CHECK (event_type IN (
                        'retention_purge', 'erasure_request', 'erasure_completed',
                        'key_rotation', 'secret_rotation', 'export_request'
                    )),
    tenant_id       TEXT,
    table_name      TEXT,
    records_affected INTEGER NOT NULL DEFAULT 0,
    performed_by    TEXT NOT NULL DEFAULT 'system',
    metadata        JSONB NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_data_lifecycle_tenant
    ON data_lifecycle_events (tenant_id, created_at DESC);
