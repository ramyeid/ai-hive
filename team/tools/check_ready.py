#!/usr/bin/env python3
"""Definition-of-Ready gate: is this task complete enough to hand to dev?

Usage: python3 team/tools/check_ready.py data/tasks/TASK-007-something.md
Exit 0 = ready, exit 1 = problems listed.

Also called by the hook: a task set to ready-for-dev that fails this check
is put back to draft automatically.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from tasklib import parse

REQUIRED = ["Problem / Goal", "User Stories", "Acceptance Criteria", "Out of Scope",
            "Existing Code to Reuse", "Reference Implementations", "Conventions to Follow", "Clarifications"]
VAGUE = re.compile(r"\b(TBD|TBC|TODO|FIXME|etc\.?)(?=\W|$)|\?\?\?", re.I)


def sections(text: str) -> dict[str, str]:
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)      # ignore guidance comments
    body = body.split("\n## Dev Log", 1)[0]                   # techlead's part only
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.M)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def table_rows(block: str) -> list[str]:
    rows = [l for l in block.splitlines() if l.strip().startswith("|")]
    return [r for r in rows[1:] if not re.fullmatch(r"\|[\s:|-]*", r.strip())]


def missing_paths(row: str, project: Path) -> list[str]:
    """Backticked paths in a table row that don't exist (URLs are skipped)."""
    missing = []
    for p in re.findall(r"`([^`]+)`", row):
        if "://" in p:
            continue
        clean = re.sub(r"(:\d+(-\d+)?|#L\d+.*)$", "", p)
        target = Path(clean).expanduser()
        target = target if target.is_absolute() else project / target
        if not target.exists():
            missing.append(p)
    return missing


def reuse_problems(block: str, project: Path) -> list[str]:
    """The Tech Lead must have looked for code that already does this, and decided extend / reuse / new."""
    problems = []
    searched = re.search(r"\*\*Searched:\*\*(.*?)(?=\n\s*\||\*\*Decision|\Z)", block, re.S)
    if not searched or not searched.group(1).strip():
        problems.append("Existing Code to Reuse: **Searched:** is empty: list the searches you ran for code that already does this.")
    rows = table_rows(block)
    if not rows:
        problems.append("Existing Code to Reuse: no rows. Add each similar piece of code found, or one row saying nothing similar exists.")
    for row in rows:
        for p in missing_paths(row, project):
            problems.append(f"Existing code path does not exist: `{p}`")
    decision = re.search(r"\*\*Decision:\*\*\s*(EXTEND|REUSE|NEW)\b(.*)", block)
    if not decision:
        problems.append("Existing Code to Reuse: **Decision:** must start with EXTEND, REUSE or NEW.")
    elif len(decision.group(2).strip(" -—:.")) < 15:
        problems.append(f"Existing Code to Reuse: say what to {decision.group(1).lower()} and why, after the decision.")
    return problems


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    meta, sec, problems = parse(path), sections(text), []

    project = Path(meta.get("project", "")).expanduser()
    if not project.is_absolute() or not (project / ".git").exists():
        problems.append(f"`project:` is not a git repository folder: `{meta.get('project')}`")
    base = meta.get("base", "")
    if not base or base == "BASE_BRANCH":
        problems.append("`base:` branch is not set.")
    elif not re.search(rf"(?<![\w/.-]){re.escape(base)}(?![\w/-])", sec.get("Clarifications", "")):
        problems.append(f"The lead hasn't confirmed the base branch `{base}`: ask \"The base branch will be "
                        f"`{base}`, OK?\" and log the answer in Clarifications.")

    if meta.get("title", "") in ("", "Short imperative title"):
        problems.append("Title is still the template placeholder.")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", meta.get("approved", "")):
        problems.append("`approved:` is empty — the lead has not explicitly approved the final readback.")

    for name in REQUIRED:
        if not sec.get(name):
            problems.append(f"Section '{name}' is empty.")

    if sec.get("Acceptance Criteria") and not re.search(r"^\s*\d+\.", sec["Acceptance Criteria"], re.M):
        problems.append("Acceptance Criteria must be a numbered list.")

    if "Clarifications" in sec and not table_rows(sec["Clarifications"]):
        problems.append("Clarifications log is empty — no questions were asked and answered.")

    if sec.get("Existing Code to Reuse"):
        problems += reuse_problems(sec["Existing Code to Reuse"], project)

    refs = table_rows(sec.get("Reference Implementations", ""))
    if not refs:
        problems.append("No Reference Implementations — dev has nothing to mirror.")
    for row in refs:
        paths = re.findall(r"`([^`]+)`", row)
        if not paths and "NEW PATTERN" not in row:
            problems.append(f"Reference row has no `path` in backticks: {row.strip()}")
        for p in missing_paths(row, project):
            problems.append(f"Reference path does not exist: `{p}`")

    open_q = re.findall(r"^\s*- \[ \]\s*(.+)$", sec.get("Open Questions", ""), re.M)
    for q in open_q:
        problems.append(f"Unanswered open question: {q}")

    dor = sec.get("Definition of Ready", "")
    unticked = re.findall(r"^\s*- \[ \]\s*(.+)$", dor, re.M)
    if not re.search(r"^\s*- \[x\]", dor, re.M | re.I):
        problems.append("Definition of Ready checklist is missing or not ticked.")
    for item in unticked:
        problems.append(f"Definition of Ready not met: {item}")

    for name, block in sec.items():
        if name in ("Clarifications", "Open Questions"):
            continue
        for m in VAGUE.finditer(block):
            problems.append(f"Placeholder/vague word '{m.group(0)}' in '{name}'.")

    return problems


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit("usage: check_ready.py data/tasks/TASK-NNN-slug.md")
    problems = check(Path(sys.argv[1]))
    if problems:
        print("NOT READY:\n" + "\n".join(f"  - {p}" for p in problems))
        sys.exit(1)
    print("READY: all Definition-of-Ready checks pass.")


if __name__ == "__main__":
    main()
