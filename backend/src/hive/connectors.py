"""The apps the team can use beyond the codebase: Figma, ClickUp, Jira, Sentry, and any MCP server.

Each connector is a token (or two) you paste in Settings → Integrations, kept in data/console/settings.json like the
other keys and never sent back to the browser, plus the roles that may use it. The agents use them through the
team's tools (team/tools/figma.py, clickup.py, jira.py, sentry.py), which read the same settings, so they work
on every provider. MCP servers are for Claude agents (Claude Code runs them).

The server's environment wins over Settings (FIGMA_TOKEN, CLICKUP_TOKEN, JIRA_SITE/JIRA_EMAIL/JIRA_TOKEN,
SENTRY_TOKEN/SENTRY_URL), as for Slack.
"""
from __future__ import annotations

import asyncio
import os
import re
import shlex
import sys

from . import store

TOOLS = store.KIT / "team" / "tools"
ROLES = ("orchestrator", "techlead", "dev", "reviewer", "coach")

# id -> name, fields (key, label, secret, environment variable, placeholder), the roles it's for at first,
# whether it can update tickets as tasks move, and what the agents are told (with {tools} = team/tools).
CATALOG: dict[str, dict] = {
    "figma": {
        "name": "Figma",
        "fields": [("token", "Personal access token", True, "FIGMA_TOKEN", "figd_…")],
        "roles": ["techlead", "dev", "reviewer"],
        "tickets": False,
        "teach": (
            "**Figma** (read-only), for any figma.com link you're given:\n"
            "- `python3 {tools}/figma.py read <link>`: the frame's layers with layout, sizes, spacing, text and colours, "
            "then the colours and text styles it uses. Build and check against these numbers, not a guess from a picture.\n"
            "- `python3 {tools}/figma.py frames <link>`: a whole file's pages and frames, each with its own link.\n"
            "- `python3 {tools}/figma.py image <link> <topic>`: the frame as a picture in data/visuals/<topic>/; it prints "
            "the Markdown that shows it in your message, e.g. next to a screenshot of the screen today."),
        "teach_role": {
            "techlead": "When a change comes with a Figma link, show the design next to a screenshot of today's screen, "
                        "put the link in the spec's Technical Notes and list the exact values the dev must match.",
            "reviewer": "When the spec links a Figma frame, read it: a screen that doesn't match it (layout, spacing, "
                        "colours, text) is a finding, with the expected value from Figma.",
            "dev": "When the spec links a Figma frame, read it before building the screen and match its values.",
        },
    },
    "clickup": {
        "name": "ClickUp",
        "fields": [("token", "Personal API token", True, "CLICKUP_TOKEN", "pk_…")],
        "roles": ["orchestrator", "techlead", "dev", "reviewer"],
        "tickets": True,
        "teach": (
            "**ClickUp**, for ClickUp ticket links and IDs:\n"
            "- `python3 {tools}/clickup.py task <ticket>`: the ticket with its description, checklists, subtasks, "
            "attachments and comments. `clickup.py attachments <ticket>` downloads the attachments (read them with files.py).\n"
            "- `python3 {tools}/clickup.py comment <ticket> \"<text>\"` and `clickup.py status <ticket> [\"<status>\"]`."),
    },
    "jira": {
        "name": "Jira",
        "fields": [("site", "Site", False, "JIRA_SITE", "yourcompany.atlassian.net"),
                   ("email", "Your Atlassian email", False, "JIRA_EMAIL", "you@company.com"),
                   ("token", "API token", True, "JIRA_TOKEN", "ATATT…")],
        "roles": ["orchestrator", "techlead", "dev", "reviewer"],
        "tickets": True,
        "teach": (
            "**Jira**, for Jira issue keys (ABC-123) and links:\n"
            "- `python3 {tools}/jira.py issue <issue>`: the issue with its description, subtasks, attachments and "
            "comments. `jira.py attachments <issue>` downloads the attachments (read them with files.py).\n"
            "- `python3 {tools}/jira.py comment <issue> \"<text>\"` and `jira.py status <issue> [\"<status>\"]`."),
    },
    "sentry": {
        "name": "Sentry",
        "fields": [("token", "Auth token", True, "SENTRY_TOKEN", "sntrys_…"),
                   ("url", "Sentry address (self-hosted only)", False, "SENTRY_URL", "https://sentry.io")],
        "roles": ["techlead", "dev"],
        "tickets": False,
        "teach": (
            "**Sentry** (read-only), for Sentry issue links:\n"
            "- `python3 {tools}/sentry.py issue <link>`: the error, how often and for whom, the release, the stack trace "
            "of its latest event (your code marked ▶), the breadcrumbs that led to it and the request. Start a fix from "
            "the in-app frames, and say in the spec or your report which release and environment it was seen in."),
    },
}

