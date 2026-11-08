"""Shared helpers for the task board. Standard library only."""
from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]   # the Hive folder
TEAM = ROOT / "team"        # the team's instructions, templates and these tools
TOOLS = TEAM / "tools"
TEMPLATES = TEAM / "templates"
DATA = ROOT / "data"        # everything local: the board, the Tech Lead's notes, the Coach's work, the console's data
TASKS = DATA / "tasks"
INBOX = TASKS / ".inbox"
STATE = INBOX / ".state.json"
KNOWLEDGE = DATA / "knowledge"   # the Tech Lead's memory of each service; local, never in the projects

# Which role gets pinged when a task enters a status.
ROUTING = {
    "ready-for-dev": "dev",
    "changes-requested": "dev",
    "ready-for-review": "reviewer",
    "blocked": "lead",
    "done": "lead",
}

ORDER = ["blocked", "draft", "ready-for-dev", "in-dev", "changes-requested",
         "ready-for-review", "in-review", "done"]

_FM = re.compile(r"^---\s*\n(.*?)\n---", re.S)


def parse(path: Path) -> dict:
    """Return the front-matter fields of a task file as a dict."""
    m = _FM.match(path.read_text(encoding="utf-8"))
    meta = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                meta[k.strip()] = v.split("#", 1)[0].strip()
    meta["file"] = path.name
    if "pm" in meta and not meta.get("techlead"):   # tasks written before the Tech Lead rename
        meta["techlead"] = meta["pm"]
    return meta


# Which task field names the agent holding a task, by status.
HOLDER = {"draft": "techlead", "in-dev": "dev", "changes-requested": "dev",
          "ready-for-review": "reviewer", "in-review": "reviewer", "blocked": "blocked_by"}


def holder(meta: dict) -> str:
    """The agent working on the task now ('' if nobody yet). For blocked: who blocked it."""
    return meta.get(HOLDER.get(meta.get("status", ""), ""), "")


def knowledge_hint(project: str | Path) -> str:
    folder = KNOWLEDGE / Path(project).name
    if folder.exists():
        files = ", ".join(sorted(p.name for p in folder.glob("*.md")))
        return (f"Knowledge: {folder}/ ({files}). Read index.md, then the service files the task touches, before "
                f"searching the code; `python3 {TOOLS}/knowledge.py status {project}` shows what changed since.")
    return f"Knowledge: none yet for {Path(project).name}. The conventions are whatever the existing code does."


def project_name(meta: dict) -> str:
    return Path(meta.get("project", "?")).name


def task_files() -> list[Path]:
    return sorted(TASKS.glob("TASK-*.md"))


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    INBOX.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2))


ROLES = ("techlead", "dev", "reviewer")


def role_of(agent_id: str) -> str:
    """dev-2 -> dev. Agent IDs are a role, optionally followed by -N."""
    return agent_id.split("-")[0]


def agent_id(role: str) -> str:
    """This agent's ID: $AGENT_ID if it belongs to the role (set by the console, or by you in
    a terminal: AGENT_ID=dev-2 claude --agent dev), otherwise just the role name."""
    env = os.environ.get("AGENT_ID", "")
    return env if env and role_of(env) == role else role


@contextmanager
def lock():
    """One writer at a time on the board, across agents and processes."""
    TASKS.mkdir(parents=True, exist_ok=True)
    with open(TASKS / ".lock", "w") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def find_task(task_id: str) -> Path | None:
    return next((p for p in task_files() if p.name.startswith(f"{task_id}-")), None)


def set_fields(path: Path, **fields: str) -> None:
    """Set front-matter values, keeping comments; add fields that are missing."""
    text = path.read_text(encoding="utf-8")
    m = _FM.match(text)
    lines = m.group(1).splitlines()
    for key, value in fields.items():
        for i, line in enumerate(lines):
            if re.match(rf"^{key}\s*:", line):
                comment = line.split("#", 1)[1] if "#" in line else ""
                lines[i] = f"{key}: {value}" + (f"        #{comment}" if comment else "")
                break
        else:
            lines.append(f"{key}: {value}")
    path.write_text(f"---\n" + "\n".join(lines) + "\n---" + text[m.end():], encoding="utf-8")


# ---- git: where branches start, and whether one is already merged ---------------------------
# Hive never changes the lead's local branches: it only fetches, so origin/<base> shows what's on GitHub.

def _git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)


def ref_exists(project: str, ref: str) -> bool:
    return _git(project, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def fetch(project: str, ref: str = "") -> None:
    """Update origin/* (never a local branch); offline or no remote: nothing happens."""
    _git(project, "fetch", "--quiet", "origin", *([ref] if ref else []))


def freshest_base(project: str, base: str) -> str:
    """The base to start from and compare against: origin's copy when it's ahead of (or replaces) the local one,
    since the lead merges on GitHub and the local branch falls behind; the local one when it has commits origin
    doesn't (work the lead hasn't pushed) or origin has no such branch."""
    local, remote = ref_exists(project, base), ref_exists(project, f"origin/{base}")
    if not remote:
        return base if local else ""
    if not local:
        return f"origin/{base}"
    origin_in_local = _git(project, "merge-base", "--is-ancestor", f"origin/{base}", base).returncode == 0
    return base if origin_in_local else f"origin/{base}"


def merged_into(project: str, branch: str, base: str) -> bool:
    """Whether everything on the branch is already on origin's base: merged, rebased or squashed (merging it
    again would change nothing). False when unsure: no origin copy, or the lead changed those lines while
    squashing."""
    target = f"origin/{base}"
    if not ref_exists(project, branch) or not ref_exists(project, target):
        return False
    if _git(project, "merge-base", "--is-ancestor", branch, target).returncode == 0:
        return True
    merged = _git(project, "merge-tree", "--write-tree", target, branch)
    if merged.returncode in (0, 1):   # git 2.38+: the tree a merge would make (1 means conflicts)
        tree = _git(project, "rev-parse", f"{target}^{{tree}}").stdout.strip()
        return merged.returncode == 0 and merged.stdout.split("\n", 1)[0].strip() == tree
    return _changes_already_in(project, branch, target)


def _changes_already_in(project: str, branch: str, target: str) -> bool:
    """For older git: the branch's whole change can be taken back out of the target cleanly, so it's in there."""
    fork = _git(project, "merge-base", target, branch).stdout.strip()
    patch = _git(project, "diff", "--binary", fork, branch).stdout
    if not fork or not patch:
        return bool(fork)
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(tmp) / "index")}
        run = lambda *args, **kw: subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True, env=env, **kw)
        return (run("read-tree", target).returncode == 0
                and run("apply", "--cached", "--check", "--reverse", "-", input=patch).returncode == 0)
