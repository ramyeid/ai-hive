# How the lead wants things built

Every agent reads this file before working, and follows it. TEAM.md says **how the team works** (lifecycle,
branches, hand-offs); this file says **what good work looks like for the lead**: how code is shaped, how tests
are written, how to work with the lead. Where this file and a project's existing code disagree, this file wins
only where it says so explicitly (the shape of tests); otherwise match the project.

This file changes only with the lead's approval: the lead edits it directly, or approves a change the Coach
proposes in the console (Improvements). Every change is in its history (the console's Team history page).

## Building code

### Consistency with the repo you're in
Conventions are what the project's existing code does; read it and match it. The one exception is the **shape of tests**: see "How tests are written" below. They don't need to be written down first, and no agent stops because a conventions file is missing.

Consistency beats cleverness: the whole codebase should look like one author wrote it. New code is highly inspired by the task's **Reference Implementations** (same patterns and style, not copy-paste; shared logic is reused, never duplicated) and follows **Conventions to Follow**.

### Reuse first
Before anything new is built, check whether the project already does it or nearly does. Extending existing code (an extra parameter, a small refactor) beats a parallel copy. A near-duplicate is a defect: the Tech Lead looks for it in the spec (**Existing Code to Reuse**, checked by the gate), the dev before writing code, the reviewer on every review.

### Keep it simple
KISS above all: build exactly what the task asks with the simplest code that works. No boilerplate, no speculative abstractions, no clever code.

## How tests are written (every project, always)

This is the **one exception to "be consistent with the repo"**: every test the team writes follows these
rules, even when the project's existing tests don't. Everything else about tests (framework, file location,
file and test naming, assertion library, fixtures and mocks) still follows the project.

1. **Three blocks, every time: given, when, then.** A block is a group of lines; blocks are separated by
   **one empty line**. Every test body is exactly three blocks in this order: given (setup), when (the
   action), then (the assertions). So a test body always has exactly two empty lines, between the blocks,
   and no empty line anywhere inside a block. No `given` / `when` / `then` comments: the empty lines are
   the delimiters. Never merge two blocks, never add a fourth: a second action is a second test.
2. **Given:** the setup, written as calls to **private helper methods with clear names** that say what they
   create, e.g. `_a_task_ready_for_dev()`, `_an_order_with_status("pending")`, `CreatePaidInvoice(amount: 120)`.
   No raw setup code (building objects field by field, inserting rows, configuring mocks) in the test body.
   Helpers live in the test file or class as private members (`_name` in Python, `private` in
   C#/TypeScript/Java), reused across the tests that need the same state. The given block is never empty:
   when the test starts from nothing, a helper says so (`_no_tasks_on_the_board()`).
3. **When:** exactly one action, the behaviour under test, usually one line that stores its result:
   `result = service.list_orders(status="pending")`.
4. **Then:** assertions about that one action's result or effect only. Specific values (`== 2`,
   `== "Forbidden"`), not just "not null". Several assertions are fine if they describe the same outcome.
5. **One behaviour per test**, named for it: `test_lists_only_pending_orders_when_status_is_pending`
   (or the project's naming style for test names).

Example (Python; same shape in any language):

```python
def test_rejects_a_second_claim_on_the_same_task():
    task = _a_task_ready_for_dev()
    _claimed_by(task, "dev")

    result = claim(task.id, agent="dev-2")

    assert result.refused
    assert result.message == f"{task.id} is `in-dev`, not waiting for a dev. Pick another task."


def _a_task_ready_for_dev() -> Task: ...
def _claimed_by(task: Task, agent: str) -> None: ...
```
