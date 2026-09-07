"""Kimi Code CLI headless runner (verified live 2026-09-06, kimi 0.41.0).

`kimi -p <prompt> --output-format stream-json` prints one JSON object per line and
takes the prompt on argv: there is no stdin form (`-p -` is read as the literal text
"-"). Prompt mode cannot be combined with `--auto`/`--yolo`; it ran tool calls
(including a file-writing `coder` child) without asking.

Children are `Agent` tool calls. The stream shows the call as an OpenAI-style
``tool_calls`` entry on an assistant line and the child's outcome as a ``role: tool``
line whose text starts with ``agent_id`` / ``actual_subagent_type`` / ``status`` /
``stop_reason`` headers. The session store under ``~/.kimi-code/sessions`` records the
child in ``state.json`` ``agents`` and in its own ``wire.jsonl`` (``turn.ended``).
"""

import hashlib
import json
import shutil
from pathlib import Path

from tests.hosts import HostSpec

SESSION_ROOT = Path.home() / ".kimi-code" / "sessions"


def binary():
    return shutil.which("kimi") or str(Path.home() / ".kimi-code" / "bin" / "kimi")


def command(prompt_path, resume=None):
    args = [binary()]
    if resume:
        args += ["-S", resume]
    return args + ["-p", Path(prompt_path).read_text(), "--output-format", "stream-json"]


def _events(lines):
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def parse_events(lines):
    session = final = None
    for ev in _events(lines):
        if ev.get("type") == "session.resume_hint":
            session = ev.get("session_id") or session
        elif ev.get("role") == "assistant" and ev.get("content"):
            final = ev["content"]
    return {"session_id": session, "final_message": final, "usage": None}  # stdout carries no usage


def _headers(text):
    """Parse the ``key: value`` header block that opens a child tool result."""
    out = {}
    for line in str(text).splitlines():
        if not line.strip():
            break
        key, sep, value = line.partition(":")
        if sep:
            out[key.strip()] = value.strip()
    return out


def session_evidence(session_id, agent_id):
    """What the session store recorded for the child, or None when it is not on disk."""
    for state_path in sorted(SESSION_ROOT.glob(f"*/session_{session_id.removeprefix('session_')}/state.json")):
        agent = json.loads(state_path.read_text()).get("agents", {}).get(agent_id)
        if agent is None:
            continue
        reasons = []
        wire = state_path.parent / "agents" / agent_id / "wire.jsonl"
        if wire.exists():
            reasons = [ev.get("reason") for ev in _events(wire.read_text().splitlines()) if ev.get("type") == "turn.ended"]
        return {"state": state_path.parent.name, "type": agent.get("type"), "labels": agent.get("labels", {}), "turn_ended_reasons": reasons}
    return None


def bind_child(run_root, child_id):
    """Bind the Agent tool call whose description is the logical task name to its completion.

    Completion is the ``role: tool`` line for the same tool_call id whose header block
    says ``status: completed``.
    """
    attempts = {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        session = None
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            if ev.get("type") == "session.resume_hint":
                session = ev.get("session_id")
                for a in attempts.values():
                    if a["run"] == events.parent.name:
                        a["session_id"] = session
            elif ev.get("role") == "assistant":
                for tc in ev.get("tool_calls") or []:
                    fn = tc.get("function", {})
                    if fn.get("name") != "Agent":
                        continue
                    try:
                        args = json.loads(fn.get("arguments", ""))
                    except ValueError:
                        continue
                    if args.get("description") == child_id:
                        attempts[tc["id"]] = {"run": events.parent.name, "session_id": session, "tool_call": {
                            "id": tc["id"], "input": {k: v for k, v in args.items() if k != "prompt"},
                            "prompt_sha256": hashlib.sha256(args.get("prompt", "").encode()).hexdigest()}}
            elif ev.get("role") == "tool" and ev.get("tool_call_id") in attempts:
                content = ev.get("content")
                attempts[ev["tool_call_id"]]["tool_result"] = {**_headers(content), "content": str(content)[:4000]}
    completed = [a for a in attempts.values() if a.get("tool_result", {}).get("status") == "completed"]
    if not completed:
        raise LookupError(f"no completed Agent child with description {child_id!r} in {run_root}")
    a = completed[-1]
    store = session_evidence(a["session_id"], a["tool_result"].get("agent_id", "")) if a.get("session_id") else None
    return {"child_id": child_id, "status": "completed", "child_api": "Agent", **a, "session_store": store}


SPEC = HostSpec(
    name="kimi", install_flag="--kimi", skill_root=".kimi-code/skills", invocation="/gsd-path",
    child_api="Agent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=True,
    notes="Prompt is argv (no stdin form). stdout has no usage; token counts live only in the session wire "
          "(usage.record), so usage is None. Live check covered a one-line reply, -S resume, and one coder child "
          "(build_probe); the guard tier is git-only, so ~/.kimi-code/config.toml hooks are not part of the receipt.",
)
