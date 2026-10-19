#!/usr/bin/env bash
# Starts the Agent Team Console at http://127.0.0.1:8420 (this machine only).
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8420}"

# The Claude Agent SDK needs Python 3.10 or newer.
if [ ! -x .venv/bin/python ]; then
  PY=""
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null &&
       "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
      PY="$candidate"; break
    fi
  done
  if [ -z "$PY" ]; then
    echo "Python 3.10 or newer is required. Install it with:  brew install python@3.12"; exit 1
  fi
  echo "Setting up the console (first run only)…"
  "$PY" -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
fi
.venv/bin/pip install --quiet -r requirements.txt

( sleep 1.5; command -v open >/dev/null && open "http://127.0.0.1:$PORT" ) &
echo "Agent Team Console → http://127.0.0.1:$PORT   (Ctrl+C to stop)"
exec .venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port "$PORT"
