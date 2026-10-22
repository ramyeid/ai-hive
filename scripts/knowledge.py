#!/usr/bin/env python3
"""The Tech Lead's memory of each service: knowledge/<service>.md (local, never committed).

Usage:
  python3 scripts/knowledge.py status <project-folder> [ref]   what's known, and what changed since
  python3 scripts/knowledge.py new <project-folder>            create the file from the template
  python3 scripts/knowledge.py stamp <project-folder> [ref]    record that the file now describes ref (default HEAD)

How to trust it: the file records the commit it describes. `status` lists the files changed in the
project since that commit, and which sections mention them: everything else can be trusted as is.
"""
from __future__ import annotations

import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

from tasklib import KNOWLEDGE, ROOT, agent_id, lock, parse, set_fields

MAX_LINES = 250


def knowledge_file(project: str | Path) -> Path:
    return KNOWLEDGE / f"{Path(project).name}.md"


def _git(project: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)


def changed_since(project: str | Path, commit: str, ref: str = "HEAD") -> list[str] | None:
    """Files changed between the recorded commit and ref; None if the commit isn't in this repo anymore."""
    if _git(project, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return None
    done = _git(project, "diff", "--name-only", f"{commit}..{ref}")
    return [line for line in done.stdout.splitlines() if line]


def sections_mentioning(text: str, files: list[str]) -> list[str]:
    """Headings of the sections that mention any of the changed files (by path or folder)."""
    hits = []
    for heading, body in re.findall(r"^## +(.+?)\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S):
        if any(f in body or str(Path(f).parent) + "/" in body for f in files):
            hits.append(heading.strip())
    return hits


def info(path: Path) -> dict:
    """What the console shows for one knowledge file."""
    meta = parse(path)
    commit = meta.get("commit", "")
    changed = changed_since(meta["path"], commit) if commit and meta.get("path") else None
    return {"service": meta.get("service") or path.stem, "file": path.name, "path": meta.get("path", ""),
            "commit": commit, "branch": meta.get("branch", ""), "updated": meta.get("updated", ""),
            "updated_by": meta.get("updated_by", ""),
            "changed": None if changed is None else len(changed), "lines": len(path.read_text(encoding="utf-8").splitlines())}


def new(project: Path) -> Path:
    path = knowledge_file(project)
    if path.exists():
        return path
    KNOWLEDGE.mkdir(parents=True, exist_ok=True)
    text = (ROOT / "templates" / "KNOWLEDGE.md").read_text(encoding="utf-8")
    path.write_text(text.replace("SERVICE_NAME", project.name).replace("PROJECT_PATH", str(project)), encoding="utf-8")
    return path


def stamp(project: Path, ref: str) -> str:
    commit = _git(project, "rev-parse", "--short", ref).stdout.strip()
    if not commit:
        sys.exit(f"`{ref}` isn't a commit in {project}.")
    branch = _git(project, "branch", "--show-current").stdout.strip() or ref
    with lock():
        set_fields(new(project), commit=commit, branch=branch, updated=dt.date.today().isoformat(),
                   updated_by=agent_id("techlead"))
    return commit


def status(project: Path, ref: str) -> str:
    path = knowledge_file(project)
    if not path.exists():
        return (f"No knowledge of {project.name} yet ({path}).\n"
                f"Research as usual. When the spec is written, create it with `knowledge.py new {project}`, "
                "fill in what you read, then `knowledge.py stamp`.")
    text = path.read_text(encoding="utf-8")
    meta = parse(path)
    lines = [f"Knowledge: {path}  ({len(text.splitlines())} lines, updated {meta.get('updated') or 'never'}"
             f" by {meta.get('updated_by') or '?'})"]
    commit = meta.get("commit", "")
    changed = changed_since(project, commit, ref) if commit else None
    if not commit:
        lines.append("Never stamped: treat it as unverified and check what you rely on.")
    elif changed is None:
        lines.append(f"Recorded commit {commit} is no longer in the repo (rebased or another clone): "
                     "treat it as unverified and check what you rely on.")
    elif not changed:
        lines.append(f"Up to date: nothing changed between {commit} and {ref}. Trust it; read code only for what it doesn't cover.")
    else:
        lines.append(f"{len(changed)} file(s) changed between {commit} and {ref}:")
        lines += [f"  {f}" for f in changed[:40]] + ([f"  … and {len(changed) - 40} more"] if len(changed) > 40 else [])
        stale = sections_mentioning(text, changed)
        lines.append("Re-check these sections: " + (", ".join(stale) if stale else "none mention them")
                     + ". Everything else can be trusted. Also skim the changed files for new APIs or entities.")
    if len(text.splitlines()) > MAX_LINES:
        lines.append(f"Over {MAX_LINES} lines: tighten it when you next update it.")
    return "\n".join(lines)


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("status", "new", "stamp"):
        sys.exit("usage: knowledge.py status|new|stamp <project-folder> [ref]")
    command, project = sys.argv[1], Path(sys.argv[2]).expanduser().resolve()
    ref = sys.argv[3] if len(sys.argv) > 3 else "HEAD"
    if not (project / ".git").exists():
        sys.exit(f"Not a git repository: {project}")
    if command == "status":
        print(status(project, ref))
    elif command == "new":
        print(new(project))
    else:
        print(f"Stamped {knowledge_file(project)} at {stamp(project, ref)}.")


if __name__ == "__main__":
    main()
