"""Shared helpers for the task board. Standard library only."""
from __future__ import annotations

import fcntl
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"
INBOX = TASKS / ".inbox"
STATE = INBOX / ".state.json"

# Which role gets pinged when a task enters a status.
ROUTING = {
    "ready-for-dev": "dev",
    "changes-requested": "dev",
    "ready-for-review": "reviewer",
    "blocked": "lead",
    "done": "lead",
}

ORDER = ["blocked", "draft", "ready-for-dev", "in-dev", "changes-requested",
         "ready-for-review", "in-review", "done"]

_FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def parse(path: Path) -> dict:
    """Return the front-matter fields of a task file as a dict."""
    m = _FM.match(path.read_text(encoding="utf-8"))
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.split("#", 1)[0].strip()
    meta["file"] = path.name
    return meta


def project_name(meta: dict) -> str:
    return Path(meta.get("project", "?")).name


def task_files() -> list[Path]:
    return sorted(TASKS.glob("TASK-*.md"))


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


ROLES = ("pm", "dev", "reviewer")


def role_of(agent_id: str) -> str:
    """dev-2 -> dev. Agent IDs are a role, optionally followed by -N."""
    return agent_id.split("-")[0]


def agent_id(role: str) -> str:
    """This agent's ID: $AGENT_ID if it belongs to the role (set by the console, or by you in
    a terminal: AGENT_ID=dev-2 claude --agent dev), otherwise just the role name."""
    env = os.environ.get("AGENT_ID", "")
    return env if env and role_of(env) == role else role


@contextmanager
def lock():
    """One writer at a time on the board, across agents and processes."""
    TASKS.mkdir(parents=True, exist_ok=True)
    with open(TASKS / ".lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def find_task(task_id: str) -> Path | None:
    return next((p for p in task_files() if p.name.startswith(f"{task_id}-")), None)


def set_fields(path: Path, **fields: str) -> None:
    """Set front-matter values, keeping comments; add fields that are missing."""
    text = path.read_text(encoding="utf-8")
    m = _FM.match(text)
    lines = m.group(1).splitlines()
    for key, value in fields.items():
        for i, line in enumerate(lines):
            if re.match(rf"^{key}\s*:", line):
                comment = line.split("#", 1)[1] if "#" in line else ""
                lines[i] = f"{key}: {value}" + (f"        #{comment}" if comment else "")
                break
        else:
            lines.append(f"{key}: {value}")
    path.write_text(f"---\n" + "\n".join(lines) + "\n---" + text[m.end():], encoding="utf-8")
