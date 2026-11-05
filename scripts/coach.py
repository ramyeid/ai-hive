#!/usr/bin/env python3
"""The Coach's tools: gather evidence of how tasks went, and write proposals to improve the team.

Usage:
  python3 scripts/coach.py evidence [--since last|all|YYYY-MM-DD] [--tasks TASK-012,TASK-019] [--project PATH]
      Writes coach/runs/<time>/evidence.md for the chosen tasks and prints its path. Per task: the lead's own
      words (conversations, Clarifications), the review findings and rounds, blocked questions, the dev's notes,
      follow-ups, and the GitHub pull request: the lead's commits on the branch (any commit without an
      `Agent:` line), with their diffs, and the lead's review comments.
  python3 scripts/coach.py propose "Short title"
      Creates coach/proposals/P-NNN-short-title.md from the template and prints its path.
  python3 scripts/coach.py check P-NNN
      Checks a proposal: allowed files only, every BEFORE found exactly once in the file as it is now.
  python3 scripts/coach.py done
      Records that this review is finished (the next `--since last` starts here).

Proposals only ever change the team's instructions: agents/*.md, TEAM.md, PREFERENCES.md, templates/*.md.
The lead approves, edits or rejects each one in the console (Improvements); nothing is applied before that.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from tasklib import INBOX, ROOT, TASKS, parse, task_files

COACH = ROOT / "coach"
RUNS = COACH / "runs"
PROPOSALS = COACH / "proposals"
STATE = COACH / "state.json"
EDITABLE = re.compile(r"^(agents/[\w-]+\.md|TEAM\.md|PREFERENCES\.md|templates/[\w-]+\.md)$")
BLOCK = re.compile(r"^<<<<<<< (\S+)[ \t]*\n(.*?)^=======[ \t]*\n(.*?)^>>>>>>>[ \t]*$", re.M | re.S)
LIMIT = {"words": 5000, "section": 3000, "diff": 6000}


# ---- proposals -------------------------------------------------------------------------

def proposal_path(pid: str) -> Path | None:
    return next(PROPOSALS.glob(f"{pid}-*.md"), None) if re.fullmatch(r"P-\d{3,}", pid) else None


def read_proposal(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    meta = parse(path)
    body = re.sub(r"^---\s*\n.*?\n---\s*\n", "", text, count=1, flags=re.S)
    def section(name: str) -> str:
        found = re.search(rf"^## {name}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
        return re.sub(r"<!--.*?-->", "", found.group(1), flags=re.S).strip() if found else ""
    changes = [{"file": m.group(1), "before": _strip_newline(m.group(2)), "after": _strip_newline(m.group(3))}
               for m in BLOCK.finditer(section("Change") if section("Change") else "")]
    return {"id": meta.get("id", ""), "title": meta.get("title", ""), "status": meta.get("status", "pending"),
            "tasks": [t.strip() for t in meta.get("tasks", "").split(",") if t.strip()],
            "created": meta.get("created", ""), "decided": meta.get("decided", ""), "note": meta.get("note", ""),
            "commit": meta.get("commit", ""), "why": section("Why"), "evidence": section("Evidence"),
            "changes": changes, "file": path.name}


def _strip_newline(text: str) -> str:
    return text[:-1] if text.endswith("\n") else text


def problems(proposal: dict, root: Path = ROOT) -> list[str]:
    """What stops a proposal from being applied to the files as they are now."""
    found = []
    if not proposal["title"]:
        found.append("The proposal has no title.")
    if not proposal["why"] or not proposal["evidence"]:
        found.append("Fill in Why and Evidence.")
    if not proposal["changes"]:
        found.append("No change blocks (<<<<<<< FILE … ======= … >>>>>>>) under ## Change.")
    contents: dict[str, str] = {}
    for change in proposal["changes"]:
        name = change["file"]
        if not EDITABLE.match(name):
            found.append(f"{name}: proposals can only change agents/*.md, TEAM.md, PREFERENCES.md or templates/*.md.")
            continue
        path = root / name
        text = contents.get(name, path.read_text(encoding="utf-8") if path.exists() else "")
        if not path.exists() and change["before"]:
            found.append(f"{name} doesn't exist: leave BEFORE empty to create it.")
        elif change["before"] and text.count(change["before"]) != 1:
            found.append(f"{name}: BEFORE appears {text.count(change['before'])} times; it must appear exactly once.")
        else:
            contents[name] = _applied(text, change)
    return found


def _applied(text: str, change: dict) -> str:
    if not change["before"]:
        return (text.rstrip("\n") + "\n\n" if text.strip() else "") + change["after"].rstrip("\n") + "\n"
    return text.replace(change["before"], change["after"], 1)


def apply(proposal: dict, root: Path = ROOT) -> list[str]:
    """Apply every change block, in order. Returns the files changed. Call only when problems() is empty."""
    changed = []
    for change in proposal["changes"]:
        path = root / change["file"]
        path.parent.mkdir(parents=True, exist_ok=True)
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        path.write_text(_applied(text, change), encoding="utf-8")
        if change["file"] not in changed:
            changed.append(change["file"])
    return changed


def propose(title: str) -> Path:
    PROPOSALS.mkdir(parents=True, exist_ok=True)
    numbers = [int(m.group(1)) for p in PROPOSALS.glob("P-*.md") if (m := re.match(r"P-(\d+)", p.name))]
    pid = f"P-{(max(numbers) + 1) if numbers else 1:03d}"
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40]
    path = PROPOSALS / f"{pid}-{slug}.md"
    text = (ROOT / "templates" / "PROPOSAL.md").read_text(encoding="utf-8")
    path.write_text(text.replace("P-000", pid).replace("TITLE", title)
                        .replace("YYYY-MM-DD", dt.date.today().isoformat()), encoding="utf-8")
    return path


# ---- evidence ----------------------------------------------------------------------------

def _clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n… ({len(text) - limit} more characters cut)"


def _activity() -> list[dict]:
    path = INBOX / "activity.jsonl"
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def _section(text: str, name: str) -> str:
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    found = re.search(rf"^## {re.escape(name)}\s*\n(.*?)(?=^## |\Z)", body, re.M | re.S)
    content = found.group(1).strip().rstrip("-").strip() if found else ""
    lines = [l for l in content.splitlines() if l.strip()]
    table = [l for l in lines if l.strip().startswith("|")]
    rows = [l for l in table[1:] if not re.fullmatch(r"\|[\s:|-]*", l.strip())]   # data rows, not header/separator
    return content if rows or len(lines) > len(table) else ""   # empty template table = nothing to say


def _lead_words(task_id: str) -> list[str]:
    """The lead's messages in the saved conversations on this task."""
    folder = TASKS / "chats" / task_id
    words = []
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        chat = json.loads(path.read_text(encoding="utf-8"))
        for event in chat.get("events", []):
            if event.get("kind") == "user" and event.get("text", "").strip():
                words.append(f"- [{event['ts'][:16].replace('T', ' ')}, to {chat.get('agent', '?')}] {event['text'].strip()}")
    return words


