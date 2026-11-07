"""Several agents per role sharing the board: task numbers, claims, worktrees, routing, notifications.

    python3 -m unittest discover team/tests      (from the Hive folder; works on temporary copies)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]   # the Hive folder


class MultiAgentTest(unittest.TestCase):

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.kit = tmp / "kit"
        shutil.copytree(KIT / "team", self.kit / "team", ignore=shutil.ignore_patterns("__pycache__"))
        self.project = tmp / "code" / "api"
        self.project.mkdir(parents=True)
        self._git("init", "-q", "-b", "main")
        self._commit("app.py", "init")

    # ---- tasks and claims -------------------------------------------------------------

    def test_tasks_created_at_the_same_moment_get_different_numbers(self):
        with ThreadPoolExecutor(10) as pool:
            made = list(pool.map(lambda i: self._run("new_task.py", self.project, f"Task {i}", agent=f"techlead-{i % 2 + 1}"), range(10)))

        ids = {Path(r.stdout.splitlines()[0]).name[:8] for r in made}

        self.assertEqual(len(ids), 10)

    def test_a_task_records_which_tech_lead_wrote_it(self):
        task = self._a_task(agent="techlead-2")

        writer = self._field(task, "techlead")

        self.assertEqual(writer, "techlead-2")

    def test_the_readiness_gate_sends_an_unready_spec_back_to_draft(self):
        task = self._a_task()

        self._set_status(task, "ready-for-dev")

        self.assertEqual(self._field(task, "status"), "draft")

    def test_two_devs_claiming_at_once_only_one_gets_the_task(self):
        task = self._a_ready_task()

        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(lambda dev: self._run("claim.py", self._id(task), "dev", agent=dev), ["dev", "dev-2"]))

        self.assertEqual(sorted(r.returncode == 0 for r in results), [False, True])
        self.assertIn("not waiting for a dev", next(r for r in results if r.returncode != 0).stderr)
        self.assertEqual(self._field(task, "status"), "in-dev")

    # ---- worktrees --------------------------------------------------------------------

    def test_a_claimed_task_gets_its_own_worktree_on_its_branch_and_the_project_stays_on_main(self):
        task = self._a_ready_task()

        self._claim(task, "dev", "dev")

        worktree = Path(self._field(task, "worktree"))
        self.assertEqual(worktree, self.project.parent / "api.worktrees" / self._field(task, "branch"))
        self.assertEqual(self._branch(worktree), self._field(task, "branch"))
        self.assertEqual(self._branch(self.project), "main")

    def test_each_dev_works_in_its_own_worktree(self):
        first, second = self._a_ready_task("First"), self._a_ready_task("Second")

        self._claim(first, "dev", "dev")
        self._claim(second, "dev", "dev-2")

        self.assertNotEqual(self._field(first, "worktree"), self._field(second, "worktree"))

    def test_when_done_the_worktree_is_removed_and_the_branch_kept(self):
        task = self._a_claimed_task("dev")
        worktree = Path(self._field(task, "worktree"))
        self._set_status(task, "done")

        done = self._run("worktree.py", "remove", self._id(task))

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertFalse(worktree.exists())
        self.assertEqual(self._field(task, "worktree"), "")
        self.assertIn(self._field(task, "branch"), self._git("branch"))

    # ---- base branch ------------------------------------------------------------------

    def test_a_new_task_bases_on_the_branch_the_lead_has_checked_out(self):
        self._git("checkout", "-q", "-b", "develop")

        made = self._run("new_task.py", self.project, "On develop", agent="techlead")

        self.assertEqual(self._field(Path(made.stdout.splitlines()[0]), "base"), "develop")
        self.assertIn("Knowledge: none yet for api", made.stdout)

    def test_the_worktree_starts_from_the_base_branch(self):
        self._git("checkout", "-q", "-b", "develop")
        self._commit("dev_only.py", "develop work")
        task = self._a_ready_task()
        self._git("checkout", "-q", "main")

        self._claim(task, "dev", "dev")

        self.assertTrue((Path(self._field(task, "worktree")) / "dev_only.py").exists())

    def test_a_base_that_exists_only_on_the_remote_is_used_as_origin_base(self):
        self._git("update-ref", "refs/remotes/origin/release-2", "main")
        task = self._a_ready_task()
        task.write_text(task.read_text().replace("base: main", "base: release-2", 1))

        done = self._run("claim.py", self._id(task), "dev", agent="dev")

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertTrue((Path(self._field(task, "worktree")) / "app.py").exists())

    # ---- routing and notifications ----------------------------------------------------

    def test_rework_goes_back_to_the_dev_who_built_it(self):
        task = self._a_reviewed_task(dev="dev", reviewer="reviewer-2")

        self._set_status(task, "changes-requested")

        self.assertIn(self._id(task), self._notifications("dev", "dev"))
        self.assertNotIn(self._id(task), self._run("inbox.py", "dev", agent="dev-2").stdout)
        refused = self._run("claim.py", self._id(task), "dev", agent="dev-2")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("dev", refused.stderr)

    def test_a_re_review_goes_back_to_the_same_reviewer(self):
        task = self._a_reviewed_task(dev="dev", reviewer="reviewer-2")
        self._set_status(task, "changes-requested")
        self._claim(task, "dev", "dev")

        self._set_status(task, "ready-for-review")

        self.assertIn(self._id(task), self._notifications("reviewer", "reviewer-2"))
        self.assertNotEqual(self._run("claim.py", self._id(task), "reviewer", agent="reviewer").returncode, 0)

    def test_a_shared_pool_notification_shows_once_per_agent(self):
        self._a_pool_notification("dev", "TASK-777")

        first, again = self._notifications("dev", "dev-3"), self._notifications("dev", "dev-3")

        self.assertIn("TASK-777", first)
        self.assertNotIn("TASK-777", again)
        self.assertIn("TASK-777", self._notifications("dev", "dev-4"))

    def test_without_an_agent_id_the_agent_is_its_role(self):
        self._a_task()

        done = self._run("inbox.py", "dev")

        self.assertIn("notifications for dev", done.stdout)

    def test_a_blocked_task_says_who_blocked_it_to_the_lead_and_on_the_board(self):
        task = self._a_claimed_task("dev")

        self._set_status(task, "blocked")

        self.assertEqual(self._field(task, "blocked_by"), "dev")
        self.assertIn("by dev", self._run("inbox.py", "lead").stdout)
        self.assertIn("blocked by dev", self._board())

    def test_unblocking_clears_who_blocked_it_and_the_board_shows_who_works_on_it(self):
        task = self._a_claimed_task("dev")
        self._set_status(task, "blocked")

        self._set_status(task, "in-dev")

        self.assertEqual(self._field(task, "blocked_by"), "")
        in_dev = self._board().split("## in-dev")[1]
        self.assertIn(self._id(task), in_dev)
        self.assertIn("· dev", in_dev)

    # ---- helpers ----------------------------------------------------------------------

    def _a_task(self, title: str = "A task", agent: str = "techlead") -> Path:
        done = self._run("new_task.py", self.project, title, agent=agent)
        self.assertEqual(done.returncode, 0, done.stderr)
        return Path(done.stdout.splitlines()[0])

    def _a_ready_task(self, title: str = "A task") -> Path:
        """Ready for dev without a full spec: the readiness gate is tested on its own."""
        task = self._a_task(title)
        task.write_text(task.read_text().replace("status: draft", "status: ready-for-dev", 1))
        return task

    def _a_claimed_task(self, dev: str) -> Path:
        task = self._a_ready_task()
        self._claim(task, "dev", dev)
        return task

    def _a_reviewed_task(self, dev: str, reviewer: str) -> Path:
        task = self._a_claimed_task(dev)
        self._set_status(task, "ready-for-review")
        self._claim(task, "reviewer", reviewer)
        return task

    def _a_pool_notification(self, role: str, task_id: str) -> None:
        """A line in a role's shared pool, as the hook writes it for new work."""
        inbox = self.kit / "data" / "tasks" / ".inbox"
        inbox.mkdir(parents=True, exist_ok=True)
        with (inbox / f"{role}.md").open("a") as f:
            f.write(f"- [2026-10-20 10:00] **{task_id}** [api] New work → `ready-for-dev` (was `draft`) — x\n")

    def _claim(self, task: Path, role: str, agent: str) -> None:
        done = self._run("claim.py", self._id(task), role, agent=agent)
        self.assertEqual(done.returncode, 0, done.stderr)

    def _set_status(self, task: Path, value: str) -> None:
        task.write_text(task.read_text().replace(f"status: {self._field(task, 'status')}", f"status: {value}", 1))
        subprocess.run([sys.executable, str(self.kit / "team" / "tools" / "on_task_change.py")],
                       input=f'{{"tool_input": {{"file_path": "{task}"}}}}', text=True, capture_output=True)

    def _notifications(self, role: str, agent: str) -> str:
        """The notifications part of an agent's inbox (before the tasks it can take)."""
        return self._run("inbox.py", role, agent=agent).stdout.split("## Tasks")[0]

    def _board(self) -> str:
        return (self.kit / "data" / "tasks" / "BOARD.md").read_text()

    def _run(self, script: str, *args, agent: str | None = None) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "AGENT_ID"}
        if agent:
            env["AGENT_ID"] = agent
        return subprocess.run([sys.executable, str(self.kit / "team" / "tools" / script), *map(str, args)],
                              capture_output=True, text=True, env=env)

    def _field(self, task: Path, name: str) -> str:
        return next(line.split(":", 1)[1].split("#")[0].strip() for line in task.read_text().splitlines()
                    if line.startswith(f"{name}:"))

    def _id(self, task: Path) -> str:
        return task.name[:8]

    def _branch(self, folder: Path) -> str:
        return subprocess.run(["git", "-C", str(folder), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()

    def _commit(self, file: str, message: str) -> None:
        (self.project / file).write_text("x = 1\n")
        self._git("add", ".")
        self._git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", message)

    def _git(self, *args: str) -> str:
        return subprocess.run(["git", "-C", str(self.project), *args], check=True, capture_output=True, text=True).stdout


if __name__ == "__main__":
    unittest.main()
