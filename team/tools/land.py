#!/usr/bin/env python3
"""Land a finished feature branch: clean up its history (like `git rebase -i`), rebase it on main, push it and
open the pull request. The lead merges on GitHub; Hive notices and cleans up.

1. Update main      fetch origin/<base>; fast-forward the local <base> too when that's safe (never touches a
                    folder where it's checked out, never makes a merge).
2. Clean up         the lead decides, commit by commit, what to keep, squash, fold in or drop, in which order and
                    with which messages; the result is rebased on origin/<base> in the same go. The branch's
                    commits from before are kept under refs/hive/pre-land/<branch> (Undo; and the Coach reads the
                    lead's own commits from there).
3. Push             git push --force-with-lease.
4. Pull request     gh pr create, with a description written from the spec and the reviews.
5. After the merge  the lead merges on GitHub; `check` notices (Hive runs it now and then), removes the worktree and
                    the local branch.

Where it works: the branch's worktree (recreated if the reviewer removed it); never the lead's project folder.
Records are kept in data/tasks/landing/.

Usage: python3 team/tools/land.py show TASK-012     (the plan: commits, what's behind, the pull request)
       python3 team/tools/land.py check             (clean up branches whose pull request was merged)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from tasklib import TASKS, fetch, find_task, lock, merged_into, parse, ref_exists, set_fields

import lead_review
from claim import checked_out_at, worktree_for

LANDING = TASKS / "landing"
ACTIONS = ("pick", "squash", "fixup", "drop")   # squash keeps the message to edit, fixup drops it, both combine


class LandError(Exception):
    """Something the lead needs to know (shown as is). `conflicts` lists the files when a rebase stopped on them."""

    def __init__(self, message: str, conflicts: list[str] | None = None):
        super().__init__(message)
        self.conflicts = conflicts or []


def _git(folder: str | Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True,
                          env={**os.environ, **(env or {})})


def _must(folder: str | Path, *args: str, env: dict | None = None) -> str:
    done = _git(folder, *args, env=env)
    if done.returncode != 0:
        raise LandError(f"`git {' '.join(args)}` failed: {(done.stderr or done.stdout).strip()}")
    return done.stdout


# ---- records ----------------------------------------------------------------------------

def _record_path(project: str, branch: str) -> Path:
    key = (project + "\n" + branch).encode()
    return LANDING / f"{hashlib.sha1(key).hexdigest()[:16]}.json"


def record(project: str, branch: str) -> dict:
    try:
        return json.loads(_record_path(project, branch).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_record(project: str, branch: str, **fields) -> dict:
    LANDING.mkdir(parents=True, exist_ok=True)
    data = {**record(project, branch), "project": project, "branch": branch, **fields}
    _record_path(project, branch).write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def records() -> list[dict]:
    if not LANDING.exists():
        return []
    out = []
    for p in LANDING.glob("*.json"):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            pass
    return out


# ---- the branch -------------------------------------------------------------------------

def _branch(task_id: str) -> tuple[dict, list[dict]]:
    """The branch's newest task (its fields) and every task on it."""
    path = find_task(task_id)
    if not path:
        raise KeyError(task_id)
    tasks = lead_review.on_branch(parse(path))
    meta = tasks[-1]
    if not meta.get("branch") or not Path(meta.get("project", "")).is_dir():
        raise LandError("This task has no branch to land.")
    return meta, tasks


def pre_land_ref(branch: str) -> str:
    return f"refs/hive/pre-land/{branch}"


def _not_done(tasks: list[dict]) -> str:
    waiting = [t for t in tasks if t.get("status") != "done"]
    if waiting:
        return ("Every task on the branch must be done first: "
                + ", ".join(f"{t['id']} is `{t.get('status', '')}`" for t in waiting) + ".")
    return ""


