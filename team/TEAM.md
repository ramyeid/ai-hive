# Team workflow (shared by all agents)

Three agents — **techlead**, **dev**, **reviewer** — managed by a human lead, working on any project on this laptop.
The central task board in `data/tasks/` covers all projects. (Paths in this file are relative to the Hive folder.) It is the single source of truth and the only handoff channel.

## Task lifecycle

```
draft ──► ready-for-dev ──► in-dev ──► ready-for-review ──► in-review ──► done
  (techlead)        (techlead)          (dev)          (dev)             (reviewer)   (reviewer)
                               ▲                                 │
                               └─────── changes-requested ◄──────┘
                                       (reviewer, or the lead)
```

**The lead's code review.** At any point after the dev hands off (`ready-for-review`, `changes-requested` or `done`),
the lead can review the branch's diff in the console and **request changes**: the comments are added to the task
file under **Lead Review** (one round each time), and the task goes back to `changes-requested` for the dev who
built it. The lead may do this as often as needed, before or after the reviewer, or never. The **reviewer is always
the last step before `done`**: after any rework the task goes through the reviewer again.

| Status              | Set by   | Meaning                                              |
|---------------------|----------|------------------------------------------------------|
| `draft`             | techlead       | Being written; not ready for anyone else             |
| `ready-for-dev`     | techlead       | Spec + acceptance criteria approved by the lead      |
| `in-dev`            | dev      | Dev has claimed it                                   |
| `ready-for-review`  | dev      | Committed on the task branch, unit tests pass        |
| `in-review`         | reviewer | Reviewer has claimed it                              |
| `changes-requested` | reviewer, lead | Findings to fix: the newest Review Report entry or Lead Review round |
| `done`              | reviewer | Requirements met, consistent with existing code     |
| `blocked`           | anyone   | Needs a decision from the lead; say why in the file  |

## Several agents per role

There can be more than one Tech Lead, dev or reviewer (e.g. `techlead`, `techlead-2`, `dev`, `dev-2`, `dev-3`). Each agent has an
ID in the `AGENT_ID` environment variable, set by the console (in a terminal: `AGENT_ID=dev-2 claude --agent dev`);
without it the ID is just the role name. The team's tools read it, so commands stay the same for everyone.

- `team/tools/inbox.py <role>` shows *your* notifications and the tasks *you* can take.
- **Claim before working:** `python3 team/tools/claim.py TASK-NNN dev` (or `reviewer`). Claims are atomic: if
  another agent got there first, the script says so; pick another task. Never claim by editing `status:` yourself.
- A task remembers who wrote, built and reviewed it (`techlead:`, `dev:`, `reviewer:`). Rework goes back to the same
  dev and re-reviews to the same reviewer; nobody else may take them.

## Rules every agent follows

1. One task = one file: `data/tasks/TASK-<NNN>-<slug>.md`, created only with `python3 team/tools/new_task.py <project-folder> "<title>"`.
   Its `project:` field is the folder where all the task's work happens; `base:` is the branch it starts from and is reviewed against. `base:` is the lead's choice and is often not `main` (a `develop`, release or feature branch). The Tech Lead asks the lead to confirm it while writing the spec (the readiness check requires it); after that, everyone uses it as given and never blocks on it.
2. Only change the `status:` field to a value your role is allowed to set (table above).
3. Never delete another role's section. Append to your own section; add dated entries. **Lead Review** is written by
   the console: never edit its comments; the dev only fills in the `- Reply:` lines.
4. If anything is ambiguous, set `status: blocked`, write the question under **Open Questions**, and stop. The lead decides.
5. **One branch per feature, named `feature-<title>`** (e.g. `feature-filter-orders-by-status`), created from `base:` when the dev first claims it. Later tasks that add to, change or fix that feature (often a misunderstanding cleared up) are **follow-ups** (`new_task.py … --follow-up TASK-NNN`): same branch, new commits on top; never a new branch, never a rebase or force-push. Only one task per branch is in progress at a time. Each task records `from_commit:`, so its own changes are `git diff <from_commit>..HEAD`.
   Code changes happen only in the branch's **worktree** (`worktree:` field): a separate folder where the `branch:` is checked out, next to the project (`<project>.worktrees/feature-…`), reused by its follow-ups. Never switch branches or edit code in the main `project:` folder; that's the lead's checkout. Never touch other projects.
