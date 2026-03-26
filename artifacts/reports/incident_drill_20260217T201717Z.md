# Incident Drill Evidence

- Timestamp (UTC): 20260217T201717Z
- Scenario: DecisionApiHighErrorRate (simulated), trigger rollback policy
- Health response: {"status":"ok"}
- Ready response: {"status":"ready","checks":{"database":{"enabled":true,"status":"ok","latency_ms":112.9},"redis":{"enabled":false,"status":"skipped","detail":"USE_REDIS=false"},"model_serving":{"enabled":false,"status":"skipped","detail":"ROUTING_MODEL_BACKEND=artifact"}}}
- Canary before drill: 0
- Canary after rollback action: 5
- Canary after restore: 0
- Rollback command exit code: 0
- Live validation command exit code: 0

## Rollback Command Output

```
Canary gate result: BLOCKED. Current=25%, target=5% (rollback to 5%). samples=0, route_acc=None, escalation_recall=None, ece=None, abstain_rate=None, source_scope=canary_only
Blocking reasons: no_canary_samples, sample_size_below_gate, missing_route_accuracy, missing_escalation_recall, missing_ece
```

## Live Validation Output

```
Live rollout validation: BLOCKED. stable_days=0/14, canary_percent=5, drift_alert_rows=0, labeled_count=0
Report JSON: artifacts/reports/live_rollout_validation_2026-02-16.json
Report Markdown: artifacts/reports/live_rollout_validation_2026-02-16.md
Blocking reasons: insufficient_stable_canary_window, drift_alerts_or_missing_drift_rows, labeling_integrity_not_met, canary_progression_not_complete_to_100, calibration_requirements_not_met
```

## Latest Rollout Event

```
2026-02-16|rollback|true|25|5|blocked|0
```
