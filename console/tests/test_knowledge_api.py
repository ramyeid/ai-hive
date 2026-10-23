"""The console's Knowledge page: lists each repository's knowledge files and shows one, with its freshness.

    uv run python -m unittest tests/test_knowledge_api.py
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

    def test_lists_each_repo_with_its_index_first_then_its_services(self):
        client = self._a_console()
        self._a_monorepo_with_knowledge("platform", services={"payments": "services/payments/", "orders": "services/orders/"})

        listing = client.get("/api/knowledge", headers=HEADERS).json()

        self.assertEqual([r["repo"] for r in listing], ["platform"])
        self.assertEqual([f["name"] for f in listing[0]["files"]], ["index", "orders", "payments"])

    def test_counts_changes_per_file_only_inside_its_own_folders(self):
        client = self._a_console()
        project = self._a_monorepo_with_knowledge("platform", services={"orders": "services/orders/", "payments": "services/payments/"})
        self._a_commit_changing(project, "services/payments/charge.py")

        listing = client.get("/api/knowledge", headers=HEADERS).json()

        changed = {f["name"]: f["changed"] for f in listing[0]["files"]}
        self.assertEqual(changed, {"index": 0, "orders": 0, "payments": 1})

    def test_shows_a_service_file_without_front_matter_with_its_changes_and_its_siblings(self):
        client = self._a_console()
        project = self._a_monorepo_with_knowledge("platform", services={"orders": "services/orders/"})
        self._a_commit_changing(project, "services/orders/api.py")

        shown = client.get("/api/knowledge/platform/orders", headers=HEADERS).json()

        self.assertTrue(shown["markdown"].lstrip().startswith("## Purpose"))
        self.assertEqual(shown["changed_files"], ["services/orders/api.py"])
        self.assertEqual([s["name"] for s in shown["siblings"]], ["index", "orders"])

    def test_refuses_paths_that_are_not_knowledge_files(self):
        client = self._a_console()
        self._a_monorepo_with_knowledge("platform", services={"orders": "services/orders/"})

        response = client.get("/api/knowledge/platform/..%2F..%2Ftasks%2FBOARD", headers=HEADERS)

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

    def _a_monorepo_with_knowledge(self, name: str, services: dict[str, str]) -> Path:
        project = Path(tempfile.mkdtemp()) / name
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        self._git(project, "init", "-q", "-b", "main")
        self._a_commit_changing(project, "package.json")
        commit = self._git(project, "rev-parse", "--short", "HEAD").stdout.strip()
        folder = self._knowledge / name
        folder.mkdir()
        self._a_knowledge_file(folder / "index.md", f"repo: {name}\npath: {project}\nscope: package.json", commit)
        for service, scope in services.items():
            self._a_knowledge_file(folder / f"{service}.md", f"service: {service}\nrepo: {name}\npath: {project}\nscope: {scope}", commit)
        return project

    def _a_knowledge_file(self, path: Path, fields: str, commit: str) -> None:
        path.write_text(f"---\n{fields}\ncommit: {commit}\nbranch: main\nupdated: 2026-10-22\nupdated_by: techlead\n---\n\n"
                        "<!-- guidance -->\n## Purpose\nPart of the platform.\n")

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
