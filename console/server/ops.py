"""What the lead can do to the team, in one place.

Used by the Orchestrator (each action only after the lead approves it), by Slack (buttons the lead
taps) and by links sent to the lead. Nothing here hands work on by itself: the lead decides.
"""
from __future__ import annotations

import os

from . import board, store

MESSAGES = {   # what an agent is told when it's handed a task (the console's own hand-off prompts)
    "techlead": "Let's continue on {id} ({title}).",
    "dev": "Work on {id} per your instructions.",
    "reviewer": "Review {id} per your instructions.",
}
WHO_TAKES = {"draft": "techlead", "ready-for-dev": "dev", "changes-requested": "dev", "ready-for-review": "reviewer"}
BUSY_STATUSES = {"in-dev": "dev", "in-review": "reviewer"}


class OpsError(Exception):
    """Something the lead needs to know (shown as is)."""


# ---- names and links --------------------------------------------------------------------

def label(agent_id: str) -> str:
    """'Nabil (Dev)', as everywhere in the console."""
    agents = store.load_settings()["agents"]
    a = agents.get(agent_id, {})
    role = {"techlead": "Tech Lead", "dev": "Dev", "reviewer": "Reviewer", "coach": "Coach",
            "orchestrator": "Orchestrator"}.get(a.get("role") or store.role_of(agent_id), agent_id)
    return f"{a['name']} ({role})" if a.get("name") else role


def find_agent(who: str) -> str:
    """An agent by id (dev-2) or name (Nabil), any case."""
    agents = store.load_settings()["agents"]
    key = who.strip().lstrip("@").lower()
    for aid, a in agents.items():
        if key in (aid.lower(), a.get("name", "").lower()):
            return aid
    raise OpsError(f"There's no agent called {who}. The team: {', '.join(label(a) for a in agents)}.")


def console_url() -> str:
    """The address the lead opens the console at, for links: Settings, else CONSOLE_URL, else this machine."""
    url = store.load_settings().get("console_url") or os.environ.get("CONSOLE_URL") or ""
    return (url or f"http://localhost:{os.environ.get('PORT', '8420')}").rstrip("/")


def links(task_id: str = "", agent_id: str = "") -> dict:
    base = console_url()
    out = {"console": base + "/"}
    if task_id:
        out["task"] = f"{base}/#/tasks/{task_id}"
        out["review"] = f"{base}/#/tasks/{task_id}/review"
    if agent_id:
        out["chat"] = f"{base}/#/agents/{agent_id}"
    return out


# ---- reading the team -------------------------------------------------------------------

def _task(task_id: str) -> dict:
    task = board.get_task(task_id.strip().upper())
    if not task:
        raise OpsError(f"There's no task {task_id}.")
    return task


def _busy_with(agent_id: str, tasks: list[dict]) -> str:
    """The task an agent is working on right now ('' if none)."""
    return next((t["id"] for t in tasks if t["status"] in BUSY_STATUSES and t["assignee"] == agent_id), "")


def agents(manager) -> list[dict]:
    tasks = board.list_tasks()
    return [{"id": aid, "name": label(aid), "role": r.role, "status": r.status, "task": _busy_with(aid, tasks),
             "waiting_for_you": len(r.pending)} for aid, r in manager.agents.items()]


def status(manager) -> dict:
    """The board in short: every open task, who has it, what waits on the lead, and the team."""
    tasks = board.list_tasks()
    open_tasks = [t for t in tasks if t["status"] != "done"]
    rows = [{"id": t["id"], "title": t["title"], "status": t["status"], "project": t["project_name"],
             "with": label(t["assignee"]) if t["assignee"] else "", "link": links(t["id"])["task"]} for t in open_tasks]
    waiting = [{"id": t["id"], "title": t["title"], "status": t["status"], "next": WHO_TAKES.get(t["status"], "lead"),
                "candidates": [label(a) for a in candidates(manager, t)], "link": links(t["id"])["task"],
                "review": links(t["id"])["review"] if t["from_commit"] else ""}
               for t in open_tasks if t["status"] in WHO_TAKES or t["status"] == "blocked"]
    approvals = [{"agent": label(aid), "tool": p["tool"], "link": links(agent_id=aid)["chat"]}
                 for aid, r in manager.agents.items() for p in r.pending.values()]
    recent = [t for t in tasks if t["status"] == "done"][:5]
    return {"tasks": rows, "waiting_on_a_hand_off": waiting, "approvals_waiting": approvals,
            "recently_done": [{"id": t["id"], "title": t["title"], "review": links(t["id"])["review"]} for t in recent],
            "team": agents(manager), "console": links()["console"]}


