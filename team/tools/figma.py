#!/usr/bin/env python3
"""Figma, read-only: what a design is made of, and a picture of it.

    python3 figma.py read <figma link> [--depth N]    the frame's layers: layout, sizes, spacing, text, colours,
                                                     then the colours and text styles it uses
    python3 figma.py frames <figma link>              a file's pages and their top-level frames, with their links
    python3 figma.py image <figma link> <topic> [name]
                                                     the frame as a PNG in data/visuals/<topic>/ (default name:
                                                     figma-<node>.png); prints the Markdown to show it in a message
    python3 figma.py whoami                           check the connection

A link is any figma.com/design/…, /file/…, /proto/… or /board/… URL; copy it from Figma with "Copy link to selection"
so it points at the frame (node-id=…). Needs Figma connected in Settings → Integrations. Standard library only.
"""
from __future__ import annotations

import re
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from connlib import ConnectorError, quote, request, require, run  # noqa: E402

API = "https://api.figma.com/v1"
MAX_LINES = 450


def parse_link(link: str) -> tuple[str, str]:
    """(file key, node id with a colon, or "") from a Figma URL."""
    m = re.search(r"figma\.com/(?:design|file|proto|board|make)/([A-Za-z0-9]+)", link)
    if not m:
        raise ConnectorError(f"Not a Figma link: {link}. Copy it from Figma (Share → Copy link, or right-click → "
                             "Copy link to selection).")
    query = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
    node = (query.get("node-id") or [""])[0].replace("-", ":")
    return m.group(1), node


def get(path: str, what: str):
    cfg = require("figma")
    return request("GET", f"{API}{path}", {"X-Figma-Token": cfg["token"]}, what=what)


def hex_color(c: dict, opacity: float = 1) -> str:
    rgb = "#" + "".join(f"{round(c.get(k, 0) * 255):02x}" for k in "rgb")
    a = c.get("a", 1) * opacity
    return rgb if a >= 0.995 else f"{rgb} {round(a * 100)}%"


def fill_of(node: dict) -> str:
    for f in node.get("fills") or []:
        if f.get("visible") is False:
            continue
        if f.get("type") == "SOLID":
            return hex_color(f["color"], f.get("opacity", 1))
        if f.get("type", "").startswith("GRADIENT"):
            return "gradient " + " → ".join(hex_color(s["color"]) for s in f.get("gradientStops", []))
        if f.get("type") == "IMAGE":
            return "image"
    return ""


def describe(node: dict, components: dict, seen: dict) -> str:
    """One line for a layer: type, name, size and the properties a developer needs."""
    t = node.get("type", "")
    box = node.get("absoluteBoundingBox") or {}
    parts = [f"{t.lower()} \"{node.get('name', '')}\""]
    if box:
        parts.append(f"{round(box.get('width', 0))}×{round(box.get('height', 0))}")
    if node.get("componentId") and components.get(node["componentId"]):
        parts.append(f"instance of {components[node['componentId']].get('name')}")
    mode = node.get("layoutMode")
    if mode in ("HORIZONTAL", "VERTICAL"):
        pad = [node.get(k, 0) for k in ("paddingTop", "paddingRight", "paddingBottom", "paddingLeft")]
        pad_text = (f"{round(pad[0])}" if len(set(pad)) == 1 else " ".join(str(round(p)) for p in pad))
        parts.append(f"auto layout {'row' if mode == 'HORIZONTAL' else 'column'}, gap {round(node.get('itemSpacing', 0))}, "
                     f"padding {pad_text}" + (f", align {node['primaryAxisAlignItems'].lower()}"
                                              if node.get("primaryAxisAlignItems") not in (None, "MIN") else ""))
    fill = fill_of(node)
    if fill and t != "TEXT":
        parts.append(f"fill {fill}")
        seen["colors"][fill] = seen["colors"].get(fill, 0) + 1
    for s in node.get("strokes") or []:
        if s.get("type") == "SOLID" and s.get("visible") is not False:
            parts.append(f"border {node.get('strokeWeight', 1)} {hex_color(s['color'], s.get('opacity', 1))}")
            break
    if node.get("cornerRadius"):
        parts.append(f"radius {round(node['cornerRadius'])}")
    for e in node.get("effects") or []:
        if e.get("type") == "DROP_SHADOW" and e.get("visible") is not False:
            o = e.get("offset", {})
            parts.append(f"shadow {round(o.get('x', 0))} {round(o.get('y', 0))} {round(e.get('radius', 0))} {hex_color(e['color'])}")
            break
    if t == "TEXT":
        st = node.get("style") or {}
        font = f"{st.get('fontFamily', '')} {st.get('fontWeight', '')} {st.get('fontSize', '')}px".strip()
        if st.get("lineHeightPx"):
            font += f"/{round(st['lineHeightPx'])}"
        color = fill_of(node)
        parts.append(font + (f" {color}" if color else ""))
        seen["text"][font] = seen["text"].get(font, 0) + 1
        if color:
            seen["colors"][color] = seen["colors"].get(color, 0) + 1
        text = " ".join((node.get("characters") or "").split())
        parts.append(f"\"{text[:160]}{'…' if len(text) > 160 else ''}\"")
    if node.get("visible") is False:
        parts.append("(hidden)")
    return ", ".join(parts)


