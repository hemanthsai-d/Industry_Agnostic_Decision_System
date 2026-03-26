# Incident Endpoint Verification (PASS)

- Generated at (UTC): 2026-02-17T23:16:10.345827+00:00
- Mode: live

## Endpoint Status
- pager: `https://pager.acmeops.com/hook`
- model_oncall: `https://model.acmeops.com/hook`
- platform_oncall: `https://platform.acmeops.com/hook`
- ticket: `https://ticket.acmeops.com/hook`

## Evidence Links
- pager: `https://ops.example.net/pager/1`
- model_oncall: `https://ops.example.net/model/1`
- platform_oncall: `https://ops.example.net/platform/1`
- ticket: `https://ops.example.net/ticket/1`

## Drill Result
- drill exit code: 0

```text
Rendered production Alertmanager config: observability/alertmanager/alertmanager.prod.yml
Activated production Alertmanager config: observability/alertmanager/alertmanager.yml
Alertmanager E2E drill complete. Evidence written to artifacts/reports/alertmanager_e2e_20260217T231610Z.md
 Container decision_alertmanager Running
```

## Errors
- none
