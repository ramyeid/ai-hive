#!/usr/bin/env bash
# Starts the Hive console at http://127.0.0.1:8420 (this machine only).
#   bash scripts/start.sh                 in this terminal (Ctrl+C stops it)
#   bash scripts/start.sh --background    in the background; output in data/hive.log, stop with scripts/stop.sh
# On a server opened from other machines (behind your VPN), see docs/INSTALL.md:
#   HOST=0.0.0.0 CONSOLE_HOSTS=hive.internal CONSOLE_PASSWORD=… CONSOLE_URL=http://hive.internal:8420 bash scripts/start.sh
set -euo pipefail
KIT="$(cd "$(dirname "$0")/.." && pwd)"
export PORT="${PORT:-8420}"
HOST="${HOST:-127.0.0.1}"
LOG="$KIT/data/hive.log"
PID="$KIT/data/hive.pid"
mkdir -p "$KIT/data"

if [ "${1:-}" = "--background" ]; then
  if [ -f "$PID" ] && kill -0 "$(cat "$PID")" 2>/dev/null; then
    echo "Hive is already running (pid $(cat "$PID")). Stop it with: bash scripts/stop.sh"
    exit 0
  fi
  NO_BROWSER=1 nohup bash "$0" > "$LOG" 2>&1 &
  echo $! > "$PID"
  # The first run installs packages, so give it time to come up.
  for _ in $(seq 1 90); do
    if ! kill -0 "$(cat "$PID")" 2>/dev/null; then
      rm -f "$PID"
      echo "Hive stopped while starting. Last lines of $LOG:"
      tail -20 "$LOG"
      exit 1
    fi
    if grep -q "Uvicorn running on" "$LOG" 2>/dev/null; then
      echo "Hive running in the background (pid $(cat "$PID")) → ${CONSOLE_URL:-http://127.0.0.1:$PORT}"
      echo "Log: $LOG   Stop: bash scripts/stop.sh"
      if [ "${ENABLE_TERMINAL:-1}" = "0" ]; then echo "Terminal page: off"
      else echo "Terminal page: on (anyone who can open the console gets a shell here; ENABLE_TERMINAL=0 turns it off)"; fi
      exit 0
    fi
    sleep 1
  done
  echo "Still starting after 90 s (pid $(cat "$PID")). Follow it with: tail -f $LOG"
  exit 0
fi

# Dependencies and Python are managed by uv (https://docs.astral.sh/uv/): backend/pyproject.toml + uv.lock.
if ! command -v uv >/dev/null; then
  echo "uv is required to run Hive."
  echo "  macOS:  brew install uv"
  echo "  Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  exit 1
fi
cd "$KIT/backend"
# Installs exactly what uv.lock pins into backend/.venv (and a suitable Python if this machine lacks one).
uv sync --locked --quiet

URL="http://127.0.0.1:$PORT"
if [ -z "${NO_BROWSER:-}" ]; then
  ( sleep 1.5
    if [ "$(uname)" = "Darwin" ]; then open "$URL"
    elif command -v xdg-open >/dev/null; then xdg-open "$URL" >/dev/null 2>&1
    fi ) &
fi
echo "Hive → ${CONSOLE_URL:-$URL}   (Ctrl+C to stop)"
# Open pages keep a live connection: at shutdown they get 5 s, then Hive stops its agents and exits.
exec uv run --locked uvicorn hive.main:app --host "$HOST" --port "$PORT" --timeout-graceful-shutdown 5