TICKET_TEACH = (
    "\nWhen a task comes from a ClickUp ticket or a Jira issue, read the ticket first, then put its link in the task's "
    "`ticket:` field (`new_task.py … --ticket <link>`, or edit the field). Hive comments on the ticket each time the "
    "task moves, and moves the ticket too if the lead set that up: don't comment the same news yourself.")

FILES_TEACH = (
    "\n\n## Files the lead attaches\n"
    "A message can end with attached files, one per line as `📎 <path>`. Read them before you answer:\n"
    "- spreadsheets (.xlsx, .csv), Word (.docx) and slides (.pptx): `python3 {tools}/files.py read <path>` "
    "(every sheet as a table; `--sheet NAME`, `--rows N` for more rows);\n"
    "- images and PDFs: look at them with your Read tool (`files.py read` also extracts a PDF's text);\n"
    "- `python3 {tools}/files.py list`: everything attached so far.")


def _saved() -> dict:
    return store._read_json(store.SETTINGS, {}).get("connectors") or {}


def _value(cid: str, key: str, env: str) -> tuple[str, bool]:
    if os.environ.get(env):
        return os.environ[env], True
    return (_saved().get(cid) or {}).get(key, ""), False


def config(cid: str) -> dict:
    """In effect: each field (the environment first), the roles and the options."""
    c, saved = CATALOG[cid], _saved().get(cid) or {}
    out = {key: _value(cid, key, env)[0] for key, _l, _s, env, _p in c["fields"]}
    roles = saved.get("roles")
    out["roles"] = list(c["roles"]) if roles is None else roles
    out["options"] = saved.get("options") or {}
    return out


def is_connected(cid: str) -> bool:
    cfg = config(cid)
    return all(cfg.get(key) for key, *_ in CATALOG[cid]["fields"] if key != "url")


def public() -> dict:
    """For the browser: what's set (a hint, never a token), the roles and options, and the MCP servers."""
    out = {}
    for cid, c in CATALOG.items():
        cfg = config(cid)
        fields = {}
        for key, label, secret, env, placeholder in c["fields"]:
            value, from_env = _value(cid, key, env)
            fields[key] = {"label": label, "secret": secret, "placeholder": placeholder, "from_env": from_env, "env": env,
                           "set": bool(value), **({"hint": value[-4:]} if secret and value else {"value": "" if secret else value})}
        out[cid] = {"name": c["name"], "connected": is_connected(cid), "fields": fields, "roles": cfg["roles"],
                    "options": cfg["options"], "tickets": c["tickets"], "checked": (_saved().get(cid) or {}).get("checked", ""),
                    "error": (_saved().get(cid) or {}).get("error", "")}
    out["mcp"] = {"servers": [{**s, "env": {k: "" for k in (s.get("env") or {})},
                               "headers": {k: "" for k in (s.get("headers") or {})}} for s in mcp_servers()]}
    return out


def save(cid: str, body: dict) -> dict:
    """Save fields (an empty secret keeps the saved one; null clears it), roles and options."""
    if cid not in CATALOG:
        raise ValueError(f"Unknown connector: {cid}")
    settings = store._read_json(store.SETTINGS, {})
    current = (settings.setdefault("connectors", {})).setdefault(cid, {})
    for key, _label, secret, _env, _p in CATALOG[cid]["fields"]:
        if key not in (body.get("fields") or {}):
            continue
        value = body["fields"][key]
        if value is None:
            current.pop(key, None)
            continue
        value = str(value).strip()
        if secret and not value:
            continue
        if key == "site":
            value = re.sub(r"^https?://", "", value).strip("/")
            if value and not re.fullmatch(r"[\w.-]+(:\d+)?", value):
                raise ValueError("The site is your Jira address, like yourcompany.atlassian.net.")
        if key == "url" and value and not re.match(r"^https?://", value):
            raise ValueError("Enter Sentry's address with https://, like https://sentry.yourcompany.com.")
        current[key] = value
    if "roles" in body:
        roles = [r for r in body["roles"] if r in ROLES]
        current["roles"] = roles
    if "options" in body:
        options = current.setdefault("options", {})
        if "comment" in body["options"]:
            options["comment"] = bool(body["options"]["comment"])
        if "move" in body["options"]:
            options["move"] = {k: str(v).strip() for k, v in (body["options"]["move"] or {}).items() if str(v).strip()}
    if "fields" in body:   # a new token: whatever the last test said no longer holds
        current.pop("checked", None)
        current.pop("error", None)
    store._write_json(store.SETTINGS, settings)
    return public()[cid]


def disconnect(cid: str) -> dict:
    settings = store._read_json(store.SETTINGS, {})
    (settings.get("connectors") or {}).pop(cid, None)
    store._write_json(store.SETTINGS, settings)
    return public()[cid]


