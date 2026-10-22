"""knowledge.py: the Tech Lead's memory of each repository, and how far it can be trusted.

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

    def test_status_says_there_is_no_knowledge_when_the_repo_has_no_folder(self):
        kit, project = self._a_kit(), self._a_project("shop")

        output = self._knowledge(kit, "status", project)

        self.assertIn("No knowledge of shop yet", output)

    def test_new_creates_the_repo_index_with_the_repo_name_and_path(self):
        kit, project = self._a_kit(), self._a_project("shop")

        self._knowledge(kit, "new", project)

        text = (kit / "knowledge" / "shop" / "index.md").read_text()
        self.assertIn("repo: shop", text)
        self.assertIn(f"path: {project}", text)
        self.assertIn("| (whole repo) |", text)

    def test_new_service_creates_its_file_with_its_scope_and_lists_it_in_the_index(self):
        kit, project = self._a_kit(), self._a_project("platform")

        self._knowledge(kit, "new", project, "--service", "orders", "--scope", "services/orders/,libs/order-models/")

        service = (kit / "knowledge" / "platform" / "orders.md").read_text()
        index = (kit / "knowledge" / "platform" / "index.md").read_text()
        self.assertIn("scope: services/orders/,libs/order-models/", service)
        self.assertIn("| orders | services/orders/,libs/order-models/ | | orders.md |", index)
        self.assertNotIn("| (whole repo) |", index)

    def test_new_service_without_a_scope_is_refused(self):
        kit, project = self._a_kit(), self._a_project("platform")

        done = self._knowledge_run(kit, "new", project, "--service", "orders")

        self.assertNotEqual(done.returncode, 0)
        self.assertIn("needs --scope", done.stderr)

    def test_stamp_records_the_commit_the_branch_and_the_agent_on_the_service_file(self):
        kit, project = self._a_kit(), self._a_project("platform")
        self._a_service(kit, project, "orders", "services/orders/")

        self._knowledge(kit, "stamp", project, "--service", "orders", agent="techlead-2")

        front = self._front_matter(kit / "knowledge" / "platform" / "orders.md")
        self.assertEqual(front["commit"], self._head(project))
        self.assertEqual(front["branch"], "main")
        self.assertEqual(front["updated_by"], "techlead-2")

    def test_a_change_in_another_service_does_not_make_a_service_stale(self):
        kit, project = self._a_kit(), self._a_project("platform")
        self._a_stamped_service(kit, project, "orders", "services/orders/")
        self._a_commit_changing(project, "services/payments/charge.py")

        output = self._knowledge(kit, "status", project, "--service", "orders")

        self.assertIn("Up to date", output)

    def test_a_change_inside_its_scope_lists_the_file_and_the_sections_that_mention_it(self):
        kit, project = self._a_kit(), self._a_project("platform")
        self._a_stamped_service(kit, project, "orders", "services/orders/", code_map="`services/orders/` → the orders API.")
        self._a_commit_changing(project, "services/orders/api.py")

        output = self._knowledge(kit, "status", project, "--service", "orders")

        self.assertIn("1 file(s) changed since", output)
        self.assertIn("services/orders/api.py", output)
        self.assertIn("Re-check these sections: Code map", output)

    def test_the_overview_shows_every_file_of_the_repo_with_its_own_freshness(self):
        kit, project = self._a_kit(), self._a_project("platform")
        self._a_stamped_service(kit, project, "orders", "services/orders/")
        self._a_stamped_service(kit, project, "payments", "services/payments/")
        self._a_commit_changing(project, "services/payments/charge.py")

        output = self._knowledge(kit, "status", project)

        self.assertRegex(output, r"orders\.md\s+services/orders/\s+up to date")
        self.assertRegex(output, r"payments\.md\s+services/payments/\s+1 file\(s\) changed")

    def test_status_marks_a_file_unverified_when_its_commit_is_no_longer_in_the_repo(self):
        kit, project = self._a_kit(), self._a_project("shop")
        self._an_index_stamped_at_commit(kit, project, "0123abc")

        output = self._knowledge(kit, "status", project, "--service", "index")

        self.assertIn("no longer in the repo", output)

    def test_migrate_moves_a_one_file_knowledge_into_the_repo_folder_as_its_index(self):
        kit = self._a_kit()
        self._an_old_flat_knowledge_file(kit, "shop")

        self._run_script(kit, "migrate.py")

        index = (kit / "knowledge" / "shop" / "index.md").read_text()
        self.assertIn("repo: shop\npath: /code/shop\nscope:", index)
        self.assertFalse((kit / "knowledge" / "shop.md").exists())

    def test_migrate_moves_old_conventions_notes_into_the_repo_index(self):
        kit = self._a_kit()
        self._old_conventions_notes(kit, "shop", "## Commands\n| Tests | pytest -q |\n")

        self._run_script(kit, "migrate.py")

        index = (kit / "knowledge" / "shop" / "index.md").read_text()
        self.assertIn("### Commands\n| Tests | pytest -q |", index)
        self.assertFalse((kit / "tasks" / "conventions" / "shop.md").exists())

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

    def _a_service(self, kit: Path, project: Path, name: str, scope: str, code_map: str = "") -> Path:
        path = Path(self._knowledge(kit, "new", project, "--service", name, "--scope", scope))
        if code_map:
            path.write_text(path.read_text().replace("## Code map\n", f"## Code map\n{code_map}\n", 1))
        return path

    def _a_stamped_service(self, kit: Path, project: Path, name: str, scope: str, code_map: str = "") -> None:
        self._a_service(kit, project, name, scope, code_map)
        self._knowledge(kit, "stamp", project, "--service", name)

    def _an_index_stamped_at_commit(self, kit: Path, project: Path, commit: str) -> None:
        path = Path(self._knowledge(kit, "new", project))
        path.write_text(path.read_text().replace("commit:  ", f"commit: {commit}  ", 1))

    def _an_old_flat_knowledge_file(self, kit: Path, repo: str) -> None:
        (kit / "knowledge").mkdir()
        (kit / "knowledge" / f"{repo}.md").write_text(f"---\nservice: {repo}\npath: /code/{repo}\ncommit:\n---\n\n## Purpose\nShop.\n")

    def _old_conventions_notes(self, kit: Path, repo: str, body: str) -> None:
        folder = kit / "tasks" / "conventions"
        folder.mkdir(parents=True)
        (folder / f"{repo}.md").write_text(f"# Conventions: {repo}\n\n{body}")

    def _front_matter(self, path: Path) -> dict:
        lines = path.read_text().split("---")[1].strip().splitlines()
        return {k.strip(): v.split("#")[0].strip() for k, v in (line.split(":", 1) for line in lines if ":" in line)}

    def _head(self, project: Path) -> str:
        return self._git(project, "rev-parse", "--short", "HEAD").stdout.strip()

    def _knowledge(self, kit: Path, command: str, project: Path, *args: str, agent: str = "techlead") -> str:
        done = self._knowledge_run(kit, command, project, *args, agent=agent)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def _knowledge_run(self, kit: Path, command: str, project: Path, *args: str, agent: str = "techlead") -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(kit / "scripts" / "knowledge.py"), command, str(project), *args],
                              capture_output=True, text=True, env={**os.environ, "AGENT_ID": agent})

    def _run_script(self, kit: Path, script: str) -> None:
        done = subprocess.run([sys.executable, str(kit / "scripts" / script)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)

    def _git(self, project: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, check=True)


if __name__ == "__main__":
    unittest.main()
