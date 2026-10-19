#!/usr/bin/env python3
"""Definition-of-Ready gate: is this task complete enough to hand to dev?

Usage: python3 scripts/check_ready.py tasks/TASK-007-something.md
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
            "Reference Implementations", "Conventions to Follow", "Clarifications"]
VAGUE = re.compile(r"\b(TBD|TBC|TODO|FIXME|etc\.?)(?=\W|$)|\?\?\?", re.I)


def sections(text: str) -> dict[str, str]:
    body = re.sub(r"<!--.*?-->", "", text, flags=re.S)      # ignore guidance comments
    body = body.split("\n## Dev Log", 1)[0]                   # pm's part only
    parts = re.split(r"^## +(.+?)\s*$", body, flags=re.M)
    return {parts[i].strip(): parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def table_rows(block: str) -> list[str]:
    rows = [l for l in block.splitlines() if l.strip().startswith("|")]
    return [r for r in rows[1:] if not re.fullmatch(r"\|[\s:|-]*", r.strip())]


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    meta, sec, problems = parse(path), sections(text), []

    project = Path(meta.get("project", "")).expanduser()
    if not project.is_absolute() or not (project / ".git").exists():
        problems.append(f"`project:` is not a git repository folder: `{meta.get('project')}`")
    if not meta.get("base") or meta.get("base") == "BASE_BRANCH":
        problems.append("`base:` branch is not set.")

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

    refs = table_rows(sec.get("Reference Implementations", ""))
    if not refs:
        problems.append("No Reference Implementations — dev has nothing to mirror.")
    for row in refs:
        paths = re.findall(r"`([^`]+)`", row)
        if not paths and "NEW PATTERN" not in row:
            problems.append(f"Reference row has no `path` in backticks: {row.strip()}")
        for p in paths:
            if "://" in p:
                continue
            clean = re.sub(r"(:\d+(-\d+)?|#L\d+.*)$", "", p)
            target = Path(clean).expanduser()
            target = target if target.is_absolute() else project / target
            if not target.exists():
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
        sys.exit("usage: check_ready.py tasks/TASK-NNN-slug.md")
    problems = check(Path(sys.argv[1]))
    if problems:
        print("NOT READY:\n" + "\n".join(f"  - {p}" for p in problems))
        sys.exit(1)
    print("READY: all Definition-of-Ready checks pass.")


if __name__ == "__main__":
    main()
