#!/usr/bin/env python3
"""Claim a task for this agent, so no other agent of the same role takes it.

Usage: python3 scripts/claim.py TASK-007 dev        (or reviewer)

The agent's ID comes from $AGENT_ID (e.g. dev-2), defaulting to the role name.
- dev:      ready-for-dev, or changes-requested on a task it built → in-dev.
            Creates (or reuses) the branch's git worktree: a separate folder on the feature
            branch, so devs never share a checkout. Follow-up tasks on the same feature reuse
            the same branch and folder and add commits on top. Only one task per branch can be
            in progress at a time. Records `from_commit:` (where this task's commits start).
- reviewer: ready-for-review → in-review.
Claims are atomic: if two agents try at once, only one gets the task.
"""
import subprocess
import sys
from pathlib import Path

from tasklib import agent_id, knowledge_hint, find_task, lock, parse, set_fields, task_files
import on_task_change

CLAIMABLE = {"dev": {"ready-for-dev", "changes-requested"}, "reviewer": {"ready-for-review"}}
WORKING = {"dev": "in-dev", "reviewer": "in-review"}
ACTIVE = {"in-dev", "changes-requested", "ready-for-review", "in-review"}   # someone is working on the branch


def _git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True)


def worktree_for(meta: dict) -> Path:
    """One folder per branch, next to the project: <project>.worktrees/feature-…"""
    project = Path(meta["project"])
    return project.parent / f"{project.name}.worktrees" / meta["branch"].replace("/", "-")


def checked_out_at(project: str, branch: str) -> Path | None:
    """Where the branch is already checked out (an existing worktree, or the project folder itself)."""
    current = None
    for line in _git(project, "worktree", "list", "--porcelain").stdout.splitlines():
        if line.startswith("worktree "):
            current = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{branch}":
            return current
    return None


def busy_with(meta: dict) -> dict | None:
    """Another task on the same feature branch that's still in progress."""
    for other in map(parse, task_files()):
        if (other.get("id") != meta["id"] and other.get("project") == meta["project"]
                and other.get("branch") == meta["branch"] and other.get("status") in ACTIVE):
            return other
    return None


def start_point(project: str, base: str, exists) -> str:
    """Where the task branch starts: the base as the lead named it, whatever branch that is.
    If it only exists on the remote (e.g. `develop` never checked out here), use origin's copy."""
    if exists(base):
        return base
    subprocess.run(["git", "-C", project, "fetch", "--quiet", "origin", base], capture_output=True)
    if exists(f"origin/{base}"):
        return f"origin/{base}"
    sys.exit(f"The base branch `{base}` doesn't exist locally or on origin, so the worktree can't be created.\n"
             "Ask the lead which branch they meant, set `base:` in the task, and claim again.")


def ensure_worktree(meta: dict) -> Path:
    project, branch = meta["project"], meta["branch"]
    existing = checked_out_at(project, branch)
    if existing == Path(project):
        sys.exit(f"The branch {branch} is checked out in your project folder ({project}), so the dev can't get its own "
                 f"folder for it. Ask the lead to switch the project folder to another branch, then claim again.")
    if existing:
        return existing   # follow-ups and rework reuse the branch's folder
    path = worktree_for(meta)
    exists = lambda ref: subprocess.run(["git", "-C", project, "rev-parse", "--verify", "--quiet", ref],
                                        capture_output=True).returncode == 0
    if exists(branch):
        cmd = ["git", "-C", project, "worktree", "add", str(path), branch]
    else:
        base = start_point(project, meta.get("base") or "main", exists)
        cmd = ["git", "-C", project, "worktree", "add", str(path), "-b", branch, base]
    done = subprocess.run(cmd, capture_output=True, text=True)
    if done.returncode != 0:
        sys.exit(f"Couldn't create the worktree for {meta['id']}: {done.stderr.strip()}\n"
                 "Set the task to blocked and tell the lead.")
    return path


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[2] not in CLAIMABLE:
        sys.exit("usage: claim.py TASK-NNN dev|reviewer")
    task_id, role = sys.argv[1], sys.argv[2]
    me = agent_id(role)
    with lock():
        path = find_task(task_id)
        if not path:
            sys.exit(f"No task {task_id} on the board.")
        meta = parse(path)
        status, owner = meta.get("status", ""), meta.get(role, "")
        if status == WORKING[role] and owner == me:
            print(f"{task_id} is already yours.")
        elif status not in CLAIMABLE[role]:
            sys.exit(f"{task_id} is `{status}`, not waiting for a {role}. Pick another task.")
        elif status == "changes-requested" and owner and owner != me:
            sys.exit(f"{task_id} is rework for {owner}, who built it. Pick another task.")
        elif status == "ready-for-review" and owner and owner != me:
            sys.exit(f"{task_id} is a re-review for {owner}, who reviewed it before. Pick another task.")
        elif role == "dev" and (other := busy_with(meta)):
            sys.exit(f"{task_id} is on branch {meta['branch']}, where {other['id']} is still `{other['status']}`. "
                     f"One task per branch at a time: pick another task, or wait until {other['id']} is done.")
        else:
            fields = {"status": WORKING[role], role: me}
            if role == "dev":
                fields["worktree"] = str(ensure_worktree(meta))
                if not meta.get("from_commit"):   # first claim: where this task's commits start
                    fields["from_commit"] = _git(fields["worktree"], "rev-parse", "--short", "HEAD").stdout.strip()
            set_fields(path, **fields)
            on_task_change.process(path)
            print(f"Claimed {task_id} for {me}.")
    meta = parse(path)
    if meta.get("worktree"):
        print(f"Work in: {meta['worktree']}  (branch {meta['branch']}, from {meta.get('base')})")
        if meta.get("follows"):
            print(f"Follow-up to {meta['follows']}: add commits on top of what's there. No new branch, no rebase, no force-push.")
        print(f"This task's changes: git diff {meta.get('from_commit')}..HEAD")
        print(f"Start every command with: cd {meta['worktree']} &&")
    print(knowledge_hint(meta["project"]))


if __name__ == "__main__":
    main()
