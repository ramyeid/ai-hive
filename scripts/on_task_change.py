#!/usr/bin/env python3
"""Claude Code PostToolUse hook: notify the next agent when a task's status changes.

Wired up in .claude/settings.json for Write|Edit|MultiEdit. Reads the hook
payload from stdin, and if the edited file is a task whose status changed:
  * appends a line to tasks/.inbox/<role>.md (shared pool), or .inbox/agents/<id>.md for rework
    and re-reviews, which go back to the same dev / reviewer
  * fires a desktop notification (macOS / Linux) if available
  * regenerates tasks/BOARD.md
Never blocks the agent: always exits 0.
"""
from __future__ import annotations

import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tasklib import INBOX, ROUTING, TASKS, load_state, parse, project_name, save_state
import board
import check_ready


def desktop_notify(title: str, msg: str) -> None:
    try:
        if shutil.which("osascript"):
            subprocess.run(["osascript", "-e",
                            f'display notification "{msg}" with title "{title}"'],
                           timeout=5, check=False)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", title, msg], timeout=5, check=False)
    except Exception:
        pass


def log_activity(meta: dict, previous: str | None, status: str) -> None:
    """Permanent record of every status change (the inbox files get cleared)."""
    INBOX.mkdir(parents=True, exist_ok=True)
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "id": meta.get("id"),
             "title": meta.get("title"), "project": project_name(meta),
             "from": previous, "to": status}
    with (INBOX / "activity.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def recipient(meta: dict, status: str) -> str | None:
    """Who gets notified: rework goes back to the dev who built it, a re-review to the same
    reviewer; new work goes to the role's shared pool (any dev / any reviewer can claim it)."""
    if status == "changes-requested" and meta.get("dev"):
        return "@" + meta["dev"]
    if status == "ready-for-review" and meta.get("reviewer"):
        return "@" + meta["reviewer"]
    return ROUTING.get(status)


def process(path: Path) -> int:
    """Handle a task file that may have changed status. Returns 2 if the change was refused."""
    meta = parse(path)
    tid, status = meta.get("id", path.stem), meta.get("status", "")
    state = load_state()
    previous = state.get(tid)
    if status == previous:
        return 0

    # Definition-of-Ready gate: nothing reaches dev with open questions.
    if status == "ready-for-dev":
        problems = check_ready.check(path)
        if problems:
            text = path.read_text(encoding="utf-8")
            path.write_text(re.sub(r"^status:\s*ready-for-dev", "status: draft",
                                   text, count=1, flags=re.M), encoding="utf-8")
            state[tid] = "draft"
            save_state(state)
            print(f"BLOCKED: {tid} was put back to `draft` — it does not meet the "
                  "Definition of Ready. Resolve these with the lead, then try again:\n"
                  + "\n".join(f"  - {p}" for p in problems), file=sys.stderr)
            return 2

    state[tid] = status
    save_state(state)
    log_activity(meta, previous, status)

    to = recipient(meta, status)
    if to:
        # A role name means its shared pool (.inbox/dev.md); an agent ID its own inbox.
        target = INBOX / "agents" / f"{to[1:]}.md" if to.startswith("@") else INBOX / f"{to}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        line = (f"- [{stamp}] **{tid}** [{project_name(meta)}] {meta.get('title', '')} → `{status}`"
                f" (was `{previous or 'new'}`) — {path}\n")
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
        desktop_notify(f"{to.lstrip('@').upper()}: {tid} [{project_name(meta)}]", f"{meta.get('title', '')} → {status}")

    board.write_board()
    return 0


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    fp = (payload.get("tool_input") or {}).get("file_path", "")
    path = Path(fp).resolve() if fp else None
    if not path or path.parent != TASKS or not path.name.startswith("TASK-") or not path.exists():
        return 0
    return process(path)


if __name__ == "__main__":
    code = 0
    try:
        code = main() or 0
    except Exception as e:  # never break the agent's turn
        print(f"on_task_change: {e}", file=sys.stderr)
    sys.exit(code)  # 2 = feed the stderr message back to the agent
