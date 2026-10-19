"""A stand-in for ClaudeSDKClient so the console can be tested without Claude.

It behaves like a slow agent: streams its thinking and reply, then asks to run
one Bash command and waits for your decision.
"""
import asyncio

from claude_agent_sdk import (AssistantMessage, ResultMessage, StreamEvent, SystemMessage,
                              TextBlock, ThinkingBlock, ToolResultBlock, ToolUseBlock,
                              UserMessage)

DELAY = 0.15


def _delta(kind, text):
    key = "thinking" if kind == "thinking_delta" else "text"
    return StreamEvent("u", "claude-abc", {"type": "content_block_delta", "delta": {"type": kind, key: text}})


class FakeClient:
    def __init__(self, options):
        self.options = options
        self.prompt = None

    async def connect(self):
        pass

    async def disconnect(self):
        pass

    async def interrupt(self):
        pass

    async def set_permission_mode(self, mode):
        self.options.permission_mode = mode

    async def query(self, prompt):
        self.prompt = prompt

    async def receive_response(self):
        yield SystemMessage("init", {"session_id": "claude-abc", "model": "opus"})
        thought = "The lead wants me to look at the repository first. I'll check git status before anything else."
        for word in thought.split(" "):
            yield _delta("thinking_delta", word + " ")
            await asyncio.sleep(DELAY)
        yield AssistantMessage([ThinkingBlock(thought, "sig")], model="opus")
        reply = f"Looking into: {self.prompt}"
        for word in reply.split(" "):
            yield _delta("text_delta", word + " ")
            await asyncio.sleep(DELAY)
        yield AssistantMessage([TextBlock(reply)], model="opus")
        yield StreamEvent("u", "claude-abc", {"type": "content_block_start", "content_block": {"type": "tool_use", "name": "Bash"}})
        await asyncio.sleep(DELAY * 4)
        tool_input = {"command": "git status"}
        yield AssistantMessage([ToolUseBlock("t1", "Bash", tool_input)], model="opus")
        decision = await self.options.can_use_tool("Bash", tool_input, None)
        ok = decision.behavior == "allow"
        yield UserMessage([ToolResultBlock("t1", "On branch main\nnothing to commit" if ok
                                           else decision.message, not ok)])
        yield AssistantMessage([TextBlock("Done. **All clean.**")], model="opus")
        yield ResultMessage("success", 1200, 1000, False, 3, "claude-abc", total_cost_usd=0.0123)
