"""VS Code in the browser (code-server), like GitHub's ".": opens a branch's worktree in a new tab.

Hive starts code-server (installed on this machine by the lead) on first use, on a Unix socket in data/editor/ that
only this user can reach, and serves it at /editor/ behind the console's own checks:
- the console's host and sign-in rules (the HTTP middleware; WebSockets check them here too);
- a cookie the console sets when you open the editor from a page that has its key, marked SameSite=Strict, so no
  other website can reach it through your browser;
- for its live connection (WebSocket), the Origin must be the console itself.

Anyone who can open the console can edit files and run commands with it, like the Terminal page: it's off until the
lead turns it on in Settings → Integrations → Editor, and ENABLE_EDITOR=0 turns it off for good.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import websockets
from fastapi import Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse

from . import access, store

FOLDER = store.DATA.parent / "editor"            # data/editor: the socket, VS Code's settings and extensions
SOCKET = FOLDER / "code-server.sock"
COOKIE = "hive_editor"
PREFIX = "/editor"
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "content-length"}
SEARCH = [Path.home() / ".local/bin/code-server", Path("/usr/local/bin/code-server"),
          Path("/opt/homebrew/bin/code-server"), Path("/usr/bin/code-server")]

log = logging.getLogger("hive.editor")
_secret = secrets.token_urlsafe(32)              # the editor cookie's value, new each time the console starts
_process: subprocess.Popen | None = None
_starting = asyncio.Lock()


def allowed_by_env() -> bool:
    return os.environ.get("ENABLE_EDITOR", "1") != "0"


def enabled() -> bool:
    return allowed_by_env() and bool(store.load_settings().get("editor_browser"))


def binary() -> str:
    """Where code-server is: $CODE_SERVER, the PATH, or the usual install places."""
    if os.environ.get("CODE_SERVER"):
        return os.environ["CODE_SERVER"]
    found = shutil.which("code-server")
    return found or next((str(p) for p in SEARCH if p.is_file() and os.access(p, os.X_OK)), "")


_versions: dict[str, str] = {}


def status() -> dict:
    path = binary()
    if path and path not in _versions:
        try:
            _versions[path] = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20).stdout.split()[0]
        except (OSError, subprocess.SubprocessError, IndexError):
            path = ""
    version = _versions.get(path, "")
    return {"installed": bool(path), "path": path, "version": version, "enabled": enabled(),
            "allowed": allowed_by_env(), "running": running()}


def running() -> bool:
    return _process is not None and _process.poll() is None


async def ensure_started() -> None:
    """Start code-server if it isn't running, and wait until it answers (up to 30 s)."""
    global _process
    async with _starting:
        if running():
            return
        path = binary()
        if not path:
            raise RuntimeError("code-server isn't installed on this machine. See Settings → Integrations → Editor.")
        FOLDER.mkdir(parents=True, exist_ok=True)
        FOLDER.chmod(0o700)   # the socket inside is only for this user
        SOCKET.unlink(missing_ok=True)
        (FOLDER / "config.yaml").touch()
        settings = FOLDER / "user" / "User" / "settings.json"
        if not settings.exists():   # open straight on the branch: no welcome walkthrough, no telemetry
            settings.parent.mkdir(parents=True, exist_ok=True)
            settings.write_text('{\n  "workbench.startupEditor": "none",\n  "telemetry.telemetryLevel": "off"\n}\n')
        with (FOLDER / "code-server.log").open("ab") as log:
            _process = subprocess.Popen(
                [path, "--socket", str(SOCKET), "--auth", "none", "--config", str(FOLDER / "config.yaml"),
                 "--user-data-dir", str(FOLDER / "user"), "--extensions-dir", str(FOLDER / "extensions"),
                 "--disable-telemetry", "--disable-update-check", "--disable-workspace-trust",
                 "--disable-getting-started-override", "--app-name", "Hive"],
                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        for _ in range(150):
            if _process.poll() is not None:
                raise RuntimeError(f"code-server stopped while starting; see {FOLDER / 'code-server.log'}.")
            if SOCKET.exists():
                try:
                    async with _client() as client:
                        await client.get("http://editor/healthz", timeout=1)
                    return
                except httpx.HTTPError:
                    pass
            await asyncio.sleep(0.2)
        raise RuntimeError("code-server didn't start within 30 seconds.")


def stop() -> None:
    global _process
    if running():
        _process.terminate()
        try:
            _process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _process.kill()
    _process = None


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.AsyncHTTPTransport(uds=str(SOCKET)), timeout=None)


def open_url(folder: str) -> str:
    return f"{PREFIX}/?folder={folder}"


