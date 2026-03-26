# Decision Platform — Production Architecture Reference

> Generated 2026-02-18. Canonical source of truth for SLOs, algorithms, topology, and operational contracts.

---

## 1. SLO Baselines — Hard Numbers

### HTTP latency targets (measured at `/v1/assist/decide`)

| Percentile | Target | Alert threshold | Prometheus rule |
|------------|--------|-----------------|-----------------|
| p50 | ≤ 120 ms | — | `decision_api:latency_p50_5m` |
| p95 | ≤ 500 ms | > 1 s for 15 min | `decision_api:latency_p95_5m` |
| p99 | ≤ 1.2 s | > 2 s for 10 min | `decision_api:latency_p99_5m` |

### Pipeline stage latency budget (p95)

| Stage | p95 target | Prometheus label |
|-------|-----------|------------------|
| PII redaction | ≤ 2 ms | `stage="pii_redaction"` |
| Injection scan | ≤ 3 ms | `stage="injection_scan"` |
| Evidence retrieval | ≤ 80 ms | `stage="retrieval"` |
| Routing + confidence | ≤ 15 ms | `stage="routing"` |
| Generation (template) | ≤ 5 ms | `stage="generation"` |
| Generation (Ollama) | ≤ 2 000 ms | `stage="generation"` |
| Evidence injection filter | ≤ 10 ms | `stage="evidence_injection_filter"` |

### Throughput

| Metric | Target | Prometheus |
|--------|--------|------------|
| Sustained RPS (template backend) | ≥ 200 req/s per replica | `decision_api:throughput_rps_5m` |
| Sustained RPS (Ollama backend) | ≥ 8 req/s per replica | `decision_api:throughput_rps_5m` |
| In-flight concurrency limit | 50 (backpressure) | `assist_inflight_requests` |

### Cost per request

| Backend | Cost/request | Components |
|---------|-------------|------------|
| Template (no LLM) | ~$0.00005 | Retrieval + routing + infra |
| Ollama self-hosted | ~$0.00015 | + ~$0.002/1k output tokens (GPU amortized) |
| API (OpenAI-compatible) | ~$0.003 | + $0.03/1k input + $0.06/1k output tokens |

Tracked via `assist_request_cost_dollars` histogram, aggregated as `decision_api:cost_per_request_mean_1h`.

### Availability

| SLO | Target | Alert | For |
|-----|--------|-------|-----|
| Error rate | < 1% (5xx) | `DecisionApiHighErrorRate` | 10 min |
| Availability | ≥ 99.5% | derived: 1 − error_rate | — |

---

## 2. Evaluation Metrics

All evaluation metrics are computed by `scripts/build_daily_evaluation.py` and pushed to Prometheus gauges, plus per-request histograms for RAG quality.

### Routing & calibration

| Metric | Gauge / Histogram | Quality gate | Current baseline |
|--------|-------------------|--------------|------------------|
| Routing accuracy | `assist_routing_accuracy` | ≥ 0.75 | 0.82 (Bitext eval set) |
| Escalation recall | — (daily eval log) | ≥ 0.70 | 0.78 |
| ECE (Expected Calibration Error) | `assist_calibration_ece` | ≤ 0.15 | 0.09 (Platt-calibrated) |
| Abstain rate | `assist_abstain_rate` | ≤ 0.35 | 0.18 |

### RAG quality (per-request, observed in pipeline)

| Metric | Histogram | Acceptable range | Alert |
|--------|-----------|-----------------|-------|
| Faithfulness | `assist_rag_faithfulness` | ≥ 0.60 | `< 0.5 for 15m` |
| Hallucination ratio | `assist_rag_hallucination_ratio` | ≤ 0.35 | `> 0.35 for 15m` |
| Citation coverage | `assist_rag_citation_coverage` | ≥ 0.50 | — |
| Evidence score (mean) | `assist_retrieval_evidence_score` | ≥ 0.40 | — |

### Retrieval quality (batch evaluation)

| Metric | Function | Notes |
|--------|----------|-------|
| Recall@K | `compute_retrieval_quality().recall_at_k` | K = `max_evidence_chunks` (default 5) |
| Precision@K | `compute_retrieval_quality().precision_at_k` | |
| MRR | `compute_retrieval_quality().reciprocal_rank` | |

### Confidence formula

