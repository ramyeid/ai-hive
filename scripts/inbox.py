#!/usr/bin/env python3
"""Show what's waiting for a role, then clear its notifications.

Usage: python3 scripts/inbox.py pm|dev|reviewer|lead [--keep]
"""
import sys

from tasklib import INBOX, ROUTING, TASKS, parse, task_files


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in {"pm", "dev", "reviewer", "lead"}:
        sys.exit("usage: inbox.py pm|dev|reviewer|lead [--keep]")
    role, keep = sys.argv[1], "--keep" in sys.argv

    note_file = INBOX / f"{role}.md"
    notes = note_file.read_text(encoding="utf-8") if note_file.exists() else ""
    print(f"## New notifications for {role}\n")
    print(notes.strip() or "(none)")

    # Source of truth is the files themselves, not the notifications.
    wanted = {s for s, r in ROUTING.items() if r == role}
    if role == "pm":
        wanted = {"draft"}
    queue = [parse(p) for p in task_files()]
    queue = [t for t in queue if t.get("status") in wanted]
    print(f"\n## Tasks currently waiting on {role}\n")
    if not queue:
        print("(none)")
    for t in sorted(queue, key=lambda t: ("urgent high medium low".split().index(
            t.get("priority", "medium")) if t.get("priority") in
            "urgent high medium low".split() else 2, t["file"])):
        print(f"- {t.get('id')} [{t.get('priority', '?')}] `{t.get('status')}` "
              f"{t.get('title')}\n    task: {TASKS / t['file']}\n    project: {t.get('project')} (base `{t.get('base')}`)")

    if notes and not keep:
        note_file.write_text("", encoding="utf-8")


if __name__ == "__main__":
    main()
