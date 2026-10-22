# Team workflow (shared by all agents)

Three agents — **techlead**, **dev**, **reviewer** — managed by a human lead, working on any project on this laptop.
The central task board in `tasks/` covers all projects. (Paths in this file are relative to the kit folder, where this file lives.) It is the single source of truth and the only handoff channel.

## Task lifecycle

```
draft ──► ready-for-dev ──► in-dev ──► ready-for-review ──► in-review ──► done
  (techlead)        (techlead)          (dev)          (dev)             (reviewer)   (reviewer)
                               ▲                                 │
                               └─────── changes-requested ◄──────┘
                                            (reviewer)
```

| Status              | Set by   | Meaning                                              |
|---------------------|----------|------------------------------------------------------|
| `draft`             | techlead       | Being written; not ready for anyone else             |
| `ready-for-dev`     | techlead       | Spec + acceptance criteria approved by the lead      |
| `in-dev`            | dev      | Dev has claimed it                                   |
| `ready-for-review`  | dev      | Committed on the task branch, unit tests pass        |
| `in-review`         | reviewer | Reviewer has claimed it                              |
| `changes-requested` | reviewer | Findings to fix; see the Review Report section       |
| `done`              | reviewer | Requirements met, consistent with existing code     |
| `blocked`           | anyone   | Needs a decision from the lead; say why in the file  |

## Several agents per role

There can be more than one Tech Lead, dev or reviewer (e.g. `techlead`, `techlead-2`, `dev`, `dev-2`, `dev-3`). Each agent has an
ID in the `AGENT_ID` environment variable, set by the console (in a terminal: `AGENT_ID=dev-2 claude --agent dev`);
without it the ID is just the role name. The kit's scripts read it, so commands stay the same for everyone.

- `scripts/inbox.py <role>` shows *your* notifications and the tasks *you* can take.
- **Claim before working:** `python3 scripts/claim.py TASK-NNN dev` (or `reviewer`). Claims are atomic: if
  another agent got there first, the script says so; pick another task. Never claim by editing `status:` yourself.
- A task remembers who wrote, built and reviewed it (`techlead:`, `dev:`, `reviewer:`). Rework goes back to the same
  dev and re-reviews to the same reviewer; nobody else may take them.

## Rules every agent follows

1. One task = one file: `tasks/TASK-<NNN>-<slug>.md`, created only with `python3 scripts/new_task.py <project-folder> "<title>"`.
   Its `project:` field is the folder where all the task's work happens; `base:` is the branch it starts from and is reviewed against. `base:` is the lead's choice and is often not `main` (a `develop`, release or feature branch). The Tech Lead asks the lead to confirm it while writing the spec (the readiness check requires it); after that, everyone uses it as given and never blocks on it.
2. Only change the `status:` field to a value your role is allowed to set (table above).
3. Never delete another role's section. Append to your own section; add dated entries.
4. If anything is ambiguous, set `status: blocked`, write the question under **Open Questions**, and stop. The lead decides.
5. Code changes happen only in the task's **worktree** (`worktree:` field): a separate folder where the task's `branch:` is checked out, created from `base:` when the dev claims the task. Never switch branches or edit code in the main `project:` folder; that's the lead's checkout. Never touch other projects.
6. Keep `tasks/BOARD.md` out of your edits — it is regenerated automatically.
7. A task only reaches `ready-for-dev` when `scripts/check_ready.py` passes (no open questions, references to follow, Definition of Ready ticked, lead approval dated). The hook enforces this and reverts it to `draft` otherwise.
8. **Consistency with the repo you're in.** Conventions are what the project's existing code does; read it and match it. The one exception is the **shape of tests**: see "How tests are written" below. They don't need to be written down first, and no agent stops because a conventions file is missing.
   Consistency beats cleverness: the whole codebase should look like one author wrote it. New code is highly inspired by the task's **Reference Implementations** (same patterns and style, not copy-paste; shared logic is reused, never duplicated) and follows **Conventions to Follow**.
