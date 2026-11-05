# Team Console

A local web app for running and managing the techlead / dev / reviewer agents:
talk to each agent, approve what it wants to do, follow tasks across projects, read inboxes and past conversations.

## Start it

```bash
bash console/start.sh        # from the repository folder
```

The first run installs the dependencies pinned in `uv.lock` (and a suitable Python, if this machine lacks one) with
[uv](https://docs.astral.sh/uv/), in about a minute; later starts take a second.
Then it opens **http://127.0.0.1:8420** in your browser. Stop it with Ctrl+C.

**On a server, or to keep it running after you close the terminal**, run it in the background:

```bash
bash console/service-start.sh    # starts it; output goes to console/service.log
bash console/service-stop.sh     # stops it (running agents are stopped first)
tail -f console/service.log      # follow the log
```

`service-start.sh` won't start a second copy, and reports the error from the log if the console fails
to start (for example, when port 8420 is already in use). Use `PORT=8500 bash console/service-start.sh` for
another port. It doesn't restart the console after a crash or a reboot: for that, run it as a system service
(systemd on Linux).

Requirements:
- `install.sh` has been run once (it adds the task hook the agents rely on).
- [uv](https://docs.astral.sh/uv/) (macOS: `brew install uv`; Linux: `curl -LsSf https://astral.sh/uv/install.sh | sh`).
  It provides Python 3.10+ itself. If you start the console from a service manager or cron, make sure `uv` is on
  that environment's `PATH` (the Linux installer puts it in `~/.local/bin`).
- You're logged in to Claude Code (`claude` works in your terminal). The console uses that same login.

## What you can do

| Page | What it's for |
|------|---------------|
| **Overview** | Each agent's status and what it's doing right now; every task placed in the stage it's in, coloured by who has it; what needs you; recent activity. |
| **Agent chats** (Tech Lead, Dev 2, Reviewer…) | Talk to the agent. Start, stop, interrupt, or start a fresh session (like `/clear`). Approve or deny each action it asks to take. |
| **Tasks** | All tasks across projects, with filters. Open one to read the full spec, dev log and review, see its stage history, and hand it to an agent. Under **Who worked on it**, each agent's conversation on the task (who, when, the hand-off, cost), for debugging. |
| **Inbox** | Notifications for you and for each agent, and what's waiting on whom. Mark as read, or tell an agent to check its inbox. |
| **Knowledge** | The Tech Lead's memory of each repository (`knowledge/<repo>/`): an index, plus one file per service of a monorepo, with purpose, code map, APIs, entities, conventions and task history. Each file shows how many files changed in its own folders since it was written. Read-only. |
| **History** | Every past conversation. Read it, or continue it where it left off. |
| **Improvements** | Start a review with the Coach, and approve, edit or reject what it proposes: each proposal shows the exact change, why, and the tasks behind it. |
| **Team history** | Every change to the team's instructions, newest first: who (the Coach or a person), when, why, and the diff. Read the team as it was at any change, or undo one. |
| **Settings** | Your team: add, remove and rename Tech Leads, devs and reviewers (e.g. 2 Tech Leads, 3 devs, 2 reviewers). Each gets a random name, shown as "Kareem (Tech Lead)". The folder agents start in (pick the one that holds your projects). Provider keys and model prices. |

## Conversations per task, and no more /clear

When an agent hands a task on (Tech Lead → ready-for-dev, dev → ready-for-review, reviewer → done or
changes-requested), the console saves that conversation with the task and starts the agent on a fresh one once
its turn ends. You don't need to start a new session between tasks.

Each task's conversations are kept in `tasks/chats/TASK-NNN/`, one `.md` (readable) and one `.json` per agent
conversation, with when it started and finished and how it ended. Open them from the task page under **Who
worked on it**. They're for your debugging only: agents never read them and work only from the task file.
Conversations are also saved when you stop an agent or start a new session. Agents run from a terminal
(`claude --agent dev`) aren't recorded, and still need `/clear` between tasks.

## Terminal

A **Terminal** page gives you a shell on the machine the console runs on, in the browser. It's on by
default; to turn it off, start the console with:

```bash
ENABLE_TERMINAL=0 bash service-start.sh     # or: ENABLE_TERMINAL=0 ./start.sh
```

Open as many shells as you need with **New shell**: they're laid out two per row (1 and 2 side by side,
3 under 1, 4 next to 3, and so on), each with a × to close it. Shells start in the agents' home folder,
run as the user the console runs as, keep running while you use other pages, and end when you close the
browser tab (or type `exit`).

**Anyone who can open the console can run any command on that machine.** Keep the console itself
protected: on your own laptop it only listens on 127.0.0.1; on a server, keep it behind your login and
IP allowlist, or turn the terminal off. Like every other request, the terminal needs the key that only the page the
console serves knows, and it refuses requests made for any other host name.

Behind nginx, add these lines to the `location` block so the terminal's WebSocket gets through:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## Choosing the AI provider

Each agent can run on a different provider and model. Pick them in the agent's chat header while it's stopped.

| Provider | How it runs | Key |
|----------|-------------|-----|
| Claude | Claude Code: its own tools, your `~/.claude` permission rules and task hook | Claude Code login, `ANTHROPIC_API_KEY` or Bedrock/Vertex |
| OpenAI, DeepSeek, Qwen, Kimi | The console's own agent loop with Read, Write, Edit, Glob, Grep and Bash | Settings page, or `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`, `DASHSCOPE_API_KEY`, `MOONSHOT_API_KEY` |

Keys saved in Settings stay in `data/settings.json` on the server (readable only by you) and are never sent back to the browser.
An environment variable wins over a saved key. The API address can be changed per provider (regions, China endpoints).

How well an agent works depends on the model: the workflow needs it to follow long instructions and call tools
reliably over many steps. Try a new model on a small task first.

**Adding a provider:** any service with an OpenAI-style Chat Completions API and tool calling needs only a new
`Provider(...)` entry in `server/engines/__init__.py`. A different kind of API needs a new engine class implementing
`AgentEngine` (`server/engines/base.py`).

## What each task cost

Every task shows its cost so far, from the Tech Lead's spec to the review, broken down by model and agent
(Tasks page and each task's page). Each agent turn is charged to the task(s) it worked on: task IDs
you mention, task files it reads or edits, IDs in its commands, or the task the Tech Lead creates. A turn
that touches no task counts toward the task that conversation worked on last; a turn touching
several tasks is split between them.

Claude costs are Claude Code's own figures (with a subscription login they're an estimate of
the equivalent API price). OpenAI, DeepSeek, Qwen and Kimi report tokens only: enter each model's
price under **Settings → Model prices**. Prices apply to past conversations too.

## How it works

- `server/` is a small FastAPI app. `agents.py` handles what you see (status, history, approvals);
  each conversation runs in an engine from `server/engines/`: `claude.py` (Claude Code through the
  [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python)) or `openai_compat.py` (OpenAI-style APIs).
  Both use the agent's instructions from `../agents/`. Each agent runs with its own `AGENT_ID`
  (`dev-2`…), which the kit's scripts use to claim tasks and route rework (see "Several agents per
  role" in the main README).
- When an agent wants to do something your settings don't already allow, it pauses and the request
  appears in its chat. Nothing runs until you allow it. You can switch an agent to allow file
  edits automatically from its chat header.
- Tasks, inboxes and activity are read straight from `../tasks/`, so the console, the terminal agents and
  the hook always agree. Conversations are saved in `data/` (not shared, not committed).
- It only listens on 127.0.0.1, and every request needs a key that only the page it serves knows, so
  other websites can't drive your agents.

## Developing

Dependencies live in `pyproject.toml`, pinned in `uv.lock`. Add one with `uv add <package>` (it updates both);
never edit `uv.lock` by hand. From this folder:
- `uv run python -m tests.test_engines` runs end-to-end checks of both engines against fake providers.
- `uv run python -m tests.test_costs` checks how costs are charged to tasks.
- `uv run python -m tests.test_team` checks adding and removing agents.
- `uv run python -m unittest tests/test_knowledge_api.py` checks the Knowledge page's API.
- `uv run python -m tests.test_terminal` checks the browser terminal (on by default, can be turned off, key required, real shell).
- `python3 ../tests/test_multi_agent.py` checks claims, worktrees and routing with several agents per role.
- `uv run python -m tests.run_fake` runs the console with fake providers, handy for UI work without spending tokens.
