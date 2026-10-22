#!/usr/bin/env python3
"""One-time upgrades of the board and console data. Safe to run any number of times.

Run by install.sh and console/start.sh.
- The "pm" role became "techlead" (Tech Lead): task fields, inboxes, console agents and history.
- Per-project conventions notes (tasks/conventions/) moved into the knowledge files (knowledge/).
"""
import json
import re
from pathlib import Path

from tasklib import INBOX, KNOWLEDGE, ROOT, parse, task_files

DATA = ROOT / "console" / "data"


def renamed(agent_id: str) -> str:
    """pm -> techlead, pm-2 -> techlead-2; anything else unchanged."""
    return re.sub(r"^pm(?=-\d+$|$)", "techlead", agent_id)


def read(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def tasks() -> int:
    count = 0
    for path in task_files():
        text = path.read_text(encoding="utf-8")
        front, sep, body = text.partition("\n---")
        new = re.sub(r"^pm:( *)(\S*)", lambda m: f"techlead:{m.group(1)}{renamed(m.group(2))}", front, count=1, flags=re.M)
        if new != front:
            path.write_text(new + sep + body, encoding="utf-8")
            count += 1
    return count


def inboxes() -> None:
    old = INBOX / "pm.md"
    if old.exists():
        with (INBOX / "techlead.md").open("a", encoding="utf-8") as f:
            f.write(old.read_text(encoding="utf-8"))
        old.unlink()
    for path in (INBOX / "agents").glob("pm*.md") if (INBOX / "agents").exists() else []:
        target = path.with_name(renamed(path.stem) + ".md")
        if target != path:
            path.rename(target)
    marks = read(INBOX / ".read.json")
    if marks and any(renamed(k) != k for k in marks):
        write(INBOX / ".read.json", {renamed(k): v for k, v in marks.items()})


def console() -> None:
    settings = read(DATA / "settings.json")
    if settings and any(renamed(k) != k for k in settings.get("agents", {})):
        settings["agents"] = {renamed(k): {**v, "role": "techlead" if v.get("role") == "pm" else v.get("role")}
                              for k, v in settings["agents"].items()}
        settings["permission_mode"] = {renamed(k): v for k, v in settings.get("permission_mode", {}).items()}
        write(DATA / "settings.json", settings)
        (DATA / "settings.json").chmod(0o600)
    index = read(DATA / "sessions" / "index.json")
    if index and any(r.get("role") == "pm" or renamed(r.get("agent", "")) != r.get("agent") for r in index.values()):
        for row in index.values():
            row["agent"] = renamed(row.get("agent", ""))
            if row.get("role") == "pm":
                row["role"] = "techlead"
        write(DATA / "sessions" / "index.json", index)


def conventions() -> None:
    old = ROOT / "tasks" / "conventions"
    if not old.exists():
        return
    projects = {Path(m.get("project", "")).name: m.get("project", "") for m in map(parse, task_files())}
    template = (ROOT / "templates" / "KNOWLEDGE.md").read_text(encoding="utf-8")
    for notes in old.glob("*.md"):
        target = KNOWLEDGE / notes.name
        if not target.exists():
            body = re.sub(r"<!--.*?-->", "", notes.read_text(encoding="utf-8"), flags=re.S)
            body = re.sub(r"^# .*\n", "", body, count=1).strip()   # drop the old title
            body = re.sub(r"^## ", "### ", body, flags=re.M)
            text = template.replace("SERVICE_NAME", notes.stem).replace("PROJECT_PATH", projects.get(notes.stem, ""))
            text = re.sub(r"(## Conventions and commands\n<!--.*?-->\n)Not explored yet\.", lambda m: m.group(1) + body,
                          text, count=1, flags=re.S)
            KNOWLEDGE.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
        notes.unlink()
    if not any(old.iterdir()):
        old.rmdir()


def main() -> None:
    changed = tasks()
    inboxes()
    console()
    conventions()
    if changed:
        print(f"Upgraded {changed} task file(s): the PM is now the Tech Lead (`techlead:`).")


if __name__ == "__main__":
    main()
