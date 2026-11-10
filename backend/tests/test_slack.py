"""Slack: messages to the Orchestrator or a named agent, approvals with buttons, and task threads.
Uses a stand-in for Slack's web client, so nothing connects to Slack.

    uv run python -m unittest tests/test_slack.py
"""
import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from hive import slack, store, team
from hive.agents import AgentManager
from hive.slack import SlackBridge, to_mrkdwn
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

import coach as kit_coach  # noqa: E402  (the team's tools, on the path via the server)
import tasklib  # noqa: E402

LEAD, STRANGER, DM = "U0LEAD", "U0OTHER", "D0DM"


class FakeSlack:
    """Records what the console posts; answers like Slack's web API."""

    def __init__(self):
        self.posted, self.updated, self.ephemeral, self.count = [], [], [], 0

    async def auth_test(self):
        return {"user_id": "U0BOT"}

    async def conversations_open(self, users):
        return {"channel": {"id": DM}}

    async def chat_postMessage(self, **message):
        self.count += 1
        self.posted.append({**message, "ts": f"100.{self.count}"})
        return {"ts": f"100.{self.count}"}

    async def chat_update(self, **message):
        self.updated.append(message)

    async def chat_postEphemeral(self, **message):
        self.ephemeral.append(message)

    async def reactions_add(self, **_):
        pass


