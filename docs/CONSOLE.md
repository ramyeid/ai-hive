# Console

Start it with `bash console/start.sh` and open **http://127.0.0.1:8420**. See [Installation](INSTALL.md) for
running it in the background or on a server.

## Navigation

- **Sidebar**: Home, Board and Activity; the Orchestrator, Team and Coach sections (each can be folded away);
  Knowledge; Settings and Terminal. On a phone it becomes a bar at the bottom.
- **⌘K / Ctrl+K**: jump to any task, agent or page.
- **/**: ask the Orchestrator from any page.

## Pages

| Page | |
|---|---|
| **Home** | What needs you, each with its action: approvals, blocked tasks, tasks ready for review or waiting for a developer, the Coach's proposals. Then what's in progress and what was just finished. |
| **Board** | Every task in its column (Blocked, Draft, Ready for dev, In dev, Ready for review, In review, Done), with filters by project and agent, and buttons to hand a task on or open its diff. **List** shows the same tasks as a table, with costs. |
| **Task** | The spec, each agent's conversation on it, your code reviews, its activity and cost; a progress line; who wrote, built and reviewed it; the branch and related tasks. |
| **Code review** | The branch's diff with line comments, request changes or approve. See [Usage](USAGE.md#reviewing-the-code-yourself). |
| **Agent chat** | Talk to an agent. Tool calls are folded into one line per run; approval requests are pinned above the message box (Enter allows, Esc denies); `#` suggests task IDs. The side panel shows the task it's on, this conversation's cost and its earlier tasks. |
| **Activity** | Every status change and who made it, by day, with filters; and every past conversation, which you can read or continue. |
| **Knowledge** | The Tech Lead's notes per repository and service, with how much has changed in git since each was written. |
| **Improvements** | The Coach's proposals: the exact change, why, and the tasks behind it. Approve, edit or reject. |
| **Team history** | Every change to the team's instructions, with diffs, the team as it was at any point, and undo. |
| **Terminal** | Shells on the machine the console runs on, side by side. |
| **Settings** | Team (agents, their models and approval mode), Models & keys, Integrations (Slack), Access & links, Workspace, Appearance, About. |

## Approvals

When an agent wants to do something your settings don't already allow, it pauses and asks: in its chat, on Home
and in Slack. Nothing runs until you answer.

- On Claude, anything your Claude Code settings allow runs without asking.
- On other providers, reading and searching in the agents' home folder and the kit, editing task files and running
  the kit's scripts don't ask; everything else does.
- Set an agent's **Edits** to *Allow automatically* in Settings → Team to skip file-edit prompts for it.
- The Orchestrator's actions (start, stop, hand on, message, Coach) always ask.

## Conversations

When an agent hands a task on, the console saves that conversation with the task and starts the agent on a fresh
one, so there's no need for `/clear`. A task's conversations are kept in `tasks/chats/TASK-NNN/` and shown on its
page. They're for you only: agents work from the task file, never from past conversations.

## Cost

Each task shows its cost from spec to review, by model and agent. Every agent turn is charged to the task it worked
on. Claude costs are Claude Code's own figures (an estimate with a subscription login). Other providers report
tokens only: enter each model's price in **Settings → Models & keys**.

## Browser terminal

The **Terminal** page opens shells on the machine the console runs on, as the user it runs as, starting in the
agents' home folder. It's on by default; start the console with `ENABLE_TERMINAL=0` to turn it off.

> **Anyone who can open the console can run commands on that machine.** Keep it on localhost, or behind a login
> (your reverse proxy or the console's password).

## Security

- By default the console answers only on 127.0.0.1, to its own host names.
- Every request carries a key known only to the page the console serves, so other websites can't drive your agents.
- On a server, other machines sign in with the console's password, or reach it through your reverse proxy.
- API keys and Slack tokens stay on the server and are never sent to the browser.
