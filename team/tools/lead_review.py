#!/usr/bin/env python3
"""The lead's own code reviews: the diff of a feature branch, line comments, and review rounds.

The lead reviews a branch in the console, like a pull request: comments on lines of the diff, then submits
"Request changes" (the task goes back to the dev who built it) or "Approve" (nothing moves; the
reviewer stays the last step before done). The lead can review at any point and as often as needed.

Reviews are per branch: follow-up tasks add commits to the same branch, one at a time. Opening the review
from any of its tasks shows the whole branch and every round on it; drafts and new rounds go to the branch's
current task (the one its dev is on, or the newest), which is the file that dev reads.

- Comments and rounds are kept in data/tasks/reviews/TASK-NNN.json (drafts too, so nothing is lost).
- Each submitted round is appended to the task file under "## Lead Review", which is what the agents
  read. The dev answers each comment on its "- Reply:" line; replies are read back from the task file.

Usage: python3 team/tools/lead_review.py show TASK-012      (the rounds and replies, as the agents see them)
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from tasklib import TASKS, find_task, freshest_base, lock, parse, set_fields, task_files

REVIEWS = TASKS / "reviews"
SECTION = "## Lead Review"
SECTION_NOTE = ("<!-- The lead's code reviews, added by the console. Never edit the comments. dev: answer every comment\n"
                "     of the newest round on its \"- Reply:\" line: `Fixed in <commit>: what changed`, or `Not changed: why`. -->")
CHANGES_FROM = {"ready-for-review", "changes-requested", "done"}   # where "Request changes" can send a task back from
BUSY = {"in-dev": "the dev is working on it", "in-review": "the reviewer is reviewing it"}
MODES = ("feature", "since")   # the whole branch against its base, or what changed since your last review
ACTIVE = ("in-dev", "changes-requested", "ready-for-review", "in-review", "blocked")


class ReviewError(Exception):
    """Something the lead needs to know (shown as is)."""


# ---- storage ----------------------------------------------------------------------------

def _path(task_id: str) -> Path:
    return REVIEWS / f"{task_id}.json"


def load(task_id: str) -> dict:
    try:
        data = json.loads(_path(task_id).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return {"rounds": data.get("rounds", []), "pending": data.get("pending", []), "next": data.get("next", 1)}


def _save(task_id: str, data: dict) -> None:
    REVIEWS.mkdir(parents=True, exist_ok=True)
    _path(task_id).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _task(task_id: str) -> tuple[Path, dict]:
    path = find_task(task_id)
    if not path:
        raise KeyError(task_id)
    return path, parse(path)


# ---- git --------------------------------------------------------------------------------

def on_branch(meta: dict) -> list[dict]:
    """Every task on the same project and branch, oldest first."""
    if not meta.get("branch"):
        return [meta]
    same = [m for m in map(parse, task_files())
            if m.get("project") == meta.get("project") and m.get("branch") == meta.get("branch")]
    return sorted(same, key=lambda m: int(re.sub(r"\D", "", m.get("id", "0")) or 0)) or [meta]


def current_task(task_id: str) -> str:
    """The task a review of this branch goes to: the one on the branch that's in progress, else the newest one a
    dev has built (rework goes back to its dev), else the task itself."""
    _, meta = _task(task_id)
    tasks = on_branch(meta)
    active = [m for m in tasks if m.get("status") in ACTIVE]
    built = [m for m in tasks if m.get("dev")]
    return (active or built or [meta])[-1].get("id") or task_id


def _adopt_drafts(task_id: str, meta: dict) -> None:
    """Drafts left on an earlier task of the branch (written before a follow-up took it over) move to the current
    task, so they're not lost."""
    for other in on_branch(meta):
        if other.get("id") in (task_id, None) or not load(other["id"])["pending"]:
            continue
        with lock():
            theirs, ours = load(other["id"]), load(task_id)
            for c in theirs["pending"]:
                ours["pending"].append({**c, "id": f"c{ours['next']}"})
                ours["next"] += 1
            theirs["pending"] = []
            _save(task_id, ours)
            _save(other["id"], theirs)


def branch_rounds(meta: dict) -> list[dict]:
    """Every round on the branch, whichever task it was submitted on, oldest first; each says its task."""
    found = [{**r, "task": m["id"]} for m in on_branch(meta) for r in rounds(m["id"])]
    return sorted(found, key=lambda r: r["at"])


