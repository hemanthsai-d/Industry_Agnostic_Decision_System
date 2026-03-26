# Production Completion Playbook

This checklist closes the final production-readiness gaps:
1. real incident endpoint verification
2. on-call schedule audit
3. live traffic quality/SLO gates
4. workload denominator feed coverage
5. security/compliance hardening evidence
6. non-functional validation evidence

## 1) Apply latest schema

```bash
make migrate-db
```

Required migrations for this stage:
1. `0007_business_scorecard.sql`
2. `0008_operational_controls.sql`

## 2) Configure real on-call roster

Create `ops/oncall.production.json` from:
- `ops/oncall.production.example.json`

Audit and produce evidence:

```bash
make oncall-audit
```

Record event in DB:

```bash
.venv/bin/python -m scripts.audit_oncall_config \
  --config ops/oncall.production.json \
  --record-event \
  --performed-by <your-name> \
  --evidence-uri <ticket-or-doc-link>
```

## 3) Verify real incident endpoints + routing

Set real webhook endpoints (not placeholders):
1. `ALERTMANAGER_PAGER_WEBHOOK_URL`
2. `ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL`
3. `ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL`
4. `ALERTMANAGER_TICKET_WEBHOOK_URL`

Run live drill:

```bash
make verify-incident-endpoints
```

Record event with delivery evidence links:

```bash
.venv/bin/python -m scripts.verify_incident_endpoints_live \
  --mode live \
  --run-drill \
  --record-event \
  --performed-by <your-name> \
  --evidence-pager <pager-incident-link> \
  --evidence-model-oncall <model-channel-message-link> \
  --evidence-platform-oncall <platform-channel-message-link> \
  --evidence-ticket <ticket-link>
```

## 4) Ingest workload denominator feed

Prepare CSV with columns:
1. `metric_date`
2. `tenant_id`
3. `section`
4. `eligible_tickets_total`
5. `active_agents_total`
6. `source`

Reference:
- `ops/workload_daily.example.csv`

Load + gap-check:

```bash
WORKLOAD_CSV=/absolute/path/workload_daily.csv make workload-feed
```

`make workload-feed` now auto-creates any missing `tenants` rows from CSV `tenant_id` values before upsert.

## 5) Run business KPI and live rollout gates

```bash
make business-scorecard
PROMETHEUS_URL=<prometheus-url> make validate-live-rollout
```

These must be PASS for go-live:
1. business scorecard KPIs
2. stable canary/SLO validation
3. closed handoff label coverage

## 6) Run security/compliance audit

```bash
make security-audit
```

Record governance controls when completed:

```bash
.venv/bin/python -m scripts.record_operational_control \
  --control-type secret_rotation \
  --status pass \
  --scope global \
  --performed-by <your-name> \
  --evidence-uri <secret-rotation-ticket>

.venv/bin/python -m scripts.record_operational_control \
  --control-type access_review \
  --status pass \
  --scope global \
  --performed-by <your-name> \
  --evidence-uri <access-review-ticket>
```

## 7) Run non-functional validation

```bash
make nonfunctional-load
make nonfunctional-soak
make nonfunctional-failure
```

Record each run:

```bash
.venv/bin/python -m scripts.run_nonfunctional_validation \
  --mode load \
  --duration-seconds 120 \
  --concurrency 20 \
  --record-event \
  --performed-by <your-name>
```

## 8) Final deployment gate

```bash
PROMETHEUS_URL=<prometheus-url> make production-readiness-gate
```

Gate is PASS only when all are true:
1. live rollout validation passed
2. business KPI scorecard passed
3. workload denominator feed has no missing dates in window
4. closed handoffs have reviewer outcomes
5. required operational controls are fresh and PASS

## 9) One-command completion runner

You can execute the full production-completion sequence with one target:

```bash
make production-completion-live
```

Runner behavior:
1. Executes all steps and continues even if an intermediate gate fails.
2. Always writes a fresh final production readiness gate report.
3. Exits non-zero at the end if any step failed or the final gate is blocked.

Required env vars for this target:
1. `PERFORMED_BY`
2. `WORKLOAD_CSV`
3. `PROMETHEUS_URL`
4. `ALERTMANAGER_PAGER_WEBHOOK_URL`
5. `ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL`
6. `ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL`
7. `ALERTMANAGER_TICKET_WEBHOOK_URL`
8. `EVIDENCE_PAGER_URL`
9. `EVIDENCE_MODEL_ONCALL_URL`
10. `EVIDENCE_PLATFORM_ONCALL_URL`
11. `EVIDENCE_TICKET_URL`
12. `SECRET_ROTATION_EVIDENCE_URL`
13. `ACCESS_REVIEW_EVIDENCE_URL`

Optional env vars:
1. `ONCALL_CONFIG` (default: `ops/oncall.production.json`)
2. `ONCALL_AUDIT_EVIDENCE_URL` (default: same as `ONCALL_CONFIG`)
3. `CONTROL_SCOPE` (default: `global`)
4. `API_BASE_URL` (default: `http://127.0.0.1:8000`) for non-functional probes
5. `API_BEARER_TOKEN` (default empty) if API auth is enabled
6. `LOAD_DURATION_SECONDS` / `LOAD_CONCURRENCY`
7. `SOAK_DURATION_SECONDS` / `SOAK_CONCURRENCY`
8. `FAILURE_DURATION_SECONDS` / `FAILURE_CONCURRENCY`
