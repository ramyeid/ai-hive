"""Checks the browser terminal: off by default, needs the page's key, runs a real shell.

    uv run python -m tests.test_terminal
"""
import sys

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from server import terminal
from server.agents import AgentManager
from server.main import TOKEN, create_app
from tests.fake_claude import FakeClient
from tests.fake_openai import fake_openai_transport

checks = 0
URL = "ws://127.0.0.1:8420/api/terminal"   # the test client ignores base_url for WebSockets


def check(condition, what):
    global checks
    checks += 1
    if not condition:
        sys.exit(f"FAIL: {what}")
    print(f"ok  {what}")


def closed_with(ws) -> int:
    try:
        ws.receive_bytes()
    except WebSocketDisconnect as exc:
        return exc.code
    return 0


def read_until(ws, text: str) -> str:
    seen = ""
    for _ in range(200):
        seen += ws.receive_bytes().decode(errors="replace")
        if text in seen:
            return seen
    return seen


def main():
    app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
    with TestClient(app, base_url="http://127.0.0.1:8420") as c:
        check(c.get("/api/state", headers={"x-token": TOKEN}).json()["terminal"] is True, "the terminal is on by default")
        terminal.ENABLED = False   # as with ENABLE_TERMINAL=0
        check(c.get("/api/state", headers={"x-token": TOKEN}).json()["terminal"] is False, "ENABLE_TERMINAL=0 turns it off")
        with c.websocket_connect(URL) as ws:
            check(closed_with(ws) == 4403, "while off, no shell is started")

        terminal.ENABLED = True
        with c.websocket_connect(URL) as ws:
            ws.send_json({"token": "wrong"})
            check(closed_with(ws) == 4401, "a wrong key gets no shell")

        try:
            with c.websocket_connect("ws://evil.example/api/terminal") as ws:
                ws.send_json({"token": TOKEN})
                refused = closed_with(ws) != 0
        except WebSocketDisconnect:
            refused = True
        check(refused, "requests for another host name are refused (DNS rebinding)")

        with c.websocket_connect(URL) as ws:
            ws.send_json({"token": TOKEN, "cols": 100, "rows": 30})
            ws.send_json({"type": "input", "data": "echo hello-$((40+2))\n"})
            check("hello-42" in read_until(ws, "hello-42"), "with the key, it's a real shell: commands run and output streams back")
            ws.send_json({"type": "resize", "cols": 132, "rows": 40})
            ws.send_json({"type": "input", "data": "stty size\n"})
            check("40 132" in read_until(ws, "40 132"), "resizing the browser window resizes the shell")
            ws.send_json({"type": "input", "data": "exit\n"})
            code = 0
            for _ in range(200):
                try:
                    ws.receive_bytes()
                except WebSocketDisconnect as exc:
                    code = exc.code
                    break
            check(code == 1000, "typing exit ends the shell and the connection")
    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