def _run(cmd: list[str], cwd: str) -> str | None:
    try:
        done = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return done.stdout if done.returncode == 0 else None


def _is_agent_commit(message: str) -> bool:
    return bool(re.search(r"^Agent:\s*\S+", message, re.M))


def _github(meta: dict) -> list[str]:
    """The pull request for the task's branch: the lead's commits (with diffs) and review comments."""
    project, branch = meta.get("project", ""), meta.get("branch", "")
    if not shutil.which("gh") or not project or not Path(project).exists() or not branch:
        return []
    listed = _run(["gh", "pr", "list", "--head", branch, "--state", "all", "--limit", "1",
                   "--json", "number,title,url,state,mergedAt"], project)
    prs = json.loads(listed) if listed else []
    if not prs:
        return []
    pr = prs[0]
    lines = [f"Pull request #{pr['number']} ({pr['state'].lower()}{', merged ' + pr['mergedAt'][:10] if pr.get('mergedAt') else ''}): {pr['url']}"]
    viewed = _run(["gh", "pr", "view", str(pr["number"]), "--json", "commits,reviews,comments"], project)
    data = json.loads(viewed) if viewed else {}
    lead_commits = [c for c in data.get("commits", [])
                    if not _is_agent_commit(c.get("messageHeadline", "") + "\n" + c.get("messageBody", ""))]
    if lead_commits:
        lines.append("\nCommits without an `Agent:` line (the lead's corrections, or agent commits from before the "
                     "`Agent:` line existed; check the message):")
        for commit in lead_commits:
            sha = commit["oid"]
            diff = _run(["git", "show", "--format=", "--patch", sha], project)
            if diff is None:
                api = _run(["gh", "api", f"repos/{{owner}}/{{repo}}/commits/{sha}"], project)
                files = json.loads(api).get("files", []) if api else []
                diff = "\n".join(f"--- {f['filename']}\n{f.get('patch', '')}" for f in files)
            lines += [f"- {sha[:9]} {commit.get('messageHeadline', '')}", "```diff", _clip(diff or "(diff unavailable)", LIMIT["diff"]), "```"]
    comments = _run(["gh", "api", f"repos/{{owner}}/{{repo}}/pulls/{pr['number']}/comments"], project)
    for comment in json.loads(comments) if comments else []:
        lines.append(f"- Review comment on `{comment.get('path')}:{comment.get('line') or comment.get('original_line')}`: "
                     f"{comment.get('body', '').strip()}")
    for review in data.get("reviews", []):
        if review.get("body", "").strip():
            lines.append(f"- Review ({review.get('state', '').lower()}): {review['body'].strip()}")
    for comment in data.get("comments", []):
        if comment.get("body", "").strip():
            lines.append(f"- Comment: {comment['body'].strip()}")
    return lines


