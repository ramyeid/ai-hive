"""An agent that stops on work handed to it without moving the task is waiting for the lead
(Home, the sidebar, Slack and the Orchestrator's status show it).

    uv run python -m unittest tests/test_waiting_for_lead.py
"""
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from hive import board, ops, store
from hive.agents import AgentManager, AgentRunner, EventBus
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport


class WaitingForLeadTest(unittest.TestCase):

    def setUp(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / ".inbox").mkdir()
        self.addCleanup(setattr, board, "INBOX", board.INBOX)
        board.INBOX = root / ".inbox"

    def test_an_agent_that_stops_on_handed_work_without_moving_the_task_is_waiting_for_the_lead(self):
        dev, started = self._a_finished_turn(source="team", said="Please switch your project folder to main.")

        dev._check_waiting(started)

        self.assertEqual(dev.waiting_for_lead["task"], "TASK-031")
        self.assertEqual(dev.waiting_for_lead["text"], "Please switch your project folder to main.")
        self.assertEqual(dev.info()["waiting_for_lead"], dev.waiting_for_lead)

    def test_it_is_announced_on_the_bus_so_slack_can_post_it(self):
        dev, started = self._a_finished_turn(source="team", said="Please switch your project folder to main.")
        queue = dev.bus.subscribe()

        dev._check_waiting(started)

        events = [queue.get_nowait() for _ in range(queue.qsize())]
        self.assertIn(("waiting_for_lead", "dev", "TASK-031"), [(e["kind"], e.get("agent"), e.get("task")) for e in events])

    def test_an_agent_that_moved_a_task_during_its_turn_is_not_waiting(self):
        dev, started = self._a_finished_turn(source="team", said="Done, ready for review.")
        self._activity("TASK-031", "ready-for-review", actor="dev", at=store.now())

        dev._check_waiting(started)

        self.assertIsNone(dev.waiting_for_lead)

    def test_a_turn_the_lead_started_in_the_chat_is_not_flagged(self):
        dev, started = self._a_finished_turn(source="console", said="Which branch?")

        dev._check_waiting(started)

        self.assertIsNone(dev.waiting_for_lead)

    def test_a_turn_from_slack_is_not_flagged_since_its_answer_goes_back_to_the_thread(self):
        dev, started = self._a_finished_turn(source="slack", said="Which branch?")

        dev._check_waiting(started)

        self.assertIsNone(dev.waiting_for_lead)

    def test_an_interrupted_turn_is_not_flagged(self):
        dev, started = self._a_finished_turn(source="team", said="Working on it…")
        dev.interrupted = True

        dev._check_waiting(started)

        self.assertIsNone(dev.waiting_for_lead)

    def test_the_orchestrators_status_names_the_task_the_agent_stopped_on(self):
        manager = AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))
        dev, started = self._a_finished_turn(source="team", said="Please switch your project folder to main.")
        manager.agents["dev"] = dev
        dev._check_waiting(started)

        team = {a["id"]: a for a in ops.agents(manager)}

        self.assertEqual(team["dev"]["stopped_for_you"]["task"], "TASK-031")
        self.assertIn("switch your project folder", team["dev"]["stopped_for_you"]["said"])

    # ---- helpers ----------------------------------------------------------------------

    def _a_finished_turn(self, source: str, said: str) -> tuple[AgentRunner, str]:
        """A dev that was sent a message about TASK-031 and answered `said`, now idle."""
        dev = AgentRunner("dev", EventBus())
        started = store.now()
        dev.turn_source, dev.turn_task, dev.turn_text, dev.status = source, "TASK-031", said, "idle"
        return dev, started

    def _activity(self, task_id: str, to: str, actor: str, at: str) -> None:
        with (board.INBOX / "activity.jsonl").open("a") as f:
            f.write(json.dumps({"ts": at, "id": task_id, "to": to, "actor": actor}) + "\n")


if __name__ == "__main__":
    unittest.main()
