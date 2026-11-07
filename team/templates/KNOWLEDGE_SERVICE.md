---
service: SERVICE_NAME
repo: REPO_NAME
path: PROJECT_PATH
scope: SCOPE             # the folders this service covers, comma-separated (e.g. services/orders/, libs/order-models/)
commit:                  # set by `knowledge.py stamp`: the commit this file describes. Never edit by hand.
branch:
updated:
updated_by:
---

<!-- The Tech Lead's memory of one service in a monorepo: what it has read while writing specs, so the next
     task starts here instead of re-reading the code. NOT documentation: fill in only what you actually read,
     and leave the rest as "Not explored yet." Repo-wide facts (build tool, shared conventions, how services
     talk) live in index.md; here, note only where this service differs.

     Rules:
     - It's an index, not a copy: names, one line on what each thing does, and where it lives
       (file path + function/class name). No code, no full schemas, no line numbers (they go stale).
     - Rewrite sections when you learn more; don't append. Keep this file under ~250 lines; if the service
       outgrows that, split a sub-area into its own service file with its own scope.
     - The code is the truth. Use this to know where to look; read the real code before putting anything in
       a spec. `knowledge.py status <project> --service SERVICE_NAME` shows what changed in `scope` since `commit`. -->

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
     test framework and locations. The shape of each test is fixed by Hive's team/PREFERENCES.md, not here.
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
