"""Backups: everything Hive needs to start again as if nothing happened, as one archive, to S3 or a folder.

What's in a backup (hive-backup-<date>-<time>.tar.gz):
- data/: the board, reviews, knowledge, the Coach's work, the console's settings (with its API keys and Slack
  tokens), Hive's own transcripts. Not VS Code's caches and extensions (they download again).
- bundles/: for each project, the branches that exist only on this machine (not on GitHub, or ahead of it), and
  the history kept when you cleaned a branch up to land it, as git bundles.
- claude/: Claude Code's conversations (so agents can resume them) and its sign-in.
- manifest.json: the projects (folder, GitHub address), their worktrees, the Hive version.

Where: an S3 address (s3://bucket/folder, with the machine's own AWS access: the `aws` command and an instance
role) or a folder on this machine. Nightly at the hour you choose; the last N are kept.

Restore with scripts/restore.sh <backup>, with Hive stopped (see docs/INSTALL.md).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import threading
from pathlib import Path

from . import store

KIT = store.KIT
DATA = KIT / "data"
FOLDER = DATA / "backup"            # this feature's own settings and log (backed up too)
CONFIG = FOLDER / "config.json"
LOG = FOLDER / "log.json"
HOME = Path.home()
CLAUDE_FILES = [HOME / ".claude" / "projects", HOME / ".claude" / ".credentials.json", HOME / ".claude.json"]
SKIP = re.compile(r"^(editor/(extensions|user/(logs|CachedData|CachedExtensionVSIXs|CachedProfilesData))(/|$)"
                  r"|hive\.pid$|.*\.sock$|backup/log\.json\.tmp$)")
NAME = re.compile(r"^hive-backup-\d{8}-\d{6}\.tar\.gz$")
DEFAULTS = {"destination": "", "schedule": "off", "hour": 3, "keep": 14}

log = logging.getLogger("hive.backup")
_running = threading.Lock()


class BackupError(Exception):
    """Something the lead needs to know (shown as is)."""


# ---- settings and history ---------------------------------------------------------------

def config() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except (FileNotFoundError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save_config(changes: dict) -> dict:
    current = config()
    if "destination" in changes:
        where = changes["destination"].strip().rstrip("/")
        if where and not (re.match(r"^s3://[a-z0-9][a-z0-9.\-]{1,61}[a-z0-9](/\S*)?$", where) or where.startswith(("/", "~"))):
            raise BackupError("Enter an S3 address (s3://bucket/folder) or a folder's full path (/backups/hive).")
        if where.startswith("~"):
            where = str(Path(where).expanduser())
        current["destination"] = where
    if "schedule" in changes:
        if changes["schedule"] not in ("off", "daily"):
            raise BackupError("The schedule is off or daily.")
        if changes["schedule"] == "daily" and current["schedule"] != "daily":
            current["since"] = dt.datetime.now().isoformat(timespec="seconds")   # the first one at the next hour
        current["schedule"] = changes["schedule"]
    if "hour" in changes:
        if not 0 <= int(changes["hour"]) <= 23:
            raise BackupError("The hour is 0 to 23.")
        current["hour"] = int(changes["hour"])
    if "keep" in changes:
        if not 1 <= int(changes["keep"]) <= 365:
            raise BackupError("Keep between 1 and 365 backups.")
        current["keep"] = int(changes["keep"])
    if current["schedule"] == "daily" and not current["destination"]:
        raise BackupError("Choose where the backups go first.")
    FOLDER.mkdir(parents=True, exist_ok=True)
    CONFIG.write_text(json.dumps(current, indent=2), encoding="utf-8")
    return current


def history() -> list[dict]:
    try:
        return json.loads(LOG.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def _remember(entry: dict) -> None:
    FOLDER.mkdir(parents=True, exist_ok=True)
    LOG.write_text(json.dumps(([entry] + history())[:50], indent=2), encoding="utf-8")


def status() -> dict:
    past = history()
    return {**config(), "running": _running.locked(), "history": past[:20],
            "last_ok": next((h for h in past if h.get("ok")), None), "aws": bool(shutil.which("aws")),
            "next": _next_run().isoformat(timespec="minutes") if config()["schedule"] == "daily" else ""}


# ---- making one -------------------------------------------------------------------------

def _git(folder: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True)


def _projects() -> list[str]:
    """Every project folder a task points at."""
    from . import board   # noqa: F401  (puts the team's tools on sys.path)
    import tasklib
    found = {tasklib.parse(p).get("project", "") for p in tasklib.task_files()}
    return sorted(p for p in found if p and (Path(p) / ".git").exists())


def _bundle(project: str, into: Path) -> dict:
    """The project's branches and kept histories that GitHub doesn't have, as one git bundle (if there are any)."""
    _git(project, "fetch", "--quiet", "origin")
    refs = [r for r in _git(project, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/hive").stdout.split() if r]
    remote = _git(project, "remote", "get-url", "origin").stdout.strip()
    unpushed = [r for r in refs
                if _git(project, "rev-list", "--count", r, "--not", "--remotes=origin").stdout.strip() not in ("", "0")]
    worktrees, current = [], None
    for line in _git(project, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            current = line[len("worktree "):]
        elif line.startswith("branch ") and current and Path(current).resolve() != Path(project).resolve():
            worktrees.append({"path": current, "branch": line[len("branch refs/heads/"):]})
    entry = {"path": project, "origin": remote, "bundle": "", "refs": unpushed, "worktrees": worktrees,
             "branch": _git(project, "branch", "--show-current").stdout.strip()}
    if unpushed:
        name = re.sub(r"\W+", "-", project.strip("/")) + ".bundle"
        made = _git(project, "bundle", "create", str(into / name), *unpushed, "--not", "--remotes=origin")
        if made.returncode != 0:   # e.g. no origin: the whole history of those refs
            made = _git(project, "bundle", "create", str(into / name), *unpushed)
        if made.returncode != 0:
            raise BackupError(f"Couldn't bundle the branches of {project}: {made.stderr.strip()}")
        entry["bundle"] = f"bundles/{name}"
    return entry


def make(into: Path) -> Path:
    """Write a backup archive in `into` and return its path."""
    name = f"hive-backup-{dt.datetime.now():%Y%m%d-%H%M%S}.tar.gz"
    with tempfile.TemporaryDirectory() as tmp:
        bundles = Path(tmp) / "bundles"
        bundles.mkdir()
        projects = [_bundle(p, bundles) for p in _projects()]
        manifest = {"made": store.now(), "kit": str(KIT), "home": str(HOME),
                    "hive_version": _git(KIT, "rev-parse", "--short", "HEAD").stdout.strip(), "projects": projects}
        (Path(tmp) / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        archive = into / name
        with tarfile.open(archive, "w:gz") as tar:
            tar.add(Path(tmp) / "manifest.json", "manifest.json")
            tar.add(bundles, "bundles")
            for path in sorted(DATA.rglob("*")):
                rel = path.relative_to(DATA).as_posix()
                if path.is_file() and not path.is_socket() and not SKIP.match(rel):
                    tar.add(path, f"data/{rel}", recursive=False)
            for path in CLAUDE_FILES:
                if path.exists():
                    tar.add(path, f"claude/{path.relative_to(HOME).as_posix()}")
    return archive


def _upload(archive: Path, destination: str) -> None:
    if destination.startswith("s3://"):
        if not shutil.which("aws"):
            raise BackupError("The AWS CLI (aws) isn't installed on this machine.")
        done = subprocess.run(["aws", "s3", "cp", "--only-show-errors", str(archive), f"{destination}/{archive.name}"],
                              capture_output=True, text=True)
        if done.returncode != 0:
            raise BackupError(f"Uploading to {destination} failed: {(done.stderr or done.stdout).strip()[-500:]}")
    else:
        Path(destination).mkdir(parents=True, exist_ok=True)
        shutil.copy2(archive, Path(destination) / archive.name)


def listing(destination: str) -> list[str]:
    """The backups at the destination, oldest first."""
    if destination.startswith("s3://"):
        done = subprocess.run(["aws", "s3", "ls", f"{destination}/"], capture_output=True, text=True)
        names = [line.split()[-1] for line in done.stdout.splitlines() if line.split()]
    else:
        names = [p.name for p in Path(destination).glob("hive-backup-*.tar.gz")] if Path(destination).is_dir() else []
    return sorted(n for n in names if NAME.match(n))


def _prune(destination: str, keep: int) -> list[str]:
    old = listing(destination)[:-keep] if keep else []
    for name in old:
        if destination.startswith("s3://"):
            subprocess.run(["aws", "s3", "rm", "--only-show-errors", f"{destination}/{name}"], capture_output=True)
        else:
            (Path(destination) / name).unlink(missing_ok=True)
    return old


def run(trigger: str = "manual") -> dict:
    """Make a backup, send it to the destination and drop the oldest beyond `keep`. One at a time."""
    settings = config()
    if not settings["destination"]:
        raise BackupError("Choose where the backups go first.")
    if not _running.acquire(blocking=False):
        raise BackupError("A backup is already running.")
    started = dt.datetime.now()
    entry = {"at": started.isoformat(timespec="seconds"), "trigger": trigger, "destination": settings["destination"]}
    try:
        with tempfile.TemporaryDirectory() as tmp:
            archive = make(Path(tmp))
            entry.update(name=archive.name, size=archive.stat().st_size)
            _upload(archive, settings["destination"])
        entry["pruned"] = _prune(settings["destination"], settings["keep"])
        entry.update(ok=True, seconds=round((dt.datetime.now() - started).total_seconds(), 1))
        return entry
    except (BackupError, OSError, tarfile.TarError) as exc:
        entry.update(ok=False, error=str(exc))
        raise BackupError(str(exc)) from exc
    finally:
        _remember(entry)
        _running.release()


# ---- nightly ----------------------------------------------------------------------------

def _next_run(now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now()
    at = now.replace(hour=config()["hour"], minute=0, second=0, microsecond=0)
    return at if at > now else at + dt.timedelta(days=1)


def due(now: dt.datetime | None = None) -> bool:
    """Daily backups: once the hour has come today, if today's hasn't been made (a missed night runs at start-up)."""
    settings, now = config(), now or dt.datetime.now()
    if settings["schedule"] != "daily" or not settings["destination"]:
        return False
    today = now.replace(hour=settings["hour"], minute=0, second=0, microsecond=0)
    last = next((h["at"] for h in history() if h.get("trigger") == "scheduled"), "") or settings.get("since", "")
    slot = today if now >= today else today - dt.timedelta(days=1)
    return not last or dt.datetime.fromisoformat(last) < slot


async def watch() -> None:
    while True:
        await asyncio.sleep(60)
        if due() and not _running.locked():
            try:
                await asyncio.to_thread(run, "scheduled")
            except BackupError as exc:
                log.warning("The nightly backup failed: %s", exc)
