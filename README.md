# Agent Team: PM → Dev → QA

A three-agent software team for Claude Code, managed by you (the lead).
Agents hand off work through task files in `tasks/`; a hook notifies the next agent whenever a task's status changes.

```
You ──talk──► pm ──writes spec──► tasks/TASK-001-*.md  (ready-for-dev)
                                        │  hook → tasks/.inbox/dev.md + desktop notification
You ──talk──► dev ──builds + unit tests──► (ready-for-qa)
                                        │  hook → tasks/.inbox/qa.md
You ──talk──► qa ──e2e tests──► done  ─or─  changes-requested ──► back to dev
```

## Setup (once)

1. In this folder run `./setup.sh` — it copies `claude-config/` into `.claude/` and runs `git init` if needed.
   (To use an existing repo instead, copy this folder's contents into its root and run `./setup.sh` there.)
2. Requirements: Claude Code, Python 3.8+, git. Nothing to pip install.
3. Add `tasks/.inbox/` to `.gitignore` (notifications are local); commit everything else.

## Daily use — one terminal per agent

Open three terminal tabs in the repo and start each agent:

```bash
claude --agent pm     # tab 1
claude --agent dev    # tab 2
claude --agent qa     # tab 3
```

Then just talk to each one:

| Tab | You say | What happens |
|-----|---------|--------------|
| pm  | "Users need to reset their password by email." | PM interviews you, writes `TASK-001`, shows you the spec. |
| pm  | "Approved." | Status → `ready-for-dev`; dev gets notified. |
| dev | "Check your inbox." | Dev claims TASK-001, codes on `task/TASK-001-…`, hands to QA. |
| qa  | "Check your inbox." | QA writes e2e tests per acceptance criterion → `done` or `changes-requested`. |

From any tab (or a fourth "lead" tab):

- `/board` — overview of all tasks, plus anything blocked or done waiting on you.
- `/ship TASK-001` — hands-off mode: runs dev → qa (→ dev …, max 3 rounds) automatically as subagents.

## How the pieces fit

| File | Role |
|------|------|
| `CLAUDE.md` | Shared rules + lifecycle every agent obeys |
| `claude-config/` → `.claude/` | Source for the config below; `setup.sh` installs it |
| `.claude/agents/{pm,dev,qa}.md` | Each agent's persona, duties and limits |
| `.claude/settings.json` | Registers the status-change hook |
| `.claude/commands/{board,ship}.md` | Lead slash commands |
| `tasks/_TEMPLATE.md` | Task spec template (PM fills top, Dev Log & QA Report below) |
| `tasks/BOARD.md` | Auto-generated kanban view |
| `scripts/on_task_change.py` | Hook: routes notifications, regenerates the board |
| `scripts/inbox.py <role>` | What's waiting for a role |
| `scripts/new_task.py "<title>"` | Creates the next numbered task |

**Notification routing:** `ready-for-dev`, `changes-requested` → dev · `ready-for-qa` → qa · `blocked`, `done` → lead.

## Customise

- **E2E stack:** edit step 3 in `.claude/agents/qa.md` (default Playwright for web, HTTP client for APIs).
- **Models:** change `model:` in each agent file (e.g. `sonnet` for dev to save cost).
- **Permissions:** add an allow-list to `.claude/settings.json` so agents don't prompt for every `git`/test command.
- **Fully automatic dev pickup:** run `watch -n 30 python3 scripts/inbox.py dev --keep` in a pane, or schedule `claude -p --agent dev "Check your inbox and work the top task"` with cron.

## Run the app (FastAPI)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt   # runtime deps only: requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
curl http://127.0.0.1:8000/                     # → {"message":"Hello World"}
```

Run unit tests: `.venv/bin/pytest`
