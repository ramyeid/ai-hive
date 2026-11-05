"""The Coach's proposals (approve, edit, reject) and the history of the team's instructions (diffs, undo).

    uv run python -m unittest tests/test_improvements.py
"""
import asyncio
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from server import agents, store, team
from server.agents import AgentManager
from server.main import TOKEN, create_app
from tests.fake_claude import FakeClient
from tests.fake_openai import fake_openai_transport

import coach as kit_coach  # noqa: E402  (the kit's scripts, on the path via the server)

HEADERS = {"x-token": TOKEN}
RULE = "### Keep it simple\nKISS above all."


class ImprovementsTest(unittest.TestCase):

    def test_approving_a_proposal_changes_the_file_and_commits_it_on_its_own(self):
        client, kit = self._a_console_with_a_team()
        self._a_proposal(kit, "P-001", before="KISS above all.", after="KISS above all, always.")

        response = client.post("/api/improvements/P-001/approve", json={}, headers=HEADERS)

        self.assertEqual(response.json()["status"], "approved")
        self.assertIn("KISS above all, always.", (kit / "PREFERENCES.md").read_text())
        self.assertEqual(self._last_commit(kit), "Coach: Simpler code\n\nBecause.\n\nCoach-Proposal: P-001\nTasks: TASK-012\nApproved-by: lead")

    def test_the_lead_can_edit_the_new_text_before_approving(self):
        client, kit = self._a_console_with_a_team()
        self._a_proposal(kit, "P-001", before="KISS above all.", after="KISS above all, always.")

        client.post("/api/improvements/P-001/approve", json={"afters": ["KISS above all, in every project."]}, headers=HEADERS)

        self.assertIn("KISS above all, in every project.", (kit / "PREFERENCES.md").read_text())
        self.assertNotIn("always", (kit / "PREFERENCES.md").read_text())

    def test_rejecting_a_proposal_records_the_leads_note_and_changes_nothing(self):
        client, kit = self._a_console_with_a_team()
        self._a_proposal(kit, "P-001", before="KISS above all.", after="Something else.")

        response = client.post("/api/improvements/P-001/reject", json={"note": "Only for that service"}, headers=HEADERS)

        self.assertEqual((response.json()["status"], response.json()["note"]), ("rejected", "Only for that service"))
        self.assertIn("KISS above all.", (kit / "PREFERENCES.md").read_text())

    def test_a_proposal_is_not_applied_over_the_leads_uncommitted_edits(self):
        client, kit = self._a_console_with_a_team()
        self._a_proposal(kit, "P-001", before="KISS above all.", after="KISS above all, always.")
        self._the_lead_edits_without_committing(kit, "PREFERENCES.md")

        response = client.post("/api/improvements/P-001/approve", json={}, headers=HEADERS)

        self.assertEqual(response.status_code, 409)
        self.assertIn("changes that aren't committed yet", response.json()["detail"])

    def test_the_history_shows_an_approved_proposal_as_the_coachs_with_its_tasks(self):
        client, kit = self._a_console_with_a_team()
        self._an_approved_proposal(client, kit)

        history = client.get("/api/team/history", headers=HEADERS).json()["changes"]

        self.assertEqual((history[0]["by"], history[0]["proposal"], history[0]["tasks"]), ("Coach", "P-001", "TASK-012"))
        self.assertEqual(history[0]["files"], ["PREFERENCES.md"])

    def test_a_change_shows_its_diff(self):
        client, kit = self._a_console_with_a_team()
        sha = self._an_approved_proposal(client, kit)

        change = client.get(f"/api/team/history/{sha}", headers=HEADERS).json()

        self.assertIn("-KISS above all.", change["diffs"][0]["diff"])
        self.assertIn("+KISS above all, always.", change["diffs"][0]["diff"])

    def test_the_team_can_be_read_as_it_was_before_a_change(self):
        client, kit = self._a_console_with_a_team()
        before = self._head(kit)
        self._an_approved_proposal(client, kit)

        old = client.get(f"/api/team/at/{before}", params={"path": "PREFERENCES.md"}, headers=HEADERS).json()

        self.assertEqual(old["text"], RULE + "\n")

    def test_undoing_a_change_restores_the_file_with_a_new_commit(self):
        client, kit = self._a_console_with_a_team()
        sha = self._an_approved_proposal(client, kit)

        client.post(f"/api/team/undo/{sha}", json={}, headers=HEADERS)

        self.assertEqual((kit / "PREFERENCES.md").read_text(), RULE + "\n")
        self.assertTrue(self._last_commit(kit).startswith('Revert "Coach: Simpler code"'))

    def test_a_commit_that_also_changed_code_cannot_be_undone_from_the_console(self):
        client, kit = self._a_console_with_a_team()
        sha = self._a_commit_touching_a_script_and_the_team(kit)

        response = client.post(f"/api/team/undo/{sha}", json={}, headers=HEADERS)

        self.assertEqual(response.status_code, 409)

    def test_the_coach_is_refused_when_it_tries_to_edit_the_teams_files_directly(self):
        _, kit = self._a_console_with_a_team()
        coach = self._the_coach()

        allowed, message = asyncio.run(coach.ask("Edit", {"file_path": str(kit / "agents" / "dev.md")}))

        self.assertFalse(allowed)
        self.assertIn("Write a proposal", message)

    # ---- helpers ----------------------------------------------------------------------

    def _a_console_with_a_team(self) -> tuple[TestClient, Path]:
        kit = Path(tempfile.mkdtemp()) / "kit"
        (kit / "agents").mkdir(parents=True)
        (kit / "scripts").mkdir()
        (kit / "agents" / "dev.md").write_text("You are the dev.\n")
        (kit / "PREFERENCES.md").write_text(RULE + "\n")
        (kit / "scripts" / "claim.py").write_text("print('claim')\n")
        self.addCleanup(shutil.rmtree, kit.parent)
        for args in (("init", "-q", "-b", "main"), ("config", "user.email", "lead@example.com"),
                     ("config", "user.name", "Lead"), ("add", "."), ("commit", "-qm", "The team")):
            _git(kit, *args)
        for module, name, value in ((team, "KIT", kit), (agents, "KIT", kit),
                                    (kit_coach, "PROPOSALS", kit / "coach" / "proposals"),
                                    (store, "SETTINGS", kit / "settings.json")):
            self.addCleanup(setattr, module, name, getattr(module, name))
            setattr(module, name, value)
        self._manager = AgentManager(claude_client_factory=FakeClient, http_transport=fake_openai_transport([]))
        client = TestClient(create_app(self._manager), base_url="http://127.0.0.1:8420")
        client.__enter__()
        self.addCleanup(client.__exit__, None, None, None)
        return client, kit

    def _a_proposal(self, kit: Path, pid: str, before: str, after: str) -> None:
        folder = kit / "coach" / "proposals"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{pid}-simpler-code.md").write_text(
            f"---\nid: {pid}\ntitle: Simpler code\nstatus: pending\ntasks: TASK-012\ncreated: 2026-11-05\n"
            f"decided:\nnote:\ncommit:\n---\n\n## Why\nBecause.\n\n## Evidence\n- TASK-012: the lead said so.\n\n"
            f"## Change\n<<<<<<< PREFERENCES.md\n{before}\n=======\n{after}\n>>>>>>>\n")

    def _an_approved_proposal(self, client: TestClient, kit: Path) -> str:
        self._a_proposal(kit, "P-001", before="KISS above all.", after="KISS above all, always.")
        return client.post("/api/improvements/P-001/approve", json={}, headers=HEADERS).json()["commit"]

    def _the_lead_edits_without_committing(self, kit: Path, file: str) -> None:
        (kit / file).write_text((kit / file).read_text() + "A note of mine.\n")

    def _a_commit_touching_a_script_and_the_team(self, kit: Path) -> str:
        (kit / "scripts" / "claim.py").write_text("print('changed')\n")
        (kit / "agents" / "dev.md").write_text("You are the dev. Changed.\n")
        _git(kit, "commit", "-qam", "Code and team together")
        return self._head(kit)

    def _the_coach(self):
        return self._manager.agents["coach"]

    def _head(self, kit: Path) -> str:
        return _git(kit, "rev-parse", "--short", "HEAD").strip()

    def _last_commit(self, kit: Path) -> str:
        return _git(kit, "log", "-1", "--format=%B").strip()


def _git(folder: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True).stdout


if __name__ == "__main__":
    unittest.main()
