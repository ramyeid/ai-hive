"""Landing a finished branch: clean up its history like `git rebase -i`, on top of origin's main, push it, and
clean up once the lead has merged the pull request on GitHub.

    python3 -m unittest discover team/tests      (from the Hive folder; works on temporary copies)
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

KIT = Path(__file__).resolve().parents[2]   # the Hive folder
WHO = {"GIT_AUTHOR_NAME": "Lead", "GIT_AUTHOR_EMAIL": "lead@example.com",
       "GIT_COMMITTER_NAME": "Lead", "GIT_COMMITTER_EMAIL": "lead@example.com"}


class LandTest(unittest.TestCase):

    def setUp(self):
        self.kit, self.project = self._a_kit(), self._a_project("shop")
        self.github = self._a_github_copy_of(self.project)
        self.gh_state = "OPEN"
        self.bin = self._a_fake_gh()
        self.task = self._a_finished_task_with_commits("Filter orders by status",
                                                       ["add the filter", "fix a typo", "add tests"])

    def test_the_plan_lists_the_branchs_commits_oldest_first(self):
        plan = self._land("plan", self._id(self.task))

        self.assertEqual([c["subject"] for c in plan["commits"]], ["add the filter", "fix a typo", "add tests"])
        self.assertEqual(plan["onto"], "origin/main")
        self.assertEqual(plan["not_ready"], "")
        self.assertTrue(plan["draft_message"].startswith("Filter orders by status"))

    def test_squashing_everything_leaves_one_commit_with_the_leads_message_on_top_of_origins_main(self):
        self._someone_merges_on_github("other.py")
        commits = self._land("plan", self._id(self.task))["commits"]

        self._land("clean_up", self._id(self.task),
                   [{"sha": commits[0]["sha"], "action": "pick"}, {"sha": commits[1]["sha"], "action": "fixup"},
                    {"sha": commits[2]["sha"], "action": "squash"}],
                   ["Filter orders by status\n\nTasks: TASK-001"])

        log = self._log("feature-filter-orders-by-status", "origin/main")
        self.assertEqual(log, ["Filter orders by status\n\nTasks: TASK-001"])
        self.assertEqual(self._git(self.project, "merge-base", "--is-ancestor", "origin/main",
                                   "feature-filter-orders-by-status", check=False).returncode, 0)
        self.assertEqual(self._files_on("feature-filter-orders-by-status"), {"README.md", "other.py", "add-the-filter.txt",
                                                                          "fix-a-typo.txt", "add-tests.txt"})

    def test_commits_can_be_reordered_dropped_and_kept_with_new_messages(self):
        c = self._land("plan", self._id(self.task))["commits"]

        self._land("clean_up", self._id(self.task),
                   [{"sha": c[2]["sha"], "action": "pick"}, {"sha": c[0]["sha"], "action": "pick"},
                    {"sha": c[1]["sha"], "action": "drop"}],
                   ["Test the filter", "Filter orders by status"])

        self.assertEqual(self._log("feature-filter-orders-by-status", "origin/main"), ["Test the filter", "Filter orders by status"])
        self.assertNotIn("fix-a-typo.txt", self._files_on("feature-filter-orders-by-status"))

    def test_the_teams_history_is_kept_and_undo_puts_it_back(self):
        before = self._rev("feature-filter-orders-by-status")
        c = self._land("plan", self._id(self.task))["commits"]
        self._land("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "pick" if i == 0 else "fixup"}
                                                       for i, x in enumerate(c)], ["One commit"])

        self.assertEqual(self._rev("refs/hive/pre-land/feature-filter-orders-by-status"), before)
        self._land("undo", self._id(self.task))
        self.assertEqual(self._rev("feature-filter-orders-by-status"), before)

    def test_a_conflict_with_main_changes_nothing_and_names_the_files(self):
        before = self._rev("feature-filter-orders-by-status")
        self._someone_merges_on_github("add-the-filter.txt", "someone else's version\n")
        c = self._land("plan", self._id(self.task))["commits"]

        error = self._land_error("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "pick"} for x in c],
                                 [x["subject"] for x in c])

        self.assertIn("conflicts in add-the-filter.txt", error)
        self.assertEqual(self._rev("feature-filter-orders-by-status"), before)
        self.assertEqual(self._git(Path(self._land("folder_of", self._id(self.task))), "status", "--porcelain").stdout, "")

    def test_choices_for_an_outdated_list_of_commits_are_refused(self):
        c = self._land("plan", self._id(self.task))["commits"]

        error = self._land_error("clean_up", self._id(self.task), [{"sha": c[0]["sha"], "action": "pick"}], ["Just one"])

        self.assertIn("changed since you opened this", error)

    def test_the_first_kept_commit_cannot_be_squashed_into_nothing(self):
        c = self._land("plan", self._id(self.task))["commits"]

        error = self._land_error("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "squash"} for x in c], ["x"])

        self.assertIn("can't be squashed into one above it", error)

    def test_a_branch_with_a_task_not_done_cannot_be_landed(self):
        self._set_field(self.task, "status", "in-review")
        c = self._land("plan", self._id(self.task))["commits"]

        error = self._land_error("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "pick"} for x in c],
                                 [x["subject"] for x in c])

        self.assertIn("TASK-001 is `in-review`", error)

    def test_push_sends_the_cleaned_branch_to_github(self):
        c = self._land("plan", self._id(self.task))["commits"]
        self._land("push", self._id(self.task))
        self._land("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "pick" if i == 0 else "fixup"}
                                                       for i, x in enumerate(c)], ["One commit"])

        self._land("push", self._id(self.task))   # replaces what was pushed before the clean-up

        self.assertEqual(self._git(self.github, "rev-parse", "feature-filter-orders-by-status").stdout.strip(),
                         self._rev("feature-filter-orders-by-status"))

    def test_a_branch_deleted_on_github_is_not_taken_for_pushed_and_can_be_pushed_again(self):
        self._land("push", self._id(self.task))
        self._git(self.github, "branch", "-D", "feature-filter-orders-by-status")   # deleted on GitHub; our copy is stale

        plan = self._land("plan", self._id(self.task))
        self.assertFalse(plan["on_origin"])
        self._land("push", self._id(self.task))

        self.assertEqual(self._git(self.github, "rev-parse", "feature-filter-orders-by-status").stdout.strip(),
                         self._rev("feature-filter-orders-by-status"))

    def test_no_pull_request_for_a_branch_that_is_not_on_github(self):
        error = self._land_error("open_pr", self._id(self.task), "Filter orders by status", "body")

        self.assertIn("Push the branch first", error)

    def test_the_local_main_is_fast_forwarded_when_nothing_has_it_checked_out(self):
        self._git(self.project, "checkout", "-q", "--detach")
        self._someone_merges_on_github("other.py")

        self._land("update_base", self._land("_branch", self._id(self.task))[0])

        self.assertEqual(self._rev("main"), self._rev("origin/main"))

    def test_the_local_main_checked_out_in_the_project_folder_is_left_alone(self):
        before = self._rev("main")
        self._someone_merges_on_github("other.py")

        result = self._land("update_base", self._land("_branch", self._id(self.task))[0])

        self.assertEqual(self._rev("main"), before)
        self.assertIn("checked out", result["local"])

    def test_the_landing_worktree_is_recreated_when_the_reviewer_removed_it(self):
        folder = Path(self._land("folder_of", self._id(self.task)))

        self.assertTrue(folder.is_dir())
        self.assertEqual(self._git(folder, "branch", "--show-current").stdout.strip(), "feature-filter-orders-by-status")

    def test_the_pull_request_is_opened_with_gh_and_noted_on_every_task_of_the_branch(self):
        self._land("push", self._id(self.task))

        opened = self._land("open_pr", self._id(self.task), "Filter orders by status", "## Why\n…")

        self.assertEqual(opened["url"], "https://github.com/acme/shop/pull/12")
        self.assertIn("pr create --base main --head feature-filter-orders-by-status --title Filter orders by status",
                      self._gh_calls())
        self.assertEqual(self._field(self.task, "pr"), "https://github.com/acme/shop/pull/12")

    def test_once_the_lead_merged_on_github_the_worktree_and_the_local_branch_are_removed(self):
        self._land("push", self._id(self.task))
        self._land("open_pr", self._id(self.task), "Filter orders by status", "body")
        folder = Path(self._land("folder_of", self._id(self.task)))
        self.gh_state = "MERGED"

        self._land("check")

        self.assertFalse(folder.exists())
        self.assertEqual(self._git(self.project, "branch", "--list", "feature-filter-orders-by-status").stdout, "")

    def test_an_open_pull_request_is_left_alone(self):
        self._land("push", self._id(self.task))
        self._land("open_pr", self._id(self.task), "Filter orders by status", "body")

        self._land("check")

        self.assertNotEqual(self._git(self.project, "branch", "--list", "feature-filter-orders-by-status").stdout, "")

    def test_the_coach_still_sees_the_leads_own_commits_after_the_history_was_squashed(self):
        folder = Path(self._land("folder_of", self._id(self.task)))
        (folder / "fix.txt").write_text("the lead's fix\n")
        self._git(folder, "add", ".")
        self._git(folder, "commit", "-qm", "Use the existing status enum")   # no Agent: line
        c = self._land("plan", self._id(self.task))["commits"]
        self._land("clean_up", self._id(self.task), [{"sha": x["sha"], "action": "pick" if i == 0 else "fixup"}
                                                       for i, x in enumerate(c)], ["One commit\n\nAgent: dev"])

        code = (f"import sys, json; sys.path.insert(0, {str(self.kit / 'team' / 'tools')!r}); import coach, tasklib\n"
                f"meta = tasklib.parse(tasklib.find_task({self._id(self.task)!r}))\n"
                f"print(json.dumps(coach._local_commits(meta, pre_landing=True)))")
        done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)

        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("Use the existing status enum", "\n".join(json.loads(done.stdout)))

    # ---- helpers ----------------------------------------------------------------------

    def _land(self, fn: str, *args):
        done = self._land_run(fn, *args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return json.loads(done.stdout)

    def _land_error(self, fn: str, *args) -> str:
        done = self._land_run(fn, *args)
        self.assertEqual(done.returncode, 3, done.stderr)
        return done.stderr

    def _land_run(self, fn: str, *args) -> subprocess.CompletedProcess:
        call = "str(land.folder(land._branch(args[0])[0]))" if fn == "folder_of" else f"land.{fn}(*args)"
        code = (f"import sys, json; sys.path.insert(0, {str(self.kit / 'team' / 'tools')!r}); import land\n"
                f"args = json.loads({json.dumps(json.dumps(args))})\n"
                f"try:\n    print(json.dumps({call}))\n"
                f"except land.LandError as e:\n    print(e, file=sys.stderr); sys.exit(3)")
        (self.bin / "state").write_text(self.gh_state)
        return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                              env={**os.environ, **WHO, "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}"})

    def _a_fake_gh(self) -> Path:
        """A stand-in for the GitHub CLI: logs its arguments; the pull request is #12, its state in bin/state."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        (folder / "gh").write_text(f"""#!{sys.executable}
