# Installation

## Requirements

| | |
|---|---|
| OS | macOS or Linux |
| [Claude Code](https://code.claude.com) | Installed and logged in (`claude` works in your terminal) |
| Python 3 | For the team's tools |
| git | Each feature gets its own branch and worktree |
| [uv](https://docs.astral.sh/uv/) | For the console. macOS: `brew install uv`. Linux: `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| [GitHub CLI](https://cli.github.com) (optional) | Logged in (`gh auth login`), so the Coach can read your pull requests |
| [code-server](https://github.com/coder/code-server) (optional) | To open code reviews in VS Code in the browser. macOS: `brew install code-server`. Linux: `curl -fsSL https://code-server.dev/install.sh \| sh` |

## Install

```bash
git clone https://github.com/ramyeid/ai-hive.git ~/ai-hive
cd ~/ai-hive
bash scripts/install.sh
```

`scripts/install.sh`:
- copies the agents into `~/.claude/agents/`;
- adds the task hook and Hive's permissions to `~/.claude/settings.json`, keeping your settings and saving a backup as `settings.json.bak`.

It replaces any personal agents with the same names: `orchestrator`, `techlead`, `dev`, `reviewer`, `coach`.

## Start the console

```bash
bash scripts/start.sh
```

The first start installs the backend's dependencies (pinned in `backend/uv.lock`) in about a minute, then opens
**http://127.0.0.1:8420**. Stop it with Ctrl+C.

To keep it running in the background:

```bash
bash scripts/start.sh --background    # output goes to data/hive.log
bash scripts/stop.sh
```

Use `PORT=8500` for another port. `--background` doesn't restart the console after a crash or reboot; use your
system's service manager (systemd, launchd) for that, with `uv` on its `PATH`.

## Update

```bash
git pull
bash scripts/install.sh
```

Then restart the console. Run `scripts/install.sh` again too if you move the folder.

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
bash scripts/start.sh --background
```

| Variable | Purpose |
|---|---|
| `HOST` | Address to listen on (`127.0.0.1` by default) |
| `CONSOLE_HOSTS` | Host names allowed to reach the console, comma-separated; any other name is refused |
| `CONSOLE_PASSWORD` | Required with `CONSOLE_HOSTS` (8 characters or more) |
| `CONSOLE_URL` | The address used in links from Slack and the Orchestrator (also in Settings → Access & links) |
| `ENABLE_TERMINAL` | `0` turns off the browser terminal |
| `ENABLE_EDITOR` | `0` turns off VS Code in the browser for good (it's off until turned on in Settings) |
| `CODE_SERVER` | Where code-server is, if it isn't on the `PATH` or in the usual install places |

To open code reviews in VS Code in the browser, install [code-server](https://github.com/coder/code-server) on the
server (`curl -fsSL https://code-server.dev/install.sh | sh`), then turn it on in **Settings → Integrations →
Editor**. See [CONSOLE.md](CONSOLE.md#vs-code-in-the-browser).

Use HTTPS in front of the console if the network isn't trusted. Behind nginx (for instance with its own IP
allowlist, passing requests to the console as local), let the Terminal's and the editor's WebSockets through:

```nginx
# WebSocket requests get "upgrade"; everything else (pages, the event stream) a normal connection
map $http_upgrade $connection_upgrade {
    default upgrade;
    ''      '';
}

server {
    listen 80;
    server_name hive.internal.example.com;

    location / {
        allow 203.0.113.10;                          # your VPN's address
        deny  all;

        proxy_pass http://127.0.0.1:8420;
        proxy_http_version 1.1;
        proxy_set_header Host 127.0.0.1:8420;        # nginx checked who you are: the console sees a local request
        proxy_set_header X-Forwarded-Host $host;     # the editor checks its page is on this name
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_buffering off;                         # live updates (the event stream)
        proxy_cache off;
        proxy_read_timeout 1d;                       # idle WebSockets stay open
    }
}
```

Set each header once: nginx sends every `proxy_set_header` line, so a second `Connection` line breaks WebSockets.
To have the console check the name and ask for its password instead, pass `Host $host` and set `CONSOLE_HOSTS`
and `CONSOLE_PASSWORD`.

## Backups

**Settings → Backup** makes one archive with everything Hive needs to start again as if nothing happened:
all of `data/` (tasks, reviews, knowledge, the Coach's work, conversations, settings with their API keys and Slack
tokens), the branches only this machine has (as git bundles), and Claude Code's conversations and sign-in. It goes
to an S3 bucket (and a folder in it) or a folder on the machine; every day, week or month at the hour you choose
(one missed while the machine was off is made when Hive starts), keeping the last N.

For S3, enter the bucket's name (and a folder) under **Where**. The machine needs the `aws` command (on Amazon
Linux already) and access to the bucket, best with the instance's role. Keep the bucket private (it holds your keys), with server-side encryption on. A policy for the
role, with your bucket's name:

```json
{ "Version": "2012-10-17", "Statement": [
  { "Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": "arn:aws:s3:::my-bucket" },
  { "Effect": "Allow", "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject"], "Resource": "arn:aws:s3:::my-bucket/hive/*" } ] }
```

To restore from the console: **Settings → Backup → Restore**, upload a backup, check what's in it, and press
**Restore this backup**: Hive stops, puts it back and starts again (it needs to have been started with
`scripts/start.sh --background`; the steps are logged in `restore.log`). Or, on the same machine or a new one, with
Hive stopped:

```bash
git clone https://github.com/ramyeid/ai-hive.git && cd ai-hive   # on a new machine
bash scripts/restore.sh s3://my-bucket/hive         # the newest backup there (or a file, or a folder)
bash scripts/start.sh --background                  # with the same environment as before
```

It never deletes anything: the `data/` already there is moved to `data.before-restore-<time>`, missing projects are
cloned from GitHub and their branches and worktrees come back, and a branch that's newer on the machine is left
alone. Not in the backup: the environment you start Hive with (`CONSOLE_PASSWORD`, `CONSOLE_HOSTS`, …) and
code-server, which you install again.

## Connect Slack

1. At [api.slack.com/apps](https://api.slack.com/apps): **Create New App** → **From a manifest**, pick the
   workspace and paste [`integrations/slack/slack-app.yml`](../integrations/slack/slack-app.yml). In a company workspace, an admin may need
   to approve the app.
2. **Basic Information** → **App-Level Tokens** → **Generate**, with the scope `connections:write`: the `xapp-…` token.
3. **Install App** → **Install to Workspace**: the `xoxb-…` bot token.
4. **Basic Information** → **Display Information**: upload `assets/app-icon-sage-1024.png` as the icon.
5. In the console, **Settings → Integrations → Slack**: paste both tokens and the Slack member IDs of the people
   allowed to use it (profile → ⋮ → **Copy member ID**), then **Save and connect** and **Send a test message**.

Under **Notifications** on the same page, choose what notifies you (an agent waiting for your answer, approvals, each
task step, the Coach's proposals), what's only posted quietly in the task's thread, and what's not posted; and
whether replies in a thread are also sent as a direct message (or to the channel).

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

Keys saved in Settings stay in `data/console/settings.json` on the server and are never sent back to the browser.
An environment variable takes precedence over a saved key.

## Uninstall

1. Delete `~/.claude/agents/{orchestrator,techlead,dev,reviewer,coach}.md`.
2. In `~/.claude/settings.json`, remove the `on_task_change.py` hook and Hive's entries under `permissions`.
3. Delete the repository folder.
