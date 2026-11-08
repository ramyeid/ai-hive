# Usage

## A task from start to finish

| Step | Who | What happens |
|---|---|---|
| 1. Describe it | You → Tech Lead | *"In ~/code/my-api, users need to reset their password by email."* |
| 2. Spec | Tech Lead | Studies the project and its notes on it, looks for code to reuse, proposes the base branch, and asks you questions in rounds (with suggested answers) until nothing is open. |
| 3. Approve | You | Say *"approved"*. A readiness check runs: the task becomes **Ready for dev**, or goes back to Draft with the reasons. |
| 4. Hand it on | You or the Orchestrator | Pick a developer (Home, Board, Slack, or ask the Orchestrator). |
| 5. Build | Dev | Claims the task, works on `feature-<title>` in its own worktree, writes the code and unit tests, reviews its own diff, and sets **Ready for review**. |
| 6. Review | Reviewer | Checks the requirements and consistency with the existing code: **Done**, or **Changes requested** back to the same developer. |
| 7. Your review | You (optional) | Read the diff and comment, at any point (see below). |
| 8. Merge | You | Push and merge the branch as usual. The team never pushes. |

A task is **Blocked** when an agent needs your answer: Home and Slack show who is waiting, with a link to the chat.

**Follow-ups.** For more work on the same feature (a change, a fix, a misunderstanding), ask the Tech Lead for a
follow-up task. The developer adds commits to the same branch instead of starting a new one, unless you've already
merged that branch: then the follow-up gets a new branch from the base.

**Merging.** Push, open your pull request, rebase, squash and merge as you like: the team never pushes, and
rewriting a finished branch doesn't bother it. New branches start from the base as it is on GitHub (Hive fetches
`origin`, and never changes your local branches), so they include what you merged there.

**Routing.** New work goes to any agent of the role. Rework goes back to the developer who built it, and a
re-review to the same reviewer.

## Reviewing the code yourself

Open a task and press **Review the code** (also in the Dev's and Reviewer's chats).

- Review the **branch**: the whole branch against its base, or what changed since your last review, in unified or
  side-by-side view. Follow-up tasks add commits to the same branch, so **Earlier reviews** lists every round on it,
  and your comments go to the branch's current task (the one its dev is on).
- Hover a line and press **+** to comment on it. Anything not about one line goes in the **General comment** box,
  sent with your review.
- Tick **Viewed** on a file to fold it away (like GitHub); the eye in the file tree hides them. A viewed file
  comes back when the dev changes it.
- Hold **.** for 2 seconds (or click **Open in editor**) to open the branch's worktree in VS Code, indexed (go to definition,
  references, search). Like GitHub's **.**, it opens in a new tab, run by Hive on its own machine; or, per browser,
  in your desktop VS Code or Cursor. It shows once it's set up in **Settings → Integrations → Editor**.
- **Request changes**: your comments are added to the task under **Lead Review** and the task goes back to the
  developer who built it. The developer answers every comment, applies each one wherever it applies, and the
  reviewer checks they were all handled.
- **Approve**: records your approval. The reviewer always has the last word before Done.

Reviewing is optional and can happen before or after the reviewer, as often as you like.

## Landing a branch

Once every task on a branch is done, **Land this branch** (in its code review) takes it to a pull request:

1. **Clean up the history**, like `git rebase -i main`: for each commit, **Keep**, **Squash into the one above**
   (its message is added to that commit's), **Fold into the one above** (its message dropped) or **Drop**; move
   commits up and down, and write each resulting commit's message. **Squash all into one** is the default, with a
   message drafted from the spec. Applying also rebases the branch on `origin/main` (fetched first; your local
   `main` is fast-forwarded too when nothing has it checked out).
   - On a conflict nothing changes: Hive names the files and offers to ask the dev to rebase and resolve them.
   - The branch as the team made it is kept (`refs/hive/pre-land/<branch>`): **Undo the clean-up** puts it back,
     and the Coach still sees the commits you made yourself.
2. **Push**: `git push --force-with-lease`, after you confirm.
3. **Pull request**: `gh pr create`, with a title and description written from the spec and the reviews (edit
   them first). Pressing it again later updates them.
4. **Merge** stays yours, on GitHub. Hive checks every 10 minutes; once it's merged, it removes the branch's
   worktree and local branch. The Reviews page's **Done** tab shows where each branch stands.

The work happens in the branch's worktree (recreated if the reviewer removed it), never in your project folder.

## Teaching the team: the Coach

[`PREFERENCES.md`](../team/PREFERENCES.md) says how you want things built and is binding for every agent;
[`TEAM.md`](../team/TEAM.md) holds the process.

Start a review with the Coach from **Improvements** (or ask the Orchestrator). It reads how finished tasks went:
your code-review comments and what changed in response, your words in the agents' conversations, review rounds,
follow-ups, and your commits and comments on the GitHub pull requests (with `gh` logged in). It asks you about
anything unclear, then proposes small, exact edits to the team's instructions, each with its evidence.

Nothing changes until you approve. Each approved proposal is its own commit, so **Team history** shows every
version of the team, with diffs and undo. The Coach runs on a stronger model, so a review costs more than a task.

## The Orchestrator and Slack

Ask the Orchestrator, in the console (press **/** anywhere) or in Slack:

- *"Where are we?"*, *"What's waiting on me?"*: a short status with links to the right pages.
- *"Hand TASK-012 to Wael"*, *"Start the Coach on TASK-012 and TASK-019"*, *"Tell Nabil to reuse the paginator"*.

Every action waits for your **Allow**. In Slack:
- message the app to reach the Orchestrator, or start with a name (*"Nabil: …"*) to talk to that agent;
- approval requests come with **Allow / Deny** buttons;
- each task gets a thread with every hand-off and buttons for what's next (**Review the diff**, **Hand to …**).

## Several agents per role

Add agents in **Settings → Team** (for example 2 Tech Leads, 3 developers, 2 reviewers). Each gets an ID (`dev-2`)
and a name you can change (shown as "Nabil (Dev)").

- **No double work**: an agent claims a task before starting it; claims are atomic.
- **One worktree per feature**, next to the project: `~/code/my-api.worktrees/feature-filter-orders-by-status`.
  Your own checkout stays untouched. When a task is done, the reviewer removes the worktree; the branch stays.
- If you remove an agent that holds a task, clear its name in the task file so another agent can take it.

## The Tech Lead's knowledge

For each repository it works on, the Tech Lead keeps notes in `data/knowledge/<repo>/`: an index, plus one file per
service of a monorepo, with purpose, code map, APIs, entities, conventions and commands, and the commit they
describe. Each task starts from them and re-checks only what changed in git since. Read them on the **Knowledge** page.

## Using the terminal instead of the console

The agents also run in Claude Code directly. Open a terminal per agent in the folder that holds your projects:

```bash
claude --agent techlead
claude --agent dev
claude --agent reviewer
AGENT_ID=dev-2 claude --agent dev        # a second developer
```

Tell the dev or reviewer *"Check your inbox."* to pick up work. Type `/clear` between tasks in a terminal. The console starts a fresh conversation for you after each hand-off.
