#!/usr/bin/env bash
# Starts the console in the background. Output goes to service.log; stop it with service-stop.sh.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8420}"

if [ -f service.pid ] && kill -0 "$(cat service.pid)" 2>/dev/null; then
  echo "The console is already running (pid $(cat service.pid)). Stop it with: bash service-stop.sh"
  exit 0
fi

NO_BROWSER=1 PORT="$PORT" nohup bash start.sh > service.log 2>&1 &
echo $! > service.pid

# The first run installs packages, so give it time to come up.
for _ in $(seq 1 90); do
  if ! kill -0 "$(cat service.pid)" 2>/dev/null; then
    rm -f service.pid
    echo "The console stopped while starting. Last lines of service.log:"
    tail -20 service.log
    exit 1
  fi
  if grep -q "Uvicorn running on" service.log 2>/dev/null; then
    echo "Console running in the background (pid $(cat service.pid)) → ${CONSOLE_URL:-http://127.0.0.1:$PORT}"
    echo "Log: $(pwd)/service.log   Stop: bash service-stop.sh"
    if [ "${ENABLE_TERMINAL:-1}" = "0" ]; then echo "Terminal page: off"
    else echo "Terminal page: on (anyone who can open the console gets a shell here; ENABLE_TERMINAL=0 turns it off)"; fi
    exit 0
  fi
  sleep 1
done
echo "Still starting after 90 s (pid $(cat service.pid)). Follow it with: tail -f service.log"
