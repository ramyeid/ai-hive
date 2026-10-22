"""knowledge.py: the Tech Lead's memory of each service, and how far it can be trusted.

    python3 -m unittest tests/test_knowledge.py      (from the kit folder; works on temporary copies)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


class KnowledgeTest(unittest.TestCase):

    def test_status_says_there_is_no_knowledge_when_the_service_has_no_file(self):
        kit, project = self._a_kit(), self._a_project("orders")

        output = self._run(kit, "status", project)

        self.assertIn("No knowledge of orders yet", output)

    def test_new_creates_the_file_from_the_template_with_the_service_name_and_path(self):
        kit, project = self._a_kit(), self._a_project("orders")

        self._run(kit, "new", project)

        text = (kit / "knowledge" / "orders.md").read_text()
        self.assertIn("service: orders", text)
        self.assertIn(f"path: {project}", text)
        self.assertIn("## APIs", text)

    def test_stamp_records_the_commit_the_branch_and_the_agent(self):
        kit, project = self._a_kit(), self._a_project("orders")

        self._run(kit, "stamp", project, agent="techlead-2")

        front = self._front_matter(kit / "knowledge" / "orders.md")
        self.assertEqual(front["commit"], self._head(project))
        self.assertEqual(front["branch"], "main")
        self.assertEqual(front["updated_by"], "techlead-2")

    def test_status_says_up_to_date_when_nothing_changed_since_the_stamp(self):
        kit, project = self._a_kit(), self._a_project("orders")
        self._run(kit, "stamp", project)

        output = self._run(kit, "status", project)

        self.assertIn("Up to date", output)

    def test_status_lists_the_changed_files_and_the_sections_that_mention_them(self):
        kit, project = self._a_kit(), self._a_project("orders")
        self._knowledge_whose_code_map_mentions(kit, project, "src/orders/")
        self._run(kit, "stamp", project)
        self._a_commit_changing(project, "src/orders/service.py")

        output = self._run(kit, "status", project)

        self.assertIn("1 file(s) changed", output)
        self.assertIn("src/orders/service.py", output)
        self.assertIn("Re-check these sections: Code map", output)

    def test_status_marks_the_file_unverified_when_its_commit_is_no_longer_in_the_repo(self):
        kit, project = self._a_kit(), self._a_project("orders")
        self._knowledge_stamped_at_commit(kit, project, "0123abc")

        output = self._run(kit, "status", project)

        self.assertIn("no longer in the repo", output)

    def test_migrate_moves_old_conventions_notes_into_the_conventions_section(self):
        kit = self._a_kit()
        self._old_conventions_notes(kit, "orders", "## Commands\n| Tests | pytest -q |\n")

        self._run_script(kit, "migrate.py")

        text = (kit / "knowledge" / "orders.md").read_text()
        self.assertIn("### Commands\n| Tests | pytest -q |", text)
        self.assertFalse((kit / "tasks" / "conventions" / "orders.md").exists())

    # ---- helpers ----------------------------------------------------------------------

    def _a_kit(self) -> Path:
        kit = Path(tempfile.mkdtemp()) / "kit"
        shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("tasks", "knowledge", "console", ".git", "__pycache__"))
        self.addCleanup(shutil.rmtree, kit.parent)
        return kit

    def _a_project(self, name: str) -> Path:
        project = Path(tempfile.mkdtemp()) / name
        project.mkdir()
        self._git(project, "init", "-q", "-b", "main")
        self._a_commit_changing(project, "README.md")
        self.addCleanup(shutil.rmtree, project.parent)
        return project

    def _a_commit_changing(self, project: Path, file: str) -> None:
        path = project / file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{path.read_text() if path.exists() else ''}change\n")
        self._git(project, "add", ".")
        self._git(project, "-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", f"change {file}")

    def _knowledge_whose_code_map_mentions(self, kit: Path, project: Path, folder: str) -> None:
        path = Path(self._run(kit, "new", project))
        path.write_text(path.read_text().replace("## Code map\n", f"## Code map\n`{folder}` → the orders API.\n", 1))

    def _knowledge_stamped_at_commit(self, kit: Path, project: Path, commit: str) -> None:
        path = Path(self._run(kit, "new", project))
        path.write_text(path.read_text().replace("commit:  ", f"commit: {commit}  ", 1))

    def _old_conventions_notes(self, kit: Path, service: str, body: str) -> None:
        folder = kit / "tasks" / "conventions"
        folder.mkdir(parents=True)
        (folder / f"{service}.md").write_text(f"# Conventions: {service}\n\n{body}")

    def _front_matter(self, path: Path) -> dict:
        lines = path.read_text().split("---")[1].strip().splitlines()
        return {k.strip(): v.split("#")[0].strip() for k, v in (line.split(":", 1) for line in lines)}

    def _head(self, project: Path) -> str:
        return self._git(project, "rev-parse", "--short", "HEAD").stdout.strip()

    def _run(self, kit: Path, command: str, project: Path, agent: str = "techlead") -> str:
        return self._run_script(kit, "knowledge.py", command, str(project), agent=agent)

    def _run_script(self, kit: Path, script: str, *args: str, agent: str = "techlead") -> str:
        done = subprocess.run([sys.executable, str(kit / "scripts" / script), *args],
                              capture_output=True, text=True, env={**os.environ, "AGENT_ID": agent})
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def _git(self, project: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