class SlackTest(unittest.IsolatedAsyncioTestCase):

    async def test_a_direct_message_goes_to_the_orchestrator_and_its_answer_comes_back_in_the_thread(self):
        bridge, web = await self._a_bridge()

        await self._the_lead_writes(bridge, "Where are we?")
        await self._the_agent_asks_and_the_lead_taps(bridge, web, "orchestrator", "allow")

        answer = await self._the_answer_in(web, thread="1.0")
        self.assertIn("All clean.", answer["text"])

    async def test_a_message_starting_with_a_name_goes_to_that_agent(self):
        bridge, _ = await self._a_bridge()
        store.rename_agent("dev", "Nabil")

        await self._the_lead_writes(bridge, "Nabil: use the existing paginator")

        self.assertEqual(self._last_message_to(bridge, "dev"), "use the existing paginator")

    async def test_someone_not_on_the_list_is_turned_away(self):
        bridge, web = await self._a_bridge()

        await self._the_lead_writes(bridge, "Start the dev", user=STRANGER)

        self.assertIn("not on this team's list", web.posted[-1]["text"])
        self.assertEqual(bridge.manager.agents["orchestrator"].status, "stopped")

    async def test_an_approval_request_comes_with_buttons_and_a_tap_answers_it(self):
        bridge, web = await self._a_bridge()
        await self._the_lead_writes(bridge, "Check the repo")

        await self._the_agent_asks_and_the_lead_taps(bridge, web, "orchestrator", "deny")

        self.assertIn("Denied by <@U0LEAD>", web.updated[-1]["text"])

    async def test_a_task_ready_for_review_is_posted_in_its_thread_with_the_diff_and_who_can_review_it(self):
        bridge, web = await self._a_bridge()
        self._a_task("ready-for-review")

        await bridge.on_activity({"id": "TASK-001", "to": "ready-for-review", "actor": "dev"})

        root, update = web.posted[-2], web.posted[-1]
        self.assertIn("TASK-001", root["text"])
        self.assertEqual(update["thread_ts"], root["ts"])
        self.assertEqual(self._buttons(update), ["Review the diff", "Hand to " + bridge_label("reviewer")])

    async def test_tapping_hand_gives_the_task_to_that_agent(self):
        bridge, web = await self._a_bridge()
        self._a_task("ready-for-review")
        await bridge.on_activity({"id": "TASK-001", "to": "ready-for-review", "actor": "dev"})

        await self._the_lead_taps(bridge, web.posted[-1], "hand|TASK-001|reviewer")

        self.assertEqual(self._last_message_to(bridge, "reviewer"), "Review TASK-001 per your instructions.")

    async def test_what_the_lead_did_in_the_console_is_not_posted_again(self):
        bridge, web = await self._a_bridge()
        self._a_task("changes-requested")
        before = len(web.posted)

        await bridge.on_activity({"id": "TASK-001", "to": "changes-requested", "actor": "lead"})

        self.assertEqual(len(web.posted), before)

    async def test_an_approval_asked_in_a_conversation_mentions_the_lead_in_the_thread_so_it_notifies(self):
        bridge, web = await self._a_bridge()

        await self._the_lead_writes(bridge, "Check the repo")

        ask = await self._wait_for(lambda: next((m for m in web.posted if "wants to" in m["text"]), None))
        self.assertEqual(ask.get("thread_ts"), "1.0")
        self.assertNotIn("reply_broadcast", ask)
        self.assertIn(f"<@{LEAD}>", ask["text"])

    async def test_an_agent_that_stopped_and_waits_for_the_lead_is_posted_in_its_task_thread(self):
        bridge, web = await self._a_bridge()
        self._a_task("changes-requested")

        await bridge.on_bus({"kind": "waiting_for_lead", "agent": "dev", "task": "TASK-001",
                             "text": "Please switch your project folder to main."})

        posted = web.posted[-1]
        self.assertIn("stopped on TASK-001 and is waiting for you", posted["text"])
        self.assertIn("switch your project folder", posted["text"])
        self.assertNotIn("reply_broadcast", posted)
        self.assertIn(f"<@{LEAD}>", posted["text"])
        self.assertEqual(self._buttons(posted), ["Open the chat with " + bridge_label("dev"), "Open the task"])

    async def test_a_kind_turned_off_in_settings_is_not_posted(self):
        bridge, web = await self._a_bridge()
        self._a_task("ready-for-review")
        store.save_settings({"slack_prefs": {"notify": {"ready-for-review": "off"}}})
        before = len(web.posted)

        await bridge.on_activity({"id": "TASK-001", "to": "ready-for-review", "actor": "dev"})

        self.assertEqual(len(web.posted), before)

    async def test_a_quiet_kind_is_posted_in_its_thread_without_a_mention(self):
        bridge, web = await self._a_bridge()
        self._a_task("ready-for-review")
        store.save_settings({"slack_prefs": {"notify": {"ready-for-review": "quiet"}}})

        await bridge.on_activity({"id": "TASK-001", "to": "ready-for-review", "actor": "dev"})

        self.assertNotIn("<@", web.posted[-1]["text"])
        self.assertIn("thread_ts", web.posted[-1])

    async def test_replies_can_also_be_sent_outside_the_thread(self):
        bridge, web = await self._a_bridge()
        self._a_task("ready-for-review")
        store.save_settings({"slack_prefs": {"replies": "thread_and_dm"}})

        await bridge.on_activity({"id": "TASK-001", "to": "ready-for-review", "actor": "dev"})

        self.assertTrue(web.posted[-1]["reply_broadcast"])
        self.assertNotIn("<@", web.posted[-1]["text"])   # the copy outside the thread notifies by itself

    async def test_approvals_turned_off_still_come_in_a_conversation_started_in_slack(self):
        bridge, web = await self._a_bridge()
        store.save_settings({"slack_prefs": {"notify": {"approval": "off"}}})

        await self._the_lead_writes(bridge, "Check the repo")

        ask = await self._wait_for(lambda: next((m for m in web.posted if "wants to" in m["text"]), None))
        self.assertEqual(ask.get("thread_ts"), "1.0")

    async def test_an_unknown_notification_setting_is_refused(self):
        await self._a_bridge()

        with self.assertRaises(ValueError):
            store.save_settings({"slack_prefs": {"notify": {"ready-for-review": "loud"}}})

    async def test_new_proposals_from_the_coach_are_announced(self):
        bridge, web = await self._a_bridge()
        await bridge.check_proposals()
        self._a_coach_proposal("P-001")

        await bridge.check_proposals()

        self.assertIn("The Coach has 1 new proposal", web.posted[-1]["text"])
        self.assertIn("P-001", web.posted[-1]["text"])

    def test_markdown_becomes_slack_formatting(self):
        text = to_mrkdwn("## Status\n- **TASK-012** is [ready](http://x/#/tasks/TASK-012/review) <now>")

        self.assertEqual(text, "*Status*\n• *TASK-012* is <http://x/#/tasks/TASK-012/review|ready> &lt;now&gt;")

    def test_the_tech_leads_hidden_questions_for_the_console_are_not_posted(self):
        text = to_mrkdwn('<!-- hive-questions {"round": 2} -->\n### Round 2\n**Q1. Reuse it?**\n<!-- /hive-questions -->')

        self.assertEqual(text, "*Round 2*\n*Q1. Reuse it?*")

    # ---- helpers ----------------------------------------------------------------------

    async def _a_bridge(self) -> tuple[SlackBridge, FakeSlack]:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        (root / "tasks" / ".inbox").mkdir(parents=True)
        for module, name, value in ((tasklib, "TASKS", root / "tasks"), (tasklib, "INBOX", root / "tasks" / ".inbox"),
                                    (store, "SETTINGS", root / "settings.json"), (slack, "STATE", root / "slack.json"),
                                    (kit_coach, "PROPOSALS", root / "coach" / "proposals"), (team, "KIT", root)):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        store.save_settings({"slack": {"users": LEAD}})
        manager = AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))
        web = FakeSlack()
        bridge = SlackBridge(manager, web=web)
        await bridge.start()
        self.addAsyncCleanup(bridge.stop)
        self.addAsyncCleanup(manager.stop_all)
        return bridge, web

    def _a_task(self, status: str) -> None:
        (tasklib.TASKS / "TASK-001-total.md").write_text(
            f"---\nid: TASK-001\ntitle: Total\nstatus: {status}\nproject: /tmp/shop\nbase: main\nbranch: feature-total\n"
            f"from_commit: abc\ndev: dev\nreviewer:\n---\n")

    def _a_coach_proposal(self, pid: str) -> None:
        kit_coach.PROPOSALS.mkdir(parents=True, exist_ok=True)
        (kit_coach.PROPOSALS / f"{pid}-x.md").write_text(f"---\nid: {pid}\ntitle: Simpler\nstatus: pending\n---\n\n## Why\nBecause.\n")

    async def _the_lead_writes(self, bridge: SlackBridge, text: str, user: str = LEAD) -> None:
        await bridge.on_event({"type": "message", "channel_type": "im", "channel": DM, "user": user, "text": text, "ts": "1.0"})

    async def _the_agent_asks_and_the_lead_taps(self, bridge: SlackBridge, web: FakeSlack, agent: str, decision: str) -> None:
        ask = await self._wait_for(lambda: next((m for m in web.posted if "wants to" in m["text"]), None))
        pid = next(b["action_id"].split("|")[2] for b in self._elements(ask) if b["action_id"].startswith("perm|"))
        await self._the_lead_taps(bridge, ask, f"perm|{agent}|{pid}|{decision}")

    async def _the_lead_taps(self, bridge: SlackBridge, message: dict, action_id: str) -> None:
        await bridge.on_action({"type": "block_actions", "user": {"id": LEAD},
                                "container": {"channel_id": message["channel"], "message_ts": message["ts"]},
                                "message": {"text": message["text"]}, "actions": [{"action_id": action_id}]})

    async def _the_answer_in(self, web: FakeSlack, thread: str) -> dict:
        return await self._wait_for(lambda: next((m for m in web.posted if m.get("thread_ts") == thread
                                                  and "wants to" not in m["text"] and "busy" not in m["text"]), None))

    async def _wait_for(self, find, seconds: float = 10):
        for _ in range(int(seconds / 0.05)):
            found = find()
            if found:
                return found
            await asyncio.sleep(0.05)
        self.fail("Nothing was posted to Slack.")

    def _last_message_to(self, bridge: SlackBridge, agent: str) -> str:
        events = store.read_events(bridge.manager.agents[agent].session_id)
        return [e for e in events if e["kind"] == "user"][-1]["text"]

    def _elements(self, message: dict) -> list[dict]:
        return [e for block in message.get("blocks", []) if block["type"] == "actions" for e in block["elements"]]

    def _buttons(self, message: dict) -> list[str]:
        return [e["text"]["text"] for e in self._elements(message)]


def bridge_label(agent: str) -> str:
    from hive import ops
    return ops.label(agent)


if __name__ == "__main__":
    unittest.main()
