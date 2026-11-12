"""Checks that task costs are charged to the right tasks and models.

    uv run python -m tests.test_costs
"""
import sys
import tempfile
from pathlib import Path

from hive import costs, store

checks = 0


def check(condition, what):
    global checks
    checks += 1
    if not condition:
        sys.exit(f"FAIL: {what}")
    print(f"ok  {what}")


def session(agent, provider, model, events):
    sid = store.new_session(agent, provider, model)
    for kind, data in events:
        store.append_event(sid, {"ts": store.now(), "agent": agent, "session": sid, "kind": kind, **data})
    return sid


def result(cost=None, tin=0, tout=0):
    return ("result", {"cost_usd": cost, "tokens_in": tin, "tokens_out": tout, "turns": 1, "duration_ms": 1})


def main():
    tmp = Path(tempfile.mkdtemp())
    store.DATA, store.SESSIONS = tmp, tmp / "sessions"
    store.INDEX, store.SETTINGS = store.SESSIONS / "index.json", tmp / "settings.json"
    kit = "/kit"

    # Tech Lead on Claude writes TASK-007 over three turns.
    session("techlead", "claude", "opus", [
        ("init", {"model": "claude-opus-5-5"}),
        ("user", {"text": "Create a task in ~/code/api: export users"}),
        ("tool", {"id": "t1", "name": "Bash", "input": {"command": f"python3 {kit}/team/tools/new_task.py ~/code/api 'Export users'"}}),
        ("tool_result", {"id": "t1", "text": f"{kit}/data/tasks/TASK-007-export-users.md"}),
        result(cost=0.10),
        ("user", {"text": "1 ok, 2 use CSV"}),
        ("tool", {"id": "t2", "name": "Edit", "input": {"file_path": f"{kit}/data/tasks/TASK-007-export-users.md"}}),
        result(cost=0.05),
        ("user", {"text": "approved"}),
        result(cost=0.01),
    ])
    # Dev on DeepSeek builds it; one turn also looks at TASK-008.
    session("dev", "deepseek", "deepseek-v4-pro", [
        ("init", {"model": "deepseek-v4-pro"}),
        ("user", {"text": "Work on TASK-007 per your instructions."}),
        result(tin=1_000_000, tout=500_000),
        ("user", {"text": "Also compare with TASK-008"}),
        ("tool", {"id": "t3", "name": "Read", "input": {"file_path": f"{kit}/data/tasks/TASK-007-export-users.md"}}),
        result(tin=200_000),
    ])
    # Reviewer on Kimi (no price set): checks the inbox, then reviews TASK-008.
    session("reviewer", "kimi", "kimi-k2-thinking", [
        ("init", {"model": "kimi-k2-thinking"}),
        ("user", {"text": "Check your inbox."}),
        ("tool", {"id": "t4", "name": "Bash", "input": {"command": f"python3 {kit}/team/tools/inbox.py reviewer"}}),
        ("tool_result", {"id": "t4", "text": "TASK-007 ready-for-review\nTASK-008 ready-for-review"}),
        result(tin=1000, tout=1000),
        ("user", {"text": "go"}),
        ("tool", {"id": "t5", "name": "Read", "input": {"file_path": f"{kit}/data/tasks/TASK-008-import.md"}}),
        result(tin=3000, tout=1000),
    ])

    s = costs.summary()
    t7 = s["tasks"]["TASK-007"]
    techlead = next(r for r in t7["rows"] if r["agent"] == "techlead")
    check(abs(techlead["cost_usd"] - 0.16) < 1e-9 and techlead["turns"] == 3,
          "Tech Lead: creating, editing and an 'approved' reply with no task named all count for TASK-007")
    check(techlead["model"] == "claude-opus-5-5", "the model is the one the provider actually ran, not the alias")
    dev7 = next(r for r in t7["rows"] if r["agent"] == "dev")
    check(dev7["unpriced_tokens"] == 1_600_000 and dev7["cost_usd"] == 0,
          "without a price, DeepSeek tokens are counted but not costed")

    store.save_settings({"prices": {"deepseek-v4-pro": {"input": 0.5, "output": 2.0}}})
    s = costs.summary()
    t7, t8 = s["tasks"]["TASK-007"], s["tasks"]["TASK-008"]
    dev7 = next(r for r in t7["rows"] if r["agent"] == "dev")
    check(abs(dev7["cost_usd"] - (0.5 + 1.0 + 0.05)) < 1e-9,
          "with a price set, cost = tokens × price (applies to past turns too)")
    dev8 = next(r for r in t8["rows"] if r["agent"] == "dev")
    check(abs(dev8["cost_usd"] - 0.05) < 1e-9, "a turn touching two tasks is split between them")
    check(abs(t7["cost_usd"] - (0.16 + 1.55)) < 1e-9, f"TASK-007 total across Tech Lead (Claude) and dev (DeepSeek): {t7['cost_usd']}")
    rev8 = next(r for r in t8["rows"] if r["agent"] == "reviewer")
    check(rev8["unpriced_tokens"] == 4000 and rev8["turns"] == 1, "reviewer's TASK-008 review counted, unpriced (Kimi has no price)")
    check(s["unlinked"]["tokens"] == 2000, "inbox check listing several tasks isn't charged to them: shown as not linked")
    check({m["model"]: m["priced"] for m in s["models"]} ==
          {"claude-opus-5-5": True, "deepseek-v4-pro": True, "kimi-k2-thinking": False},
          "Settings can list which models still need a price")

    # Costs are cached (most pages show them); a new turn, or a new price, still shows at once.
    check(costs.summary() is s, "asking again without a change reuses the last result")
    t7_before = s["tasks"]["TASK-007"]["cost_usd"]
    techlead = next(x["id"] for x in store.list_sessions() if x["agent"] == "techlead")
    store.append_event(techlead, {"ts": store.now(), "agent": "techlead", "session": techlead, "kind": "user",
                                  "text": "One more thing on TASK-007"})
    store.append_event(techlead, {"ts": store.now(), "agent": "techlead", "session": techlead, "kind": "tool",
                                  "name": "Edit", "input": {"file_path": f"{kit}/data/tasks/TASK-007-x.md"}})
    store.append_event(techlead, {"ts": store.now(), "agent": "techlead", "session": techlead, "kind": "result",
                                  "cost_usd": 0.5, "tokens_in": 1, "tokens_out": 1, "turns": 1, "duration_ms": 1})
    after = costs.summary()["tasks"]["TASK-007"]["cost_usd"]
    check(abs(after - (t7_before + 0.5)) < 1e-9, f"a new turn in a conversation is counted at once: {after}")
    store.save_settings({"prices": {"kimi-k2-thinking": {"input": 1, "output": 1}}})
    check(costs.summary()["tasks"]["TASK-008"]["unpriced_tokens"] == 0, "a new price is used at once")
    lines = costs.ledger()["lines"]
    t7 = sum(l["cost_usd"] or 0 for l in lines if l["task"] == "TASK-007")
    check(abs(t7 - costs.summary()["tasks"]["TASK-007"]["cost_usd"]) < 1e-3, f"the ledger adds up to the task's cost: {t7}")
    check(all(l["ts"] and l["agent"] for l in lines), "every line says when and who")
    check(lines == sorted(lines, key=lambda l: l["ts"]), "the ledger is in time order")
    check(costs.ledger() is costs.ledger(), "the ledger is reused until something changes")
    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
