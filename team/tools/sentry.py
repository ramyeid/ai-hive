#!/usr/bin/env python3
"""Sentry, read-only: what an error is, where it happens and what led to it.

    python3 sentry.py issue <issue>     the issue: title, how often and for whom, release and environment, then
                                       its latest event's stack trace (your code marked ▶), breadcrumbs and request
    python3 sentry.py whoami            check the connection

An issue is its link (https://yours.sentry.io/issues/4512345678/ or …/organizations/yours/issues/…) or its
numeric ID. Needs Sentry connected in Settings → Integrations (an auth token with event:read, project:read and
org:read; self-hosted Sentry: its URL too). Standard library only.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connlib import ConnectorError, request, require, run  # noqa: E402

FRAMES, CRUMBS = 25, 25


def parse(issue: str) -> tuple[str, str]:
    """(organization slug or "", issue id)."""
    issue = issue.strip()
    org = ""
    m = re.search(r"https?://([a-z0-9-]+)\.sentry\.io/", issue)
    if m and m.group(1) not in ("www", "us", "de"):
        org = m.group(1)
    m2 = re.search(r"/organizations/([^/]+)/", issue)
    if m2:
        org = m2.group(1)
    m3 = re.search(r"/issues/(\d+)", issue) or re.fullmatch(r"(\d+)", issue)
    if not m3:
        raise ConnectorError(f"Not a Sentry issue: {issue}. Use its link or its numeric ID.")
    return org, m3.group(1)


def base() -> str:
    return (require("sentry").get("url") or "https://sentry.io").rstrip("/")


def call(path: str, what: str = "Sentry"):
    cfg = require("sentry")
    return request("GET", f"{base()}/api/0{path}", {"Authorization": f"Bearer {cfg['token']}"}, what=what)


def cmd_issue(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: sentry.py issue <issue>")
    org, iid = parse(args[0])
    prefix = f"/organizations/{org}/issues/{iid}" if org else f"/issues/{iid}"
    i = call(prefix + "/", f"Sentry issue {iid}")
    print(f"# {i.get('title')}")
    print(f"{i.get('level', '')} · {i.get('status', '')} · {i.get('count', '?')} events, {i.get('userCount', '?')} users"
          f" · first seen {(i.get('firstSeen') or '')[:16].replace('T', ' ')}, last seen {(i.get('lastSeen') or '')[:16].replace('T', ' ')}")
    print(f"Where: {i.get('culprit', '')} · Project: {(i.get('project') or {}).get('slug', '')}")
    print(f"Link: {i.get('permalink', '')}")
    e = call(prefix + "/events/latest/", "Sentry latest event")
    tags = {t.get("key"): t.get("value") for t in e.get("tags") or []}
    keep = [k for k in ("release", "environment", "browser", "os", "runtime", "url", "transaction", "server_name") if tags.get(k)]
    if keep:
        print("Latest event: " + " · ".join(f"{k} {tags[k]}" for k in keep))
    for entry in e.get("entries") or []:
        kind, data = entry.get("type"), entry.get("data") or {}
        if kind == "exception":
            for value in data.get("values") or []:
                print(f"\n## {value.get('type')}: {value.get('value', '')}")
                frames = ((value.get("stacktrace") or {}).get("frames") or [])[-FRAMES:]
                for f in reversed(frames):   # the innermost call first, like Sentry shows it
                    mark = "▶" if f.get("inApp") else " "
                    print(f"{mark} {f.get('filename') or f.get('module') or '?'}:{f.get('lineNo', '?')} in {f.get('function') or '?'}")
                    for no, line in f.get("context") or []:
                        if no == f.get("lineNo"):
                            print(f"      {line.strip()}")
        elif kind == "breadcrumbs":
            crumbs = (data.get("values") or [])[-CRUMBS:]
            if crumbs:
                print("\n## Breadcrumbs (what happened before, oldest first)")
                for b in crumbs:
                    msg = b.get("message") or " ".join(f"{k}={v}" for k, v in (b.get("data") or {}).items())[:200]
                    print(f"- {(b.get('timestamp') or '')[11:19]} [{b.get('category', '')}] {b.get('level', '')} {msg}".rstrip())
        elif kind == "request":
            print(f"\n## Request\n{data.get('method', '')} {data.get('url', '')}")
        elif kind == "message":
            print(f"\n## Message\n{data.get('formatted') or data.get('message', '')}")
    return 0


def cmd_whoami(_args: list[str]) -> int:
    orgs = call("/organizations/", "Sentry")
    print(f"Connected to {base()} · organizations: " + (", ".join(o.get("slug", "") for o in orgs) or "none visible"))
    return 0


def main(argv: list[str]) -> int:
    commands = {"issue": cmd_issue, "whoami": cmd_whoami}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 0 if not argv else 1
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    run(main)
