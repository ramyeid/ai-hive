"""A shell on the machine the console runs on, streamed to the browser over a WebSocket.

On by default; start the console with ENABLE_TERMINAL=0 to turn it off. Anyone who can open the console
can run any command as the user the console runs as, so keep the console itself protected (this machine
only, or behind your login and IP allowlist).

Protocol: the browser's first message is {"token": ...}; after that, {"type": "input", "data": "..."}
or {"type": "resize", "cols": 120, "rows": 30}. The server sends the shell's output as binary frames.
One shell per connection; it ends when the page closes the connection.
"""
from __future__ import annotations

import asyncio
import fcntl
import os
import pty
import signal
import struct
import termios

from fastapi import WebSocket, WebSocketDisconnect

ENABLED = os.environ.get("ENABLE_TERMINAL", "1") != "0"


def _resize(fd: int, cols: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", max(rows, 1), max(cols, 1), 0, 0))


def _spawn(folder: str) -> tuple[int, int]:
    """Start a login shell in a new pseudo-terminal. Returns (pid, fd)."""
    shell = os.environ.get("SHELL") or "/bin/bash"
    pid, fd = pty.fork()
    if pid == 0:   # child: becomes the shell
        try:
            os.chdir(folder)
        except OSError:
            os.chdir(os.path.expanduser("~"))
        env = {**os.environ, "TERM": "xterm-256color"}
        env.pop("ENABLE_TERMINAL", None)
        os.execvpe(shell, [shell, "-l"], env)
    return pid, fd


def _end(pid: int, fd: int) -> None:
    try:
        os.kill(pid, signal.SIGHUP)
    except ProcessLookupError:
        pass
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass


async def session(ws: WebSocket, token_ok, folder: str) -> None:
    await ws.accept()
    if not ENABLED:
        await ws.close(code=4403, reason="The terminal is turned off (ENABLE_TERMINAL=0).")
        return
    try:
        hello = await asyncio.wait_for(ws.receive_json(), timeout=10)
    except Exception:
        await ws.close(code=4401)
        return
    if not token_ok(hello.get("token", "")):
        await ws.close(code=4401, reason="Reload the page.")
        return

    pid, fd = _spawn(folder)
    if hello.get("cols") and hello.get("rows"):
        _resize(fd, int(hello["cols"]), int(hello["rows"]))
    loop = asyncio.get_running_loop()
    output: asyncio.Queue[bytes] = asyncio.Queue()

    def readable() -> None:
        try:
            data = os.read(fd, 65536)
        except OSError:
            data = b""
        output.put_nowait(data)   # b"" means the shell exited
        if not data:
            loop.remove_reader(fd)

    loop.add_reader(fd, readable)

    async def send_output() -> None:
        while (data := await output.get()):
            await ws.send_bytes(data)
        await ws.close(code=1000, reason="The shell exited.")

    sender = asyncio.create_task(send_output())
    try:
        while not sender.done():
            message = await ws.receive_json()
            if message.get("type") == "input":
                os.write(fd, message.get("data", "").encode())
            elif message.get("type") == "resize":
                _resize(fd, int(message.get("cols", 80)), int(message.get("rows", 24)))
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        loop.remove_reader(fd)
        sender.cancel()
        _end(pid, fd)