def folder(meta: dict) -> Path:
    """Where to rewrite the branch: its worktree, recreated when the reviewer removed it. Never the lead's project
    folder, and never a folder with uncommitted changes."""
    project, branch = meta["project"], meta["branch"]
    where = checked_out_at(project, branch)
    if where and where.resolve() == Path(project).resolve():
        raise LandError(f"{branch} is checked out in your project folder ({project}). Switch that folder to another "
                        f"branch, then land.")
    if not where:
        where = worktree_for(meta)
        if where.exists():
            raise LandError(f"{where} already exists but isn't {branch}'s worktree. Move it away, then land.")
        _must(project, "worktree", "add", str(where), branch)
    if _git(where, "status", "--porcelain").stdout.strip():
        raise LandError(f"{where} has uncommitted changes. Commit or remove them, then land.")
    return where


def update_base(meta: dict) -> dict:
    """Fetch origin/<base> (and the branch); move the local <base> forward too when that's only a fast-forward and
    it isn't checked out anywhere. Returns what happened."""
    project, base, branch = meta["project"], meta.get("base") or "main", meta["branch"]
    fetch(project, base)
    on_origin(project, branch)
    if not ref_exists(project, f"origin/{base}"):
        raise LandError(f"There's no origin/{base} to land on. Push {base} first, or set the task's base.")
    local = "not changed"
    if ref_exists(project, base) and not checked_out_at(project, base):
        if _git(project, "merge-base", "--is-ancestor", base, f"origin/{base}").returncode == 0:
            if _git(project, "fetch", "--quiet", "origin", f"{base}:{base}").returncode == 0:
                local = "fast-forwarded"
        else:
            local = f"not changed: your {base} has commits origin doesn't"
    elif checked_out_at(project, base):
        local = f"not changed: it's checked out in {checked_out_at(project, base)}"
    return {"onto": f"origin/{base}", "local": local}


def on_origin(project: str, branch: str) -> str:
    """The branch's commit on GitHub ('' when it isn't there), asked from origin itself; origin/<branch> is updated to
    match, or removed when GitHub no longer has the branch (a stale copy would make a push or a pull request wrong)."""
    listed = _git(project, "ls-remote", "origin", f"refs/heads/{branch}")
    if listed.returncode != 0:
        return _git(project, "rev-parse", "--verify", "--quiet", f"origin/{branch}").stdout.strip()   # offline: our copy
    sha = listed.stdout.split()[0] if listed.stdout.strip() else ""
    if sha:
        _git(project, "fetch", "--quiet", "origin", f"+refs/heads/{branch}:refs/remotes/origin/{branch}")
    else:
        _git(project, "update-ref", "-d", f"refs/remotes/origin/{branch}")
    return sha


def _commits(project: str, since: str, tip: str) -> list[dict]:
    log = _git(project, "log", "--reverse", "--no-merges", "--format=%H%x1f%h%x1f%s%x1f%an%x1f%aI%x1f%B%x1e",
               f"{since}..{tip}").stdout
    out = []
    for item in log.split("\x1e"):
        if not item.strip():
            continue
        sha, short, subject, author, at, message = item.strip("\n").split("\x1f", 5)
        stat = _git(project, "show", "--shortstat", "--format=", sha).stdout
        numbers = {k: int(n) for n, k in re.findall(r"(\d+) (file|insertion|deletion)", stat)}
        out.append({"sha": sha, "short": short, "subject": subject, "author": author, "at": at,
                    "message": message.strip(), "agent": bool(re.search(r"^Agent:\s*\S+", message, re.M)),
                    "files": numbers.get("file", 0), "additions": numbers.get("insertion", 0),
                    "deletions": numbers.get("deletion", 0)})
    return out


def _section(text: str, title: str) -> str:
    m = re.search(rf"^## {re.escape(title)}\s*\n(.*?)(?=^## |\Z)", text, re.S | re.M)
    return re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip() if m else ""


