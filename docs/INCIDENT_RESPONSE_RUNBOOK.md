# Incident Response Runbook

## Scope

This runbook defines first-response and mitigation procedures for production alerts in:
- `observability/prometheus/rules/slo_alerts.yml`

Primary goals:
1. Restore service safely within SLO/error-budget limits.
2. Preserve data correctness and tenant isolation.
3. Capture clear incident evidence for postmortem and follow-up.

## Severity Policy

1. `critical`: page immediately, acknowledge in 5 minutes, mitigation in 15 minutes.
2. `warning`: acknowledge in 15 minutes, mitigation plan in 60 minutes.

## Global Triage Checklist

1. Confirm alert scope: affected service, tenant scope, start time, current blast radius.
2. Check deployment timeline: recent API/model/config changes.
3. Check dependency health: `/ready`, database, Redis, model-serving, workflow backend.
4. If user impact is active, prefer safe-mode behavior:
   - reduce canary percent
   - force handoff/escalation path
   - keep model fallback enabled
5. Record timeline events in incident notes every 15 minutes.

## DecisionApiHighErrorRate

Owner: `platform_oncall`  
Escalate to: `model_oncall` if failures are model-serving related.

Immediate actions:
1. Check API health/readiness:
```bash
curl -s http://<api-host>/ready
curl -s http://<api-host>/health
```
2. Inspect API error logs and top failing routes.
3. If rollout is active, execute rollback gate:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --rollback-on-fail
```
4. If model path is unstable, keep handoff path safe and verify guardrail fallback activity.

Exit criteria:
1. Error rate below threshold for 30 minutes.
2. No new user-visible failures in incident channel.

## DecisionApiHighLatencyP95

Owner: `platform_oncall`

Immediate actions:
1. Check latency contributors: DB latency, Redis, model-serving timeout/fallback.
2. Confirm rate limiting and queue pressure.
3. If model-serving latency dominates, temporarily reduce canary and/or route via fallback.

Exit criteria:
1. p95 latency under threshold for 30 minutes.

## ModelServingHighErrorRate

Owner: `model_oncall`  
Escalate to: `platform_oncall` if shared infra/network issue.

Immediate actions:
1. Check model-serving pod/process health and recent deploy.
2. Verify model artifacts and calibration files are readable and version-correct.
3. Keep fallback + handoff path active while restoring serving health.
4. Rollback canary stage if required:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --rollback-on-fail
```

Exit criteria:
1. Model-serving 5xx below threshold for 30 minutes.

## DecisionApiInputDriftDetected

Owner: `model_oncall`

Immediate actions:
1. Run daily model-ops pipeline and inspect drift report:
```bash
make model-ops-daily
```
2. Validate whether drift is expected (seasonality, product release, new tenant rollout).
3. If unexpected, reduce canary and increase manual review/handoff.

## DecisionApiConfidenceDriftDetected

Owner: `model_oncall`

Immediate actions:
1. Recompute evaluation and inspect calibration age/sample size:
```bash
make recalibrate-models
```
2. Compare confidence distribution against prior 7-14 day baseline.
3. If quality drops, rollback one canary stage and continue in shadow.

## DecisionApiOutcomeDriftDetected

Owner: `model_oncall`

Immediate actions:
1. Validate label integrity from closed handoffs and feedback.
2. Check escalation precision/recall and route accuracy from evaluation tables.
3. Trigger conservative rollback if outcome quality degrades.

## DecisionApiGuardrailFallbackSpike

Owner: `model_oncall`  
Severity: `critical`

Immediate actions:
1. Assume model instability until proven otherwise.
2. Rollback canary stage immediately:
```bash
.venv/bin/python -m scripts.promote_canary --lookback-days 14 --apply --rollback-on-fail
```
3. Keep fallback + reviewer handoff path active and verify queue capacity.
4. Open incident bridge and notify platform + product stakeholders.

Exit criteria:
1. Guardrail fallback rate returns to baseline for 30 minutes.
2. Root-cause hypothesis documented with next corrective action.

