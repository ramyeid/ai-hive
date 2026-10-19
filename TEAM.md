# Team workflow (shared by all agents)

Three agents — **pm**, **dev**, **reviewer** — managed by a human lead, working on any project on this laptop.
The central task board in `tasks/` covers all projects. (Paths in this file are relative to the kit folder, where this file lives.) It is the single source of truth and the only handoff channel.

## Task lifecycle

```
draft ──► ready-for-dev ──► in-dev ──► ready-for-review ──► in-review ──► done
  (pm)        (pm)          (dev)          (dev)             (reviewer)   (reviewer)
                               ▲                                 │
                               └─────── changes-requested ◄──────┘
                                            (reviewer)
```

| Status              | Set by   | Meaning                                              |
|---------------------|----------|------------------------------------------------------|
| `draft`             | pm       | Being written; not ready for anyone else             |
| `ready-for-dev`     | pm       | Spec + acceptance criteria approved by the lead      |
| `in-dev`            | dev      | Dev has claimed it                                   |
| `ready-for-review`  | dev      | Committed on the task branch, unit tests pass        |
| `in-review`         | reviewer | Reviewer has claimed it                              |
| `changes-requested` | reviewer | Findings to fix; see the Review Report section       |
| `done`              | reviewer | Business need met, consistent, simple — accepted     |
| `blocked`           | anyone   | Needs a decision from the lead; say why in the file  |

## Rules every agent follows

1. One task = one file: `tasks/TASK-<NNN>-<slug>.md`, created only with `python3 scripts/new_task.py <project-folder> "<title>"`.
   Its `project:` field is the folder where all the task's work happens; `base:` is the branch it starts from and is reviewed against.
2. Only change the `status:` field to a value your role is allowed to set (table above).
3. Never delete another role's section. Append to your own section; add dated entries.
4. If anything is ambiguous, set `status: blocked`, write the question under **Open Questions**, and stop. The lead decides.
5. Work inside the task's `project:` folder, on the git branch named in `branch:`, created from `base:`. Never touch other projects.
6. Keep `tasks/BOARD.md` out of your edits — it is regenerated automatically.
7. A task only reaches `ready-for-dev` when `scripts/check_ready.py` passes (no open questions, references to follow, Definition of Ready ticked, lead approval dated). The hook enforces this and reverts it to `draft` otherwise.
8. Consistency beats cleverness: the whole codebase should look like one author wrote it. New code is highly inspired by the task's **Reference Implementations** (same patterns and style, not copy-paste; shared logic is reused, never duplicated) and follows **Conventions to Follow**.
9. KISS above all: build exactly what the task asks with the simplest code that works. No boilerplate, no speculative abstractions, no clever code.
