---
id: TASK-000
title: Short imperative title
project: PROJECT_PATH     # set by new_task.py — all work for this task happens in this folder
base: BASE_BRANCH        # branch to start from and review against: the lead's choice, any branch
status: draft
priority: medium        # low | medium | high | urgent
branch: BRANCH_NAME             # feature-<title>; shared by every follow-up task on this feature
follows: FOLLOWS                # set by new_task.py --follow-up: the earlier task whose feature this continues
from_commit:                    # set by claim.py: the branch's commit when the dev started; this task's changes are from_commit..HEAD
techlead: TECHLEAD_ID                # who wrote the spec
dev:                     # set by claim.py: the dev building it (rework comes back to them)
reviewer:                # set by claim.py: the reviewer (re-reviews come back to them)
worktree:                # set by claim.py: the folder where the branch is checked out
blocked_by:              # set automatically when the task goes to blocked: the agent that blocked it
created: YYYY-MM-DD
approved:               # techlead: date the lead explicitly approved the final readback — required for ready-for-dev
---

## Problem / Goal
<!-- techlead: why this matters, who it's for, what success looks like (measurable) -->

## User Stories
<!-- techlead: As a <user>, I want <capability>, so that <benefit>. -->

## Acceptance Criteria
<!-- techlead: numbered, testable, Given/When/Then, with exact inputs and expected outputs.
     Dev builds and tests exactly these; the reviewer verifies exactly these. Example:
     1. **Given** a logged-in user with role `viewer`, **when** they send `DELETE /items/42`,
        **then** the response is `403` with body `{"detail": "Forbidden"}`. -->

## Out of Scope
<!-- techlead: what we are deliberately NOT doing, agreed with the lead -->

## Existing Code to Reuse
<!-- techlead: answer this FIRST: does the project already do this, or nearly? Search every layer for code doing
     the same job on the same data (routes, controllers, services, queries, DTOs, UI components, API clients).
     A near-match is not a style reference: it's code to EXTEND (a parameter, a small refactor) instead of
     building a parallel copy. Fill in:
     **Searched:** the searches you ran, e.g. `grep -ril "invoice" src/`, routes under `/api/invoices`
     a table row per match (paths in backticks are checked and must exist), or one row saying nothing similar exists
     **Decision:** EXTEND <what, how> | REUSE <what> | NEW <why nothing above fits>, confirmed by the lead.
     For EXTEND, list every existing caller and how it stays working. -->
**Searched:**

| Existing code | What it already does | Overlap with this task |
|---------------|----------------------|------------------------|

**Decision:**

## Reference Implementations
<!-- techlead: existing code the dev MUST read (the given line ranges) before writing anything and take as the model
     for the new code — follow its patterns and style, NOT a literal copy. Shared logic gets
     reused/extracted, never duplicated.
     At least one row. Paths in backticks are checked automatically and must exist:
       - relative to the project folder, with the lines that show the pattern (`app/main.py:12-58`), or
       - absolute, for a similar project elsewhere on this machine (`/Users/me/proj/app/routers/users.py`), or
       - a URL.
     Only if nothing comparable exists anywhere: one row containing NEW PATTERN, with the
     pattern spelled out under Conventions and approved by the lead. -->
| Reference | Why it's similar | Patterns to follow |
|-----------|------------------|----------------|

## Conventions to Follow
<!-- techlead: concrete rules taken from the references above (+ the repository's knowledge files, if any).
     Each rule specific enough that a reviewer can answer yes/no. Cover at least:
     naming, file/folder placement, structure/layering, error handling, logging,
     typing, tests (framework, location, naming), dependencies allowed.
     Test shape is fixed for every project: given/when/then as three blocks separated by empty lines, named private setup helpers
     ("How tests are written" in PREFERENCES.md), even where the existing tests differ. -->

## Technical Notes
<!-- techlead: your research, so nobody repeats it: files and places to change (with line ranges),
     where things are registered/configured, test setup and the commands to run. dev may append. -->

## Clarifications
<!-- techlead: every question asked and the lead's answer, in order. The audit trail of decisions. -->
| # | Question | Lead's answer |
|---|----------|---------------|

## Open Questions
<!-- anyone: unanswered = "- [ ] question"; answered = "- [x] question → answer".
     A task cannot become ready-for-dev while any "- [ ]" remains here. -->

## Definition of Ready
<!-- techlead: tick only when actually true. Every box must be [x] before ready-for-dev (checked automatically). -->
- [ ] Base branch confirmed by the lead
- [ ] Goal and measurable success confirmed by the lead
- [ ] Every user role / actor and their permissions named
- [ ] Happy path described step by step
- [ ] Edge cases, invalid input and error behaviour specified (exact status codes / messages)
- [ ] Data: models, fields, validation, migrations, impact on existing data — covered or confirmed N/A
- [ ] Interfaces: API contracts, UI states and copy — covered or confirmed N/A
- [ ] Non-functional: performance, security, logging, config/env vars — covered or confirmed N/A
- [ ] Out of scope agreed with the lead
- [ ] Existing code searched; extend/reuse/new decided with the lead (no near-duplicate will be built)
- [ ] Reference implementations and conventions listed — dev knows which patterns and style to follow
- [ ] Every acceptance criterion is verifiable with concrete inputs and expected outputs
- [ ] Dev self-audit done: no implementation decision is left to the dev's judgement
- [ ] Every assumption confirmed by the lead and logged in Clarifications
- [ ] Lead approved the final readback

---

## Dev Log
<!-- dev: dated entries — approach, files changed, how to run, unit tests added -->

## Review Report
<!-- reviewer: dated entries — verdict, AC-by-AC verification, findings (blocker / should-fix / nit) with evidence -->
