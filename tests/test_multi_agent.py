"""Checks that several agents per role can share the board safely.

    python3 tests/test_multi_agent.py      (from the kit folder; uses a temporary copy)
"""
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
checks = 0


def check(condition, what):
    global checks
    checks += 1
    if not condition:
        sys.exit(f"FAIL: {what}")
    print(f"ok  {what}")


def main():
    tmp = Path(tempfile.mkdtemp())
    kit = tmp / "kit"
    shutil.copytree(KIT, kit, ignore=shutil.ignore_patterns("tasks", "console", ".git", "__pycache__"))
    project = tmp / "code" / "api"
    project.mkdir(parents=True)
    git = lambda *a: subprocess.run(["git", "-C", str(project), *a], check=True, capture_output=True, text=True)
    git("init", "-q", "-b", "main")
    (project / "app.py").write_text("print('hi')\n")
    git("add", ".")
    git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "init")

    def run(script, *args, agent=None):
        env = {**os.environ, "AGENT_ID": agent} if agent else {k: v for k, v in os.environ.items() if k != "AGENT_ID"}
        return subprocess.run([sys.executable, str(kit / "scripts" / script), *map(str, args)],
                              capture_output=True, text=True, env=env)

    def status(path):
        return next(l.split(":", 1)[1].split("#")[0].strip() for l in path.read_text().splitlines() if l.startswith("status:"))

    def field(path, name):
        return next(l.split(":", 1)[1].split("#")[0].strip() for l in path.read_text().splitlines() if l.startswith(f"{name}:"))

    def set_status(path, value):
        path.write_text(path.read_text().replace(f"status: {status(path)}", f"status: {value}", 1))
        subprocess.run([sys.executable, str(kit / "scripts/on_task_change.py")],
                       input=f'{{"tool_input": {{"file_path": "{path}"}}}}', text=True, capture_output=True)

    # Two Tech Leads creating tasks at the same moment get different numbers.
    with ThreadPoolExecutor(10) as pool:
        made = list(pool.map(lambda i: run("new_task.py", project, f"Task {i}", agent=f"techlead-{i % 2 + 1}"), range(10)))
    ids = [Path(r.stdout.splitlines()[0]).name[:8] for r in made]
    check(len(set(ids)) == 10, f"10 tasks created in parallel got 10 different numbers ({sorted(ids)[0]}..{sorted(ids)[-1]})")
    task = Path(made[0].stdout.splitlines()[0])
    check(field(task, "techlead") in ("techlead-1", "techlead-2"), "the task records which Tech Lead wrote it")

    # Two devs race for the same task: exactly one wins.
    set_status(task, "ready-for-dev")   # the readiness gate bounces it (spec is empty) ...
    check(status(task) == "draft", "the readiness gate still applies")
    task.write_text(task.read_text().replace("status: draft", "status: ready-for-dev", 1))  # ... so bypass it for this test
    tid = task.name[:8]
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda d: run("claim.py", tid, "dev", agent=d), ["dev", "dev-2"]))
    winners = [r for r in results if r.returncode == 0]
    check(len(winners) == 1, "two devs claiming at once: only one gets the task")
    loser = next(r for r in results if r.returncode != 0)
    check("not waiting for a dev" in loser.stderr, f"the other is told to pick another task ({loser.stderr.strip()})")
    winner = field(task, "dev")
    check(status(task) == "in-dev" and winner in ("dev", "dev-2"), f"task is in-dev and assigned to {winner}")
    worktree = Path(field(task, "worktree"))
    check(worktree == project.parent / "api.worktrees" / tid and (worktree / "app.py").exists(),
          "the task got its own worktree next to the project")
    branch = subprocess.run(["git", "-C", str(worktree), "branch", "--show-current"], capture_output=True, text=True).stdout.strip()
    check(branch == field(task, "branch"), "the worktree is on the task's branch")
    check(subprocess.run(["git", "-C", str(project), "branch", "--show-current"], capture_output=True, text=True).stdout.strip() == "main",
          "the main project folder stays on main (the lead's checkout is untouched)")

    # Second task for the other dev: separate worktree, no interference.
    other = Path(made[1].stdout.splitlines()[0])
    other.write_text(other.read_text().replace("status: draft", "status: ready-for-dev", 1))
    loser_id = "dev-2" if winner == "dev" else "dev"
    r = run("claim.py", other.name[:8], "dev", agent=loser_id)
    check(r.returncode == 0 and Path(field(other, "worktree")) != worktree, "the other dev works on another task in its own worktree")

    # Review, rework back to the same dev, re-review by the same reviewer.
    set_status(task, "ready-for-review")
    check(run("claim.py", tid, "reviewer", agent="reviewer-2").returncode == 0, "a reviewer claims the review")
    set_status(task, "changes-requested")
    inbox = run("inbox.py", "dev", agent=winner).stdout
    check(tid in inbox.split("## Tasks you can take")[0], "rework notification goes to the dev who built it")
    check(tid not in run("inbox.py", "dev", agent=loser_id).stdout.split("## Tasks you can take")[1],
          "the other dev doesn't see someone else's rework as available")
    r = run("claim.py", tid, "dev", agent=loser_id)
    check(r.returncode != 0 and winner in r.stderr, "another dev can't take someone else's rework")
    check(run("claim.py", tid, "dev", agent=winner).returncode == 0, "the original dev takes the rework, same worktree")
    set_status(task, "ready-for-review")
    check(tid in run("inbox.py", "reviewer", agent="reviewer-2").stdout.split("## Tasks you can take")[0],
          "the re-review goes back to the same reviewer")
    check(run("claim.py", tid, "reviewer", agent="reviewer").returncode != 0, "another reviewer can't take the re-review")

    # Shared pool: every agent sees new work once, independently.
    pool_tid = "TASK-777"   # a line in the dev pool, as the hook writes it for new ready-for-dev work
    with (kit / "tasks/.inbox/dev.md").open("a") as f:
        f.write(f"- [2026-10-20 10:00] **{pool_tid}** [api] New work → `ready-for-dev` (was `draft`) — x\n")
    first = run("inbox.py", "dev", agent="dev-3").stdout
    again = run("inbox.py", "dev", agent="dev-3").stdout
    other_dev = run("inbox.py", "dev", agent="dev-4").stdout
    check(pool_tid in first.split("## Tasks")[0] and pool_tid not in again.split("## Tasks")[0],
          "a shared-pool notification shows once per agent")
    check(pool_tid in other_dev.split("## Tasks")[0], "reading it doesn't hide it from the other devs")

    # Finished: the worktree is removed, the branch kept for merging.
    set_status(task, "done")
    r = run("worktree.py", "remove", tid)
    check(r.returncode == 0 and not worktree.exists() and field(task, "worktree") == "", "worktree removed when done")
    check(field(task, "branch") in subprocess.run(["git", "-C", str(project), "branch"], capture_output=True, text=True).stdout,
          "the task's branch is kept for merging")

    # No AGENT_ID (a single terminal agent): falls back to the role name.
    r = run("inbox.py", "dev")
    check(r.returncode == 0 and "notifications for dev" in r.stdout, "without AGENT_ID the agent is just 'dev'")

    # Base branch: whatever the lead uses, never forced to main.
    git("checkout", "-q", "-b", "develop")
    (project / "dev_only.py").write_text("x = 1\n")
    git("add", ".")
    git("-c", "user.email=a@b", "-c", "user.name=a", "commit", "-qm", "develop work")
    made = run("new_task.py", project, "On develop", agent="techlead")
    on_dev = Path(made.stdout.splitlines()[0])
    check(field(on_dev, "base") == "develop", "a new task's base is the branch the lead has checked out (develop)")
    check("Conventions notes:" in made.stdout and "not written yet" in made.stdout,
          "new_task prints where the conventions notes go, and that a missing file is fine")
    on_dev.write_text(on_dev.read_text().replace("status: draft", "status: ready-for-dev", 1))
    r = run("claim.py", on_dev.name[:8], "dev", agent="dev")
    check(r.returncode == 0 and (Path(field(on_dev, "worktree")) / "dev_only.py").exists(),
          "the dev's worktree starts from develop, not main")
    git("update-ref", "refs/remotes/origin/release-2", "main")   # a base that only exists on the remote
    remote = Path(run("new_task.py", project, "From release", agent="techlead").stdout.splitlines()[0])
    remote.write_text(remote.read_text().replace("base: develop", "base: release-2", 1).replace("status: draft", "status: ready-for-dev", 1))
    r = run("claim.py", remote.name[:8], "dev", agent="dev-2")
    check(r.returncode == 0 and not (Path(field(remote, "worktree")) / "dev_only.py").exists(),
          "a base that exists only on origin is used as origin/<base>")
    git("checkout", "-q", "main")

    # Blocked: the task says who blocked it, and the lead's notification too.
    set_status(on_dev, "blocked")
    check(field(on_dev, "blocked_by") == "dev", "a blocked task records which agent blocked it")
    lead = run("inbox.py", "lead").stdout
    check(f"{on_dev.name[:8]}" in lead and "by dev" in lead, "the lead's notification says who blocked it")
    check("blocked by dev" in (kit / "tasks/BOARD.md").read_text(), "the board shows who blocked it")
    set_status(on_dev, "in-dev")
    check(field(on_dev, "blocked_by") == "", "unblocking clears it")
    check(f"{on_dev.name[:8]}" in (kit / "tasks/BOARD.md").read_text().split("## in-dev")[1] and "· dev" in
          (kit / "tasks/BOARD.md").read_text().split("## in-dev")[1], "in-progress tasks show who's working on them")

    # Upgrading from the PM era: task fields, inboxes.
    old = kit / "tasks" / "TASK-900-old.md"
    old.write_text(on_dev.read_text().replace("techlead: techlead", "pm: pm-2", 1))
    (kit / "tasks/.inbox/pm.md").write_text("- old note\n")
    run("migrate.py")
    check(field(old, "techlead") == "techlead-2" and "\npm:" not in old.read_text(), "migrate.py renames pm: pm-2 to techlead: techlead-2")
    check((kit / "tasks/.inbox/techlead.md").read_text().endswith("- old note\n") and not (kit / "tasks/.inbox/pm.md").exists(),
          "the old PM inbox is carried over")
    check(run("migrate.py").returncode == 0 and field(old, "techlead") == "techlead-2", "running it again changes nothing")
    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