import json, sys
from pathlib import Path
here = Path(__file__).parent
with (here / "calls").open("a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:2] == ["pr", "create"]:
    print("https://github.com/acme/shop/pull/12")
elif args[:2] == ["pr", "list"]:
    print("[]")
elif args[:2] == ["pr", "view"]:
    print(json.dumps({{"state": (here / "state").read_text()}}))
""")
        (folder / "gh").chmod(0o755)
        return folder

    def _gh_calls(self) -> str:
        return (self.bin / "calls").read_text()

    def _a_finished_task_with_commits(self, title: str, subjects: list[str]) -> Path:
        task = Path(self._script("new_task.py", str(self.project), title, agent="techlead").splitlines()[0])
        self._set_field(task, "status", "ready-for-dev")
        self._script("claim.py", self._id(task), "dev")
        folder = Path(self._field(task, "worktree"))
        for subject in subjects:
            self._commit(folder, re.sub(r"\W+", "-", subject) + ".txt", subject)
        self._set_field(task, "status", "done")
        self._script("worktree.py", "remove", self._id(task))
        return task

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT / "team", kit / "team", ignore=shutil.ignore_patterns("__pycache__"))
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit

    def _a_project(self, name: str) -> Path:
        project = Path(tempfile.mkdtemp()) / name
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        self._git(project, "init", "-q", "-b", "main")
        self._commit(project, "README.md", "start")
        return project

    def _a_github_copy_of(self, project: Path) -> Path:
        github = project.parent / "github.git"
        self._git(project.parent, "clone", "-q", "--bare", str(project), str(github))
        self._git(project, "remote", "add", "origin", str(github))
        self._git(project, "fetch", "-q", "origin")
        return github

    def _someone_merges_on_github(self, file: str, content: str = "change\n") -> None:
        elsewhere = self.github.parent / "elsewhere"
        if not elsewhere.exists():
            self._git(self.github.parent, "clone", "-q", str(self.github), str(elsewhere))
        (elsewhere / file).write_text(content)
        self._git(elsewhere, "add", ".")
        self._git(elsewhere, "commit", "-qm", f"add {file}")
        self._git(elsewhere, "push", "-q", "origin", "main")

    def _commit(self, folder: Path, file: str, subject: str) -> None:
        (folder / file).write_text("change\n")
        self._git(folder, "add", ".")
        self._git(folder, "commit", "-qm", f"{subject}\n\nAgent: dev")

    def _log(self, tip: str, since: str) -> list[str]:
        out = self._git(self.project, "log", "--reverse", "--format=%B%x1e", f"{since}..{tip}").stdout
        return [m.strip() for m in out.split("\x1e") if m.strip()]

    def _files_on(self, ref: str) -> set[str]:
        return set(self._git(self.project, "ls-tree", "--name-only", ref).stdout.split())

    def _rev(self, ref: str) -> str:
        return self._git(self.project, "rev-parse", ref).stdout.strip()

    def _id(self, task: Path) -> str:
        return task.name[:8]

    def _field(self, task: Path, name: str) -> str:
        line = next(l for l in task.read_text().splitlines() if l.startswith(f"{name}:"))
        return line.split(":", 1)[1].split("#")[0].strip()

    def _set_field(self, task: Path, name: str, value: str) -> None:
        text = task.read_text()
        task.write_text(re.sub(rf"^{name}:[^\n#]*", f"{name}: {value} ", text, count=1, flags=re.M))

    def _script(self, script: str, *args: str, agent: str = "dev") -> str:
        done = subprocess.run([sys.executable, str(self.kit / "team" / "tools" / script), *args],
                              capture_output=True, text=True, env={**os.environ, **WHO, "AGENT_ID": agent})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def _git(self, folder: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=check,
                              env={**os.environ, **WHO})


if __name__ == "__main__":
    unittest.main()
