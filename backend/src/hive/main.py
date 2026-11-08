"""Agent Team Console: a local web app to run and manage the techlead / dev / reviewer agents.

Run with ./start.sh — it serves http://127.0.0.1:8420 (this machine only).
"""
from __future__ import annotations

import asyncio
import json
import os
import secrets
import subprocess
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import access, board, chats, costs, editor, ops, store, team, terminal
from .agents import ORCHESTRATOR_KEY, TEAM_ACTION, AgentManager
from .slack import SlackBridge
from .engines import PROVIDERS
from .store import ASSETS, FRONTEND

import lead_review  # noqa: E402  (the team's tools are on sys.path via board)

TOKEN = secrets.token_urlsafe(24)   # new on every start; only the page we serve knows it
APPROVAL_WAIT = 100   # seconds an Orchestrator request waits for the lead before answering "still waiting"


# ---- request bodies ---------------------------------------------------------------

class StartBody(BaseModel):
    resume: str | None = None


class MessageBody(BaseModel):
    text: str


class DecisionBody(BaseModel):
    decision: str          # allow | always | deny
    message: str = ""


class ModeBody(BaseModel):
    mode: str              # default | acceptEdits


class SettingsBody(BaseModel):
    workspace: str


class AgentConfigBody(BaseModel):
    provider: str
    model: str = ""


class ProposalDecision(BaseModel):
    note: str = ""
    afters: list[str] | None = None   # approve: the lead's edited version of each change's new text


class ReviewComment(BaseModel):
    body: str
    file: str = ""
    line: int | None = None
    side: str = "new"
    code: str = ""


class ReviewSubmit(BaseModel):
    verdict: str            # changes | approve
    comment: str = ""       # a general comment written with the review
    mode: str = "feature"   # the view the lead reviewed: feature | since


class TeamAction(BaseModel):
    action: str             # start | stop | tell | hand | coach
    agent: str = ""         # id or name
    task: str = ""
    text: str = ""          # tell: the message; hand: a note for the agent; coach: what to review


class SlackBody(BaseModel):
    bot_token: str | None = None    # None = keep, "" = remove
    app_token: str | None = None
    users: str | None = None        # Slack member IDs allowed to use it, comma-separated
    channel: str | None = None      # "" = direct messages to the first user


class SlackPrefsBody(BaseModel):
    notify: dict[str, str] = {}    # event -> notify | quiet | off
    replies: str | None = None     # thread | thread_and_dm


class EditorSwitch(BaseModel):
    enabled: bool


class EditorOpen(BaseModel):
    folder: str


class ReviewViewed(BaseModel):
    path: str
    viewed: bool = True


class ConsoleUrlBody(BaseModel):
    console_url: str


class NameBody(BaseModel):
    name: str


class NewAgentBody(BaseModel):
    role: str                      # techlead | dev | reviewer


class PriceBody(BaseModel):
    model: str
    input: float | None = None     # US$ per 1M tokens; both None = remove the price
    output: float | None = None


class ProviderBody(BaseModel):
    api_key: str | None = None     # None = keep, "" = remove
    base_url: str | None = None    # None = keep, "" = back to the default


def public_settings() -> dict:
    """Settings for the browser: API keys are replaced by hints."""
    settings = store.load_settings()
    settings.pop("providers", None)
    settings["providers"] = store.public_providers(PROVIDERS)
    settings["slack"] = store.public_slack()
    settings["slack_prefs"] = store.slack_prefs()
    settings["console_url_effective"] = ops.console_url()
    return settings