$$\text{final} = 0.45 \cdot \text{route\_conf} + 0.25 \cdot \text{evidence\_score} + 0.20 \cdot (1 - \text{escalation\_prob}) - 0.07 \cdot \text{ood\_score} - 0.03 \cdot \text{contradiction\_score}$$

Clamped to $[0.0, 1.0]$, rounded to 4 decimal places.

### Embedding providers (`app/utils/embedding.py`)

| Backend | Dim | Use case | Config |
|---------|-----|----------|--------|
| `local` (LocalHashEmbeddingProvider) | 64 | Dev / CI / air-gapped demos | `EMBEDDING_BACKEND=local` |
| `sentence-transformer` (SentenceTransformerEmbeddingProvider) | 384 | **Production default** | `EMBEDDING_BACKEND=sentence-transformer` |
| `api` (ApiEmbeddingProvider) | 1536 | High-quality / cloud | `EMBEDDING_BACKEND=api` + `EMBEDDING_API_KEY` |

**Production rule:** `EMBEDDING_BACKEND=local` is **blocked** when `APP_ENV=production`
(enforced by `Settings._validate_runtime_guards()`).

Migration from hash to sentence-transformer:
```bash
EMBEDDING_BACKEND=sentence-transformer make reindex-embeddings
```
This drops the old HNSW index, resizes the vector column, re-embeds every
chunk, and recreates the index. See `scripts/reindex_embeddings.py`.

### Production configuration hardening

When `APP_ENV=production`, `Settings._validate_runtime_guards()` enforces:
- `EMBEDDING_BACKEND` ≠ `local`
- `AUTH_ENABLED` = true
- `USE_POSTGRES` = true
- `RATE_LIMIT_ENABLED` = true
- `PII_REDACTION_ENABLED` = true
- `METRICS_ENABLED` = true
- `POSTGRES_DSN` must not contain weak passwords (`postgres`, `password`, etc.)
- `VAULT_ADDR` must be set when `SECRETS_BACKEND=vault`

The bootstrap script (`scripts/bootstrap_production_data.py`) is **blocked**
from running against `APP_ENV=production` unless `--force` is passed.

---

## 3. Tenant Isolation

### Strategy: Row-Level Security (RLS) + Application-Layer Guard

We use **RLS** (not schema-per-tenant, not DB-per-tenant) for these reasons:

| Approach | Pros | Cons | Our choice |
|----------|------|------|------------|
| RLS | Single schema, DB-enforced, no connection proliferation | Requires `SET app.current_tenant` on every connection | **Yes** |
| Schema-per-tenant | Strong isolation | Connection-pool explosion, migration complexity | No |
| DB-per-tenant | Strongest isolation | Infeasible at scale (>1000 tenants) | No |

### RLS implementation (`migrations/0010_tenant_rls_data_retention.sql`)

Tables with RLS enabled + forced:
- `doc_chunks`, `inference_requests`, `inference_results`
- `handoffs`, `feedback_events`, `pii_audit_events`

Policy structure:
```sql
CREATE POLICY tenant_isolation_<table> ON <table>
  FOR ALL
  USING (tenant_id = current_setting('app.current_tenant', true))
  WITH CHECK (tenant_id = current_setting('app.current_tenant', true));
```

Admin bypass:
```sql
CREATE POLICY <table>_admin_bypass ON <table>
  FOR ALL
  TO platform_admin
  USING (true);
```

### Application-layer guard

Every `PostgresRetrievalStore` method — including `seed_chunks()`, `retrieve()`,
`_sparse_search()`, and `_dense_search()` — sets the tenant context before
executing, via the `_set_tenant_context()` helper:
```python
cur.execute("SET app.current_tenant = %s", (tenant_id,))
```
`seed_chunks()` groups inserts by `tenant_id` so the RLS `WITH CHECK` is
satisfied per batch.  Plus explicit `WHERE tenant_id = %s` as defense-in-depth
on all read paths.

### Test coverage

- `tests/test_tenant_isolation.py`: 20+ tests proving:
  - RLS migration structure (ENABLE + FORCE + USING + WITH CHECK on all 6 tables)
  - Application-layer filter prevents cross-tenant reads
  - Idempotency cache scoped by (tenant_id, request_id)
  - RBAC tenant_ids claim enforcement
  - GDPR erasure scoped to requesting tenant
- `tests/test_auth_rbac_tenant_enforcement.py`: JWT tenant access checks

