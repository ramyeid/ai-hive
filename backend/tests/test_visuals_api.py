"""The pictures the team draws (data/visuals/): screenshots, mockups and diagrams, served for the chats and specs.

    uv run python -m unittest tests/test_visuals_api.py
"""
import shutil
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from hive import visuals
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

HEADERS = {"x-token": TOKEN}


class VisualsApiTest(unittest.TestCase):

    def test_serves_a_screenshot_as_an_image(self):
        client = self._a_console()
        self._a_file("orders-csv/now.png", b"\x89PNG\r\n\x1a\n...")

        got = client.get("/api/visuals/orders-csv/now.png", headers=HEADERS)

        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers["content-type"], "image/png")
        self.assertEqual(got.content, b"\x89PNG\r\n\x1a\n...")

    def test_serves_a_mockup_sandboxed_so_it_cannot_reach_the_console(self):
        client = self._a_console()
        self._a_file("orders-csv/proposed.html", b"<!doctype html><p>Orders</p>")

        got = client.get("/api/visuals/orders-csv/proposed.html", headers=HEADERS)

        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.headers["content-type"].startswith("text/html"))
        self.assertTrue(got.headers["content-security-policy"].startswith("sandbox allow-scripts;"))
        self.assertNotIn("allow-same-origin", got.headers["content-security-policy"])

    def test_also_takes_the_token_in_the_address_for_images_and_frames(self):
        client = self._a_console()
        self._a_file("orders-csv/now.png", b"png")

        self.assertEqual(client.get(f"/api/visuals/orders-csv/now.png?token={TOKEN}").status_code, 200)
        self.assertEqual(client.get("/api/visuals/orders-csv/now.png").status_code, 401)

    def test_nothing_outside_data_visuals(self):
        client = self._a_console()
        (self._root.parent / "secret.png").write_bytes(b"png")

        got = client.get("/api/visuals/..%2Fsecret.png", headers=HEADERS)

        self.assertEqual(got.status_code, 404)
        self.assertIsNone(visuals.find("../secret.png", self._root))

    def test_only_kinds_of_picture_the_console_shows(self):
        client = self._a_console()
        self._a_file("orders-csv/notes.txt", b"not a picture")

        self.assertEqual(client.get("/api/visuals/orders-csv/notes.txt", headers=HEADERS).status_code, 404)
        self.assertEqual(client.get("/api/visuals/orders-csv/missing.png", headers=HEADERS).status_code, 404)

    def _a_file(self, rel: str, data: bytes) -> None:
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def _a_console(self) -> TestClient:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        self._root = folder / "visuals"
        self._root.mkdir()
        original = visuals.VISUALS
        visuals.VISUALS = self._root
        self.addCleanup(setattr, visuals, "VISUALS", original)
        app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
        client = TestClient(app, base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client
