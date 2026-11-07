"""coach.py: the evidence the Coach reviews, and the proposals it writes.

    python3 -m unittest discover team/tests      (from the Hive folder; works on temporary copies)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]   # the Hive folder


class EvidenceTest(unittest.TestCase):

    def test_the_evidence_quotes_what_the_lead_said_to_the_agents(self):
        kit = self._a_kit()
        self._a_task(kit, "TASK-001")
        self._a_saved_conversation(kit, "TASK-001", "dev", "No, errors are always { code, message }.")

        evidence = self._evidence(kit, "--since", "all")

        self.assertIn("No, errors are always { code, message }.", evidence)
        self.assertIn("to dev]", evidence)

    def test_the_evidence_counts_review_rounds_and_includes_the_review_report(self):
        kit = self._a_kit()
        self._a_task(kit, "TASK-001", review="Should-fix: the error shape doesn't match `OrdersController`.")
        self._activity(kit, "TASK-001", ["changes-requested", "changes-requested", "done"])

        evidence = self._evidence(kit, "--since", "all")

        self.assertIn("Review rounds sent back: 2.", evidence)
        self.assertIn("the error shape doesn't match", evidence)

    def test_the_leads_commits_on_the_branch_are_shown_and_the_agents_are_not(self):
        kit, project = self._a_kit(), self._a_project()
        self._a_task(kit, "TASK-001", project=project, branch="feature-x")
        self._a_commit(project, "feature-x", "agent.py", "TASK-001: add filter", agent="dev")
        self._a_commit(project, "feature-x", "lead.py", "rename to fetch_orders")

        evidence = self._evidence(kit, "--since", "all")

        self.assertIn("rename to fetch_orders", evidence)
        self.assertIn("+++ b/lead.py", evidence)
        self.assertNotIn("TASK-001: add filter", evidence)

    def test_the_pull_request_gives_the_leads_commits_and_review_comments(self):
        kit, project = self._a_kit(), self._a_project()
        self._a_task(kit, "TASK-001", project=project, branch="feature-x")
        lead_sha = self._a_commit(project, "feature-x", "lead.py", "use cursor pagination")
        fake_gh = self._a_github_pull_request(lead_sha, comment="We always paginate with cursors here.")

        evidence = self._evidence(kit, "--since", "all", path=fake_gh)

        self.assertIn("Pull request #7 (merged, merged 2026-11-01)", evidence)
        self.assertIn("use cursor pagination", evidence)
        self.assertIn("Review comment on `api.py:12`: We always paginate with cursors here.", evidence)

    def test_the_evidence_shows_the_leads_code_review_with_the_code_and_the_devs_reply(self):
        kit = self._a_kit()
        self._a_task(kit, "TASK-001")
        self._a_lead_review(kit, "TASK-001", comment="Errors are always { code, message }.", code='return {"error": msg}',
                            reply="Fixed in abc1234: returns { code, message }.")
        self._activity(kit, "TASK-001", ["done"], at="2026-11-01T10:00:00")

        evidence = self._evidence(kit, "--since", "all")

        self.assertIn("round 1 (changes requested) at `abc1234`, after the reviewer had marked it done", evidence)
        self.assertIn('1. `api.py:12`: "Errors are always { code, message }."', evidence)
        self.assertIn('return {"error": msg}', evidence)
        self.assertIn("Dev's reply: Fixed in abc1234: returns { code, message }.", evidence)

    def test_since_the_last_review_only_takes_tasks_with_activity_after_it(self):
        kit = self._a_kit()
        self._a_task(kit, "TASK-001")
        self._a_task(kit, "TASK-002")
        self._activity(kit, "TASK-001", ["done"], at="2026-10-01T10:00:00")
        self._activity(kit, "TASK-002", ["done"], at="2026-11-03T10:00:00")
        self._last_review_at(kit, "2026-11-01T00:00:00")

        evidence = self._evidence(kit)

        self.assertIn("Tasks: TASK-002.", evidence)

    def test_the_evidence_lists_rejected_proposals_with_the_leads_note(self):
        kit = self._a_kit()
        self._a_proposal(kit, "P-001", status="rejected", note="Only in that one service")

        evidence = self._evidence(kit, "--since", "all")

        self.assertIn("P-001 Use cursors (Only in that one service)", evidence)

    # ---- helpers ----

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT / "team", kit / "team", ignore=shutil.ignore_patterns("__pycache__"))
        (kit / "data" / "tasks" / ".inbox").mkdir(parents=True)
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit

    def _a_project(self) -> Path:
        project = Path(tempfile.mkdtemp()) / "shop"
        project.mkdir()
        self.addCleanup(shutil.rmtree, project.parent)
        _git(project, "init", "-q", "-b", "main")
        (project / "README.md").write_text("shop\n")
        _git(project, "add", ".")
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")
        return project

    def _a_task(self, kit: Path, task_id: str, review: str = "", project: Path | None = None, branch: str = "") -> None:
        text = (f"---\nid: {task_id}\ntitle: Filter orders\nstatus: done\nproject: {project or '/nowhere'}\n"
                f"base: main\nbranch: {branch}\ntechlead: techlead\ndev: dev\nreviewer: reviewer\n---\n\n"
                f"## Clarifications\n| # | Question | Lead's answer |\n|---|---|---|\n\n## Dev Log\n\n## Review Report\n{review}\n")
        (kit / "data" / "tasks" / f"{task_id}-filter.md").write_text(text)

    def _a_saved_conversation(self, kit: Path, task_id: str, agent: str, said: str) -> None:
        folder = kit / "data" / "tasks" / "chats" / task_id
        folder.mkdir(parents=True)
        events = [{"ts": "2026-11-02T10:00:00", "kind": "user", "text": said}]
        (folder / f"20261102-100000-{agent}-abc.json").write_text(json.dumps({"agent": agent, "events": events}))

    def _activity(self, kit: Path, task_id: str, statuses: list[str], at: str = "2026-11-02T10:00:00") -> None:
        with (kit / "data" / "tasks" / ".inbox" / "activity.jsonl").open("a") as f:
            for status in statuses:
                f.write(json.dumps({"ts": at, "id": task_id, "to": status}) + "\n")

    def _last_review_at(self, kit: Path, at: str) -> None:
        (kit / "data" / "coach").mkdir(exist_ok=True)
        (kit / "data" / "coach" / "state.json").write_text(json.dumps({"last_review": at}))

    def _a_lead_review(self, kit: Path, task_id: str, comment: str, code: str, reply: str) -> None:
        comments = [{"id": "c1", "file": "api.py", "line": 12, "side": "new", "code": code, "body": comment}]
        rounds = [{"n": 1, "at": "2026-11-02T10:00:00", "verdict": "changes", "commit": "abc1234" + "0" * 33,
                   "describes": "the whole feature", "summary": "", "comments": comments}]
        (kit / "data" / "tasks" / "reviews").mkdir(parents=True)
        (kit / "data" / "tasks" / "reviews" / f"{task_id}.json").write_text(json.dumps({"rounds": rounds, "pending": [], "next": 2}))
        task = next((kit / "data" / "tasks").glob(f"{task_id}-*.md"))
        task.write_text(task.read_text() + f"\n## Lead Review\n\n### Round 1 — x\n\n1. `api.py:12`\n   {comment}\n   - Reply: {reply}\n")

    def _a_proposal(self, kit: Path, pid: str, status: str, note: str) -> None:
        folder = kit / "data" / "coach" / "proposals"
        folder.mkdir(parents=True)
        (folder / f"{pid}-use-cursors.md").write_text(f"---\nid: {pid}\ntitle: Use cursors\nstatus: {status}\nnote: {note}\n---\n")

    def _a_commit(self, project: Path, branch: str, file: str, message: str, agent: str = "") -> str:
        if _git(project, "branch", "--list", branch).strip():
            _git(project, "checkout", "-q", branch)
        else:
            _git(project, "checkout", "-q", "-b", branch)
        (project / file).write_text(f"{file}\n")
        _git(project, "add", ".")
        trailers = ["--trailer", f"Agent: {agent}"] if agent else []
        _git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", message, *trailers)
        sha = _git(project, "rev-parse", "HEAD").strip()
        _git(project, "checkout", "-q", "main")
        return sha

    def _a_github_pull_request(self, lead_sha: str, comment: str) -> Path:
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        answers = {
            "pr list": [{"number": 7, "title": "x", "url": "https://github.com/o/r/pull/7", "state": "MERGED", "mergedAt": "2026-11-01T09:00:00Z"}],
            "pr view": {"commits": [{"oid": lead_sha, "messageHeadline": "use cursor pagination", "messageBody": ""},
                                    {"oid": "f" * 40, "messageHeadline": "TASK-001: add", "messageBody": "Agent: dev"}],
                        "reviews": [], "comments": []},
            "api": [{"path": "api.py", "line": 12, "body": comment}],
        }
        script = folder / "gh"
        script.write_text(textwrap.dedent(f"""\
            #!{sys.executable}
            import json, sys
            answers = {json.dumps(answers)!r}
            answers = json.loads(answers)
            args = sys.argv[1:]
            key = "api" if args[0] == "api" else " ".join(args[:2])
            print(json.dumps(answers[key]))
            """))
        script.chmod(0o755)
        return folder

    def _no_pull_requests(self) -> Path:
        """A stand-in `gh` that finds nothing, so the evidence falls back to the local branch."""
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder)
        (folder / "gh").write_text("#!/bin/sh\nexit 1\n")
        (folder / "gh").chmod(0o755)
        return folder

    def _evidence(self, kit: Path, *args: str, path: Path | None = None) -> str:
        env = {**os.environ, "PATH": f"{path or self._no_pull_requests()}{os.pathsep}{os.environ['PATH']}"}
        done = subprocess.run([sys.executable, str(kit / "team" / "tools" / "coach.py"), "evidence", *args],
                              capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 0, done.stderr)
        return Path(done.stdout.splitlines()[0]).read_text()


class ProposalTest(unittest.TestCase):

    def test_propose_creates_the_next_numbered_proposal_from_the_template(self):
        kit = self._a_kit()

        path = self._coach(kit, "propose", "Errors are code and message")

        self.assertTrue(Path(path).name.startswith("P-001-errors-are-code-and-message"))
        self.assertIn("title: Errors are code and message", Path(path).read_text())

    def test_a_proposal_whose_before_text_is_in_the_file_once_passes_the_check(self):
        kit = self._a_kit()
        self._a_written_proposal(kit, file="PREFERENCES.md", before="### Keep it simple", after="### Keep it simple, always")

        output = self._coach(kit, "check", "P-001")

        self.assertIn("P-001 is ready for the lead.", output)

    def test_a_proposal_whose_before_text_is_not_in_the_file_fails_the_check(self):
        kit = self._a_kit()
        self._a_written_proposal(kit, file="PREFERENCES.md", before="text that isn't there", after="new")

        done = self._coach_run(kit, "check", "P-001")

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("BEFORE appears 0 times", done.stderr)

    def test_a_proposal_to_change_a_script_is_refused(self):
        kit = self._a_kit()
        self._a_written_proposal(kit, file="tools/claim.py", before="", after="print('hi')")

        done = self._coach_run(kit, "check", "P-001")

        self.assertIn("proposals can only change agents/*.md, TEAM.md, PREFERENCES.md or templates/*.md", done.stderr)

    def test_done_records_the_review_so_the_next_one_starts_from_it(self):
        kit = self._a_kit()

        self._coach(kit, "done")

        self.assertIn("last_review", json.loads((kit / "data" / "coach" / "state.json").read_text()))

    # ---- helpers ----

    def _a_kit(self) -> Path:
        return EvidenceTest._a_kit(self)

    def _a_written_proposal(self, kit: Path, file: str, before: str, after: str) -> None:
        path = Path(self._coach(kit, "propose", "A change"))
        text = path.read_text().replace("tasks:  ", "tasks: TASK-001  ", 1)
        text = text.replace("## Evidence\n", "## Evidence\n- TASK-001: the lead said so.\n", 1)
        text = text.replace("## Why\n", "## Why\nBecause.\n", 1)
        path.write_text(text + f"\n<<<<<<< {file}\n{before}\n=======\n{after}\n>>>>>>>\n")

    def _coach(self, kit: Path, *args: str) -> str:
        done = self._coach_run(kit, *args)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def _coach_run(self, kit: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(kit / "team" / "tools" / "coach.py"), *args], capture_output=True, text=True)


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    unittest.main()
