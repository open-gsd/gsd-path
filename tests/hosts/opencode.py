"""OpenCode headless runner (verified live 2026-09-06, opencode 1.18.25).

`opencode run --format json --auto --pure` reads the prompt on stdin and prints one
JSON event per line (``step_start``, ``text``, ``tool_use``, ``step_finish``); every
event carries ``sessionID``. Children are ``task`` tool calls (the ``Task`` child API):
the ``tool_use`` event's ``part.state`` holds the call input (``description`` is the
logical task name), ``status``, the child's ``<task id=... state=...>`` output, and
``metadata.sessionId`` for the child session. OpenCode also persists every session in
its sqlite store (``session`` table, child rows carry ``parent_id``); ``bind_child``
attaches that row when the store is present.
"""

import hashlib
import json
import os
import re
import sqlite3
from pathlib import Path

from tests.hosts import HostSpec

SESSION_DB = Path.home() / ".local" / "share" / "opencode" / "opencode.db"
TASK_TAG = re.compile(r'<task id="([^"]+)" state="([^"]+)">')


def command(prompt_path, resume=None):
    args = ["opencode", "run", "--format", "json", "--auto", "--pure"]
    model = os.environ.get("GSD_OPENCODE_MODEL")
    if model:
        args += ["--model", model]
    if resume:
        args += ["--session", resume]
    return args


def _events(lines):
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def parse_events(lines):
    session = final = usage = None
    for ev in _events(lines):
        session = ev.get("sessionID") or session
        part = ev.get("part", {})
        if ev.get("type") == "text":
            final = part.get("text")
        elif ev.get("type") == "step_finish":
            usage = {"tokens": part.get("tokens"), "cost": part.get("cost")}
    return {"session_id": session, "final_message": final, "usage": usage}


def session_row(session_id, db=None):
    """Return the persisted session row for ``session_id`` or None when the store is absent."""
    db = Path(db or SESSION_DB)
    if not session_id or not db.exists():
        return None
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        row = conn.execute("select id, parent_id, title, agent, model, time_created, time_updated from session where id = ?",
                           (session_id,)).fetchone()
    if row is None:
        return None
    return dict(zip(("id", "parent_id", "title", "agent", "model", "time_created", "time_updated"), row))


def bind_child(run_root, child_id):
    """Bind the ``task`` tool call whose description is the logical task name to its completion.

    A child is complete when the tool call state is ``completed`` and its output tag
    reports ``state="completed"``; the child session id comes from that tag (and
    ``metadata.sessionId``).
    """
    attempts = []
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError):
                continue
            part = ev.get("part", {})
            if ev.get("type") != "tool_use" or part.get("tool") != "task":
                continue
            state = part.get("state", {}); inp = state.get("input", {})
            if inp.get("description") != child_id:
                continue
            output = str(state.get("output", "")); tag = TASK_TAG.search(output)
            attempts.append({"run": events.parent.name, "parent_session": ev.get("sessionID"), "call_id": part.get("callID"),
                             "status": state.get("status"), "task_state": tag.group(2) if tag else None,
                             "child_session": (tag.group(1) if tag else None) or state.get("metadata", {}).get("sessionId"),
                             "input": {k: v for k, v in inp.items() if k != "prompt"},
                             "prompt_sha256": hashlib.sha256(str(inp.get("prompt", "")).encode()).hexdigest(),
                             "output": output[:4000], "metadata": state.get("metadata")})
    completed = [a for a in attempts if a["status"] == "completed" and a["task_state"] == "completed"]
    if not completed:
        raise LookupError(f"no completed task child with description {child_id!r} in {run_root}")
    a = completed[-1]
    return {"child_id": child_id, "status": "completed", "child_api": "Task", **a, "session_row": session_row(a["child_session"])}


SPEC = HostSpec(
    name="opencode", install_flag="--opencode", skill_root=".opencode/skills", invocation="gsd-path",
    child_api="Task", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, verified_live=True,
    notes="The stream names the tool 'task' (lowercase) and puts the child's session id in the output tag. "
          "--pure keeps operator plugins out of the run; MCP servers from the user config still load. "
          "--auto approves permissions; there is no host guard hook (git-only tier). Live checks: stdin prompt, "
          "--format json, --session resume, one Task child named build_probe; the installed skill was not invoked.",
)
