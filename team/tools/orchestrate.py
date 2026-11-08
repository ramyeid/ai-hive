#!/usr/bin/env python3
"""The Orchestrator's controls over the team, through the running console.

Reading is immediate. Every action waits for the lead to approve it (in the console or in Slack); if the lead
hasn't answered within ~100 seconds, this says so and the action happens later, when they approve.

  orchestrate.py status                      every open task, who has it, what waits on the lead, the team
  orchestrate.py task TASK-012               one task: status, who, links (task page, code review)
  orchestrate.py start Nabil                 start an agent (by name or id)
  orchestrate.py stop dev-2                  stop an agent
  orchestrate.py tell Nabil "message"        pass a message to an agent
  orchestrate.py hand TASK-012 Wael ["note"] give a task to an agent (the console's hand-off prompt + your note)
  orchestrate.py coach [TASK-012,TASK-019 | all | <project>]   start a Coach review (default: since its last one)

Needs CONSOLE_API and CONSOLE_ORCHESTRATOR_KEY, which the console gives the Orchestrator.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

API = os.environ.get("CONSOLE_API", "http://127.0.0.1:8420").rstrip("/")
KEY = os.environ.get("CONSOLE_ORCHESTRATOR_KEY", "")


def call(method: str, path: str, body: dict | None = None):
    request = urllib.request.Request(API + path, method=method, headers={"x-orchestrator": KEY, "content-type": "application/json"},
                                     data=json.dumps(body).encode() if body is not None else None)
    try:
        with urllib.request.urlopen(request, timeout=130) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read()).get("detail", "")
        except ValueError:
            detail = ""
        sys.exit(detail or f"The console answered {exc.code}.")
    except urllib.error.URLError as exc:
        sys.exit(f"Can't reach the console at {API} ({exc.reason}). Is it running?")


def show_status(s: dict) -> None:
    print("Team:")
    for a in s["team"]:
        extra = f", on {a['task']}" if a["task"] else ""
        extra += f", waiting for the lead's approval ({a['approvals_waiting']})" if a["approvals_waiting"] else ""
        if a["stopped_for_you"]:
            extra += f", stopped on {a['stopped_for_you']['task'] or 'its last message'} waiting for the lead"
        print(f"  {a['name']} [{a['id']}]: {a['status']}{extra}")
    print("\nOpen tasks:" if s["tasks"] else "\nNo open tasks.")
    for t in s["tasks"]:
        print(f"  {t['id']} {t['title']} ({t['project']}): {t['status']}{', with ' + t['with'] if t['with'] else ''}  {t['link']}")
    if s["waiting_on_a_hand_off"]:
        print("\nWaiting for someone to be handed them (the lead decides who):")
        for t in s["waiting_on_a_hand_off"]:
            who = f" → can go to {', '.join(t['candidates'])}" if t["candidates"] else ""
            review = f"  review the diff: {t['review']}" if t["review"] else ""
            print(f"  {t['id']} {t['title']}: {t['status']}{who}{review}")
    if s["agents_stopped_for_you"]:
        print("\nAgents that stopped and are waiting for the lead (their last words):")
        for a in s["agents_stopped_for_you"]:
            said = " ".join(a["said"].split())[:300]
            print(f"  {a['agent']}{' on ' + a['task'] if a['task'] else ''}: \"{said}\"  {a['chat']}")
    if s["approvals_waiting"]:
        print("\nAgents waiting for the lead's approval:")
        for a in s["approvals_waiting"]:
            print(f"  {a['agent']} wants to use {a['tool']}  {a['link']}")
    if s["recently_done"]:
        print("\nRecently done:")
        for t in s["recently_done"]:
            print(f"  {t['id']} {t['title']}  review the diff: {t['review']}")
    print(f"\nConsole: {s['console']}")


def act(body: dict) -> None:
    result = call("POST", "/api/orchestrator/act", body)
    print(result["message"])
    if not result.get("done") and not result.get("waiting"):
        sys.exit(1)


def main(argv: list[str]) -> None:
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return
    command, args = argv[0], argv[1:]
    if command == "status":
        show_status(call("GET", "/api/orchestrator/status"))
    elif command == "task" and len(args) == 1:
        print(json.dumps(call("GET", f"/api/orchestrator/tasks/{args[0]}"), indent=2))
    elif command in ("start", "stop") and len(args) == 1:
        act({"action": command, "agent": args[0]})
    elif command == "tell" and len(args) >= 2:
        act({"action": "tell", "agent": args[0], "text": " ".join(args[1:])})
    elif command == "hand" and len(args) >= 2:
        act({"action": "hand", "task": args[0], "agent": args[1], "text": " ".join(args[2:])})
    elif command == "coach":
        act({"action": "coach", "text": " ".join(args)})
    else:
        sys.exit(f"Not understood: {' '.join(argv)}\n\n{__doc__}")


if __name__ == "__main__":
    main(sys.argv[1:])