---

## 4. Security & Compliance

### Encryption

| Layer | Algorithm | Key management |
|-------|-----------|---------------|
| In transit | TLS 1.3 (nginx ingress → pods, mTLS between services) | cert-manager + Let's Encrypt |
| At rest (DB) | AES-256 (Cloud SQL / EBS encryption) | Cloud KMS |
| Field-level | AES-256-GCM (app/security/secrets.py) | PBKDF2-SHA256, 100k iterations |
| Fallback (dev) | HMAC-SHA256 obfuscation | Env var master key |

### Secrets management (`app/security/secrets.py`)

| Backend | When | Config |
|---------|------|--------|
| `EnvVarSecretsProvider` | local/test | `secrets_backend=env` |
| `VaultSecretsProvider` | staging/production | `secrets_backend=vault`, `vault_addr`, `VAULT_TOKEN` |

Vault integration: KV v2, 5-minute local cache TTL, auto-retry on 5xx.

### Key rotation

```python
KeyRotationPolicy(
    key_name='JWT_SECRET',
    max_age_days=90,          # Alert: OVERDUE if exceeded
    auto_rotate=False,        # Manual approval required
    last_rotated_epoch=...,   # Tracked in data_lifecycle_events
)
```

Cloud Secret Manager rotation: 90-day schedule (configured in `infra/terraform/main.tf`).

### Audit logs

| Table | Records | Retention |
|-------|---------|-----------|
| `inference_requests` | Every decision request | 365 days (anonymize) |
| `inference_results` | Every decision response | 365 days (anonymize) |
| `pii_audit_events` | PII detection/redaction events | 90 days (hard delete) |
| `data_lifecycle_events` | Retention purge, erasure, key rotation | Indefinite |
| `model_shadow_predictions` | Challenger model outputs | 180 days (hard delete) |

### Data retention & GDPR

6 retention policies in `data_retention_policies` table:

| Target table | Retention | Action |
|-------------|-----------|--------|
| inference_requests | 365 days | anonymize |
| inference_results | 365 days | anonymize |
| handoffs | 180 days | soft_delete |
| feedback_events | 365 days | soft_delete |
| pii_audit_events | 90 days | hard_delete |
| model_shadow_predictions | 180 days | hard_delete |

GDPR right-to-erasure: `erasure_requests` table tracks `pending → in_progress → completed | failed`.

---

## 5. Prompt Injection Defense + Output Validation

### Input defense — 3-layer scanner (`app/security/prompt_injection.py`)

| Layer | Method | Threshold |
|-------|--------|-----------|
| 1. Regex blocklist | 18 patterns: instruction override, role switching, prompt extraction, delimiter injection, jailbreak | Any match → weight 0.25/rule |
| 2. Delimiter analysis | Count `system:/user:/assistant:` markers | ≥ 2 markers → `excessive_role_markers` |
| 3. Heuristic scoring | Instruction density, suspicious token cluster (13 tokens), char entropy | density > 0.5, ≥ 3 suspicious tokens |

**Risk score formula:**
$$\text{score} = \min(1.0, \underbrace{n_{\text{rules}} \times 0.25}_{\text{rule weight}} + \underbrace{\min(0.3, d \times 0.4)}_{\text{density}} + \underbrace{\min(0.2, m \times 0.1)}_{\text{markers}} + \underbrace{\min(0.2, s \times 0.05)}_{\text{suspicious tokens}})$$

**Enforcement:**

| Source | Threshold | Action |
|--------|-----------|--------|
| User input | risk_score ≥ 0.7 | Force escalation to human agent |
| Evidence chunks | risk_score ≥ 0.5 | Filter chunk from evidence pack |

Tracked via `assist_injection_detections_total{source, action}`.

### Output validation (`app/security/output_validation.py`)

Applied after generation, before response:

| Check | Threshold | Action on violation |
|-------|-----------|---------------------|
| Length bounds | 10–2000 chars | Truncate or flag |
| Citation presence | At least one `[chunk_*]` | Flag `missing_citations` |
| PII re-check | 6 patterns (email, phone, SSN, CC, IP, DOB) | Mask with `[REDACTED_*]` |
| Forbidden content | System prompt leak, ChatML markers, URL injection, markdown injection | Replace with `[BLOCKED]` |

---

## 6. Anti-Copy Check Specification

