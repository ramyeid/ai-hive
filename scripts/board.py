#!/usr/bin/env python3
"""Regenerate tasks/BOARD.md — a kanban-style overview for the lead.

Usage: python scripts/board.py   (also run automatically by the hook)
"""
import datetime as dt

from tasklib import ORDER, TASKS, holder, parse, project_name, task_files


def write_board() -> str:
    tasks = [parse(p) for p in task_files()]
    lines = ["# Task Board",
             f"_Generated {dt.datetime.now():%Y-%m-%d %H:%M} — do not edit by hand._", ""]
    statuses = ORDER + sorted({t.get("status", "?") for t in tasks} - set(ORDER))
    for status in statuses:
        group = [t for t in tasks if t.get("status") == status]
        if not group:
            continue
        lines.append(f"## {status} ({len(group)})")
        for t in group:
            who = holder(t)
            who = f"blocked by {who}" if who and status == "blocked" else who
            lines.append(f"- [{t.get('id')}]({t['file']}) **{project_name(t)}** · "
                         f"{t.get('title')} · {t.get('priority', '')}" + (f" · {who}" if who else ""))
        lines.append("")
    if not tasks:
        lines.append("_No tasks yet. Ask the techlead agent to create one._")
    text = "\n".join(lines) + "\n"
    (TASKS / "BOARD.md").write_text(text, encoding="utf-8")
    return text


if __name__ == "__main__":
    print(write_board())
