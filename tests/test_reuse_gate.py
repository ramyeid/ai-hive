"""Checks that the readiness gate demands a reuse check before a task reaches dev.

    python3 tests/test_reuse_gate.py      (from the kit folder; uses a temporary project)
"""
import re
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KIT / "scripts"))
import check_ready  # noqa: E402

checks = 0


def check(condition, what):
    global checks
    checks += 1
    if not condition:
        sys.exit(f"FAIL: {what}")
    print(f"ok  {what}")


def fill(template: str, project: Path, reuse: str) -> str:
    """A complete spec, with the given Existing Code to Reuse section body."""
    text = (template.replace("PROJECT_PATH", str(project)).replace("BASE_BRANCH", "main")
            .replace("title: Short imperative title", "title: Filter orders by status")
            .replace("approved:  ", "approved: 2026-10-20  ")
            .replace("- [ ]", "- [x]"))
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    body = {
        "Problem / Goal": "Support staff need to see only pending orders.",
        "User Stories": "As support, I want to filter orders by status, so that I see what needs action.",
        "Acceptance Criteria": "1. **Given** orders, **when** `GET /api/orders?status=pending`, **then** only pending ones return.",
        "Out of Scope": "Sorting.",
        "Reference Implementations": "| Reference | Why | Patterns |\n|---|---|---|\n| `app/orders.py:1-2` | same endpoint | filters |",
        "Conventions to Follow": "Query parameters are optional and snake_case.",
        "Clarifications": "| # | Question | Answer |\n|---|---|---|\n| 1 | Extend the existing endpoint? | Yes |\n| 2 | The base branch will be `main`, OK? | Yes |",
    }
    body["Existing Code to Reuse"] = reuse
    for name, content in body.items():   # replace the section's whole body, up to the next heading
        text = re.sub(rf"(## {re.escape(name)}\n).*?(?=\n## )", lambda m: m.group(1) + content + "\n", text, count=1, flags=re.S)
    return text


GOOD = """**Searched:** `grep -ril order app/`, routes under `/api/orders`

| Existing code | What it already does | Overlap with this task |
|---|---|---|
| `app/orders.py:1-2` | lists all orders | same data, no status filter |

**Decision:** EXTEND `list_orders` with an optional `status` parameter; its one caller keeps working unchanged.
"""


def main():
    project = Path(tempfile.mkdtemp()) / "shop"
    (project / "app").mkdir(parents=True)
    (project / "app/orders.py").write_text("def list_orders():\n    return []\n")
    subprocess.run(["git", "init", "-q", str(project)], check=True)
    template = (KIT / "templates/TASK.md").read_text()
    task = project.parent / "TASK-001-filter.md"

    def problems(reuse):
        task.write_text(fill(template, project, reuse))
        return check_ready.check(task)

    found = problems(GOOD)
    check(found == [], f"a complete spec with a reuse decision is ready {found}")

    task.write_text(fill(template, project, GOOD).replace("| 2 | The base branch will be `main`, OK? | Yes |", ""))
    found = check_ready.check(task)
    check(any("base branch `main`" in p for p in found), "base branch not confirmed by the lead → not ready")

    found = problems(GOOD.replace("**Searched:** `grep -ril order app/`, routes under `/api/orders`", "**Searched:**"))
    check(any("Searched" in p for p in found), "no searches listed → not ready")

    found = problems(GOOD.split("| `app/orders.py")[0] + "\n**Decision:** NEW because nothing lists orders at all today.\n")
    check(any("no rows" in p for p in found), "no rows (not even 'nothing similar') → not ready")

    found = problems(GOOD.replace("app/orders.py:1-2", "app/invoices.py:1-9"))
    check(any("does not exist" in p and "invoices" in p for p in found), "a made-up existing-code path → not ready")

    found = problems(GOOD.replace("**Decision:** EXTEND", "**Decision:** maybe extend"))
    check(any("EXTEND, REUSE or NEW" in p for p in found), "decision isn't EXTEND / REUSE / NEW → not ready")

    found = problems(GOOD.split("**Decision:**")[0] + "**Decision:** NEW\n")
    check(any("and why" in p for p in found), "a bare NEW with no reason → not ready")

    found = problems(GOOD.replace("| `app/orders.py:1-2` | lists all orders | same data, no status filter |",
                                  "| none | nothing similar: searched orders, carts, checkout | none |")
                     .replace("EXTEND `list_orders` with an optional `status` parameter; its one caller keeps working unchanged.",
                              "NEW, nothing in the project lists or filters orders yet."))
    check(found == [], "nothing similar found, NEW with a reason → ready")
    print(f"\nAll {checks} checks passed.")


if __name__ == "__main__":
    main()
