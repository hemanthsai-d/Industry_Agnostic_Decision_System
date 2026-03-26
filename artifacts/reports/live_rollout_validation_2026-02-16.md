# Live Rollout Validation (BLOCKED)

- Generated at (UTC): 2026-02-17T23:33:19.106192+00:00
- Validation window: 2026-01-20 -> 2026-02-16
- Stable days required: 14
- Stable days observed: 0

## Checks
- quality_window_passed: False
- drift_passed: False
- labeling_passed: False
- slo_passed: True
- canary_passed: False
- rollback_drill_passed: False
- calibration_passed: False
- overall_passed: False

## Blocking Reasons
- insufficient_stable_canary_window
- drift_alerts_or_missing_drift_rows
- labeling_integrity_not_met
- canary_progression_not_complete_to_100
- rollback_drill_not_recorded
- calibration_requirements_not_met
