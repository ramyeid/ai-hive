"""Files you attach in a chat: kept in data/uploads/<date>/, read by the agents with team/tools/files.py.

The message carries one `📎 <path>` line per file; the console shows those as chips (and pictures as pictures).
"""
from __future__ import annotations

import datetime as dt
import re
import urllib.parse
from pathlib import Path

from .store import KIT

UPLOADS = KIT / "data" / "uploads"
MAX_BYTES = 50 * 1024 * 1024


class UploadError(Exception):
    pass


async def receive(chunks, name: str) -> dict:
    name = Path(urllib.parse.unquote(name)).name.strip()
    stem, ext = Path(name).stem, Path(name).suffix.lower()
    stem = re.sub(r"[^\w.\- ]+", "_", stem).strip(" .") or "file"
    ext = re.sub(r"[^\w.]", "", ext)[:10]
    folder = UPLOADS / dt.date.today().isoformat()
    folder.mkdir(parents=True, exist_ok=True)
    target, n = folder / f"{stem}{ext}", 2
    while target.exists():   # the same name twice in a day: keep both
        target, n = folder / f"{stem} ({n}){ext}", n + 1
    size = 0
    try:
        with target.open("wb") as f:
            async for chunk in chunks:
                size += len(chunk)
                if size > MAX_BYTES:
                    raise UploadError(f"{name} is over {MAX_BYTES // 1024 // 1024} MB.")
                f.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    if not size:
        target.unlink(missing_ok=True)
        raise UploadError(f"{name} is empty.")
    return {"path": str(target), "rel": target.relative_to(UPLOADS).as_posix(), "name": target.name, "size": size}


def find(rel: str) -> Path | None:
    path = (UPLOADS / rel).resolve()
    if UPLOADS.resolve() not in path.parents or not path.is_file():
        return None
    return path
