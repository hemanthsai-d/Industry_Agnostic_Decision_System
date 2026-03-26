#!/usr/bin/env bash
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

require_env() {
  local name="$1"
  if [[ -z "${!name:-}" ]]; then
    fail "Missing required env var: ${name}"
  fi
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    fail "Missing required file: ${path}"
  fi
}

require_non_placeholder_url() {
  local name="$1"
  local value="${!name:-}"
  local lower
  lower="$(echo "$value" | tr '[:upper:]' '[:lower:]')"
  if [[ -z "$value" ]]; then
    fail "Missing required URL env var: ${name}"
  fi
  if [[ "$lower" == *"example.com"* || "$lower" == *"example.invalid"* || "$lower" == *"<"* || "$lower" == *"placeholder"* ]]; then
    fail "${name} looks placeholder-like: ${value}"
  fi
}

FAILURES=0
STEP_RESULTS=()

run_step() {
  local name="$1"
  shift
  echo "==> ${name}"
  if "$@"; then
    STEP_RESULTS+=("PASS: ${name}")
    return 0
  else
    local code=$?
    STEP_RESULTS+=("FAIL(${code}): ${name}")
    echo "STEP FAILED: ${name} (exit=${code})" >&2
    FAILURES=$((FAILURES + 1))
    return 0
  fi
}

echo "==> Production completion run starting"

require_env PERFORMED_BY
require_env WORKLOAD_CSV
require_file "$WORKLOAD_CSV"

ONCALL_CONFIG="${ONCALL_CONFIG:-ops/oncall.production.json}"
require_file "$ONCALL_CONFIG"

require_non_placeholder_url ALERTMANAGER_PAGER_WEBHOOK_URL
require_non_placeholder_url ALERTMANAGER_MODEL_ONCALL_WEBHOOK_URL
require_non_placeholder_url ALERTMANAGER_PLATFORM_ONCALL_WEBHOOK_URL
require_non_placeholder_url ALERTMANAGER_TICKET_WEBHOOK_URL

require_env EVIDENCE_PAGER_URL
require_env EVIDENCE_MODEL_ONCALL_URL
require_env EVIDENCE_PLATFORM_ONCALL_URL
require_env EVIDENCE_TICKET_URL
require_env SECRET_ROTATION_EVIDENCE_URL
require_env ACCESS_REVIEW_EVIDENCE_URL
require_env PROMETHEUS_URL

ONCALL_AUDIT_EVIDENCE_URL="${ONCALL_AUDIT_EVIDENCE_URL:-$ONCALL_CONFIG}"
CONTROL_SCOPE="${CONTROL_SCOPE:-global}"
API_BASE_URL="${API_BASE_URL:-http://127.0.0.1:8000}"
API_BEARER_TOKEN="${API_BEARER_TOKEN:-}"
LOAD_DURATION_SECONDS="${LOAD_DURATION_SECONDS:-120}"
LOAD_CONCURRENCY="${LOAD_CONCURRENCY:-20}"
SOAK_DURATION_SECONDS="${SOAK_DURATION_SECONDS:-900}"
SOAK_CONCURRENCY="${SOAK_CONCURRENCY:-10}"
FAILURE_DURATION_SECONDS="${FAILURE_DURATION_SECONDS:-180}"
FAILURE_CONCURRENCY="${FAILURE_CONCURRENCY:-8}"

run_step "Applying DB migrations" make migrate-db

run_step "Loading workload denominator feed" bash -lc "WORKLOAD_CSV='$WORKLOAD_CSV' make workload-feed"

run_step "Auditing on-call schedule and recording evidence" \
  .venv/bin/python -m scripts.audit_oncall_config \
    --config "$ONCALL_CONFIG" \
    --record-event \
    --performed-by "$PERFORMED_BY" \
    --scope "$CONTROL_SCOPE" \
    --evidence-uri "$ONCALL_AUDIT_EVIDENCE_URL"

