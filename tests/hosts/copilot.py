"""GitHub Copilot CLI headless runner (verified live 2026-09-07, copilot 1.0.83).

The shapes below come from the official docs, the CLI changelog, and issue-tracker
samples, and a live one-child probe confirmed them (see ``SPEC.notes``):

- Programmatic reference (``-p PROMPT``, ``--allow-all``/``--yolo``, ``--no-ask-user``,
  ``--allow-all-tools``, ``--model``, ``COPILOT_HOME``):
  https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-programmatic-reference
- Session resume (``--resume``, ``--continue``, ``-p`` programmatic sessions):
  https://docs.github.com/en/copilot/how-tos/use-copilot-agents/use-copilot-cli
- Configuration directory (``~/.copilot/session-state/<session-id>/events.jsonl``,
  ``logs/process-{timestamp}-{pid}.log``, ``COPILOT_HOME`` override):
  https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-config-dir-reference
- Session data concept (every session persisted under ``session-state/``):
  https://docs.github.com/en/copilot/concepts/agents/copilot-cli/chronicle
- Event envelope and payloads (``id``/``timestamp``/``parentId``/``agentId``/``type``/``data``;
  ``tool.execution_start`` = ``toolCallId``/``toolName``/``arguments``;
  ``tool.execution_complete`` = ``toolCallId``/``success``/``result.content``/``error``):
  https://docs.github.com/en/copilot/how-tos/copilot-sdk/use-copilot-sdk/streaming-events
- Sub-agent lifecycle (``subagent.started``/``completed``/``failed`` carry ``toolCallId``
  and ``agentName``; the envelope ``agentId`` marks sub-agent-originated events):
  https://docs.github.com/en/copilot/how-tos/copilot-sdk/features/custom-agents
- Changelog: ``--output-format json`` "emit JSONL in prompt mode" (0.0.422),
  ``--resume=<id>`` / ``-r`` and ``--session-id=<id>`` (1.0.51), ``task(agent_type=...)``
  subagents (1.0.49), task sub-agent ids derived from their name (1.0.6), prompt piped
  over stdin (1.0.78): https://github.com/github/copilot-cli/blob/main/changelog.md
- Samples: ``events.jsonl`` ``tool.execution_start`` with ``toolName: "task"`` and
  ``subagent.started`` (https://github.com/github/copilot-cli/issues/4462); the stdout
  JSONL terminal ``result`` event with ``usage`` (https://github.com/github/copilot-cli/issues/4107);
  main and sub-agent events interleave in one ``events.jsonl``
  (https://github.com/github/copilot-cli/issues/2543).

Children are ``task`` tool calls (dispatch contract: ``platforms/copilot/dispatch.md``).
Completion is the ``tool.execution_complete`` (``success`` true) and/or
``subagent.completed`` event sharing the launching ``toolCallId``.
"""

import hashlib
import json
import os
from pathlib import Path

from tests.hosts import HostSpec

TASK_NAME_KEYS = ("description", "name")  # live: the task call sets both to the task name
SUBAGENT_FIELDS = ("agentName", "model", "durationMs", "totalTokens", "totalToolCalls", "error")


def command(prompt_path, resume=None):
    args = ["copilot", "-p", Path(prompt_path).read_text(), "--allow-all", "--no-ask-user", "--output-format", "json"]
    if resume:
        args.append(f"--resume={resume}")
    return args


def _events(lines):
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def _session_id(ev):
    data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
    return ev.get("session_id") or ev.get("sessionId") or data.get("session_id") or data.get("sessionId")


def parse_events(lines):
    session = final = usage = None
    for ev in _events(lines):
        session = _session_id(ev) or session
        data = ev.get("data") if isinstance(ev.get("data"), dict) else {}
        if ev.get("type") == "assistant.message" and data.get("content") is not None:
            final = data["content"]
        elif ev.get("type") == "assistant.usage":
            usage = data
        elif ev.get("type") == "result" and isinstance(ev.get("usage"), dict):
            usage = ev["usage"]
    return {"session_id": session, "final_message": final, "usage": usage}


