"""Read-only views over the kit's task board: tasks, inboxes, activity."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

from .store import KIT

sys.path.insert(0, str(KIT / "scripts"))
from tasklib import INBOX, ORDER, ROUTING, TASKS, parse, project_name, task_files  # noqa: E402

ROLES = ("pm", "dev", "reviewer", "lead")
_NOTE = re.compile(r"^- \[(?P<ts>[^\]]+)\] \*\*(?P<id>[^*]+)\*\* (?:\[(?P<project>[^\]]+)\] )?"
                   r"(?P<title>.*?) → `(?P<to>[^`]+)` \(was `(?P<frm>[^`]+)`\)")


def _summary(path: Path) -> dict:
    meta = parse(path)
    text = path.read_text(encoding="utf-8")
    dor = re.search(r"## Definition of Ready(.*?)(\n## |\n---)", text, re.S)
    ticks = re.findall(r"^\s*- \[([ xX])\]", dor.group(1), re.M) if dor else []
    return {
        "id": meta.get("id", path.stem), "file": path.name,
        "title": meta.get("title", ""), "status": meta.get("status", ""),
        "priority": meta.get("priority", ""), "project": meta.get("project", ""),
        "project_name": project_name(meta), "base": meta.get("base", ""),
        "branch": meta.get("branch", ""), "created": meta.get("created", ""),
        "approved": meta.get("approved", ""),
        "updated": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        "owner": ROUTING.get(meta.get("status", ""), _owner(meta.get("status", ""))),
        "ready": {"done": sum(t != " " for t in ticks), "total": len(ticks)},
    }


def _owner(status: str) -> str:
    return {"draft": "pm", "in-dev": "dev", "in-review": "reviewer"}.get(status, "lead")


def list_tasks() -> list[dict]:
    return sorted((_summary(p) for p in task_files()), key=lambda t: t["id"], reverse=True)


def get_task(task_id: str) -> dict | None:
    for path in task_files():
        if path.name.startswith(f"{task_id}-") or path.stem == task_id:
            text = path.read_text(encoding="utf-8")
            body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
            body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
            return {**_summary(path), "markdown": body, "path": str(path),
                    "activity": [a for a in activity(1000) if a["id"] == task_id]}
    return None


def inbox(role: str) -> dict:
    note_file = INBOX / f"{role}.md"
    notes = []
    if note_file.exists():
        for line in note_file.read_text(encoding="utf-8").splitlines():
            m = _NOTE.match(line)
            if m:
                notes.append({k: (v or "") for k, v in m.groupdict().items()})
    wanted = {"pm": {"draft"}, "lead": {"blocked"}}.get(role) or {s for s, r in ROUTING.items() if r == role}
    waiting = [t for t in list_tasks() if t["status"] in wanted]
    return {"role": role, "notifications": list(reversed(notes)), "waiting": waiting}


def clear_inbox(role: str) -> None:
    note_file = INBOX / f"{role}.md"
    if note_file.exists():
        note_file.write_text("", encoding="utf-8")


def activity(limit: int = 50) -> list[dict]:
    path = INBOX / "activity.jsonl"
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    return [json.loads(line) for line in reversed(lines) if line.strip()]


def summary() -> dict:
    tasks = list_tasks()
    by_status = {s: 0 for s in ORDER}
    for t in tasks:
        by_status[t["status"]] = by_status.get(t["status"], 0) + 1
    unread = {r: len(inbox(r)["notifications"]) for r in ROLES}
    return {"by_status": by_status, "tasks": tasks, "unread": unread,
            "activity": activity(25), "projects": sorted({t["project_name"] for t in tasks})}


def signature() -> str:
    """Changes whenever a task or inbox file changes (used for live refresh)."""
    files = list(task_files()) + (list(INBOX.glob("*")) if INBOX.exists() else [])
    return "|".join(f"{p.name}:{p.stat().st_mtime_ns}" for p in sorted(files) if p.exists())
