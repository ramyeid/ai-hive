"""The Orchestrator's controls: the board in short, and team actions that wait for the lead's approval.

    uv run python -m unittest tests/test_orchestrator.py
"""
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from hive import main, store
from hive.agents import ORCHESTRATOR_KEY, AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

import tasklib  # noqa: E402  (the team's tools, on the path via the server)

PAGE = {"x-token": TOKEN}
ORCHESTRATOR = {"x-orchestrator": ORCHESTRATOR_KEY}


class OrchestratorTest(unittest.TestCase):

    def test_an_action_happens_only_after_the_lead_allows_it(self):
        client = self._a_console()
        request = self._the_orchestrator_asks(client, {"action": "start", "agent": "dev"})

        self._the_lead_answers(client, "allow")

        self.assertEqual(request.result()["done"], True)
        self.assertEqual(self._status_of(client, "dev"), "idle")

    def test_a_denied_action_does_not_happen(self):
        client = self._a_console()
        request = self._the_orchestrator_asks(client, {"action": "start", "agent": "dev"})

        self._the_lead_answers(client, "deny")

        self.assertEqual(request.result()["done"], False)
        self.assertEqual(self._status_of(client, "dev"), "stopped")

    def test_rework_can_only_be_handed_to_the_dev_who_built_it(self):
        client = self._a_console()
        self._a_task("changes-requested", dev="dev")
        client.post("/api/agents", json={"role": "dev"}, headers=PAGE)

        response = client.post("/api/orchestrator/act", json={"action": "hand", "task": "TASK-001", "agent": "dev-2"},
                               headers=ORCHESTRATOR)

        self.assertEqual(response.status_code, 409)
        self.assertIn("rework goes back to the dev who built it", response.json()["detail"])

    def test_the_status_lists_a_task_waiting_for_review_with_its_review_link(self):
        client = self._a_console()
        self._a_task("ready-for-review", dev="dev")

        status = client.get("/api/orchestrator/status", headers=ORCHESTRATOR).json()

        waiting = status["waiting_on_a_hand_off"][0]
        self.assertEqual((waiting["id"], waiting["next"]), ("TASK-001", "reviewer"))
        self.assertEqual(waiting["review"], "http://localhost:8420/#/tasks/TASK-001/review")

    def test_links_use_the_console_address_from_settings(self):
        client = self._a_console()
        self._a_task("ready-for-review", dev="dev")
        client.put("/api/settings/console-url", json={"console_url": "http://hive.internal:8420/"}, headers=PAGE)

        status = client.get("/api/orchestrator/status", headers=ORCHESTRATOR).json()

        self.assertEqual(status["tasks"][0]["link"], "http://hive.internal:8420/#/tasks/TASK-001")

    def test_the_orchestrators_controls_refuse_the_pages_key(self):
        client = self._a_console()

        response = client.get("/api/orchestrator/status", headers=PAGE)

        self.assertEqual(response.status_code, 401)

    def test_only_the_orchestrator_is_given_the_key(self):
        client = self._a_console()

        keys = {agent: self._key_given_to(client, agent) for agent in ("orchestrator", "dev")}

        self.assertEqual(keys, {"orchestrator": ORCHESTRATOR_KEY, "dev": None})

    # ---- helpers ----------------------------------------------------------------------

    def _a_console(self) -> TestClient:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "tasks" / ".inbox").mkdir(parents=True)
        for module, name, value in ((tasklib, "TASKS", root / "tasks"), (tasklib, "INBOX", root / "tasks" / ".inbox"),
                                    (store, "SETTINGS", root / "settings.json"), (main, "APPROVAL_WAIT", 20)):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        client = TestClient(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))),
                            base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        self.addCleanup(lambda: [client.post(f"/api/agents/{a}/stop", headers=PAGE) for a in ("orchestrator", "dev", "dev-2")])
        return client

    def _a_task(self, status: str, dev: str = "") -> None:
        (tasklib.TASKS / "TASK-001-total.md").write_text(
            f"---\nid: TASK-001\ntitle: Total\nstatus: {status}\nproject: /tmp/shop\nbase: main\nbranch: feature-total\n"
            f"from_commit: abc\ndev: {dev}\nreviewer:\n---\n")

    def _the_orchestrator_asks(self, client: TestClient, body: dict):
        result = {}
        worker = threading.Thread(target=lambda: result.update(client.post("/api/orchestrator/act", json=body, headers=ORCHESTRATOR).json()))
        worker.start()

        class Pending:
            def result(self):
                worker.join(15)
                return result
        return Pending()

    def _the_lead_answers(self, client: TestClient, decision: str) -> None:
        for _ in range(200):
            pending = self._agent(client, "orchestrator")["pending"]
            if pending:
                client.post(f"/api/agents/orchestrator/permissions/{pending[0]['id']}", json={"decision": decision}, headers=PAGE)
                return
            time.sleep(0.02)
        self.fail("The Orchestrator never asked the lead.")

    def _agent(self, client: TestClient, name: str) -> dict:
        return next(a for a in client.get("/api/state", headers=PAGE).json()["agents"] if a["name"] == name)

    def _status_of(self, client: TestClient, name: str) -> str:
        return self._agent(client, name)["status"]

    def _key_given_to(self, client: TestClient, agent: str):
        FakeClient.last_options = None
        client.post(f"/api/agents/{agent}/start", json={}, headers=PAGE)
        for _ in range(200):
            if FakeClient.last_options is not None:
                break
            time.sleep(0.02)
        return FakeClient.last_options.env.get("CONSOLE_ORCHESTRATOR_KEY")


if __name__ == "__main__":
    unittest.main()
