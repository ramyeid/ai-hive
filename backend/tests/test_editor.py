"""VS Code in the browser (code-server): off until the lead turns it on, only for a browser the console let in, and
its live connection only from the console's own page. A stand-in code-server (tests/fakes/code_server.py) answers.

    uv run python -m unittest tests/test_editor.py
"""
import shutil
import socket
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import uvicorn
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.sync.client import connect

from hive import editor, store
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

KEY = {"x-token": TOKEN}
CONSOLE = "http://127.0.0.1:8420"
SOCKET_URL = "ws://127.0.0.1:8420/editor/socket"


class EditorTest(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="ed"))   # short: a Unix socket's path is limited to ~100 characters
        self.addCleanup(shutil.rmtree, self.root, True)
        fake = self.root / "code-server"
        fake.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{Path(__file__).parent / "fakes/code_server.py"}" "$@"\n')
        fake.chmod(fake.stat().st_mode | stat.S_IEXEC)
        for module, name, value in ((store, "SETTINGS", self.root / "settings.json"), (editor, "FOLDER", self.root / "editor"),
                                    (editor, "SOCKET", self.root / "editor" / "cs.sock")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        self.env("CODE_SERVER", str(fake))
        self.env("ENABLE_EDITOR", None)
        self.addCleanup(editor.stop)
        self.console = TestClient(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))),
                                  base_url=CONSOLE)
        self.console.__enter__()
        self.addCleanup(self.console.__exit__, None, None, None)
        self.folder = self.root / "shop"
        self.folder.mkdir()

    def test_it_is_off_until_the_lead_turns_it_on(self):
        self.assertFalse(self.console.get("/api/editor", headers=KEY).json()["enabled"])
        self.assertEqual(self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)}).status_code, 409)
        self.assertEqual(self.console.get("/editor/").status_code, 404)

    def test_the_settings_page_sees_whether_code_server_is_installed(self):
        status = self.console.get("/api/editor", headers=KEY).json()

        self.assertTrue(status["installed"])
        self.assertEqual(status["version"], "4.0.0-fake")

    def test_opening_a_folder_starts_code_server_and_lets_this_browser_in(self):
        self.turn_on()

        opened = self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})
        page = self.console.get(opened.json()["url"])

        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.text, f"workbench for {self.folder}")
        self.assertEqual(page.headers["x-seen-prefix"], "/editor")
        self.assertIn("samesite=strict", opened.headers["set-cookie"].lower())

    def test_opening_needs_the_pages_key(self):
        self.turn_on()

        self.assertEqual(self.console.post("/api/editor/open", json={"folder": str(self.folder)}).status_code, 401)

    def test_a_browser_the_console_did_not_let_in_is_refused(self):
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})

        stranger = TestClient(self.console.app, base_url=CONSOLE)

        self.assertEqual(stranger.get(f"/editor/?folder={self.folder}").status_code, 403)

    def test_a_folder_that_does_not_exist_is_refused(self):
        self.turn_on()

        self.assertEqual(self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.root / "gone")}).status_code, 404)

    def test_the_live_connection_is_passed_through_from_the_consoles_own_page(self):
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})

        with self.console.websocket_connect(SOCKET_URL, headers={"origin": CONSOLE}) as ws:
            ws.send_text("hello")
            self.assertEqual(ws.receive_text(), "echo hello (host 127.0.0.1:8420)")

    def test_behind_a_reverse_proxy_the_page_is_on_the_consoles_name_while_the_host_is_the_proxys_upstream(self):
        self.env("CONSOLE_HOSTS", "hive.example.com")
        self.env("CONSOLE_PASSWORD", "a long password")
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})

        with self.console.websocket_connect(SOCKET_URL, headers={"origin": "https://hive.example.com"}) as ws:
            ws.send_text("hello")
            self.assertEqual(ws.receive_text(), "echo hello (host hive.example.com)")

    def test_closing_the_tab_while_code_server_is_sending_ends_quietly(self):
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})
        port = self.a_real_server()   # how a tab goes away shows only with uvicorn itself, not the test client

        with self.assertNoLogs("uvicorn.error", level="ERROR"):
            ws = connect(f"ws://127.0.0.1:{port}/editor/chatter", additional_headers={
                "origin": f"http://127.0.0.1:{port}", "cookie": f"{editor.COOKIE}={self.console.cookies[editor.COOKIE]}"})
            ws.recv()
            ws.socket.close()   # the tab is gone, without a goodbye; code-server keeps sending
            time.sleep(0.5)

    def test_the_live_connection_from_another_website_is_refused(self):
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})

        with self.assertRaises(WebSocketDisconnect) as refused:
            with self.console.websocket_connect(SOCKET_URL, headers={"origin": "http://evil.example"}):
                pass
        self.assertEqual(refused.exception.code, 4403)

    def test_turning_it_off_stops_code_server(self):
        self.turn_on()
        self.console.post("/api/editor/open", headers=KEY, json={"folder": str(self.folder)})

        status = self.console.put("/api/editor", headers=KEY, json={"enabled": False}).json()

        self.assertFalse(status["running"])
        self.assertEqual(self.console.get(f"/editor/?folder={self.folder}").status_code, 404)

    def test_enable_editor_0_keeps_it_off_for_good(self):
        self.env("ENABLE_EDITOR", "0")

        self.assertEqual(self.console.put("/api/editor", headers=KEY, json={"enabled": True}).status_code, 409)

    # ---- helpers ----------------------------------------------------------------------

    def a_real_server(self) -> int:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(self.console.app, host="127.0.0.1", port=port, lifespan="off", log_level="warning"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 5)
        self.addCleanup(setattr, server, "should_exit", True)
        while not server.started:
            time.sleep(0.05)
        return port

    def turn_on(self):
        self.assertTrue(self.console.put("/api/editor", headers=KEY, json={"enabled": True}).json()["enabled"])

    def env(self, name, value):
        import os
        self.addCleanup(lambda old=os.environ.get(name): os.environ.__setitem__(name, old) if old is not None else os.environ.pop(name, None))
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


if __name__ == "__main__":
    unittest.main()
