"""Engine for any provider with an OpenAI-style Chat Completions API and tool calling:
OpenAI, DeepSeek, Qwen (Alibaba Cloud), Kimi (Moonshot), …

It runs the agent loop itself: send the conversation, stream back thinking and text,
run the tools the model asks for (pausing for approval when needed), repeat until
the model answers without asking for a tool. The conversation is saved after every
step so it can be resumed from History.
"""
from __future__ import annotations

import asyncio
import json
import platform
import time
import uuid
from datetime import date

import httpx

from .. import store
from .base import AgentEngine, EngineConfig, EngineHooks
from .tools import OPENAI_TOOLS, Toolbox

MAX_STEPS = 150            # model calls per turn before giving up
SHOWN_RESULT = 4000        # characters of tool output shown in the chat


class ProviderError(Exception):
    pass


class OpenAICompatibleEngine(AgentEngine):
    def __init__(self, config: EngineConfig, hooks: EngineHooks, provider,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        super().__init__(config, hooks)
        self.provider = provider
        self.transport = transport
        self.http: httpx.AsyncClient | None = None
        self.messages: list[dict] = []
        self.tools = Toolbox(config.workspace, config.kit, env={"AGENT_ID": config.agent})
        self.task: asyncio.Task | None = None
        self.interrupted = False
        self.usage = {"steps": 0, "tokens_in": 0, "tokens_out": 0, "started": 0.0}

    # ---- lifecycle -------------------------------------------------------------------

    async def start(self) -> None:
        cfg = self.config
        if not cfg.api_key:
            raise ValueError(f"Add a {self.provider.label} API key in Settings first.")
        if not cfg.model:
            raise ValueError(f"Choose a {self.provider.label} model for this agent first.")
        self.http = httpx.AsyncClient(
            base_url=cfg.base_url.rstrip("/"), transport=self.transport,
            headers={"Authorization": f"Bearer {cfg.api_key}"},
            timeout=httpx.Timeout(600, connect=20))
        saved = store.load_messages(cfg.session_id) if cfg.resume else []
        self.messages = saved or [{"role": "system", "content": self._system_prompt()}]
        self.hooks.emit("init", model=cfg.model, provider=self.provider.id)

    async def stop(self) -> None:
        await self.interrupt()
        if self.http:
            await self.http.aclose()
            self.http = None

    async def interrupt(self) -> None:
        if self.task and not self.task.done():
            self.interrupted = True
            self.task.cancel()

    async def run_turn(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self.interrupted = False
        self.usage = {"steps": 0, "tokens_in": 0, "tokens_out": 0, "started": time.monotonic()}
        self.task = asyncio.create_task(self._loop())
        try:
            await self.task
        except asyncio.CancelledError:
            self._close_open_tool_calls()
            self._report(is_error=True)   # what was used before the interrupt still counts
            if not self.interrupted:
                raise
        except Exception:
            self._report(is_error=True)   # e.g. the provider failed mid-turn
            raise
        finally:
            store.save_messages(self.config.session_id, self.messages)

    # ---- the agent loop ------------------------------------------------------------

    async def _loop(self) -> None:
        used = self.usage
        while used["steps"] < MAX_STEPS:
            used["steps"] += 1
            message, usage = await self._complete()
            used["tokens_in"] += usage.get("prompt_tokens", 0) or 0
            used["tokens_out"] += usage.get("completion_tokens", 0) or 0
            self.messages.append(message)
            if message.get("reasoning_content"):
                self.hooks.emit("thinking", text=message["reasoning_content"])
            if (message.get("content") or "").strip():
                self.hooks.emit("text", text=message["content"])
            calls = message.get("tool_calls") or []
            if not calls:
                break
            for call in calls:
                await self._run_tool_call(call)
            store.save_messages(self.config.session_id, self.messages)
        else:
            self.hooks.emit("error", text=f"Stopped after {MAX_STEPS} steps without finishing. Tell the agent how to continue.")
        self._report(is_error=False)

    def _report(self, is_error: bool) -> None:
        used = self.usage
        self.hooks.emit("result", duration_ms=int((time.monotonic() - used["started"]) * 1000),
                        turns=used["steps"], cost_usd=None, tokens_in=used["tokens_in"],
                        tokens_out=used["tokens_out"], is_error=is_error)

    async def _run_tool_call(self, call: dict) -> None:
        name = call["function"]["name"]
        try:
            args = json.loads(call["function"].get("arguments") or "{}")
            if not isinstance(args, dict):
                raise ValueError("arguments must be a JSON object")
        except ValueError as exc:
            self._tool_result(call["id"], f"Invalid arguments for {name}: {exc}. Send valid JSON.", True)
            return
        self.hooks.emit("tool", id=call["id"], name=name, input=args)
        if self.tools.needs_approval(name, args, self.config.permission_mode):
            allowed, why = await self.hooks.ask(name, args)
            if not allowed:
                self._tool_result(call["id"], f"The lead denied this. {why}".strip(), True)
                return
        output, is_error = await self.tools.run(name, args)
        self._tool_result(call["id"], output, is_error)

    def _tool_result(self, call_id: str, output: str, is_error: bool) -> None:
        self.messages.append({"role": "tool", "tool_call_id": call_id, "content": output})
        shown = output if len(output) <= SHOWN_RESULT else output[:SHOWN_RESULT] + "\n… (truncated)"
        self.hooks.emit("tool_result", id=call_id, is_error=is_error, text=shown)

    def _close_open_tool_calls(self) -> None:
        """After an interrupt, answer any tool call left open so the conversation stays valid."""
        answered = {m.get("tool_call_id") for m in self.messages if m.get("role") == "tool"}
        for message in [m for m in self.messages if m.get("tool_calls")]:
            for call in message["tool_calls"]:
                if call["id"] not in answered:
                    self.messages.append({"role": "tool", "tool_call_id": call["id"],
                                          "content": "Interrupted by the lead before this ran."})

    # ---- talking to the provider -------------------------------------------------------

    async def _complete(self) -> tuple[dict, dict]:
        body = {"model": self.config.model, "messages": self.messages,
                "tools": OPENAI_TOOLS, "tool_choice": "auto"}
        if not self.provider.stream:
            response = await self.http.post("/chat/completions", json=body)
            _raise_for(response, self.provider.label, response.text)
            data = response.json()
            return _assistant(data["choices"][0]["message"]), data.get("usage") or {}

        body["stream"] = True
        if self.provider.usage_in_stream:
            body["stream_options"] = {"include_usage": True}
        content, reasoning, calls, usage = [], [], {}, {}
        async with self.http.stream("POST", "/chat/completions", json=body) as response:
            if response.status_code >= 400:
                _raise_for(response, self.provider.label, (await response.aread()).decode(errors="replace"))
            async for line in response.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                chunk = json.loads(payload)
                usage = chunk.get("usage") or usage
                for choice in chunk.get("choices") or []:
                    self._absorb(choice.get("delta") or {}, content, reasoning, calls)
        message = {"role": "assistant", "content": "".join(content),
                   "reasoning_content": "".join(reasoning),
                   "tool_calls": [calls[i] for i in sorted(calls)]}
        return _assistant(message), usage

    def _absorb(self, delta: dict, content: list, reasoning: list, calls: dict) -> None:
        thought = delta.get("reasoning_content") or delta.get("reasoning")
        if thought:
            reasoning.append(thought)
            self.hooks.live("delta", block="thinking", text=thought)
        if delta.get("content"):
            content.append(delta["content"])
            self.hooks.live("delta", block="text", text=delta["content"])
        for part in delta.get("tool_calls") or []:
            slot = calls.setdefault(part.get("index", len(calls)),
                                    {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            slot["id"] = part.get("id") or slot["id"]
            fn = part.get("function") or {}
            if fn.get("name"):
                slot["function"]["name"] += fn["name"]
                self.hooks.live("delta", block="tool", text=slot["function"]["name"])
            slot["function"]["arguments"] += fn.get("arguments") or ""

    def _system_prompt(self) -> str:
        cfg = self.config
        return f"""{cfg.instructions}

---
## How you run
You are the {cfg.agent} agent, running in the Team Console on the {self.provider.label} model `{cfg.model}`.
The lead talks to you in this chat. Ask the lead questions in your reply and wait for the answer.

- Working directory: {cfg.workspace}
- Kit folder (task board, scripts, TEAM.md): {cfg.kit}
- Today's date: {date.today().isoformat()}. OS: {platform.system()}.

Tools: Read, Write, Edit, Glob, Grep, Bash. Use absolute paths. Read a file before changing it,
and prefer Edit over Write for existing files. Bash runs in the working directory unless you `cd`.
Some actions need the lead's approval. If one is denied, don't retry it: ask the lead what to do."""


def _assistant(raw: dict) -> dict:
    """Normalise an assistant message so it can be sent back to the provider."""
    message = {"role": "assistant", "content": raw.get("content") or ""}
    if raw.get("reasoning_content"):
        message["reasoning_content"] = raw["reasoning_content"]  # some providers need it echoed back
    calls = [c for c in raw.get("tool_calls") or [] if c.get("function", {}).get("name")]
    if calls:
        for call in calls:
            call["id"] = call.get("id") or f"call_{uuid.uuid4().hex[:12]}"
            call["type"] = "function"
        message["tool_calls"] = calls
    return message


def _raise_for(response: httpx.Response, label: str, body: str) -> None:
    if response.status_code < 400:
        return
    hint = {401: "Check the API key in Settings.", 403: "Check the API key and its permissions.",
            404: "Check the model name and the API address in Settings.",
            429: "Rate limit or quota reached on your account."}.get(response.status_code, "")
    raise ProviderError(f"{label} returned {response.status_code}. {hint} {body[:400]}".strip())
