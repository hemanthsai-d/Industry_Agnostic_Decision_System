# Security And Compliance Audit (FAIL)

- Generated at (UTC): 2026-02-17T23:33:19.348168+00:00

## Errors
- APP_ENV must be production/prod.
- AUTH_ENABLED must be true.
- JWT_SECRET_KEY is insecure/default.

## Warnings
- RATE_LIMIT_ENABLED is false in production expectation.
- USE_REDIS is false; rate-limit and queue protections may be degraded.

## Control Recency
- secret_rotation: status=ok, age_days=0, max_age_days=90
- access_review: status=ok, age_days=0, max_age_days=90
- oncall_schedule_audit: status=ok, age_days=0, max_age_days=30
- incident_endpoint_verification: status=ok, age_days=0, max_age_days=30
