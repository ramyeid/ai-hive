"""What each task cost, per model, from the conversation history.

Every agent turn ends with a "result" event carrying its cost (Claude Code reports
it) and/or its tokens (all providers). This module replays each conversation and
charges every turn to the task(s) it worked on:

- task IDs the lead mentions in the message ("Work on TASK-004"),
- task files the agent reads, writes or edits,
- task IDs in the agent's shell commands,
- the task the Tech Lead creates with new_task.py.

A turn that touches no task (e.g. answering the Tech Lead's questions) is charged to the
task(s) the same conversation worked on last. A turn touching several tasks is
split evenly. Anything left is reported as "not linked to a task".

Providers that only report tokens are priced with the per-model prices set in
Settings (US$ per 1M input / output tokens).
"""
from __future__ import annotations

import json
import re
from collections import defaultdict

from . import store

TASK_ID = re.compile(r"\bTASK-\d{3,}\b")
TASK_FILE = re.compile(r"/tasks/(TASK-\d{3,})-[^/]*\.md$")


def _ids_in(text: str) -> set[str]:
    return set(TASK_ID.findall(text or ""))


def attributed_turns(events: list[dict], model: str = "") -> list[dict]:
    """Split a conversation into turns (from the lead's message to the result) and say which tasks each
    one worked on. Shared by costs and the per-task conversation records, so they always agree."""
    turns, current, touched, last_tasks, tools = [], [], set(), set(), {}
    for event in events:
        kind = event["kind"]
        current.append(event)
        if kind == "init" and event.get("model"):
            model = event["model"]
        elif kind == "user":
            touched = _ids_in(event["text"])
        elif kind == "tool":
            name, args = event.get("name", ""), event.get("input") or {}
            tools[event.get("id")] = (name, args)
            if name in ("Read", "Write", "Edit", "MultiEdit"):
                match = TASK_FILE.search(args.get("file_path", ""))
                if match:
                    touched.add(match.group(1))
            elif name == "Bash":
                touched |= _ids_in(args.get("command", ""))
        elif kind == "tool_result":
            name, args = tools.get(event.get("id"), ("", {}))
            if name == "Bash" and "new_task.py" in args.get("command", ""):
                touched |= _ids_in(event.get("text", ""))
        elif kind == "result":
            tasks = touched or last_tasks
            last_tasks = tasks
            turns.append({"tasks": sorted(tasks), "events": current, "result": event, "model": model})
            current, touched = [], set()
    if current and any(e["kind"] == "user" for e in current):   # a turn still running (or cut short)
        turns.append({"tasks": sorted(touched or last_tasks), "events": current, "result": None, "model": model})
    return turns


_rows: dict[str, tuple[tuple, list[dict]]] = {}   # session -> (what it was worked out from, its rows)


def session_turns(session_id: str, meta: dict) -> list[dict]:
    """One row per finished turn: who, which model, tokens, cost and the tasks it's charged to. A conversation is
    read again only when it changed: most pages show costs, and conversations get long."""
    key = (store.events_stamp(session_id), meta.get("agent"), meta.get("provider"), meta.get("model"))
    cached = _rows.get(session_id)
    if cached and cached[0] == key:
        return cached[1]
    rows = []
    for turn in attributed_turns(store.read_events(session_id), meta.get("model") or ""):
        result = turn["result"]
        if result is None:
            continue
        rows.append({"session": session_id, "agent": meta["agent"],
                     "provider": meta.get("provider", "claude"), "model": turn["model"] or "unknown",
                     "tokens_in": result.get("tokens_in") or 0, "tokens_out": result.get("tokens_out") or 0,
                     "cost_usd": result.get("cost_usd"), "tasks": turn["tasks"], "ts": result["ts"]})
    _rows[session_id] = (key, rows)
    return rows