9. **Reuse first.** Before anything new is built, check whether the project already does it or nearly does. Extending existing code (an extra parameter, a small refactor) beats a parallel copy. A near-duplicate is a defect: the Tech Lead looks for it in the spec (**Existing Code to Reuse**, checked by the gate), the dev before writing code, the reviewer on every review.
10. KISS above all: build exactly what the task asks with the simplest code that works. No boilerplate, no speculative abstractions, no clever code.

## How tests are written (every project, always)

This is the **one exception to "be consistent with the repo"**: every test the team writes follows these
rules, even when the project's existing tests don't. Everything else about tests (framework, file location,
file and test naming, assertion library, fixtures and mocks) still follows the project.

1. **Three blocks, every time: given, when, then.** Each test body has exactly three blocks, in this order,
   each marked with a comment in the language's syntax (`# given` / `// given`, `# when`, `# then`).
   Always all three, even when one is short. If nothing needs setting up, the given block still says what
   the starting state is (`# given: no tasks exist`). Never merge them (`# when/then`), never repeat them
   (given, when, then, when, then): a second action is a second test.
2. **Given:** the setup, written as calls to **private helper methods with clear names** that say what they
   create, e.g. `_given_a_task_ready_for_dev()`, `_an_order_with_status("pending")`,
   `CreatePaidInvoice(amount: 120)`. No raw setup code (building objects field by field, inserting rows,
   configuring mocks) in the test body. Helpers live in the test file or class as private members (`_name`
   in Python, `private` in C#/TypeScript/Java), reused across the tests that need the same state.
3. **When:** exactly one action, the behaviour under test, usually one line that stores its result:
   `result = service.list_orders(status="pending")`.
4. **Then:** assertions about that one action's result or effect only. Specific values (`== 2`,
   `== "Forbidden"`), not just "not null". Several assertions are fine if they describe the same outcome.
5. **One behaviour per test**, named for it: `test_lists_only_pending_orders_when_status_is_pending`
   (or the project's naming style for test names).

Example (Python; same shape in any language):

```python
def test_rejects_a_second_claim_on_the_same_task():
    # given
    task = _a_task_ready_for_dev()
    _claimed_by(task, "dev")

    # when
    result = claim(task.id, agent="dev-2")

    # then
    assert result.refused
    assert result.message == f"{task.id} is `in-dev`, not waiting for a dev. Pick another task."


def _a_task_ready_for_dev() -> Task: ...
def _claimed_by(task: Task, agent: str) -> None: ...
```

## Keep it cheap (every agent)

Every message re-sends the whole conversation, so everything you read or print is paid for again on every later turn.

- **Search, then read only what you need.** Use Grep/Glob to find the spot, then Read just those lines (offset/limit). Read a whole file only when you need all of it. Don't re-read a file you already read in this session unless it changed.
- **The task file is the shared memory.** The Tech Lead records what it found: reference files with line ranges, the places to change, the conventions. Use that instead of exploring the codebase again. Each project's **conventions notes** (`tasks/conventions/<project>.md`, in the kit, never in the repo) are the standing summary of how that project is built, derived from its code. `new_task.py` and `claim.py` print the path. If they don't exist yet, whoever needs them first writes them from the code; a missing file never blocks anyone.
- **Run only what you need.** While working, run the tests for the code you changed; run the full suite once before handing off. Use quiet output and keep only the end of long output, e.g. `pytest -q 2>&1 | tail -30`, `dotnet test --nologo -v q 2>&1 | tail -40`, `npm test --silent 2>&1 | tail -40`.
- **Use the project's commands.** The Commands section of the project's conventions notes lists the quiet test, type-check and build commands. Use them as written.
- **Build only when needed.** To check that code compiles, prefer the type-check or compile check (faster, prints only errors). Run a full build (e.g. `ng build`) only when an acceptance criterion or the hand-off needs it.
- **Never start anything that doesn't exit:** dev servers (`ng serve`, `npm start`, `dotnet watch`), watch-mode tests (`ng test` without `--watch=false`), `docker compose up` without `-d`. They hang until the command times out and waste a turn.
- **Never dump large output:** no `ls -R` or unfiltered `find` over a repository, no `cat` of big, generated or lock files, logs or build output. Filter (`grep`, `head`, `tail`) first.
- **Keep replies to the lead short:** decisions, questions and results, not file contents.