def create_app(manager: AgentManager | None = None, slack_bridge: SlackBridge | None = None) -> FastAPI:
    access.check_config()
    manager = manager or AgentManager()
    slack = slack_bridge or SlackBridge(manager)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watcher = asyncio.create_task(_watch_board(manager))
        await slack.start()
        yield
        watcher.cancel()
        await slack.stop()
        await manager.stop_all()
        editor.stop()

    app = FastAPI(title="Agent Team Console", lifespan=lifespan)
    app.state.manager = manager

    @app.middleware("http")
    async def guard(request: Request, call_next):
        # Only the host names you allow (blocks DNS rebinding); other machines sign in first (see access.py);
        # every API call carries the page's key (blocks other websites driving your agents).
        host = (request.headers.get("host") or "").split(":")[0]
        path = request.url.path
        if not access.allowed(host):
            return JSONResponse({"detail": "This console doesn't answer to that address."}, status_code=403)
        if path.startswith("/api/orchestrator/"):   # the Orchestrator's own key, from this machine only
            key = request.headers.get("x-orchestrator") or ""
            if not access.is_local(host) or not secrets.compare_digest(key, ORCHESTRATOR_KEY):
                return JSONResponse({"detail": "Only the Orchestrator, on this machine."}, status_code=401)
            return await call_next(request)
        if not access.is_local(host) and not access.signed_in(request.cookies) and path != "/login":
            if path.startswith("/api/"):
                return JSONResponse({"detail": "Sign in again: reload the page."}, status_code=401)
            return HTMLResponse(access.login_page(), status_code=200)
        if path.startswith("/api/"):
            token = request.headers.get("x-token") or request.query_params.get("token")
            if not secrets.compare_digest(token or "", TOKEN):
                return JSONResponse({"detail": "Reload the page."}, status_code=401)
        return await call_next(request)

    @app.post("/login")
    async def login(request: Request, password: str = Form(""), next: str = Form("")):
        if not access.password_ok(password):
            await asyncio.sleep(1)   # slows down guessing
            return HTMLResponse(access.login_page("That's not the password."), status_code=401)
        target = "/" + (next if next.startswith("#/") else "")
        response = RedirectResponse(target, status_code=303)
        secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
        response.set_cookie(access.COOKIE, access.session_value(), max_age=access.MAX_AGE,
                            httponly=True, samesite="lax", secure=secure)
        return response

    def runner(name: str):
        if name not in manager.agents:
            raise HTTPException(404, f"No agent called {name}.")
        return manager.get(name)

    # ---- page --------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        return html.replace("__TOKEN__", TOKEN)

    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
    app.mount("/assets", StaticFiles(directory=ASSETS), name="assets")

    # ---- state & live events -------------------------------------------------------

    @app.get("/api/state")
    async def state():
        return {"agents": [r.info() for r in manager.agents.values()],
                "settings": public_settings(), "kit": str(store.KIT), "terminal": terminal.ENABLED,
                "editor_browser": editor.enabled(),
                "improvements": sum(1 for p in team.proposals() if p["status"] == "pending")}

    # ---- the Coach's proposals, and the history of the team's instructions ----------------

    @app.get("/api/improvements")
    def improvements():
        return team.proposals()

    @app.post("/api/improvements/{pid}/{decision}")
    def decide_improvement(pid: str, decision: str, body: ProposalDecision):
        if decision not in ("approve", "reject"):
            raise HTTPException(404, "Unknown decision.")
        try:
            done = team.approve(pid, body.afters, body.note) if decision == "approve" else team.reject(pid, body.note)
        except KeyError:
            raise HTTPException(404, f"No proposal {pid}.")
        except team.TeamError as exc:
            raise HTTPException(409, str(exc))
        manager.bus.publish({"kind": "team"})
        return done

    @app.get("/api/team/history")
    def team_history():
        return {"repo": team.is_repo(), "changes": team.history()}

    @app.get("/api/team/history/{sha}")
    def team_change(sha: str):
        try:
            return team.change(sha)
        except KeyError:
            raise HTTPException(404, "No such change to the team.")

    @app.get("/api/team/at/{sha}")
    def team_files_at(sha: str, path: str = ""):
        try:
            return {"files": team.files_at(sha)} if not path else {"path": path, "text": team.file_at(sha, path)}
        except (KeyError, team.TeamError):
            raise HTTPException(404, "Not found at that version.")

    @app.post("/api/team/undo/{sha}")
    def team_undo(sha: str):
        try:
            done = team.undo(sha)
        except KeyError:
            raise HTTPException(404, "No such change to the team.")
        except team.TeamError as exc:
            raise HTTPException(409, str(exc))
        manager.bus.publish({"kind": "team"})
        return done

    @app.get("/api/knowledge")
    async def knowledge_list():
        return board.knowledge_list()

    @app.get("/api/knowledge/{repo}/{name}")
    async def knowledge_get(repo: str, name: str):
        found = board.knowledge_get(repo, name)
        if not found:
            raise HTTPException(404, f"No knowledge file {repo}/{name}.")
        return found

    # ---- VS Code in the browser (code-server), see editor.py --------------------------

    @app.get("/api/editor")
    def editor_status():
        return editor.status()

    @app.put("/api/editor")
    def editor_switch(body: EditorSwitch):
        if body.enabled and not editor.allowed_by_env():
            raise HTTPException(409, "The editor in the browser is turned off on this server (ENABLE_EDITOR=0).")
        store.save_settings({"editor_browser": body.enabled})
        if not body.enabled:
            editor.stop()
        return editor.status()

    @app.post("/api/editor/open")
    async def editor_open(body: EditorOpen):
        if not editor.enabled():
            raise HTTPException(409, "The editor in the browser is off. Turn it on in Settings → Integrations → Editor.")
        if not Path(body.folder).is_dir():
            raise HTTPException(404, f"Folder not found: {body.folder}")
        try:
            await editor.ensure_started()
        except RuntimeError as exc:
            raise HTTPException(503, str(exc))
        response = JSONResponse({"url": editor.open_url(body.folder)})
        editor.grant(response)   # this browser (the page has the key) may use the editor
        return response

    @app.get("/editor")
    async def editor_root():
        return RedirectResponse("/editor/", status_code=307)

    @app.api_route("/editor/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
    async def editor_http(request: Request, path: str):
        return await editor.http(request, path)

    @app.websocket("/editor/{path:path}")
    async def editor_socket(ws: WebSocket, path: str):
        await editor.socket(ws, path)

    @app.websocket("/api/terminal")
    async def terminal_socket(ws: WebSocket):
        # The HTTP middleware doesn't cover WebSockets, so the same checks happen here:
        # local host only, and the page's key (sent as the first message).
        host = (ws.headers.get("host") or "").split(":")[0]
        if not access.allowed(host) or not (access.is_local(host) or access.signed_in(ws.cookies)):
            await ws.close(code=4403)
            return
        await terminal.session(ws, lambda token: secrets.compare_digest(token or "", TOKEN),
                               store.load_settings()["workspace"])

    @app.get("/api/events")
    async def events(request: Request):
        queue = manager.bus.subscribe()

        async def stream():
            try:
                yield "retry: 2000\n\n"
                while not await request.is_disconnected():
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15)
                        yield f"data: {json.dumps(event, default=str)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keep-alive\n\n"
            finally:
                manager.bus.unsubscribe(queue)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # ---- agents ----------------------------------------------------------------------


    async def _do(action):
        try:
            await action
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(409, str(exc))
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(500, f"Couldn't reach Claude Code: {exc}")

    @app.post("/api/agents/{name}/start")
    async def start(name: str, body: StartBody):
        await _do(runner(name).start(resume=body.resume))
        return runner(name).info()

    @app.post("/api/agents/{name}/stop")
    async def stop(name: str):
        await _do(runner(name).stop())
        return runner(name).info()

    @app.post("/api/agents/{name}/new")
    async def new(name: str):
        await _do(runner(name).new_session())
        return runner(name).info()

    @app.post("/api/agents/{name}/interrupt")
    async def interrupt(name: str):
        await _do(runner(name).interrupt())
        return runner(name).info()

    @app.post("/api/agents/{name}/watching")
    async def watching(name: str):
        """The lead has this agent's chat open on screen (sent every few seconds): it doesn't need notifying."""
        runner(name).lead_watching = store.now()
        return {"ok": True}

    @app.post("/api/agents/{name}/message")
    async def message(name: str, body: MessageBody):
        if not body.text.strip():
            raise HTTPException(400, "Write a message first.")
        await _do(runner(name).send(body.text.strip()))
        return runner(name).info()

    @app.post("/api/agents/{name}/permissions/{pid}")
    async def decide(name: str, pid: str, body: DecisionBody):
        if body.decision not in ("allow", "always", "deny"):
            raise HTTPException(400, "Decision must be allow, always or deny.")
        try:
            runner(name).decide(pid, body.decision, body.message)
        except KeyError:
            raise HTTPException(404, "That request was already answered.")
        return runner(name).info()

    @app.put("/api/agents/{name}/mode")
    async def mode(name: str, body: ModeBody):
        try:
            store.save_settings({"permission_mode": {runner(name).name: body.mode}})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await _do(runner(name).set_permission_mode(body.mode))
        return public_settings()

    @app.post("/api/agents")
    async def add_agent(body: NewAgentBody):
        try:
            agent_id = store.add_agent(body.role)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        manager.sync()
        manager.bus.publish({"kind": "team"})
        return {"id": agent_id, "agents": [r.info() for r in manager.agents.values()], "settings": public_settings()}

    @app.delete("/api/agents/{name}")
    async def remove_agent(name: str):
        if runner(name).status != "stopped":
            raise HTTPException(409, f"Stop {name} first.")
        try:
            store.remove_agent(name)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        manager.sync()
        manager.bus.publish({"kind": "team"})
        return {"agents": [r.info() for r in manager.agents.values()], "settings": public_settings()}

    @app.put("/api/agents/{name}/name")
    async def rename_agent(name: str, body: NameBody):
        runner(name)
        try:
            store.rename_agent(name, body.name)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        manager.bus.publish({"kind": "team"})
        return public_settings()

    @app.put("/api/agents/{name}/config")
    async def agent_config(name: str, body: AgentConfigBody):
        agent = runner(name)
        if body.provider not in PROVIDERS:
            raise HTTPException(400, f"Unknown provider: {body.provider}")
        if agent.status != "stopped":
            raise HTTPException(409, f"Stop {name} first. The provider and model apply when it starts.")
        store.save_settings({"agents": {name: body.model_dump()}})
        return public_settings()

    @app.put("/api/providers/{pid}")
    async def provider(pid: str, body: ProviderBody):
        if pid not in PROVIDERS or PROVIDERS[pid].engine == "claude":
            raise HTTPException(404, "Unknown provider.")
        store.save_settings({"providers": {pid: body.model_dump()}})
        return public_settings()

    # ---- history ---------------------------------------------------------------------

    @app.get("/api/sessions")
    async def sessions(agent: str | None = None):
        return store.list_sessions(agent)

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str):
        meta = store.get_session(session_id)
        if not meta:
            raise HTTPException(404, "Session not found.")
        return {"id": session_id, **meta, "events": store.read_events(session_id)}

    # ---- board -------------------------------------------------------------------------

    @app.get("/api/activity")
    async def activity_feed(limit: int = 500):
        return board.activity(max(1, min(limit, 5000)))

    @app.get("/api/dashboard")
    async def dashboard():
        data = board.summary()
        sessions = store.list_sessions()
        data["cost_usd"] = round(sum(s.get("cost_usd") or 0 for s in sessions), 2)
        data["sessions"] = sessions[:8]
        return data

    @app.get("/api/tasks")
    async def tasks():
        spent = costs.summary()["tasks"]
        empty = {"cost_usd": 0, "unpriced_tokens": 0, "tokens": 0, "rows": []}
        return [{**t, "cost": spent.get(t["id"], empty)} for t in board.list_tasks()]

    @app.get("/api/costs")
    async def cost_summary():
        return costs.summary()

    @app.put("/api/prices")
    async def price(body: PriceBody):
        if body.input is None and body.output is None:
            store.save_settings({"prices": {body.model: None}})
        elif body.input is None or body.output is None or body.input < 0 or body.output < 0:
            raise HTTPException(400, "Enter both prices, in US$ per 1M tokens.")
        else:
            store.save_settings({"prices": {body.model: {"input": body.input, "output": body.output}}})
        return costs.summary()

    @app.get("/api/tasks/{task_id}")
    async def task(task_id: str):
        found = board.get_task(task_id)
        if not found:
            raise HTTPException(404, "Task not found.")
        found["cost"] = costs.summary()["tasks"].get(task_id, {"cost_usd": 0, "unpriced_tokens": 0, "tokens": 0, "rows": []})
        return found

    # ---- the lead's code review ----------------------------------------------------------

    def reviewing(fn, *args):
        try:
            return fn(*args)
        except KeyError:
            raise HTTPException(404, "Not found.")
        except lead_review.ReviewError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/reviews")
    def reviews():
        """Every feature branch, with where the lead's review stands (the Reviews page)."""
        return lead_review.branches()

    @app.get("/api/tasks/{task_id}/review")
    def review(task_id: str, mode: str = "feature"):
        return reviewing(lead_review.diff, task_id, mode)

    @app.post("/api/tasks/{task_id}/review/comments")
    def review_comment(task_id: str, body: ReviewComment):
        return reviewing(lead_review.add_comment, task_id, body.body, body.file, body.line, body.side, body.code)

    @app.put("/api/tasks/{task_id}/review/comments/{cid}")
    def review_comment_edit(task_id: str, cid: str, body: ReviewComment):
        reviewing(lead_review.edit_comment, task_id, cid, body.body)
        return {"ok": True}

    @app.delete("/api/tasks/{task_id}/review/comments/{cid}")
    def review_comment_delete(task_id: str, cid: str):
        reviewing(lead_review.delete_comment, task_id, cid)
        return {"ok": True}

    @app.post("/api/tasks/{task_id}/review/viewed")
    def review_viewed(task_id: str, body: ReviewViewed):
        return reviewing(lead_review.mark_viewed, task_id, body.path, body.viewed)

    @app.post("/api/tasks/{task_id}/review/submit")
    def review_submit(task_id: str, body: ReviewSubmit):
        done = reviewing(lead_review.submit, task_id, body.verdict, body.comment, body.mode)
        manager.bus.publish({"kind": "board"})
        return done

    # ---- the Orchestrator's view of the team and its actions (each one approved by the lead) ----

    def _ops(fn, *args):
        try:
            return fn(*args)
        except ops.OpsError as exc:
            raise HTTPException(409, str(exc))

    @app.get("/api/orchestrator/status")
    def orchestrator_status():
        return ops.status(manager)

    @app.get("/api/orchestrator/tasks/{task_id}")
    def orchestrator_task(task_id: str):
        return _ops(ops.task, task_id)

    def _plan(body: TeamAction):
        """Check the action can happen now, and describe it for the lead's approval."""
        act = body.action
        if act == "coach":
            return f"Start a Coach review ({body.text or 'since its last review'})", lambda: ops.coach(manager, body.text)
        agent = _ops(ops.find_agent, body.agent)
        if act == "start":
            return f"Start {ops.label(agent)}", lambda: ops.start(manager, agent)
        if act == "stop":
            return f"Stop {ops.label(agent)}", lambda: ops.stop(manager, agent)
        if act == "tell":
            if not body.text.strip():
                raise HTTPException(409, "The message is empty.")
            return (f"Send {ops.label(agent)} this message:\n\n{body.text.strip()}",
                    lambda: ops.tell(manager, agent, body.text))
        if act == "hand":
            t = _ops(ops.check_hand, manager, body.task, agent)
            note = f"\n\nWith this note: {body.text.strip()}" if body.text.strip() else ""
            return (f"Hand {t['id']} ({t['title']}) to {ops.label(agent)}{note}",
                    lambda: ops.hand(manager, t["id"], agent, body.text))
        raise HTTPException(400, "Actions: start, stop, tell, hand, coach.")

    @app.post("/api/orchestrator/act")
    async def orchestrator_act(body: TeamAction):
        summary, do = _plan(body)
        orchestrator = next((r for r in manager.agents.values() if r.role == "orchestrator"), None)
        if not orchestrator:
            raise HTTPException(409, "There's no Orchestrator on the team.")

        async def approve_then_do():
            allowed, message = await orchestrator.ask(TEAM_ACTION, {"summary": summary, "action": body.action})
            if not allowed:
                return {"done": False, "message": f"The lead said no{': ' + message if message else '.'}"}
            try:
                return {"done": True, "message": await do()}
            except ops.OpsError as exc:
                return {"done": False, "message": str(exc)}

        job = asyncio.create_task(approve_then_do())   # carries on if the lead answers after the reply below
        try:
            return await asyncio.wait_for(asyncio.shield(job), APPROVAL_WAIT)
        except asyncio.TimeoutError:
            return {"done": False, "waiting": True,
                    "message": "Waiting for the lead's approval (in the console or Slack). It will happen once they approve."}

    # ---- links, and the Slack connection ----------------------------------------------------

    @app.put("/api/settings/console-url")
    async def save_console_url(body: ConsoleUrlBody):
        try:
            store.save_settings({"console_url": body.console_url})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return public_settings()

    @app.put("/api/settings/slack")
    async def save_slack(body: SlackBody):
        try:
            store.save_settings({"slack": body.model_dump(exclude_none=True)})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        await slack.restart()
        return public_settings()

    @app.put("/api/settings/slack/notifications")
    async def save_slack_prefs(body: SlackPrefsBody):
        try:
            store.save_settings({"slack_prefs": body.model_dump(exclude_none=True)})
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        return public_settings()

    @app.get("/api/slack")
    async def slack_status():
        return slack.status()

    @app.post("/api/slack/test")
    async def slack_test():
        if not slack.connected or not slack.home:
            raise HTTPException(409, "Slack isn't connected yet.")
        await slack.post(slack.home, "👋 Hive is connected. Task updates and approval requests will come here, "
                                     "and you can message me to talk to the Orchestrator.")
        return {"ok": True}

    @app.get("/api/about")
    def about():
        def git(*args: str) -> str:
            done = subprocess.run(["git", "-C", str(store.KIT), *args], capture_output=True, text=True)
            return done.stdout.strip() if done.returncode == 0 else ""
        ahead = git("rev-list", "--count", "@{upstream}..HEAD")
        return {"kit": str(store.KIT), "commit": git("rev-parse", "--short", "HEAD"), "date": git("log", "-1", "--format=%cI"),
                "subject": git("log", "-1", "--format=%s"), "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
                "ahead": int(ahead) if ahead.isdigit() else None, "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
                "hosts": sorted(access.extra_hosts()), "password": bool(os.environ.get("CONSOLE_PASSWORD")),
                "listen": os.environ.get("HOST", "127.0.0.1"), "terminal": terminal.ENABLED, "console_url": ops.console_url(),
                "workspace": store.load_settings().get("workspace", "")}

    @app.post("/api/tasks/{task_id}/hand/{agent}")
    async def hand_task(task_id: str, agent: str):
        try:
            return {"message": await ops.hand(manager, task_id, agent)}
        except ops.OpsError as exc:
            raise HTTPException(409, str(exc))

    def live_sessions() -> list[str]:
        return [r.session_id for r in manager.agents.values() if r.engine and r.session_id]

    @app.get("/api/tasks/{task_id}/chats")
    async def task_chats(task_id: str):
        if not board.get_task(task_id):
            raise HTTPException(404, "Task not found.")
        return chats.for_task(task_id, live_sessions())

    @app.get("/api/tasks/{task_id}/chats/{name}")
    async def task_chat(task_id: str, name: str):
        found = chats.get(task_id, name, live_sessions()) if board.get_task(task_id) else None
        if not found:
            raise HTTPException(404, "Conversation not found.")
        return found

    @app.get("/api/inbox/{role}")
    async def inbox(role: str):
        if role not in board.ROLES:
            raise HTTPException(404, "Unknown inbox.")
        return board.inbox(role)

    @app.post("/api/inbox/{role}/clear")
    async def clear(role: str):
        if role not in board.ROLES:
            raise HTTPException(404, "Unknown inbox.")
        board.clear_inbox(role)
        return board.inbox(role)

    # ---- settings ----------------------------------------------------------------------


    @app.put("/api/settings")
    async def settings(body: SettingsBody):
        try:
            store.save_settings({"workspace": body.workspace})
            return public_settings()
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    return app


async def _watch_board(manager: AgentManager) -> None:
    """Tell open pages to refresh when a task or inbox file changes on disk."""
    last = board.signature()
    while True:
        await asyncio.sleep(1.5)
        try:
            current = board.signature()
        except OSError:
            continue
        if current != last:
            last = current
            manager.bus.publish({"kind": "board"})


app = create_app()
