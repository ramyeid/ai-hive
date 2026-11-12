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

New code is built like its **siblings**, the existing pieces of the same kind. A new entity, collection, repository or model inherits the base class its siblings use, uses the same model type (pydantic `BaseModel` where the project uses it, not a `dataclass`) and is registered the same way (e.g. its entry in the entity-type enum, its property on the repository). A new app or service has the same files as a sibling app, set up the same way (e.g. Dockerfile, CI entries, how `server.py` declares its routes), and none they don't have (no README if they have none). Before writing a generic helper (concurrency, retries, parsing), search the project's shared packages for one.

### Reuse first
Before anything new is built, check whether the project already does it or nearly does. Extending existing code (an extra parameter, a small refactor) beats a parallel copy. A near-duplicate is a defect: the Tech Lead looks for it in the spec (**Existing Code to Reuse**, checked by the gate), the dev before writing code, the reviewer on every review.

Extending never changes what existing callers see: an existing method or property keeps its name, return type and sync/async form, and every existing call works unchanged. A new parameter is optional and used by the method itself; never add one that the class only ignores so another class can share its signature. New behaviour for a new case goes in a class that inherits and overrides (e.g. `LangchainLlmRag(LangchainLLM)` overriding `invoke`), not in the existing class.

### Files and imports
- A small enum or class used only by one class lives in that class's file (e.g. on top of the service that uses
  it), and a package's small exception classes together in one `exceptions.py`: no file of their own. A type that
  a public method returns goes in the project's models folder (e.g. `models/`).
- No `if TYPE_CHECKING:` imports unless a circular import truly can't be avoided; one usually means the new code
  depends the wrong way (a base class importing a type only its subclass needs).

### Keep it simple
KISS above all: build exactly what the task asks with the simplest code that works. No boilerplate, no speculative abstractions, no clever code.

Nothing is built "just in case", unless the task asks for it: no default or fallback for a missing input (a blank search query means no search, not a default query), no cache, no lazy or async version of something that is simple and sync today, no handling of crashes, restarts or half-finished work, no endpoint, option or parameter nobody uses, no Protocol or base class with a single implementation. Ideas for extras are welcome as suggestions the lead can ignore, never built in.

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
   Helper names follow the project's naming style for methods (`BuildCourse(...)` in a C# file, not
   `_a_course()`). Helpers are generic building blocks reused across the class (`AddCourse(context, course,
   sections, lessons)`), never one written for a single test; use the file's existing builders first.
   No raw setup code (building objects field by field, inserting rows, configuring mocks) in the test body;
   creating the object under test and an empty mock with `new` is fine. When the file's existing tests are clean
   and organized, set up new tests the way they do, not in an opposite style; the three blocks still apply.
   Helpers live in the test file or class as private members (`_name` in Python, `private` in
   C#/TypeScript/Java). The given block is never empty:
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
