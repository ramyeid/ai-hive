#!/usr/bin/env bash
# Starts the Agent Team Console at http://127.0.0.1:8420 (this machine only).
# On a server you open from other machines (behind your VPN), see server/access.py:
#   HOST=0.0.0.0 CONSOLE_HOSTS=hive.internal CONSOLE_PASSWORD=… CONSOLE_URL=http://hive.internal:8420 bash start.sh
set -euo pipefail
cd "$(dirname "$0")"
export PORT="${PORT:-8420}"
HOST="${HOST:-127.0.0.1}"

# Dependencies and Python are managed by uv (https://docs.astral.sh/uv/): pyproject.toml + uv.lock.
if ! command -v uv >/dev/null; then
  echo "uv is required to run the console."
  echo "  macOS:  brew install uv"
  echo "  Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
# Installs exactly what uv.lock pins into .venv (and a suitable Python if this machine lacks one).
uv sync --locked --quiet

URL="http://127.0.0.1:$PORT"
if [ -z "${NO_BROWSER:-}" ]; then   # service-start.sh sets NO_BROWSER
  ( sleep 1.5
    if [ "$(uname)" = "Darwin" ]; then open "$URL"
    elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1
    fi ) &
fi
echo "Agent Team Console → ${CONSOLE_URL:-$URL}   (Ctrl+C to stop)"
exec uv run --locked uvicorn server.main:app --host "$HOST" --port "$PORT"
