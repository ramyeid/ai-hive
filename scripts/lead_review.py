#!/usr/bin/env python3
"""The lead's own code reviews: the diff of a task's branch, line comments, and review rounds.

The lead reviews in the console, like a pull request: comments on lines of the diff, then submits
"Request changes" (the task goes back to the dev who built it) or "Approve" (nothing moves; the
reviewer stays the last step before done). The lead can review at any point and as often as needed.

- Comments and rounds are kept in tasks/reviews/TASK-NNN.json (drafts too, so nothing is lost).
- Each submitted round is appended to the task file under "## Lead Review", which is what the agents
  read. The dev answers each comment on its "- Reply:" line; replies are read back from the task file.

Usage: python3 scripts/lead_review.py show TASK-012      (the rounds and replies, as the agents see them)
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

from tasklib import TASKS, find_task, lock, parse, set_fields

REVIEWS = TASKS / "reviews"
SECTION = "## Lead Review"
SECTION_NOTE = ("<!-- The lead's code reviews, added by the console. Never edit the comments. dev: answer every comment\n"
                "     of the newest round on its \"- Reply:\" line: `Fixed in <commit>: what changed`, or `Not changed: why`. -->")
CHANGES_FROM = {"ready-for-review", "changes-requested", "done"}   # where "Request changes" can send a task back from
BUSY = {"in-dev": "the dev is working on it", "in-review": "the reviewer is reviewing it"}
MODES = ("feature", "task", "since")


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

def _git(project: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", project, *args], capture_output=True, text=True)


def _exists(project: str, ref: str) -> bool:
    return _git(project, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def base_ref(meta: dict) -> str:
    """The base branch as the lead named it, or origin's copy if it only exists there."""
    base, project = meta.get("base") or "main", meta.get("project", "")
    return base if _exists(project, base) or not _exists(project, f"origin/{base}") else f"origin/{base}"


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
    if mode == "task" and meta.get("from_commit"):
        return f"{meta['from_commit']}..{branch}", f"this task's commits (from `{meta['from_commit']}`)"
    base = base_ref(meta)
    return f"{base}...{branch}", f"the whole feature against `{base}`"


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
    """What the lead looks at: the branch's diff, the rounds so far and the drafts."""
    _, meta = _task(task_id)
    data = load(task_id)
    last = data["rounds"][-1]["commit"] if data["rounds"] else ""
    result = {"task": task_id, "status": meta.get("status", ""), "branch": meta.get("branch", ""),
              "base": meta.get("base", ""), "dev": meta.get("dev", ""), "reviewer": meta.get("reviewer", ""),
              "mode": mode, "head": head(meta), "last_reviewed": last, "files": [], "range": "", "describes": "",
              "rounds": rounds(task_id), "pending": data["pending"], "can_request_changes": can_request_changes(meta)}
    if not result["head"]:
        result["describes"] = "There's no code yet: the branch is created when a dev claims the task."
        return result
    rng, result["describes"] = _range(meta, mode if mode in MODES else "feature", last)
    done = _git(meta["project"], "diff", "--no-color", "--no-ext-diff", "-M", "-U3", rng)
    if done.returncode != 0:
        raise ReviewError(f"git diff {rng} failed: {done.stderr.strip()}")
    result["range"], result["files"] = rng, parse_diff(done.stdout)
    return result


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
    _task(task_id)
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
    with lock():
        data = load(task_id)
        found = next((c for c in data["pending"] if c["id"] == comment_id), None)
        if not found:
            raise KeyError(comment_id)
        found["body"] = body.strip()
        _save(task_id, data)


def delete_comment(task_id: str, comment_id: str) -> None:
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


def submit(task_id: str, verdict: str, summary: str = "", mode: str = "feature") -> dict:
    """Turn the drafts into a round. verdict: 'changes' sends the task back to its dev; 'approve' moves nothing."""
    if verdict not in ("changes", "approve"):
        raise ReviewError("A review is either 'changes' or 'approve'.")
    import claim            # noqa: E402  (imported here: claim imports the hook, which imports this module's neighbours)
    import on_task_change   # noqa: E402
    path, meta = _task(task_id)
    with lock():
        meta = parse(path)
        data = load(task_id)
        if verdict == "changes":
            why_not = can_request_changes(meta)
            if why_not:
                raise ReviewError(why_not)
            if not data["pending"] and not summary.strip():
                raise ReviewError("Add at least one comment, or a summary, so the dev knows what to change.")
            if (other := claim.busy_with(meta)):
                raise ReviewError(f"{other['id']} is on the same branch and still `{other['status']}`. "
                                  f"Review it there, or wait until it's done.")
        commit = head(meta)
        if not commit:
            raise ReviewError("There's no code to review yet.")
        last = data["rounds"][-1]["commit"] if data["rounds"] else ""
        _, describes = _range(meta, mode, last)
        r = {"n": len(data["rounds"]) + 1, "at": dt.datetime.now().isoformat(timespec="seconds"), "verdict": verdict,
             "commit": commit, "describes": describes, "summary": summary.strip(), "status_before": meta.get("status", ""),
             # in reading order: by file and line, general comments last
             "comments": sorted(data["pending"], key=lambda c: (not c.get("file"), c.get("file", ""), c.get("line") or 0))}
        data["rounds"].append(r)
        data["pending"] = []
        _save(task_id, data)
        _append_round(path, round_markdown(r, meta))
        if verdict == "changes":
            set_fields(path, status="changes-requested")
            on_task_change.process(path, actor="lead")
    return {**r, "dev": meta.get("dev", "")}


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


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] != "show":
        sys.exit("usage: lead_review.py show TASK-NNN")
    for r in rounds(sys.argv[2]):
        print(f"Round {r['n']} ({r['verdict']}) at {r['commit'][:7]}:")
        for c in r["comments"]:
            print(f"  {c['number']}. {_where(c)}: {c['body']}\n     reply: {c['reply'] or '(none yet)'}")


if __name__ == "__main__":
    main()
