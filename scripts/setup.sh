#!/usr/bin/env bash
set -euo pipefail

EXPECTED_VENV_PATH="$(pwd)/.venv"

if [[ ! -x ".venv/bin/python" ]]; then
  python3 -m venv .venv
else
  CURRENT_PREFIX="$(".venv/bin/python" -c 'import sys; print(sys.prefix)')"
  if [[ "$CURRENT_PREFIX" != "$EXPECTED_VENV_PATH" ]]; then
    python3 -m venv --clear .venv
  fi
fi

.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt

.venv/bin/python - <<'PY'
from pathlib import Path
import re

venv_path = str(Path.cwd() / ".venv")

activate = Path(".venv/bin/activate")
if activate.exists():
    text = activate.read_text()
    text = re.sub(r"/Users/[^\n\"']+/\.venv", venv_path, text)
    activate.write_text(text)

activate_csh = Path(".venv/bin/activate.csh")
if activate_csh.exists():
    text = activate_csh.read_text()
    text = re.sub(r"/Users/[^\n\"']+/\.venv", venv_path, text)
    activate_csh.write_text(text)

activate_fish = Path(".venv/bin/activate.fish")
if activate_fish.exists():
    text = activate_fish.read_text()
    text = re.sub(r"/Users/[^\n\"']+/\.venv", venv_path, text)
    activate_fish.write_text(text)
PY

echo "Setup complete."
echo "Next steps:"
echo "  cp .env.example .env"
echo "  make test"
echo "  make run-api"