def draft_message(tasks: list[dict]) -> str:
    """One commit for the whole feature: the first task's title, its goal, and the tasks."""
    first = tasks[0]
    goal = _section((find_task(first["id"]) or Path("/dev/null")).read_text(encoding="utf-8"), "Problem / Goal")
    goal = "\n".join(line for line in goal.splitlines()).strip()
    lines = [first.get("title", first["id"]), ""]
    if goal:
        lines += [goal, ""]
    lines.append("Tasks: " + ", ".join(f"{t['id']} {t.get('title', '')}".strip() for t in tasks))
    return "\n".join(lines).strip()


def plan(task_id: str) -> dict:
    """Everything the landing panel shows. Fetches first."""
    meta, tasks = _branch(task_id)
    project, branch, base = meta["project"], meta["branch"], meta.get("base") or "main"
    fetch(project, base)
    remote = on_origin(project, branch)
    onto = f"origin/{base}" if ref_exists(project, f"origin/{base}") else base
    fork = _git(project, "merge-base", onto, branch).stdout.strip()
    head = _git(project, "rev-parse", branch).stdout.strip()
    rec = record(project, branch)
    return {
        "task": meta["id"], "tasks": [{"id": t["id"], "title": t.get("title", ""), "status": t.get("status", "")} for t in tasks],
        "project": project, "branch": branch, "base": base, "onto": onto, "head": head,
        "behind": int(_git(project, "rev-list", "--count", f"{branch}..{onto}").stdout.strip() or 0) if fork else 0,
        "commits": _commits(project, fork, branch) if fork else [],
        "pushed": bool(remote) and remote == head, "on_origin": bool(remote),
        "can_undo": ref_exists(project, pre_land_ref(branch)) and not rec.get("merged_at"),
        "not_ready": _not_done(tasks), "gh": bool(shutil.which("gh")),
        "draft_message": draft_message(tasks), "pr_title": tasks[0].get("title", ""), "pr_body": pr_body(tasks),
        "record": rec, "merged": merged_into(project, branch, base),
        "dev": meta.get("dev", ""), "folder": str(checked_out_at(project, branch) or worktree_for(meta)),
    }


# ---- 2. clean up: an interactive rebase onto origin/<base> --------------------------------

def clean_up(task_id: str, steps: list[dict], messages: list[str]) -> dict:
    """Rewrite the branch as the lead decided, on top of origin/<base>.
    steps: every commit of the branch, in the new order, each {"sha", "action": pick|squash|fixup|drop}; a pick
    starts a new commit, squash and fixup add to the one before. messages: the message of each resulting commit."""
    meta, tasks = _branch(task_id)
    if (why := _not_done(tasks)):
        raise LandError(why)
    project, branch = meta["project"], meta["branch"]
    with lock():
        where = folder(meta)
        onto = update_base(meta)["onto"]
        fork = _must(project, "merge-base", onto, branch).strip()
        mine = [c["sha"] for c in _commits(project, fork, branch)]
        given = [s.get("sha", "") for s in steps]
        if sorted(given) != sorted(mine):
            raise LandError("The branch changed since you opened this. Reload and choose again.")
        if any(s.get("action") not in ACTIONS for s in steps):
            raise LandError("Each commit is pick, squash, fixup or drop.")
        kept = [s for s in steps if s["action"] != "drop"]
        if kept and kept[0]["action"] != "pick":
            raise LandError("The first commit you keep can't be squashed into one above it: there's none.")
        groups = sum(1 for s in kept if s["action"] == "pick")
        if len(messages) != groups or any(not m.strip() for m in messages):
            raise LandError("Every commit needs a message.")
        head = _must(project, "rev-parse", branch).strip()
        if not ref_exists(project, pre_land_ref(branch)):   # the history as the team made it, kept once
            _must(project, "update-ref", pre_land_ref(branch), head)
        with tempfile.TemporaryDirectory() as tmp:
            todo, n = [], 0
            for s in kept:
                if s["action"] == "pick":
                    if n:
                        todo.append(f"exec git commit --quiet --amend --allow-empty --no-verify -F {Path(tmp) / f'm{n}'}")
                    n += 1
                    (Path(tmp) / f"m{n}").write_text(messages[n - 1].strip() + "\n", encoding="utf-8")
                todo.append(f"{'pick' if s['action'] == 'pick' else 'fixup'} {s['sha']}")
            if n:
                todo.append(f"exec git commit --quiet --amend --allow-empty --no-verify -F {Path(tmp) / f'm{n}'}")
            else:
                todo.append("noop")
            (Path(tmp) / "todo").write_text("\n".join(todo) + "\n", encoding="utf-8")
            sequence = f"{shutil.which('cp') or 'cp'} {Path(tmp) / 'todo'}"
            done = _git(where, "rebase", "-i", "--empty=drop", "--onto", onto, fork,
                        env={"GIT_SEQUENCE_EDITOR": sequence, "GIT_EDITOR": "true"})
            if done.returncode != 0:
                conflicts = [f for f in _git(where, "diff", "--name-only", "--diff-filter=U").stdout.splitlines() if f]
                _git(where, "rebase", "--abort")
                if conflicts:
                    raise LandError(f"Rebasing on {onto} stopped on conflicts in {', '.join(conflicts)}. Nothing "
                                    f"changed. Ask the dev to rebase the branch on {onto} and resolve them, then land.",
                                    conflicts)
                raise LandError(f"The rebase failed, so nothing changed: {(done.stderr or done.stdout).strip()[-600:]}")
    new_head = _must(project, "rev-parse", branch).strip()
    _save_record(project, branch, cleaned_at=_now(), original=_git(project, "rev-parse", pre_land_ref(branch)).stdout.strip())
    return {"head": new_head, "commits": len(_commits(project, onto, branch)), "onto": onto}


