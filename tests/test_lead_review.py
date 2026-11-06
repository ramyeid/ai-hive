"""The lead's code review: the branch's diff, line comments, rounds sent back to the dev, and the dev's replies.

    python3 -m unittest tests/test_lead_review.py      (from the kit folder; works on temporary copies)
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


class LeadReviewTest(unittest.TestCase):

    def test_the_diff_shows_each_changed_file_with_its_line_numbers(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="ready-for-review")

        diff = self._call(kit, f"diff('{self._id(task)}')")

        self.assertEqual([(f["path"], f["additions"], f["deletions"]) for f in diff["files"]], [("app.py", 1, 1)])
        self.assertEqual(self._changed_lines(diff), [("-", 2, None, "return 1"), ("+", None, 2, "return 2")])

    def test_requesting_changes_sends_the_task_back_to_the_dev_who_built_it(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="ready-for-review")
        self._a_comment(kit, task, "Name it total.")

        self._call(kit, f"submit('{self._id(task)}', 'changes')")

        self.assertEqual(self._field(task, "status"), "changes-requested")
        self.assertIn(self._id(task), (kit / "tasks" / ".inbox" / "agents" / "dev-2.md").read_text())
        self.assertEqual(self._last_activity(kit)["actor"], "lead")

    def test_the_round_is_written_into_the_task_file_where_the_agents_read_it(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="ready-for-review")
        self._a_comment(kit, task, "Name it total.", file="app.py", line=2, code="    return 2")

        self._call(kit, f"submit('{self._id(task)}', 'changes', 'Close, two things.')")

        section = task.read_text().split("## Lead Review", 1)[1]
        self.assertIn("### Round 1", section)
        self.assertIn("Close, two things.", section)
        self.assertIn("1. `app.py:2`\n   ```\n       return 2\n   ```\n   Name it total.\n   - Reply:", section)

    def test_the_devs_reply_is_read_back_with_its_comment(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_sent_back_with_a_comment(kit, project, "Name it total.")
        self._the_dev_replies(task, "Fixed in abc1234: renamed.")

        rounds = self._call(kit, f"rounds('{self._id(task)}')")

        self.assertEqual((rounds[0]["comments"][0]["body"], rounds[0]["comments"][0]["reply"]),
                         ("Name it total.", "Fixed in abc1234: renamed."))

    def test_approving_records_the_round_and_leaves_the_task_where_it_is(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="ready-for-review")

        self._call(kit, f"submit('{self._id(task)}', 'approve')")

        self.assertEqual(self._field(task, "status"), "ready-for-review")
        self.assertIn("### Round 1", task.read_text())
        self.assertIn("approved", task.read_text().split("### Round 1", 1)[1].splitlines()[0])

    def test_changes_cannot_be_requested_while_the_dev_is_working_and_the_comments_are_kept(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="in-dev")
        self._a_comment(kit, task, "Name it total.")

        done = self._call_run(kit, f"submit('{self._id(task)}', 'changes')")

        self.assertIn("the dev is working on it", done.stderr)
        self.assertEqual(len(self._call(kit, f"load('{self._id(task)}')")["pending"]), 1)

    def test_a_done_task_can_be_sent_back_to_its_dev(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_built_by(kit, project, "dev-2", status="done")
        self._a_comment(kit, task, "One more thing.")

        self._call(kit, f"submit('{self._id(task)}', 'changes')")

        self.assertEqual(self._field(task, "status"), "changes-requested")

    def test_since_the_last_review_shows_only_what_the_dev_changed_after_it(self):
        kit, project = self._a_kit(), self._a_project()
        task = self._a_task_sent_back_with_a_comment(kit, project, "Name it total.")
        self._the_dev_commits(task, "total.py")

        diff = self._call(kit, f"diff('{self._id(task)}', 'since')")

        self.assertEqual([f["path"] for f in diff["files"]], ["total.py"])

    # ---- helpers ----

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("tasks", "knowledge", "coach", "console", ".git", "__pycache__"))
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit

    def _a_project(self) -> Path:
        project = Path(tempfile.mkdtemp()) / "shop"
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        _git(project, "init", "-q", "-b", "main")
        (project / "app.py").write_text("def total():\n    return 1\n")
        _git(project, "add", ".")
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
        return project

    def _a_task_built_by(self, kit: Path, project: Path, dev: str, status: str) -> Path:
        task = Path(self._script(kit, "new_task.py", str(project), "Compute the total", agent="techlead").splitlines()[0])
        self._set_field(task, "status", "ready-for-dev")
        self._script(kit, "claim.py", self._id(task), "dev", agent=dev)
        folder = Path(self._field(task, "worktree"))
        (folder / "app.py").write_text("def total():\n    return 2\n")
        _git(folder, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qam", "change the total")
        self._set_field(task, "status", status)
        return task

    def _a_task_sent_back_with_a_comment(self, kit: Path, project: Path, body: str) -> Path:
        task = self._a_task_built_by(kit, project, "dev-2", status="ready-for-review")
        self._a_comment(kit, task, body, file="app.py", line=2, code="    return 2")
        self._call(kit, f"submit('{self._id(task)}', 'changes')")
        return task

    def _a_comment(self, kit: Path, task: Path, body: str, file: str = "", line: int = 0, code: str = "") -> None:
        self._call(kit, f"add_comment('{self._id(task)}', {body!r}, {file!r}, {line or None}, 'new', {code!r})")

    def _the_dev_replies(self, task: Path, reply: str) -> None:
        task.write_text(task.read_text().replace("   - Reply:", f"   - Reply: {reply}", 1))

    def _the_dev_commits(self, task: Path, file: str) -> None:
        folder = Path(self._field(task, "worktree"))
        (folder / file).write_text("x\n")
        _git(folder, "add", ".")
        _git(folder, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", f"add {file}")

    def _changed_lines(self, diff: dict) -> list[tuple]:
        lines = [l for f in diff["files"] for h in f["hunks"] for l in h["lines"] if l["t"] != " "]
        return [(l["t"], l["o"], l["n"], l["s"].strip()) for l in lines]

    def _last_activity(self, kit: Path) -> dict:
        return json.loads((kit / "tasks" / ".inbox" / "activity.jsonl").read_text().splitlines()[-1])

    def _id(self, task: Path) -> str:
        return task.name[:8]

    def _field(self, task: Path, name: str) -> str:
        line = next(l for l in task.read_text().splitlines() if l.startswith(f"{name}:"))
        return line.split(":", 1)[1].split("#")[0].strip()

    def _set_field(self, task: Path, name: str, value: str) -> None:
        task.write_text(re.sub(rf"^{name}:[^\n#]*", f"{name}: {value} ", task.read_text(), count=1, flags=re.M))

    def _call(self, kit: Path, expression: str):
        done = self._call_run(kit, expression)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def _call_run(self, kit: Path, expression: str) -> subprocess.CompletedProcess:
        code = (f"import json, sys; sys.path.insert(0, {str(kit / 'scripts')!r}); from lead_review import *\n"
                f"try:\n    print(json.dumps({expression}))\n"
                f"except ReviewError as e:\n    sys.exit(str(e))")
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env={**os.environ, "AGENT_ID": ""})

    def _script(self, kit: Path, script: str, *args: str, agent: str) -> str:
        done = subprocess.run([sys.executable, str(kit / "scripts" / script), *args],
                              capture_output=True, text=True, env={**os.environ, "AGENT_ID": agent})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    unittest.main()
