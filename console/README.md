# Team Console

A local web app for running and managing the pm / dev / reviewer agents:
talk to each agent, approve what it wants to do, follow tasks across projects, read inboxes and past conversations.

## Start it

```bash
bash console/start.sh        # from the repository folder
```

The first run creates a Python environment and installs three packages (about a minute).
Then it opens **http://127.0.0.1:8420** in your browser. Stop it with Ctrl+C.

Requirements:
- `install.sh` has been run once (it adds the task hook the agents rely on).
- Python 3.10 or newer (macOS: `brew install python@3.12`).
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

## How it works

- `server/` is a small FastAPI app. `agents.py` handles what you see (status, history, approvals);
  each conversation runs in an engine from `server/engines/`: `claude.py` (Claude Code through the
  [Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python)) or `openai_compat.py` (OpenAI-style APIs).
  Both use the agent's instructions from `../agents/`.
- When an agent wants to do something your settings don't already allow, it pauses and the request
  appears in its chat. Nothing runs until you allow it. You can switch an agent to allow file
  edits automatically from its chat header.
- Tasks, inboxes and activity are read straight from `../tasks/`, so the console, the terminal agents and
  the hook always agree. Conversations are saved in `data/` (not shared, not committed).
- It only listens on 127.0.0.1, and every request needs a key that only the page it serves knows, so
  other websites can't drive your agents.

## Developing

From this folder, with `.venv` active:
- `python -m tests.test_engines` runs end-to-end checks of both engines against fake providers.
- `python -m tests.run_fake` runs the console with fake providers, handy for UI work without spending tokens.
