"""Session history and console settings, stored as plain files in console/data/."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path

CONSOLE = Path(__file__).resolve().parent.parent
KIT = CONSOLE.parent
DATA = CONSOLE / "data"
SESSIONS = DATA / "sessions"
INDEX = SESSIONS / "index.json"
SETTINGS = DATA / "settings.json"

DEFAULT_SETTINGS = {
    "workspace": str(Path.home()),
    "permission_mode": {"pm": "default", "dev": "default", "reviewer": "default"},
}


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(path)


# ---- settings ---------------------------------------------------------------

def load_settings() -> dict:
    saved = _read_json(SETTINGS, {})
    settings = {**DEFAULT_SETTINGS, **saved}
    settings["permission_mode"] = {**DEFAULT_SETTINGS["permission_mode"],
                                   **saved.get("permission_mode", {})}
    return settings


def save_settings(changes: dict) -> dict:
    settings = load_settings()
    if "workspace" in changes:
        folder = Path(changes["workspace"]).expanduser()
        if not folder.is_dir():
            raise ValueError(f"Folder not found: {folder}")
        settings["workspace"] = str(folder)
    for agent, mode in changes.get("permission_mode", {}).items():
        if mode not in ("default", "acceptEdits"):
            raise ValueError(f"Unknown permission mode: {mode}")
        settings["permission_mode"][agent] = mode
    _write_json(SETTINGS, settings)
    return settings


# ---- sessions ---------------------------------------------------------------

def list_sessions(agent: str | None = None) -> list[dict]:
    index = _read_json(INDEX, {})
    rows = [{"id": sid, **meta} for sid, meta in index.items()]
    if agent:
        rows = [r for r in rows if r["agent"] == agent]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def get_session(session_id: str) -> dict | None:
    return _read_json(INDEX, {}).get(session_id)


def new_session(agent: str) -> str:
    session_id = uuid.uuid4().hex[:12]
    _update_index(session_id, {"agent": agent, "started": now(), "updated": now(),
                               "title": "", "claude_session_id": None,
                               "cost_usd": 0.0, "turns": 0})
    return session_id


def _update_index(session_id: str, changes: dict) -> None:
    index = _read_json(INDEX, {})
    index[session_id] = {**index.get(session_id, {}), **changes}
    _write_json(INDEX, index)


def append_event(session_id: str, event: dict) -> None:
    SESSIONS.mkdir(parents=True, exist_ok=True)
    with (SESSIONS / f"{session_id}.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")

    meta = get_session(session_id) or {}
    changes = {"updated": event["ts"]}
    if event["kind"] == "user" and not meta.get("title"):
        changes["title"] = event["text"][:120]
    if event["kind"] == "result":
        changes["cost_usd"] = round(meta.get("cost_usd", 0) + (event.get("cost_usd") or 0), 4)
        changes["turns"] = meta.get("turns", 0) + (event.get("turns") or 0)
    if event.get("claude_session_id"):
        changes["claude_session_id"] = event["claude_session_id"]
    _update_index(session_id, changes)


def read_events(session_id: str) -> list[dict]:
    path = SESSIONS / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
