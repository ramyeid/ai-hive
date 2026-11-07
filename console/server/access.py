"""Who can open the console.

By default, only this machine: http://localhost:8420, and nothing else is accepted (other sites can't drive your
agents through your browser). To run it on a server (an EC2 behind your VPN, say) and open it from your laptop or
phone, set:

    HOST=0.0.0.0                                 listen on the network, not only on this machine
    CONSOLE_HOSTS=hive.internal.example.com      the name(s) people type to reach it (comma-separated)
    CONSOLE_PASSWORD=…                           required with CONSOLE_HOSTS: each browser signs in once
    CONSOLE_URL=http://hive.internal.example.com:8420   the address put in links (Slack, the Orchestrator)

Opened from this machine (localhost) it never asks for the password.
"""
from __future__ import annotations

import hashlib
import hmac
import os

LOCAL_HOSTS = {"127.0.0.1", "localhost"}
COOKIE = "team_console"
MAX_AGE = 30 * 24 * 3600   # signed in for 30 days per browser


def extra_hosts() -> set[str]:
    return {h.strip().lower() for h in os.environ.get("CONSOLE_HOSTS", "").split(",") if h.strip()}


def allowed(host: str) -> bool:
    return host in LOCAL_HOSTS or host.lower() in extra_hosts()


def is_local(host: str) -> bool:
    return host in LOCAL_HOSTS


def check_config() -> None:
    if extra_hosts() and len(os.environ.get("CONSOLE_PASSWORD", "")) < 8:
        raise RuntimeError("CONSOLE_HOSTS is set, so the console is reachable from other machines: "
                           "set CONSOLE_PASSWORD too (8 characters or more).")


def session_value() -> str:
    """The sign-in cookie: derived from the password, so changing the password signs everyone out."""
    return hmac.new(os.environ.get("CONSOLE_PASSWORD", "").encode(), b"team-console-session", hashlib.sha256).hexdigest()


def signed_in(cookies: dict) -> bool:
    return bool(extra_hosts()) and hmac.compare_digest(cookies.get(COOKIE, ""), session_value())


def password_ok(given: str) -> bool:
    expected = os.environ.get("CONSOLE_PASSWORD", "")
    return bool(expected) and hmac.compare_digest(given.encode(), expected.encode())


def login_page(error: str = "") -> str:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Team console: sign in</title>
<style>
  :root {{ color-scheme: light dark; --bg:#eceff2; --panel:#fff; --ink:#18202a; --muted:#5d6672; --rule:#d5dae0; --bad:#a3164e; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#14181d; --panel:#1c2128; --ink:#e6e9ed; --muted:#9aa3ad; --rule:#2e353e; --bad:#f07aa5; }} }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:var(--bg); color:var(--ink);
         font:16px/1.5 system-ui, -apple-system, "Segoe UI", sans-serif; padding:16px; box-sizing:border-box; }}
  form {{ width:100%; max-width:360px; background:var(--panel); border:1px solid var(--rule); border-radius:10px; padding:24px; }}
  h1 {{ font-size:1.25rem; margin:0 0 4px; }} p {{ color:var(--muted); margin:0 0 16px; }}
  label {{ display:block; font-weight:500; margin-bottom:4px; }}
  input {{ width:100%; box-sizing:border-box; font:inherit; padding:8px 10px; border:1px solid var(--rule); border-radius:6px;
          background:var(--panel); color:var(--ink); }}
  button {{ margin-top:12px; width:100%; font:inherit; font-weight:600; padding:9px; border:0; border-radius:6px;
           background:var(--ink); color:var(--panel); cursor:pointer; }}
  .error {{ color:var(--bad); margin:8px 0 0; }}
</style></head><body>
<form method="post" action="/login">
  <h1>Team console</h1><p>Sign in to open the console from this browser.</p>
  <label for="password">Password</label>
  <input type="password" id="password" name="password" autocomplete="current-password" autofocus required>
  <input type="hidden" name="next" id="next">
  {f'<p class="error" role="alert">{error}</p>' if error else ''}
  <button>Sign in</button>
</form>
<script>document.getElementById("next").value = location.hash;</script>
</body></html>"""
