#!/usr/bin/env bash
# Copies your data from a Hive folder with the old layout (before data/ existed) into this one.
#   bash scripts/migrate.sh /path/to/old/hive
# The old folder is only read, never changed. Run it before starting this copy of Hive for the first time.
#
#   old folder            this folder
#   tasks/          →     data/tasks/        the board, notifications, conversations, your code reviews
#   knowledge/      →     data/knowledge/    the Tech Lead's notes
#   coach/          →     data/coach/        the Coach's runs and proposals
#   console/data/   →     data/console/      settings (agents, keys, Slack), sessions
set -euo pipefail

OLD="${1:-}"
NEW="$(cd "$(dirname "$0")/.." && pwd)"
if [ -z "$OLD" ] || [ ! -d "$OLD" ]; then
  echo "Usage: bash scripts/migrate.sh /path/to/old/hive"
  exit 1
fi
OLD="$(cd "$OLD" && pwd)"
if [ "$OLD" = "$NEW" ]; then
  echo "That's this folder. Give the path of the old Hive folder."
  exit 1
fi
if [ ! -f "$OLD/TEAM.md" ] || [ ! -d "$OLD/console" ]; then
  echo "$OLD doesn't look like a Hive folder with the old layout (no TEAM.md or console/)."
  exit 1
fi
if [ -f "$NEW/data/hive.pid" ] && kill -0 "$(cat "$NEW/data/hive.pid")" 2>/dev/null; then
  echo "This Hive is running. Stop it first: bash scripts/stop.sh"
  exit 1
fi

PAIRS=("tasks:data/tasks" "knowledge:data/knowledge" "coach:data/coach" "console/data:data/console")

# Refuse to mix data: every destination must be empty (empty folders, as install.sh creates them, are fine).
for pair in "${PAIRS[@]}"; do
  to="$NEW/${pair#*:}"
  if [ -d "$to" ] && [ -n "$(find "$to" -type f -print -quit)" ]; then
    echo "${pair#*:} already has files in it, so nothing was copied. Migrate into a fresh copy of Hive."
    exit 1
  fi
done

for pair in "${PAIRS[@]}"; do
  from="$OLD/${pair%%:*}" to="$NEW/${pair#*:}"
  if [ ! -d "$from" ]; then
    echo "  ${pair%%:*}/ isn't in the old folder: skipped"
    continue
  fi
  mkdir -p "$to"
  cp -a "$from/." "$to/"
  if ! diff -rq "$from" "$to" >/dev/null; then
    echo "  ${pair%%:*}/ → ${pair#*:}/: the copy differs from the original. Your old folder is untouched:"
    diff -rq "$from" "$to" | head -10
    exit 1
  fi
  echo "  ${pair%%:*}/ → ${pair#*:}/: $(find "$to" -type f | wc -l | tr -d ' ') files, identical"
done

echo
echo "✓ Your data is in $NEW/data. The old folder is unchanged."
echo "Next: bash scripts/install.sh, then bash scripts/start.sh"
