#!/usr/bin/env python3
"""Remove a finished task's git worktree. The branch and its commits stay, ready to merge.

The folder belongs to the feature branch, so it's kept while another task on that branch isn't done yet
(a follow-up in progress or waiting). A later follow-up recreates it from the branch.

Usage: python3 scripts/worktree.py remove TASK-007
"""
import subprocess
import sys

from tasklib import find_task, lock, parse, set_fields, task_files


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "remove":
        sys.exit("usage: worktree.py remove TASK-NNN")
    task_id = sys.argv[2]
    with lock():
        path = find_task(task_id)
        if not path:
            sys.exit(f"No task {task_id} on the board.")
        meta = parse(path)
        folder = meta.get("worktree")
        if not folder:
            print(f"{task_id} has no worktree.")
            return
        waiting = [t["id"] for t in map(parse, task_files())
                   if t.get("id") != task_id and t.get("project") == meta["project"]
                   and t.get("branch") == meta["branch"] and t.get("status") not in ("done", "")]
        if waiting:
            set_fields(path, worktree="")
            print(f"Kept {folder}: {', '.join(waiting)} on the same branch isn't done yet.")
            return
        done = subprocess.run(["git", "-C", meta["project"], "worktree", "remove", folder],
                              capture_output=True, text=True)
        if done.returncode != 0:
            sys.exit(f"Couldn't remove {folder}: {done.stderr.strip()}\n"
                     "It may have uncommitted changes. Tell the lead.")
        for other in task_files():   # every task that pointed at this folder
            if parse(other).get("worktree") == folder:
                set_fields(other, worktree="")
    print(f"Removed the worktree for {task_id}. Branch {meta['branch']} is kept for merging.")


if __name__ == "__main__":
    main()
