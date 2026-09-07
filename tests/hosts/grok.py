"""Grok CLI headless runner (verified live 2026-09-06, grok 1.0.13 stable).

`grok --prompt-file F --output-format streaming-json --always-approve` prints one
ACP session update per line (``text``/``thought`` deltas, ``tool_call``,
``tool_call_update``, ``usage``, ``end``). Children are ``spawn_subagent`` tool
calls; the background child's completion is the ``tool_call_update`` of the
``get_command_or_subagent_output`` (or wait/monitor) call whose ``Result`` carries
the child's ``task_id`` with ``status: completed``.

Grok also keeps a session directory at ``~/.grok/sessions/<url-encoded cwd>/<id>/``
(``chat_history.jsonl``, ``events.jsonl``, ``resources_state.json``, ``summary.json``);
a subagent gets a sibling directory named by its ``subagent_id``. ``bind_child``
uses that directory only as extra evidence when it exists; the stream is sufficient.
"""

import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import quote

from tests.hosts import HostSpec

SESSION_ROOT = Path.home() / ".grok" / "sessions"
_SUBAGENT_ID = re.compile(r"subagent_id:\s*([0-9a-f-]{36})")


def command(prompt_path, resume=None):
    exe = shutil.which("grok") or str(Path.home() / ".grok" / "bin" / "grok")
    args = [exe, "--prompt-file", str(prompt_path), "--output-format", "streaming-json", "--always-approve", "--no-plan"]
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
    """Session id and usage come from the ``end`` event; the final message is the text
    streamed after the last tool event (background children stream their own text
    deltas into the parent stream while they run)."""
    session = usage = None
    text = []
    for ev in _events(lines):
        kind = ev.get("type")
        if kind == "text":
            text.append(str(ev.get("data", "")))
        elif kind in ("tool_call", "tool_call_update"):
            text = []
        elif kind == "end":
            session, usage = ev.get("sessionId") or session, ev.get("usage")
    return {"session_id": session, "final_message": "".join(text) or None, "usage": usage}


def _results(node):
    """Yield every task-status record (``task_id`` + ``status``) inside a tool output."""
    if isinstance(node, dict):
        if "task_id" in node and "status" in node:
            yield node
        for value in node.values():
            yield from _results(value)
    elif isinstance(node, list):
        for value in node:
            yield from _results(value)


def _output_text(update):
    out = update.get("rawOutput")
    if isinstance(out, dict) and isinstance(out.get("text"), str):
        return out["text"]
    return "".join(c.get("content", {}).get("text", "") for c in update.get("content", []) if isinstance(c, dict))


def session_dir(cwd, session_id):
    return SESSION_ROOT / quote(str(cwd), safe="") / session_id


def _transcript_evidence(cwd, session_id, subagent_id):
    parent = session_dir(cwd, session_id)
    if not session_id or not parent.is_dir():
        return None
    evidence = {"session_dir": str(parent), "child_session_dir": None, "reported_completions": []}
    child = parent.parent / subagent_id
    if child.is_dir():
        evidence["child_session_dir"] = str(child)
    state = parent / "resources_state.json"
    if state.is_file():
        try:
            evidence["reported_completions"] = json.loads(state.read_text())["state"]["grok_build.ReportedTaskCompletions"]["reported"]
        except (ValueError, KeyError, TypeError):
            pass
    return evidence


def bind_child(run_root, child_id):
    """Bind the ``spawn_subagent`` call whose ``description`` is the logical task name
    to the completion record of the ``subagent_id`` it returned."""
    run_root = Path(run_root)
    attempts, session = {}, None
    for events in sorted(run_root.glob("quick/run-*/events.jsonl")):
        by_call = {}
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            kind, call = ev.get("type"), ev.get("toolCallId")
            if kind == "tool_call" and ev.get("toolName") == "spawn_subagent":
                inp = ev.get("rawInput") or {}
                if inp.get("description") == child_id:
                    by_call[call] = attempts[call] = {"run": events.parent.name, "tool_call_id": call, "spawn_input": {
                        k: v for k, v in inp.items() if k != "prompt"},
                        "prompt_sha256": hashlib.sha256(str(inp.get("prompt", "")).encode()).hexdigest()}
            elif kind == "tool_call_update" and call in by_call and ev.get("status") == "completed":
                a = by_call[call]; text = _output_text(ev)
                m = _SUBAGENT_ID.search(text)
                a["spawn_output"] = text[:4000]
                if m:
                    a["subagent_id"] = m.group(1)
                elif not a["spawn_input"].get("background"):
                    a["foreground_completed"] = True
            elif kind == "tool_call_update" and ev.get("status") == "completed":
                for r in _results(ev.get("rawOutput")):
                    for a in by_call.values():
                        if a.get("subagent_id") == r.get("task_id"):
                            a["completion"] = {"tool_call_id": call, **{k: r.get(k) for k in ("task_id", "command", "status", "exit_code", "started", "ended", "duration_secs")},
                                               "output": str(r.get("output", ""))[:4000]}
            elif kind == "end":
                session = ev.get("sessionId") or session
    if not attempts:
        raise LookupError(f"no spawn_subagent call with description {child_id!r} in {run_root}")
    completed = [a for a in attempts.values() if a.get("completion", {}).get("status") == "completed" or a.get("foreground_completed")]
    if not completed:
        raise LookupError(f"spawn_subagent {child_id!r} never reported completed in {run_root}; the orchestrator must wait for the child (get_command_or_subagent_output) after it returns")
    a = completed[-1]
    cwd = a["spawn_input"].get("cwd") or run_root / "quick" / "repo"
    return {"child_id": child_id, "status": "completed", "child_api": "spawn_subagent", "session_id": session,
            "transcript": _transcript_evidence(cwd, session, a.get("subagent_id", "")), **a}


SPEC = HostSpec(
    name="grok", install_flag="--grok", skill_root=".grok/skills", invocation="/gsd-path",
    child_api="spawn_subagent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=True,
    notes="Verified live: --prompt-file, --output-format streaming-json, --resume <sessionId>, and a background "
          "spawn_subagent child (description build_probe) completing through get_command_or_subagent_output. "
          "Not verified: the installed /gsd-path skill running end to end; grok lists gsd-path among its slash "
          "commands and expands a leading /command unless --verbatim is passed, which is why --verbatim is omitted. "
          "The stream has no message boundaries, so final_message is the text after the last tool event. "
          "A foreground (background false) spawn is bound from its own completed tool_call_update; that form was "
          "not observed live. --always-approve replaces permission prompts; the git-only tier installs no grok hook.",
)
