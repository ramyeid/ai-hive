---
id: P-000
title: TITLE
status: pending          # pending | approved | rejected (set in the console by the lead)
tasks:                   # the tasks this is based on, e.g. TASK-012, TASK-019
created: YYYY-MM-DD
decided:
note:                    # the lead's note when approving or rejecting
commit:                  # the commit that applied it, once approved
---

## Why
<!-- The pattern you saw, why it happened, and the earliest point that would have prevented it
     (often a question the Tech Lead didn't ask). Two to five sentences. -->

## Evidence
<!-- One bullet per task: what happened, quoting the lead's own words where you can.
     - TASK-012: the lead wrote "errors are always { code, message }" after the dev returned a plain string. -->

## Change
<!-- One block per edit, in the order they apply. FILE is relative to the kit: agents/<role>.md, TEAM.md,
     PREFERENCES.md or templates/<name>.md. BEFORE is copied exactly from the file as it is now and must appear
     there exactly once (include enough surrounding text); leave BEFORE empty to add AFTER at the end of the file.
     Keep each edit small: change or add a few lines, never rewrite a section that works.
     Format (without the indentation):

        <<<<<<< PREFERENCES.md
        exact text as it is now
        =======
        the text it becomes
        >>>>>>>
-->
