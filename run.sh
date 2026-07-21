#!/usr/bin/env bash
# Start the escalation harness backend + inbox.
# Usage: ./run.sh   then open http://127.0.0.1:8000
set -euo pipefail

cd "$(dirname "$0")"

# Prefer the local venv if it exists.
PY="python3"
if [ -x ".venv/bin/python" ]; then
  PY=".venv/bin/python"
fi

HOST="${HARNESS_HOST:-127.0.0.1}"
PORT="${HARNESS_PORT:-8000}"

echo "Starting escalation harness on http://${HOST}:${PORT}"
echo "Open the inbox in a browser, then run: ${PY} demo/demo_agent.py"
exec "$PY" -m uvicorn harness.app:app --host "$HOST" --port "$PORT"
