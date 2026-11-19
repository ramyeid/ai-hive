#!/usr/bin/env python3
"""Keep a task's ClickUp ticket or Jira issue up to date as the task moves.

A task's `ticket:` field names the ticket it came from (a ClickUp link or ID, a Jira key or link). When the task's
status changes, on_task_change.py starts this in the background:

    python3 tickets.py sync <task file> <previous status> <new status>

It comments on the ticket ("TASK-012 is now Ready for review", with a link to it in the console) and, if the lead
set it up in Settings → Integrations, moves the ticket to the matching status. Failures go to
data/tasks/.inbox/tickets.log and never reach the agent.

    python3 tickets.py which <ticket>       which app a ticket belongs to (clickup | jira)
Standard library only.
"""
from __future__ import annotations

import datetime as dt
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connlib import ConnectorError, config, settings  # noqa: E402
from tasklib import INBOX, parse  # noqa: E402

LABELS = {"draft": "in draft", "ready-for-dev": "ready for a developer", "in-dev": "being built",
          "ready-for-review": "ready for review", "in-review": "in review", "changes-requested": "back with the developer for changes",
          "blocked": "blocked, waiting on an answer", "done": "done"}
LOG = INBOX / "tickets.log"


def connected(cid: str) -> bool:
    cfg = config(cid)
    return bool(cfg.get("token")) and (cid != "jira" or bool(cfg.get("site") and cfg.get("email")))


def which(ticket: str) -> str:
    t = ticket.strip()
    if "clickup.com" in t or re.match(r"^(#|CU-)", t, re.I):
        return "clickup"
    if "atlassian.net" in t or "/browse/" in t:
        return "jira"
    if re.fullmatch(r"[A-Z][A-Z0-9_]+-\d+", t):   # ABC-123: Jira, unless only ClickUp (custom IDs) is connected
        return "clickup" if connected("clickup") and not connected("jira") else "jira"
    return "clickup"


def log(line: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{dt.datetime.now().isoformat(timespec='seconds')} {line}\n")


def sync(path: Path, previous: str, status: str) -> None:
    meta = parse(path)
    ticket = (meta.get("ticket") or "").strip()
    if not ticket or ticket.lower() in ("none", "-"):
        return
    app = which(ticket)
    if not connected(app):
        return
    cfg = config(app)
    options = cfg.get("options") or {}
    tid = meta.get("id", path.stem)
    url = (settings().get("console_url") or "").rstrip("/")
    text = f"Hive: {tid} \"{meta.get('title', '')}\" is now {LABELS.get(status, status)}."
    if url:
        text += f" {url}/#/tasks/{tid}"
    import clickup, jira   # noqa: E401
    mod = clickup if app == "clickup" else jira
    try:
        if options.get("comment", True):
            mod.comment(ticket, text)
        target = (options.get("move") or {}).get(status, "").strip()
        if target:
            mod.move(ticket, target)
        log(f"{tid} {previous}→{status}: {app} {ticket} updated" + (f", moved to {target}" if target else ""))
    except ConnectorError as e:
        log(f"{tid} {previous}→{status}: {app} {ticket} FAILED: {e}")


def main(argv: list[str]) -> int:
    if len(argv) == 4 and argv[0] == "sync":
        try:
            sync(Path(argv[1]), argv[2], argv[3])
        except Exception as e:  # noqa: BLE001 (never matters to the agent)
            log(f"{argv[1]}: FAILED: {e}")
        return 0
    if len(argv) == 2 and argv[0] == "which":
        print(which(argv[1]))
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
