"""The readiness gate demands a reuse check (and a confirmed base branch) before a task reaches a developer.

    python3 -m unittest discover team/tests      (from the Hive folder; uses a temporary project)
"""
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]   # the Hive folder
sys.path.insert(0, str(KIT / "team" / "tools"))
import check_ready  # noqa: E402

CLARIFICATIONS = "| # | Question | Answer |\n|---|---|---|\n| 1 | Extend the existing endpoint? | Yes |\n| 2 | The base branch will be `main`, OK? | Yes |"


def fill(template: str, project: Path, reuse: str, clarifications: str) -> str:
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
        "Clarifications": clarifications,
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


NOTHING_SIMILAR = (GOOD.replace("| `app/orders.py:1-2` | lists all orders | same data, no status filter |",
                                "| none | nothing similar: searched orders, carts, checkout | none |")
                   .replace("EXTEND `list_orders` with an optional `status` parameter; its one caller keeps working unchanged.",
                            "NEW, nothing in the project lists or filters orders yet."))


class ReuseGateTest(unittest.TestCase):

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp)
        self.project = tmp / "shop"
        (self.project / "app").mkdir(parents=True)
        (self.project / "app/orders.py").write_text("def list_orders():\n    return []\n")
        subprocess.run(["git", "init", "-q", str(self.project)], check=True)
        self.task = tmp / "TASK-001-filter.md"

    def test_a_complete_spec_with_a_reuse_decision_is_ready(self):
        self._a_spec(GOOD)

        found = check_ready.check(self.task)

        self.assertEqual(found, [])

    def test_a_base_branch_the_lead_has_not_confirmed_is_not_ready(self):
        self._a_spec(GOOD, clarifications=CLARIFICATIONS.replace("| 2 | The base branch will be `main`, OK? | Yes |", ""))

        found = check_ready.check(self.task)

        self.assertTrue(any("base branch `main`" in p for p in found), found)

    def test_no_searches_listed_is_not_ready(self):
        self._a_spec(GOOD.replace("**Searched:** `grep -ril order app/`, routes under `/api/orders`", "**Searched:**"))

        found = check_ready.check(self.task)

        self.assertTrue(any("Searched" in p for p in found), found)

    def test_no_rows_at_all_is_not_ready(self):
        self._a_spec(GOOD.split("| `app/orders.py")[0] + "\n**Decision:** NEW because nothing lists orders at all today.\n")

        found = check_ready.check(self.task)

        self.assertTrue(any("no rows" in p for p in found), found)

    def test_a_made_up_existing_code_path_is_not_ready(self):
        self._a_spec(GOOD.replace("app/orders.py:1-2", "app/invoices.py:1-9"))

        found = check_ready.check(self.task)

        self.assertTrue(any("does not exist" in p and "invoices" in p for p in found), found)

    def test_a_decision_other_than_extend_reuse_or_new_is_not_ready(self):
        self._a_spec(GOOD.replace("**Decision:** EXTEND", "**Decision:** maybe extend"))

        found = check_ready.check(self.task)

        self.assertTrue(any("EXTEND, REUSE or NEW" in p for p in found), found)

    def test_a_bare_new_without_a_reason_is_not_ready(self):
        self._a_spec(GOOD.split("**Decision:**")[0] + "**Decision:** NEW\n")

        found = check_ready.check(self.task)

        self.assertTrue(any("and why" in p for p in found), found)

    def test_nothing_similar_found_and_new_with_a_reason_is_ready(self):
        self._a_spec(NOTHING_SIMILAR)

        found = check_ready.check(self.task)

        self.assertEqual(found, [])

    # ---- helpers ----------------------------------------------------------------------

    def _a_spec(self, reuse: str, clarifications: str | None = None) -> None:
        template = (KIT / "team" / "templates" / "TASK.md").read_text()
        self.task.write_text(fill(template, self.project, reuse, clarifications or CLARIFICATIONS))


if __name__ == "__main__":
    unittest.main()
