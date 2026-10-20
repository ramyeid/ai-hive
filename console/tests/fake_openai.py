"""A stand-in for an OpenAI-compatible API (OpenAI, DeepSeek, Qwen, Kimi) for tests and UI work.

Each turn it: thinks, says what it will do, lists files (no approval needed),
then asks to run `echo hello` (needs approval), then answers.
"""
import asyncio
import json

import httpx

DELAY = 0.12


def _plan(messages: list[dict]) -> dict:
    since_user = []
    for message in reversed(messages):
        if message["role"] == "user":
            break
        since_user.append(message)
    tool_results = sum(1 for m in since_user if m["role"] == "tool")
    if tool_results == 0:
        return {"reasoning": "The lead asked something. I'll look at the files first.",
                "content": "Let me look at the project first.",
                "tool": ("Glob", {"pattern": "*.md"})}
    if tool_results == 1:
        return {"content": "", "tool": ("Bash", {"command": "echo hello"})}
    last = since_user[0]["content"]
    return {"content": f"Done. The last tool said: **{last.splitlines()[0][:60]}**"}


def _sse(obj) -> bytes:
    return f"data: {json.dumps(obj)}\n\n".encode()


async def _stream(plan: dict):
    def delta(**d):
        return {"choices": [{"index": 0, "delta": d}]}
    for word in plan.get("reasoning", "").split():
        yield _sse(delta(reasoning_content=word + " "))
        await asyncio.sleep(DELAY)
    for word in plan.get("content", "").split():
        yield _sse(delta(content=word + " "))
        await asyncio.sleep(DELAY)
    if plan.get("tool"):
        name, args = plan["tool"]
        raw = json.dumps(args)
        yield _sse(delta(tool_calls=[{"index": 0, "id": f"call_{name.lower()}", "type": "function",
                                      "function": {"name": name, "arguments": raw[:5]}}]))
        await asyncio.sleep(DELAY)
        yield _sse(delta(tool_calls=[{"index": 0, "function": {"arguments": raw[5:]}}]))
    yield _sse({"choices": [], "usage": {"prompt_tokens": 120, "completion_tokens": 30}})
    yield b"data: [DONE]\n\n"


def fake_openai_transport(log: list | None = None) -> httpx.MockTransport:
    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if log is not None:
            log.append({"url": str(request.url), "auth": request.headers.get("authorization"), "body": body})
        if body["model"] == "missing-model":
            return httpx.Response(404, json={"error": {"message": "The model does not exist"}})
        plan = _plan(body["messages"])
        if body.get("stream"):
            return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_stream(plan))
        message = {"role": "assistant", "content": plan.get("content", "")}
        if plan.get("reasoning"):
            message["reasoning_content"] = plan["reasoning"]
        if plan.get("tool"):
            name, args = plan["tool"]
            message["tool_calls"] = [{"id": f"call_{name.lower()}", "type": "function",
                                      "function": {"name": name, "arguments": json.dumps(args)}}]
        return httpx.Response(200, json={"choices": [{"message": message}],
                                         "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
    return httpx.MockTransport(handler)
