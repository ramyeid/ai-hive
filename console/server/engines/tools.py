"""The tools agents get when they run on a non-Claude model.

Names and arguments mirror Claude Code's (Read, Write, Edit, Glob, Grep, Bash), so
the agents' instructions, the console UI and the task hook work the same way.

Approval rules mirror the kit's Claude Code setup:
- reading and searching inside the workspace or the kit: allowed
- editing task files on the board, running the kit's own scripts: allowed
- other edits: ask the lead (or allowed, if the agent is set to "Allow automatically")
- any other command, anything outside the workspace and kit: ask the lead
"""
from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import re
import shutil
from pathlib import Path

OUTPUT_LIMIT = 30_000      # characters of tool output sent back to the model
READ_LINES = 2000          # default lines per Read
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "bin", "obj", "dist", "build", "target"}

SCHEMAS = [
    {"name": "Read", "description": "Read a text file. Returns numbered lines. Use offset/limit for large files.",
     "parameters": {"type": "object", "properties": {
         "file_path": {"type": "string", "description": "Absolute path, or relative to the working directory."},
         "offset": {"type": "integer", "description": "First line to read (1-based)."},
         "limit": {"type": "integer", "description": f"Number of lines (default {READ_LINES})."}},
         "required": ["file_path"]}},
    {"name": "Write", "description": "Create a file or replace its whole content. Read existing files first; prefer Edit for changes.",
     "parameters": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "content": {"type": "string"}},
         "required": ["file_path", "content"]}},
    {"name": "Edit", "description": "Replace an exact piece of text in a file. old_string must match exactly once (include enough surrounding lines), unless replace_all is true.",
     "parameters": {"type": "object", "properties": {
         "file_path": {"type": "string"}, "old_string": {"type": "string"}, "new_string": {"type": "string"},
         "replace_all": {"type": "boolean"}},
         "required": ["file_path", "old_string", "new_string"]}},
    {"name": "Glob", "description": "Find files by name pattern, e.g. **/*.py or src/**/Controller*.cs.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string", "description": "Folder to search (default: working directory)."}},
         "required": ["pattern"]}},
    {"name": "Grep", "description": "Search file contents with a regular expression. Returns file:line: text.",
     "parameters": {"type": "object", "properties": {
         "pattern": {"type": "string"}, "path": {"type": "string"},
         "glob": {"type": "string", "description": "Only files matching this name pattern, e.g. *.ts"}},
         "required": ["pattern"]}},
    {"name": "Bash", "description": "Run a shell command (bash) and return its output. Start with `cd <folder> &&` to work in a project.",
     "parameters": {"type": "object", "properties": {
         "command": {"type": "string"},
         "timeout": {"type": "integer", "description": "Seconds, default 120, max 600."}},
         "required": ["command"]}},
]

OPENAI_TOOLS = [{"type": "function", "function": schema} for schema in SCHEMAS]


class ToolError(Exception):
    pass