def grant(response) -> None:
    """Called when the console page (which has the key) opens the editor: this browser may now use it."""
    response.set_cookie(COOKIE, _secret, httponly=True, samesite="strict", path=PREFIX)


def _granted(cookies: dict) -> bool:
    return secrets.compare_digest(cookies.get(COOKIE, ""), _secret)


async def http(request: Request, path: str):
    """Pass an HTTP request through to code-server (the middleware has already checked the host and sign-in)."""
    if not enabled():
        return JSONResponse({"detail": "The editor is off. Turn it on in Settings → Integrations → Editor."}, 404)
    if not _granted(request.cookies):
        return JSONResponse({"detail": "Open the editor from the console (the button in a code review)."}, 403)
    try:
        await ensure_started()
    except RuntimeError as exc:
        return JSONResponse({"detail": str(exc)}, 503)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["x-forwarded-prefix"] = PREFIX
    client = _client()
    upstream = await client.send(client.build_request(
        request.method, f"http://editor/{path}", params=request.query_params, headers=headers,
        content=request.stream()), stream=True)

    async def body():
        try:
            async for chunk in upstream.aiter_raw():
                yield chunk
        finally:
            await upstream.aclose()
            await client.aclose()

    out = {k: v for k, v in upstream.headers.items() if k.lower() not in HOP_BY_HOP}
    return StreamingResponse(body(), status_code=upstream.status_code, headers=out)


def _same_origin(origin: str, headers) -> bool:
    """The page opening the connection is the console itself. Behind a reverse proxy the Host may be the proxy's
    upstream (127.0.0.1:8420) while the page is on hive.example.com, so the proxy's X-Forwarded-Host and the
    names in CONSOLE_HOSTS count too."""
    seen = urlsplit(origin).netloc.lower()
    if not seen:
        return False
    hosts = {(headers.get("host") or "").lower(), (headers.get("x-forwarded-host") or "").split(",")[0].strip().lower()}
    return seen in hosts or (urlsplit(origin).hostname or "") in access.extra_hosts()


def _refusal(ws: WebSocket) -> str:
    host = (ws.headers.get("host") or "").split(":")[0]
    origin = ws.headers.get("origin", "")
    if not enabled():
        return "the editor is off"
    if not access.allowed(host):
        return f"the address {host!r} isn't in CONSOLE_HOSTS"
    if not (access.is_local(host) or access.signed_in(ws.cookies)):
        return "this browser isn't signed in"
    if not _granted(ws.cookies):
        return "no editor cookie (open the editor from a code review; the console restarted since?)"
    if not _same_origin(origin, ws.headers):
        return f"the page {origin!r} isn't the console at {ws.headers.get('host')!r}"
    return ""


async def socket(ws: WebSocket, path: str) -> None:
    """Pass VS Code's live connection through, after the same checks the HTTP middleware makes, plus the Origin."""
    refused = _refusal(ws)
    if refused:
        log.warning("Editor connection refused: %s.", refused)
        await ws.close(code=4403)
        return
    try:
        await ensure_started()
    except RuntimeError as exc:
        log.warning("Editor connection failed: %s", exc)
        await ws.close(code=1011)
        return
    query = f"?{ws.url.query}" if ws.url.query else ""
    headers = {k: v for k, v in ws.headers.items()
               if k.lower() in ("cookie", "origin", "user-agent", "accept-language")}
    subprotocols = [p.strip() for p in ws.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    # the URL's host becomes the Host header: the page's own address, so code-server's origin check agrees
    try:
        upstream = await websockets.unix_connect(
            str(SOCKET), f"ws://{urlsplit(ws.headers['origin']).netloc}/{path}{query}", additional_headers=headers,
            subprotocols=subprotocols or None, max_size=None, compression=None)
    except (OSError, websockets.InvalidHandshake) as exc:
        log.warning("Editor connection failed: code-server answered %s.", exc)
        await ws.close(code=1011)
        return
    async with upstream:
        await ws.accept(subprotocol=upstream.subprotocol)

        async def to_editor():
            try:
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    await upstream.send(message["bytes"] if message.get("bytes") is not None else message.get("text", ""))
            except (WebSocketDisconnect, websockets.ConnectionClosed):
                pass
            await upstream.close()

        async def to_browser():
            # Either side can go at any moment (a closed or reloaded tab, code-server restarting): end quietly.
            try:
                async for message in upstream:
                    if isinstance(message, bytes):
                        await ws.send_bytes(message)
                    else:
                        await ws.send_text(message)
            except (WebSocketDisconnect, websockets.ConnectionClosed, RuntimeError):
                pass
            await upstream.close()
            try:
                await ws.close()
            except (WebSocketDisconnect, RuntimeError):
                pass

        await asyncio.gather(to_editor(), to_browser())
