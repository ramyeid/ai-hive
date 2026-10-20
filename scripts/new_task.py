#!/usr/bin/env python3
"""Create the next task file on the central board, for a given project.

Usage: python3 scripts/new_task.py <project-folder> "Add password reset flow"
"""
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

from tasklib import ROOT, TASKS, agent_id, lock, task_files


def base_branch(project: Path) -> str:
    """main or master if it exists, else the current branch, else main."""
    def git(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-C", str(project), *args],
                              capture_output=True, text=True)
    for name in ("main", "master"):
        if git("rev-parse", "--verify", "--quiet", name).returncode == 0:
            return name
    return git("branch", "--show-current").stdout.strip() or "main"


def main() -> None:
    if len(sys.argv) < 3:
        sys.exit('usage: new_task.py <project-folder> "<title>"')
    project = Path(sys.argv[1]).expanduser().resolve()
    if not (project / ".git").exists():
        sys.exit(f"Not a git repository: {project}\n"
                 "Ask the lead for the right folder (or to run `git init` there).")

    title = " ".join(sys.argv[2:]).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    base = base_branch(project)
    with lock():   # two PMs creating tasks at once must not get the same number
        nums = [int(m.group(1)) for p in task_files()
                if (m := re.match(r"TASK-(\d+)", p.name))]
        tid = f"TASK-{(max(nums) + 1) if nums else 1:03d}"
        body = (ROOT / "templates" / "TASK.md").read_text(encoding="utf-8")
        body = (body.replace("TASK-000-short-slug", f"{tid}-{slug}")
                    .replace("TASK-000", tid)
                    .replace("Short imperative title", title)
                    .replace("PROJECT_PATH", str(project))
                    .replace("BASE_BRANCH", base)
                    .replace("PM_ID", agent_id("pm"))
                    .replace("YYYY-MM-DD", dt.date.today().isoformat()))
        path = TASKS / f"{tid}-{slug}.md"
        path.write_text(body, encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
