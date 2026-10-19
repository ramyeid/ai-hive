"""Runs the pm / dev / reviewer agents through the Claude Agent SDK.

Each agent is one long-lived Claude Code session. The console sends it your
messages, streams back what it does, and pauses on every tool call that needs
approval until you allow or deny it in the browser.
"""
from __future__ import annotations

import asyncio
import json
import re
import uuid
from typing import Any, Callable

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient,
                              PermissionResultAllow, PermissionResultDeny, ResultMessage,
                              StreamEvent, SystemMessage, TextBlock, ThinkingBlock,
                              ToolResultBlock, ToolUseBlock, UserMessage)

from . import store
from .store import KIT

AGENTS = ("pm", "dev", "reviewer")
RESULT_LIMIT = 4000  # characters of tool output kept per call


def load_agent(name: str) -> tuple[str, str | None]:
    """The agent's instructions (with the kit path filled in) and its model."""
    text = (KIT / "agents" / f"{name}.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.S)
    front = match.group(1) if match else ""
    model = re.search(r"^model:\s*(\S+)", front, re.M)
    body = text[match.end():] if match else text
    return body.replace("{{KIT}}", str(KIT)), (model.group(1) if model else None)


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
    def __init__(self, name: str, bus: EventBus,
                 client_factory: Callable[[ClaudeAgentOptions], Any] = ClaudeSDKClient) -> None:
        self.name = name
        self.bus = bus
        self.client_factory = client_factory
        self.client = None
        self.status = "stopped"          # stopped | starting | idle | working | waiting
        self.session_id: str | None = None
        self.pending: dict[str, dict] = {}
        self.always_allow: set[str] = set()
        self.consumer: asyncio.Task | None = None
        self.error = ""

    # ---- state -------------------------------------------------------------

    def info(self) -> dict:
        return {"name": self.name, "status": self.status, "session_id": self.session_id,
                "error": self.error,
                "pending": [{"id": pid, **{k: v for k, v in p.items() if k != "future"}}
                            for pid, p in self.pending.items()]}

    def _set_status(self, status: str) -> None:
        self.status = status
        self.bus.publish({"kind": "agent", "agent": self.info()})

    def _live(self, kind: str, **data) -> None:
        """Progress shown while the agent works, not kept in history."""
        self.bus.publish({"ts": store.now(), "agent": self.name, "session": self.session_id,
                          "kind": kind, **data})

    def _emit(self, kind: str, **data) -> None:
        event = {"ts": store.now(), "agent": self.name, "session": self.session_id,
                 "kind": kind, **data}
        if self.session_id:
            store.append_event(self.session_id, event)
        self.bus.publish(event)

    # ---- lifecycle -----------------------------------------------------------

    async def start(self, resume: str | None = None) -> None:
        """Start a fresh session, or continue an earlier one from history."""
        if self.client:
            return
        self._set_status("starting")
        self.error = ""
        settings = store.load_settings()
        prompt, model = load_agent(self.name)
        claude_session = None
        if resume:
            meta = store.get_session(resume)
            if not meta or meta["agent"] != self.name:
                self._set_status("stopped")
                raise ValueError("That session doesn't belong to this agent.")
            claude_session = meta.get("claude_session_id")
        self.session_id = resume or store.new_session(self.name)
        options = ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code", "append": prompt},
            model=model,
            cwd=settings["workspace"],
            add_dirs=[str(KIT)],
            setting_sources=["user"],  # your ~/.claude settings: task hook + permissions
            permission_mode=settings["permission_mode"].get(self.name, "default"),
            can_use_tool=self._can_use_tool,
            disallowed_tools=["AskUserQuestion"],  # questions come to you as chat text
            resume=claude_session,
            include_partial_messages=True,  # stream thinking and replies as they're written
        )
        try:
            self.client = self.client_factory(options)
            await self.client.connect()
        except Exception as exc:  # e.g. Claude Code not logged in
            self.client = None
            self.error = str(exc)
            self._set_status("stopped")
            raise
        self._emit("system", text="Session resumed." if resume else "Session started.")
        self._set_status("idle")

    async def stop(self) -> None:
        if not self.client:
            return
        for pid in list(self.pending):
            self.decide(pid, "deny", "The lead stopped the agent.")
        if self.status == "working":
            await self.client.interrupt()
        if self.consumer:
            self.consumer.cancel()
        try:
            await self.client.disconnect()
        finally:
            self.client = None
            self.consumer = None
            self.always_allow.clear()
            self._emit("system", text="Agent stopped.")
            self._set_status("stopped")

    async def new_session(self) -> None:
        await self.stop()
        self.session_id = None
        await self.start()

    async def interrupt(self) -> None:
        if self.client and self.status in ("working", "waiting"):
            for pid in list(self.pending):
                self.decide(pid, "deny", "Interrupted by the lead.")
            await self.client.interrupt()
            self._emit("system", text="Interrupted.")

    async def set_permission_mode(self, mode: str) -> None:
        if self.client:
            await self.client.set_permission_mode(mode)

    # ---- conversation ----------------------------------------------------------

    async def send(self, text: str) -> None:
        if not self.client:
            await self.start()
        if self.status not in ("idle",):
            raise RuntimeError(f"{self.name} is busy. Wait for it to finish, or interrupt it.")
        self._emit("user", text=text)
        self._set_status("working")
        await self.client.query(text)
        self.consumer = asyncio.create_task(self._consume())

    async def _consume(self) -> None:
        try:
            async for message in self.client.receive_response():
                self._handle(message)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.error = str(exc)
            self._emit("error", text=str(exc))
        finally:
            if self.client:
                self._set_status("idle")

    def _handle(self, message) -> None:
        if isinstance(message, StreamEvent):
            if not message.parent_tool_use_id:
                self._stream(message.event)
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            self._emit("init", claude_session_id=message.data.get("session_id"),
                       model=message.data.get("model"))
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    self._emit("text", text=block.text)
                elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                    self._emit("thinking", text=block.thinking)
                elif isinstance(block, ToolUseBlock):
                    self._emit("tool", id=block.id, name=block.name, input=block.input)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    self._emit("tool_result", id=block.tool_use_id,
                               is_error=bool(block.is_error), text=_result_text(block.content))
        elif isinstance(message, ResultMessage):
            self._emit("result", claude_session_id=message.session_id,
                       cost_usd=message.total_cost_usd, turns=message.num_turns,
                       duration_ms=message.duration_ms, is_error=message.is_error)

    def _stream(self, event: dict) -> None:
        kind = event.get("type")
        if kind == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                self._live("delta", block="text", text=delta.get("text", ""))
            elif delta.get("type") == "thinking_delta":
                self._live("delta", block="thinking", text=delta.get("thinking", ""))
        elif kind == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                self._live("delta", block="tool", text=block.get("name", ""))
            elif block.get("type") == "thinking":
                self._live("delta", block="thinking", text="")

    # ---- permissions -------------------------------------------------------------

    async def _can_use_tool(self, tool: str, tool_input: dict, context) -> Any:
        if tool in self.always_allow:
            return PermissionResultAllow(updated_input=tool_input)
        pid = uuid.uuid4().hex[:8]
        future = asyncio.get_running_loop().create_future()
        self.pending[pid] = {"future": future, "tool": tool, "input": tool_input,
                             "reason": str(getattr(context, "decision_reason", None) or ""),
                             "title": str(getattr(context, "title", None) or "")}
        self._emit("permission", id=pid, tool=tool, input=tool_input)
        self._set_status("waiting")
        decision, message = await future
        self._set_status("working")
        if decision in ("allow", "always"):
            if decision == "always":
                self.always_allow.add(tool)
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=message or "The lead denied this.")

    def decide(self, pid: str, decision: str, message: str = "") -> None:
        pending = self.pending.pop(pid, None)
        if not pending:
            raise KeyError(pid)
        self._emit("decision", id=pid, tool=pending["tool"], decision=decision, message=message)
        if not pending["future"].done():
            pending["future"].set_result((decision, message))


def _result_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    text = content if isinstance(content, str) else json.dumps(content)
    return text if len(text) <= RESULT_LIMIT else text[:RESULT_LIMIT] + "\n… (truncated)"


class AgentManager:
    def __init__(self, client_factory=ClaudeSDKClient) -> None:
        self.bus = EventBus()
        self.agents = {name: AgentRunner(name, self.bus, client_factory) for name in AGENTS}

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
