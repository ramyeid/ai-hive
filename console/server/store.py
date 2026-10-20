"""Session history and console settings, stored as plain files in console/data/."""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime
from pathlib import Path

CONSOLE = Path(__file__).resolve().parent.parent
KIT = CONSOLE.parent
DATA = CONSOLE / "data"
SESSIONS = DATA / "sessions"
INDEX = SESSIONS / "index.json"
SETTINGS = DATA / "settings.json"

AGENT_NAMES = ("pm", "dev", "reviewer")
DEFAULT_SETTINGS = {
    "workspace": str(Path.home()),
    "permission_mode": {name: "default" for name in AGENT_NAMES},
    "agents": {name: {"provider": "claude", "model": ""} for name in AGENT_NAMES},
    "providers": {},   # id -> {"api_key": ..., "base_url": ...}; never sent to the browser
    "prices": {},      # model -> {"input": US$ per 1M tokens, "output": US$ per 1M tokens}
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
    os.chmod(tmp, 0o600)   # settings can hold API keys
    tmp.replace(path)


# ---- settings ---------------------------------------------------------------

def load_settings() -> dict:
    saved = _read_json(SETTINGS, {})
    settings = {**DEFAULT_SETTINGS, **saved}
    settings["permission_mode"] = {**DEFAULT_SETTINGS["permission_mode"],
                                   **saved.get("permission_mode", {})}
    settings["agents"] = {name: {**DEFAULT_SETTINGS["agents"][name], **saved.get("agents", {}).get(name, {})}
                          for name in AGENT_NAMES}
    settings["providers"] = saved.get("providers", {})
    settings["prices"] = saved.get("prices", {})
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
    for agent, choice in changes.get("agents", {}).items():
        settings["agents"][agent] = {"provider": choice["provider"], "model": choice.get("model", "").strip()}
    for model, price in changes.get("prices", {}).items():
        if price is None:
            settings["prices"].pop(model, None)
        else:
            settings["prices"][model] = {"input": float(price["input"]), "output": float(price["output"])}
    for pid, values in changes.get("providers", {}).items():
        current = settings["providers"].setdefault(pid, {})
        for field in ("api_key", "base_url"):
            if values.get(field) is not None:      # "" clears, None leaves unchanged
                current[field] = values[field].strip()
    _write_json(SETTINGS, settings)
    return settings


def provider_credentials(provider) -> tuple[str, str, bool]:
    """(api_key, base_url, key_from_env) for a provider; the environment wins over saved keys."""
    saved = load_settings()["providers"].get(provider.id, {})
    env_key = os.environ.get(provider.key_env, "") if provider.key_env else ""
    return env_key or saved.get("api_key", ""), saved.get("base_url") or provider.base_url, bool(env_key)


def public_providers(providers: dict) -> list[dict]:
    """What the browser may see about each provider: never the key itself."""
    rows = []
    for p in providers.values():
        key, base_url, from_env = provider_credentials(p)
        rows.append({"id": p.id, "label": p.label, "engine": p.engine, "models": list(p.models),
                     "note": p.note, "base_url": base_url, "default_base_url": p.base_url,
                     "key_env": p.key_env, "has_key": bool(key), "key_from_env": from_env,
                     "key_hint": key[-4:] if key else ""})
    return rows


# ---- sessions ---------------------------------------------------------------

def list_sessions(agent: str | None = None) -> list[dict]:
    index = _read_json(INDEX, {})
    rows = [{"id": sid, **meta} for sid, meta in index.items()]
    if agent:
        rows = [r for r in rows if r["agent"] == agent]
    return sorted(rows, key=lambda r: r["updated"], reverse=True)


def get_session(session_id: str) -> dict | None:
    return _read_json(INDEX, {}).get(session_id)


def new_session(agent: str, provider: str = "claude", model: str = "") -> str:
    session_id = uuid.uuid4().hex[:12]
    _update_index(session_id, {"agent": agent, "provider": provider, "model": model,
                               "started": now(), "updated": now(),
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
        changes["tokens"] = meta.get("tokens", 0) + (event.get("tokens_in") or 0) + (event.get("tokens_out") or 0)
    if event.get("claude_session_id"):
        changes["claude_session_id"] = event["claude_session_id"]
    _update_index(session_id, changes)


def read_events(session_id: str) -> list[dict]:
    path = SESSIONS / f"{session_id}.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def save_messages(session_id: str, messages: list[dict]) -> None:
    """The full conversation for engines that keep it themselves (non-Claude providers)."""
    _write_json(SESSIONS / f"{session_id}.messages.json", messages)


def load_messages(session_id: str) -> list[dict]:
    return _read_json(SESSIONS / f"{session_id}.messages.json", [])