def _git(project: str, *args: str) -> subprocess.CompletedProcess:
    # core.quotePath off: file names with accents or in other scripts come as they are, not as "\330\257…"
    return subprocess.run(["git", "-C", project, "-c", "core.quotePath=false", *args], capture_output=True, text=True)


def _exists(project: str, ref: str) -> bool:
    return _git(project, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def base_ref(meta: dict) -> str:
    """The base to compare against: the one the branch started from (origin's copy when it's newer than the local
    one, since the lead merges on GitHub), so the diff shows only the branch's own changes."""
    base = meta.get("base") or "main"
    return freshest_base(meta.get("project", ""), base) or base


def head(meta: dict) -> str:
    """The branch's newest commit ('' while the branch doesn't exist yet)."""
    if not meta.get("branch") or not Path(meta.get("project", "")).is_dir():
        return ""
    done = _git(meta["project"], "rev-parse", "--verify", "--quiet", f"{meta['branch']}^{{commit}}")
    return done.stdout.strip() if done.returncode == 0 else ""


def _range(meta: dict, mode: str, last: str) -> tuple[str, str]:
    """The git range for each view, and its description."""
    branch = meta["branch"]
    if mode == "since" and last and _git(meta["project"], "merge-base", "--is-ancestor", last, branch).returncode == 0:
        return f"{last}..{branch}", f"what changed since your last review (`{last[:7]}`)"
    base = base_ref(meta)
    return f"{base}...{branch}", f"the whole branch against `{base}`"


_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$")


def parse_diff(patch: str) -> list[dict]:
    """A unified diff as files → hunks → lines, each line with its old and new line numbers."""
    files, current, hunk, old, new = [], None, None, 0, 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            m = re.match(r"diff --git a/(.+?) b/(.+)$", line)
            current = {"path": m.group(2) if m else line, "old_path": m.group(1) if m else "", "status": "modified",
                       "binary": False, "additions": 0, "deletions": 0, "hunks": []}
            files.append(current)
            hunk = None
        elif current is None:
            continue
        elif hunk is None and line.startswith("new file mode"):
            current["status"] = "added"
        elif hunk is None and line.startswith("deleted file mode"):
            current["status"] = "deleted"
        elif hunk is None and line.startswith("rename from "):
            current["status"] = "renamed"
        elif hunk is None and line.startswith("Binary files "):
            current["binary"] = True
        elif (m := _HUNK.match(line)):
            old, new = int(m.group(1)), int(m.group(2))
            hunk = {"header": line, "lines": []}
            current["hunks"].append(hunk)
        elif hunk is not None and line[:1] in ("+", "-", " ") and not line.startswith(("+++ ", "--- ")):
            kind = line[:1]
            entry = {"t": kind, "o": old if kind != "+" else None, "n": new if kind != "-" else None, "s": line[1:]}
            hunk["lines"].append(entry)
            if kind != "+":
                old += 1
            if kind != "-":
                new += 1
            if kind == "+":
                current["additions"] += 1
            elif kind == "-":
                current["deletions"] += 1
    return files


def diff(task_id: str, mode: str = "feature") -> dict:
    """What the lead looks at: the branch's diff, every round on the branch and the drafts. `task` is the task the
    review goes to (the branch's current one), `opened` the one the lead opened it from."""
    opened, task_id = task_id, current_task(task_id)
    _, meta = _task(task_id)
    _adopt_drafts(task_id, meta)
    data = load(task_id)
    all_rounds = branch_rounds(meta)
    last = all_rounds[-1]["commit"] if all_rounds else ""
    result = {"task": task_id, "opened": opened, "status": meta.get("status", ""), "branch": meta.get("branch", ""),
              "base": meta.get("base", ""), "dev": meta.get("dev", ""), "reviewer": meta.get("reviewer", ""),
              "mode": mode if mode in MODES else "feature", "head": head(meta), "last_reviewed": last, "files": [],
              "range": "", "describes": "", "rounds": all_rounds, "pending": data["pending"],
              "can_request_changes": can_request_changes(meta), **code_folder(meta)}
    if not result["head"]:
        result["describes"] = "There's no code yet: the branch is created when a dev claims the task."
        return result
    rng, result["describes"] = _range(meta, mode if mode in MODES else "feature", last)
    done = _git(meta["project"], "diff", "--no-color", "--no-ext-diff", "-M", "-U3", rng)
    if done.returncode != 0:
        raise ReviewError(f"git diff {rng} failed: {done.stderr.strip()}")
    result["range"], result["files"] = rng, _with_viewed(meta, parse_diff(done.stdout))
    return result


SOURCE_LIMIT = 2_000_000   # bytes: a bigger file isn't expanded


def source(task_id: str, rev: str, path: str) -> list[str]:
    """A file's lines at a commit of the task's branch, for expanding the unchanged lines around a change (like
    GitHub). rev is the commit the diff shows (its head)."""
    if not re.fullmatch(r"[0-9a-f]{7,40}", rev or ""):
        raise ReviewError("That isn't a commit.")
    _, meta = _task(current_task(task_id))
    if not Path(meta.get("project", "")).is_dir():
        raise ReviewError("The project folder isn't there.")
    size = _git(meta["project"], "cat-file", "-s", f"{rev}:{path}")
    if size.returncode != 0:
        raise ReviewError(f"{path} isn't in {rev[:7]}.")
    if int(size.stdout.strip() or 0) > SOURCE_LIMIT:
        raise ReviewError(f"{path} is too big to expand here: open it in the editor.")
    shown = subprocess.run(["git", "-C", meta["project"], "show", f"{rev}:{path}"], capture_output=True)
    return shown.stdout.decode("utf-8", errors="replace").splitlines()


# ---- files the lead marked as viewed (per branch, like GitHub) ---------------------------

def _viewed_file(meta: dict) -> Path:
    key = hashlib.sha1(f"{meta.get('project', '')}\0{meta.get('branch', '')}".encode()).hexdigest()[:16]
    return REVIEWS / "viewed" / f"{key}.json"


def _viewed(meta: dict) -> dict[str, str]:
    """{path: the file's blob when the lead marked it viewed}."""
    try:
        return json.loads(_viewed_file(meta).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _blobs(meta: dict, paths: list[str], rev: str = "") -> dict[str, str]:
    """Each file's blob at `rev` (the branch's head by default; 'deleted' for a file that isn't there): what "viewed"
    is tied to. -z: names with accents or other scripts come raw, not quoted, so they match."""
    out = {p: "deleted" for p in paths}
    if paths:
        listed = _git(meta["project"], "ls-tree", "-z", rev or meta["branch"], "--", *paths).stdout
        for entry in listed.split("\0"):
            info, _, path = entry.partition("\t")
            if path:
                out[path] = info.split()[2]
    return out


def mark_viewed(task_id: str, path: str, viewed: bool = True, at: str = "") -> dict:
    """Mark a file viewed (or not) as the lead saw it: at the commit the page showed (`at`), not at whatever the
    branch has now; so a change the dev made meanwhile shows the file as not viewed. It's unviewed again whenever
    the file changes."""
    if at and not re.fullmatch(r"[0-9a-f]{7,40}", at):
        raise ReviewError("That isn't a commit.")
    _, meta = _task(current_task(task_id))
    with lock():
        seen = _viewed(meta)
        if viewed:
            seen[path] = _blobs(meta, [path], at)[path]
        else:
            seen.pop(path, None)
        _viewed_file(meta).parent.mkdir(parents=True, exist_ok=True)
        _viewed_file(meta).write_text(json.dumps(seen, indent=2), encoding="utf-8")
    return {"path": path, "viewed": viewed}


def _with_viewed(meta: dict, files: list[dict]) -> list[dict]:
    seen, blobs = _viewed(meta), _blobs(meta, [f["path"] for f in files])
    for f in files:
        was = seen.get(f["path"])
        f["viewed"] = bool(was) and was == blobs[f["path"]]
        f["changed_since_viewed"] = bool(was) and was != blobs[f["path"]]
    return files


def code_folder(meta: dict) -> dict:
    """Where to open the branch's code in an editor: its worktree, or the project folder (which may be on another
    branch) once the worktree is removed."""
    worktree = meta.get("worktree", "")
    if worktree and Path(worktree).is_dir():
        return {"folder": worktree, "folder_on_branch": True}
    return {"folder": meta.get("project", ""), "folder_on_branch": False}


def can_request_changes(meta: dict) -> str:
    """'' when the lead can send the task back now, else why not."""
    status = meta.get("status", "")
    if status in BUSY:
        return f"Right now {BUSY[status]}. Your comments are kept: submit them when it hands off."
    if status not in CHANGES_FROM:
        return "There's nothing to send back yet." if status in ("draft", "ready-for-dev") else f"The task is `{status}`."
    if not meta.get("dev"):
        return "No dev has built it yet."
    return ""


# ---- comments and rounds ----------------------------------------------------------------

def add_comment(task_id: str, body: str, file: str = "", line: int | None = None, side: str = "new", code: str = "") -> dict:
    task_id = current_task(task_id)
    if not body.strip():
        raise ReviewError("The comment is empty.")
    with lock():
        data = load(task_id)
        code = "\n".join(code.splitlines()).strip("\n")   # no blank lines around the snippet; keep its indentation
        while code and not code.splitlines()[0].strip():
            code = code.split("\n", 1)[1] if "\n" in code else ""
        comment = {"id": f"c{data['next']}", "file": file, "line": line, "side": "old" if side == "old" else "new",
                   "code": code.rstrip(), "body": body.strip()}
        data["pending"].append(comment)
        data["next"] += 1
        _save(task_id, data)
    return comment


def edit_comment(task_id: str, comment_id: str, body: str) -> None:
    task_id = current_task(task_id)
    with lock():
        data = load(task_id)
        found = next((c for c in data["pending"] if c["id"] == comment_id), None)
        if not found:
            raise KeyError(comment_id)
        found["body"] = body.strip()
        _save(task_id, data)


def delete_comment(task_id: str, comment_id: str) -> None:
    task_id = current_task(task_id)
    with lock():
        data = load(task_id)
        data["pending"] = [c for c in data["pending"] if c["id"] != comment_id]
        _save(task_id, data)


def _where(c: dict) -> str:
    if not c.get("file"):
        return "General"
    if not c.get("line"):
        return f"`{c['file']}`"
    return f"`{c['file']}:{c['line']}`" if c.get("side") != "old" else f"`{c['file']}` (removed line {c['line']})"


def _indent(text: str, spaces: int = 3) -> str:
    return "\n".join((" " * spaces + line) if line.strip() else "" for line in text.splitlines())


def round_markdown(r: dict, meta: dict) -> str:
    verdict = "changes requested" if r["verdict"] == "changes" else "approved"
    lines = [f"### Round {r['n']} — {r['at'].replace('T', ' ')[:16]} — {verdict}",
             f"At `{r['commit'][:7]}` on `{meta.get('branch', '')}`, reviewing {r['describes']}.", ""]
    if r.get("summary"):
        lines += [r["summary"], ""]
    for i, c in enumerate(r["comments"], 1):
        lines.append(f"{i}. {_where(c)}")
        if c.get("code"):
            lines += ["   ```", _indent(c["code"]), "   ```"]
        lines.append(_indent(c["body"]))
        if r["verdict"] == "changes":
            lines.append("   - Reply:")
    return "\n".join(lines).rstrip() + "\n"


def _append_round(path: Path, markdown: str) -> None:
    text = path.read_text(encoding="utf-8").rstrip("\n") + "\n"
    if f"\n{SECTION}\n" not in f"\n{text}":
        text += f"\n{SECTION}\n{SECTION_NOTE}\n"
    path.write_text(text + "\n" + markdown, encoding="utf-8")


def submit(task_id: str, verdict: str, comment: str = "", mode: str = "feature") -> dict:
    """Turn the drafts into a round. verdict: 'changes' sends the task back to its dev; 'approve' moves nothing.
    comment: a general comment written with the review; it's numbered with the others, so the dev answers it."""
    if verdict not in ("changes", "approve"):
        raise ReviewError("A review is either 'changes' or 'approve'.")
    import claim            # noqa: E402  (imported here: claim imports the hook, which imports this module's neighbours)
    import on_task_change   # noqa: E402
    task_id = current_task(task_id)
    path, meta = _task(task_id)
    with lock():
        meta = parse(path)
        data = load(task_id)
        if verdict == "changes":
            why_not = can_request_changes(meta)
            if why_not:
                raise ReviewError(why_not)
            if not data["pending"] and not comment.strip():
                raise ReviewError("Add at least one comment so the dev knows what to change.")
            if (other := claim.busy_with(meta)):
                raise ReviewError(f"{other['id']} is on the same branch and still `{other['status']}`. "
                                  f"Review it there, or wait until it's done.")
        commit = head(meta)
        if not commit:
            raise ReviewError("There's no code to review yet.")
        if comment.strip():
            data["pending"].append({"id": f"c{data['next']}", "file": "", "line": None, "side": "new", "code": "",
                                    "body": comment.strip()})
            data["next"] += 1
        on_branch_so_far = branch_rounds(meta)
        last = on_branch_so_far[-1]["commit"] if on_branch_so_far else ""
        _, describes = _range(meta, mode if mode in MODES else "feature", last)
        r = {"n": len(data["rounds"]) + 1, "at": dt.datetime.now().isoformat(timespec="seconds"), "verdict": verdict,
             "commit": commit, "describes": describes, "status_before": meta.get("status", ""),
             # in reading order: by file and line, general comments last
             "comments": sorted(data["pending"], key=lambda c: (not c.get("file"), c.get("file", ""), c.get("line") or 0))}
        data["rounds"].append(r)
        data["pending"] = []
        _save(task_id, data)
        _append_round(path, round_markdown(r, meta))
        if verdict == "changes":
            set_fields(path, status="changes-requested")
            on_task_change.process(path, actor="lead")
    return {**r, "dev": meta.get("dev", ""), "task": task_id}


# ---- reading back (with the dev's replies) ----------------------------------------------

def _section_text(text: str) -> str:
    m = re.search(rf"^{re.escape(SECTION)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def replies(text: str) -> dict[int, dict[int, str]]:
    """{round: {comment number: reply}} from the task file's Lead Review section."""
    found: dict[int, dict[int, str]] = {}
    for block in re.split(r"^(?=### Round \d+)", _section_text(text), flags=re.M):
        m = re.match(r"### Round (\d+)", block)
        if not m:
            continue
        n, number, answers = int(m.group(1)), None, {}
        lines = block.splitlines()
        for i, line in enumerate(lines):
            item = re.match(r"^(\d+)\. ", line)
            if item:
                number = int(item.group(1))
                continue
            reply = re.match(r"^\s+- Reply:[ \t]*(.*)$", line)
            if reply and number is not None:
                more = []
                for follow in lines[i + 1:]:
                    if not follow.startswith("     ") or not follow.strip():
                        break
                    more.append(follow.strip())
                answers[number] = " ".join([reply.group(1).strip(), *more]).strip()
        found[n] = answers
    return found


def rounds(task_id: str) -> list[dict]:
    """Every submitted round, newest last, each comment with the dev's reply ('' if none yet)."""
    path = find_task(task_id)
    answers = replies(path.read_text(encoding="utf-8")) if path else {}
    out = []
    for r in load(task_id)["rounds"]:
        got = answers.get(r["n"], {})
        out.append({**r, "comments": [{**c, "number": i, "reply": got.get(i, "")} for i, c in enumerate(r["comments"], 1)]})
    return out


# ---- every feature branch, for the Reviews page ------------------------------------------

OPEN = ("ready-for-review", "in-review")
_sizes: dict[tuple[str, str], dict] = {}   # (project, head commit) -> files and lines changed; a commit never changes


def _size(meta: dict, commit: str) -> dict:
    key = (meta["project"], commit)
    if key not in _sizes:
        stat = _git(meta["project"], "diff", "--shortstat", f"{base_ref(meta)}...{commit}").stdout
        numbers = {k: int(n) for n, k in re.findall(r"(\d+) (file|insertion|deletion)", stat)}
        _sizes[key] = {"files": numbers.get("file", 0), "additions": numbers.get("insertion", 0),
                       "deletions": numbers.get("deletion", 0)}
    return _sizes[key]


def branches() -> list[dict]:
    """One row per feature branch: its tasks, who has it, where the lead's review stands and how big it is.
    state: open (ready for review or being reviewed), draft (the dev is still on it) or done (every task done).
    needs_you: open, and new since the lead's last review (or never reviewed). Those come first."""
    import land   # noqa: E402  (land imports this module)
    landed = {(r.get("project"), r.get("branch")): r for r in land.records()}
    groups: dict[tuple[str, str], list[dict]] = {}
    for meta in map(parse, task_files()):
        if meta.get("branch") and meta.get("project"):
            groups.setdefault((meta["project"], meta["branch"]), []).append(meta)
    out = []
    for (project, branch), tasks in groups.items():
        tasks.sort(key=lambda m: int(re.sub(r"\D", "", m.get("id", "0")) or 0))
        active = [m for m in tasks if m.get("status") in ACTIVE]
        current = (active or [m for m in tasks if m.get("dev")] or tasks)[-1]
        status = current.get("status", "")
        state = "done" if all(m.get("status") == "done" for m in tasks) else "open" if status in OPEN else "draft"
        commit = head(current)
        reviewed = branch_rounds(current)
        last = reviewed[-1] if reviewed else None
        needs_you = state == "open" and bool(commit) and (not last or last["commit"] != commit)
        your_review = ("new" if last and needs_you else "none" if not last
                       else "approved" if last["verdict"] == "approve" else "changes")
        files = [find_task(m["id"]) for m in tasks]
        updated = max((f.stat().st_mtime for f in files if f), default=0)
        out.append({
            "branch": branch, "project": project, "project_name": Path(project).name,
            "title": tasks[0].get("title", ""), "tasks": [{"id": m["id"], "title": m.get("title", ""), "status": m.get("status", "")} for m in tasks],
            "task": current["id"], "status": status, "dev": current.get("dev", ""), "reviewer": current.get("reviewer", ""),
            "state": state, "needs_you": needs_you, "your_review": your_review, "head": commit,
            "updated": dt.datetime.fromtimestamp(updated).isoformat(timespec="seconds") if updated else "",
            "size": _size(current, commit) if commit and state != "done" else None,
            "pr": landed.get((project, branch), {}).get("pr_url", ""),
            "merged": bool(landed.get((project, branch), {}).get("merged_at")),
        })
    out.sort(key=lambda b: b["updated"], reverse=True)       # newest first,
    return sorted(out, key=lambda b: not b["needs_you"])     # and what needs the lead before the rest


def all_reviewed() -> dict[str, dict]:
    """Per task: how many rounds the lead submitted and the commit last reviewed (for lists)."""
    out = {}
    if REVIEWS.exists():
        for p in REVIEWS.glob("TASK-*.json"):
            data = load(p.stem)
            if data["rounds"] or data["pending"]:
                out[p.stem] = {"rounds": len(data["rounds"]), "last": data["rounds"][-1]["commit"] if data["rounds"] else "",
                               "drafts": len(data["pending"])}
    return out


def checklist(meta: dict) -> str:
    """Every comment the lead has made on the branch, in every round and on every task of it, oldest first, with the
    dev's reply. They all still hold: printed for the dev and the reviewer each time they take a task on the branch
    ('' when the lead hasn't reviewed the branch)."""
    found = [r for r in branch_rounds(meta) if r["verdict"] == "changes" or r["comments"]]
    if not found:
        return ""
    total = sum(len(r["comments"]) for r in found)
    several = len({r["task"] for r in found}) > 1
    lines = [f"The lead's comments on this branch: {plural(len(found), 'round')}, {plural(total, 'comment')}. "
             "Every one still holds, not only the newest round: whatever you change, the feature's whole diff "
             f"(git diff {meta.get('base') or 'main'}...HEAD) must follow them all, and none may come back."]
    for n, r in enumerate(found, 1):
        lines.append(f"Round {n}{' (on ' + r['task'] + ')' if several else ''}, "
                     f"{r['at'][:10]}, {'changes requested' if r['verdict'] == 'changes' else 'approved'}:")
        if r.get("summary"):
            lines.append(f"  {r['summary'].strip()}")
        for c in r["comments"]:
            body = " ".join(c["body"].split())
            lines.append(f"  {n}.{c['number']} {_where(c)}: {body}")
            lines.append(f"       reply: {' '.join(c['reply'].split()) or '(none yet)'}")
    return "\n".join(lines)


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def main() -> None:
    if len(sys.argv) == 3 and sys.argv[1] == "checklist":
        path = find_task(sys.argv[2])
        if not path:
            sys.exit(f"No task {sys.argv[2]} on the board.")
        print(checklist(parse(path)) or "The lead hasn't reviewed this branch.")
        return
    if len(sys.argv) != 3 or sys.argv[1] != "show":
        sys.exit("usage: lead_review.py show TASK-NNN | lead_review.py checklist TASK-NNN")
    for r in rounds(sys.argv[2]):
        print(f"Round {r['n']} ({r['verdict']}) at {r['commit'][:7]}:")
        for c in r["comments"]:
            print(f"  {c['number']}. {_where(c)}: {c['body']}\n     reply: {c['reply'] or '(none yet)'}")


if __name__ == "__main__":
    main()
