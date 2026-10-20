#!/usr/bin/env bash
# Stops the console started by service-start.sh. Running agents are stopped first.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -f service.pid ]; then
  echo "The console isn't running in the background (no service.pid)."
  exit 0
fi
PID="$(cat service.pid)"
if ! kill -0 "$PID" 2>/dev/null; then
  rm -f service.pid
  echo "The console wasn't running (pid $PID had already exited)."
  exit 0
fi

kill -TERM "$PID"          # graceful: the console stops its agents, then exits
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || { rm -f service.pid; echo "Console stopped (pid $PID)."; exit 0; }
  sleep 1
done

pkill -KILL -P "$PID" 2>/dev/null || true   # agent processes it started
kill -KILL "$PID" 2>/dev/null || true
rm -f service.pid
echo "Console didn't stop within 20 s, so it was killed (pid $PID)."