def _local_commits(meta: dict) -> list[str]:
    """No pull request: the branch's commits without an `Agent:` line, compared with its base."""
    project, branch, base = meta.get("project", ""), meta.get("branch", ""), meta.get("base", "")
    if not (project and branch and base and Path(project).exists()):
        return []
    log = _run(["git", "log", f"{base}..{branch}", "--format=%H%x1f%s%x1f%B%x1e"], project)
    lines = []
    for record in (log or "").split("\x1e"):
        if not record.strip():
            continue
        sha, subject, message = record.strip().split("\x1f", 2)
        if not _is_agent_commit(message):
            diff = _run(["git", "show", "--format=", "--patch", sha], project) or ""
            lines += [f"- {sha[:9]} {subject}", "```diff", _clip(diff, LIMIT["diff"]), "```"]
    if lines:
        lines.insert(0, f"Commits on {branch} without an `Agent:` line (no pull request found):")
    return lines


def _task_evidence(path: Path, activity: list[dict], all_tasks: list[dict]) -> str:
    meta, text = parse(path), path.read_text(encoding="utf-8")
    tid = meta.get("id", path.name[:8])
    moves = [a for a in activity if a.get("id") == tid]
    rounds = sum(1 for a in moves if a.get("to") == "changes-requested")
    blocked = sum(1 for a in moves if a.get("to") == "blocked")
    follow_ups = [t["id"] for t in all_tasks if t.get("follows") == tid]
    head = [f"## {tid}: {meta.get('title', '')}  [{meta.get('status', '')}]",
            f"Project `{meta.get('project', '')}`, branch `{meta.get('branch', '')}` from `{meta.get('base', '')}`"
            + (f", follows {meta['follows']}" if meta.get("follows") else "")
            + (f", follow-ups: {', '.join(follow_ups)}" if follow_ups else ""),
            f"Review rounds sent back: {rounds}. Times blocked: {blocked}. "
            f"Tech Lead: {meta.get('techlead', '?')}, dev: {meta.get('dev') or '?'}, reviewer: {meta.get('reviewer') or '?'}."]
    parts = ["\n".join(head)]
    words = _lead_words(tid)
    if words:
        parts.append("### The lead's words in the conversations\n" + _clip("\n".join(words), LIMIT["words"]))
    for name, title in (("Clarifications", "Clarifications (the lead's answers)"), ("Open Questions", "Open questions"),
                        ("Review Report", "Review report"), ("Dev Log", "Dev log")):
        content = _section(text, name)
        if content:
            parts.append(f"### {title}\n" + _clip(content, LIMIT["section"]))
    code = _github(meta) or _local_commits(meta)
    parts.append("### The lead's changes to the agents' code\n" + ("\n".join(code) if code else
                 "None found (no pull request, or only `Agent:` commits)."))
    return "\n\n".join(parts)


