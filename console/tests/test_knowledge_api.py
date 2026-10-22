"""The console's Knowledge page: lists the Tech Lead's knowledge files and shows one, with its freshness.

    .venv/bin/python -m unittest tests/test_knowledge_api.py
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server import board
from server.agents import AgentManager
from server.main import TOKEN, create_app
from tests.fake_claude import FakeClient
from tests.fake_openai import fake_openai_transport

HEADERS = {"x-token": TOKEN}


class KnowledgeApiTest(unittest.TestCase):

    def test_lists_each_service_with_the_number_of_files_changed_since_its_commit(self):
        client = self._a_console()
        project = self._a_project_with_knowledge_at_head("orders")
        self._a_commit_changing(project, "src/orders/api.py")

        listing = client.get("/api/knowledge", headers=HEADERS).json()

        self.assertEqual([k["service"] for k in listing], ["orders"])
        self.assertEqual(listing[0]["changed"], 1)

    def test_shows_a_file_without_its_front_matter_and_with_the_changed_files(self):
        client = self._a_console()
        project = self._a_project_with_knowledge_at_head("orders")
        self._a_commit_changing(project, "src/orders/api.py")

        shown = client.get("/api/knowledge/orders", headers=HEADERS).json()

        self.assertTrue(shown["markdown"].lstrip().startswith("## Purpose"))
        self.assertEqual(shown["changed_files"], ["src/orders/api.py"])
        self.assertNotIn("<!--", shown["markdown"])

    def test_says_up_to_date_when_nothing_changed_since_the_commit(self):
        client = self._a_console()
        self._a_project_with_knowledge_at_head("orders")

        listing = client.get("/api/knowledge", headers=HEADERS).json()

        self.assertEqual(listing[0]["changed"], 0)

    def test_refuses_names_that_are_not_knowledge_files(self):
        client = self._a_console()
        self._a_project_with_knowledge_at_head("orders")

        response = client.get("/api/knowledge/..%2Ftasks%2FBOARD", headers=HEADERS)

        self.assertEqual(response.status_code, 404)

    # ---- helpers ----------------------------------------------------------------------

    def _a_console(self) -> TestClient:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        self._knowledge = folder / "knowledge"
        self._knowledge.mkdir()
        original = board.KNOWLEDGE
        board.KNOWLEDGE = self._knowledge
        self.addCleanup(setattr, board, "KNOWLEDGE", original)
        app = create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([])))
        client = TestClient(app, base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def _a_project_with_knowledge_at_head(self, name: str) -> Path:
        project = Path(tempfile.mkdtemp()) / name
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        self._git(project, "init", "-q", "-b", "main")
        self._a_commit_changing(project, "README.md")
        commit = self._git(project, "rev-parse", "--short", "HEAD").stdout.strip()
        (self._knowledge / f"{name}.md").write_text(
            f"---\nservice: {name}\npath: {project}\ncommit: {commit}\nbranch: main\nupdated: 2026-10-22\n"
            f"updated_by: techlead\n---\n\n<!-- guidance -->\n## Purpose\nTakes orders.\n\n## Code map\n`src/orders/` → the API.\n")
        return project

    def _a_commit_changing(self, project: Path, file: str) -> None:
        path = project / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("change\n")
        self._git(project, "add", ".")
        self._git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", f"change {file}")

    def _git(self, project: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
