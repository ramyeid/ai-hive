#!/usr/bin/env python3
"""Claim a task for this agent, so no other agent of the same role takes it.

Usage: python3 scripts/claim.py TASK-007 dev        (or reviewer)

The agent's ID comes from $AGENT_ID (e.g. dev-2), defaulting to the role name.
- dev:      ready-for-dev, or changes-requested on a task it built → in-dev.
            Creates (or reuses) the task's git worktree: a separate folder on the task's
            branch, so several devs never share one checkout. Prints where to work.
- reviewer: ready-for-review → in-review.
Claims are atomic: if two agents try at once, only one gets the task.
"""
import subprocess
import sys
from pathlib import Path

from tasklib import agent_id, find_task, lock, parse, set_fields
import on_task_change

CLAIMABLE = {"dev": {"ready-for-dev", "changes-requested"}, "reviewer": {"ready-for-review"}}
WORKING = {"dev": "in-dev", "reviewer": "in-review"}


def worktree_for(meta: dict) -> Path:
    project = Path(meta["project"])
    return project.parent / f"{project.name}.worktrees" / meta["id"]


def ensure_worktree(meta: dict) -> Path:
    path = worktree_for(meta)
    if path.exists():
        return path
    project, branch, base = meta["project"], meta["branch"], meta.get("base") or "main"
    has_branch = subprocess.run(["git", "-C", project, "rev-parse", "--verify", "--quiet", branch],
                                capture_output=True).returncode == 0
    cmd = ["git", "-C", project, "worktree", "add", str(path)] + ([branch] if has_branch else ["-b", branch, base])
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
        else:
            fields = {"status": WORKING[role], role: me}
            if role == "dev":
                fields["worktree"] = str(ensure_worktree(meta))
            set_fields(path, **fields)
            on_task_change.process(path)
            print(f"Claimed {task_id} for {me}.")
    meta = parse(path)
    if meta.get("worktree"):
        print(f"Work in: {meta['worktree']}  (branch {meta['branch']}, from {meta.get('base')})")
        print(f"Start every command with: cd {meta['worktree']} &&")


if __name__ == "__main__":
    main()