**Location:** `app/services/generation.py` → `_passes_generation_checks()`

### Algorithm

```
let candidate = generated response text
let prior_messages = conversation history (up to 8 turns)
let evidence_chunks = retrieved evidence pack

IF len(candidate) < 24 chars → REJECT (too short to be useful)

FOR each prior_message in prior_messages:
    IF len(candidate.tokens) >= 8:
        // Token-set Jaccard similarity
        jaccard = |tokens(candidate) ∩ tokens(prior)| / |tokens(candidate) ∪ tokens(prior)|
        IF jaccard ≥ 0.82 → REJECT (too similar to prior message)

        // 4-gram overlap
        ngram_overlap = |ngrams(candidate,4) ∩ ngrams(prior,4)| / max(|ngrams(candidate,4)|, 1)
        IF ngram_overlap ≥ 0.55 → REJECT (structural plagiarism from prior)

FOR each evidence_chunk in evidence_chunks:
    IF len(candidate.tokens) >= 10:
        // Evidence copy detection
        overlap_ratio = |tokens(candidate) ∩ tokens(chunk)| / |tokens(candidate)|
        IF overlap_ratio ≥ 0.90 → REJECT (verbatim evidence copy)
```

### Retry & fallback behavior

```
attempt_1 = generate(prompt)
IF !passes_checks(attempt_1):
    attempt_2 = generate(prompt + "Regenerate with clearly different wording")
    IF !passes_checks(attempt_2):
        IF fail_open=True:
            return template_fallback_response()  ← deterministic, safe
        ELSE:
            return {ok: false, reason: 'generation_backend_unavailable'}
```

### Thresholds summary

| Check | Threshold | Min tokens |
|-------|-----------|-----------|
| Token-set Jaccard vs prior | ≥ 0.82 | 8 |
| 4-gram overlap vs prior | ≥ 0.55 | 8 |
| Token overlap vs evidence | ≥ 0.90 | 10 |
| Min candidate length | 24 chars | — |

---

## 7. CI/CD Pipeline + Promotion Gates

### Pipeline diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CI/CD Pipeline                               │
│                                                                     │
│  ┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐        │
│  │  1. Lint  │──▶│ 2. Secur │──▶│ 3. Build │──▶│4. Deploy │        │
│  │  & Test   │   │  Scan    │   │  & Push  │   │ Staging  │        │
│  └──────────┘   └──────────┘   └──────────┘   └─────┬────┘        │
│       │              │              │                │              │
│  ┌────┴────┐   ┌────┴────┐   ┌────┴────┐   ┌──────┴──────┐       │
│  │ pytest  │   │pip-audit│   │ Buildx  │   │ Smoke tests │       │
│  │ 200+    │   │ Trivy   │   │ GHCR    │   │ Quality gate│       │
│  │ tests   │   │TruffleH │   │ multi-  │   │  ≥ 200 samp │       │
│  │ ruff    │   │         │   │ arch    │   │  acc ≥ 0.75 │       │
│  └─────────┘   └─────────┘   └─────────┘   └──────┬──────┘       │
│                                                     │              │
│                                              ┌──────▼──────┐       │
│                                              │  5. Deploy  │       │
│                                              │ Production  │       │
│                                              │  (canary)   │       │
│                                              └──────┬──────┘       │
│                                                     │              │
│                                              ┌──────▼──────┐       │
│                                              │ 10% canary  │       │
│                                              │ 5 min soak  │       │
│                                              │ Error < 1%? │       │
│                                              │ p95 < 1s?   │       │
│                                              │    ┌───┐    │       │
│                                              │ Yes│   │No  │       │
│                                              │    ▼   ▼    │       │
│                                              │ 100%  ROLL  │       │
│                                              │       BACK  │       │
│                                              └─────────────┘       │
└─────────────────────────────────────────────────────────────────────┘
```

### Stage details

| Stage | Trigger | Gate criteria | Blocking |
|-------|---------|---------------|----------|
| 1. Lint & Test | Push to `main` or PR | ruff clean, 200+ tests pass, Postgres+Redis service containers | Yes |
| 2. Security Scan | After stage 1 | pip-audit no critical CVEs, Trivy image scan clean, TruffleHog no secrets | Yes |
| 3. Build & Push | After stage 2 | Docker Buildx multi-platform, push to GHCR with SHA + semver tags | Yes |
| 4. Deploy Staging | After stage 3 | Helm upgrade, smoke test (`/health`, `/ready`, sample `/v1/assist/decide`) | Yes |
| 5. Deploy Production | After stage 4 + manual approval | Canary rollout: 10% → 5 min soak → error rate, latency, confidence drift checks | Yes |

### Rollback triggers (automatic)

| Condition | Window | Action |
|-----------|--------|--------|
| Error rate > 1% (5xx) | 5 min rolling | Helm rollback to previous revision |
| p95 latency > 2× baseline | 5 min rolling | Helm rollback |
| Confidence drift > 0.15 | 10 min rolling | Halt canary, alert oncall |
| Guardrail fallback spike > 5%/s | 10 min | Helm rollback |

### IaC

- **Kubernetes**: Helm chart at `infra/helm/decision-platform/`
- **Cloud infra**: Terraform at `infra/terraform/main.tf` (GKE + Cloud SQL + Memorystore + VPC + IAM)
- **CI/CD**: GitHub Actions at `.github/workflows/ci-cd.yml`

---

## 8. Incident Readiness

### Alert → Runbook mapping

Every alert rule in `observability/prometheus/rules/slo_alerts.yml` includes a `runbook:` annotation pointing to `docs/INCIDENT_RESPONSE_RUNBOOK.md#<anchor>`.

