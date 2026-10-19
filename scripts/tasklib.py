"""Shared helpers for the task board. Standard library only."""
from __future__ import annotations

import json
import re
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
