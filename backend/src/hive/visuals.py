"""The pictures the team draws for the lead: screenshots of a screen as it is, mockups of what it would become, and
diagrams. The Tech Lead saves them under data/visuals/<topic>/ and puts them in its messages and specs as Markdown
images (`![Now](visuals/orders-csv/now.png)`); the console shows them from here.

A mockup is a small HTML page. It is served with a sandboxing policy, so in the console (and opened on its own) it
runs with no access to the console, its cookies or anything else on this machine."""
from __future__ import annotations

from pathlib import Path

from .store import KIT

VISUALS = KIT / "data" / "visuals"

TYPES = {
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".gif": "image/gif",
    ".svg": "image/svg+xml", ".html": "text/html; charset=utf-8",
}
# A mockup (or an SVG) may style itself and run its own small scripts, and nothing more: no network, no forms,
# no reaching the console, which serves it from its own origin.
SANDBOX = ("sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; "
           "img-src data:; font-src data:")


def find(rel: str, root: Path | None = None) -> tuple[Path, str, dict] | None:
    """The file at data/visuals/<rel>, its media type and the headers to serve it with; None if there isn't one
    (or the path leaves data/visuals/, or it isn't a kind of picture the console shows)."""
    base = (root or VISUALS).resolve()
    target = (base / rel).resolve()
    if base not in target.parents or not target.is_file():
        return None
    kind = TYPES.get(target.suffix.lower())
    if not kind:
        return None
    headers = {"X-Content-Type-Options": "nosniff", "Cache-Control": "no-cache"}
    if target.suffix.lower() in (".html", ".svg"):
        headers["Content-Security-Policy"] = SANDBOX
    return target, kind, headers
