#!/usr/bin/env python3
"""Create the next task file on the central board, for a given project.

Usage:
  python3 team/tools/new_task.py <project-folder> "Filter orders by status"
      a new feature: its own branch, feature-filter-orders-by-status
  python3 team/tools/new_task.py <project-folder> "Show the status filter as a dropdown" --follow-up TASK-012
      more work on TASK-012's feature (an addition, a fix, a misunderstanding cleared up):
      same branch and base, new commits on top
"""
import argparse
import datetime as dt
import re
import subprocess
from pathlib import Path

from tasklib import TASKS, TEMPLATES, agent_id, find_task, knowledge_hint, lock, parse, task_files


def _git(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)


def _agent_branches(project: Path) -> set[str]:
    """Branches the agents created for this project's tasks."""
    return {t.get("branch", "") for t in map(parse, task_files()) if t.get("project") == str(project)}


def base_branch(project: Path) -> str:
    """The branch the lead has checked out (their working base: main, develop, a release…), unless it's
    one of the agents' feature branches; else main or master. The Tech Lead confirms it with the lead."""
    current = _git(project, "branch", "--show-current").stdout.strip()
    if current and current not in _agent_branches(project):
        return current
    for name in ("main", "master"):
        if _git(project, "rev-parse", "--verify", "--quiet", name).returncode == 0:
            return name
    return current or "main"


def feature_branch(project: Path, title: str) -> str:
    """feature-<title in kebab case>; -2, -3… if that name is already taken in the repo or on the board."""
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:50].strip("-") or "work"
    taken = _agent_branches(project)
    name, n = f"feature-{slug}", 2
    while name in taken or any(_git(project, "rev-parse", "--verify", "--quiet", ref).returncode == 0
                               for ref in (name, f"origin/{name}")):
        name, n = f"feature-{slug}-{n}", n + 1
    return name


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the next task on the board.")
    parser.add_argument("project")
    parser.add_argument("title", nargs="+")
    parser.add_argument("--follow-up", metavar="TASK-NNN",
                        help="more work on that task's feature: same branch and base, new commits on top")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    if not (project / ".git").exists():
        parser.exit(1, f"Not a git repository: {project}\nAsk the lead for the right folder (or to run `git init` there).\n")
    title = " ".join(args.title).strip()
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]

    with lock():   # two Tech Leads creating tasks at once must not get the same number
        if args.follow_up:
            original = find_task(args.follow_up)
            if not original:
                parser.exit(1, f"No task {args.follow_up} on the board.\n")
            first = parse(original)
            if first.get("project") != str(project):
                parser.exit(1, f"{args.follow_up} is in {first.get('project')}, not {project}.\n")
            branch, base, follows = first["branch"], first.get("base", ""), args.follow_up
        else:
            branch, base, follows = feature_branch(project, title), base_branch(project), ""
        nums = [int(m.group(1)) for p in task_files() if (m := re.match(r"TASK-(\d+)", p.name))]
        tid = f"TASK-{(max(nums) + 1) if nums else 1:03d}"
        body = (TEMPLATES / "TASK.md").read_text(encoding="utf-8")
        body = (body.replace("BRANCH_NAME", branch)
                    .replace("FOLLOWS", follows)
                    .replace("TASK-000", tid)
                    .replace("Short imperative title", title)
                    .replace("PROJECT_PATH", str(project))
                    .replace("BASE_BRANCH", base)
                    .replace("TECHLEAD_ID", agent_id("techlead"))
                    .replace("YYYY-MM-DD", dt.date.today().isoformat()))
        path = TASKS / f"{tid}-{slug}.md"
        path.write_text(body, encoding="utf-8")
    print(path)
    if follows:
        print(f"Follow-up to {follows}: same branch {branch} (from {base}); the dev adds commits on top.")
    else:
        print(f"Branch: {branch}, from base {base}  (confirm the base with the lead; change `base:` if they want another)")
    print(knowledge_hint(project))


if __name__ == "__main__":
    main()
