# Rollback Drill Evidence

- Timestamp (UTC): 20260217T201620Z
- Promote command exit code: 0
- Canary before drill: 0
- Canary after rollback command: 5
- Canary after restore: 0

## Promote Command Output

```
Canary gate result: BLOCKED. Current=25%, target=5% (rollback to 5%). samples=0, route_acc=None, escalation_recall=None, ece=None, abstain_rate=None, source_scope=canary_only
Blocking reasons: no_canary_samples, sample_size_below_gate, missing_route_accuracy, missing_escalation_recall, missing_ece
```

## Latest Rollout Event

```
2026-02-16|rollback|true|25|5|blocked|0
```