run_step "Verifying real incident endpoints and recording evidence" \
  .venv/bin/python -m scripts.verify_incident_endpoints_live \
    --mode live \
    --run-drill \
    --record-event \
    --performed-by "$PERFORMED_BY" \
    --scope "$CONTROL_SCOPE" \
    --evidence-pager "$EVIDENCE_PAGER_URL" \
    --evidence-model-oncall "$EVIDENCE_MODEL_ONCALL_URL" \
    --evidence-platform-oncall "$EVIDENCE_PLATFORM_ONCALL_URL" \
    --evidence-ticket "$EVIDENCE_TICKET_URL"

run_step "Recording secret rotation control evidence" \
  .venv/bin/python -m scripts.record_operational_control \
    --control-type secret_rotation \
    --status pass \
    --scope "$CONTROL_SCOPE" \
    --performed-by "$PERFORMED_BY" \
    --evidence-uri "$SECRET_ROTATION_EVIDENCE_URL"

run_step "Recording access review control evidence" \
  .venv/bin/python -m scripts.record_operational_control \
    --control-type access_review \
    --status pass \
    --scope "$CONTROL_SCOPE" \
    --performed-by "$PERFORMED_BY" \
    --evidence-uri "$ACCESS_REVIEW_EVIDENCE_URL"

run_step "Running business scorecard" make business-scorecard
run_step "Running live rollout validation" bash -lc "PROMETHEUS_URL='$PROMETHEUS_URL' make validate-live-rollout"

run_step "Running security/compliance audit" make security-audit

run_step "Running non-functional load test" \
  .venv/bin/python -m scripts.run_nonfunctional_validation \
    --mode load \
    --base-url "$API_BASE_URL" \
    --token "$API_BEARER_TOKEN" \
    --duration-seconds "$LOAD_DURATION_SECONDS" \
    --concurrency "$LOAD_CONCURRENCY" \
    --record-event \
    --performed-by "$PERFORMED_BY" \
    --scope "$CONTROL_SCOPE"

run_step "Running non-functional soak test" \
  .venv/bin/python -m scripts.run_nonfunctional_validation \
    --mode soak \
    --base-url "$API_BASE_URL" \
    --token "$API_BEARER_TOKEN" \
    --duration-seconds "$SOAK_DURATION_SECONDS" \
    --concurrency "$SOAK_CONCURRENCY" \
    --record-event \
    --performed-by "$PERFORMED_BY" \
    --scope "$CONTROL_SCOPE"

run_step "Running non-functional failure test" \
  .venv/bin/python -m scripts.run_nonfunctional_validation \
    --mode failure \
    --base-url "$API_BASE_URL" \
    --token "$API_BEARER_TOKEN" \
    --duration-seconds "$FAILURE_DURATION_SECONDS" \
    --concurrency "$FAILURE_CONCURRENCY" \
    --record-event \
    --performed-by "$PERFORMED_BY" \
    --scope "$CONTROL_SCOPE"

run_step "Running final production readiness gate report" \
  .venv/bin/python -m scripts.production_readiness_gate --prometheus-url "$PROMETHEUS_URL"

LATEST_GATE_JSON="$(ls -1t artifacts/reports/production_readiness_gate_*.json 2>/dev/null | head -n 1 || true)"
if [[ -z "$LATEST_GATE_JSON" ]]; then
  STEP_RESULTS+=("FAIL: final gate report not found")
  FAILURES=$((FAILURES + 1))
else
  if ! .venv/bin/python - "$LATEST_GATE_JSON" <<'PY'
import json
import sys

path = sys.argv[1]
with open(path, 'r', encoding='utf-8') as handle:
    payload = json.load(handle)

overall = bool(payload.get('overall_passed'))
status = 'PASS' if overall else 'BLOCKED'
print(f"Final gate status from {path}: {status}")
sys.exit(0 if overall else 2)
PY
  then
    STEP_RESULTS+=("FAIL: production readiness gate is BLOCKED")
    FAILURES=$((FAILURES + 1))
  else
    STEP_RESULTS+=("PASS: production readiness gate is PASS")
  fi
fi

echo "==> Production completion run summary"
for row in "${STEP_RESULTS[@]}"; do
  echo " - ${row}"
done
echo "Reports directory: artifacts/reports/"

if [[ "$FAILURES" -gt 0 ]]; then
  echo "Completed with ${FAILURES} failing step(s)." >&2
  exit 2
fi

echo "Completed successfully with all gates passing."
