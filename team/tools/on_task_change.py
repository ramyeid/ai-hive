#!/usr/bin/env python3
"""Claude Code PostToolUse hook: notify the next agent when a task's status changes.

Wired up in .claude/settings.json for Write|Edit|MultiEdit. Reads the hook
payload from stdin, and if the edited file is a task whose status changed:
  * appends a line to data/tasks/.inbox/<role>.md (shared pool), or .inbox/agents/<id>.md for rework
    and re-reviews, which go back to the same dev / reviewer
  * fires a desktop notification (macOS / Linux) if available
  * regenerates data/tasks/BOARD.md
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

import os

from tasklib import HOLDER, INBOX, ROUTING, TASKS, holder, load_state, parse, project_name, save_state, set_fields
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


def log_activity(meta: dict, previous: str | None, status: str, actor: str | None = None) -> None:
    """Permanent record of every status change (the inbox files get cleared)."""
    INBOX.mkdir(parents=True, exist_ok=True)
    entry = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "id": meta.get("id"),
             "title": meta.get("title"), "project": project_name(meta),
             "from": previous, "to": status, "by": holder(meta),
             # the agent whose edit made the change ("lead" from the console's code review; "" = the lead or a terminal)
             "actor": os.environ.get("AGENT_ID", "") if actor is None else actor}
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


def _git(folder: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=30)


def uncommitted(meta: dict) -> list[str]:
    """What stops a task from being reviewed: files left uncommitted in its worktree, or no commits since it started.
    Empty when it can't tell (no folder, not a git repository)."""
    branch, start = meta.get("branch", ""), meta.get("from_commit", "")
    folder = meta.get("worktree", "") or meta.get("project", "")
    if not branch or not folder or not Path(folder).is_dir():
        return []
    problems = []
    on = _git(folder, "rev-parse", "--abbrev-ref", "HEAD")
    if on.returncode == 0 and on.stdout.strip() == branch:
        dirty = [l[3:] for l in _git(folder, "status", "--porcelain").stdout.splitlines() if l.strip()]
        if dirty:
            shown = ", ".join(dirty[:5]) + (f" and {len(dirty) - 5} more" if len(dirty) > 5 else "")
            problems.append(f"{len(dirty)} file{'s are' if len(dirty) != 1 else ' is'} changed but not committed in {folder}: {shown}.")
    if start:
        count = _git(folder, "rev-list", "--count", f"{start}..{branch}")
        if count.returncode == 0 and count.stdout.strip() == "0":
            problems.append(f"The branch {branch} has no commits since this task started ({start[:7]}).")
    return problems


def process(path: Path, actor: str | None = None) -> int:
    """Handle a task file that may have changed status. Returns 2 if the change was refused.
    actor: who made the change, when it isn't $AGENT_ID (the console passes "lead" for the lead's review)."""
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

    # Nothing reaches review that the lead can't see: the work must be committed on the task's branch.
    if status == "ready-for-review" and actor != "lead":
        problems = uncommitted(meta)
        if problems:
            back = previous if previous in ("in-dev", "changes-requested") else "in-dev"
            text = path.read_text(encoding="utf-8")
            path.write_text(re.sub(r"^status:\s*ready-for-review", f"status: {back}", text, count=1, flags=re.M), encoding="utf-8")
            print(f"BLOCKED: {tid} was put back to `{back}`: there's nothing for the reviewer or the lead to see yet.\n"
                  + "\n".join(f"  - {p}" for p in problems)
                  + "\nCommit your work (with the task's trailers), then set `ready-for-review` again. If this task needed "
                    "no code change, set it to `blocked` and tell the lead why.", file=sys.stderr)
            return 2

    # Record who blocked it: the agent that made the change, else whoever held the task before.
    if status == "blocked":
        by = (actor if actor is not None else os.environ.get("AGENT_ID")) or meta.get(HOLDER.get(previous or "", ""), "")
        if by != meta.get("blocked_by", ""):
            set_fields(path, blocked_by=by)
            meta = parse(path)
    elif meta.get("blocked_by"):
        set_fields(path, blocked_by="")
        meta = parse(path)

    state[tid] = status
    save_state(state)
    log_activity(meta, previous, status, actor)
    if (meta.get("ticket") or "").strip():   # its ClickUp ticket / Jira issue hears about it, in the background
        try:
            subprocess.Popen([sys.executable, str(Path(__file__).with_name("tickets.py")), "sync", str(path),
                              previous or "new", status], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError:
            pass

    to = recipient(meta, status)
    if status == "cancelled":   # whoever had it stops: tell them, nobody else
        had = meta.get(HOLDER.get(previous or "", ""), "")
        to = "@" + had if had else None
    if to:
        # A role name means its shared pool (.inbox/dev.md); an agent ID its own inbox.
        target = INBOX / "agents" / f"{to[1:]}.md" if to.startswith("@") else INBOX / f"{to}.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
        who = holder(meta)
        by = f" by {who}" if who and status == "blocked" else f" ({who})" if who else ""
        line = (f"- [{stamp}] **{tid}** [{project_name(meta)}] {meta.get('title', '')} → `{status}`"
                f" (was `{previous or 'new'}`){by} — {path}\n")
        with target.open("a", encoding="utf-8") as f:
            f.write(line)
        desktop_notify(f"{to.lstrip('@').upper()}: {tid} [{project_name(meta)}]", f"{meta.get('title', '')} → {status}{by}")

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
