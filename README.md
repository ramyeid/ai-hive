# Agent Team: Tech Lead → Dev → Reviewer

One tech lead (a staff engineer who designs and specs the work), one developer and one reviewer for Claude Code, installed once and usable on **any project on your machine**.
You talk to each agent; they hand work to each other through one task board.

```
You ──► techlead ──interviews you until nothing is unknown──► task (project: ~/code/my-api)
              readiness check passes + you approve ──► ready-for-dev ──► notifies dev
You ──► dev ──works in the task's project: simplest code that fits + unit tests──► ready-for-review
You ──► reviewer ──requirements met · consistent with existing code──► done   or   changes-requested ──► dev
```

## Get started

Requirements: [Claude Code](https://code.claude.com) (logged in), Python 3 (for the kit's scripts), git. macOS or Linux.
The console also needs [uv](https://docs.astral.sh/uv/), which installs its dependencies.

```bash
git clone git@github.com:ramyeid/team-agents.git ~/team-agents
bash ~/team-agents/install.sh
```

`install.sh` puts the agents and the `/board` and `/ship` commands into `~/.claude/`, and adds the task
hook to `~/.claude/settings.json`. Your existing settings are kept, and a backup is saved as `settings.json.bak`.
It overwrites any personal agents or commands with the same names (`techlead`, `dev`, `reviewer`, `coach`, `board`, `ship`).

**Updating:** `git pull`, then run `install.sh` again. Do the same if you move the folder.

**Your board is yours.** `tasks/` and the console's `data/` stay on your machine and are not committed:
task files hold paths from your laptop and details of your projects. Each person has their own board.

**Changing an agent:** edit the files in `agents/`, `TEAM.md`, `PREFERENCES.md` or `templates/`, run `install.sh`,
and open a pull request so everyone gets the improvement. Or let the Coach propose changes (below).

## Reviewing the code yourself

Open a task in the console and press **Review the code** (also on the Dev's and Reviewer's chat pages). You get a
pull-request view of the branch: the whole feature against its base, only this task's commits, or what changed
since your last review. Comment on any line (hover it and press **+**) or on the whole change, then:

- **Request changes**: your comments are added to the task file under **Lead Review**, and the task goes back to
  the dev who built it (started and told, in the console). The dev fixes the code on the same branch, answers each
  comment, and hands it to the reviewer, who checks every comment was handled. Then it's back with you, if you want.
- **Approve**: records your approval; the task stays where it is. The reviewer always has the last word before `done`.

Reviewing is optional, and you can do it as often as you like, before or after the reviewer (also on a `done`
task). Nothing is pushed: the branch stays local until you push it. Your comments are also the Coach's strongest
evidence (below).

## Teaching the team: the Coach

`PREFERENCES.md` says how you want things built (code shape, reuse, simplicity, how tests are written, and
whatever else you add); every agent reads it. `TEAM.md` keeps the process.

Now and then, start a review with the **Coach** (console → **Improvements**, or `claude --agent coach`). It reads
how finished tasks went: your code-review comments (with the code they were about and what the dev changed),
your own words in the agents' conversations, your answers in Clarifications, review
rounds, follow-ups, and your commits and comments on the GitHub pull requests (`gh` must be logged in; agent
commits carry an `Agent:` line, so anything without one is yours). It asks you about anything unclear, then
proposes small, exact changes to `PREFERENCES.md`, the agents' files, `TEAM.md` or the task template, each with
its evidence. Nothing changes until you approve; approved changes are committed one by one, so the console's
**Team history** shows every version of the team, with diffs and undo. It runs on Opus, thinking hard, so a
review costs more than a task; you decide when.

## Daily use

Open three terminals in the folder that holds your projects (e.g. `~/code`) — the agents can then
work in any project under it without permission prompts:

```bash
claude --agent techlead         # tab 1
claude --agent dev        # tab 2
claude --agent reviewer   # tab 3
```

| Tab | You say | What happens |
|-----|---------|--------------|
| techlead | "In `~/code/my-api`: users need to reset their password by email." | Tech Lead studies that project, then asks you questions in rounds (with suggested answers) until nothing is unknown. |
| techlead | "approved" | Readiness check runs. Pass → `ready-for-dev`, dev notified. Fail → back to `draft`, with the reasons. |
| dev | "Check your inbox." | Dev sees tasks from every project, goes to the task's project, builds exactly what's asked (KISS, consistent with that codebase), self-reviews, hands off. |
| reviewer | "Check your inbox." | Reviewer reads the change in that project and checks that the requirements are met and the code is consistent with what exists → `done` or `changes-requested`. |

- `/board` (in any tab): every task across all projects, plus anything blocked or waiting on you.
- `/ship TASK-007`: runs dev → reviewer (→ dev …, max 3 rounds) automatically.
- **Between tasks**, type `/clear` in the dev and reviewer tabs so nothing carries over from another project.

## Several agents per role

Need two Tech Leads, three devs and two reviewers? Give each terminal its own ID with `AGENT_ID`
(the role, then `-2`, `-3`…):

```bash
claude --agent techlead                          # techlead
AGENT_ID=techlead-2 claude --agent techlead
claude --agent dev                         # dev
AGENT_ID=dev-2 claude --agent dev
AGENT_ID=dev-3 claude --agent dev
claude --agent reviewer                    # reviewer
AGENT_ID=reviewer-2 claude --agent reviewer
```

In the console, add and remove agents under **Settings → Team**; each one gets its ID automatically,
and a random name (Kareem, Aliaa, Hossam…) shown as "Kareem (Tech Lead)". Rename them there or from their
chat header. Names are only for you: scripts and task files use the IDs.

- **No double work.** An agent claims a task before starting it (`scripts/claim.py`). Claims are
  atomic, so if two devs reach for the same task, one gets it and the other picks another.
- **One branch per feature, `feature-<title>`**, in its own git worktree next to the project:
  `~/code/my-api.worktrees/feature-filter-orders-by-status`. Follow-up tasks on the same feature (more
  changes, a fix, a misunderstanding cleared up: ask the Tech Lead for a follow-up to TASK-007) add commits
  to that branch instead of creating a new one. Devs never share a checkout, and your own
  `~/code/my-api` stays on its branch untouched.
- **Rework goes back to the dev who built it, re-reviews to the same reviewer**, so nobody has to
  relearn the task. New work goes to a shared pool every agent of the role sees.
- **When a task is `done`**, the reviewer removes its worktree (`python3 scripts/worktree.py remove
  TASK-007`). The branch stays: merge it as usual. If it couldn't be removed (uncommitted files),
  remove it yourself with `git -C ~/code/my-api worktree remove ../my-api.worktrees/feature-…`. The folder is kept while a follow-up on the same branch isn't done.
- The task file records who has it (`techlead:`, `dev:`, `reviewer:`, `worktree:`). If you remove an
  agent while it holds a task, clear its name in the task file so another agent of the role can take it.

## Prefer a browser?

`bash console/start.sh` opens the **Team Console** at http://127.0.0.1:8420: chat with each agent,
approve their actions, start and stop them, and see tasks, inboxes and history. See `console/README.md`.

## What lives where

```
team-agents/              ← this repository: the only copy of the agents and rules
├── TEAM.md               how the team works: lifecycle, branches, hand-offs
├── PREFERENCES.md        how you want things built; every agent follows it
├── agents/               techlead.md · dev.md · reviewer.md · coach.md   (installed into ~/.claude/agents)
├── commands/             board.md · ship.md             (installed into ~/.claude/commands)
├── templates/            TASK.md (task spec) · KNOWLEDGE_*.md (knowledge files) · PROPOSAL.md (Coach)
├── scripts/              new_task · claim · inbox · board · check_ready · knowledge · coach · on_task_change …
├── tasks/                ← your board: TASK-*.md for all projects + BOARD.md; reviews/ = your code reviews (not committed)
├── knowledge/            ← the Tech Lead's memory: one folder per repository it has worked on (not committed)
├── coach/                ← the Coach's evidence and proposals (not committed)
├── console/              ← the Team Console web app (optional)
└── install.sh
```

Your projects get nothing from the kit — only the dev's commits on `feature-…` branches.
Each task records `project:` (its folder) and `base:` (the branch it starts from and is reviewed against; the Tech Lead proposes the branch you have checked out and asks you to confirm it).

**Knowledge:** each time the Tech Lead writes a spec, it records what it learned in `knowledge/<repo>/`:
`index.md` for the repository (and everything, for a single-service repo), plus one file per service of a
monorepo, each covering its own folders. Files hold purpose, code map, APIs, entities, connections,
conventions and commands, and the commit they describe. The next task starts from them, re-checking only
what changed in git in those folders since, instead of re-reading the code. Read them in the console's
**Knowledge** page.

**Routing:** `ready-for-dev`, `changes-requested` (from the reviewer or your own review) → the dev who built it · `ready-for-review` → reviewer · `blocked`, `done` → you.

## Uninstall

Delete `~/.claude/agents/{techlead,dev,reviewer}.md` and `~/.claude/commands/{board,ship}.md`, and remove the
`on_task_change.py` hook and the agent-team entries under `permissions` in `~/.claude/settings.json`.
