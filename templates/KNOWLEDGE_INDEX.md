---
repo: REPO_NAME
path: PROJECT_PATH
scope:                   # empty = the whole repo (single-service repo). In a monorepo: the repo-wide files only
                         # (root config, build files, shared tooling), e.g. package.json, nx.json, .github/
commit:                  # set by `knowledge.py stamp`: the commit this file describes. Never edit by hand.
branch:
updated:
updated_by:
---

<!-- The Tech Lead's memory of this repository: what it has read while writing specs, so the next task
     starts here instead of re-reading the code. NOT documentation: fill in only what you actually read,
     and leave the rest as "Not explored yet."

     Single-service repo: everything goes in this file; leave the Services table with its one line.
     Monorepo: this file holds what the repo is, its services and shared packages, how they connect, and
     repo-wide conventions and commands. Each service gets its own file (`knowledge.py new <project>
     --service <name> --scope <folders>`), which adds its row below. Leave APIs and Entities here empty.

     Rules:
     - It's an index, not a copy: names, one line on what each thing does, and where it lives
       (file path + function/class name). No code, no full schemas, no line numbers (they go stale).
     - Rewrite sections when you learn more; don't append. Keep this file under ~150 lines in a monorepo,
       ~250 in a single-service repo.
     - The code is the truth. Use this to know where to look; read the real code before putting anything in
       a spec. `knowledge.py status <project>` shows what changed since `commit`, for every file. -->

## Services and packages
<!-- Monorepo: one row per service or shared package you know of (a row without a file is fine: not explored yet). -->
| Name | Folder | What it is | Knowledge file |
|------|--------|------------|----------------|
| (whole repo) | / | Single service: everything is in this file. | index.md |

## Purpose
<!-- What this service is for, who uses it, in 2–4 sentences. -->
Not explored yet.

## Code map
<!-- Where each kind of code lives: routes/controllers, services, data access, jobs, UI, tests, config.
     One line each: `src/orders/` → order API and its services. -->
Not explored yet.

## APIs
<!-- One row per endpoint (or public function / message handler) you've read. -->
| Method | Path | What it does | Where |
|--------|------|--------------|-------|

## Entities
<!-- What this service saves, reads or owns. One row each. -->
| Entity | What it represents | Stored in | Where |
|--------|--------------------|-----------|-------|

## Connections
<!-- Services it calls and that call it, queues/events published and consumed, external APIs, databases. -->
Not explored yet.

## Configuration
<!-- Environment variables, feature flags, settings that change behaviour. -->
Not explored yet.

## Auth and permissions
<!-- How requests are authenticated; how roles/permissions are checked, and where. -->
Not explored yet.

## Conventions and commands
<!-- How this codebase is written (derived from the code): structure, naming, error handling, data access,
     test framework and locations. The shape of each test is fixed by the kit's TEAM.md, not here.
     Commands, quiet, from the project root:
       tests for the code you changed / full suite / type-check or compile check / build / lint,
       and what never to run (servers, watch modes). -->
Not explored yet.

## Gotchas
<!-- What would surprise the next person: quirks, known duplicates, legacy areas not to copy. -->
Nothing noted yet.

## Task history
<!-- One line per task on this service: TASK-012 Filter orders by status (extended GET /api/orders). -->

## Coverage
<!-- Which areas you've actually read, and which you haven't. "Not in this file" only means "doesn't
     exist" for areas listed as read. -->
- Read:
- Not read yet: everything else.
