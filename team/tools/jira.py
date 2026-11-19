#!/usr/bin/env python3
"""Jira: read an issue, comment on it, move it.

    python3 jira.py issue <issue>                     the issue: summary, status, description, subtasks,
                                                     attachments and comments
    python3 jira.py attachments <issue>               download its attachments to data/uploads/jira-<KEY>/
                                                     (read them with files.py)
    python3 jira.py comment <issue> "<text>"          add a comment
    python3 jira.py status <issue> ["<status>"]       move it; without a status, list the moves it can make
    python3 jira.py whoami                            check the connection

An issue is its key (ABC-123) or its link (https://yours.atlassian.net/browse/ABC-123). Put it in the task's
`ticket:` field and Hive comments on it (and moves it, if the lead turned that on) as the task moves. Needs Jira
connected in Settings → Integrations (Jira Cloud: site, email and API token). Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connlib import ConnectorError, basic, quote, request, require, run  # noqa: E402


def parse(issue: str) -> str:
    m = re.search(r"\b([A-Z][A-Z0-9_]+-\d+)\b", issue.strip())
    if not m:
        raise ConnectorError(f"Not a Jira issue: {issue}. Use its key (ABC-123) or its link.")
    return m.group(1)


def site() -> str:
    url = require("jira")["site"].strip().rstrip("/")
    return url if url.startswith("http") else f"https://{url}"


def call(method: str, path: str, body=None, what: str = "Jira", raw: bool = False):
    cfg = require("jira")
    return request(method, f"{site()}{path}", {"Authorization": basic(cfg["email"], cfg["token"])}, body,
                   raw=raw, what=what)


def adf_text(node, depth: int = 0) -> str:
    """Atlassian Document Format (Jira's rich text) as plain Markdown-ish text."""
    if isinstance(node, str) or node is None:
        return node or ""
    kind, kids = node.get("type"), node.get("content") or []
    inner = "".join(adf_text(k, depth) for k in kids)
    if kind == "text":
        text = node.get("text", "")
        for mark in node.get("marks") or []:
            if mark.get("type") == "strong":
                text = f"**{text}**"
            elif mark.get("type") == "code":
                text = f"`{text}`"
            elif mark.get("type") == "link":
                text = f"[{text}]({mark.get('attrs', {}).get('href', '')})"
        return text
    if kind == "hardBreak":
        return "\n"
    if kind == "heading":
        return "#" * node.get("attrs", {}).get("level", 2) + " " + inner + "\n\n"
    if kind == "paragraph":
        return inner + "\n\n"
    if kind in ("bulletList", "orderedList"):
        out = ""
        for i, item in enumerate(kids, 1):
            body = "".join(adf_text(k, depth + 1) for k in item.get("content") or []).strip()
            out += "  " * depth + (f"{i}. " if kind == "orderedList" else "- ") + body + "\n"
        return out + ("\n" if depth == 0 else "")
    if kind == "codeBlock":
        return f"```{node.get('attrs', {}).get('language', '')}\n{inner}\n```\n\n"
    if kind == "blockquote":
        return "> " + inner.strip().replace("\n", "\n> ") + "\n\n"
    if kind == "table":
        rows = [["".join(adf_text(c) for c in cell.get("content") or []).strip().replace("\n", " ")
                 for cell in row.get("content") or []] for row in kids]
        if not rows:
            return ""
        out = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * len(rows[0])]
        out += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n".join(out) + "\n\n"
    if kind in ("mention", "emoji"):
        return node.get("attrs", {}).get("text", "")
    if kind == "inlineCard":
        return node.get("attrs", {}).get("url", "")
    if kind in ("mediaSingle", "mediaGroup", "media"):
        return "[attachment]" if kind == "media" else inner
    return inner


def adf(text: str) -> dict:
    return {"type": "doc", "version": 1,
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in text.split("\n\n") if p.strip()]}


FIELDS = "summary,status,issuetype,priority,assignee,reporter,labels,description,subtasks,parent,attachment,comment,duedate"


def get_issue(issue: str) -> dict:
    key = parse(issue)
    return call("GET", f"/rest/api/3/issue/{quote(key)}?fields={FIELDS}", what=f"Jira issue {key}")


