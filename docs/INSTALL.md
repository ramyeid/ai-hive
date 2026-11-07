# Installation

## Requirements

| | |
|---|---|
| OS | macOS or Linux |
| [Claude Code](https://code.claude.com) | Installed and logged in (`claude` works in your terminal) |
| Python 3 | For the kit's scripts |
| git | Each feature gets its own branch and worktree |
| [uv](https://docs.astral.sh/uv/) | For the console. macOS: `brew install uv`. Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [GitHub CLI](https://cli.github.com) (optional) | Logged in (`gh auth login`), so the Coach can read your pull requests |

## Install

```bash
git clone git@github.com:ramyeid/hive-ai-squad.git ~/hive-ai-squad
bash ~/hive-ai-squad/install.sh
```

`install.sh`:
- copies the agents into `~/.claude/agents/` and the `/board` and `/ship` commands into `~/.claude/commands/`;
- adds the task hook and the kit's permissions to `~/.claude/settings.json`, keeping your settings and saving a backup as `settings.json.bak`.

It replaces any personal agents or commands with the same names: `orchestrator`, `techlead`, `dev`, `reviewer`,
`coach`, `board`, `ship`.

## Start the console

```bash
bash console/start.sh
```

The first start installs the console's dependencies (pinned in `console/uv.lock`) in about a minute, then opens
**http://127.0.0.1:8420**. Stop it with Ctrl+C.

To keep it running in the background:

```bash
bash console/service-start.sh    # output goes to console/service.log
bash console/service-stop.sh
```

Use `PORT=8500` for another port. `service-start.sh` doesn't restart the console after a crash or reboot; use your
system's service manager (systemd, launchd) for that, with `uv` on its `PATH`.

## Update

```bash
git pull
bash install.sh
```

Then restart the console. Run `install.sh` again too if you move the folder.

## Run on a server

By default the console answers only on the machine it runs on. To open it from your laptop and phone (for example
on a server behind your VPN), choose one:

- **Behind your reverse proxy** (nginx with its own login or IP allowlist): keep the console on 127.0.0.1.
- **On the network, with a password** each browser signs in with once (valid for 30 days):

```bash
HOST=0.0.0.0 \
CONSOLE_HOSTS=hive.internal.example.com \
CONSOLE_PASSWORD='a long password' \
CONSOLE_URL=http://hive.internal.example.com:8420 \
bash console/service-start.sh
```

| Variable | Purpose |
|---|---|
| `HOST` | Address to listen on (`127.0.0.1` by default) |
| `CONSOLE_HOSTS` | Host names allowed to reach the console, comma-separated; any other name is refused |
| `CONSOLE_PASSWORD` | Required with `CONSOLE_HOSTS` (8 characters or more) |
| `CONSOLE_URL` | The address used in links from Slack and the Orchestrator (also in Settings → Access & links) |
| `ENABLE_TERMINAL` | `0` turns off the browser terminal |

Use HTTPS in front of the console if the network isn't trusted. Behind nginx, let the terminal's WebSocket through:

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade $http_upgrade;
proxy_set_header Connection "upgrade";
```

## Connect Slack

1. At [api.slack.com/apps](https://api.slack.com/apps): **Create New App** → **From a manifest**, pick the
   workspace and paste [`console/slack-app.yml`](../console/slack-app.yml). In a company workspace, an admin may need
   to approve the app.
2. **Basic Information** → **App-Level Tokens** → **Generate**, with the scope `connections:write`: the `xapp-…` token.
3. **Install App** → **Install to Workspace**: the `xoxb-…` bot token.
4. **Basic Information** → **Display Information**: upload `brand/app-icon-sage-1024.png` as the icon.
5. In the console, **Settings → Integrations → Slack**: paste both tokens and the Slack member IDs of the people
   allowed to use it (profile → ⋮ → **Copy member ID**), then **Save and connect** and **Send a test message**.

The console connects out to Slack (Socket Mode), so no public address is needed. Use one Slack app per running
console. On a server, the settings can come from `SLACK_BOT_TOKEN`, `SLACK_APP_TOKEN`, `SLACK_USERS` and
`SLACK_CHANNEL` instead.

## AI providers

Each agent runs on Claude by default, through your Claude Code login. To use another provider, add its API key in
**Settings → Models & keys** (or as an environment variable) and pick it for an agent in **Settings → Team**.

| Provider | Key |
|---|---|
| Claude | Claude Code login, `ANTHROPIC_API_KEY`, or Bedrock / Vertex |
| OpenAI | `OPENAI_API_KEY` |
| DeepSeek | `DEEPSEEK_API_KEY` |
| Qwen | `DASHSCOPE_API_KEY` |
| Kimi | `MOONSHOT_API_KEY` |

Keys saved in Settings stay in `console/data/settings.json` on the server and are never sent back to the browser.
An environment variable takes precedence over a saved key.

## Uninstall

1. Delete `~/.claude/agents/{orchestrator,techlead,dev,reviewer,coach}.md` and `~/.claude/commands/{board,ship}.md`.
2. In `~/.claude/settings.json`, remove the `on_task_change.py` hook and the kit's entries under `permissions`.
3. Delete the repository folder.
