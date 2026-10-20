"""End-to-end checks for both engines, with fake providers (no API keys, no cost).

    .venv/bin/python -m tests.test_engines
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server import store
from server.agents import AgentManager
from server.engines import PROVIDERS
from server.engines.tools import Toolbox
from server.main import TOKEN, create_app
from tests.fake_claude import FakeClient
from tests.fake_openai import fake_openai_transport

H = {"x-token": TOKEN}
checks = 0


def check(condition, what):
    global checks
    checks += 1
    if not condition:
        sys.exit(f"FAIL: {what}")
    print(f"ok  {what}")


def wait(client, agent, predicate, what):
    for _ in range(300):
        info = next(a for a in client.get("/api/state", headers=H).json()["agents"] if a["name"] == agent)
        if predicate(info):
            return info
        time.sleep(0.03)
    sys.exit(f"FAIL: timed out waiting for {what}: {info}")


def events(client, session_id):
    return client.get(f"/api/sessions/{session_id}", headers=H).json()["events"]


def main():
    workspace = Path(tempfile.mkdtemp())
    (workspace / "README.md").write_text("# demo\n")
    log = []
    app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport(log)))
    with TestClient(app, base_url="http://127.0.0.1:8420") as c:
        c.put("/api/settings", json={"workspace": str(workspace)}, headers=H)

        # --- provider keys are stored but never shown ---------------------------------
        secret = "sk-test-SECRET-9f3a"
        c.put("/api/providers/deepseek", json={"api_key": secret}, headers=H)
        state = c.get("/api/state", headers=H)
        check(secret not in state.text, "API key never sent to the browser")
        deepseek = next(p for p in state.json()["settings"]["providers"] if p["id"] == "deepseek")
        check(deepseek["has_key"] and deepseek["key_hint"] == "9f3a", "browser sees only that a key exists and its last 4 characters")
        check(c.put("/api/providers/claude", json={"api_key": "x"}, headers=H).status_code == 404, "Claude has no key field (uses Claude Code's login)")

        # --- choosing provider and model ------------------------------------------------
        r = c.put("/api/agents/dev/config", json={"provider": "deepseek", "model": "deepseek-v4-pro"}, headers=H)
        check({k: r.json()["agents"]["dev"][k] for k in ("provider", "model")} == {"provider": "deepseek", "model": "deepseek-v4-pro"}, "dev set to DeepSeek")
        r = c.post("/api/agents/kimi/start", json={}, headers=H)
        check(r.status_code == 404, "unknown agent rejected")
        r = c.put("/api/agents/pm/config", json={"provider": "kimi", "model": ""}, headers=H)
        r = c.post("/api/agents/pm/start", json={}, headers=H)
        check(r.status_code == 409 and "API key" in r.json()["detail"], f"starting without a key explains what's missing ({r.json()['detail']})")

        # --- a full streamed turn on DeepSeek -------------------------------------------
        c.post("/api/agents/dev/message", json={"text": "check the repo"}, headers=H)
        check(c.put("/api/agents/dev/config", json={"provider": "qwen", "model": "x"}, headers=H).status_code == 409,
              "can't switch provider while the agent is running")
        info = wait(c, "dev", lambda a: a["pending"], "approval request")
        check(info["provider"] == "deepseek" and info["model"] == "deepseek-v4-pro", "running agent reports its provider and model")
        check(info["pending"][0]["tool"] == "Bash" and info["pending"][0]["input"]["command"] == "echo hello",
              "Glob ran without asking; Bash waits for approval")
        c.post(f"/api/agents/dev/permissions/{info['pending'][0]['id']}", json={"decision": "allow"}, headers=H)
        wait(c, "dev", lambda a: a["status"] == "idle", "turn to finish")
        sid = info["session_id"]
        kinds = [e["kind"] for e in events(c, sid)]
        check(kinds == ["init", "system", "user", "thinking", "text", "tool", "tool_result", "tool",
                        "permission", "decision", "tool_result", "text", "result"], f"event sequence: {kinds}")
        ev = events(c, sid)
        glob_result = next(e for e in ev if e["kind"] == "tool_result")
        check("README.md" in glob_result["text"], "Glob really listed the workspace")
        bash_result = [e for e in ev if e["kind"] == "tool_result"][1]
        check(bash_result["text"] == "hello" and not bash_result["is_error"], "Bash really ran after approval")
        result = ev[-1]
        check(result["tokens_in"] == 360 and result["tokens_out"] == 90, "token usage counted across the 3 model calls")
        meta = next(s for s in c.get("/api/sessions", headers=H).json() if s["id"] == sid)
        check(meta["provider"] == "deepseek" and meta["model"] == "deepseek-v4-pro" and meta["tokens"] == 450, "history records provider, model and tokens")

        first = log[0]
        check(first["url"] == "https://api.deepseek.com/chat/completions", "DeepSeek address used")
        check(first["auth"] == f"Bearer {secret}", "key sent as a Bearer token")
        check(first["body"]["stream"] and {t["function"]["name"] for t in first["body"]["tools"]} ==
              {"Read", "Write", "Edit", "Glob", "Grep", "Bash"}, "streams, and offers the six tools")
        check("dev agent" in first["body"]["messages"][0]["content"] and "Developer" in first["body"]["messages"][0]["content"],
              "system prompt = the dev's instructions + how it runs")
        second = log[1]["body"]["messages"]
        check(second[2].get("reasoning_content") and second[2]["tool_calls"][0]["function"]["name"] == "Glob",
              "reasoning echoed back with the tool call (DeepSeek/Kimi need this)")
        check(second[3]["role"] == "tool" and second[3]["tool_call_id"] == "call_glob", "tool result sent back")
        check("stream_options" not in first["body"], "no stream_options for providers that may not support it")

        # --- resume from history ---------------------------------------------------------------
        c.post("/api/agents/dev/stop", headers=H)
        c.put("/api/agents/dev/config", json={"provider": "claude", "model": ""}, headers=H)
        r = c.post("/api/agents/dev/start", json={"resume": sid}, headers=H).json()
        check(r["provider"] == "deepseek", "resuming uses the session's own provider, not the current setting")
        before = len(log)
        c.post("/api/agents/dev/message", json={"text": "again"}, headers=H)
        info = wait(c, "dev", lambda a: a["pending"], "approval after resume")
        check(any(m.get("content") == "check the repo" for m in log[before]["body"]["messages"]),
              "resumed conversation includes the earlier messages")

        # --- interrupt while waiting for approval ---------------------------------------------
        c.post("/api/agents/dev/interrupt", headers=H)
        wait(c, "dev", lambda a: a["status"] == "idle", "idle after interrupt")
        saved = store.load_messages(sid)
        open_calls = {tc["id"] for m in saved if m.get("tool_calls") for tc in m["tool_calls"]}
        answered = {m["tool_call_id"] for m in saved if m["role"] == "tool"}
        check(open_calls <= answered, "after an interrupt every tool call has an answer (conversation stays valid)")
        c.post("/api/agents/dev/message", json={"text": "continue"}, headers=H)
        wait(c, "dev", lambda a: a["pending"], "agent usable after interrupt")
        c.post("/api/agents/dev/stop", headers=H)

        # --- Qwen: no streaming with tools, deny path ------------------------------------
        c.put("/api/providers/qwen", json={"api_key": "qk", "base_url": "https://example-ws.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"}, headers=H)
        c.put("/api/agents/reviewer/config", json={"provider": "qwen", "model": "qwen-max"}, headers=H)
        before = len(log)
        c.post("/api/agents/reviewer/message", json={"text": "review"}, headers=H)
        info = wait(c, "reviewer", lambda a: a["pending"], "Qwen approval")
        c.post(f"/api/agents/reviewer/permissions/{info['pending'][0]['id']}", json={"decision": "deny", "message": "not now"}, headers=H)
        wait(c, "reviewer", lambda a: a["status"] == "idle", "Qwen turn finished")
        check(log[before]["url"].startswith("https://example-ws.ap-southeast-1") and "stream" not in log[before]["body"],
              "Qwen uses your region's address and doesn't stream")
        ev = events(c, info["session_id"])
        denied = [e for e in ev if e["kind"] == "tool_result"][1]
        check(denied["is_error"] and "not now" in denied["text"], "denial and reason reach the model")
        c.post("/api/agents/reviewer/stop", headers=H)

        # --- provider errors are explained -------------------------------------------------
        c.put("/api/agents/pm/config", json={"provider": "deepseek", "model": "missing-model"}, headers=H)
        c.post("/api/agents/pm/message", json={"text": "hi"}, headers=H)
        wait(c, "pm", lambda a: a["status"] == "idle", "pm error turn")
        err = [e for e in events(c, c.get("/api/state", headers=H).json()["agents"][0]["session_id"]) if e["kind"] == "error"]
        check(err and "404" in err[0]["text"] and "model name" in err[0]["text"], "a wrong model name gives a clear error")
        c.post("/api/agents/pm/stop", headers=H)

        # --- Claude still works through the same interface ----------------------------------
        c.put("/api/agents/dev/config", json={"provider": "claude", "model": ""}, headers=H)
        c.post("/api/agents/dev/message", json={"text": "hello claude"}, headers=H)
        info = wait(c, "dev", lambda a: a["pending"], "Claude approval")
        check(info["provider"] == "claude" and info["model"] == "sonnet", "Claude uses the agent file's model by default")
        c.post(f"/api/agents/dev/permissions/{info['pending'][0]['id']}", json={"decision": "allow"}, headers=H)
        wait(c, "dev", lambda a: a["status"] == "idle", "Claude turn")
        c.post("/api/agents/dev/stop", headers=H)

    # --- tools: approval rules and the task hook ---------------------------------------------
    kit = store.KIT
    box = Toolbox(workspace, kit)
    check(not box.needs_approval("Read", {"file_path": str(workspace / "README.md")}, "default"), "reading in the workspace: no approval")
    check(box.needs_approval("Read", {"file_path": "/etc/passwd"}, "default"), "reading outside workspace and kit: ask")
    check(box.needs_approval("Edit", {"file_path": str(workspace / "a.py")}, "default"), "editing code: ask")
    check(not box.needs_approval("Edit", {"file_path": str(workspace / "a.py")}, "acceptEdits"), "editing code with 'Allow automatically': no approval")
    check(not box.needs_approval("Bash", {"command": f"python3 {kit}/scripts/inbox.py dev"}, "default"), "kit scripts: no approval")
    check(box.needs_approval("Bash", {"command": f"python3 {kit}/scripts/inbox.py dev; rm -rf /"}, "default"), "kit script + anything else: ask")

    async def task_hook():
        project = workspace / "proj"
        subprocess.run(["git", "init", "-q", str(project)], check=True)
        path = Path(subprocess.run([sys.executable, str(kit / "scripts/new_task.py"), str(project), "Hook test"],
                                   capture_output=True, text=True, check=True).stdout.strip())
        out, is_error = await box.run("Edit", {"file_path": str(path), "old_string": "status: draft", "new_string": "status: ready-for-dev"})
        check("BLOCKED" in out and "status: draft" in path.read_text(), "task hook runs: unready spec bounced back to draft")
        path.unlink()
        out, is_error = await box.run("Edit", {"file_path": str(workspace / "README.md"), "old_string": "nope", "new_string": "x"})
        check(is_error and "not found" in out, "Edit explains a missing match")
        out, is_error = await box.run("Bash", {"command": "sleep 5", "timeout": 1})
        check(is_error and "timed out" in out, "Bash commands time out")
    asyncio.run(task_hook())

    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
