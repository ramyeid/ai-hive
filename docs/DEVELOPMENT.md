# Development

## Repository layout

```
team/                       everything about the team (the Coach proposes changes to the Markdown here)
  TEAM.md, PREFERENCES.md     the process, and how the lead wants things built (read by every agent)
  agents/                     orchestrator, techlead, dev, reviewer, coach
  templates/                  TASK.md, KNOWLEDGE_*.md, PROPOSAL.md
  tools/                      what the agents run (standard library only), also used by the backend:
    tasklib.py                  task files, locking, routing, where data lives
    new_task.py, claim.py       creating and claiming tasks
    worktree.py                 feature branches and worktrees
    on_task_change.py           the Claude Code hook: readiness checks, notifications, activity log
    check_ready.py              the readiness check before a task reaches a developer
    inbox.py, board.py          notifications and the board
    knowledge.py                the Tech Lead's notes per repository
    lead_review.py              the lead's code review (diffs, comments, rounds)
    coach.py                    the Coach's evidence and proposals
    orchestrate.py              the Orchestrator's controls (through the console)
  tests/
backend/
  pyproject.toml, uv.lock
  src/hive/                   the FastAPI app
    main.py                     HTTP API, sign-in, the Orchestrator's API
    agents.py                   agent runners: status, sessions, approvals
    engines/                    claude.py (Claude Agent SDK), openai_compat.py (OpenAI-style APIs), tools.py
    ops.py                      team actions shared by the Orchestrator and Slack
    slack.py                    the Slack integration (Socket Mode)
    team.py                     proposals and the team's history (git)
    store.py                    settings and sessions; where every folder is
    access.py, terminal.py, costs.py, chats.py, board.py
  tests/                      with fakes/ (a fake Claude and a fake OpenAI-style API)
frontend/src/               the single-page app (vanilla JS, no build step), served at /static
integrations/slack/         the Slack app manifest
scripts/                    install.sh, start.sh, stop.sh
assets/                     logos and icons, served at /assets
docs/
data/                       local only, never committed: tasks/, knowledge/, coach/, console/ (settings, sessions)
```

## Running the tests

The team's tools (from the Hive folder):

```bash
python3 -m unittest discover team/tests
```

The backend (from `backend/`):

```bash
uv run python -m unittest discover tests
uv run python -m tests.test_engines
uv run python -m tests.test_team
uv run python -m tests.test_costs
uv run python -m tests.test_terminal
```

`uv run python -m tests.fakes.server` starts the console with fake AI providers, for UI work without spending tokens.

Tests follow the rules in [`PREFERENCES.md`](../team/PREFERENCES.md): each test has three blocks (given, when, then)
separated by a blank line, with setup in clearly named private helpers.

## Dependencies

The backend's dependencies are declared in `backend/pyproject.toml` and pinned in `backend/uv.lock`. Add one with
`uv add <package>` in `backend/`; never edit `uv.lock` by hand.

## Adding an AI provider

- A service with an OpenAI-style Chat Completions API and tool calling: add a `Provider(...)` entry in
  `backend/src/hive/engines/__init__.py`.
- Any other kind of API: implement `AgentEngine` (`backend/src/hive/engines/base.py`).

How well an agent works depends on the model following long instructions and calling tools reliably over many
steps; try a new model on a small task first.

## Adding an integration

Integrations are listed in **Settings → Integrations** (`INTEGRATIONS` in `frontend/src/app.js`). Team actions an
integration triggers should go through `backend/src/hive/ops.py`, so they behave exactly like the console's buttons.
