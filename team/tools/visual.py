#!/usr/bin/env python3
"""Pictures for the lead: a screenshot of a screen as it is, and a preview of a mockup of what it would become.

    python3 visual.py dir <topic>                     the folder for this topic's pictures (made if missing)
    python3 visual.py shot <url> <out.png> [--wait-for <css selector>] [--full]
                                                     a screenshot of the running app, 1280 x 800
    python3 visual.py preview <mockup.html>           <mockup>.png next to it: what the console shows in the chat

Pictures live in data/visuals/<topic>/ and go into messages and specs as Markdown images:
`![Now](visuals/<topic>/now.png)`, `![Proposed](visuals/<topic>/proposed.html)` (the console shows its preview, and
"open full size" opens the mockup itself). Diagrams are ```mermaid blocks and need no file.

Screenshots need a browser: Playwright for Python, or Playwright for Node. Standard library only otherwise; when
there is no browser this says so (exit code 3), and the screen is rebuilt as a mockup instead.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tasklib import DATA  # noqa: E402

VISUALS = DATA / "visuals"
WIDTH, HEIGHT = 1280, 800
NO_BROWSER = 3

NODE_SHOT = """
const { chromium } = require('playwright');
(async () => {
  const [url, out, waitFor, full] = JSON.parse(process.argv[1]);
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: %d, height: %d }, deviceScaleFactor: 2 });
  await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
  if (waitFor) await page.waitForSelector(waitFor, { timeout: 20000 });
  await page.waitForTimeout(500);
  await page.screenshot({ path: out, fullPage: full });
  await browser.close();
})().catch((e) => { console.error(e.message); process.exit(1); });
""" % (WIDTH, HEIGHT)


def folder(topic: str) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,60}", topic):
        sys.exit("A topic is a short name in lowercase letters, digits and dashes, like orders-csv-export.")
    path = VISUALS / topic
    path.mkdir(parents=True, exist_ok=True)
    return path


def _with_python(url: str, out: Path, wait_for: str | None, full: bool) -> bool | None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return None
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT}, device_scale_factor=2)
        page.goto(url, wait_until="networkidle", timeout=45000)
        if wait_for:
            page.wait_for_selector(wait_for, timeout=20000)
        page.wait_for_timeout(500)
        page.screenshot(path=str(out), full_page=full)
        browser.close()
    return True


def _with_node(url: str, out: Path, wait_for: str | None, full: bool) -> bool | None:
    node, npm = shutil.which("node"), shutil.which("npm")
    if not node or not npm:
        return None
    root = subprocess.run([npm, "root", "-g"], capture_output=True, text=True).stdout.strip()
    env = {**os.environ, "NODE_PATH": root}
    if subprocess.run([node, "-e", "require.resolve('playwright')"], env=env, capture_output=True).returncode:
        return None
    done = subprocess.run([node, "-e", NODE_SHOT, json.dumps([url, str(out), wait_for, full])], env=env,
                          capture_output=True, text=True)
    if done.returncode:
        sys.exit(f"The screenshot failed: {done.stderr.strip() or done.stdout.strip()}")
    return True


def shot(url: str, out: Path, wait_for: str | None = None, full: bool = False) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    for way in (_with_python, _with_node):
        if way(url, out, wait_for, full):
            print(out)
            return
    print("No browser here to take screenshots with (Playwright for Python or Node). Rebuild the screen as it is "
          "today as a mockup from the code instead, and label it \"Now (rebuilt from the code)\".", file=sys.stderr)
    sys.exit(NO_BROWSER)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__.strip())
        return
    command, rest = argv[0], argv[1:]
    if command == "dir" and len(rest) == 1:
        print(folder(rest[0]))
    elif command == "shot" and len(rest) >= 2:
        wait_for = rest[rest.index("--wait-for") + 1] if "--wait-for" in rest else None
        shot(rest[0], Path(rest[1]).resolve(), wait_for, "--full" in rest)
    elif command == "preview" and len(rest) == 1:
        mockup = Path(rest[0]).resolve()
        if not mockup.is_file():
            sys.exit(f"No mockup at {mockup}.")
        shot(mockup.as_uri(), mockup.with_suffix(".png"))
    else:
        sys.exit(__doc__.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
