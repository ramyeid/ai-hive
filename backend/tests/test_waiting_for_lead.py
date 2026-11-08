"""An agent that stops without moving any task is waiting for the lead, unless the lead has its chat open
(Home, the sidebar, Slack and the Orchestrator's status show it).

    uv run python -m unittest tests/test_waiting_for_lead.py
"""
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta
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

    def test_a_question_asked_after_the_lead_left_the_chat_is_flagged(self):
        dev, started = self._a_finished_turn(source="console", said="Which branch should I base it on?")
        dev.lead_watching = self._seconds_ago(120)

        dev._check_waiting(started)

        self.assertEqual(dev.waiting_for_lead["text"], "Which branch should I base it on?")

    def test_a_question_asked_while_the_lead_has_the_chat_open_is_not_flagged(self):
        dev, started = self._a_finished_turn(source="console", said="Which branch?")
        dev.lead_watching = self._seconds_ago(5)

        dev._check_waiting(started)

        self.assertIsNone(dev.waiting_for_lead)

    def test_the_orchestrator_is_never_flagged_since_its_turns_are_answers_to_the_lead(self):
        orchestrator, started = self._a_finished_turn(source="console", said="Here's the status.", agent="orchestrator")

        orchestrator._check_waiting(started)

        self.assertIsNone(orchestrator.waiting_for_lead)

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

    def _a_finished_turn(self, source: str, said: str, agent: str = "dev") -> tuple[AgentRunner, str]:
        """An agent that was sent a message about TASK-031 and answered `said`, now idle."""
        dev = AgentRunner(agent, EventBus())
        started = store.now()
        dev.turn_source, dev.turn_task, dev.turn_text, dev.status = source, "TASK-031", said, "idle"
        return dev, started

    def _seconds_ago(self, seconds: int) -> str:
        return (datetime.fromisoformat(store.now()) - timedelta(seconds=seconds)).isoformat(timespec="seconds")

    def _activity(self, task_id: str, to: str, actor: str, at: str) -> None:
        with (board.INBOX / "activity.jsonl").open("a") as f:
            f.write(json.dumps({"ts": at, "id": task_id, "to": to, "actor": actor}) + "\n")


if __name__ == "__main__":
    unittest.main()