def undo(task_id: str) -> dict:
    """Put the branch back as the team made it (before the first clean-up)."""
    meta, _ = _branch(task_id)
    project, branch = meta["project"], meta["branch"]
    if not ref_exists(project, pre_land_ref(branch)):
        raise LandError("There's nothing to undo: the branch hasn't been cleaned up.")
    with lock():
        where = folder(meta)
        _must(where, "reset", "--hard", "--quiet", pre_land_ref(branch))
        _must(project, "update-ref", "-d", pre_land_ref(branch))
    _save_record(project, branch, cleaned_at="", undone_at=_now())
    return {"head": _must(project, "rev-parse", branch).strip()}


# ---- 3. push, 4. the pull request -------------------------------------------------------

def push(task_id: str) -> dict:
    meta, tasks = _branch(task_id)
    if (why := _not_done(tasks)):
        raise LandError(why)
    project, branch = meta["project"], meta["branch"]
    on_origin(project, branch)   # what --force-with-lease expects to replace
    done = _git(project, "push", "--force-with-lease", "--set-upstream", "origin", f"{branch}:{branch}")
    if done.returncode != 0:
        raise LandError(f"The push failed: {(done.stderr or done.stdout).strip()[-600:]}")
    _save_record(project, branch, pushed_at=_now(), pushed=_git(project, "rev-parse", branch).stdout.strip())
    return {"output": (done.stderr + done.stdout).strip()}


def pr_body(tasks: list[dict]) -> str:
    text = (find_task(tasks[0]["id"]) or Path("/dev/null")).read_text(encoding="utf-8")
    parts = []
    if (goal := _section(text, "Problem / Goal")):
        parts += ["## Why", goal]
    if (criteria := _section(text, "Acceptance Criteria")):
        parts += ["## What it does", criteria]
    parts += ["## Tasks", "\n".join(f"- {t['id']} {t.get('title', '')}".rstrip() for t in tasks)]
    reviewed = []
    for t in tasks:
        rounds = lead_review.rounds(t["id"])
        if t.get("reviewer"):
            reviewed.append(f"- {t['id']}: reviewed by {t['reviewer']}"
                            + (f"; {len(rounds)} lead review round{'s' * (len(rounds) != 1)}, last: "
                               f"{'approved' if rounds[-1]['verdict'] == 'approve' else 'changes requested'}" if rounds else ""))
    if reviewed:
        parts += ["## Reviews", "\n".join(reviewed)]
    return "\n\n".join(parts) + "\n"


