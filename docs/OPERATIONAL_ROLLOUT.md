# Operational Rollout Plan

## Purpose

This document defines operational ownership and execution policy for production rollout:
1. SLO ownership
2. on-call responsibilities
3. escalation and incident command
4. rollout control and evidence requirements

## SLO Ownership Matrix

| SLO Domain | Target | Primary Owner | Secondary Owner | Pager Policy |
|---|---:|---|---|---|
| API availability | 99.0% (5xx < 1%) | `platform_oncall` | `model_oncall` | page on `critical` |
| API latency | p95 < 1s | `platform_oncall` | `platform_backup` | page on sustained breach + user impact |
| Model-serving availability | 99.0% (5xx < 1%) | `model_oncall` | `platform_oncall` | page on `critical`, ticket on warning |
| Data/model quality drift | thresholds in config | `model_oncall` | `platform_oncall` | page if sustained + user impact |
| Guardrail fallback rate | service-specific baseline | `model_oncall` | `platform_oncall` | immediate page |

Reference alerts:
- `/Users/hemanthsai/Desktop/decision-platform/observability/prometheus/rules/slo_alerts.yml`

## On-Call Structure

Roles:
1. `platform_oncall`: API, DB, Redis, deployment, network, infra reliability.
2. `model_oncall`: model-serving, calibration, canary quality, drift response.
3. `incident_commander`: assigned during SEV incidents; owns timeline and decisions.
4. `scribe`: records timeline, actions, and owner handoffs.

Cadence:
1. Weekly primary rotation, weekly secondary rotation.
2. Mandatory handoff summary at rotation boundary.
3. Backup responder required for weekends/holidays.

## Escalation Rules

1. `critical` not acknowledged in 5 minutes: escalate to backup on-call.
2. `critical` unresolved in 15 minutes: escalate to incident commander + engineering manager.
3. `critical` unresolved in 30 minutes: notify product/operations leadership.
4. Any tenant-wide impact: open incident bridge immediately.

## Incident Response Workflow

1. Detect: Alertmanager page/slack/ticket.
2. Triage: classify severity and blast radius.
3. Mitigate: rollback canary and/or force safe path.
4. Stabilize: confirm SLO return and no active critical alerts.
5. Recover: validate data/model quality and rollout readiness.
6. Learn: complete postmortem and preventive actions.

Detailed response procedures:
- `/Users/hemanthsai/Desktop/decision-platform/docs/INCIDENT_RESPONSE_RUNBOOK.md`

## Rollout Safety Controls

Required controls before promotion:
1. Promotion gates pass with minimum sample threshold.
2. Canary progression evidence exists: `5 -> 25 -> 50 -> 100`.
3. No SLO breach in validation window.
4. Drift checks clean (or explicitly accepted with risk sign-off).
5. Calibration is fresh and sample-adequate.

Automated validation command:
```bash
PROMETHEUS_URL=<prom-url> make validate-live-rollout
```

## Business Adoption And Impact Scorecard

Decision window policy:
1. Current window: last 28 days.
2. Baseline window: prior 28 days immediately before current window.
3. Track overall and by tenant/section for production sign-off.

Target KPIs:

| Area | KPI | Target |
|---|---|---:|
| Adoption | assisted_coverage_pct | >= 80% |
| Adoption | agent_weekly_active_usage_pct | >= 70% |
| Adoption | feedback_completeness_pct | >= 95% |
| Accuracy | top1_route_accuracy_pct | >= 85% |
| Accuracy | escalation_precision_pct | >= 80% |
| Accuracy | escalation_recall_pct | >= 75% |
| Accuracy | ece | <= 0.10 |
| Impact | escalation_rate_reduction_pct | >= 20% |
| Impact | median_handling_time_reduction_pct | >= 25% |
| Impact | p90_handling_time_reduction_pct | >= 15% |

Required operational feed for adoption denominators:
1. Populate `ops_workload_daily` daily per tenant/section with:
   - `eligible_tickets_total`
   - `active_agents_total`
2. Targets are stored in `business_kpi_targets` and can be adjusted without code changes.

Run scorecard with default windows:

```bash
make business-scorecard
```

Run scorecard for specific window and tenant:

```bash
.venv/bin/python -m scripts.compute_business_scorecard \
  --window-start 2026-01-20 \
  --window-end 2026-02-16 \
  --baseline-start 2025-12-23 \
  --baseline-end 2026-01-19 \
  --tenant-id org_demo \
  --fail-on-miss
```

Artifacts:
1. `artifacts/reports/business_scorecard_<window_end>.json`
2. `artifacts/reports/business_scorecard_<window_end>.md`

## Communication Templates

### Incident Start

```
[SEV{n}] Decision Platform incident opened
Start: <UTC timestamp>
Impact: <tenant(s)/feature(s)>
Current symptoms: <summary>
Commander: <name>
Next update: <+15 min>
```

### Incident Update

```
[SEV{n}] Update <timestamp UTC>
Status: <investigating|mitigating|monitoring>
What changed: <action/result>
ETA: <time or unknown>
Risks: <known risks>
```

### Incident Resolved

```
[SEV{n}] Resolved <timestamp UTC>
Duration: <minutes>
Root cause (initial): <summary>
Follow-up postmortem: <ticket/link>
```

## Operational Readiness Checklist

Go-live readiness:
1. Alert routes configured and test alert delivered to on-call channels.
2. SLO dashboard reviewed by platform + model owners.
3. `prod-check` passes with production env.
4. `validate-live-rollout` policy agreed by owners.
5. Incident runbook reviewed in last 30 days.
6. Rollback drill completed at least once per quarter.

Weekly operations:
1. Review alert noise and tune thresholds.
2. Review canary/quality metrics and drift.
3. Verify on-call roster and escalation contacts.

Monthly operations:
1. Review error budget burn and SLO target fitness.
2. Review top incidents and unresolved remediation actions.
3. Rehearse incident drill if no real incident occurred.

Implementation guide for incident platform setup:
- `/Users/hemanthsai/Desktop/decision-platform/docs/INCIDENT_PLATFORM_SETUP.md`

End-to-end production completion playbook:
- `/Users/hemanthsai/Desktop/decision-platform/docs/PRODUCTION_COMPLETION_PLAYBOOK.md`