def _priced(row: dict, prices: dict) -> float | None:
    if row["cost_usd"] is not None:
        return row["cost_usd"]
    price = prices.get(row["model"])
    if not price:
        return None
    return row["tokens_in"] / 1e6 * price.get("input", 0) + row["tokens_out"] / 1e6 * price.get("output", 0)


_summary: tuple[tuple, dict] | None = None


def summary() -> dict:
    """{"tasks": {TASK-ID: breakdown}, "unlinked": breakdown, "models": [models seen]}. Worked out again only when a
    conversation or a price changed (most pages ask for it)."""
    global _summary
    prices = store.load_settings().get("prices", {})
    sessions = store.list_sessions()
    key = (json.dumps(prices, sort_keys=True),
           tuple((s["id"], s.get("agent"), s.get("provider"), s.get("model"), store.events_stamp(s["id"])) for s in sessions))
    if _summary and _summary[0] == key:
        return _summary[1]
    _summary = (key, _summary_of(sessions, prices))
    return _summary[1]


_ledger: tuple[tuple, dict] | None = None


def ledger() -> dict:
    """Every finished turn as a line of spending, for the Finance page: when, which task (None when it's not linked
    to one), who, which model, its tokens and cost. A turn on several tasks is split evenly between them, as in
    summary(). cost_usd is None for tokens of a model without a price. Worked out again only when something changed."""
    global _ledger
    prices = store.load_settings().get("prices", {})
    sessions = store.list_sessions()
    key = (json.dumps(prices, sort_keys=True),
           tuple((s["id"], s.get("agent"), s.get("provider"), s.get("model"), store.events_stamp(s["id"])) for s in sessions))
    if _ledger and _ledger[0] == key:
        return _ledger[1]
    lines = []
    for session in sessions:
        for row in session_turns(session["id"], session):
            cost = _priced(row, prices)
            targets = row["tasks"] or [None]
            share = 1 / len(targets)
            for task in targets:
                lines.append({"ts": row["ts"], "task": task, "agent": row["agent"], "provider": row["provider"],
                              "model": row["model"], "tokens": round((row["tokens_in"] + row["tokens_out"]) * share),
                              "cost_usd": None if cost is None else round(cost * share, 6)})
    lines.sort(key=lambda line: line["ts"])
    _ledger = (key, {"lines": lines})
    return _ledger[1]


def _summary_of(sessions: list[dict], prices: dict) -> dict:
    buckets: dict[str, dict] = defaultdict(lambda: defaultdict(lambda: {
        "turns": 0, "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "unpriced_tokens": 0}))
    models: dict[str, str] = {}
    for session in sessions:
        for row in session_turns(session["id"], session):
            models[row["model"]] = row["provider"]
            cost = _priced(row, prices)
            targets = row["tasks"] or ["unlinked"]
            share = 1 / len(targets)
            for task in targets:
                line = buckets[task][(row["provider"], row["model"], row["agent"])]
                line["turns"] += 1
                line["tokens_in"] += round(row["tokens_in"] * share)
                line["tokens_out"] += round(row["tokens_out"] * share)
                if cost is None:
                    line["unpriced_tokens"] += round((row["tokens_in"] + row["tokens_out"]) * share)
                else:
                    line["cost_usd"] += cost * share
    tasks = {task: _breakdown(lines) for task, lines in buckets.items() if task != "unlinked"}
    return {"tasks": tasks, "unlinked": _breakdown(buckets.get("unlinked", {})),
            "models": [{"model": m, "provider": p, "priced": m in prices or p == "claude"}
                       for m, p in sorted(models.items())]}


def _breakdown(lines: dict) -> dict:
    rows = [{"provider": p, "model": m, "agent": a, **{k: (round(v, 4) if k == "cost_usd" else v) for k, v in vals.items()}}
            for (p, m, a), vals in sorted(lines.items())]
    return {"cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
            "unpriced_tokens": sum(r["unpriced_tokens"] for r in rows),
            "tokens": sum(r["tokens_in"] + r["tokens_out"] for r in rows),
            "rows": rows}
