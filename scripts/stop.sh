#!/usr/bin/env bash
# Stops Hive started with `scripts/start.sh --background`. Running agents are stopped first.
set -euo pipefail
PID_FILE="$(cd "$(dirname "$0")/.." && pwd)/data/hive.pid"

if [ ! -f "$PID_FILE" ]; then
  echo "Hive isn't running in the background (no data/hive.pid)."
  exit 0
fi
PID="$(cat "$PID_FILE")"
if ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_FILE"
  echo "Hive wasn't running (pid $PID had already exited)."
  exit 0
fi

kill -TERM "$PID"          # graceful: Hive stops its agents, then exits
for _ in $(seq 1 20); do
  kill -0 "$PID" 2>/dev/null || { rm -f "$PID_FILE"; echo "Hive stopped (pid $PID)."; exit 0; }
  sleep 1
done

pkill -KILL -P "$PID" 2>/dev/null || true   # agent processes it started
kill -KILL "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Hive didn't stop within 20 s, so it was killed (pid $PID)."
