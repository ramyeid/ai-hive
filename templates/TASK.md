---
id: TASK-000
title: Short imperative title
project: PROJECT_PATH     # set by new_task.py — all work for this task happens in this folder
base: BASE_BRANCH        # branch to start from and review against
status: draft
priority: medium        # low | medium | high | urgent
branch: task/TASK-000-short-slug
pm: PM_ID                # who wrote the spec
dev:                     # set by claim.py: the dev building it (rework comes back to them)
reviewer:                # set by claim.py: the reviewer (re-reviews come back to them)
worktree:                # set by claim.py: the folder where the branch is checked out
created: YYYY-MM-DD
approved:               # pm: date the lead explicitly approved the final readback — required for ready-for-dev
---

## Problem / Goal
<!-- pm: why this matters, who it's for, what success looks like (measurable) -->

## User Stories
<!-- pm: As a <user>, I want <capability>, so that <benefit>. -->

## Acceptance Criteria
<!-- pm: numbered, testable, Given/When/Then, with exact inputs and expected outputs.
     Dev builds and tests exactly these; the reviewer verifies exactly these. Example:
     1. **Given** a logged-in user with role `viewer`, **when** they send `DELETE /items/42`,
        **then** the response is `403` with body `{"detail": "Forbidden"}`. -->

## Out of Scope
<!-- pm: what we are deliberately NOT doing, agreed with the lead -->

## Reference Implementations
<!-- pm: existing code the dev MUST read (the given line ranges) before writing anything and take as the model
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
<!-- pm: concrete rules taken from the references above (+ the project's docs/CONVENTIONS.md if it exists).
     Each rule specific enough that a reviewer can answer yes/no. Cover at least:
     naming, file/folder placement, structure/layering, error handling, logging,
     typing, tests (location, naming, fixtures), dependencies allowed. -->

## Technical Notes
<!-- pm: your research, so nobody repeats it: files and places to change (with line ranges),
     where things are registered/configured, test setup and the commands to run. dev may append. -->

## Clarifications
<!-- pm: every question asked and the lead's answer, in order. The audit trail of decisions. -->
| # | Question | Lead's answer |
|---|----------|---------------|

## Open Questions
<!-- anyone: unanswered = "- [ ] question"; answered = "- [x] question → answer".
     A task cannot become ready-for-dev while any "- [ ]" remains here. -->

## Definition of Ready
<!-- pm: tick only when actually true. Every box must be [x] before ready-for-dev (checked automatically). -->
- [ ] Goal and measurable success confirmed by the lead
- [ ] Every user role / actor and their permissions named
- [ ] Happy path described step by step
- [ ] Edge cases, invalid input and error behaviour specified (exact status codes / messages)
- [ ] Data: models, fields, validation, migrations, impact on existing data — covered or confirmed N/A
- [ ] Interfaces: API contracts, UI states and copy — covered or confirmed N/A
- [ ] Non-functional: performance, security, logging, config/env vars — covered or confirmed N/A
- [ ] Out of scope agreed with the lead
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
