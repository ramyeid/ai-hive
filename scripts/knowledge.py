#!/usr/bin/env python3
"""The Tech Lead's memory of each repository: knowledge/<repo>/ (local, never committed).

  knowledge/<repo>/index.md        what the repo is, its services and packages, repo-wide conventions.
                                   For a single-service repo, everything is in this file.
  knowledge/<repo>/<service>.md    one file per service of a monorepo, covering its own folders (`scope:`).

Usage:
  python3 scripts/knowledge.py status <project> [--service NAME] [--ref REF]   what's known, what changed since
  python3 scripts/knowledge.py new <project> [--service NAME --scope DIR,DIR]  create the index or a service file
  python3 scripts/knowledge.py stamp <project> [--service NAME] [--ref REF]    record the commit a file now describes

How to trust it: every file records the commit it describes. `status` lists the files changed since then
inside that file's scope only, and which sections mention them: everything else can be trusted as is.
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import subprocess
import sys
from pathlib import Path

from tasklib import KNOWLEDGE, ROOT, agent_id, lock, parse, set_fields

MAX_LINES = {"index": 150, "service": 250}


def repo_folder(project: str | Path) -> Path:
    return KNOWLEDGE / Path(project).name


def file_for(project: str | Path, service: str | None = None) -> Path:
    return repo_folder(project) / f"{service or 'index'}.md"


def _git(project: str | Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(project), *args], capture_output=True, text=True)


def scope_of(meta: dict) -> list[str]:
    return [s.strip() for s in meta.get("scope", "").split(",") if s.strip()]


def changed_since(project: str | Path, commit: str, scope: list[str] | None = None, ref: str = "HEAD") -> list[str] | None:
    """Files changed between the recorded commit and ref, inside scope (empty = whole repo).
    None if the commit isn't in this repo anymore."""
    if _git(project, "cat-file", "-e", f"{commit}^{{commit}}").returncode != 0:
        return None
    done = _git(project, "diff", "--name-only", f"{commit}..{ref}", "--", *(scope or []))
    return [line for line in done.stdout.splitlines() if line]


def sections_mentioning(text: str, files: list[str]) -> list[str]:
    """Headings of the sections that mention any of the changed files (by path or folder)."""
    hits = []
    for heading, body in re.findall(r"^## +(.+?)\n(.*?)(?=^## |\Z)", text, flags=re.M | re.S):
        if any(f in body or str(Path(f).parent) + "/" in body for f in files):
            hits.append(heading.strip())
    return hits


def info(path: Path) -> dict:
    """One knowledge file, as the console and `status` show it."""
    meta = parse(path)
    kind = "index" if path.stem == "index" else "service"
    commit, project = meta.get("commit", ""), meta.get("path", "")
    changed = changed_since(project, commit, scope_of(meta)) if commit and project and Path(project).exists() else None
    return {"name": path.stem, "kind": kind, "service": meta.get("service", "") if kind == "service" else "",
            "repo": meta.get("repo") or path.parent.name, "path": project, "scope": scope_of(meta),
            "commit": commit, "branch": meta.get("branch", ""), "updated": meta.get("updated", ""),
            "updated_by": meta.get("updated_by", ""), "changed": None if changed is None else len(changed),
            "lines": len(path.read_text(encoding="utf-8").splitlines())}


def repo_files(folder: Path) -> list[Path]:
    """index.md first, then the service files by name."""
    return sorted(folder.glob("*.md"), key=lambda p: (p.stem != "index", p.stem.lower()))


# ---- commands -----------------------------------------------------------------------

def new(project: Path, service: str | None = None, scope: str = "") -> Path:
    path = file_for(project, service)
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    index = file_for(project)
    if not index.exists():
        _from_template(index, "KNOWLEDGE_INDEX.md", project)
    if service:
        _from_template(path, "KNOWLEDGE_SERVICE.md", project, service, scope)
        _add_to_services_table(index, service, scope)
    return path


def _from_template(path: Path, template: str, project: Path, service: str = "", scope: str = "") -> None:
    text = (ROOT / "templates" / template).read_text(encoding="utf-8")
    text = (text.replace("SERVICE_NAME", service).replace("REPO_NAME", project.name)
                .replace("PROJECT_PATH", str(project)).replace("SCOPE", scope))
    path.write_text(text, encoding="utf-8")


def _add_to_services_table(index: Path, service: str, scope: str) -> None:
    """Add the service's row to the index (and drop the single-service placeholder row)."""
    text = index.read_text(encoding="utf-8")
    text = re.sub(r"^\| \(whole repo\) \|.*\n", "", text, count=1, flags=re.M)
    row = f"| {service} | {scope} | | {service}.md |\n"
    table = re.search(r"(## Services and packages\n(?:<!--.*?-->\n)?(?:\|.*\n)+)", text, flags=re.S)
    if table and f"| {service} |" not in table.group(1):
        text = text.replace(table.group(1), table.group(1) + row, 1)
    index.write_text(text, encoding="utf-8")


