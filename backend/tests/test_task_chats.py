"""Each task's conversations (for the lead's debugging), and a fresh conversation after every hand-off.

    uv run python -m unittest tests/test_task_chats.py
"""
import json
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from hive import board, chats, store  # puts the team's tools on the path
import tasklib  # noqa: E402
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

HEADERS = {"x-token": TOKEN}


class TaskChatsTest(unittest.TestCase):

    def test_a_conversation_is_saved_in_the_folder_of_the_task_it_worked_on(self):
        self._an_empty_board()
        session = self._a_conversation("dev", [("Work on TASK-007", 0.25)])

        chats.archive(session)

        saved = self._saved("TASK-007")
        self.assertEqual(len(saved), 1)
        self.assertEqual((saved[0]["agent"], saved[0]["turns"], saved[0]["cost_usd"]), ("dev", 1, 0.25))
        self.assertTrue(Path(str(self._chat_files("TASK-007")[0]).replace(".json", ".md")).exists())

    def test_a_conversation_on_two_tasks_is_split_between_them(self):
        self._an_empty_board()
        session = self._a_conversation("dev", [("Work on TASK-007", 0.25), ("Now TASK-008", 0.5)])

        chats.archive(session)

        self.assertEqual(self._saved("TASK-007")[0]["cost_usd"], 0.25)
        self.assertEqual(self._saved("TASK-008")[0]["cost_usd"], 0.5)

    def test_the_saved_conversation_records_the_hand_off_the_agent_made(self):
        self._an_empty_board()
        session = self._a_conversation("dev", [("Work on TASK-007", 0.25)])
        self._activity("TASK-007", "ready-for-review", actor="dev", at=self._during(session))

        chats.archive(session)

        self.assertEqual(self._saved("TASK-007")[0]["outcome"], "ready-for-review")

    def test_handing_a_task_on_during_a_turn_starts_the_agent_on_a_fresh_conversation(self):
        self._an_empty_board()
        client = self._a_console()
        first = self._a_dev_turn_that_hands_off(client, "TASK-007", handoff=True)

        current = self._wait_for_a_new_session(client, "dev", first)

        self.assertNotEqual(current, first)
        self.assertEqual([c["session"] for c in self._saved("TASK-007")], [first])

    def test_a_turn_without_a_hand_off_keeps_the_conversation(self):
        self._an_empty_board()
        client = self._a_console()
        first = self._a_dev_turn_that_hands_off(client, "TASK-007", handoff=False)

        time.sleep(0.5)

        self.assertEqual(self._agent(client, "dev")["session_id"], first)

    def test_the_task_page_lists_saved_and_running_conversations(self):
        self._an_empty_board()
        client = self._a_console()
        saved = self._a_conversation("techlead", [("Spec TASK-007", 0.1)])
        chats.archive(saved)
        running = self._a_dev_turn_that_hands_off(client, "TASK-007", handoff=False)

        listed = client.get("/api/tasks/TASK-007/chats", headers=HEADERS).json()

        self.assertEqual([(c["agent"], c["live"]) for c in listed], [("techlead", False), ("dev", True)])
        self.assertEqual(listed[1]["session"], running)

    def test_a_conversation_name_that_is_not_a_saved_file_is_refused(self):
        self._an_empty_board()
        client = self._a_console()

        response = client.get("/api/tasks/TASK-007/chats/..%2F..%2FBOARD", headers=HEADERS)

        self.assertEqual(response.status_code, 404)

    # ---- helpers ----------------------------------------------------------------------

    def _an_empty_board(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        tasks = root / "tasks"
        (tasks / ".inbox").mkdir(parents=True)
        for task_id in ("TASK-007", "TASK-008"):
            (tasks / f"{task_id}-x.md").write_text(f"---\nid: {task_id}\ntitle: Task\nstatus: in-dev\nproject: /p\n---\n")
        self._patch(tasklib, "TASKS", tasks)
        self._patch(board, "INBOX", tasks / ".inbox")
        self._patch(chats, "CHATS", tasks / "chats")
        self._patch(store, "SESSIONS", root / "sessions")
        self._patch(store, "INDEX", root / "sessions" / "index.json")
        self._patch(store, "SETTINGS", root / "settings.json")

    def _patch(self, module, name: str, value) -> None:
        self.addCleanup(setattr, module, name, getattr(module, name))
        setattr(module, name, value)

    def _a_conversation(self, agent: str, turns: list[tuple[str, float]]) -> str:
        session = store.new_session(agent, "claude", "sonnet")
        for message, cost in turns:
            store.append_event(session, {"ts": store.now(), "kind": "user", "text": message})
            store.append_event(session, {"ts": store.now(), "kind": "text", "text": "On it."})
            store.append_event(session, {"ts": store.now(), "kind": "result", "cost_usd": cost})
        return session

    def _during(self, session: str) -> str:
        return store.read_events(session)[0]["ts"]

    def _activity(self, task_id: str, to: str, actor: str, at: str) -> None:
        with (board.INBOX / "activity.jsonl").open("a") as f:
            f.write(json.dumps({"ts": at, "id": task_id, "to": to, "actor": actor}) + "\n")

    def _a_console(self) -> TestClient:
        app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
        client = TestClient(app, base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def _a_dev_turn_that_hands_off(self, client: TestClient, task_id: str, handoff: bool) -> str:
        client.post("/api/agents/dev/start", json={}, headers=HEADERS)
        client.post("/api/agents/dev/message", json={"text": f"Work on {task_id}"}, headers=HEADERS)
        agent = self._wait(client, "dev", lambda a: a["pending"])
        if handoff:
            self._activity(task_id, "ready-for-review", actor="dev", at=store.now())
        client.post(f"/api/agents/dev/permissions/{agent['pending'][0]['id']}", json={"decision": "allow"}, headers=HEADERS)
        self._wait(client, "dev", lambda a: a["status"] == "idle" and not a["pending"])
        return agent["session_id"]

    def _wait_for_a_new_session(self, client: TestClient, name: str, old: str) -> str:
        return self._wait(client, name, lambda a: a["session_id"] not in (None, old) and a["status"] == "idle")["session_id"]

    def _wait(self, client: TestClient, name: str, condition) -> dict:
        deadline = datetime.now() + timedelta(seconds=15)
        while datetime.now() < deadline:
            agent = self._agent(client, name)
            if condition(agent):
                return agent
            time.sleep(0.05)
        self.fail(f"timed out waiting for {name}: {agent}")

    def _agent(self, client: TestClient, name: str) -> dict:
        return next(a for a in client.get("/api/state", headers=HEADERS).json()["agents"] if a["name"] == name)

    def _chat_files(self, task_id: str) -> list[Path]:
        return sorted((chats.CHATS / task_id).glob("*.json"))

    def _saved(self, task_id: str) -> list[dict]:
        return [json.loads(p.read_text()) for p in self._chat_files(task_id)]


if __name__ == "__main__":
    unittest.main()
