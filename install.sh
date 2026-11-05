#!/usr/bin/env bash
# Installs the techlead / dev / reviewer agents for every project on this machine.
# Safe to re-run after any change to this kit (or after moving the kit folder).
set -euo pipefail

KIT="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR/agents" "$CLAUDE_DIR/commands" "$KIT/tasks/.inbox" "$KIT/knowledge" "$KIT/coach/proposals"

# Upgrade task and console data from older versions of the kit (safe to repeat).
python3 "$KIT/scripts/migrate.py"
# The PM agent became the Tech Lead: remove our old agent file (only if it's ours).
if [ -f "$CLAUDE_DIR/agents/pm.md" ] && grep -q "$KIT/TEAM.md" "$CLAUDE_DIR/agents/pm.md"; then
  rm "$CLAUDE_DIR/agents/pm.md"
fi

# Agents and slash commands, with this kit's absolute path filled in.
for f in "$KIT"/agents/*.md;   do sed "s#{{KIT}}#$KIT#g" "$f" > "$CLAUDE_DIR/agents/$(basename "$f")";   done
for f in "$KIT"/commands/*.md; do sed "s#{{KIT}}#$KIT#g" "$f" > "$CLAUDE_DIR/commands/$(basename "$f")"; done

# Merge the task hook and permissions into ~/.claude/settings.json (keeps everything else).
python3 - "$KIT" "$CLAUDE_DIR/settings.json" <<'PY'
import json, shutil, sys
from pathlib import Path

kit, path = sys.argv[1], Path(sys.argv[2])
settings = json.loads(path.read_text()) if path.exists() else {}
if path.exists():
    shutil.copy(path, path.with_name("settings.json.bak"))

# Hook: replace any previous copy of ours, keep all other hooks.
post = settings.setdefault("hooks", {}).setdefault("PostToolUse", [])
post[:] = [g for g in post
           if not any("on_task_change.py" in h.get("command", "") for h in g.get("hooks", []))]
post.append({"matcher": "Write|Edit|MultiEdit",
             "hooks": [{"type": "command",
                        "command": f'python3 "{kit}/scripts/on_task_change.py"'}]})

# Let the agents read the kit, edit task files and run the kit's scripts without prompting.
perms = settings.setdefault("permissions", {})
dirs = perms.setdefault("additionalDirectories", [])
if kit not in dirs:
    dirs.append(kit)
allow = perms.setdefault("allow", [])
for rule in (f"Edit(/{kit}/tasks/**)", f"Edit(/{kit}/knowledge/**)", f"Edit(/{kit}/coach/**)", f"Bash(python3 {kit}/scripts/*)"):
    if rule not in allow:
        allow.append(rule)

path.write_text(json.dumps(settings, indent=2) + "\n")
PY

echo "✓ Installed for every project:"
echo "    agents:   $(ls "$KIT"/agents | sed 's/\.md//' | tr '\n' ' ')→ $CLAUDE_DIR/agents"
echo "    commands: /board /ship"
echo "    hook + permissions → $CLAUDE_DIR/settings.json (backup: settings.json.bak)"
echo "    task board: $KIT/tasks"
echo "    knowledge:  $KIT/knowledge (the Tech Lead's memory of each service)"
echo
echo "Use it: cd into the folder that holds your projects, then"
echo "    claude --agent techlead   |   claude --agent dev   |   claude --agent reviewer"
