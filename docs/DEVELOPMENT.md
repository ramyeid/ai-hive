# Development

## Repository layout

```
TEAM.md, PREFERENCES.md   the process, and how the lead wants things built (read by every agent)
agents/                   orchestrator, techlead, dev, reviewer, coach
commands/                 /board and /ship for Claude Code
templates/                TASK.md, KNOWLEDGE_*.md, PROPOSAL.md
scripts/                  the kit's tools, used by the agents and the console:
  tasklib.py                task files, locking, routing
  new_task.py, claim.py     creating and claiming tasks
  worktree.py               feature branches and worktrees
  on_task_change.py         the Claude Code hook: readiness checks, notifications, activity log
  check_ready.py            the readiness check before a task reaches a developer
  inbox.py, board.py        notifications and the board
  knowledge.py              the Tech Lead's notes per repository
  lead_review.py            the lead's code review (diffs, comments, rounds)
  coach.py                  the Coach's evidence and proposals
  orchestrate.py            the Orchestrator's controls (through the console)
console/
  server/                   FastAPI app
    main.py                   HTTP API, sign-in, the Orchestrator's API
    agents.py                 agent runners: status, sessions, approvals
    engines/                  claude.py (Claude Agent SDK), openai_compat.py (OpenAI-style APIs), tools.py
    ops.py                    team actions shared by the Orchestrator and Slack
    slack.py                  the Slack integration (Socket Mode)
    team.py                   proposals and the team's history (git)
    access.py, terminal.py, costs.py, chats.py, board.py, store.py
  web/                      the single-page app (vanilla JS, no build step)
  tests/                    console tests
tests/                    kit tests
brand/                    logos and icons
```

## Running the tests

Kit (from the repository folder):

```bash
python3 -m unittest tests/test_coach.py tests/test_lead_review.py tests/test_feature_branches.py tests/test_knowledge.py
python3 tests/test_multi_agent.py
python3 tests/test_reuse_gate.py
```

Console (from `console/`):

```bash
uv run python -m unittest tests/test_code_review.py tests/test_improvements.py tests/test_orchestrator.py \
  tests/test_slack.py tests/test_access.py tests/test_knowledge_api.py tests/test_task_chats.py
uv run python -m tests.test_engines
uv run python -m tests.test_team
uv run python -m tests.test_costs
uv run python -m tests.test_terminal
```

`uv run python -m tests.run_fake` starts the console with fake AI providers, for UI work without spending tokens.

Tests follow the rules in [`PREFERENCES.md`](../PREFERENCES.md): each test has three blocks (given, when, then)
separated by a blank line, with setup in clearly named private helpers.

## Dependencies

The console's dependencies are declared in `console/pyproject.toml` and pinned in `console/uv.lock`. Add one with
`uv add <package>`; never edit `uv.lock` by hand.

## Adding an AI provider

- A service with an OpenAI-style Chat Completions API and tool calling: add a `Provider(...)` entry in
  `console/server/engines/__init__.py`.
- Any other kind of API: implement `AgentEngine` (`console/server/engines/base.py`).

How well an agent works depends on the model following long instructions and calling tools reliably over many
steps; try a new model on a small task first.

## Adding an integration

Integrations are listed in **Settings → Integrations** (`INTEGRATIONS` in `console/web/app.js`). Team actions an
integration triggers should go through `console/server/ops.py`, so they behave exactly like the console's buttons.
