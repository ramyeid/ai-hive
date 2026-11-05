"""Checks adding and removing agents (several per role), with a fake Claude (no cost).

    uv run python -m tests.test_team
"""
import shutil
import sys
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from server import store
from server.agents import AgentManager
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


def main():
    backup = Path(tempfile.mkdtemp()) / "settings.json"
    had_settings = store.SETTINGS.exists()
    if had_settings:
        shutil.copy(store.SETTINGS, backup)
    try:
        run()
    finally:
        if had_settings:
            shutil.copy(backup, store.SETTINGS)
        else:
            store.SETTINGS.unlink(missing_ok=True)
    print(f"\nAll {checks} checks passed.")


def names(c):
    return [a["name"] for a in c.get("/api/state", headers=H).json()["agents"]]


def run():
    store.SETTINGS.unlink(missing_ok=True)
    app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
    with TestClient(app, base_url="http://127.0.0.1:8420") as c:
        check(names(c) == ["techlead", "dev", "reviewer", "coach"], "a fresh install has one agent per role, and the Coach")

        for role in ["techlead", "dev", "dev", "reviewer"]:
            r = c.post("/api/agents", json={"role": role}, headers=H)
            check(r.status_code == 200, f"added a {role}: {r.json().get('id')}")
        check(names(c) == ["techlead", "techlead-2", "dev", "dev-2", "dev-3", "reviewer", "reviewer-2", "coach"],
              "two Tech Leads, three devs, two reviewers, listed by role")
        state = c.get("/api/state", headers=H).json()
        check(next(a for a in state["agents"] if a["name"] == "dev-3")["role"] == "dev", "each agent reports its role")
        check(c.post("/api/agents", json={"role": "qa"}, headers=H).status_code == 400, "unknown roles are refused")

        # Each agent has its own provider and model.
        c.put("/api/agents/dev-2/config", json={"provider": "deepseek", "model": "deepseek-chat"}, headers=H)
        agents = store.load_settings()["agents"]
        check({k: agents["dev-2"][k] for k in ("role", "provider", "model")} == {"role": "dev", "provider": "deepseek", "model": "deepseek-chat"}
              and agents["dev"]["provider"] == "claude", "changing dev-2's model leaves dev alone and keeps its role")

        # The agent knows who it is.
        c.post("/api/agents/dev-3/start", json={}, headers=H)
        for _ in range(200):
            if FakeClient.last_options is not None:
                break
            time.sleep(0.02)
        opts = FakeClient.last_options
        check(opts is not None and opts.env.get("AGENT_ID") == "dev-3", "dev-3 runs with AGENT_ID=dev-3")
        check("dev-3" in (opts.system_prompt if isinstance(opts.system_prompt, str) else str(opts.system_prompt)),
              "dev-3's instructions name its agent ID")

        check(c.delete("/api/agents/dev-3", headers=H).status_code == 409, "a running agent can't be removed")
        c.post("/api/agents/dev-3/stop", headers=H)
        check(c.delete("/api/agents/dev-3", headers=H).status_code == 200, "a stopped agent can be removed")
        check("dev-3" not in names(c) and "dev-3" not in store.load_settings()["agents"], "it's gone from the team and settings")

        c.delete("/api/agents/techlead-2", headers=H)
        r = c.delete("/api/agents/techlead", headers=H)
        check(r.status_code == 409 and "at least one techlead" in r.json()["detail"], "the last Tech Lead can't be removed")
        check(c.post("/api/agents", json={"role": "dev"}, headers=H).json()["id"] == "dev-3", "freed numbers are reused")
        check(c.post("/api/agents/nobody/start", json={}, headers=H).status_code == 404, "unknown agents are refused")

        # Names: every agent gets a different one from the pool, and can be renamed.
        agents = store.load_settings()["agents"]
        given = [a["name"] for a in agents.values()]
        check(all(n in store.NAMES for n in given) and len(set(given)) == len(given),
              f"every agent has its own name from the pool ({', '.join(given)})")
        check(store.load_settings()["agents"] == agents, "names are kept, not re-drawn on every load")
        check(c.put("/api/agents/dev/name", json={"name": "  Kareem  "}, headers=H).json()["agents"]["dev"]["name"] == "Kareem",
              "dev renamed to Kareem")
        r = c.put("/api/agents/techlead/name", json={"name": "kareem"}, headers=H)
        check(r.status_code == 400 and "already" in r.json()["detail"], "two agents can't share a name")
        check(c.put("/api/agents/techlead/name", json={"name": " "}, headers=H).status_code == 400, "empty names are refused")
        check(store.load_settings()["agents"]["dev"]["role"] == "dev", "renaming keeps the role")
        c.put("/api/agents/dev/config", json={"provider": "claude", "model": ""}, headers=H)
        check(store.load_settings()["agents"]["dev"]["name"] == "Kareem", "changing the model keeps the name")
        c.post("/api/agents/dev/start", json={}, headers=H)
        for _ in range(200):
            if "Kareem" in str(FakeClient.last_options.system_prompt):
                break
            time.sleep(0.02)
        check("Your name is Kareem" in str(FakeClient.last_options.system_prompt), "the agent is told its name")
        c.post("/api/agents/dev/stop", headers=H)


if __name__ == "__main__":
    main()