def selected_tasks(since: str, ids: list[str], project: str) -> list[Path]:
    activity = _activity()
    if ids:
        chosen = [p for p in task_files() if p.name[:8] in ids]
    else:
        start = ""
        if since == "last":
            start = json.loads(STATE.read_text()).get("last_review", "") if STATE.exists() else ""
        elif since != "all":
            start = since
        touched = {a.get("id") for a in activity if a.get("ts", "") >= start}
        chosen = [p for p in task_files() if not start or p.name[:8] in touched]
    if project:
        root = str(Path(project).expanduser().resolve())
        chosen = [p for p in chosen if parse(p).get("project") == root]
    return sorted(chosen)


def evidence(since: str, ids: list[str], project: str) -> Path:
    paths = selected_tasks(since, ids, project)
    activity, all_tasks = _activity(), [parse(p) for p in task_files()]
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    run = RUNS / stamp
    run.mkdir(parents=True, exist_ok=True)
    rejected = [read_proposal(p) for p in sorted(PROPOSALS.glob("P-*.md"))] if PROPOSALS.exists() else []
    header = [f"# Evidence for the Coach, {stamp}",
              f"Tasks: {', '.join(p.name[:8] for p in paths) or 'none'}.",
              "Rejected proposals (don't propose these again unless the evidence is new): "
              + ("; ".join(f"{r['id']} {r['title']} ({r['note'] or 'no note'})" for r in rejected if r["status"] == "rejected") or "none") + "."]
    body = [_task_evidence(p, activity, all_tasks) for p in paths]
    path = run / "evidence.md"
    path.write_text("\n\n".join(["\n".join(header)] + body) + "\n", encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="The Coach's tools.")
    sub = parser.add_subparsers(dest="command", required=True)
    ev = sub.add_parser("evidence")
    ev.add_argument("--since", default="last")
    ev.add_argument("--tasks", default="")
    ev.add_argument("--project", default="")
    sub.add_parser("propose").add_argument("title")
    sub.add_parser("check").add_argument("id")
    sub.add_parser("done")
    args = parser.parse_args()
    if args.command == "evidence":
        ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        path = evidence(args.since, ids, args.project)
        print(path)
        print(path.read_text(encoding="utf-8").splitlines()[1])
    elif args.command == "propose":
        print(propose(args.title))
    elif args.command == "check":
        path = proposal_path(args.id)
        if not path:
            sys.exit(f"No proposal {args.id}.")
        found = problems(read_proposal(path))
        if found:
            sys.exit("\n".join(found))
        print(f"{args.id} is ready for the lead.")
    else:
        COACH.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps({"last_review": dt.datetime.now().isoformat(timespec="seconds")}))
        print("Review recorded. The next review (`--since last`) starts from now.")


if __name__ == "__main__":
    main()
