#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is required for Redis integration tests."
  exit 1
fi

if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon is not running. Start Docker Desktop (or daemon) and retry."
  exit 1
fi

if [[ ! -x ".venv/bin/python" ]]; then
  echo "Virtualenv not found. Run ./scripts/setup.sh first."
  exit 1
fi

export REDIS_URL="${REDIS_URL:-redis://127.0.0.1:6379/0}"
export DECISION_PLATFORM_RUN_REDIS_RATE_LIMIT_E2E=1

docker compose up -d redis

echo "Waiting for Redis at ${REDIS_URL}..."
for _ in $(seq 1 30); do
  if .venv/bin/python - <<'PY'
import os
import redis
import sys

url = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
try:
    client = redis.Redis.from_url(url, decode_responses=True)
    client.ping()
    client.close()
except Exception:
    sys.exit(1)
sys.exit(0)
PY
  then
    echo "Redis is ready."
    break
  fi
  sleep 1
done

.venv/bin/python -m pytest -q -m integration tests/integration/test_rate_limit_redis_e2e.py
