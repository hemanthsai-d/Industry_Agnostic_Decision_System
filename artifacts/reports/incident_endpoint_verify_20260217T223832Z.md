# Incident Endpoint Verification (FAIL)

- Generated at (UTC): 2026-02-17T22:38:32.869058+00:00
- Mode: live

## Endpoint Status
- pager: `missing`
- model_oncall: `missing`
- platform_oncall: `missing`
- ticket: `missing`

## Evidence Links
- pager: `missing`
- model_oncall: `missing`
- platform_oncall: `missing`
- ticket: `missing`

## Drill Result
- drill exit code: 1

```text
Missing required webhook URLs:
  - ALERTMANAGER_PAGER_WEBHOOK_URL
  - ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL
  - ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL
  - ALERTMANAGER_TICKET_WEBHOOK_URL
Set these env vars or pass explicit CLI args, then rerun.
```

## Errors
- ALERTMANAGER_PAGER_WEBHOOK_URL is missing.
- ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL is missing.
- ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL is missing.
- ALERTMANAGER_TICKET_WEBHOOK_URL is missing.
- Evidence link missing for pager route.
- Evidence link missing for model_oncall route.
- Evidence link missing for platform_oncall route.
- Evidence link missing for ticket route.
- Alertmanager E2E drill failed with exit code 1.