def task(task_id: str) -> dict:
    t = _task(task_id)
    return {k: t[k] for k in ("id", "title", "status", "project", "base", "branch", "techlead", "dev", "reviewer",
                              "blocked_by", "assignee")} | {
        "with": label(t["assignee"]) if t["assignee"] else "", "links": links(t["id"]),
        "your_reviews": t["lead_review"], "recent_activity": t["activity"][:8]}


def candidates(manager, t: dict) -> list[str]:
    """Who can take a task now, free agents first. Rework goes back to the dev who built it."""
    role = WHO_TAKES.get(t["status"])
    if not role:
        return []
    if t["status"] == "changes-requested" and t["dev"]:
        return [t["dev"]] if t["dev"] in manager.agents else []
    if t["status"] == "draft" and t["techlead"] in manager.agents:
        return [t["techlead"]]
    if t["status"] == "ready-for-review" and t["reviewer"] in manager.agents:   # re-review: the same reviewer
        return [t["reviewer"]]
    tasks = board.list_tasks()
    team = [aid for aid, r in manager.agents.items() if r.role == role]
    return sorted(team, key=lambda aid: (bool(_busy_with(aid, tasks)), manager.agents[aid].status == "working"))


# ---- acting (the lead's decisions) --------------------------------------------------------

def _runner(manager, agent_id: str):
    if agent_id not in manager.agents:
        raise OpsError(f"There's no agent {agent_id}.")
    return manager.get(agent_id)


async def start(manager, agent_id: str) -> str:
    runner = _runner(manager, agent_id)
    if runner.status != "stopped":
        return f"{label(agent_id)} is already running."
    await runner.start()
    return f"Started {label(agent_id)}."


async def stop(manager, agent_id: str) -> str:
    runner = _runner(manager, agent_id)
    if runner.status == "stopped":
        return f"{label(agent_id)} isn't running."
    await runner.stop()
    return f"Stopped {label(agent_id)}."


async def tell(manager, agent_id: str, text: str) -> str:
    """Send an agent a message (starting it if needed). Refused while it's in the middle of something."""
    runner = _runner(manager, agent_id)
    if not text.strip():
        raise OpsError("The message is empty.")
    if runner.status in ("working", "waiting", "starting"):
        raise OpsError(f"{label(agent_id)} is busy ({runner.status}). Wait for it to finish, or interrupt it in the console.")
    await runner.send(text.strip())
    return f"Sent to {label(agent_id)}."


def check_hand(manager, task_id: str, agent_id: str) -> dict:
    """Whether this agent can take this task now; the task if so."""
    t = _task(task_id)
    role = WHO_TAKES.get(t["status"])
    runner = _runner(manager, agent_id)
    if t["status"] in BUSY_STATUSES:
        raise OpsError(f"{t['id']} is {t['status']}: {label(t['assignee']) if t['assignee'] else 'someone'} is already on it.")
    if not role:
        raise OpsError(f"{t['id']} is {t['status']}: there's nothing to hand on. "
                       + ("Send it back from your code review if it needs changes." if t["status"] == "done" else ""))
    if runner.role != role:
        raise OpsError(f"{t['id']} is {t['status']}, which is for a {role}; {label(agent_id)} is a {runner.role}.")
    allowed = candidates(manager, t)
    if agent_id not in allowed:
        raise OpsError(f"{t['id']} goes to {', '.join(label(a) for a in allowed) or 'nobody right now'}"
                       f" ({'rework goes back to the dev who built it' if t['status'] == 'changes-requested' else 'the one who already has it'}).")
    return t


async def hand(manager, task_id: str, agent_id: str, note: str = "") -> str:
    """Give a task to an agent: start it if needed and tell it to pick the task up."""
    t = check_hand(manager, task_id, agent_id)
    text = MESSAGES[manager.agents[agent_id].role].format(id=t["id"], title=t["title"])
    if note.strip():
        text += f"\n\nA note from the lead: {note.strip()}"
    await tell(manager, agent_id, text)
    return f"Handed {t['id']} to {label(agent_id)}."


async def coach(manager, scope: str = "") -> str:
    """Start a Coach review: 'last' (since the last review), 'all', or task ids / a project."""
    coach_id = next((aid for aid, r in manager.agents.items() if r.role == "coach"), "")
    if not coach_id:
        raise OpsError("There's no Coach on the team.")
    scope = scope.strip()
    text = ({"": "Review everything since your last review.", "last": "Review everything since your last review.",
             "all": "Review all tasks."}.get(scope.lower())
            or (f"Review these tasks: {scope}." if scope.upper().startswith("TASK-") else f"Review the tasks in {scope}."))
    await tell(manager, coach_id, text)
    return f"The Coach is reviewing ({text[:-1].lower()})."
