# Security And Compliance Audit (FAIL)

- Generated at (UTC): 2026-02-17T22:40:05.658963+00:00

## Errors
- APP_ENV must be production/prod.
- AUTH_ENABLED must be true.
- JWT_SECRET_KEY is insecure/default.
- USE_POSTGRES must be true.
- Control recency check failed for secret_rotation: status=missing_pass_event, max_age_days=90.
- Control recency check failed for access_review: status=missing_pass_event, max_age_days=90.
- Control recency check failed for oncall_schedule_audit: status=missing_pass_event, max_age_days=30.
- Control recency check failed for incident_endpoint_verification: status=missing_pass_event, max_age_days=30.

## Warnings
- RATE_LIMIT_ENABLED is false in production expectation.
- USE_REDIS is false; rate-limit and queue protections may be degraded.
- ALERTMANAGER_PAGER_WEBHOOK_URL is not present in environment for this audit process.
- ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL is not present in environment for this audit process.
- ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL is not present in environment for this audit process.
- ALERTMANAGER_TICKET_WEBHOOK_URL is not present in environment for this audit process.

## Control Recency
- secret_rotation: status=missing_pass_event, age_days=n/a, max_age_days=90
- access_review: status=missing_pass_event, age_days=n/a, max_age_days=90
- oncall_schedule_audit: status=missing_pass_event, age_days=n/a, max_age_days=30
- incident_endpoint_verification: status=missing_pass_event, age_days=n/a, max_age_days=30
