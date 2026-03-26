# Production Readiness Gate (BLOCKED)

- Generated at (UTC): 2026-02-18T00:19:29.800943+00:00
- Scope tenant: __all__
- Scope section: __all__

## Gates
- live_rollout_passed: False
- business_kpi_passed: False
- workload_feed_coverage_passed: False
- label_coverage_passed: True
- control_recency_passed: False
- overall_passed: False

## Blocking Reasons
- live_rollout_validation_blocked
- business_kpi_targets_not_met
- ops_workload_daily_has_missing_dates
- operational_control_recency_failed

## Control Recency
- incident_endpoint_verification: status=missing_pass_event, age_days=None, max_age_days=30
- oncall_schedule_audit: status=missing_pass_event, age_days=None, max_age_days=30
- secret_rotation: status=missing_pass_event, age_days=None, max_age_days=90
- access_review: status=missing_pass_event, age_days=None, max_age_days=90
- load_test: status=ok, age_days=0, max_age_days=30
- soak_test: status=ok, age_days=0, max_age_days=30
- failure_test: status=ok, age_days=0, max_age_days=30