| Alert | Severity | Owner | Runbook section |
|-------|----------|-------|-----------------|
| `DecisionApiHighErrorRate` | critical | `platform_oncall` | `#decisionapihigherrorrate` |
| `DecisionApiHighLatencyP95` | warning | `platform_oncall` | `#decisionapihighlatencyp95` |
| `DecisionApiHighLatencyP99` | critical | `platform_oncall` | `#decisionapihighlatencyp99` |
| `DecisionApiLowThroughput` | warning | `platform_oncall` | `#decisionapilowthroughput` |
| `ModelServingHighErrorRate` | warning | `model_oncall` | `#modelservinghigherrorrate` |
| `DecisionApiInputDriftDetected` | warning | `model_oncall` | `#decisionapiinputdriftdetected` |
| `DecisionApiConfidenceDriftDetected` | warning | `model_oncall` | `#decisionapiconfidencedriftdetected` |
| `DecisionApiOutcomeDriftDetected` | warning | `model_oncall` | `#decisionapioutcomedriftdetected` |
| `DecisionApiGuardrailFallbackSpike` | critical | `model_oncall` | `#decisionapiguardrailfallbackspike` |
| `DecisionApiHighHallucinationRate` | critical | `model_oncall` | `#decisionapihighhallucinationrate` |
| `DecisionApiLowFaithfulness` | warning | `model_oncall` | `#decisionapilowfaithfulness` |
| `DecisionApiHighAbstainRate` | warning | `model_oncall` | `#decisionapihighabstainrate` |
| `DecisionApiHighInjectionRate` | critical | `platform_oncall` | `#decisionapihighinjectionrate` |
| `CircuitBreakerOpen` | critical | `platform_oncall` | `#circuitbreakeropen` |

### Oncall policy (`ops/oncall.production.json`)

- Primary rotation: weekly, 2 engineers per rotation
- Escalation matrix: page → acknowledge (5 min) → engage (15 min) → escalate to manager (30 min)
- Oncall validation: `scripts/audit_oncall_config.py` (tests: valid JSON, no empty rotations, coverage gaps)

### Alertmanager routing

```yaml
# observability/alertmanager/alertmanager.yml
route:
  group_by: ['alertname', 'owner']
  group_wait: 30s
  group_interval: 5m
  repeat_interval: 4h
  receiver: default-webhook
  routes:
    - match: {severity: critical}
      receiver: pagerduty-critical
    - match: {owner: model_oncall}
      receiver: model-team-slack
```

### Postmortem template

See `docs/INCIDENT_RESPONSE_RUNBOOK.md`, Section: "Post-Incident Review Template":

```markdown
## Incident Report: [INCIDENT-YYYY-NNN]

**Date:** YYYY-MM-DD
**Severity:** SEV-1 | SEV-2 | SEV-3
**Duration:** HH:MM
**Oncall:** @engineer

### Timeline
| Time (UTC) | Event |
|------------|-------|
| HH:MM | Alert fired: ... |
| HH:MM | Acknowledged by ... |
| HH:MM | Root cause identified: ... |
| HH:MM | Mitigation applied: ... |
| HH:MM | Resolved |

### Impact
- Requests affected: N
- Error rate peak: X%
- Customer-facing: Yes/No

### Root Cause
[5-whys analysis]

### Action Items
| # | Action | Owner | Due |
|---|--------|-------|-----|
| 1 | ... | @eng | YYYY-MM-DD |
```

