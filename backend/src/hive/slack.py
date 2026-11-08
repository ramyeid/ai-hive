"""Slack: talk to the Orchestrator or any agent, approve their requests with buttons, follow every task in a thread.

- Direct-message the app (or mention it in a channel): the Orchestrator answers. Start with an agent's name
  ("Nabil: use the existing paginator") to talk to that agent instead. Reply in a thread to keep talking to
  whoever answered there.
- When an agent asks to run something, the request comes with Allow / Deny buttons (the console shows it too;
  whichever you answer first counts).
- Each task gets a thread: hand-offs are posted in it, with buttons for what's next ("Review the diff",
  "Hand to Wael (Reviewer)"). Nothing is handed on unless you tap.

It uses Socket Mode: the console connects out to Slack, so it works the same on your laptop or on a server behind
a VPN, with nothing exposed to the internet. Use one Slack app per running console: two consoles connected with the
same app would each get only some of the messages. Only the Slack members listed in Settings can use it.
"""
from __future__ import annotations

import asyncio
import json
import os
import re

from . import board, ops, store, team

import tasklib  # noqa: E402  (the team's tools, on the path via board)
from .agents import TEAM_ACTION

STATE = store.DATA / "slack.json"
WAIT_FOR_FREE = 30 * 60      # seconds a message waits for a busy agent
CHUNK = 3500                 # characters per Slack message
LOUD = {"ready-for-dev", "ready-for-review", "changes-requested", "done", "blocked"}   # mention the lead so they notify


def to_mrkdwn(markdown: str) -> str:
    """The agents write Markdown; Slack has its own flavour."""
    out, in_code = [], False
    for line in markdown.splitlines():
        line = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if line.strip().startswith("```"):
            in_code = not in_code
            out.append("```")
            continue
        if not in_code:
            line = re.sub(r"^#{1,6}\s+(.*)$", r"*\1*", line)
            line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
            line = re.sub(r"__(.+?)__", r"*\1*", line)
            line = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", line)
            line = re.sub(r"^(\s*)[-*] ", r"\1• ", line)
        out.append(line)
    return "\n".join(out)


def _chunks(text: str) -> list[str]:
    parts, current = [], ""
    for line in text.splitlines(keepends=True):
        if len(current) + len(line) > CHUNK and current:
            parts.append(current)
            current = ""
        current += line
    return [p for p in parts + [current] if p.strip()] or ["(empty)"]


def _button(text: str, action_id: str, style: str = "") -> dict:
    button = {"type": "button", "text": {"type": "plain_text", "text": text[:75]}, "action_id": action_id[:255]}
    return {**button, "style": style} if style else button


def _link(text: str, url: str) -> dict:
    return {"type": "button", "text": {"type": "plain_text", "text": text[:75]}, "url": url, "action_id": f"link|{url}"[:255]}


def _blocks(text: str, buttons: list[dict]) -> list[dict]:
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}}]
    if buttons:
        blocks.append({"type": "actions", "elements": buttons[:5]})
    return blocks


def _detail(tool: str, tool_input: dict) -> str:
    if tool == TEAM_ACTION:
        return tool_input.get("summary", "")
    if tool == "Bash":
        return tool_input.get("command", "")
    if tool_input.get("file_path"):
        return tool_input["file_path"]
    return json.dumps(tool_input, indent=1)[:1500]


