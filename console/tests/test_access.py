"""Opening the console from another machine (a server behind a VPN): allowed names only, and a password.

    uv run python -m unittest tests/test_access.py
"""
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from server import access
from server.agents import AgentManager
from server.main import TOKEN, create_app
from tests.fake_claude import FakeClient
from tests.fake_openai import fake_openai_transport

PASSWORD = "correct horse battery"
REMOTE = {"CONSOLE_HOSTS": "hive.internal", "CONSOLE_PASSWORD": PASSWORD}


class AccessTest(unittest.TestCase):

    def test_by_default_only_this_machine_can_open_the_console(self):
        client = self._a_console("http://hive.internal:8420", env={})

        response = client.get("/")

        self.assertEqual(response.status_code, 403)

    def test_an_allowed_name_asks_for_the_password_first(self):
        client = self._a_console("http://hive.internal:8420", env=REMOTE)

        response = client.get("/")

        self.assertIn('type="password"', response.text)
        self.assertNotIn(TOKEN, response.text)

    def test_a_wrong_password_is_refused(self):
        client = self._a_console("http://hive.internal:8420", env=REMOTE)

        response = client.post("/login", data={"password": "guess"}, follow_redirects=False)

        self.assertEqual(response.status_code, 401)

    def test_after_signing_in_the_console_and_its_api_open(self):
        client = self._a_console("http://hive.internal:8420", env=REMOTE)

        client.post("/login", data={"password": PASSWORD, "next": "#/tasks/TASK-001/review"}, follow_redirects=False)

        self.assertIn(TOKEN, client.get("/").text)
        self.assertEqual(client.get("/api/state", headers={"x-token": TOKEN}).status_code, 200)

    def test_signing_in_takes_you_back_to_the_page_you_opened(self):
        client = self._a_console("http://hive.internal:8420", env=REMOTE)

        response = client.post("/login", data={"password": PASSWORD, "next": "#/tasks/TASK-001/review"}, follow_redirects=False)

        self.assertEqual(response.headers["location"], "/#/tasks/TASK-001/review")

    def test_this_machine_never_needs_the_password(self):
        client = self._a_console("http://127.0.0.1:8420", env=REMOTE)

        response = client.get("/")

        self.assertIn(TOKEN, response.text)

    def test_allowing_other_names_without_a_password_is_refused_at_start(self):
        with mock.patch.dict(os.environ, {"CONSOLE_HOSTS": "hive.internal"}, clear=False):
            os.environ.pop("CONSOLE_PASSWORD", None)

            with self.assertRaises(RuntimeError):
                access.check_config()

    # ---- helpers ----------------------------------------------------------------------

    def _a_console(self, base_url: str, env: dict) -> TestClient:
        patch = mock.patch.dict(os.environ, env, clear=False)
        patch.start()
        self.addCleanup(patch.stop)
        for name in ("CONSOLE_HOSTS", "CONSOLE_PASSWORD"):
            if name not in env:
                os.environ.pop(name, None)
        client = TestClient(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))),
                            base_url=base_url)
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client


if __name__ == "__main__":
    unittest.main()
