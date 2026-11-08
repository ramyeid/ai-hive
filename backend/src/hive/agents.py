"""Runs the techlead / dev / reviewer agents and connects them to the browser.

An AgentRunner owns what you see: status, history, live updates and approval
cards. The conversation itself is handled by an engine (see engines/), chosen
from the provider set for the agent: Claude Code for Claude, or the
OpenAI-compatible engine for OpenAI, DeepSeek, Qwen and Kimi.
"""
from __future__ import annotations

import asyncio
import os
import re
import secrets
import uuid
from pathlib import Path

from . import board, chats, store
from .engines import PROVIDERS, make_engine
from .engines.base import AgentEngine, EngineConfig
from .store import KIT, TEAM

# The Orchestrator's key to the console's team actions (team/tools/orchestrate.py). New on every start;
# only the Orchestrator gets it, and every action it asks for still waits for the lead's approval.
ORCHESTRATOR_KEY = secrets.token_urlsafe(24)
TEAM_ACTION = "Team action"   # how the Orchestrator's actions appear in approval requests


def load_agent(role: str) -> tuple[str, str, str]:
    """A role's instructions (with the kit path filled in), its default Claude model and effort level."""
    text = (TEAM / "agents" / f"{role}.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    front = match.group(1) if match else ""
    model = re.search(r"^model:\s*(\S+)", front, re.M)
    effort = re.search(r"^effort:\s*(\S+)", front, re.M)
    body = text[match.end():] if match else text
    return body.replace("{{KIT}}", str(KIT)), (model.group(1) if model else ""), (effort.group(1) if effort else "")


class EventBus:
    """Fans live events out to every open browser tab."""

    def __init__(self) -> None:
        self.queues: set[asyncio.Queue] = set()

    def subscribe(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self.queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        self.queues.discard(queue)

    def publish(self, event: dict) -> None:
        for queue in list(self.queues):
            if not queue.full():
                queue.put_nowait(event)


class AgentRunner:
    """One agent as the console sees it. Also the EngineHooks its engine reports to."""

    def __init__(self, name: str, bus: EventBus, engine_options: dict | None = None) -> None:
        self.name = name                 # agent id: techlead, dev, dev-2, …
        self.role = store.role_of(name)
        self.bus = bus
        self.engine_options = engine_options or {}
        self.engine: AgentEngine | None = None
        self.status = "stopped"          # stopped | starting | idle | working | waiting
        self.session_id: str | None = None
        self.provider = ""
        self.model = ""
        self.pending: dict[str, dict] = {}
        self.always_allow: set[str] = set()
        self.turn: asyncio.Task | None = None
        self.turn_started = ""
        self.turn_task = ""              # the task this turn was about, when its message named one
        self.turn_source = ""            # who started this turn: console (you, in its chat), team or slack
        self.turn_text = ""              # the agent's last words this turn
        self.interrupted = False
        self.waiting_for_lead: dict | None = None   # stopped waiting for your answer; see _check_waiting
        self.lead_watching = ""          # when the lead last had its chat open on screen
        self.error = ""

    # ---- state ---------------------------------------------------------------------

    def info(self) -> dict:
        return {"name": self.name, "role": self.role, "status": self.status, "session_id": self.session_id,
                "error": self.error, "provider": self.provider, "model": self.model,
                "waiting_for_lead": self.waiting_for_lead,
                "pending": [{"id": pid, **{k: v for k, v in p.items() if k != "future"}}
                            for pid, p in self.pending.items()]}

    def _set_status(self, status: str) -> None:
        self.status = status
        self.bus.publish({"kind": "agent", "agent": self.info()})

    # ---- EngineHooks -------------------------------------------------------------------

    def live(self, kind: str, **data) -> None:
        """Progress shown while the agent works, not kept in history."""
        self.bus.publish({"ts": store.now(), "agent": self.name, "session": self.session_id,
                          "kind": kind, **data})

    def emit(self, kind: str, **data) -> None:
        event = {"ts": store.now(), "agent": self.name, "session": self.session_id,
                 "kind": kind, **data}
        if self.session_id:
            store.append_event(self.session_id, event)
        if kind == "text" and data.get("text", "").strip():
            self.turn_text = data["text"]
        self.bus.publish(event)

    async def ask(self, tool: str, tool_input: dict) -> tuple[bool, str]:
        if self.role == "orchestrator" and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            return False, ("The Orchestrator doesn't edit files: hand the work to the agent whose job it is "
                           "(`orchestrate.py hand` or `tell`), with the lead's approval.")
        if self.role == "coach" and tool in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
            target = Path(str(tool_input.get("file_path") or tool_input.get("notebook_path") or "")).expanduser()
            if not target.resolve().is_relative_to((KIT / "data" / "coach").resolve()):
                return False, ("The Coach never edits files directly. Write a proposal in coach/proposals/ "
                               "(`coach.py propose`), and the lead approves it in the console.")
        if tool in self.always_allow:
            return True, ""
        pid = uuid.uuid4().hex[:8]
        future = asyncio.get_running_loop().create_future()
        self.pending[pid] = {"future": future, "tool": tool, "input": tool_input}
        self.emit("permission", id=pid, tool=tool, input=tool_input)
        self._set_status("waiting")
        decision, message = await future
        if not self.pending:
            self._set_status("working" if self.engine and self.turn and not self.turn.done()
                             else "idle" if self.engine else "stopped")
        if decision == "always":
            self.always_allow.add(tool)
        return decision in ("allow", "always"), message

    def decide(self, pid: str, decision: str, message: str = "") -> None:
        pending = self.pending.pop(pid, None)
        if not pending:
            raise KeyError(pid)
        self.emit("decision", id=pid, tool=pending["tool"], decision=decision, message=message)
        if not pending["future"].done():
            pending["future"].set_result((decision, message))

    # ---- lifecycle -----------------------------------------------------------------------

    async def start(self, resume: str | None = None) -> None:
        """Start a fresh session on the agent's chosen provider, or continue one from history."""
        if self.engine:
            return
        settings = store.load_settings()
        if resume:
            meta = store.get_session(resume)
            if not meta or meta["agent"] != self.name:
                raise ValueError("That session doesn't belong to this agent.")
            provider_id, model = meta.get("provider", "claude"), meta.get("model", "")
        else:
            choice = settings["agents"].get(self.name)
            if not choice:
                raise ValueError(f"{self.name} has been removed from the team.")
            provider_id, model = choice["provider"], choice["model"]
        provider = PROVIDERS.get(provider_id)
        if not provider:
            raise ValueError(f"Unknown provider: {provider_id}")
        instructions, default_claude_model, effort = load_agent(self.role)
        display = store.load_settings()["agents"].get(self.name, {}).get("name", "")
        instructions += (f"\n\n## Your identity\n{f'Your name is {display}. ' if display else ''}"
                         f"Your agent ID is `{self.name}` (role: {self.role}). It's in the "
                         "`AGENT_ID` environment variable, which the team's tools use for your inbox and claims.")
        if provider.engine == "claude":
            model = model or default_claude_model
        api_key, base_url, _ = store.provider_credentials(provider)

        self._set_status("starting")
        self.error = ""
        self.session_id = resume or store.new_session(self.name, provider.id, model)
        self.provider, self.model = provider.id, model
        config = EngineConfig(
            agent=self.name, role=self.role, instructions=instructions, provider=provider.id, model=model,
            workspace=Path(settings["workspace"]), kit=KIT, session_id=self.session_id,
            resume=bool(resume), permission_mode=settings["permission_mode"].get(self.name, "default"),
            api_key=api_key, base_url=base_url, effort=effort,
            env={"CONSOLE_API": f"http://127.0.0.1:{os.environ.get('PORT', '8420')}",
                 "CONSOLE_ORCHESTRATOR_KEY": ORCHESTRATOR_KEY} if self.role == "orchestrator" else None)
        engine = make_engine(config, self, **self.engine_options)
        try:
            await engine.start()
        except Exception as exc:  # e.g. not logged in, no API key, no model chosen
            self.error = str(exc)
            self.session_id = None
            self._set_status("stopped")
            raise
        self.engine = engine
        self.emit("system", text="Session resumed." if resume else "Session started.")
        self._set_status("idle")

    async def stop(self) -> None:
        if not self.engine:
            return
        for pid in list(self.pending):
            self.decide(pid, "deny", "The lead stopped the agent.")
        engine, self.engine = self.engine, None
        if self.turn and not self.turn.done():
            await engine.interrupt()
            self.turn.cancel()
        try:
            await engine.stop()
        finally:
            self.turn = None
            self.always_allow.clear()
            self.emit("system", text="Agent stopped.")
            self._save_chats()
            self._set_status("stopped")

    def _save_chats(self) -> None:
        """Save this conversation into the folder of each task it worked on (never breaks the agent)."""
        try:
            chats.archive(self.session_id)
        except Exception as exc:
            self.bus.publish({"ts": store.now(), "agent": self.name, "kind": "error",
                              "text": f"Couldn't save the conversation with its tasks: {exc}"})

    async def new_session(self) -> None:
        await self.stop()
        self.session_id = None
        await self.start()

    async def interrupt(self) -> None:
        if self.engine and self.status in ("working", "waiting"):
            for pid in list(self.pending):
                self.decide(pid, "deny", "Interrupted by the lead.")
            self.interrupted = True
            await self.engine.interrupt()
            self.emit("system", text="Interrupted.")

    async def set_permission_mode(self, mode: str) -> None:
        if self.engine:
            await self.engine.set_permission_mode(mode)

    # ---- conversation ----------------------------------------------------------------------

    async def send(self, text: str, source: str = "console") -> None:
        """source: "console" when you typed it in the agent's chat (you're watching), "team" for hand-offs and the
        Orchestrator's messages, "slack" for messages from Slack (the answer goes back to the Slack thread)."""
        if not self.engine:
            await self.start()
        if self.status != "idle":
            raise RuntimeError(f"{self.name} is busy. Wait for it to finish, or interrupt it.")
        self.turn_started = store.now()
        self.turn_source, self.turn_text, self.interrupted = source, "", False
        self.turn_task = (re.findall(r"TASK-\d+", text) or [""])[0]
        self.waiting_for_lead = None
        self.emit("user", text=text)
        self._set_status("working")
        self.turn = asyncio.create_task(self._run_turn(text))

    async def _run_turn(self, text: str) -> None:
        try:
            await self.engine.run_turn(text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)
            self.emit("error", text=str(exc))
        finally:
            if self.engine:
                self._set_status("idle")
                asyncio.get_running_loop().create_task(self._after_turn(self.turn_started))

    async def _after_turn(self, started: str) -> None:
        """If the agent handed a task on during this turn, save the conversation with the task and start a
        fresh one, so the next task doesn't carry this one's context (what /clear does in a terminal)."""
        if self.turn and not self.turn.done():
            await asyncio.wait([self.turn])
        self._check_waiting(started)
        handoffs = chats.handed_off(self.name, started)
        if not handoffs or not self.engine or self.status != "idle":
            return
        done = ", ".join(f"{h['id']} → {h['to']}" for h in handoffs)
        self.emit("system", text=f"Handed off {done}. This conversation is saved with the task; starting a fresh one.")
        try:
            await self.new_session()
        except Exception as exc:
            self.error = str(exc)
            self._set_status("stopped")
            return
        self.emit("system", text=f"Fresh conversation after handing off {done}. The previous one is saved with the task.")


    def _check_waiting(self, started: str) -> None:
        """An agent that stops without moving any task is waiting for you: a question, or something only you can fix
        (like a branch checked out in your project folder). Agents don't always mark the task Blocked, so Home, the
        sidebar and Slack show it from this instead. Not when you have its chat open (you see it there), not for
        messages from Slack (the answer goes back to the Slack thread), and not for the Orchestrator, whose turns
        are answers to you."""
        if self.turn_source == "slack" or self.interrupted or self.role == "orchestrator" or self.status != "idle":
            return
        if self.lead_watching and _seconds_since(self.lead_watching) < WATCHING_SECONDS:
            return
        if any(a.get("actor") == self.name and a.get("ts", "") >= started for a in board.activity(500)):
            return   # it moved a task: the board and its notifications already say what's next
        self.waiting_for_lead = {"since": store.now(), "task": self.turn_task,
                                 "text": (self.error if not self.turn_text else self.turn_text).strip()[:2000]}
        self.bus.publish({"kind": "agent", "agent": self.info()})
        self.bus.publish({"ts": store.now(), "agent": self.name, "kind": "waiting_for_lead", **self.waiting_for_lead})


WATCHING_SECONDS = 30   # the chat page reports every 10 s while it's on screen


def _seconds_since(iso: str) -> float:
    from datetime import datetime
    return (datetime.fromisoformat(store.now()) - datetime.fromisoformat(iso)).total_seconds()


class AgentManager:
    def __init__(self, **engine_options) -> None:
        """engine_options: claude_client_factory / http_transport, used by the tests."""
        self.bus = EventBus()
        self.engine_options = engine_options
        self.agents: dict[str, AgentRunner] = {}
        self.sync()

    def sync(self) -> None:
        """Match the running agents to the team in Settings (after adding or removing one)."""
        team = store.load_settings()["agents"]
        for name in team:
            self.agents.setdefault(name, AgentRunner(name, self.bus, self.engine_options))
        for name in [n for n in self.agents if n not in team and self.agents[n].status == "stopped"]:
            del self.agents[name]
        order = {role: i for i, role in enumerate(store.ROLES)}
        self.agents = dict(sorted(self.agents.items(), key=lambda kv: (order.get(kv[1].role, 9), _number(kv[0]))))

    def get(self, name: str) -> AgentRunner:
        if name not in self.agents:
            raise KeyError(name)
        return self.agents[name]

    async def stop_all(self) -> None:
        for runner in self.agents.values():
            try:
                await runner.stop()
            except Exception:
                pass


def _number(agent_id: str) -> int:
    tail = agent_id.rsplit("-", 1)[-1]
    return int(tail) if tail.isdigit() else 1