def cmd_issue(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: jira.py issue <issue>")
    data = get_issue(args[0])
    f, key = data.get("fields") or {}, data.get("key")
    name = lambda x: (x or {}).get("displayName") or (x or {}).get("name") or ""
    print(f"# {key}: {f.get('summary')}")
    print(f"{name(f.get('issuetype'))} · Status: {name(f.get('status'))} · Priority: {name(f.get('priority'))}"
          + (f" · Assignee: {name(f.get('assignee'))}" if f.get("assignee") else "")
          + (f" · Reporter: {name(f.get('reporter'))}" if f.get("reporter") else "")
          + (f" · Due: {f['duedate']}" if f.get("duedate") else ""))
    print(f"Link: {site()}/browse/{key}")
    if f.get("parent"):
        print(f"Parent: {f['parent'].get('key')} {((f['parent'].get('fields') or {}).get('summary') or '')}")
    if f.get("labels"):
        print("Labels: " + ", ".join(f["labels"]))
    print("\n## Description\n")
    print(adf_text(f.get("description")).strip() or "(none)")
    if f.get("subtasks"):
        print("\n## Subtasks")
        for s in f["subtasks"]:
            print(f"- {s.get('key')} {(s.get('fields') or {}).get('summary', '')} ({name((s.get('fields') or {}).get('status'))})")
    if f.get("attachment"):
        print(f"\n## Attachments (download them with: jira.py attachments {key})")
        for a in f["attachment"]:
            print(f"- {a.get('filename')} ({a.get('mimeType', '')}, {a.get('size', 0) // 1024 or 1} KB)")
    comments = (f.get("comment") or {}).get("comments") or []
    if comments:
        print("\n## Comments (oldest first)")
        for c in comments:
            print(f"\n**{name(c.get('author'))}**, {(c.get('created') or '')[:16].replace('T', ' ')}:\n{adf_text(c.get('body')).strip()}")
    return 0


def cmd_attachments(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: jira.py attachments <issue>")
    from tasklib import DATA
    data = get_issue(args[0])
    files = (data.get("fields") or {}).get("attachment") or []
    if not files:
        print("This issue has no attachments.")
        return 0
    folder = DATA / "uploads" / f"jira-{data['key']}"
    folder.mkdir(parents=True, exist_ok=True)
    cfg = require("jira")
    for a in files:
        name = re.sub(r"[^\w.\- ]+", "_", a.get("filename", "file"))
        body = request("GET", a["content"], {"Authorization": basic(cfg["email"], cfg["token"])}, raw=True, what=name)
        (folder / name).write_bytes(body)
        print(folder / name)
    return 0


def comment(issue: str, text: str) -> None:
    key = parse(issue)
    call("POST", f"/rest/api/3/issue/{quote(key)}/comment", {"body": adf(text)}, "Jira comment")


def cmd_comment(args: list[str]) -> int:
    if len(args) < 2:
        raise ConnectorError('Usage: jira.py comment <issue> "<text>"')
    comment(args[0], args[1])
    print("Comment added.")
    return 0


def move(issue: str, status: str) -> str:
    key = parse(issue)
    moves = call("GET", f"/rest/api/3/issue/{quote(key)}/transitions", what="Jira transitions").get("transitions") or []
    want = status.lower()
    t = next((t for t in moves if t.get("name", "").lower() == want or (t.get("to") or {}).get("name", "").lower() == want), None)
    if not t:
        raise ConnectorError(f"{key} can't move to {status!r} from where it is. It can move to: "
                             + ", ".join(sorted({(t.get('to') or {}).get('name', t.get('name')) for t in moves})))
    call("POST", f"/rest/api/3/issue/{quote(key)}/transitions", {"transition": {"id": t["id"]}}, "Jira transition")
    return (t.get("to") or {}).get("name") or t.get("name")


def cmd_status(args: list[str]) -> int:
    if not args:
        raise ConnectorError('Usage: jira.py status <issue> ["<status>"]')
    if len(args) == 1:
        key = parse(args[0])
        f = get_issue(key).get("fields") or {}
        moves = call("GET", f"/rest/api/3/issue/{quote(key)}/transitions", what="Jira transitions").get("transitions") or []
        print(f"Now: {(f.get('status') or {}).get('name', '')}\nIt can move to: "
              + ", ".join(sorted({(t.get('to') or {}).get('name', t.get('name')) for t in moves})))
        return 0
    print(f"Moved to {move(args[0], args[1])}.")
    return 0


def cmd_whoami(_args: list[str]) -> int:
    me = call("GET", "/rest/api/3/myself")
    print(f"Connected to {site()} as {me.get('displayName', '')} ({me.get('emailAddress', '')})")
    return 0


def main(argv: list[str]) -> int:
    commands = {"issue": cmd_issue, "attachments": cmd_attachments, "comment": cmd_comment, "status": cmd_status,
                "whoami": cmd_whoami}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 0 if not argv else 1
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    run(main)
