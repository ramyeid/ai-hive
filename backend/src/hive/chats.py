"""Each task's conversations, for the lead's debugging: which agent worked on it, when, and what was said.

Kept in tasks/chats/<TASK-ID>/, one pair of files per agent conversation that worked on the task:
  <started>-<agent>-<session>.json   what the console shows (with the events)
  <started>-<agent>-<session>.md     the same, readable in any editor
Agents never read these: the task file is what carries work from one agent to the next.

A conversation is saved when it ends: when the agent hands the task on (the console then starts it on a
fresh conversation, so you don't have to /clear), when you stop it, or when you start a new session.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from . import board, costs, store

CHATS = board.TASKS / "chats"
# Hand-offs that end an agent's part in a task: the console starts that agent on a fresh conversation.
HANDOFF = {"techlead": {"ready-for-dev"}, "dev": {"ready-for-review"}, "reviewer": {"done", "changes-requested"}}
NAME = re.compile(r"^[0-9T-]+-[a-z]+(?:-\d+)?-[0-9a-f]+$")


def handed_off(agent: str, since: str) -> list[dict]:
    """Status changes this agent made since `since` that hand a task on to someone else."""
    wanted = HANDOFF.get(store.role_of(agent), set())
    return [a for a in reversed(board.activity(500))
            if a.get("actor") == agent and a.get("ts", "") >= since and a.get("to") in wanted]


def stints(session_id: str) -> dict[str, dict]:
    """The parts of one conversation that worked on each task: task id -> its turns, times and cost."""
    meta = store.get_session(session_id) or {}
    found: dict[str, dict] = {}
    for turn in costs.attributed_turns(store.read_events(session_id), meta.get("model") or ""):
        result = turn["result"] or {}
        for task in turn["tasks"]:
            stint = found.setdefault(task, {"task": task, "agent": meta.get("agent", ""), "session": session_id,
                                            "provider": meta.get("provider", ""), "model": turn["model"],
                                            "started": turn["events"][0]["ts"], "events": [],
                                            "cost_usd": 0.0, "tokens": 0, "turns": 0})
            stint["events"] += turn["events"]
            stint["finished"] = turn["events"][-1]["ts"]
            stint["cost_usd"] = round(stint["cost_usd"] + (result.get("cost_usd") or 0), 4)
            stint["tokens"] += (result.get("tokens_in") or 0) + (result.get("tokens_out") or 0)
            stint["turns"] += 1
    for stint in found.values():
        moves = [a for a in reversed(board.activity(1000)) if a.get("id") == stint["task"]
                 and a.get("actor") == stint["agent"] and stint["started"] <= a.get("ts", "") <= stint["finished"]]
        stint["outcome"] = moves[-1]["to"] if moves else ""
    return found


def _file_stem(stint: dict) -> str:
    started = datetime.fromisoformat(stint["started"]).strftime("%Y%m%d-%H%M%S")
    return f"{started}-{stint['agent']}-{stint['session']}"


def archive(session_id: str | None) -> list[Path]:
    """Save the conversation into each task it worked on. Safe to repeat: rewrites the same files."""
    if not session_id:
        return []
    written = []
    for task, stint in stints(session_id).items():
        folder = CHATS / task
        folder.mkdir(parents=True, exist_ok=True)
        stem = _file_stem(stint)
        (folder / f"{stem}.json").write_text(json.dumps(stint, indent=1, default=str), encoding="utf-8")
        (folder / f"{stem}.md").write_text(_markdown(stint), encoding="utf-8")
        written.append(folder / f"{stem}.json")
    return written


def for_task(task_id: str, live_sessions: list[str]) -> list[dict]:
    """The task's saved conversations, plus the parts of running conversations that work on it."""
    folder = CHATS / task_id
    saved = [json.loads(p.read_text(encoding="utf-8")) | {"name": p.stem, "live": False}
             for p in sorted(folder.glob("*.json"))] if folder.exists() else []
    saved_sessions = {s["session"] for s in saved}
    live = [stint | {"name": f"live-{session}", "live": True}
            for session in live_sessions if session not in saved_sessions
            for task, stint in stints(session).items() if task == task_id]
    rows = saved + live
    for row in rows:
        row.pop("events", None)
    return sorted(rows, key=lambda r: r["started"])


def get(task_id: str, name: str, live_sessions: list[str]) -> dict | None:
    if name.startswith("live-"):
        session = name[len("live-"):]
        stint = stints(session).get(task_id) if session in live_sessions else None
        return stint | {"name": name, "live": True} if stint else None
    if not NAME.match(name):   # only our own file names: no path tricks
        return None
    path = CHATS / task_id / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8")) | {"name": name, "live": False} if path.exists() else None


def _markdown(stint: dict) -> str:
    agent = stint["agent"]
    name = store.load_settings()["agents"].get(agent, {}).get("name", "")
    agent = f"{name} ({agent})" if name else agent
    lines = [f"# {stint['task']}: {agent}", "",
             f"- Started: {stint['started']}", f"- Finished: {stint.get('finished', '')}",
             f"- Outcome: {stint.get('outcome') or 'no hand-off in this conversation'}",
             f"- Model: {stint.get('provider', '')} {stint.get('model', '')}".rstrip(),
             f"- Turns: {stint['turns']}, cost: ${stint['cost_usd']:.4f}, tokens: {stint['tokens']}",
             f"- Console session: {stint['session']}", "", "---", ""]
    for e in stint["events"]:
        kind = e["kind"]
        if kind == "user":
            lines += [f"**Lead** ({e['ts']}):", "", e["text"], ""]
        elif kind == "text":
            lines += [f"**{agent}:**", "", e["text"], ""]
        elif kind == "tool":
            lines += [f"`{e.get('name', '')}` {json.dumps(e.get('input') or {})[:400]}", ""]
        elif kind == "tool_result":
            text = (e.get("text") or "")[:1500]
            lines += ["```", text, "```", ""]
        elif kind in ("permission", "decision"):
            lines += [f"_{kind}: {e.get('tool', '')} {e.get('decision', '')} {e.get('message', '')}_".strip(), ""]
        elif kind in ("error", "system"):
            lines += [f"_{kind}: {e.get('text', '')}_", ""]
    return "\n".join(lines) + "\n"
