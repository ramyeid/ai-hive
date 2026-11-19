"""Cancelling a task (and reopening it): from the task page, or by the Orchestrator once the lead allows it.

    uv run python -m unittest tests/test_cancel_task.py
"""
import shutil
import tempfile
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from hive import board, store
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

import board as board_tool  # noqa: E402  (the team's tools, on the path via the server)
import on_task_change  # noqa: E402
import tasklib  # noqa: E402

PAGE = {"x-token": TOKEN}


class CancelTaskTest(unittest.TestCase):

    def test_cancel_records_when_and_why_and_tells_whoever_had_it(self):
        client = self._a_console()
        self._a_task("in-dev", dev="dev")

        got = client.post("/api/tasks/TASK-001/cancel", json={"reason": "The client dropped it."}, headers=PAGE)

        self.assertEqual(got.status_code, 200, got.text)
        task = client.get("/api/tasks/TASK-001", headers=PAGE).json()
        self.assertEqual(task["status"], "cancelled")
        self.assertEqual(task["cancelled"], store.now()[:10])
        self.assertIn("## Cancelled\n", task["markdown"])
        self.assertIn("by the lead, from in-dev: The client dropped it.", task["markdown"])
        self.assertEqual((task["activity"][0]["to"], task["activity"][0]["actor"]), ("cancelled", "lead"))
        inbox = (tasklib.INBOX / "agents" / "dev.md").read_text()
        self.assertIn("**TASK-001**", inbox)
        self.assertIn("`cancelled`", inbox)

    def test_an_agent_working_on_it_stops_and_is_told_why(self):
        client = self._a_console()
        self._a_task("in-dev", dev="dev")
        client.post("/api/agents/dev/message", json={"text": "Work on TASK-001"}, headers=PAGE)
        self._wait_for(client, "dev", "waiting")   # the fake agent asks to run a command

        client.post("/api/tasks/TASK-001/cancel", json={"reason": "Not needed."}, headers=PAGE)

        self.assertIn("The lead cancelled TASK-001 (Total): Not needed.", self.client_prompt())

    def test_done_or_cancelled_tasks_cannot_be_cancelled(self):
        client = self._a_console()
        self._a_task("done")

        got = client.post("/api/tasks/TASK-001/cancel", json={}, headers=PAGE)

        self.assertEqual(got.status_code, 409)
        self.assertIn("already done", got.json()["detail"])

    def test_reopen_brings_back_an_approved_spec_ready_for_a_dev(self):
        client = self._a_console()
        self._a_task("ready-for-dev", approved="2026-11-18")
        client.post("/api/tasks/TASK-001/cancel", json={}, headers=PAGE)
        import check_ready
        self.addCleanup(setattr, check_ready, "check", check_ready.check)
        check_ready.check = lambda path: []   # a spec that still passes the readiness check

        got = client.post("/api/tasks/TASK-001/reopen", headers=PAGE)

        self.assertEqual(got.json()["message"], "Reopened TASK-001: ready for a dev.")
        task = client.get("/api/tasks/TASK-001", headers=PAGE).json()
        self.assertEqual((task["status"], task["cancelled"]), ("ready-for-dev", ""))

    def test_reopen_says_so_when_the_spec_no_longer_passes_the_readiness_check(self):
        client = self._a_console()
        self._a_task("ready-for-dev", approved="2026-11-18")
        client.post("/api/tasks/TASK-001/cancel", json={}, headers=PAGE)

        got = client.post("/api/tasks/TASK-001/reopen", headers=PAGE).json()["message"]

        self.assertIn("as a draft: its spec no longer passes the readiness check", got)
        self.assertEqual(client.get("/api/tasks/TASK-001", headers=PAGE).json()["status"], "draft")

    def test_reopen_an_unapproved_one_as_a_draft(self):
        client = self._a_console()
        self._a_task("draft")
        client.post("/api/tasks/TASK-001/cancel", json={}, headers=PAGE)

        self.assertEqual(client.post("/api/tasks/TASK-001/reopen", headers=PAGE).json()["message"],
                         "Reopened TASK-001: a draft, with the Tech Lead.")

    def test_the_orchestrator_lists_no_cancelled_tasks(self):
        client = self._a_console()
        self._a_task("ready-for-dev")
        client.post("/api/tasks/TASK-001/cancel", json={}, headers=PAGE)

        from hive.agents import ORCHESTRATOR_KEY
        status = client.get("/api/orchestrator/status", headers={"x-orchestrator": ORCHESTRATOR_KEY}).json()

        self.assertEqual(status["tasks"], [])
        self.assertEqual(status["waiting_on_a_hand_off"], [])

    # ---- helpers ----------------------------------------------------------------------

    def client_prompt(self) -> str:
        for _ in range(100):
            if FakeClient.last_prompt and "cancelled" in FakeClient.last_prompt:
                break
            time.sleep(0.1)
        return FakeClient.last_prompt or ""

    def _a_console(self) -> TestClient:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        inbox = root / "tasks" / ".inbox"
        inbox.mkdir(parents=True)
        for module, name, value in ((tasklib, "TASKS", root / "tasks"), (tasklib, "INBOX", inbox), (tasklib, "STATE", inbox / ".state.json"),
                                    (on_task_change, "INBOX", inbox), (on_task_change, "TASKS", root / "tasks"),
                                    (board_tool, "TASKS", root / "tasks"), (board, "INBOX", inbox), (store, "SETTINGS", root / "settings.json")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        FakeClient.last_prompt = None
        original_query = FakeClient.query

        async def query(fake, prompt):
            FakeClient.last_prompt = prompt
            await original_query(fake, prompt)
        FakeClient.query = query
        self.addCleanup(setattr, FakeClient, "query", original_query)
        client = TestClient(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))),
                            base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.addCleanup(lambda: client.post("/api/agents/dev/stop", headers=PAGE))
        return client

    def _a_task(self, status: str, dev: str = "", approved: str = "") -> None:
        path = tasklib.TASKS / "TASK-001-total.md"
        path.write_text(f"---\nid: TASK-001\ntitle: Total\nstatus: {status}\nproject: /tmp/shop\nbase: main\nbranch: feature-total\n"
                        f"from_commit: abc\ndev: {dev}\nreviewer:\napproved: {approved}\n---\n\n## Problem / Goal\nTotals.\n")
        state = tasklib.load_state()
        state["TASK-001"] = status
        tasklib.save_state(state)

    def _wait_for(self, client: TestClient, agent: str, status: str) -> None:
        for _ in range(300):
            if next(a for a in client.get("/api/state", headers=PAGE).json()["agents"] if a["name"] == agent)["status"] == status:
                return
            time.sleep(0.05)
        self.fail(f"{agent} never became {status}.")


if __name__ == "__main__":
    unittest.main()
