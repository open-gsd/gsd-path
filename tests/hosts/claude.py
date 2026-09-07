"""Claude Code headless runner (verified live 2026-09-06, claude 2.1.263).

`claude -p --output-format stream-json --verbose` prints one JSON object per line.
Children are Agent tool calls; a background child completes with a
``system``/``task_notification`` event bound to the launching tool_use id.
"""

import hashlib
import json
from pathlib import Path

from tests.hosts import HostSpec


def command(prompt_path, resume=None):
    args = ["claude", "-p", "--dangerously-skip-permissions", "--output-format", "stream-json", "--verbose"]
    if resume:
        args += ["--resume", resume]
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
        session = ev.get("session_id") or session
        if ev.get("type") == "result":
            final, usage = ev.get("result"), ev.get("usage")
    return {"session_id": session, "final_message": final, "usage": usage}


def bind_child(run_root, child_id):
    """Bind the Agent tool_use whose description is the logical task name to its completion.

    Background launch: completion is the ``task_notification`` system event whose
    ``tool_use_id`` matches and whose status is ``completed``. Foreground call: a
    non-error tool_result for the same tool_use id.
    """
    attempts = {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError):
                continue
            if ev.get("type") == "assistant":
                for c in ev["message"].get("content", []):
                    if c.get("type") == "tool_use" and c.get("name") == "Agent" and c["input"].get("description") == child_id:
                        attempts[c["id"]] = {"run": events.parent.name, "tool_use": {
                            "id": c["id"], "input": {k: v for k, v in c["input"].items() if k != "prompt"},
                            "prompt_sha256": hashlib.sha256(c["input"].get("prompt", "").encode()).hexdigest()}}
            elif ev.get("type") == "user":
                for c in ev["message"].get("content", []):
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("tool_use_id") in attempts:
                        attempts[c["tool_use_id"]]["tool_result"] = {"is_error": bool(c.get("is_error")), "content": str(c.get("content"))[:4000]}
            elif ev.get("type") == "system" and ev.get("tool_use_id") in attempts:
                a = attempts[ev["tool_use_id"]]
                if ev.get("subtype") == "task_started":
                    a["task_id"] = ev.get("task_id"); a["task_started"] = {k: ev.get(k) for k in ("task_id", "description", "subagent_type", "is_backgrounded")}
                elif ev.get("subtype") == "task_notification":
                    a["task_notification"] = {k: ev.get(k) for k in ("task_id", "status", "summary")}
    completed = []
    for a in attempts.values():
        background = (a["tool_use"]["input"].get("run_in_background")
                      or a.get("task_started", {}).get("is_backgrounded"))
        if background:
            if a.get("task_notification", {}).get("status") == "completed":
                completed.append(a)
        elif a.get("tool_result") and not a["tool_result"]["is_error"]:
            completed.append(a)
    if not completed:
        raise LookupError(f"no completed Agent child with description {child_id!r} in {run_root}")
    a = completed[-1]
    return {"child_id": child_id, "status": "completed", "child_api": "Agent", **a}


SPEC = HostSpec(
    name="claude", install_flag="--claude", skill_root=".claude/skills", invocation="/gsd-path",
    child_api="Agent", guard_tier="native-fail-closed", command=command, parse_events=parse_events,
    bind_child=bind_child, verified_live=True,
    notes="Native guard evidence: the PreToolUse denial appears in the Edit tool_result text, not as a hook_response event.",
)
