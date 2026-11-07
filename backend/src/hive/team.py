"""The team's instructions under version control: the Coach's proposals, and the history of every change.

The team = team/agents/*.md, team/TEAM.md, team/PREFERENCES.md and team/templates/ in the Hive folder, a git repository.
- Proposals (data/coach/proposals/P-NNN-*.md, file paths relative to team/) are applied only when the lead approves one: the change is written,
  committed on its own (with the proposal id and its tasks in the message), and the agents are reinstalled.
- History is `git log` over those files: who changed what, when and why, the diff, the files at any commit,
  and undo (a commit that reverses one, so the undo is in the history too).
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
from pathlib import Path

from . import board  # noqa: F401  (puts the team's tools on the path)
from .store import KIT, TEAM

import coach as kit_coach  # noqa: E402  (team/tools/coach.py)

TEAM_PATHS = ["team/agents", "team/TEAM.md", "team/PREFERENCES.md", "team/templates"]
SHA = re.compile(r"^[0-9a-f]{7,40}$")


class TeamError(Exception):
    """Something the lead needs to sort out (shown as is)."""


def _git(*args: str, check: bool = True) -> str:
    done = subprocess.run(["git", "-C", str(KIT), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise TeamError(done.stderr.strip() or f"git {' '.join(args)} failed")
    return done.stdout


def is_repo() -> bool:
    return subprocess.run(["git", "-C", str(KIT), "rev-parse", "--git-dir"], capture_output=True).returncode == 0


def _team_file(path: str) -> bool:
    return any(path == p or path.startswith(p + "/") for p in TEAM_PATHS)


def _reinstall() -> None:
    """Copy the changed instructions to ~/.claude/agents for terminal agents (console agents read team/)."""
    subprocess.run(["bash", str(KIT / "scripts" / "install.sh")], capture_output=True, text=True, timeout=120)


def _clean(files: list[str]) -> None:
    dirty = [f for f in files if _git("status", "--porcelain", "--", f).strip()]
    if dirty:
        raise TeamError(f"{', '.join(dirty)} has changes that aren't committed yet. Commit or discard them first, "
                        "so this change can be committed (and undone) on its own.")


# ---- proposals --------------------------------------------------------------------------

def proposals() -> list[dict]:
    folder = kit_coach.PROPOSALS
    items = [kit_coach.read_proposal(p) for p in sorted(folder.glob("P-*.md"))] if folder.exists() else []
    for item in items:
        item["problems"] = kit_coach.problems(item, TEAM) if item["status"] == "pending" else []
    order = {"pending": 0, "approved": 1, "rejected": 2}
    return sorted(items, key=lambda p: (order.get(p["status"], 3), -int(p["id"][2:] or 0)))


def _proposal(pid: str) -> tuple[Path, dict]:
    path = kit_coach.proposal_path(pid)
    if not path:
        raise KeyError(pid)
    return path, kit_coach.read_proposal(path)


def _decide(path: Path, status: str, note: str, commit: str = "") -> None:
    text = path.read_text(encoding="utf-8")
    fields = {"status": status, "decided": dt.date.today().isoformat(), "note": " ".join(note.split()), "commit": commit}
    for name, value in fields.items():
        text = re.sub(rf"^{name}:[^\n]*", lambda m: f"{name}: {value}", text, count=1, flags=re.M)
    path.write_text(text, encoding="utf-8")


def _with_edited_afters(path: Path, afters: list[str]) -> None:
    """The lead edited the new text of the blocks before approving: write it into the proposal file."""
    text = path.read_text(encoding="utf-8")
    blocks = list(kit_coach.BLOCK.finditer(text))
    if len(afters) != len(blocks):
        raise TeamError("The edited proposal doesn't match its change blocks. Reload the page and try again.")
    for block, after in reversed(list(zip(blocks, afters))):
        start, end = block.span(3)
        text = text[:start] + after.rstrip("\n") + "\n" + text[end:]
    path.write_text(text, encoding="utf-8")


def approve(pid: str, afters: list[str] | None = None, note: str = "") -> dict:
    path, proposal = _proposal(pid)
    if proposal["status"] != "pending":
        raise TeamError(f"{pid} is already {proposal['status']}.")
    if afters is not None:
        _with_edited_afters(path, afters)
        proposal = kit_coach.read_proposal(path)
    found = kit_coach.problems(proposal, TEAM)
    if found:
        raise TeamError("Can't apply it as it is: " + " ".join(found))
    files = sorted({f"team/{c['file']}" for c in proposal["changes"]})
    commit = ""
    if is_repo():
        _clean(files)
    kit_coach.apply(proposal, TEAM)
    if is_repo():
        message = (f"Coach: {proposal['title']}\n\n{proposal['why']}\n\n"
                   f"Coach-Proposal: {pid}\nTasks: {', '.join(proposal['tasks']) or '-'}\nApproved-by: lead"
                   + (f"\nNote: {note}" if note else ""))
        _git("add", "--", *files)
        _git("commit", "-m", message, "--", *files)
        commit = _git("rev-parse", "--short", "HEAD").strip()
    _decide(path, "approved", note, commit)
    _reinstall()
    return kit_coach.read_proposal(path)


def reject(pid: str, note: str = "") -> dict:
    path, proposal = _proposal(pid)
    if proposal["status"] != "pending":
        raise TeamError(f"{pid} is already {proposal['status']}.")
    _decide(path, "rejected", note)
    return kit_coach.read_proposal(path)


# ---- history ----------------------------------------------------------------------------

def history(limit: int = 200) -> list[dict]:
    """Every commit that changed the team's instructions, newest first."""
    if not is_repo():
        return []
    out = _git("log", f"-n{limit}", "--format=\x1e%H\x1f%h\x1f%aI\x1f%an\x1f%s\x1f%b\x1f", "--name-only", "--", *TEAM_PATHS)
    entries = []
    for record in out.split("\x1e")[1:]:
        sha, short, date, author, subject, body, names = record.split("\x1f", 6)
        trailers = dict(re.findall(r"^(Coach-Proposal|Tasks|Approved-by|Note): *(.+)$", body, re.M))
        entries.append({"sha": sha, "short": short, "date": date, "author": author, "subject": subject,
                        "body": re.sub(r"^(Coach-Proposal|Tasks|Approved-by|Note|Co-Authored-By|Claude-Session):.*\n?",
                                       "", body, flags=re.M).strip(),
                        "proposal": trailers.get("Coach-Proposal", ""), "tasks": trailers.get("Tasks", ""),
                        "by": "Coach" if "Coach-Proposal" in trailers else author,
                        "files": [n for n in names.split("\n") if n.strip() and _team_file(n.strip())]})
    return entries


