"""A stand-in for code-server, for the editor tests: serves a page, /healthz and an echoing WebSocket on --socket.

    python tests/fakes/code_server.py --socket /path/to.sock [code-server's other options, ignored]
"""
import sys

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute


async def page(request):
    return PlainTextResponse(f"workbench for {request.query_params.get('folder', '')}",
                             headers={"x-seen-prefix": request.headers.get("x-forwarded-prefix", "")})


async def healthz(request):
    return JSONResponse({"status": "alive"})


async def echo(ws):
    await ws.accept()
    async for text in ws.iter_text():
        await ws.send_text(f"echo {text} (host {ws.headers.get('host')})")


async def chatter(ws):
    """Keeps sending, like VS Code's server does, whether or not the tab is still there."""
    import asyncio
    await ws.accept()
    while True:
        await ws.send_bytes(b"x" * 1024)
        await asyncio.sleep(0.01)


if "--version" in sys.argv:
    print("4.0.0-fake abc with Code 1.0.0")
    sys.exit(0)
app = Starlette(routes=[Route("/", page), Route("/healthz", healthz), WebSocketRoute("/socket", echo), WebSocketRoute("/chatter", chatter)])
uvicorn.run(app, uds=sys.argv[sys.argv.index("--socket") + 1], log_level="warning")
