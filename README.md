# Agent Team: PM → Dev → Reviewer

One product manager, one developer and one reviewer for Claude Code, installed once and usable on **any project on your machine**.
You talk to each agent; they hand work to each other through one task board.

```
You ──► pm ──interviews you until nothing is unknown──► task (project: ~/code/my-api)
              readiness check passes + you approve ──► ready-for-dev ──► notifies dev
You ──► dev ──works in the task's project: simplest code that fits + unit tests──► ready-for-review
You ──► reviewer ──business need · consistency · simplicity──► done   or   changes-requested ──► dev
```

## Get started

Requirements: [Claude Code](https://code.claude.com) (logged in), Python 3, git. macOS or Linux.

```bash
git clone git@github.com:ramyeid/team-agents.git ~/team-agents
bash ~/team-agents/install.sh
```

`install.sh` puts the agents and the `/board` and `/ship` commands into `~/.claude/`, and adds the task
hook to `~/.claude/settings.json`. Your existing settings are kept, and a backup is saved as `settings.json.bak`.
It overwrites any personal agents or commands with the same names (`pm`, `dev`, `reviewer`, `board`, `ship`).

**Updating:** `git pull`, then run `install.sh` again. Do the same if you move the folder.

**Your board is yours.** `tasks/` and the console's `data/` stay on your machine and are not committed:
task files hold paths from your laptop and details of your projects. Each person has their own board.

**Changing an agent:** edit the files in `agents/`, `TEAM.md` or `templates/`, run `install.sh`, and open a pull
request so everyone gets the improvement.

## Daily use

Open three terminals in the folder that holds your projects (e.g. `~/code`) — the agents can then
work in any project under it without permission prompts:

```bash
claude --agent pm         # tab 1
claude --agent dev        # tab 2
claude --agent reviewer   # tab 3
```

| Tab | You say | What happens |
|-----|---------|--------------|
| pm | "In `~/code/my-api`: users need to reset their password by email." | PM studies that project, then asks you questions in rounds (with suggested answers) until nothing is unknown. |
| pm | "approved" | Readiness check runs. Pass → `ready-for-dev`, dev notified. Fail → back to `draft`, with the reasons. |
| dev | "Check your inbox." | Dev sees tasks from every project, goes to the task's project, builds exactly what's asked (KISS, consistent with that codebase), self-reviews, hands off. |
| reviewer | "Check your inbox." | Reviewer reads the change in that project and checks business need, consistency, simplicity → `done` or `changes-requested`. |

- `/board` (in any tab): every task across all projects, plus anything blocked or waiting on you.
- `/ship TASK-007`: runs dev → reviewer (→ dev …, max 3 rounds) automatically.
- **Between tasks**, type `/clear` in the dev and reviewer tabs so nothing carries over from another project.
- Want two projects moving at once? Open a second `claude --agent dev` tab — same agent, separate task.

## Prefer a browser?

`bash console/start.sh` opens the **Team Console** at http://127.0.0.1:8420: chat with each agent,
approve their actions, start and stop them, and see tasks, inboxes and history. See `console/README.md`.

## What lives where

```
team-agents/              ← this repository: the only copy of the agents and rules
├── TEAM.md               shared rules + lifecycle every agent follows
├── agents/               pm.md · dev.md · reviewer.md   (installed into ~/.claude/agents)
├── commands/             board.md · ship.md             (installed into ~/.claude/commands)
├── templates/            TASK.md (task spec) · CONVENTIONS.md (per-project conventions + commands)
├── scripts/              new_task · inbox · board · check_ready · on_task_change
├── tasks/                ← your board: TASK-*.md for all projects + BOARD.md (not committed)
├── console/              ← the Team Console web app (optional)
└── install.sh
```

Your projects get nothing from the kit — only the dev's commits on `task/TASK-…` branches.
Each task records `project:` (its folder) and `base:` (the branch it starts from and is reviewed against; main/master detected automatically).

**Routing:** `ready-for-dev`, `changes-requested` → dev · `ready-for-review` → reviewer · `blocked`, `done` → you.

## Uninstall

Delete `~/.claude/agents/{pm,dev,reviewer}.md` and `~/.claude/commands/{board,ship}.md`, and remove the
`on_task_change.py` hook and the agent-team entries under `permissions` in `~/.claude/settings.json`.