def open_pr(task_id: str, title: str, body: str, draft: bool = False) -> dict:
    meta, tasks = _branch(task_id)
    project, branch, base = meta["project"], meta["branch"], meta.get("base") or "main"
    if not title.strip():
        raise LandError("The pull request needs a title.")
    if not on_origin(project, branch):
        raise LandError("Push the branch first: it isn't on GitHub.")
    if not shutil.which("gh"):
        raise LandError("The GitHub CLI (gh) isn't installed on this machine, so Hive can't open the pull request. "
                        "Open it on GitHub; the branch is pushed.")
    existing = _gh(project, "pr", "list", "--head", branch, "--state", "open", "--json", "url,number", "--limit", "1")
    found = json.loads(existing) if existing else []
    if found:
        url, number = found[0]["url"], found[0]["number"]
        _gh(project, "pr", "edit", str(number), "--title", title.strip(), "--body", body)
    else:
        args = ["pr", "create", "--base", base, "--head", branch, "--title", title.strip(), "--body", body]
        done = subprocess.run(["gh", *args, *(["--draft"] if draft else [])], cwd=project, capture_output=True, text=True)
        if done.returncode != 0:
            raise LandError(f"gh pr create failed: {(done.stderr or done.stdout).strip()[-600:]}")
        url = done.stdout.strip().splitlines()[-1]
        number = int(re.search(r"/pull/(\d+)", url).group(1)) if re.search(r"/pull/(\d+)", url) else 0
    with lock():
        for t in tasks:
            if (path := find_task(t["id"])):
                set_fields(path, pr=url)
    _save_record(project, branch, pr_url=url, pr_number=number, pr_opened_at=_now())
    return {"url": url, "number": number}


def _gh(project: str, *args: str) -> str:
    done = subprocess.run(["gh", *args], cwd=project, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else ""


# ---- 5. after the lead merged on GitHub -------------------------------------------------

def check() -> list[str]:
    """For each branch with an open pull request: once it's merged, remove its worktree and local branch."""
    cleaned = []
    for rec in records():
        if not rec.get("pr_url") or rec.get("merged_at") or not Path(rec.get("project", "")).is_dir():
            continue
        project, branch = rec["project"], rec["branch"]
        state = json.loads(_gh(project, "pr", "view", str(rec.get("pr_number") or rec["pr_url"]), "--json", "state")
                           or "{}").get("state", "") if shutil.which("gh") else ""
        if state == "CLOSED":
            _save_record(project, branch, pr_state="closed")
            continue
        if state != "MERGED":
            continue
        with lock():
            where = checked_out_at(project, branch)
            removed = []
            if where and where.resolve() != Path(project).resolve():
                if _git(project, "worktree", "remove", str(where)).returncode == 0:
                    removed.append(f"the worktree {where}")
            if not checked_out_at(project, branch) and _git(project, "branch", "-D", branch).returncode == 0:
                removed.append(f"the local branch {branch}")
            _save_record(project, branch, merged_at=_now(), pr_state="merged", removed=removed)
        cleaned.append(f"{branch}: merged; removed {', '.join(removed) or 'nothing'}")
    return cleaned


def _now() -> str:
    return dt.datetime.now().isoformat(timespec="seconds")


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "show":
        p = plan(sys.argv[2])
        print(f"{p['branch']} → {p['onto']} ({p['behind']} behind)")
        for c in p["commits"]:
            print(f"  {c['short']} {c['subject']}")
        print(f"Pull request: {p['record'].get('pr_url', 'none')}")
    elif len(sys.argv) == 2 and sys.argv[1] == "check":
        print("\n".join(check()) or "Nothing merged since the last check.")
    else:
        sys.exit("usage: land.py show TASK-NNN | land.py check")


if __name__ == "__main__":
    main()
