"""A task reaches review only with its work committed, and an empty review says why.

    uv run python -m unittest tests/test_handoff_gate.py
"""
import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hive import board, store  # noqa: F401  (board puts the team's tools on the path)

import board as board_tool  # noqa: E402
import lead_review  # noqa: E402
import on_task_change  # noqa: E402
import tasklib  # noqa: E402


class HandoffGateTest(unittest.TestCase):

    def test_ready_for_review_with_uncommitted_files_goes_back_to_the_dev(self):
        task, worktree = self._a_task_being_built()
        (worktree / "app.py").write_text("def total():\n    return 3\n")   # changed, never committed
        (worktree / "tax.py").write_text("RATE = 14\n")

        code, said = self._dev_sets(task, "ready-for-review")

        self.assertEqual(code, 2)
        self.assertEqual(tasklib.parse(task)["status"], "in-dev")
        self.assertIn("2 files are changed but not committed", said)
        self.assertIn("app.py", said)
        self.assertIn("tax.py", said)

    def test_ready_for_review_with_no_commits_goes_back_too(self):
        task, _ = self._a_task_being_built()

        code, said = self._dev_sets(task, "ready-for-review")

        self.assertEqual(code, 2)
        self.assertIn("has no commits since this task started", said)

    def test_committed_work_goes_to_review(self):
        task, worktree = self._a_task_being_built()
        (worktree / "app.py").write_text("def total():\n    return 2\n")
        _git(worktree, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qam", "TASK-001: total")

        code, _ = self._dev_sets(task, "ready-for-review")

        self.assertEqual(code, 0)
        self.assertEqual(tasklib.parse(task)["status"], "ready-for-review")

    def test_an_empty_review_says_the_work_was_never_committed(self):
        task, worktree = self._a_task_being_built()
        (worktree / "app.py").write_text("x = 1\n")
        task.write_text(task.read_text().replace("status: in-dev", "status: ready-for-review"))   # an edit the hook didn't see

        review = lead_review.diff("TASK-001")

        self.assertEqual(review["files"], [])
        self.assertIn("has no commits that aren't already in main", review["empty_reason"])
        self.assertIn("1 file changed but not committed", review["empty_reason"])

    # ---- helpers ----------------------------------------------------------------------

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root)
        tasks = self.root / "tasks"
        inbox = tasks / ".inbox"
        inbox.mkdir(parents=True)
        for module, name, value in ((tasklib, "TASKS", tasks), (tasklib, "INBOX", inbox), (tasklib, "STATE", inbox / ".state.json"),
                                    (on_task_change, "INBOX", inbox), (on_task_change, "TASKS", tasks),
                                    (board_tool, "TASKS", tasks), (lead_review, "REVIEWS", tasks / "reviews")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)

    def _a_task_being_built(self):
        project, worktree = self.root / "shop", self.root / "shop-wt"
        project.mkdir()
        _git(project, "init", "-q", "-b", "main")
        (project / "app.py").write_text("def total():\n    return 1\n")
        _git(project, "add", ".")
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
        start = _git(project, "rev-parse", "HEAD").strip()
        _git(project, "worktree", "add", "-q", "-b", "feature-total", str(worktree))
        task = tasklib.TASKS / "TASK-001-total.md"
        task.write_text(f"---\nid: TASK-001\ntitle: Total\nstatus: in-dev\nproject: {project}\nbase: main\nbranch: feature-total\n"
                        f"from_commit: {start}\ndev: dev\nreviewer:\nworktree: {worktree}\n---\n")
        state = tasklib.load_state()
        state["TASK-001"] = "in-dev"
        tasklib.save_state(state)
        return task, worktree

    def _dev_sets(self, task: Path, status: str):
        task.write_text(task.read_text().replace("status: in-dev", f"status: {status}"))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code = on_task_change.process(task)
        return code, err.getvalue()


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    unittest.main()
