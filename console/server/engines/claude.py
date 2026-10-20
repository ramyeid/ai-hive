"""Engine for Claude models, through Claude Code (the Claude Agent SDK).

Claude Code brings its own tools, permission rules (from ~/.claude/settings.json)
and the task hook; this adapter translates its messages into console events.
"""
from __future__ import annotations

import json
from typing import Any, Callable

from claude_agent_sdk import (AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient,
                              PermissionResultAllow, PermissionResultDeny, ResultMessage,
                              StreamEvent, SystemMessage, TextBlock, ThinkingBlock,
                              ToolResultBlock, ToolUseBlock, UserMessage)

from .. import store
from .base import AgentEngine, EngineConfig, EngineHooks

RESULT_LIMIT = 4000  # characters of tool output shown per call


class ClaudeCodeEngine(AgentEngine):
    def __init__(self, config: EngineConfig, hooks: EngineHooks,
                 client_factory: Callable[[ClaudeAgentOptions], Any] = ClaudeSDKClient) -> None:
        super().__init__(config, hooks)
        self.client_factory = client_factory
        self.client = None

    async def start(self) -> None:
        cfg = self.config
        claude_session = None
        if cfg.resume:
            claude_session = (store.get_session(cfg.session_id) or {}).get("claude_session_id")
        options = ClaudeAgentOptions(
            system_prompt={"type": "preset", "preset": "claude_code", "append": cfg.instructions},
            model=cfg.model or None,
            cwd=str(cfg.workspace),
            add_dirs=[str(cfg.kit)],
            setting_sources=["user"],  # your ~/.claude settings: task hook + permissions
            permission_mode=cfg.permission_mode,
            can_use_tool=self._can_use_tool,
            disallowed_tools=["AskUserQuestion"],  # questions come to you as chat text
            resume=claude_session,
            include_partial_messages=True,  # stream thinking and replies as they're written
        )
        self.client = self.client_factory(options)
        await self.client.connect()

    async def run_turn(self, text: str) -> None:
        await self.client.query(text)
        async for message in self.client.receive_response():
            self._handle(message)

    async def interrupt(self) -> None:
        if self.client:
            await self.client.interrupt()

    async def stop(self) -> None:
        if self.client:
            try:
                await self.client.disconnect()
            finally:
                self.client = None

    async def set_permission_mode(self, mode: str) -> None:
        await super().set_permission_mode(mode)
        if self.client:
            await self.client.set_permission_mode(mode)

    # ---- Claude Code messages → console events ----------------------------------

    def _handle(self, message) -> None:
        emit = self.hooks.emit
        if isinstance(message, StreamEvent):
            if not message.parent_tool_use_id:
                self._stream(message.event)
        elif isinstance(message, SystemMessage) and message.subtype == "init":
            emit("init", claude_session_id=message.data.get("session_id"),
                 model=message.data.get("model"))
        elif isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    emit("text", text=block.text)
                elif isinstance(block, ThinkingBlock) and block.thinking.strip():
                    emit("thinking", text=block.thinking)
                elif isinstance(block, ToolUseBlock):
                    emit("tool", id=block.id, name=block.name, input=block.input)
        elif isinstance(message, UserMessage) and isinstance(message.content, list):
            for block in message.content:
                if isinstance(block, ToolResultBlock):
                    emit("tool_result", id=block.tool_use_id,
                         is_error=bool(block.is_error), text=_result_text(block.content))
        elif isinstance(message, ResultMessage):
            usage = message.usage or {}
            tokens_in = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_creation_input_tokens",
                                                        "cache_read_input_tokens"))
            emit("result", claude_session_id=message.session_id,
                 cost_usd=message.total_cost_usd, turns=message.num_turns,
                 duration_ms=message.duration_ms, is_error=message.is_error,
                 tokens_in=tokens_in, tokens_out=usage.get("output_tokens") or 0)

    def _stream(self, event: dict) -> None:
        live = self.hooks.live
        kind = event.get("type")
        if kind == "content_block_delta":
            delta = event.get("delta", {})
            if delta.get("type") == "text_delta":
                live("delta", block="text", text=delta.get("text", ""))
            elif delta.get("type") == "thinking_delta":
                live("delta", block="thinking", text=delta.get("thinking", ""))
        elif kind == "content_block_start":
            block = event.get("content_block", {})
            if block.get("type") == "tool_use":
                live("delta", block="tool", text=block.get("name", ""))
            elif block.get("type") == "thinking":
                live("delta", block="thinking", text="")

    async def _can_use_tool(self, tool: str, tool_input: dict, context) -> Any:
        allowed, message = await self.hooks.ask(tool, tool_input)
        if allowed:
            return PermissionResultAllow(updated_input=tool_input)
        return PermissionResultDeny(message=message or "The lead denied this.")


def _result_text(content) -> str:
    if content is None:
        return ""
    if isinstance(content, list):
        content = "\n".join(c.get("text", "") if isinstance(c, dict) else str(c) for c in content)
    text = content if isinstance(content, str) else json.dumps(content)
    return text if len(text) <= RESULT_LIMIT else text[:RESULT_LIMIT] + "\n… (truncated)"