## Recovery Validation

Before resolving any incident:
1. Run live validation check for the affected window:
```bash
.venv/bin/python -m scripts.validate_live_rollout \
  --stable-days-min 14 \
  --stable-days-max 28 \
  --min-daily-samples 50 \
  --min-ground-truth 50 \
  --min-calibration-samples 200 \
  --max-calibration-age-days 7 \
  --prometheus-url <prometheus-url>
```
2. Confirm SLO dashboards are stable and no active critical alerts remain.
3. Capture evidence artifacts in `artifacts/reports/`.

## Postmortem Requirements

For `critical` incidents:
1. Postmortem within 2 business days.
2. Include timeline, root cause, blast radius, detection gap, prevention actions.
3. Create tracked remediation tickets and assign DRI/ETA.

---

## DecisionApiHighLatencyP99

Owner: `platform_oncall`  
Severity: `critical`

Immediate actions:
1. Identify which pipeline stage dominates p99:
```
Check Grafana → "Pipeline Stage Latency (p95)" panel.
Usual suspect: generation (Ollama backend) or retrieval (pgvector).
```
2. If generation: Check Ollama pod health, GPU utilization, queue depth.
3. If retrieval: Check PostgreSQL connection pool, active queries, VACUUM status.
4. Temporarily switch to template backend if Ollama is the bottleneck:
```bash
export GENERATION_BACKEND=template
# Rolling restart pods
kubectl rollout restart deployment/decision-api
```
5. If issue persists, scale up replicas and reduce backpressure limit.

Exit criteria:
1. p99 latency below 2s for 30 minutes.
2. No request timeouts in error logs.

## DecisionApiLowThroughput

Owner: `platform_oncall`

Immediate actions:
1. Verify upstream load balancer and ingress health.
2. Check if DNS resolution is working: `nslookup api.decision-platform.internal`.
3. Check if rate limiting is over-blocking: inspect `assist_rate_limit_exceeded_total`.
4. Verify no network policy changes blocking ingress.
5. Check pod readiness: `kubectl get pods -l app=decision-api`.

Exit criteria:
1. Throughput returns to baseline for 15 minutes.
2. Upstream callers confirmed healthy.

## DecisionApiHighHallucinationRate

Owner: `model_oncall`  
Severity: `critical`

Immediate actions:
1. Check `decision_api:hallucination_rate_mean_1h` in Grafana.
2. Inspect recent generation outputs in inference logs for ungrounded claims.
3. Check retrieval quality: `decision_api:evidence_score_mean_1h`. If low, the problem is retrieval, not generation.
4. If retrieval healthy but hallucination high:
   - Reduce `generation_temperature` to 0.1
   - Switch to template backend as stopgap
5. If retrieval degraded:
   - Check pgvector index health: `SELECT * FROM pg_stat_user_indexes WHERE relname = 'doc_chunks';`
   - Reindex if needed: `POST /v1/assist/reindex`

Exit criteria:
1. Hallucination ratio below 0.35 for 30 minutes.
2. Generation quality logged as stable in incident notes.

## DecisionApiLowFaithfulness

Owner: `model_oncall`

Immediate actions:
1. Compare `decision_api:faithfulness_mean_1h` against 24h trailing average.
2. If sudden drop: check for evidence corpus changes (new/deleted chunks).
3. If gradual decline: trigger model re-evaluation to check routing accuracy (wrong route = wrong evidence = low faithfulness).
4. Increase `max_evidence_chunks` temporarily to improve grounding coverage.

Exit criteria:
1. Faithfulness above 0.5 for 30 minutes.

## DecisionApiHighAbstainRate

Owner: `model_oncall`

Immediate actions:
1. Check `decision_api:abstain_rate_1h` vs `_24h` for drift.
2. If new traffic pattern: verify input distribution — may be new intents not covered by taxonomy.
3. Check OOD score distribution: high OOD typically drives abstain.
4. If product-driven: expand routing taxonomy and retrain routing model.
5. Short-term: lower `base_confidence_threshold` from 0.65 to 0.55 to reduce abstains (accept lower precision).

