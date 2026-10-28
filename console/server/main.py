"""Agent Team Console: a local web app to run and manage the techlead / dev / reviewer agents.

Run with ./start.sh — it serves http://127.0.0.1:8420 (this machine only).
"""
from __future__ import annotations

import asyncio
import json
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, WebSocket
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import board, chats, costs, store, terminal
from .agents import AgentManager
from .engines import PROVIDERS
from .store import CONSOLE

import migrate  # noqa: E402  (kit scripts are on sys.path via board)

TOKEN = secrets.token_urlsafe(24)   # new on every start; only the page we serve knows it
LOCAL_HOSTS = {"127.0.0.1", "localhost"}
WEB = CONSOLE / "web"


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
    return settings


def create_app(manager: AgentManager | None = None) -> FastAPI:
    migrate.main()   # upgrade data from older versions of the kit (safe to repeat)
    manager = manager or AgentManager()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        watcher = asyncio.create_task(_watch_board(manager))
        yield
        watcher.cancel()
        await manager.stop_all()

    app = FastAPI(title="Agent Team Console", lifespan=lifespan)
    app.state.manager = manager

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        # Blocks other websites from driving your agents (DNS rebinding / CSRF).
        host = (request.headers.get("host") or "").split(":")[0]
        if host not in LOCAL_HOSTS:
            return JSONResponse({"detail": "Local access only."}, status_code=403)
        if request.url.path.startswith("/api/"):
            token = request.headers.get("x-token") or request.query_params.get("token")
            if not secrets.compare_digest(token or "", TOKEN):
                return JSONResponse({"detail": "Reload the page."}, status_code=401)
        return await call_next(request)

    def runner(name: str):
        if name not in manager.agents:
            raise HTTPException(404, f"No agent called {name}.")
        return manager.get(name)

    # ---- page --------------------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def index():
        html = (WEB / "index.html").read_text(encoding="utf-8")
        return html.replace("__TOKEN__", TOKEN)

    app.mount("/static", StaticFiles(directory=WEB), name="static")

    # ---- state & live events -------------------------------------------------------

    @app.get("/api/state")
    async def state():
        return {"agents": [r.info() for r in manager.agents.values()],
                "settings": public_settings(), "kit": str(store.KIT), "terminal": terminal.ENABLED}

    @app.get("/api/knowledge")
    async def knowledge_list():
        return board.knowledge_list()

    @app.get("/api/knowledge/{repo}/{name}")
    async def knowledge_get(repo: str, name: str):
        found = board.knowledge_get(repo, name)
        if not found:
            raise HTTPException(404, f"No knowledge file {repo}/{name}.")
        return found

    @app.websocket("/api/terminal")
    async def terminal_socket(ws: WebSocket):
        # The HTTP middleware doesn't cover WebSockets, so the same checks happen here:
        # local host only, and the page's key (sent as the first message).
        if (ws.headers.get("host") or "").split(":")[0] not in LOCAL_HOSTS:
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