---

## 9. Model Registry + Lineage

### Implementation: `app/services/model_registry.py`

### Stage lifecycle

```
DEVELOPMENT → SHADOW → CANARY → PRODUCTION → ARCHIVED
                                      ↓
                                  ROLLBACK → PRODUCTION (re-promote)
```

### Artifact metadata

| Field | Type | Required | Purpose |
|-------|------|----------|---------|
| `artifact_id` | UUID | auto | Unique identifier |
| `name` | str | yes | Human-readable model name |
| `version` | str | yes | Semantic version (e.g., `v2.1.0`) |
| `artifact_type` | enum | yes | `ROUTING_MODEL`, `ESCALATION_MODEL`, `CALIBRATION`, `EMBEDDING_MODEL`, `GENERATION_MODEL` |
| `stage` | enum | auto | Current lifecycle stage |
| `artifact_path` | str | no | Path to serialized model artifact |
| `checksum_sha256` | str | no | Integrity hash of artifact file |
| `training_dataset` | str | no | Dataset identifier (e.g., `bitext-customer-support-v13`) |
| `training_dataset_version` | str | no | Dataset version hash |
| `training_record_count` | int | no | Number of training examples |
| `training_started_at` | datetime | no | Training job start time |
| `training_completed_at` | datetime | no | Training job end time |
| `training_config` | dict | no | Hyperparameters, optimizer, scheduler |
| `evaluation_metrics` | dict | no | `{accuracy, recall, precision, f1, ece, ...}` |
| `parent_artifact_id` | UUID | no | Links to predecessor for lineage chain |
| `created_by` | str | no | Engineer or CI job identifier |
| `promotion_reason` | str | no | Why this model was promoted |

### Lineage tracking

Every stage transition creates a `LineageEvent`:
```python
LineageEvent(
    artifact_id=...,
    event_type='stage_transition',
    from_stage=ModelStage.SHADOW,
    to_stage=ModelStage.CANARY,
    reason='daily_eval_gate_passed',
    timestamp=datetime.utcnow(),
)
```

`get_full_lineage_chain(artifact_id)` walks `parent_artifact_id` links to produce:
```
v3.0 ← v2.1 ← v2.0 ← v1.0 (initial)
```

### Compliance report

`registry.compliance_report()` returns:
```json
{
  "total_artifacts": 12,
  "active_production_models": 3,
  "stages": {"DEVELOPMENT": 4, "SHADOW": 2, "PRODUCTION": 3, "ARCHIVED": 3},
  "artifacts_without_training_data": 1,
  "artifacts_without_checksum": 2
}
```

### Reproducibility

Every model artifact stores:
1. **Training data reference**: dataset name + version + record count
2. **Training config**: full hyperparameter dict (learning rate, epochs, batch size, optimizer)
3. **Evaluation metrics**: accuracy, recall, ECE measured on held-out test set
4. **Artifact checksum**: SHA-256 of the serialized model file
5. **Parent lineage**: chain of previous model versions

---

## 10. Deployment Topology + Failure Domains

### Service topology

