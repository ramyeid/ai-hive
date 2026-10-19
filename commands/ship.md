---
description: Run a task through the whole pipeline (pm → dev → reviewer) using subagents
argument-hint: <task id, e.g. TASK-004>
---
You are orchestrating the team for task $ARGUMENTS. Read `{{KIT}}/TEAM.md`.

1. Read `{{KIT}}/tasks/$ARGUMENTS-*.md`. If status is `draft`, stop and tell the lead it needs PM approval first.
2. If status is `ready-for-dev` or `changes-requested`: delegate to the **dev** subagent with "Work task $ARGUMENTS per your instructions." Wait for it.
3. If status is now `ready-for-review`: delegate to the **reviewer** subagent with "Review task $ARGUMENTS per your instructions."
4. If the reviewer returns `changes-requested`, loop back to step 2 — at most 3 rounds, then stop and report.
5. Stop immediately on `blocked` and show the lead the open question.
6. Finish with a 3-line summary: final status, rounds taken, anything the lead should look at.
