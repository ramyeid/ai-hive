#!/usr/bin/env bash
# Installs Hive's agents into Claude Code for every project on this machine.
# Safe to re-run after any update, or after moving the Hive folder.
set -euo pipefail

KIT="$(cd "$(dirname "$0")/.." && pwd)"
CLAUDE_DIR="$HOME/.claude"
mkdir -p "$CLAUDE_DIR/agents" "$KIT/data/tasks/.inbox" "$KIT/data/knowledge" "$KIT/data/coach/proposals"

# The agents, with this folder's absolute path filled in.
for f in "$KIT"/team/agents/*.md; do sed "s#{{KIT}}#$KIT#g" "$f" > "$CLAUDE_DIR/agents/$(basename "$f")"; done

# Earlier versions also installed the /board and /ship commands: remove ours (only if they're ours).
for name in board ship; do
  f="$CLAUDE_DIR/commands/$name.md"
  if [ -f "$f" ] && grep -q "scripts/board.py\|/TEAM.md" "$f"; then rm "$f"; fi
done

# Merge the task hook and permissions into ~/.claude/settings.json (keeps everything else).
python3 - "$KIT" "$CLAUDE_DIR/settings.json" <<'PY'
import json, re, shutil, sys
from pathlib import Path

kit, path = sys.argv[1], Path(sys.argv[2])
settings = json.loads(path.read_text()) if path.exists() else {}
if path.exists():
    shutil.copy(path, path.with_name("settings.json.bak"))


def another_hive(folder: str) -> bool:
    """A Hive folder other than this one (an older copy, or this one before it moved)."""
    folder = folder.rstrip("/")
    return folder != kit and any(Path(folder, f).exists() for f in ("TEAM.md", "team/TEAM.md"))


# Hook: replace any previous copy of ours, keep all other hooks.
post = settings.setdefault("hooks", {}).setdefault("PostToolUse", [])
post[:] = [g for g in post
           if not any("on_task_change.py" in h.get("command", "") for h in g.get("hooks", []))]
post.append({"matcher": "Write|Edit|MultiEdit",
             "hooks": [{"type": "command",
                        "command": f'python3 "{kit}/team/tools/on_task_change.py"'}]})

# Let the agents read Hive, edit task files and run the team's tools without prompting.
perms = settings.setdefault("permissions", {})
ours = re.compile(r"^(?:Edit\(/(?P<edit>.+?)/(?:data/)?(?:tasks|knowledge|coach)/\*\*\)|Bash\(python3 (?P<bash>.+?)/(?:scripts|team/tools)/\*\))$")
allow = [r for r in perms.get("allow", []) if not ((m := ours.match(r)) and another_hive(m["edit"] or m["bash"]))]
dirs = [d for d in perms.get("additionalDirectories", []) if not another_hive(d)]
if kit not in dirs:
    dirs.append(kit)
for rule in (f"Edit(/{kit}/data/tasks/**)", f"Edit(/{kit}/data/knowledge/**)", f"Edit(/{kit}/data/coach/**)",
             f"Bash(python3 {kit}/team/tools/*)"):
    if rule not in allow:
        allow.append(rule)
perms["allow"], perms["additionalDirectories"] = allow, dirs

path.write_text(json.dumps(settings, indent=2) + "\n")
PY

echo "✓ Hive installed for every project:"
echo "    agents: $(ls "$KIT"/team/agents | sed 's/\.md//' | tr '\n' ' ')→ $CLAUDE_DIR/agents"
echo "    hook + permissions → $CLAUDE_DIR/settings.json (backup: settings.json.bak)"
echo "    your data: $KIT/data"
echo
echo "Start the console: bash $KIT/scripts/start.sh"