Exit criteria:
1. Abstain rate below 0.35 for 1 hour.

## DecisionApiHighInjectionRate

Owner: `platform_oncall`  
Severity: `critical`

Immediate actions:
1. Check `assist_injection_detections_total` for source breakdown (user_input vs evidence_chunk).
2. If user_input dominant: possible coordinated attack.
   - Enable enhanced rate limiting per-user.
   - Review triggered rules in logs for pattern analysis.
   - Block repeat offenders at WAF/IP level.
3. If evidence_chunk dominant: possible evidence corpus poisoning.
   - Audit recent chunk ingestion: who uploaded, when, what content.
   - Quarantine suspicious chunks (set `is_deleted = true`).
4. Notify security team immediately.

Exit criteria:
1. Injection block rate below 5% for 30 minutes.
2. Security team acknowledged and investigating.

## CircuitBreakerOpen

Owner: `platform_oncall`  
Severity: `critical`

Immediate actions:
1. Identify which downstream dependency tripped (check `target` label).
2. Check dependency health:
   - Model-serving: `curl http://model-serving:9000/health`
   - PostgreSQL: connection pool metrics
   - Redis: `redis-cli ping`
3. If dependency is truly down: circuit breaker is working correctly — focus on restoring the dependency.
4. If dependency recovered but CB still open: wait for `recovery_timeout_seconds` (30s default) and monitor half-open probes.
5. If stuck: restart affected API pods to reset circuit breaker state.

Exit criteria:
1. Circuit breaker returns to CLOSED state.
2. Dependency health verified stable for 5 minutes.

---

## Post-Incident Review Template

```markdown
## Incident Report: [INCIDENT-YYYY-NNN]

**Date:** YYYY-MM-DD
**Severity:** SEV-1 | SEV-2 | SEV-3
**Duration:** HH:MM (start to resolution)
**Oncall:** @engineer-primary, @engineer-secondary
**Alert:** [alert name that fired]

### Summary
One-paragraph description of what happened and customer impact.

### Timeline
| Time (UTC) | Event |
|------------|-------|
| HH:MM | Alert fired: [alert name] |
| HH:MM | Acknowledged by @engineer |
| HH:MM | Initial triage: [findings] |
| HH:MM | Root cause identified: [description] |
| HH:MM | Mitigation applied: [action taken] |
| HH:MM | Monitoring confirmed stable |
| HH:MM | Incident resolved |

### Impact
- Requests affected: N (from Prometheus query)
- Error rate peak: X%
- Latency peak (p95): Xs
- Decisions degraded: N
- Customer-facing: Yes/No
- Data integrity: Confirmed / Investigating

### Root Cause
[Detailed 5-whys analysis]

1. Why did the alert fire? → [immediate cause]
2. Why did that happen? → [contributing factor]
3. Why wasn't it caught earlier? → [detection gap]
4. Why did it reach production? → [process gap]
5. Why wasn't there a safeguard? → [systemic issue]

### Detection
- How was it detected? Alert / Customer report / Manual check
- Time to detect (TTD): X minutes
- Time to acknowledge (TTA): X minutes
- Time to mitigate (TTM): X minutes

### Mitigation
What was done to stop the bleeding:
- [ ] Rollback deployed: `helm rollback decision-api <revision>`
- [ ] Feature flag toggled
- [ ] Traffic shifted
- [ ] Manual intervention

### Prevention
What will prevent recurrence:

| # | Action | Type | Owner | Due | Ticket |
|---|--------|------|-------|-----|--------|
| 1 | Add integration test for [scenario] | Test | @eng | YYYY-MM-DD | JIRA-XXX |
| 2 | Add alert for [new condition] | Monitoring | @eng | YYYY-MM-DD | JIRA-XXX |
| 3 | Update runbook for [gap] | Process | @eng | YYYY-MM-DD | JIRA-XXX |

### Lessons Learned
- What went well:
- What could be improved:
- Lucky breaks (things that could have been worse):
```