6. Keep `data/tasks/BOARD.md` out of your edits — it is regenerated automatically.
7. A task only reaches `ready-for-dev` when `team/tools/check_ready.py` passes (no open questions, references to follow, Definition of Ready ticked, lead approval dated). The hook enforces this and reverts it to `draft` otherwise.
8. **Build the way the lead wants:** `PREFERENCES.md` (consistency with the repo, reuse first, KISS, how tests
   are written, and whatever else the lead has asked for) is as binding as this file. Read it before working.
9. **Secrets are flagged, never repeated.** When you see a password, key or token in plain text (code, config, a
   diff), never copy it into another file, never write its value in a task file, report, commit message or reply,
   and never use it. Flag only where it is, for the lead: `backend/configuration.yml:36-40 (production DB password)`.
   A config that needs a secret takes it the way the file already does elsewhere (e.g. `source: ssm`).

## One conversation per hand-off

- **Handing a task on is the last thing you do in a turn** (Tech Lead → `ready-for-dev`, dev → `ready-for-review`,
  reviewer → `done` or `changes-requested`). In the console, your conversation is then saved with the task and you
  start fresh for the next one, so nothing carries over from one task to another. In a terminal, ask the lead to
  `/clear` instead.
- **The task file is the only thing that carries work between agents.** Write everything the next agent needs there.
- `data/tasks/chats/` holds every agent's conversation on each task, for the lead's debugging. **Never read it.**

## Keep it cheap (every agent)

Every message re-sends the whole conversation, so everything you read or print is paid for again on every later turn.

- **Search, then read only what you need.** Use Grep/Glob to find the spot, then Read just those lines (offset/limit). Read a whole file only when you need all of it. Don't re-read a file you already read in this session unless it changed.
- **The task file is the shared memory.** The Tech Lead records what it found: reference files with line ranges, the places to change, the conventions. Use that instead of exploring the codebase again. Each repository's **knowledge** (`data/knowledge/<repo>/` in the Hive folder, local, never in the repo) is the Tech Lead's memory of it: `index.md` (what the repo is, its services, repo-wide conventions and commands; everything, for a single-service repo) plus one file per service of a monorepo (purpose, code map, APIs, entities, connections, conventions). Read the index and the files of the services you touch before searching the code. Each file records the commit it describes and the folders it covers; `python3 team/tools/knowledge.py status <project>` lists what changed in those folders since, so you know which parts to re-check. Only the Tech Lead writes it; a missing file never blocks anyone.
- **Run only what you need.** While working, run the tests for the code you changed; run the full suite once before handing off. Use quiet output and keep only the end of long output, e.g. `pytest -q 2>&1 | tail -30`, `dotnet test --nologo -v q 2>&1 | tail -40`, `npm test --silent 2>&1 | tail -40`.
- **Use the project's commands.** The "Conventions and commands" sections of the repository's knowledge list the quiet test, type-check and build commands. Use them as written.
- **Build only when needed.** To check that code compiles, prefer the type-check or compile check (faster, prints only errors). Run a full build (e.g. `ng build`) only when an acceptance criterion or the hand-off needs it.
- **Never start anything that doesn't exit:** dev servers (`ng serve`, `npm start`, `dotnet watch`), watch-mode tests (`ng test` without `--watch=false`), `docker compose up` without `-d`. They hang until the command times out and waste a turn.
- **Never dump large output:** no `ls -R` or unfiltered `find` over a repository, no `cat` of big, generated or lock files, logs or build output. Filter (`grep`, `head`, `tail`) first.
- **Keep replies to the lead short:** decisions, questions and results, not file contents.