def stamp(project: Path, service: str | None, ref: str) -> str:
    commit = _git(project, "rev-parse", "--short", ref).stdout.strip()
    if not commit:
        sys.exit(f"`{ref}` isn't a commit in {project}.")
    branch = _git(project, "branch", "--show-current").stdout.strip() or ref
    with lock():
        set_fields(new(project, service), commit=commit, branch=branch,
                   updated=dt.date.today().isoformat(), updated_by=agent_id("techlead"))
    return commit


def _freshness(path: Path, project: Path, ref: str) -> tuple[str, list[str] | None]:
    meta = parse(path)
    commit = meta.get("commit", "")
    if not commit:
        return "never stamped: unverified", None
    changed = changed_since(project, commit, scope_of(meta), ref)
    if changed is None:
        return f"commit {commit} is no longer in the repo: unverified", None
    if not changed:
        return f"up to date ({commit})", []
    return f"{len(changed)} file(s) changed since {commit}", changed


def status(project: Path, service: str | None, ref: str) -> str:
    folder = repo_folder(project)
    if not folder.exists():
        return (f"No knowledge of {project.name} yet ({folder}).\n"
                f"Research as usual. When the spec is written, create it with `knowledge.py new {project}` "
                "(and `--service <name> --scope <folders>` for each service of a monorepo), fill in what you read, "
                "then `knowledge.py stamp`.")
    if not service:
        lines = [f"Knowledge of {project.name}: {folder}"]
        for path in repo_files(folder):
            summary, _ = _freshness(path, project, ref)
            scope = ", ".join(scope_of(parse(path))) or "whole repo"
            lines.append(f"  {path.name:<28} {scope:<40} {summary}")
        lines.append("Read index.md, then only the service files the task touches. For details on one: "
                     f"`knowledge.py status {project} --service <name>`.")
        return "\n".join(lines)

    path = file_for(project, service if service != "index" else None)
    if not path.exists():
        return (f"No file for {service} yet. When the spec is written: "
                f"`knowledge.py new {project} --service {service} --scope <its folders>`.")
    text = path.read_text(encoding="utf-8")
    meta = parse(path)
    summary, changed = _freshness(path, project, ref)
    lines = [f"{path}  ({len(text.splitlines())} lines, updated {meta.get('updated') or 'never'} by {meta.get('updated_by') or '?'})",
             f"Scope: {', '.join(scope_of(meta)) or 'whole repo'}", summary.capitalize() + "."]
    if changed is None:
        lines.append("Check what you rely on before using it.")
    elif not changed:
        lines.append("Trust it; read code only for what it doesn't cover.")
    else:
        lines += [f"  {f}" for f in changed[:40]] + ([f"  … and {len(changed) - 40} more"] if len(changed) > 40 else [])
        stale = sections_mentioning(text, changed)
        lines.append("Re-check these sections: " + (", ".join(stale) if stale else "none mention them")
                     + ". Everything else can be trusted. Also skim the changed files for new APIs or entities.")
    limit = MAX_LINES["index" if path.stem == "index" else "service"]
    if len(text.splitlines()) > limit:
        lines.append(f"Over {limit} lines: tighten it, or split a part into its own service file.")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="The Tech Lead's memory of each repository.")
    parser.add_argument("command", choices=["status", "new", "stamp"])
    parser.add_argument("project")
    parser.add_argument("--service", help="a service of a monorepo (default: the repo's index.md)")
    parser.add_argument("--scope", default="", help="with new --service: its folders, comma-separated")
    parser.add_argument("--ref", default="HEAD", help="compare against this commit or branch (default HEAD)")
    args = parser.parse_args()
    project = Path(args.project).expanduser().resolve()
    if not (project / ".git").exists():
        sys.exit(f"Not a git repository: {project}")
    if args.service and not re.fullmatch(r"[A-Za-z0-9._-]+", args.service):
        sys.exit("Service names are letters, digits, dot, dash and underscore.")
    if args.command == "status":
        print(status(project, args.service, args.ref))
    elif args.command == "new":
        if args.service and not args.scope and not file_for(project, args.service).exists():
            sys.exit("A new service file needs --scope: the folders it covers, e.g. --scope services/orders/")
        print(new(project, args.service, args.scope))
    else:
        print(f"Stamped {file_for(project, args.service)} at {stamp(project, args.service, args.ref)}.")


if __name__ == "__main__":
    main()
