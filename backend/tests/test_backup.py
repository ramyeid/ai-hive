"""Backups: one archive with everything Hive needs, sent to a folder (or S3), the oldest dropped; and
scripts/restore.sh puts it all back on a machine that has nothing.

    uv run python -m unittest tests/test_backup.py
"""
import datetime as dt
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path

from hive import backup

KIT = Path(__file__).resolve().parents[2]
WHO = {"GIT_AUTHOR_NAME": "Lead", "GIT_AUTHOR_EMAIL": "lead@example.com",
       "GIT_COMMITTER_NAME": "Lead", "GIT_COMMITTER_EMAIL": "lead@example.com"}


class BackupTest(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.data, self.home = self.root / "kit" / "data", self.root / "home"
        (self.data / "tasks").mkdir(parents=True)
        (self.data / "tasks" / "TASK-001-x.md").write_text("---\nid: TASK-001\n---\n")
        (self.data / "console").mkdir()
        (self.data / "console" / "settings.json").write_text('{"providers": {"openai": {"api_key": "sk-secret"}}}')
        (self.data / "editor" / "extensions" / "ms-python").mkdir(parents=True)
        (self.data / "editor" / "extensions" / "ms-python" / "big.vsix").write_text("x" * 1000)
        (self.data / "hive.pid").write_text("123")
        (self.home / ".claude" / "projects" / "-shop").mkdir(parents=True)
        (self.home / ".claude" / "projects" / "-shop" / "abc.jsonl").write_text('{"type": "user"}\n')
        (self.home / ".claude" / ".credentials.json").write_text('{"token": "t"}')
        self.github, self.project = self._a_project_on_github()
        self.patch(backup, "DATA", self.data)
        self.patch(backup, "FOLDER", self.data / "backup")
        self.patch(backup, "CONFIG", self.data / "backup" / "config.json")
        self.patch(backup, "LOG", self.data / "backup" / "log.json")
        self.patch(backup, "CLAUDE_FILES", [self.home / ".claude" / "projects", self.home / ".claude" / ".credentials.json"])
        self.patch(backup, "_projects", lambda: [str(self.project)])
        self.patch(backup, "HOME", self.home)
        for k, v in WHO.items():
            self.patch(os.environ, k, v, item=True)

    def test_a_backup_has_the_data_the_branches_only_this_machine_has_and_claude_codes_conversations(self):
        names, manifest = self._contents(backup.make(self.root))

        self.assertIn("data/tasks/TASK-001-x.md", names)
        self.assertIn("data/console/settings.json", names)   # with its keys: everything, as the lead chose
        self.assertIn("claude/.claude/projects/-shop/abc.jsonl", names)
        self.assertIn("claude/.claude/.credentials.json", names)
        self.assertEqual(manifest["projects"][0]["refs"], ["refs/heads/feature-filter"])
        self.assertEqual(manifest["projects"][0]["worktrees"][0]["branch"], "feature-filter")
        self.assertIn(manifest["projects"][0]["bundle"], names)

    def test_caches_and_running_state_are_left_out(self):
        names, _ = self._contents(backup.make(self.root))

        self.assertNotIn("data/editor/extensions/ms-python/big.vsix", names)
        self.assertNotIn("data/hive.pid", names)

    def test_a_project_with_everything_on_github_has_no_bundle(self):
        self._git(self.worktree, "push", "-q", "origin", "feature-filter")

        _, manifest = self._contents(backup.make(self.root))

        self.assertEqual(manifest["projects"][0]["bundle"], "")

    def test_backups_go_to_the_folder_and_only_the_last_ones_are_kept(self):
        out = self.root / "backups"
        backup.save_config({"destination": str(out), "keep": 2})
        for n in range(3):
            (out / f"hive-backup-2026010{n + 1}-030000.tar.gz").parent.mkdir(exist_ok=True)
            (out / f"hive-backup-2026010{n + 1}-030000.tar.gz").write_text("old")

        entry = backup.run()

        self.assertTrue(entry["ok"])
        self.assertEqual(sorted(p.name for p in out.iterdir()), ["hive-backup-20260103-030000.tar.gz", entry["name"]])
        self.assertEqual(backup.history()[0]["name"], entry["name"])

    def test_a_failed_backup_is_in_the_history_with_its_reason(self):
        blocked = self.root / "file"
        blocked.write_text("not a folder")
        backup.save_config({"destination": str(blocked)})

        with self.assertRaises(backup.BackupError):
            backup.run()

        self.assertFalse(backup.history()[0]["ok"])
        self.assertTrue(backup.history()[0]["error"])

    def test_the_destination_must_be_s3_or_a_full_path(self):
        with self.assertRaises(backup.BackupError):
            backup.save_config({"destination": "backups"})

        self.assertEqual(backup.save_config({"destination": "s3://my-bucket/hive/"})["destination"], "s3://my-bucket/hive")

    def test_the_nightly_backup_is_due_once_its_hour_has_come_and_not_again_that_day(self):
        backup.save_config({"destination": str(self.root / "b"), "schedule": "daily", "hour": 3})
        at = lambda h, m=0, day=8: dt.datetime(2026, 11, day, h, m)
        self._turned_on_at(at(1))

        self.assertFalse(backup.due(at(2, 59)))
        self.assertTrue(due := backup.due(at(3, 1)))
        backup._remember({"at": at(3, 1).isoformat(), "trigger": "scheduled", "ok": True})
        self.assertFalse(backup.due(at(15)))
        self.assertFalse(backup.due(at(2, 59, day=9)))
        self.assertTrue(backup.due(at(3, 0, day=9)))
        self.assertTrue(due)

    def test_turning_the_nightly_backup_on_waits_for_its_hour_and_a_missed_night_is_made_up(self):
        backup.save_config({"destination": str(self.root / "b"), "schedule": "daily", "hour": 3})
        self._turned_on_at(dt.datetime(2026, 11, 8, 20, 0))

        self.assertFalse(backup.due(dt.datetime(2026, 11, 8, 20, 1)))   # not right away
        self.assertTrue(backup.due(dt.datetime(2026, 11, 10, 9, 0)))    # the machine was off at 3:00: at start-up

    def test_restore_puts_everything_back_on_a_machine_that_has_nothing(self):
        archive = backup.make(self.root)
        branch_head = self._git(self.project, "rev-parse", "feature-filter").stdout.strip()
        kit = self._a_fresh_kit()
        shutil.rmtree(self.project.parent / f"{self.project.name}.worktrees")
        shutil.rmtree(self.project)                     # the machine lost everything
        fresh_home = self.root / "newhome"
        fresh_home.mkdir()

        done = subprocess.run(["bash", str(kit / "scripts" / "restore.sh"), str(archive)], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(fresh_home)})

        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        self.assertEqual((kit / "data" / "tasks" / "TASK-001-x.md").read_text(), "---\nid: TASK-001\n---\n")
        self.assertEqual(self._git(self.project, "rev-parse", "feature-filter").stdout.strip(), branch_head)
        self.assertTrue(self.worktree.is_dir())
        self.assertTrue((fresh_home / ".claude" / "projects" / "-shop" / "abc.jsonl").exists())
        self.assertTrue((fresh_home / ".claude" / ".credentials.json").exists())
        self.assertTrue((fresh_home / ".claude" / "agents").is_dir())   # install.sh ran

    def test_restore_keeps_the_data_that_was_there_and_never_rewinds_a_newer_branch(self):
        archive = backup.make(self.root)
        kit = self._a_fresh_kit()
        (kit / "data").mkdir()
        (kit / "data" / "note.txt").write_text("mine")
        (self.worktree / "more.txt").write_text("newer work")
        self._git(self.worktree, "add", ".")
        self._git(self.worktree, "commit", "-qm", "newer")
        newer = self._git(self.project, "rev-parse", "feature-filter").stdout.strip()

        done = subprocess.run(["bash", str(kit / "scripts" / "restore.sh"), str(archive)], capture_output=True, text=True,
                              env={**os.environ, "HOME": str(self.home)})

        self.assertEqual(done.returncode, 0, done.stderr + done.stdout)
        kept = [p for p in kit.iterdir() if p.name.startswith("data.before-restore-")]
        self.assertEqual((kept[0] / "note.txt").read_text(), "mine")
        self.assertEqual(self._git(self.project, "rev-parse", "feature-filter").stdout.strip(), newer)

    # ---- helpers ----------------------------------------------------------------------

    def _turned_on_at(self, when: dt.datetime) -> None:
        saved = json.loads(backup.CONFIG.read_text())
        backup.CONFIG.write_text(json.dumps({**saved, "since": when.isoformat()}))

    def _a_project_on_github(self) -> tuple[Path, Path]:
        project = self.root / "work" / "shop"
        project.mkdir(parents=True)
        self._git(project, "init", "-q", "-b", "main")
        (project / "README.md").write_text("shop\n")
        self._git(project, "add", ".")
        self._git(project, "commit", "-qm", "start")
        github = self.root / "github.git"
        self._git(self.root, "clone", "-q", "--bare", str(project), str(github))
        self._git(project, "remote", "add", "origin", str(github))
        self._git(project, "fetch", "-q", "origin")
        self.worktree = self.root / "work" / "shop.worktrees" / "feature-filter"
        self._git(project, "worktree", "add", "-q", "-b", "feature-filter", str(self.worktree))
        (self.worktree / "filter.py").write_text("def f(): ...\n")
        self._git(self.worktree, "add", ".")
        self._git(self.worktree, "commit", "-qm", "add the filter")   # only on this machine
        return github, project

    def _a_fresh_kit(self) -> Path:
        kit = self.root / "newkit"
        shutil.copytree(KIT / "scripts", kit / "scripts")
        shutil.copytree(KIT / "team", kit / "team", ignore=shutil.ignore_patterns("__pycache__"))
        return kit

    def _contents(self, archive: Path) -> tuple[set, dict]:
        with tarfile.open(archive) as tar:
            names = set(tar.getnames())
            manifest = json.load(tar.extractfile("manifest.json"))
        return names, manifest

    def patch(self, owner, name, value, item=False):
        if item:
            old = owner.get(name)
            owner[name] = value
            self.addCleanup(lambda: owner.__setitem__(name, old) if old is not None else owner.pop(name, None))
        else:
            old = getattr(owner, name)
            setattr(owner, name, value)
            self.addCleanup(setattr, owner, name, old)

    def _git(self, folder: Path, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, check=True,
                              env={**os.environ, **WHO})


if __name__ == "__main__":
    unittest.main()