class Toolbox:
    def __init__(self, workspace: Path, kit: Path, env: dict | None = None) -> None:
        self.workspace = workspace.resolve()
        self.kit = kit.resolve()
        self.env = {**os.environ, **(env or {})}

    # ---- approval policy ---------------------------------------------------------

    def path(self, raw: str) -> Path:
        path = Path(os.path.expanduser(raw or "."))
        return (path if path.is_absolute() else self.workspace / path).resolve()

    def _inside(self, path: Path) -> bool:
        return any(path == root or root in path.parents for root in (self.workspace, self.kit))

    def needs_approval(self, name: str, args: dict, permission_mode: str) -> bool:
        if name in ("Read", "Glob", "Grep"):
            return not self._inside(self.path(args.get("file_path") or args.get("path") or "."))
        if name in ("Write", "Edit"):
            path = self.path(args.get("file_path", ""))
            if path.parent == self.kit / "tasks" and path.name.startswith("TASK-"):
                return False
            if path.parent == self.kit / "knowledge" and path.suffix == ".md":
                return False
            return not (permission_mode == "acceptEdits" and self._inside(path))
        if name == "Bash":
            command = args.get("command", "")
            own_script = command.startswith(f"python3 {self.kit}/scripts/")
            return not (own_script and not re.search(r"[;&|`$<>]", command))
        return True

    # ---- running tools ---------------------------------------------------------------

    async def run(self, name: str, args: dict) -> tuple[str, bool]:
        """Returns (output for the model, is_error)."""
        try:
            handler = getattr(self, f"_{name.lower()}", None)
            if not handler:
                raise ToolError(f"Unknown tool {name}. Available: Read, Write, Edit, Glob, Grep, Bash.")
            output = await handler(**args)
            if name in ("Write", "Edit"):
                output += await self._task_hook(self.path(args["file_path"]))
            return _limit(output), False
        except ToolError as exc:
            return str(exc), True
        except TypeError as exc:
            return f"Wrong arguments for {name}: {exc}", True
        except (OSError, ValueError) as exc:
            return f"{name} failed: {exc}", True

    async def _read(self, file_path: str, offset: int = 1, limit: int = READ_LINES) -> str:
        path = self.path(file_path)
        if not path.is_file():
            raise ToolError(f"File not found: {path}")
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(offset or 1))
        chunk = lines[start - 1:start - 1 + int(limit or READ_LINES)]
        if not chunk:
            return f"(no lines from {start}; the file has {len(lines)} lines)"
        body = "\n".join(f"{n:>6}\t{line}" for n, line in enumerate(chunk, start))
        end = start + len(chunk) - 1
        return body + (f"\n… {len(lines) - end} more lines (use offset={end + 1})" if end < len(lines) else "")

    async def _write(self, file_path: str, content: str) -> str:
        path = self.path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed = path.exists()
        path.write_text(content, encoding="utf-8")
        return f"{'Updated' if existed else 'Created'} {path} ({len(content.splitlines())} lines)."

    async def _edit(self, file_path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
        path = self.path(file_path)
        if not path.is_file():
            raise ToolError(f"File not found: {path}")
        text = path.read_text(encoding="utf-8")
        count = text.count(old_string) if old_string else 0
        if count == 0:
            raise ToolError("old_string was not found. Read the file again and copy the text exactly.")
        if count > 1 and not replace_all:
            raise ToolError(f"old_string matches {count} places. Include more surrounding lines, or set replace_all.")
        path.write_text(text.replace(old_string, new_string, -1 if replace_all else 1), encoding="utf-8")
        return f"Edited {path} ({count if replace_all else 1} replacement{'s' if replace_all and count > 1 else ''})."

    async def _glob(self, pattern: str, path: str = ".") -> str:
        root = self.path(path)
        matches = []
        for found in root.glob(pattern):
            if not SKIP_DIRS.intersection(found.relative_to(root).parts) and found.is_file():
                matches.append(str(found))
                if len(matches) >= 500:
                    break
        return "\n".join(sorted(matches)) or "No files found."

    async def _grep(self, pattern: str, path: str = ".", glob: str = "") -> str:
        root = self.path(path)
        if shutil.which("rg"):
            cmd = ["rg", "-n", "--no-heading", "--max-count", "50", "-e", pattern]
            if glob:
                cmd += ["-g", glob]
            proc = await asyncio.create_subprocess_exec(*cmd, str(root), stdout=asyncio.subprocess.PIPE,
                                                        stderr=asyncio.subprocess.PIPE)
            out, err = await proc.communicate()
            if proc.returncode == 2:
                raise ToolError(err.decode(errors="replace").strip())
            lines = out.decode(errors="replace").splitlines()
        else:
            lines = _python_grep(pattern, root, glob)
        return "\n".join(lines[:300]) + (f"\n… {len(lines) - 300} more" if len(lines) > 300 else "") if lines else "No matches."

    async def _bash(self, command: str, timeout: int = 120) -> str:
        timeout = max(1, min(int(timeout or 120), 600))
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command, cwd=self.workspace, env=self.env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        try:
            out, _ = await asyncio.wait_for(proc.communicate(), timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
            _kill(proc)
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ToolError(f"Command timed out after {timeout} s and was stopped.")
        text = out.decode(errors="replace").strip()
        return f"{text}\n(exit code {proc.returncode})" if proc.returncode else (text or "(no output)")

    async def _task_hook(self, path: Path) -> str:
        """The same hook Claude Code runs: readiness gate, notifications, board refresh."""
        if path.parent != self.kit / "tasks" or not path.name.startswith("TASK-"):
            return ""
        proc = await asyncio.create_subprocess_exec(
            "python3", str(self.kit / "scripts" / "on_task_change.py"), env=self.env,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        _, err = await proc.communicate(json.dumps({"tool_input": {"file_path": str(path)}}).encode())
        message = err.decode(errors="replace").strip()
        return f"\n\nTask hook:\n{message}" if proc.returncode == 2 and message else ""


def _python_grep(pattern: str, root: Path, glob: str) -> list[str]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"Invalid regular expression: {exc}")
    found = []
    files = [root] if root.is_file() else root.rglob("*")
    for path in files:
        if not path.is_file() or SKIP_DIRS.intersection(path.parts) or (glob and not fnmatch.fnmatch(path.name, glob)):
            continue
        try:
            for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if regex.search(line):
                    found.append(f"{path}:{n}:{line[:300]}")
        except (UnicodeDecodeError, OSError):
            continue
        if len(found) > 1000:
            break
    return found


def _kill(proc) -> None:
    try:
        os.killpg(proc.pid, 9)
    except (ProcessLookupError, PermissionError):
        pass


def _limit(text: str) -> str:
    return text if len(text) <= OUTPUT_LIMIT else text[:OUTPUT_LIMIT] + f"\n… (output cut at {OUTPUT_LIMIT} characters)"
