"""The contract between the console and whatever runs an agent.

The console (AgentRunner) owns everything you see: status, history, live
updates and approval cards. An engine owns one conversation with one model
and reports back through EngineHooks. Adding a provider means writing an
engine (or a preset for an existing one), nothing else.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class EngineHooks(Protocol):
    def emit(self, kind: str, **data) -> None:
        """Record an event in the conversation history and show it live.

        Kinds: text, thinking, tool (id, name, input), tool_result (id, is_error, text),
        result (duration_ms, turns, cost_usd?, tokens_in?, tokens_out?), init, error.
        """

    def live(self, kind: str, **data) -> None:
        """Show progress that isn't kept in history: kind "delta" with block text|thinking|tool."""

    async def ask(self, tool: str, tool_input: dict) -> tuple[bool, str]:
        """Ask the lead to approve a tool call. Returns (allowed, message for the agent)."""


@dataclass
class EngineConfig:
    agent: str                 # agent id: pm, dev, dev-2, …
    instructions: str          # the agent's .md body, kit path filled in
    provider: str              # key in PROVIDERS
    model: str                 # "" = the provider's / agent file's default
    workspace: Path            # folder the agent starts in
    kit: Path                  # the agent-team folder (task board, scripts)
    session_id: str            # console session, used to save and resume the conversation
    resume: bool               # continue a saved conversation instead of starting fresh
    permission_mode: str       # default | acceptEdits
    api_key: str = ""
    base_url: str = ""
    role: str = ""             # pm | dev | reviewer


class AgentEngine(ABC):
    def __init__(self, config: EngineConfig, hooks: EngineHooks) -> None:
        self.config = config
        self.hooks = hooks

    @abstractmethod
    async def start(self) -> None:
        """Connect and load the conversation (fresh or resumed). Raise if it can't run."""

    @abstractmethod
    async def run_turn(self, text: str) -> None:
        """Send the lead's message and work until the agent has replied in full."""

    @abstractmethod
    async def interrupt(self) -> None:
        """Stop the current turn as soon as possible; the conversation stays usable."""

    @abstractmethod
    async def stop(self) -> None:
        """End the conversation and release resources."""

    async def set_permission_mode(self, mode: str) -> None:
        self.config.permission_mode = mode