class SlackBridge:
    def __init__(self, manager, web=None) -> None:
        """web: a stand-in for Slack's web client, for the tests (no connection is made)."""
        self.manager = manager
        self.fake_web = web
        self.web = None
        self.socket = None
        self.jobs: list[asyncio.Task] = []
        self.connected = False
        self.error = ""
        self.cfg: dict = {}
        self.bot_user = ""
        self.home = ""   # where notifications go: the channel in Settings, or a DM with the first member
        self.listening: dict[str, dict] = {}   # agent -> the Slack thread its next answer goes to
        self.dm_users: dict[str, str] = {}      # direct-message channel -> the person in it
        self.seen: set[str] = set()
        self.proposals_seen: set[str] | None = None
        self.state = {"threads": {}, "convos": {}, "asks": {}}
        try:
            self.state.update(json.loads(STATE.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    # ---- connection ---------------------------------------------------------------------

    def status(self) -> dict:
        return {"configured": bool(self.cfg.get("bot_token") and self.cfg.get("app_token") and self.cfg.get("users")),
                "connected": self.connected, "error": self.error, "users": self.cfg.get("users", []),
                "channel": self.cfg.get("channel", "")}

    async def start(self) -> None:
        self.cfg = store.slack_config()
        self.error = ""
        if not self.fake_web and not self.status()["configured"]:
            return
        try:
            if self.fake_web:
                self.web = self.fake_web
            else:
                from slack_sdk.socket_mode.aiohttp import SocketModeClient
                from slack_sdk.web.async_client import AsyncWebClient
                proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None
                self.web = AsyncWebClient(token=self.cfg["bot_token"], proxy=proxy)
                self.socket = SocketModeClient(app_token=self.cfg["app_token"], web_client=self.web, proxy=proxy)
                self.socket.socket_mode_request_listeners.append(self._on_request)
            self.bot_user = (await self.web.auth_test())["user_id"]
            self.home = self.cfg.get("channel") or ""
            if not self.home and self.cfg.get("users"):
                self.home = (await self.web.conversations_open(users=self.cfg["users"][0]))["channel"]["id"]
            if self.socket:
                await self.socket.connect()
            self.connected = True
        except Exception as exc:   # bad token, no network, missing scope…
            await self.stop()
            self.error = f"Couldn't connect to Slack: {exc}"
            return
        queue = self.manager.bus.subscribe()   # now, so nothing from here on is missed
        self.jobs = [asyncio.create_task(self._watch_bus(queue)), asyncio.create_task(self._watch_activity()),
                     asyncio.create_task(self._watch_proposals())]

    async def stop(self) -> None:
        for job in self.jobs:
            job.cancel()
        self.jobs = []
        if self.socket:
            try:
                await self.socket.disconnect()
                await self.socket.close()
            except Exception:
                pass
        self.socket = None
        self.connected = False

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _on_request(self, client, req) -> None:
        from slack_sdk.socket_mode.response import SocketModeResponse
        await client.send_socket_mode_response(SocketModeResponse(envelope_id=req.envelope_id))
        try:
            if req.type == "events_api":
                await self.on_event(req.payload.get("event", {}))
            elif req.type == "interactive":
                await self.on_action(req.payload)
        except Exception as exc:
            self.error = f"Slack message failed: {exc}"

    def _save(self) -> None:
        convos = self.state["convos"]
        if len(convos) > 500:
            self.state["convos"] = dict(list(convos.items())[-500:])
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(self.state, indent=1), encoding="utf-8")

    # ---- sending ------------------------------------------------------------------------

    async def post(self, channel: str, text: str, thread: str = "", buttons: list[dict] | None = None) -> str:
        args = {"channel": channel, "text": text}
        if buttons:
            args["blocks"] = _blocks(text, buttons)
        if thread:
            args["thread_ts"] = thread
        return (await self.web.chat_postMessage(**args))["ts"]

    async def _react(self, channel: str, ts: str, emoji: str) -> None:
        try:
            await self.web.reactions_add(channel=channel, timestamp=ts, name=emoji)
        except Exception:
            pass   # reactions are a nicety

    async def _replace_buttons(self, channel: str, ts: str, text: str, note: str) -> None:
        await self.web.chat_update(channel=channel, ts=ts, text=f"{text}\n{note}",
                                   blocks=[{"type": "section", "text": {"type": "mrkdwn", "text": text[:2900]}},
                                           {"type": "context", "elements": [{"type": "mrkdwn", "text": note}]}])

    # ---- messages from Slack ------------------------------------------------------------

    def orchestrator(self) -> str:
        return next((aid for aid, r in self.manager.agents.items() if r.role == "orchestrator"), "")

    def _known_thread(self, thread: str) -> bool:
        return bool(thread) and (thread in self.state["convos"]
                                 or any(th["ts"] == thread for th in self.state["threads"].values()))

    def route(self, text: str, thread: str) -> tuple[str, str]:
        """Who a message is for: a name first ("Nabil: …"), then whoever answers in this thread, else the Orchestrator."""
        named = re.match(r"^@?([\w-]+)\s*[:,]\s*(.*)$", text, re.S)
        if named:
            try:
                return ops.find_agent(named.group(1)), named.group(2).strip()
            except ops.OpsError:
                pass
        if thread:
            agent = self.state["convos"].get(thread)
            if agent in self.manager.agents:
                return agent, text
            task = next((tid for tid, th in self.state["threads"].items() if th["ts"] == thread), "")
            if task:
                return self.orchestrator(), f"(About {task}) {text}"
        return self.orchestrator(), text

    async def on_event(self, event: dict) -> None:
        if event.get("type") not in ("message", "app_mention"):
            return
        if event.get("subtype") or event.get("bot_id") or event.get("user") == self.bot_user:
            return
        channel, ts, thread = event["channel"], event["ts"], event.get("thread_ts", "")
        if event["type"] == "message" and event.get("channel_type") != "im" and not self._known_thread(thread):
            return   # in channels: mentions of the app, and replies in its threads
        if ts in self.seen:
            return   # a mention in one of its threads arrives twice (message + app_mention)
        self.seen = (self.seen | {ts}) if len(self.seen) < 200 else {ts}
        if event.get("channel_type") == "im":
            self.dm_users[channel] = event.get("user", "")
        if event.get("user") not in self.cfg.get("users", []):
            await self.post(channel, "You're not on this team's list. The lead can add your Slack member ID in the "
                                     "console's Settings.", thread or ts)
            return
        text = re.sub(r"<@[A-Z0-9]+>", "", event.get("text", "")).strip()
        agent, text = self.route(text, thread)
        if not agent or not text:
            return
        await self.deliver(agent, text, channel, thread or ts, ts)

    async def deliver(self, agent: str, text: str, channel: str, thread: str, message_ts: str = "") -> None:
        self.state["convos"][thread] = agent
        self._save()
        if message_ts:
            await self._react(channel, message_ts, "eyes")
        if self.manager.agents[agent].status in ("working", "waiting", "starting"):
            await self.post(channel, f"{ops.label(agent)} is busy; I'll pass this on when it's free.", thread)
            asyncio.create_task(self._when_free(agent, text, channel, thread))
            return
        await self._send(agent, text, channel, thread)

    async def _send(self, agent: str, text: str, channel: str, thread: str) -> None:
        self.listening[agent] = {"channel": channel, "thread": thread, "texts": [], "started": False}
        try:
            await ops.tell(self.manager, agent, text, source="slack")
        except Exception as exc:
            self.listening.pop(agent, None)
            await self.post(channel, f"Couldn't reach {ops.label(agent)}: {exc}", thread)

    async def _when_free(self, agent: str, text: str, channel: str, thread: str) -> None:
        for _ in range(WAIT_FOR_FREE // 2):
            await asyncio.sleep(2)
            if self.manager.agents.get(agent) and self.manager.agents[agent].status in ("idle", "stopped") \
                    and agent not in self.listening:
                await self._send(agent, text, channel, thread)
                return
        await self.post(channel, f"{ops.label(agent)} was busy for 30 minutes, so I didn't pass that on. Send it again.", thread)

    # ---- what the agents do -------------------------------------------------------------

    async def _watch_bus(self, queue: asyncio.Queue) -> None:
        try:
            while True:
                event = await queue.get()
                try:
                    await self.on_bus(event)
                except Exception as exc:
                    self.error = f"Couldn't post to Slack: {exc}"
        finally:
            self.manager.bus.unsubscribe(queue)

    async def on_bus(self, event: dict) -> None:
        kind = event.get("kind")
        if kind == "agent":
            info = event["agent"]
            listening = self.listening.get(info["name"])
            if listening and listening["started"] and info["status"] in ("idle", "stopped"):
                await self._answer(info["name"])
            return
        agent = event.get("agent", "")
        listening = self.listening.get(agent)
        if kind == "user" and listening:
            listening["started"] = True
        elif kind == "text" and listening:
            listening["texts"].append(event.get("text", ""))
        elif kind == "error" and listening:
            listening["texts"].append(f"Something went wrong: {event.get('text', '')}")
        elif kind == "result" and listening and listening["started"]:
            await self._answer(agent)
        elif kind == "waiting_for_lead":
            await self._stopped(agent, event)
        elif kind == "permission":
            await self._ask(agent, event)
        elif kind == "decision":
            await self._decided(event)

    async def _answer(self, agent: str) -> None:
        listening = self.listening.pop(agent, None)
        if not listening:
            return
        texts = [t for t in listening["texts"] if t.strip()]
        answer = texts[-1] if texts else "Done."
        prefix = "" if agent == self.orchestrator() else f"*{ops.label(agent)}*\n"
        for part in _chunks(prefix + to_mrkdwn(answer)):
            await self.post(listening["channel"], part, listening["thread"])

    async def _stopped(self, agent: str, event: dict) -> None:
        """An agent stopped on work handed to it without moving the task: it's waiting for the lead. Its last words go
        in the task's thread (or the channel), with a mention so it notifies."""
        if not self.home:
            return
        task = board.get_task(event.get("task", "")) if event.get("task") else None
        said = event.get("text", "").strip() or "It stopped without saying why."
        where = f" on {task['id']}" if task else ""
        thread = await self._thread(task) if task else ""
        text = self._ping(f"*{ops.label(agent)}* stopped{where} and is waiting for you:\n", thread=thread) + to_mrkdwn(said)
        buttons = [_link(f"Open the chat with {ops.label(agent)}", ops.links(agent_id=agent)["chat"])]
        if task:
            buttons.append(_link("Open the task", ops.links(task["id"])["task"]))
        parts = _chunks(text)
        for i, part in enumerate(parts):
            await self.post(self.home, part, thread, buttons if i == len(parts) - 1 else None)

    async def _ask(self, agent: str, event: dict) -> None:
        pid, tool = event["id"], event["tool"]
        detail = _detail(tool, event.get("input", {}))
        what = "do this" if tool == TEAM_ACTION else f"use {tool}"
        text = f"*{ops.label(agent)}* wants to {what}:\n```{detail[:2500]}```"
        listening = self.listening.get(agent)
        channel, thread = (listening["channel"], listening["thread"]) if listening else (self.home, "")
        if not channel:
            return
        buttons = [_button("Allow", f"perm|{agent}|{pid}|allow", "primary"),
                   _button("Allow for this session", f"perm|{agent}|{pid}|always"),
                   _button("Deny", f"perm|{agent}|{pid}|deny", "danger"),
                   _link("Open the chat", ops.links(agent_id=agent)["chat"])]
        ts = await self.post(channel, self._ping(text, channel, thread), thread, buttons)
        self.state["asks"][pid] = {"channel": channel, "ts": ts, "text": text}
        self._save()

    async def _decided(self, event: dict) -> None:
        """Answered in the console (a Slack tap removes the request first)."""
        ask = self.state["asks"].pop(event.get("id"), None)
        if ask:
            self._save()
            word = {"allow": "✅ Allowed", "always": "✅ Allowed for this session", "deny": "❌ Denied"}.get(event.get("decision"), "Answered")
            await self._replace_buttons(ask["channel"], ask["ts"], ask["text"], f"{word} in the console.")

    # ---- buttons ------------------------------------------------------------------------

    async def on_action(self, payload: dict) -> None:
        if payload.get("type") != "block_actions":
            return
        user = payload.get("user", {}).get("id", "")
        channel = payload.get("container", {}).get("channel_id") or payload.get("channel", {}).get("id", "")
        ts = payload.get("container", {}).get("message_ts", "")
        text = payload.get("message", {}).get("text", "")
        for action in payload.get("actions", []):
            parts = action.get("action_id", "").split("|")
            if parts[0] == "link":
                continue
            if user not in self.cfg.get("users", []):
                await self.web.chat_postEphemeral(channel=channel, user=user, text="You're not on this team's list.")
                return
            if parts[0] == "perm" and len(parts) == 4:
                await self._tap_permission(parts[1], parts[2], parts[3], user, channel, ts, text)
            elif parts[0] == "hand" and len(parts) == 3:
                await self._tap_hand(parts[1], parts[2], user, channel, ts, text)

    async def _tap_permission(self, agent: str, pid: str, decision: str, user: str, channel: str, ts: str, text: str) -> None:
        ask = self.state["asks"].pop(pid, None)
        self._save()
        try:
            self.manager.get(agent).decide(pid, decision, "" if decision != "deny" else "Denied from Slack.")
            word = {"allow": "✅ Allowed", "always": "✅ Allowed for this session", "deny": "❌ Denied"}[decision]
            note = f"{word} by <@{user}>."
        except KeyError:
            note = "Already answered, or the agent stopped."
        await self._replace_buttons(channel, ts, ask["text"] if ask else text, note)

    async def _tap_hand(self, task_id: str, agent: str, user: str, channel: str, ts: str, text: str) -> None:
        try:
            done = await ops.hand(self.manager, task_id, agent)
            thread = self.state["threads"].get(task_id)
            if thread and agent not in self.listening:   # its report on the task goes to the task's thread
                self.listening[agent] = {"channel": thread["channel"], "thread": thread["ts"], "texts": [], "started": False}
            note = f"👉 {done} (<@{user}>)"
        except (ops.OpsError, KeyError) as exc:
            note = f"Couldn't: {exc}"
        await self._replace_buttons(channel, ts, text, note)

    # ---- task threads -------------------------------------------------------------------

    async def _watch_activity(self) -> None:
        path = tasklib.INBOX / "activity.jsonl"
        offset = path.stat().st_size if path.exists() else 0   # only what happens from now on
        while True:
            await asyncio.sleep(2)
            try:
                offset = await self._read_activity(path, offset)
            except Exception as exc:
                self.error = f"Couldn't post a task update: {exc}"

    async def _read_activity(self, path, offset: int) -> int:
        if not path.exists():
            return 0
        size = path.stat().st_size
        if size < offset:
            offset = 0
        if size == offset:
            return offset
        with path.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        end = chunk.rfind(b"\n")
        if end < 0:
            return offset
        for line in chunk[:end + 1].decode("utf-8", errors="replace").splitlines():
            if line.strip():
                await self.on_activity(json.loads(line))
        return offset + end + 1

    async def on_activity(self, entry: dict) -> None:
        if entry.get("actor") == "lead" or not self.home:
            return   # you did it yourself
        task = board.get_task(entry.get("id", ""))
        if not task:
            return
        message = self.notification(task, entry)
        if not message:
            return
        text, buttons = message
        thread = await self._thread(task)
        loud = entry.get("to") in LOUD
        await self.post(self.home, self._ping(text, thread=thread) if loud else text, thread, buttons)

    def _ping(self, text: str, channel: str = "", thread: str = "") -> str:
        """Mention the lead so the message notifies: in a channel, everyone on the list; in a direct message, the person
        in it, and only inside a thread (a reply in a thread you haven't joined doesn't notify by itself, a direct
        message does)."""
        channel = channel or self.home
        users = self.cfg.get("users", [])
        if channel.startswith("D"):
            if not thread:
                return text
            users = [self.dm_users.get(channel) or (users[0] if users else "")]
        users = [u for u in users if u]
        return " ".join(f"<@{u}>" for u in users) + " " + text if users else text

    async def _watch_proposals(self) -> None:
        while True:
            try:
                await self.check_proposals()
            except Exception as exc:
                self.error = f"Couldn't check the Coach's proposals: {exc}"
            await asyncio.sleep(15)

    async def check_proposals(self) -> None:
        """Tell the lead when the Coach has new proposals waiting (the first check only notes what's there)."""
        pending = {p["id"] for p in team.proposals() if p["status"] == "pending"}
        new = sorted(pending - self.proposals_seen) if self.proposals_seen is not None else []
        self.proposals_seen = pending
        if new and self.home:
            await self.post(self.home, self._ping(f"🧭 The Coach has {len(new)} new proposal{'s' if len(new) > 1 else ''} "
                                                  f"to improve the team's instructions ({', '.join(new)}). Approve, edit or reject them."),
                            buttons=[_link("See proposals", ops.links()["console"] + "#/improvements")])

    async def _thread(self, task: dict) -> str:
        found = self.state["threads"].get(task["id"])
        if found and found["channel"] == self.home:
            return found["ts"]
        text = f"*{task['id']}* {task['title']}  ·  _{task['project_name']}_"
        ts = await self.post(self.home, text, buttons=[_link("Open the task", ops.links(task["id"])["task"])])
        self.state["threads"][task["id"]] = {"channel": self.home, "ts": ts}
        self._save()
        return ts

    def notification(self, t: dict, entry: dict) -> tuple[str, list[dict]] | None:
        to = entry.get("to", "")
        who = lambda a: ops.label(a) if a else "Someone"   # noqa: E731
        link = ops.links(t["id"])
        review = [_link("Review the diff", link["review"])] if t["from_commit"] else []
        hands = ([_button(f"Hand to {ops.label(a)}", f"hand|{t['id']}|{a}", "primary" if i == 0 else "")
                  for i, a in enumerate(ops.candidates(self.manager, t)[:3])] if t["status"] == to else [])
        if to == "draft":
            return f"New task from {who(t['techlead'])}, still a draft.", []
        if to == "ready-for-dev":
            return f"Approved: *ready for a dev*. Who should build it?", hands + [_link("Open the task", link["task"])]
        if to == "in-dev":
            return f"{who(t['dev'])} is building it.", []
        if to == "ready-for-review":
            return f"{who(t['dev'])} finished: *ready for review*. Review the diff yourself, or hand it to a reviewer.", review + hands
        if to == "in-review":
            return f"{who(t['reviewer'])} is reviewing it.", []
        if to == "changes-requested":
            return f"{who(entry.get('actor') or t['reviewer'])} sent it back: *changes requested*.", hands + review
        if to == "done":
            return f"{who(t['reviewer'])} approved it: *done*. Have a look before you merge.", review
        if to == "blocked":
            agent = t["blocked_by"]
            return (f"{who(agent)} is *blocked* and needs you.",
                    ([_link(f"Open the chat with {ops.label(agent)}", ops.links(agent_id=agent)["chat"])] if agent else [])
                    + [_link("Open the task", link["task"])])
        return None
