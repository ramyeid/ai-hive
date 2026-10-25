"""Feature branches: one feature-<title> branch per feature, follow-up tasks add commits on top.

    python3 -m unittest tests/test_feature_branches.py      (from the kit folder; works on temporary copies)
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


class FeatureBranchTest(unittest.TestCase):

    def test_a_new_task_gets_a_feature_branch_named_after_its_title(self):
        kit, project = self._a_kit(), self._a_project("shop")

        task = self._new_task(kit, project, "Filter orders by status")

        self.assertEqual(self._field(task, "branch"), "feature-filter-orders-by-status")
        self.assertEqual(self._field(task, "follows"), "")

    def test_a_new_feature_whose_branch_name_is_taken_gets_a_numbered_branch(self):
        kit, project = self._a_kit(), self._a_project("shop")
        self._a_branch_in(project, "feature-filter-orders-by-status")

        task = self._new_task(kit, project, "Filter orders by status")

        self.assertEqual(self._field(task, "branch"), "feature-filter-orders-by-status-2")

    def test_a_follow_up_reuses_the_branch_and_the_base_of_the_task_it_follows(self):
        kit, project = self._a_kit(), self._a_project("shop")
        first = self._new_task(kit, project, "Filter orders by status")
        self._set_field(first, "base", "develop")

        follow_up = self._new_task(kit, project, "Show the filter as a dropdown", "--follow-up", self._id(first))

        self.assertEqual(self._field(follow_up, "branch"), "feature-filter-orders-by-status")
        self.assertEqual(self._field(follow_up, "base"), "develop")
        self.assertEqual(self._field(follow_up, "follows"), self._id(first))

    def test_the_first_claim_records_the_commit_where_the_tasks_changes_start(self):
        kit, project = self._a_kit(), self._a_project("shop")
        task = self._a_task_ready_for_dev(kit, project, "Filter orders by status")

        self._claim(kit, task, "dev")

        self.assertEqual(self._field(task, "from_commit"), self._head(project))

    def test_a_follow_up_works_on_the_same_branch_on_top_of_the_earlier_commits(self):
        kit, project = self._a_kit(), self._a_project("shop")
        first = self._a_finished_task_with_a_commit(kit, project, "Filter orders by status")
        follow_up = self._a_follow_up_ready_for_dev(kit, project, first, "Show the filter as a dropdown")

        self._claim(kit, follow_up, "dev")

        folder = Path(self._field(follow_up, "worktree"))
        self.assertEqual(self._git(folder, "branch", "--show-current").stdout.strip(), "feature-filter-orders-by-status")
        self.assertTrue((folder / "filter.py").exists())
        self.assertEqual(self._field(follow_up, "from_commit"), self._git(folder, "rev-parse", "--short", "HEAD").stdout.strip())

    def test_a_follow_up_cannot_be_claimed_while_the_earlier_task_is_still_in_progress(self):
        kit, project = self._a_kit(), self._a_project("shop")
        first = self._a_task_ready_for_dev(kit, project, "Filter orders by status")
        self._claim(kit, first, "dev")
        follow_up = self._a_follow_up_ready_for_dev(kit, project, first, "Show the filter as a dropdown")

        done = self._claim_run(kit, follow_up, "dev", agent="dev-2")

        self.assertNotEqual(done.returncode, 0)
        self.assertIn(f"where {self._id(first)} is still `in-dev`", done.stderr)

    def test_finishing_a_task_keeps_the_branch_folder_while_a_follow_up_is_waiting(self):
        kit, project = self._a_kit(), self._a_project("shop")
        first = self._a_task_ready_for_dev(kit, project, "Filter orders by status")
        folder = Path(self._claim_and_get_folder(kit, first))
        self._a_follow_up_ready_for_dev(kit, project, first, "Show the filter as a dropdown")
        self._set_field(first, "status", "done")

        output = self._script(kit, "worktree.py", "remove", self._id(first))

        self.assertIn("isn't done yet", output)
        self.assertTrue(folder.exists())

    def test_a_branch_checked_out_in_the_project_folder_is_refused(self):
        kit, project = self._a_kit(), self._a_project("shop")
        task = self._a_task_ready_for_dev(kit, project, "Filter orders by status")
        self._lead_checks_out(project, "feature-filter-orders-by-status")

        done = self._claim_run(kit, task, "dev")

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("is checked out in your project folder", done.stderr)

    def test_an_existing_folder_for_the_branch_is_reused_even_under_an_old_name(self):
        kit, project = self._a_kit(), self._a_project("shop")
        task = self._a_task_ready_for_dev(kit, project, "Filter orders by status")
        old_folder = self._an_old_per_task_worktree(project, "feature-filter-orders-by-status", "TASK-001")

        self._claim(kit, task, "dev")

        self.assertEqual(Path(self._field(task, "worktree")), old_folder)

    # ---- helpers ----------------------------------------------------------------------

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("tasks", "knowledge", "console", ".git", "__pycache__"))
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit

    def _a_project(self, name: str) -> Path:
        project = Path(tempfile.mkdtemp()) / name
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        self._git(project, "init", "-q", "-b", "main")
        self._commit(project, "README.md")
        return project

    def _a_task_ready_for_dev(self, kit: Path, project: Path, title: str, *args: str) -> Path:
        task = self._new_task(kit, project, title, *args)
        self._set_field(task, "status", "ready-for-dev")
        return task

    def _a_follow_up_ready_for_dev(self, kit: Path, project: Path, first: Path, title: str) -> Path:
        return self._a_task_ready_for_dev(kit, project, title, "--follow-up", self._id(first))

    def _a_finished_task_with_a_commit(self, kit: Path, project: Path, title: str) -> Path:
        task = self._a_task_ready_for_dev(kit, project, title)
        folder = Path(self._claim_and_get_folder(kit, task))
        self._commit(folder, "filter.py")
        self._set_field(task, "status", "done")
        self._script(kit, "worktree.py", "remove", self._id(task))
        return task

    def _claim_and_get_folder(self, kit: Path, task: Path) -> str:
        self._claim(kit, task, "dev")
        return self._field(task, "worktree")

    def _an_old_per_task_worktree(self, project: Path, branch: str, task_id: str) -> Path:
        folder = project.parent / f"{project.name}.worktrees" / task_id
        self._git(project, "worktree", "add", "-q", str(folder), "-b", branch)
        return folder

    def _a_branch_in(self, project: Path, branch: str) -> None:
        self._git(project, "branch", branch)

    def _lead_checks_out(self, project: Path, branch: str) -> None:
        self._git(project, "checkout", "-q", "-b", branch)

    def _commit(self, folder: Path, file: str) -> None:
        (folder / file).write_text("change\n")
        self._git(folder, "add", ".")
        self._git(folder, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", f"add {file}")

    def _head(self, project: Path) -> str:
        return self._git(project, "rev-parse", "--short", "HEAD").stdout.strip()

    def _id(self, task: Path) -> str:
        return task.name[:8]

    def _field(self, task: Path, name: str) -> str:
        line = next(l for l in task.read_text().splitlines() if l.startswith(f"{name}:"))
        return line.split(":", 1)[1].split("#")[0].strip()

    def _set_field(self, task: Path, name: str, value: str) -> None:
        text = task.read_text()
        task.write_text(re.sub(rf"^{name}:[^\n#]*", f"{name}: {value} ", text, count=1, flags=re.M))

    def _new_task(self, kit: Path, project: Path, title: str, *args: str) -> Path:
        return Path(self._script(kit, "new_task.py", str(project), title, *args, agent="techlead").splitlines()[0])

    def _claim(self, kit: Path, task: Path, role: str, agent: str = "dev") -> str:
        done = self._claim_run(kit, task, role, agent)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def _claim_run(self, kit: Path, task: Path, role: str, agent: str = "dev") -> subprocess.CompletedProcess:
        return self._script_run(kit, "claim.py", self._id(task), role, agent=agent)

    def _script(self, kit: Path, script: str, *args: str, agent: str = "dev") -> str:
        done = self._script_run(kit, script, *args, agent=agent)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def _script_run(self, kit: Path, script: str, *args: str, agent: str = "dev") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(kit / "scripts" / script), *args],
                              capture_output=True, text=True, env={**os.environ, "AGENT_ID": agent})

    def _git(self, folder: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
