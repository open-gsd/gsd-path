"""Kiro CLI headless runner (verified live 2026-09-06, kiro-cli 2.21.1, GitHub login).

`kiro-cli chat --agent-engine v2 --no-interactive --trust-all-tools --output-format
stream-json` reads the prompt on stdin and prints one ACP event per line. The v1
engine rejects ``stream-json``, so the engine flag is required. Children are the v2
engine's crew tool: a ``sessionUpdate``/``tool_call`` whose ``_meta.kiro.toolName``
is ``subagent`` and whose ``rawInput.task`` (and ``stages[].name``) carry the logical
task name; completion is the ``tool_call_update`` with the same ``toolCallId`` and
``status`` ``completed``. Child turns appear in the same stream under their own
``sessionId``. Sessions land in ``~/.kiro/sessions/cli/<id>.json`` (a child records
``parent_session_id``) and ``<id>.jsonl`` (``ToolResults`` rows keyed by
``toolUseId``).

Limits: the manifest names the child API ``invoke_sub_agent``; the v2 engine stream
labels the same facility ``subagent`` (AgentCrew), so ``bind_child`` accepts both
names and reports the one it saw. The crew ``taskResult`` is not exposed on the
parent update beyond ``rawOutput`` text; no list-children call exists.
"""

import hashlib
import json
from pathlib import Path

from tests.hosts import HostSpec

SESSION_ROOT = Path.home() / ".kiro" / "sessions" / "cli"
CHILD_TOOLS = ("invoke_sub_agent", "subagent")


def command(prompt_path, resume=None):
    args = ["kiro-cli", "chat", "--agent-engine", "v2", "--no-interactive", "--trust-all-tools",
            "--output-format", "stream-json"]
    if resume:
        args += ["--resume-id", resume]
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
        data = ev.get("data") or {}
        if ev.get("type") == "runFinished":
            session, final = data.get("sessionId") or session, data.get("finalText")
        elif ev.get("type") == "metadata" and session is None:
            session = data.get("sessionId")
    for ev in _events(lines):
        data = ev.get("data") or {}
        if ev.get("type") == "metadata" and data.get("sessionId") == session and "meteringUsage" in data:
            usage = {k: data.get(k) for k in ("meteringUsage", "turnDurationMs", "contextUsagePercentage")}
    return {"session_id": session, "final_message": final, "usage": usage}


def _names(raw_input):
    names = {raw_input.get(k) for k in ("task", "description", "name")}
    names.update(s.get("name") for s in raw_input.get("stages", []) if isinstance(s, dict))
    return names


def _redacted(raw_input):
    out = {k: v for k, v in raw_input.items() if k not in ("stages", "prompt")}
    briefs = [raw_input.get("prompt", "")] + [s.get("prompt_template", "") for s in raw_input.get("stages", []) if isinstance(s, dict)]
    out["stages"] = [{k: v for k, v in s.items() if k != "prompt_template"} for s in raw_input.get("stages", []) if isinstance(s, dict)]
    out["prompt_sha256"] = hashlib.sha256("".join(briefs).encode()).hexdigest()
    return out


def _session_store(parent, tool_call_id):
    """Evidence from ~/.kiro/sessions/cli when it exists: child sessions and the parent tool result."""
    out = {}
    if not SESSION_ROOT.exists():
        return out
    children = []
    for meta in sorted(SESSION_ROOT.glob("*.json")):
        try:
            d = json.loads(meta.read_text())
        except ValueError:
            continue
        if d.get("parent_session_id") == parent:
            children.append({k: d.get(k) for k in ("session_id", "created_at", "updated_at", "session_created_reason")})
    if children:
        out["child_sessions"] = children
    transcript = SESSION_ROOT / f"{parent}.jsonl"
    if transcript.exists():
        for line in transcript.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("kind") != "ToolResults":
                continue
            for c in row.get("data", {}).get("content", []):
                r = c.get("data", {}) if c.get("kind") == "toolResult" else {}
                if r.get("toolUseId") == tool_call_id:
                    out["transcript"] = {"file": transcript.name, "status": r.get("status"),
                                         "content": "".join(x.get("data", "") for x in r.get("content", []) if x.get("kind") == "text")[:4000]}
    return out


def bind_child(run_root, child_id):
    """Bind the crew/subagent tool_call whose task name is the logical task name to its completed update."""
    attempts = {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError):
                continue
            if ev.get("type") != "sessionUpdate":
                continue
            data = ev.get("data") or {}; up = data.get("update") or {}
            kind, call_id = up.get("sessionUpdate"), up.get("toolCallId")
            if kind == "tool_call":
                tool = ((up.get("_meta") or {}).get("kiro") or {}).get("toolName")
                if tool in CHILD_TOOLS and child_id in _names(up.get("rawInput") or {}):
                    attempts[call_id] = {"run": events.parent.name, "session_id": data.get("sessionId"), "child_api": tool,
                                         "tool_call": {"id": call_id, "title": up.get("title"), "input": _redacted(up.get("rawInput") or {})}}
            elif kind == "tool_call_update" and call_id in attempts and up.get("status"):
                text = "".join(i.get("Text", "") for i in (up.get("rawOutput") or {}).get("items", []) if isinstance(i, dict))
                attempts[call_id]["tool_call_update"] = {"status": up.get("status"), "output": text[:4000]}
    completed = [a for a in attempts.values() if a.get("tool_call_update", {}).get("status") == "completed"]
    if not completed:
        raise LookupError(f"no completed subagent child with task name {child_id!r} in {run_root}")
    a = completed[-1]
    return {"child_id": child_id, "status": "completed", **a, **_session_store(a["session_id"], a["tool_call"]["id"])}


SPEC = HostSpec(
    name="kiro", install_flag="--kiro", skill_root=".kiro/skills", invocation="/gsd-path",
    child_api="invoke_sub_agent", guard_tier="git-only", command=command, parse_events=parse_events,
    child_name_key="task",
    bind_child=bind_child, verified_live=True,
    notes="/usr/local/bin/kiro is the Kiro IDE launcher; the agent is ~/.local/bin/kiro-cli. stream-json needs "
          "--agent-engine v2. The v2 stream names the child tool 'subagent' (AgentCrew), not 'invoke_sub_agent'; "
          "bind_child accepts both and reports the observed name. The stream interleaves child-session events, so "
          "parse_events keys session_id and usage on the runFinished session.",
)
