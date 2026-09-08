"""Cursor Agent CLI headless runner (verified live 2026-09-07, cursor-agent 2026.08.11, Composer 2.5).

`cursor-agent -p --output-format stream-json --force --trust "<prompt>"` prints one JSON
object per line (documented at cursor.com/docs/cli/reference/output-format). The prompt is
a positional argument, so ``prompt_on_stdin`` is False and ``command`` places the prompt
text into argv. Children are calls to Cursor's ``Task`` tool with the installed custom
``gsd-path`` subagent; a tool call appears as a ``tool_call`` event with subtype
``started`` and, later, ``completed`` under the same ``call_id``.

The local binary ``~/.local/bin/cursor`` is a shim that execs the Cursor IDE launcher when
one is on PATH, so the headless CLI is invoked as ``cursor-agent`` (symlink to
``~/.local/share/cursor-agent/versions/<version>/cursor-agent``).
"""

import hashlib
import json
from pathlib import Path

from tests.hosts import HostSpec

CHILD_TOOL = "Task"


def command(prompt_path, resume=None):
    args = ["cursor-agent", "-p", "--output-format", "stream-json", "--force", "--trust"]
    if resume:
        args += ["--resume", resume]
    return args + [Path(prompt_path).read_text()]


def _events(lines):
    for line in lines:
        try:
            yield json.loads(line)
        except ValueError:
            continue


def parse_events(lines):
    session = final = usage = None
    for ev in _events(lines):
        session = ev.get("session_id") or session
        if ev.get("type") == "result":
            final, usage = ev.get("result"), ev.get("usage")  # usage is not in the documented schema; None when absent
    return {"session_id": session, "final_message": final, "usage": usage}


def _tool_call(ev):
    """Return (tool_key, payload) for a ``tool_call`` event, else (None, None).

    The documented shape is ``{"tool_call": {"<name>ToolCall": {"args": ..., "result": ...}}}``; the live
    body adds ``toolCallId``, ``startedAtMs`` and ``completedAtMs`` beside the ``<name>ToolCall`` key.
    """
    body = ev.get("tool_call")
    if ev.get("type") != "tool_call" or not isinstance(body, dict):
        return None, None
    keys = [k for k in body if k.endswith("ToolCall")]
    if len(keys) != 1:
        return None, None
    payload = body[keys[0]]
    return keys[0], payload if isinstance(payload, dict) else {}


def _is_child(key, payload, child_id):
    return key.lower().startswith(CHILD_TOOL.lower()) and payload.get("args", {}).get("description") == child_id


def bind_child(run_root, child_id):
    """Bind the Task tool call whose description is the logical task name to its completion.

    Completion is the ``tool_call``/``completed`` event with the same ``call_id`` whose
    ``result`` carries a ``success`` key. The installed ``gsd-path`` subagent is foreground
    (no ``is_background`` in its frontmatter), so the completed event is the child's return.
    Only the recorded stream is read: ``~/.cursor/chats/*/*/store.db`` holds opaque
    content-addressed blobs with no documented transcript format.
    """
    attempts = {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            key, payload = _tool_call(ev)
            if key is None or not _is_child(key, payload, child_id):
                continue
            call_id = ev.get("call_id")
            args = payload.get("args", {})
            attempt = attempts.setdefault(call_id, {
                "run": events.parent.name, "session_id": ev.get("session_id"), "tool_key": key,
                "tool_use": {"id": call_id, "input": {k: v for k, v in args.items() if k != "prompt"},
                             "prompt_sha256": hashlib.sha256(str(args.get("prompt", "")).encode()).hexdigest()}})
            if ev.get("subtype") == "completed":
                result = payload.get("result", {})
                attempt["tool_result"] = {"is_error": "success" not in result, "content": json.dumps(result)[:4000]}
    completed = [a for a in attempts.values() if a.get("tool_result") and not a["tool_result"]["is_error"]]
    if not completed:
        raise LookupError(f"no completed {CHILD_TOOL} child with description {child_id!r} in {run_root}")
    return {"child_id": child_id, "status": "completed", "child_api": CHILD_TOOL, **completed[-1]}


SPEC = HostSpec(
    name="cursor", install_flag="--cursor", skill_root=".cursor/skills", invocation="/gsd-path",
    child_api=CHILD_TOOL, guard_tier="native-fail-closed", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=True,
    notes=(
        "Verified live (2026-09-07): `-p --output-format stream-json --force --trust <prompt>` streams system/init, "
        "user, thinking, assistant, tool_call started|completed and result (session_id on each); a foreground Task "
        "child with description build_probe completed as `taskToolCall.result.success`; `--resume <session_id>` "
        "resumed the same session. Cursor exposes no tool that lists child agents. Not verified: the installed "
        "/gsd-path skill end to end and the native guard probe (see extra)."
    ),
    extra={
        "native_guard_probe": (
            "UNVERIFIED (guard not exercised in the 2026-09-07 live run; an allowed call must print an allow object, since Cursor treats empty stdout as a hook failure). Installer writes .cursor/hooks.json {version:1, hooks:{preToolUse:[{command, "
            "matcher:'.*', failClosed:true}]}}. Per the hooks docs, guard_hook.py denies with "
            "{permission:'deny', user_message, agent_message}; with failClosed the edit is also blocked on hook "
            "crash/timeout/invalid JSON. Expected headless evidence: a tool_call completed event for the edit tool "
            "whose result has no `success` key and carries the agent_message; the docs do not state the exact key. "
            "Do not cite a denial shape until one is observed."
        ),
    },
)
