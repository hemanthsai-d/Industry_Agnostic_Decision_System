#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

MODE="${ALERT_E2E_MODE:-local}"
ALERTMANAGER_URL="${ALERTMANAGER_URL:-http://127.0.0.1:9093}"
SINK_PORT="${ALERT_WEBHOOK_SINK_PORT:-19100}"
TS_UTC="$(date -u +%Y%m%dT%H%M%SZ)"
REPORT_PATH="artifacts/reports/alertmanager_e2e_${TS_UTC}.md"
SUMMARY_PATH="$ROOT_DIR/artifacts/reports/alert_webhook_summary_${TS_UTC}.json"
EVENTS_PATH="$ROOT_DIR/artifacts/reports/alert_webhook_events_${TS_UTC}.jsonl"
PAYLOAD_PATH="/tmp/decision_alertmanager_e2e_payload_${TS_UTC}.json"
SINK_LOG_PATH="/tmp/decision_webhook_sink_${TS_UTC}.log"
SINK_PID=""

mkdir -p "$ROOT_DIR/artifacts/reports"

cleanup() {
  if [[ -n "$SINK_PID" ]] && kill -0 "$SINK_PID" >/dev/null 2>&1; then
    kill "$SINK_PID" >/dev/null 2>&1 || true
    wait "$SINK_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

if [[ "$MODE" == "local" ]]; then
  export WEBHOOK_SINK_EVENTS_PATH="$EVENTS_PATH"
  .venv/bin/python -m uvicorn scripts.webhook_sink:app --host 127.0.0.1 --port "$SINK_PORT" >"$SINK_LOG_PATH" 2>&1 &
  SINK_PID="$!"

  sink_ready="0"
  for _ in {1..30}; do
    if curl -fsS "http://127.0.0.1:${SINK_PORT}/health" >/dev/null 2>&1; then
      sink_ready="1"
      break
    fi
    sleep 1
  done
  if [[ "$sink_ready" != "1" ]]; then
    echo "Webhook sink did not become ready on port ${SINK_PORT}" >&2
    exit 1
  fi

  export ALERTMANAGER_PAGER_WEBHOOK_URL="http://host.docker.internal:${SINK_PORT}/pager"
  export ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL="http://host.docker.internal:${SINK_PORT}/model-oncall"
  export ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL="http://host.docker.internal:${SINK_PORT}/platform-oncall"
  export ALERTMANAGER_TICKET_WEBHOOK_URL="http://host.docker.internal:${SINK_PORT}/ticket"
fi

.venv/bin/python -m scripts.configure_alertmanager_prod --activate
docker compose --profile observability up -d alertmanager

ready="0"
for _ in {1..60}; do
  if curl -fsS "${ALERTMANAGER_URL}/-/ready" >/dev/null; then
    ready="1"
    break
  fi
  sleep 1
done
if [[ "$ready" != "1" ]]; then
  echo "Alertmanager did not become ready at ${ALERTMANAGER_URL}" >&2
  exit 1
fi

cat >"$PAYLOAD_PATH" <<JSON
[
  {
    "labels": {
      "alertname": "E2ECriticalPager",
      "severity": "critical",
      "owner": "platform_oncall",
      "slo": "api_error_rate",
      "drill_id": "${TS_UTC}"
    },
    "annotations": {
      "summary": "E2E critical pager route test"
    },
    "startsAt": "2026-02-17T00:00:00Z",
    "endsAt": "2027-02-17T00:00:00Z"
  },
  {
    "labels": {
      "alertname": "E2EModelWarning",
      "severity": "warning",
      "owner": "model_oncall",
      "slo": "model_quality",
      "drill_id": "${TS_UTC}"
    },
    "annotations": {
      "summary": "E2E model on-call route test"
    },
    "startsAt": "2026-02-17T00:00:00Z",
    "endsAt": "2027-02-17T00:00:00Z"
  },
  {
    "labels": {
      "alertname": "E2EPlatformWarning",
      "severity": "warning",
      "owner": "platform_oncall",
      "slo": "api_latency",
      "drill_id": "${TS_UTC}"
    },
    "annotations": {
      "summary": "E2E platform on-call route test"
    },
    "startsAt": "2026-02-17T00:00:00Z",
    "endsAt": "2027-02-17T00:00:00Z"
  },
  {
    "labels": {
      "alertname": "E2ETicketOnly",
      "severity": "warning",
      "owner": "none",
      "slo": "misc",
      "drill_id": "${TS_UTC}"
    },
    "annotations": {
      "summary": "E2E ticket fallback route test"
    },
    "startsAt": "2026-02-17T00:00:00Z",
    "endsAt": "2027-02-17T00:00:00Z"
  }
]
JSON

curl -fsS -X POST "${ALERTMANAGER_URL}/api/v2/alerts" \
  -H 'Content-Type: application/json' \
  --data-binary "@${PAYLOAD_PATH}" >/dev/null

validation_note="live mode: external endpoint delivery verification not available from this environment"
if [[ "$MODE" == "local" ]]; then
  deliveries_verified="0"
  for _ in {1..120}; do
    curl -fsS "http://127.0.0.1:${SINK_PORT}/summary" >"$SUMMARY_PATH"
    if .venv/bin/python - "$SUMMARY_PATH" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    summary = json.load(handle)

required = ['/pager', '/model-oncall', '/platform-oncall', '/ticket']
counts = summary.get('counts', {})
missing = [route for route in required if int(counts.get(route, 0)) < 1]
if missing:
    sys.exit(1)
print('ok')
PY
    then
      deliveries_verified="1"
      break
    fi
    sleep 1
  done
  if [[ "$deliveries_verified" != "1" ]]; then
    echo "Missing webhook deliveries after timeout. Summary: $(cat "$SUMMARY_PATH")" >&2
    exit 1
  fi
  validation_note="local mode: webhook sink confirmed pager/model/platform/ticket deliveries"
fi

{
  echo "# Alertmanager E2E Drill Evidence"
  echo
  echo "- Timestamp (UTC): ${TS_UTC}"
  echo "- Mode: ${MODE}"
  echo "- Alertmanager URL: ${ALERTMANAGER_URL}"
  echo "- Active config: observability/alertmanager/alertmanager.yml"
  echo "- Posted alerts payload: ${PAYLOAD_PATH}"
  echo "- Validation: ${validation_note}"
  if [[ "$MODE" == "local" ]]; then
    echo "- Webhook events file: ${EVENTS_PATH}"
    echo "- Webhook summary file: ${SUMMARY_PATH}"
    echo
    echo "## Webhook Summary"
    echo
    echo '```json'
    cat "$SUMMARY_PATH"
    echo
    echo '```'
  fi
} >"$REPORT_PATH"

echo "Alertmanager E2E drill complete. Evidence written to ${REPORT_PATH}"