def session_home():
    return Path(os.environ.get("COPILOT_HOME") or Path.home() / ".copilot")


def transcript_for(session_id):
    path = session_home() / "session-state" / session_id / "events.jsonl"
    if not path.exists():
        raise LookupError(f"no Copilot session transcript at {path}")
    return path


def _sources(run_root):
    """Yield (source, event) from the recorded stdout streams and each run's session transcript."""
    for events in sorted(run_root.glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            if isinstance(ev, dict):
                yield events.parent.name, ev
    for run_json in sorted(run_root.glob("quick/run-*/run.json")):
        try:
            session = json.loads(run_json.read_text()).get("session_id")
        except ValueError:
            continue
        if not session:
            continue
        try:
            transcript = transcript_for(session)
        except LookupError:
            continue
        for ev in _events(transcript.read_text().splitlines()):
            yield f"session-state/{session}", ev


def bind_child(run_root, child_id):
    """Bind the ``task`` tool call named ``child_id`` to its completion events."""
    run_root = Path(run_root)
    attempts = {}
    for source, ev in _sources(run_root):
        kind, data = ev.get("type"), ev.get("data") if isinstance(ev.get("data"), dict) else {}
        call_id = data.get("toolCallId")
        if kind == "tool.execution_start" and data.get("toolName") == "task" and call_id:
            args = data.get("arguments") if isinstance(data.get("arguments"), dict) else {}
            key = next((k for k in TASK_NAME_KEYS if args.get(k) == child_id), None)
            if key:
                attempts[call_id] = {"source": source, "matched_argument": key, "agent_id": None, "tool_call": {
                    "toolCallId": call_id, "arguments": {k: v for k, v in args.items() if k != "prompt"},
                    "prompt_sha256": hashlib.sha256(str(args.get("prompt", "")).encode()).hexdigest()}}
        elif call_id in attempts:
            a = attempts[call_id]
            if kind == "tool.execution_complete":
                result = data.get("result") if isinstance(data.get("result"), dict) else {}
                a["tool_result"] = {"success": bool(data.get("success")), "content": str(result.get("content", data.get("error")))[:4000]}
            elif kind in ("subagent.started", "subagent.completed", "subagent.failed"):
                a[kind.split(".")[1]] = {k: data[k] for k in SUBAGENT_FIELDS if k in data}
                a["agent_id"] = ev.get("agentId")  # live: the child id rides on the subagent.* envelope
    if not attempts:
        raise LookupError(f"no task tool call whose {'/'.join(TASK_NAME_KEYS)} is {child_id!r} in {run_root} streams or session-state transcripts")
    completed = [a for a in attempts.values() if "failed" not in a and (a.get("tool_result", {}).get("success") or "completed" in a)]
    if not completed:
        raise LookupError(f"task call for {child_id!r} never completed: no successful tool.execution_complete or subagent.completed for {sorted(attempts)}")
    return {"child_id": child_id, "status": "completed", "child_api": "task", **completed[-1]}


SPEC = HostSpec(
    name="copilot", install_flag="--copilot", skill_root=".github/skills", invocation="/gsd-path",
    child_api="task", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=True,
    notes=(
        "Verified live (GitHub Copilot CLI 1.0.83, 2026-09-07): `copilot -p <text> --allow-all --no-ask-user "
        "--output-format json` prints {type,data,id,timestamp,parentId} envelopes (subagent.* events carry agentId "
        "on the envelope); the terminal `result` line carries sessionId and usage, and the final text is the last "
        "assistant.message content; `--resume=<sessionId>` resumes headlessly; a `task` call with name and "
        "description build_probe (mode sync) completed through subagent.completed and tool.execution_complete "
        "success=true, and list_agents reported it Idle afterwards. Not verified: the installed /gsd-path skill "
        "running end to end, whether --allow-all covers writes into linked worktrees outside the cwd (--add-dir), "
        "and argv length limits for a multi-kilobyte prompt."
    ),
)
