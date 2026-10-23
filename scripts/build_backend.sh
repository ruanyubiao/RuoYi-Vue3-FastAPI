#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$REPO_ROOT"

PY="$REPO_ROOT/ruoyi-fastapi-backend/venv/bin/python"
if [[ ! -x "$PY" ]]; then
  echo "ERROR: Cannot find venv python, please create venv in ruoyi-fastapi-backend first" >&2
  exit 1
fi

exec "$PY" "$SCRIPT_DIR/_build_backend.py" "$@"
