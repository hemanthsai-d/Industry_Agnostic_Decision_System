
CREATE TABLE IF NOT EXISTS intent_taxonomy (
    intent_id       TEXT PRIMARY KEY,
    category        TEXT NOT NULL,
    description     TEXT NOT NULL DEFAULT '',
    risk_level      TEXT NOT NULL DEFAULT 'medium' CHECK (risk_level IN ('low', 'medium', 'high')),
    keywords        JSONB NOT NULL DEFAULT '[]',
    escalation_hint REAL NOT NULL DEFAULT 0.10,
    is_active       BOOLEAN NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE intent_taxonomy IS 'Canonical intent catalog drawn from ABCD, Bitext, and Twitter support datasets.';

INSERT INTO intent_taxonomy (intent_id, category, description, risk_level, keywords, escalation_hint) VALUES
    ('create_account',          'ACCOUNT',          'Customer wants to create a new account',       'low',    '["create account","sign up","register","new account","open account"]', 0.05),
    ('delete_account',          'ACCOUNT',          'Customer wants to delete their account',       'medium', '["delete account","close account","remove account","deactivate"]', 0.25),
    ('edit_account',            'ACCOUNT',          'Customer wants to edit account details',       'low',    '["edit account","update account","change details","modify account"]', 0.05),
    ('switch_account',          'ACCOUNT',          'Customer wants to switch between accounts',    'low',    '["switch account","change account","different account"]', 0.05),
    ('recover_password',        'ACCOUNT',          'Customer needs password recovery',             'medium', '["password","forgot password","reset password","locked out","login"]', 0.15),
    ('registration_problems',   'ACCOUNT',          'Customer has trouble registering',             'medium', '["registration","signup error","cannot register"]', 0.15),
    ('place_order',             'ORDER',            'Customer wants to place an order',             'low',    '["place order","buy","purchase","order","checkout"]', 0.05),
    ('cancel_order',            'ORDER',            'Customer wants to cancel an order',            'medium', '["cancel order","cancel my order","cancel purchase"]', 0.15),
    ('change_order',            'ORDER',            'Customer wants to change an existing order',   'medium', '["change order","modify order","update order","edit order"]', 0.15),
    ('track_order',             'ORDER',            'Customer wants to track their order',          'low',    '["track order","where is my order","order status"]', 0.05),
    ('check_payment_methods',   'PAYMENT',          'Customer asks about payment methods',          'low',    '["payment method","how to pay","accepted payments"]', 0.05),
    ('payment_issue',           'PAYMENT',          'Customer has a payment problem',               'high',   '["payment issue","payment failed","declined","charged twice","double charge"]', 0.35),
    ('check_refund_policy',     'REFUND',           'Customer asks about refund policy',            'low',    '["refund policy","return policy","refund eligibility"]', 0.05),
    ('get_refund',              'REFUND',           'Customer requests a refund',                   'medium', '["refund","money back","get refund","want refund","request refund"]', 0.20),
    ('track_refund',            'REFUND',           'Customer wants to track refund status',        'low',    '["track refund","refund status","where is my refund"]', 0.05),
    ('delivery_options',        'SHIPPING',         'Customer asks about delivery options',         'low',    '["delivery option","shipping option","shipping method"]', 0.05),
    ('delivery_period',         'SHIPPING',         'Customer asks about delivery time',            'low',    '["delivery time","how long","estimated delivery","arrival"]', 0.05),
    ('change_shipping_address', 'SHIPPING',         'Customer wants to change shipping address',    'medium', '["change address","shipping address","wrong address"]', 0.10),
    ('set_up_shipping_address', 'SHIPPING',         'Customer wants to set up shipping address',    'low',    '["set up address","add address","new address"]', 0.05),
    ('shipping_delay',          'SHIPPING',         'Customer complains about shipping delay',      'medium', '["delay","late","delayed","shipping delay","not arrived","lost package"]', 0.20),
    ('check_invoice',           'INVOICE',          'Customer wants to check an invoice',           'low',    '["check invoice","view invoice","invoice details"]', 0.05),
    ('get_invoice',             'INVOICE',          'Customer wants to get/download an invoice',    'low',    '["get invoice","download invoice","send invoice","receipt"]', 0.05),
    ('check_cancellation_fee',  'CANCELLATION_FEE', 'Customer asks about cancellation fees',        'low',    '["cancellation fee","cancel fee","penalty"]', 0.10),
    ('complaint',               'FEEDBACK',         'Customer files a complaint',                   'high',   '["complaint","unhappy","dissatisfied","terrible","worst","angry"]', 0.40),
    ('review',                  'FEEDBACK',         'Customer leaves a review',                     'low',    '["review","feedback","rate","experience","suggestion"]', 0.05),
    ('newsletter_subscription', 'NEWSLETTER',       'Customer wants to manage newsletter',          'low',    '["newsletter","subscribe","unsubscribe","mailing list"]', 0.05),
    ('contact_customer_service','CONTACT',          'Customer wants to contact support',            'low',    '["contact","speak to","talk to","customer service"]', 0.10),
    ('contact_human_agent',     'CONTACT',          'Customer wants a human agent',                 'medium', '["human","real person","agent","representative","escalate","manager"]', 0.45),
    ('technical_issue',         'TECHNICAL',        'Customer reports a technical issue',           'medium', '["error","bug","crash","not working","broken","glitch"]', 0.20),
    ('general_inquiry',         'GENERAL',          'General support inquiry',                      'low',    '["help","support","question","information","how to"]', 0.05)
ON CONFLICT (intent_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS pii_audit_events (
    event_id        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id      TEXT,
    tenant_id       TEXT NOT NULL,
    entity_types    JSONB NOT NULL DEFAULT '[]',
    redacted_count  INTEGER NOT NULL DEFAULT 0,
    source_field    TEXT NOT NULL DEFAULT 'issue_text',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pii_audit_tenant_created
    ON pii_audit_events (tenant_id, created_at DESC);

COMMENT ON TABLE pii_audit_events IS 'Audit trail of PII detections and redactions for compliance.';

CREATE TYPE reindex_job_status AS ENUM ('queued', 'running', 'completed', 'failed');

CREATE TABLE IF NOT EXISTS reindex_jobs (
    job_id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id       TEXT NOT NULL,
    section         TEXT,
    status          reindex_job_status NOT NULL DEFAULT 'queued',
    chunks_indexed  INTEGER NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_reindex_jobs_tenant_status
    ON reindex_jobs (tenant_id, status);

COMMENT ON TABLE reindex_jobs IS 'Tracks reindex jobs queued via the /v1/assist/reindex endpoint.';

ALTER TABLE inference_results
    ADD COLUMN IF NOT EXISTS detected_intent TEXT,
    ADD COLUMN IF NOT EXISTS detected_category TEXT,
    ADD COLUMN IF NOT EXISTS pii_redacted BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS dataset_imports (
    import_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_source      TEXT NOT NULL,
    dataset_version     TEXT NOT NULL DEFAULT 'v1',
    record_count        INTEGER NOT NULL DEFAULT 0,
    import_type         TEXT NOT NULL DEFAULT 'retrieval_seed',
    imported_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    imported_by         TEXT NOT NULL DEFAULT 'system',
    metadata            JSONB NOT NULL DEFAULT '{}'
);

COMMENT ON TABLE dataset_imports IS 'Tracks external dataset imports for provenance and reproducibility.';