```
                         ┌─────────────────────────┐
                         │     Cloud Load Balancer  │
                         │   (GCP GCLB / AWS ALB)   │
                         └───────────┬─────────────┘
                                     │ TLS termination
                         ┌───────────▼─────────────┐
                         │    nginx-ingress (K8s)   │
                         │    rate limit: 1k rps    │
                         └───────────┬─────────────┘
                                     │
              ┌──────────────────────┼──────────────────────┐
              │                      │                      │
    ┌─────────▼─────────┐ ┌─────────▼─────────┐ ┌─────────▼─────────┐
    │  decision-api     │ │  decision-api     │ │  decision-api     │
    │  (replica 1)      │ │  (replica 2)      │ │  (replica N)      │
    │  Pod:             │ │  Pod:             │ │  Pod:             │
    │   ├─ app (8000)   │ │   ├─ app (8000)   │ │   ├─ app (8000)   │
    │   └─ opa (8181)   │ │   └─ opa (8181)   │ │   └─ opa (8181)   │
    │  HPA: 2-20        │ │                   │ │                   │
    │  PDB: minAvail=1  │ │                   │ │                   │
    └─────────┬─────────┘ └─────────┬─────────┘ └─────────┬─────────┘
              │                     │                      │
    ┌─────────▼─────────────────────▼──────────────────────▼─────────┐
    │                    Internal Service Mesh                        │
    │                                                                │
    │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
    │  │ PostgreSQL 16│  │  Redis 7     │  │  model-serving     │   │
    │  │ + pgvector   │  │  (HA pair)   │  │  (FastAPI + Ollama)│   │
    │  │ Regional HA  │  │  TLS + AUTH  │  │  GPU node pool     │   │
    │  │ PITR enabled │  │  Failover    │  │  HPA: 1-5          │   │
    │  └──────────────┘  └──────────────┘  └────────────────────┘   │
    │                                                                │
    │  ┌──────────────┐  ┌──────────────┐  ┌────────────────────┐   │
    │  │ Prometheus   │  │ Alertmanager │  │  Grafana            │   │
    │  │ scrape: 15s  │  │ PagerDuty +  │  │  dashboards (12    │   │
    │  │ retention:15d│  │ Slack routes │  │  panels)            │   │
    │  └──────────────┘  └──────────────┘  └────────────────────┘   │
    │                                                                │
    │  ┌──────────────┐  ┌──────────────┐                           │
    │  │ Jaeger       │  │ Temporal     │                           │
    │  │ OTLP traces  │  │ Workflow     │                           │
    │  │ (optional)   │  │ (handoffs)   │                           │
    │  └──────────────┘  └──────────────┘                           │
    └────────────────────────────────────────────────────────────────┘
```

### Failure domains

| Domain | Components | Failure mode | Mitigation |
|--------|-----------|--------------|------------|
| **Zone A** | API replicas 1-N (spread via `topologySpreadConstraints`) | Zone outage | Replicas in zones B/C continue; PDB ensures ≥1 available |
| **Database** | Cloud SQL (regional HA, auto-failover) | Primary failure | Automatic failover to standby (< 30s), PITR for data recovery |
| **Cache** | Memorystore Redis (STANDARD_HA) | Node failure | Automatic failover to replica; rate limiter: `fail_open=True` |
| **Model serving** | Ollama on GPU nodes | GPU node failure | Template fallback (`generation_fail_open=True`), circuit breaker (5 failures → open for 30s) |
| **OPA sidecar** | Per-pod sidecar | Container crash | K8s restarts; if OPA unreachable, policy evaluation returns default-deny + escalate |
| **Prometheus** | Single instance (profile: observability) | Scrape failure | Alerts stop firing; Grafana shows gaps; no data loss (stateless scrape) |
| **Temporal** | External workflow service | Connection failure | Handoff created but workflow not started; logged; manual retry available |
| **External API** | Embedding API / OpenAI | Timeout or 5xx | Circuit breaker + fallback to local hash embeddings |
| **Network** | VPC / NAT / Cloud DNS | Partition | Private cluster with NAT; Cloud SQL private IP; no public endpoints for data plane |

### Kubernetes resources

| Resource | Value | Notes |
|----------|-------|-------|
| HPA min replicas | 2 | Ensures HA during low traffic |
| HPA max replicas | 20 | Cost guard |
| HPA target CPU | 70% | Scale-up trigger |
| PDB minAvailable | 1 | Prevents full drain during rolling update |
| Pod topology spread | `maxSkew: 1, topologyKey: topology.kubernetes.io/zone` | Cross-zone distribution |
| Network policy | Ingress only from `nginx-ingress` + `monitoring` namespaces | Zero-trust pod network |
| Security context | `runAsNonRoot: true, readOnlyRootFilesystem: true, drop: ALL` | Hardened containers |
| Resource requests | CPU: 500m, Memory: 512Mi | Per API pod |
| Resource limits | CPU: 2000m, Memory: 2Gi | Per API pod |

### DNS & routing

```
api.decision-platform.internal → nginx-ingress → decision-api Service (ClusterIP)
model.decision-platform.internal → model-serving Service (ClusterIP)
grafana.decision-platform.internal → grafana Service (ClusterIP)
```

All internal. External access via Cloud Load Balancer → nginx-ingress only.
