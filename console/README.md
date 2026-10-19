# Team Console

A local web app for running and managing the pm / dev / reviewer agents:
talk to each agent, approve what it wants to do, follow tasks across projects, read inboxes and past conversations.

## Start it

```bash
bash ~/Desktop/agent-team/console/start.sh
```

The first run creates a Python environment and installs three packages (about a minute).
Then it opens **http://127.0.0.1:8420** in your browser. Stop it with Ctrl+C.

Requirements:
- `install.sh` has been run once (it adds the task hook the agents rely on).
- Python 3.10 or newer (`brew install python@3.12` if you don't have it).
- You're logged in to Claude Code (`claude` works in your terminal). The console uses that same login.

## What you can do

| Page | What it's for |
|------|---------------|
| **Overview** | Each agent's status and what it's doing right now; every task placed in the stage it's in, coloured by who has it; what needs you; recent activity. |
| **Agent chats** (PM, Dev, Reviewer) | Talk to the agent. Start, stop, interrupt, or start a fresh session (like `/clear`). Approve or deny each action it asks to take. |
| **Tasks** | All tasks across projects, with filters. Open one to read the full spec, dev log and review, see its stage history, and hand it to an agent. |
| **Inbox** | Notifications for you and for each agent, and what's waiting on whom. Mark as read, or tell an agent to check its inbox. |
| **History** | Every past conversation. Read it, or continue it where it left off. |
| **Settings** | The folder agents start in (pick the one that holds your projects). |

## How it works

- `server/` is a small FastAPI app. Each agent runs as a Claude Code session through the
  [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python), using the agent's
  instructions from `../agents/` and your normal `~/.claude` settings (task hook and permission rules).
- When an agent wants to do something your settings don't already allow, it pauses and the request
  appears in its chat. Nothing runs until you allow it. You can switch an agent to allow file
  edits automatically from its chat header.
- Tasks, inboxes and activity are read straight from `../tasks/`, so the console, the terminal agents and
  the hook always agree. Conversations are saved in `data/` (not shared, not committed).
- It only listens on 127.0.0.1, and every request needs a key that only the page it serves knows, so
  other websites can't drive your agents.

## Developing

`python -m tests.run_fake` (from this folder, with `.venv` active) runs the console with a fake Claude,
handy for working on the UI without spending tokens.
