#!/usr/bin/env python3
"""Show what's waiting for this agent (or the lead), and mark notifications as read.

Usage: python3 scripts/inbox.py pm|dev|reviewer|lead [--keep]

The agent's ID comes from $AGENT_ID (e.g. dev-2), defaulting to the role name. It sees:
- its own notifications (rework and re-reviews sent back to it): .inbox/agents/<id>.md
- new lines in its role's shared pool (new work any agent of the role can claim): .inbox/<role>.md
- the tasks it can pick up: unclaimed ones, plus those already assigned to it.
"""
import json
import sys

from tasklib import INBOX, ROLES, ROUTING, TASKS, agent_id, parse, task_files

AGENT_INBOXES = INBOX / "agents"
READ = INBOX / ".read.json"   # how far each agent has read its role's shared pool
PRIORITY = "urgent high medium low".split()


def unread_pool(role: str, me: str, keep: bool) -> str:
    """Pool lines this agent hasn't seen. The pool is shared, so it's never cleared by an agent."""
    pool = INBOX / f"{role}.md"
    text = pool.read_text(encoding="utf-8") if pool.exists() else ""
    try:
        marks = json.loads(READ.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        marks = {}
    seen = marks.get(me, 0)
    if seen > len(text):          # the lead cleared the pool since: start over
        seen = 0
    if not keep:
        marks[me] = len(text)
        READ.write_text(json.dumps(marks, indent=2))
    return text[seen:]


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in (*ROLES, "lead"):
        sys.exit("usage: inbox.py pm|dev|reviewer|lead [--keep]")
    role, keep = sys.argv[1], "--keep" in sys.argv
    INBOX.mkdir(parents=True, exist_ok=True)

    if role == "lead":
        me, own_file = "lead", INBOX / "lead.md"
        pool = ""
    else:
        me, own_file = agent_id(role), AGENT_INBOXES / f"{agent_id(role)}.md"
        pool = unread_pool(role, me, keep)
    own = own_file.read_text(encoding="utf-8") if own_file.exists() else ""
    print(f"## New notifications for {me}\n")
    print((own + pool).strip() or "(none)")
    if own and not keep:
        own_file.write_text("", encoding="utf-8")

    # Source of truth is the task files, not the notifications.
    wanted = {"pm": {"draft"}, "lead": {"blocked"}}.get(role) or {s for s, r in ROUTING.items() if r == role}
    queue = [t for t in (parse(p) for p in task_files())
             if t.get("status") in wanted and (role == "lead" or t.get(role, "") in ("", me))]
    print(f"\n## Tasks you can take ({me})\n")
    if not queue:
        print("(none)")
    for t in sorted(queue, key=lambda t: (PRIORITY.index(t.get("priority")) if t.get("priority") in PRIORITY else 2, t["file"])):
        mine = " (yours)" if role != "lead" and t.get(role) == me else ""
        print(f"- {t.get('id')} [{t.get('priority', '?')}] `{t.get('status')}`{mine} {t.get('title')}\n"
              f"    task: {TASKS / t['file']}\n    project: {t.get('project')} (base `{t.get('base')}`)")


if __name__ == "__main__":
    main()