async def test(cid: str) -> tuple[bool, str]:
    """Ask the app who we are, with the team's own tool, so the test is what the agents will do."""
    if cid not in CATALOG:
        raise ValueError(f"Unknown connector: {cid}")
    if not is_connected(cid):
        return False, "Fill in every field first."
    env = {k: v for k, v in os.environ.items() if k != "AGENT_ID"}
    proc = await asyncio.create_subprocess_exec(sys.executable, str(TOOLS / f"{cid}.py"), "whoami", env=env,
                                                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), 45)
    except asyncio.TimeoutError:
        proc.kill()
        return False, f"{CATALOG[cid]['name']} didn't answer within 45 seconds."
    ok = proc.returncode == 0
    message = (out if ok else err).decode("utf-8", "replace").strip().removeprefix("Error: ")
    settings = store._read_json(store.SETTINGS, {})
    saved = settings.setdefault("connectors", {}).setdefault(cid, {})
    saved["checked" if ok else "error"] = message
    saved.pop("error" if ok else "checked", None)
    store._write_json(store.SETTINGS, settings)
    return ok, message


# ---- MCP servers (Claude agents) -------------------------------------------------

def mcp_servers() -> list[dict]:
    """[{name, type: stdio|http, command, url, env, headers, roles}], as saved."""
    return store._read_json(store.SETTINGS, {}).get("mcp_servers") or []


def save_mcp(servers: list[dict]) -> dict:
    """Replace the list. Values left empty for env/headers keep the saved ones (they're secrets)."""
    old = {s["name"]: s for s in mcp_servers()}
    clean, names = [], set()
    for s in servers:
        name = str(s.get("name", "")).strip()
        if not re.fullmatch(r"[a-zA-Z0-9][\w-]{0,40}", name):
            raise ValueError("Give each server a short name: letters, digits, - and _ (it prefixes its tools).")
        if name in names:
            raise ValueError(f"Two servers are called {name}.")
        names.add(name)
        kind = s.get("type") if s.get("type") in ("stdio", "http") else "stdio"
        entry = {"name": name, "type": kind, "roles": [r for r in s.get("roles") or [] if r in ROLES]}
        if kind == "stdio":
            entry["command"] = str(s.get("command", "")).strip()
            if not entry["command"]:
                raise ValueError(f"{name}: enter the command that starts it, like npx -y @notionhq/notion-mcp-server.")
            shlex.split(entry["command"])   # raises on unbalanced quotes
        else:
            entry["url"] = str(s.get("url", "")).strip()
            if not re.match(r"^https?://", entry["url"]):
                raise ValueError(f"{name}: enter its address with https://.")
        for part in ("env", "headers"):
            keep = (old.get(name) or {}).get(part) or {}
            values = {}
            for k, v in (s.get(part) or {}).items():
                k = str(k).strip()
                if not k:
                    continue
                values[k] = str(v) if str(v) != "" else keep.get(k, "")
            entry[part] = values
        clean.append(entry)
    settings = store._read_json(store.SETTINGS, {})
    settings["mcp_servers"] = clean
    store._write_json(store.SETTINGS, settings)
    return public()["mcp"]


def mcp_for(role: str) -> dict:
    """Claude Code's mcp_servers option for an agent of this role."""
    out = {}
    for s in mcp_servers():
        if role not in (s.get("roles") or []):
            continue
        if s["type"] == "stdio":
            parts = shlex.split(s["command"])
            out[s["name"]] = {"type": "stdio", "command": parts[0], "args": parts[1:], "env": s.get("env") or {}}
        else:
            out[s["name"]] = {"type": "http", "url": s["url"], "headers": s.get("headers") or {}}
    return out


# ---- what the agents are told ------------------------------------------------------

def instructions_for(role: str, engine: str) -> str:
    """The "Connected apps" section of an agent's instructions: only what's connected and allowed for its role."""
    tools = str(TOOLS)
    parts = []
    tickets = False
    for cid, c in CATALOG.items():
        cfg = config(cid)
        if not is_connected(cid) or role not in cfg["roles"]:
            continue
        text = c["teach"].format(tools=tools)
        extra = (c.get("teach_role") or {}).get(role)
        parts.append(text + (f"\n{extra}" if extra else ""))
        tickets = tickets or c["tickets"]
    servers = [s["name"] for s in mcp_servers() if role in (s.get("roles") or [])]
    if servers and engine == "claude":
        parts.append("**Other tools**: the MCP servers " + ", ".join(f"`{n}`" for n in servers)
                     + " (their tools are named `mcp__<server>__…`).")
    text = ""
    if parts:
        text = ("\n\n## Connected apps\nThe lead connected these apps for you. If one answers that it isn't connected "
                "or the token was refused, tell the lead; don't work around it.\n\n" + "\n\n".join(parts)
                + (TICKET_TEACH if tickets and role in ("techlead", "orchestrator") else ""))
    return text + FILES_TEACH.format(tools=tools)
