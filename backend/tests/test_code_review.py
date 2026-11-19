"""Your code review in the console: the branch's diff, draft comments, and submitting a review.

    uv run python -m unittest tests/test_code_review.py
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from hive import store
from hive.agents import AgentManager
from hive.main import TOKEN, create_app
from tests.fakes.claude import FakeClient
from tests.fakes.openai import fake_openai_transport

import lead_review  # noqa: E402  (the team's tools, on the path via the server)
import tasklib  # noqa: E402

HEADERS = {"x-token": TOKEN}


class CodeReviewTest(unittest.TestCase):

    def test_the_review_shows_the_branchs_diff_against_its_base(self):
        client = self._a_console()
        self._a_task_with_code("ready-for-review")

        review = client.get("/api/tasks/TASK-001/review", headers=HEADERS).json()

        self.assertEqual([(f["path"], f["additions"], f["deletions"]) for f in review["files"]], [("app.py", 1, 1)])
        self.assertEqual(review["range"], "main...feature-total")

    def test_a_comment_stays_a_draft_until_the_review_is_submitted(self):
        client = self._a_console()
        self._a_task_with_code("ready-for-review")

        client.post("/api/tasks/TASK-001/review/comments", json={"body": "Name it total.", "file": "app.py", "line": 2}, headers=HEADERS)

        review = client.get("/api/tasks/TASK-001/review", headers=HEADERS).json()
        self.assertEqual(([c["body"] for c in review["pending"]], review["rounds"]), (["Name it total."], []))

    def test_approving_records_a_round_and_leaves_the_task_with_the_reviewer(self):
        client = self._a_console()
        task = self._a_task_with_code("ready-for-review")

        response = client.post("/api/tasks/TASK-001/review/submit", json={"verdict": "approve"}, headers=HEADERS)

        self.assertEqual(response.json()["verdict"], "approve")
        self.assertIn("status: ready-for-review", task.read_text())

    def test_changes_cannot_be_requested_while_the_reviewer_is_reviewing(self):
        client = self._a_console()
        self._a_task_with_code("in-review")
        client.post("/api/tasks/TASK-001/review/comments", json={"body": "Name it total."}, headers=HEADERS)

        response = client.post("/api/tasks/TASK-001/review/submit", json={"verdict": "changes"}, headers=HEADERS)

        self.assertEqual(response.status_code, 409)
        self.assertIn("the reviewer is reviewing it", response.json()["detail"])

    # ---- helpers ----------------------------------------------------------------------

    def _a_console(self) -> TestClient:
        self._root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self._root)
        tasks = self._root / "tasks"
        (tasks / ".inbox").mkdir(parents=True)
        for module, name, value in ((tasklib, "TASKS", tasks), (lead_review, "REVIEWS", tasks / "reviews"),
                                    (store, "SETTINGS", self._root / "settings.json")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        client = TestClient(create_app(AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))),
                            base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client

    def _a_task_with_code(self, status: str) -> Path:
        project = self._root / "shop"
        project.mkdir()
        _git(project, "init", "-q", "-b", "main")
        (project / "app.py").write_text("def total():\n    return 1\n")
        _git(project, "add", ".")
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
        _git(project, "checkout", "-q", "-b", "feature-total")
        (project / "app.py").write_text("def total():\n    return 2\n")
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qam", "TASK-001: change the total")
        task = tasklib.TASKS / "TASK-001-total.md"
        task.write_text(f"---\nid: TASK-001\ntitle: Total\nstatus: {status}\nproject: {project}\nbase: main\n"
                        f"branch: feature-total\nfrom_commit: abc\ndev: dev-2\nreviewer: reviewer\n---\n\n## Dev Log\n")
        return task


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    unittest.main()