def change(sha: str) -> dict:
    """One commit: its message and the diff of each team file it changed."""
    if not SHA.match(sha):
        raise KeyError(sha)
    entry = next((e for e in history(1000) if e["sha"].startswith(sha)), None)
    if not entry:
        raise KeyError(sha)
    patch = _git("show", "--format=", "--patch", "--no-color", entry["sha"], "--", *TEAM_PATHS)
    diffs = []
    for part in re.split(r"^(?=diff --git )", patch, flags=re.M):
        name = re.match(r"diff --git a/(\S+) b/(\S+)", part)
        if name:
            diffs.append({"file": name.group(2), "diff": part})
    every_file = [n for n in _git("show", "--format=", "--name-only", entry["sha"]).splitlines() if n.strip()]
    others = [n for n in every_file if not _team_file(n)]
    return {**entry, "diffs": diffs, "other_files": others,
            "undoable": not others and len(_git("rev-list", "--parents", "-n1", entry["sha"]).split()) == 2}


def files_at(sha: str) -> list[str]:
    if not SHA.match(sha):
        raise KeyError(sha)
    return [n for n in _git("ls-tree", "-r", "--name-only", sha, "--", *TEAM_PATHS).splitlines() if n.strip()]


def file_at(sha: str, path: str) -> str:
    if not SHA.match(sha) or path not in files_at(sha):
        raise KeyError(path)
    return _git("show", f"{sha}:{path}")


def undo(sha: str) -> dict:
    found = change(sha)
    if not found["undoable"]:
        raise TeamError("This change also touched files outside the team's instructions "
                        f"({', '.join(found['other_files'][:5]) or 'a merge'}), so it can't be undone from here.")
    _clean(found["files"])
    _git("revert", "--no-edit", found["sha"])
    _reinstall()
    return history(1)[0]
