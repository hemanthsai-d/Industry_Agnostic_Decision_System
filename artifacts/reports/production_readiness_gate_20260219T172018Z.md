# Production Readiness Gate (BLOCKED)

- Generated at (UTC): 2026-02-19T17:20:18.012662+00:00
- Scope tenant: __all__
- Scope section: __all__

## Gates
- live_rollout_passed: False
- business_kpi_passed: True
- workload_feed_coverage_passed: True
- label_coverage_passed: True
- control_recency_passed: True
- overall_passed: False

## Blocking Reasons
- live_rollout_validation_blocked

## Control Recency
- incident_endpoint_verification: status=ok, age_days=0, max_age_days=30
- oncall_schedule_audit: status=ok, age_days=0, max_age_days=30
- secret_rotation: status=ok, age_days=0, max_age_days=90
- access_review: status=ok, age_days=0, max_age_days=90
- load_test: status=ok, age_days=0, max_age_days=30
- soak_test: status=ok, age_days=0, max_age_days=30
- failure_test: status=ok, age_days=0, max_age_days=30
