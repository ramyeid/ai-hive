"""The console's own files (/static): a browser checks them again each time, so an update shows at once.

    uv run python -m unittest tests/test_static_files.py
"""
import unittest

from fastapi.testclient import TestClient

from hive.agents import AgentManager
from hive.main import create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport


class StaticFilesTest(unittest.TestCase):

    def test_the_consoles_code_is_never_used_from_a_stale_browser_copy(self):
        client = self._a_console()

        got = client.get("/static/app.js")

        self.assertEqual(got.status_code, 200)
        self.assertEqual(got.headers["cache-control"], "no-cache")

    def test_an_unchanged_file_is_still_a_cheap_not_modified(self):
        client = self._a_console()
        first = client.get("/static/styles.css")

        again = client.get("/static/styles.css", headers={"if-none-match": first.headers["etag"]})

        self.assertEqual(again.status_code, 304)

    def _a_console(self) -> TestClient:
        app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
        client = TestClient(app, base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client
