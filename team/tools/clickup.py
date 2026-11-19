#!/usr/bin/env python3
"""ClickUp: read a ticket, comment on it, move it.

    python3 clickup.py task <ticket>                  the ticket: title, status, description, checklists,
                                                     subtasks, attachments and comments
    python3 clickup.py attachments <ticket>           download its attachments to data/uploads/clickup-<id>/
                                                     (read them with files.py)
    python3 clickup.py comment <ticket> "<text>"      add a comment (Markdown is fine)
    python3 clickup.py status <ticket> ["<status>"]   move it to a status; without one, list the statuses it can take
    python3 clickup.py whoami                         check the connection

A ticket is its link (https://app.clickup.com/t/86c2xk1ab), its ID (86c2xk1ab, #86c2xk1ab, CU-86c2xk1ab) or a
custom ID (ENG-42, with the link that has the workspace ID in it). Put it in the task's `ticket:` field and Hive
comments on it (and moves it, if the lead turned that on) as the task moves. Needs ClickUp connected in Settings →
Integrations. Standard library only.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connlib import ConnectorError, quote, request, require, run  # noqa: E402

API = "https://api.clickup.com/api/v2"


def parse(ticket: str) -> tuple[str, str]:
    """(task id, query string for custom IDs) from a link or an ID."""
    ticket = ticket.strip()
    m = re.search(r"app\.clickup\.com/t/(?:(\d+)/)?([A-Za-z0-9_-]+)", ticket)
    if m:
        team, tid = m.group(1), m.group(2)
        return (tid, f"?custom_task_ids=true&team_id={team}") if team else (tid, "")
    tid = re.sub(r"^(#|CU-)", "", ticket, flags=re.I)
    if not re.fullmatch(r"[A-Za-z0-9_-]+", tid):
        raise ConnectorError(f"Not a ClickUp ticket: {ticket}. Use its link or ID.")
    return tid, ""


def call(method: str, path: str, body=None, what: str = "ClickUp"):
    cfg = require("clickup")
    return request(method, f"{API}{path}", {"Authorization": cfg["token"]}, body, what=what)


def when(ms) -> str:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return ""


def get_task(ticket: str) -> tuple[dict, str, str]:
    tid, q = parse(ticket)
    sep = "&" if q else "?"
    task = call("GET", f"/task/{quote(tid)}{q}{sep}include_subtasks=true&include_markdown_description=true",
                what=f"ClickUp ticket {ticket}")
    return task, task.get("id", tid), ""


def cmd_task(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: clickup.py task <ticket>")
    t, tid, _ = get_task(args[0])
    people = ", ".join(a.get("username") or a.get("email", "") for a in t.get("assignees") or [])
    print(f"# {t.get('name')}  ({t.get('custom_id') or t.get('id')})")
    print(f"Status: {(t.get('status') or {}).get('status', '')} · List: {(t.get('list') or {}).get('name', '')}"
          f" · Priority: {((t.get('priority') or {}) or {}).get('priority', 'none')}"
          + (f" · Assignees: {people}" if people else "") + (f" · Due: {when(t.get('due_date'))}" if t.get("due_date") else ""))
    print(f"Link: {t.get('url')}")
    tags = ", ".join(x.get("name", "") for x in t.get("tags") or [])
    if tags:
        print(f"Tags: {tags}")
    for f in t.get("custom_fields") or []:
        if f.get("value") not in (None, "", []):
            print(f"{f.get('name')}: {f.get('value')}")
    print("\n## Description\n")
    print((t.get("markdown_description") or t.get("text_content") or t.get("description") or "(none)").strip())
    for cl in t.get("checklists") or []:
        print(f"\n## Checklist: {cl.get('name')}")
        for item in cl.get("items") or []:
            print(f"- [{'x' if item.get('resolved') else ' '}] {item.get('name')}")
    if t.get("subtasks"):
        print("\n## Subtasks")
        for s in t["subtasks"]:
            print(f"- {s.get('name')} ({(s.get('status') or {}).get('status', '')}) {s.get('url', '')}")
    if t.get("attachments"):
        print("\n## Attachments (download them with: clickup.py attachments " + tid + ")")
        for a in t["attachments"]:
            print(f"- {a.get('title')} {a.get('url', '')}")
    comments = call("GET", f"/task/{quote(tid)}/comment", what="ClickUp comments").get("comments") or []
    if comments:
        print("\n## Comments (oldest first)")
        for c in reversed(comments):
            who = (c.get("user") or {}).get("username", "")
            print(f"\n**{who}**, {when(c.get('date'))}:\n{(c.get('comment_text') or '').strip()}")
    return 0


def cmd_attachments(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: clickup.py attachments <ticket>")
    from tasklib import DATA
    t, tid, _ = get_task(args[0])
    files = t.get("attachments") or []
    if not files:
        print("This ticket has no attachments.")
        return 0
    folder = DATA / "uploads" / f"clickup-{tid}"
    folder.mkdir(parents=True, exist_ok=True)
    for a in files:
        name = re.sub(r"[^\w.\- ]+", "_", a.get("title") or a.get("id", "file"))
        data = request("GET", a["url"], raw=True, what=f"attachment {name}")
        (folder / name).write_bytes(data)
        print(folder / name)
    return 0


def cmd_comment(args: list[str]) -> int:
    if len(args) < 2:
        raise ConnectorError('Usage: clickup.py comment <ticket> "<text>"')
    _, tid, _ = get_task(args[0])
    call("POST", f"/task/{quote(tid)}/comment", {"comment_text": args[1], "notify_all": False}, "ClickUp comment")
    print("Comment added.")
    return 0


def statuses(task: dict) -> list[str]:
    lid = (task.get("list") or {}).get("id")
    lst = call("GET", f"/list/{lid}", what="ClickUp list") if lid else {}
    return [s.get("status", "") for s in lst.get("statuses") or []]


def move(ticket: str, status: str) -> str:
    t, tid, _ = get_task(ticket)
    names = statuses(t)
    match = next((s for s in names if s.lower() == status.lower()), None)
    if not match:
        raise ConnectorError(f"ClickUp has no status {status!r} in this ticket's list. It can be: " + ", ".join(names))
    call("PUT", f"/task/{quote(tid)}", {"status": match}, "ClickUp status")
    return match


def cmd_status(args: list[str]) -> int:
    if not args:
        raise ConnectorError('Usage: clickup.py status <ticket> ["<status>"]')
    if len(args) == 1:
        t, _, _ = get_task(args[0])
        print(f"Now: {(t.get('status') or {}).get('status', '')}\nIt can be: " + ", ".join(statuses(t)))
        return 0
    print(f"Moved to {move(args[0], args[1])}.")
    return 0


def cmd_whoami(_args: list[str]) -> int:
    u = call("GET", "/user").get("user") or {}
    teams = call("GET", "/team").get("teams") or []
    print(f"Connected as {u.get('username', '')} ({u.get('email', '')})"
          + (f" · workspaces: {', '.join(t.get('name', '') for t in teams)}" if teams else ""))
    return 0


def comment(ticket: str, text: str) -> None:
    """For the task sync (tickets.py)."""
    _, tid, _ = get_task(ticket)
    call("POST", f"/task/{quote(tid)}/comment", {"comment_text": text, "notify_all": False}, "ClickUp comment")


def main(argv: list[str]) -> int:
    commands = {"task": cmd_task, "attachments": cmd_attachments, "comment": cmd_comment, "status": cmd_status,
                "whoami": cmd_whoami}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 0 if not argv else 1
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    run(main)