def outline(node: dict, components: dict, depth: int) -> list[str]:
    seen = {"colors": {}, "text": {}}
    lines: list[str] = []

    def walk(n: dict, level: int) -> None:
        if len(lines) >= MAX_LINES:
            return
        lines.append("  " * level + "- " + describe(n, components, seen))
        kids = n.get("children") or []
        if level >= depth and kids:
            lines.append("  " * (level + 1) + f"- … {len(kids)} more layer{'s' if len(kids) > 1 else ''} "
                         "(read with a bigger --depth, or link the inner frame)")
            return
        for k in kids:
            walk(k, level + 1)

    walk(node, 0)
    if len(lines) >= MAX_LINES:
        lines.append(f"… cut at {MAX_LINES} lines: link a smaller frame for the rest.")
    if seen["colors"]:
        lines += ["", "Colours used: " + ", ".join(c for c, _ in sorted(seen["colors"].items(), key=lambda x: -x[1]))]
    if seen["text"]:
        lines += ["Text styles used: " + "; ".join(t for t, _ in sorted(seen["text"].items(), key=lambda x: -x[1]))]
    return lines


def cmd_read(args: list[str]) -> int:
    depth = 6
    if "--depth" in args:
        i = args.index("--depth")
        depth = int(args[i + 1])
        args = args[:i] + args[i + 2:]
    if not args:
        raise ConnectorError("Usage: figma.py read <figma link> [--depth N]")
    key, node = parse_link(args[0])
    if not node:
        print("This link points at the whole file, not a frame. Its frames:\n")
        return cmd_frames(args)
    data = get(f"/files/{key}/nodes?ids={quote(node)}", "Figma file")
    found = (data.get("nodes") or {}).get(node)
    if not found:
        raise ConnectorError(f"Frame {node} isn't in this file (deleted, or the link is from another file).")
    print(f"# {data.get('name', '')} · {found['document'].get('name', '')} (node {node})\n")
    print("\n".join(outline(found["document"], found.get("components") or {}, depth)))
    return 0


def cmd_frames(args: list[str]) -> int:
    if not args:
        raise ConnectorError("Usage: figma.py frames <figma link>")
    key, _ = parse_link(args[0])
    data = get(f"/files/{key}?depth=2", "Figma file")
    print(f"# {data.get('name', '')}  (last modified {data.get('lastModified', '')[:10]})")
    for page in data.get("document", {}).get("children", []):
        print(f"\n## {page.get('name')}")
        for frame in page.get("children", [])[:80]:
            if frame.get("type") in ("FRAME", "SECTION", "COMPONENT", "COMPONENT_SET"):
                print(f"- {frame.get('name')} ({frame.get('type').lower()}): "
                      f"https://www.figma.com/design/{key}/?node-id={frame['id'].replace(':', '-')}")
    return 0


def cmd_image(args: list[str]) -> int:
    if len(args) < 2:
        raise ConnectorError("Usage: figma.py image <figma link> <topic> [name]")
    import visual   # the visuals folder for this topic (data/visuals/<topic>/)
    key, node = parse_link(args[0])
    if not node:
        raise ConnectorError("Link a frame, not the whole file: in Figma, right-click the frame → Copy link to selection.")
    folder = visual.folder(args[1])
    name = re.sub(r"[^a-z0-9-]+", "-", (args[2] if len(args) > 2 else f"figma-{node.replace(':', '-')}").lower()).strip("-")
    data = get(f"/images/{key}?ids={quote(node)}&format=png&scale=2", "Figma image")
    if data.get("err"):
        raise ConnectorError(f"Figma couldn't render it: {data['err']}")
    url = (data.get("images") or {}).get(node)
    if not url:
        raise ConnectorError("Figma returned no picture for this frame (an empty or invisible layer?).")
    png = request("GET", url, raw=True, what="Figma image download")
    out = folder / f"{name}.png"
    out.write_bytes(png)
    rel = out.relative_to(folder.parent.parent)
    print(f"Saved {out}\nShow it with: ![Design (Figma)]({rel.as_posix()})")
    return 0


def cmd_whoami(_args: list[str]) -> int:
    me = get("/me", "Figma")
    print(f"Connected as {me.get('handle', '')} ({me.get('email', '')})")
    return 0


def main(argv: list[str]) -> int:
    commands = {"read": cmd_read, "frames": cmd_frames, "image": cmd_image, "whoami": cmd_whoami}
    if not argv or argv[0] not in commands:
        print(__doc__)
        return 0 if not argv else 1
    return commands[argv[0]](argv[1:])


if __name__ == "__main__":
    run(main)
