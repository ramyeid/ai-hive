"""Shared helpers for the connectors (Figma, ClickUp, Jira, Sentry): their settings, the agent's role, HTTP.

You connect an app in the console (Settings → Integrations): its token is kept in data/console/settings.json,
or comes from the server's environment (FIGMA_TOKEN, CLICKUP_TOKEN, JIRA_SITE / JIRA_EMAIL / JIRA_TOKEN,
SENTRY_TOKEN / SENTRY_URL), which wins. Each connector also says which roles may use it.
Standard library only.
"""
from __future__ import annotations

import base64
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tasklib import DATA  # noqa: E402

SETTINGS = DATA / "console" / "settings.json"
TIMEOUT = 30

# The fields each connector keeps, and the environment variable that overrides each one.
FIELDS = {
    "figma": {"token": "FIGMA_TOKEN"},
    "clickup": {"token": "CLICKUP_TOKEN"},
    "jira": {"site": "JIRA_SITE", "email": "JIRA_EMAIL", "token": "JIRA_TOKEN"},
    "sentry": {"token": "SENTRY_TOKEN", "url": "SENTRY_URL"},
}
NAMES = {"figma": "Figma", "clickup": "ClickUp", "jira": "Jira", "sentry": "Sentry"}
# Who may use each until the lead changes it (the same as the console's connectors.CATALOG).
DEFAULT_ROLES = {"figma": ["techlead", "dev", "reviewer"], "clickup": ["orchestrator", "techlead", "dev", "reviewer"],
                 "jira": ["orchestrator", "techlead", "dev", "reviewer"], "sentry": ["techlead", "dev"]}


class ConnectorError(Exception):
    """Something the agent should read and act on (or tell the lead about)."""


def settings() -> dict:
    try:
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def config(cid: str) -> dict:
    """This connector's settings in effect: the server's environment first, then Settings → Integrations."""
    saved = (settings().get("connectors") or {}).get(cid) or {}
    out = {k: os.environ.get(env) or saved.get(k, "") for k, env in FIELDS[cid].items()}
    out["roles"] = saved.get("roles") if saved.get("roles") is not None else DEFAULT_ROLES[cid]
    out["options"] = saved.get("options") or {}
    return out


def my_role() -> str:
    """The role of the agent running this tool ("" for you, from a terminal or the console)."""
    agent = os.environ.get("AGENT_ID", "")
    if not agent:
        return ""
    return ((settings().get("agents") or {}).get(agent) or {}).get("role") or agent.split("-")[0]


def require(cid: str) -> dict:
    """The connector's settings, or a clear error when it isn't connected or isn't for this agent's role."""
    cfg = config(cid)
    name = NAMES[cid]
    missing = [k for k in FIELDS[cid] if k != "url" and not cfg.get(k)]
    if missing:
        raise ConnectorError(f"{name} isn't connected. Ask the lead to connect it in the console: "
                             f"Settings → Integrations → {name}.")
    role = my_role()
    if role and role not in cfg["roles"]:
        raise ConnectorError(f"{name} is connected, but not for your role ({role}). "
                             f"The lead can allow it in Settings → Integrations → {name}.")
    return cfg


def request(method: str, url: str, headers: dict | None = None, body=None, raw: bool = False, what: str = ""):
    """An HTTP call; JSON in and out unless raw. Errors become a ConnectorError the agent can read."""
    data = None
    headers = {"Accept": "application/json", "User-Agent": "Hive", **(headers or {})}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as res:
            payload = res.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        hint = {401: "the token was refused (expired or wrong?)", 403: "the token can't see this (permissions or scope)",
                404: "not found (check the link or ID, and that the token's account can see it)",
                429: "rate-limited, try again in a minute"}.get(e.code, "")
        raise ConnectorError(f"{what or url}: HTTP {e.code}{f', {hint}' if hint else ''}. {detail}".strip()) from None
    except (urllib.error.URLError, TimeoutError) as e:
        raise ConnectorError(f"{what or url}: couldn't connect ({getattr(e, 'reason', e)}).") from None
    if raw:
        return payload
    return json.loads(payload) if payload.strip() else {}


def basic(user: str, token: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()


def run(main) -> None:
    """Run a tool's main(); a ConnectorError is printed for the agent, exit code 1."""
    try:
        sys.exit(main(sys.argv[1:]) or 0)
    except ConnectorError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")
