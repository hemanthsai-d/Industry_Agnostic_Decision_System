# Incident Platform Production Setup

This checklist maps Alertmanager routes to real incident tooling and records go-live evidence.

## 1) Create real incident endpoints

Create one endpoint per route in your incident platform stack:
1. Critical pager endpoint (`ops-pager-critical`)
2. Model on-call warning endpoint (`model-oncall-warning`)
3. Platform on-call warning endpoint (`platform-oncall-warning`)
4. Ticketing endpoint (`ops-ticket`)

Recommended mapping:
1. Pager endpoint -> pager service or incident event API
2. Model on-call endpoint -> model team Slack/on-call integration
3. Platform on-call endpoint -> platform team Slack/on-call integration
4. Ticket endpoint -> issue tracker intake webhook

## 2) Configure schedules and escalation contacts

Minimum required schedule and escalation policy:
1. `platform_oncall` primary + backup weekly rotation
2. `model_oncall` primary + backup weekly rotation
3. Escalation policy:
   - T+5m: backup on-call
   - T+15m: incident commander + engineering manager
   - T+30m: product/ops leadership

Document real contacts in your incident platform:
1. Name
2. Role
3. Primary contact method
4. Secondary contact method
5. Timezone and coverage window

## 3) Apply production Alertmanager config

Export real endpoints and activate the config:

```bash
export ALERTMANAGER_PAGER_WEBHOOK_URL='https://<real-pager-endpoint>'
export ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL='https://<real-model-oncall-endpoint>'
export ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL='https://<real-platform-oncall-endpoint>'
export ALERTMANAGER_TICKET_WEBHOOK_URL='https://<real-ticket-endpoint>'
make configure-alertmanager-prod
```

The renderer rejects empty or placeholder values.

## 4) Deploy and run alert drill

Deploy Alertmanager and fire end-to-end test alerts:

```bash
ALERT_E2E_MODE=live make alertmanager-e2e-drill
```

In `live` mode, the script verifies Alertmanager readiness + alert injection and writes evidence.
Confirm delivery in your incident platform UI for all four routes and attach screenshots/links.

Use the production verification wrapper to enforce evidence links:

```bash
.venv/bin/python -m scripts.verify_incident_endpoints_live \
  --mode live \
  --run-drill \
  --evidence-pager <pager-incident-link> \
  --evidence-model-oncall <model-oncall-link> \
  --evidence-platform-oncall <platform-oncall-link> \
  --evidence-ticket <ticket-link>
```

For local proof without external connectivity:

```bash
ALERT_E2E_MODE=local make alertmanager-e2e-drill
```

This uses a local webhook sink and validates all route deliveries automatically.

## 5) Run operational drills and attach evidence

Run and capture:
1. Incident drill (`docs/INCIDENT_RESPONSE_RUNBOOK.md`)
2. Rollback drill (`scripts/promote_canary.py --rollback-on-fail`)

Store final evidence in `artifacts/reports/`:
1. Alertmanager E2E drill output
2. Incident drill timeline and command outputs
3. Rollback drill outputs
4. Incident platform screenshots/URLs showing page/slack/ticket events
