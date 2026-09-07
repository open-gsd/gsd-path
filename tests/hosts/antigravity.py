"""Antigravity CLI (``agy``) headless runner, documentation-derived (NOT verified live).

Sources read on 2026-09-06:

- https://antigravity.google/docs/cli/headless/ -- ``-p``/``--print``/``--prompt`` runs one
  prompt and exits; the prompt is an argv value (stdin is only read with
  ``--input-format stream-json``); ``--output-format stream-json`` emits one JSON object per
  line: ``{"event":"init","conversation_id":...,"init":{...}}``, then
  ``{"event":"step_update","step_update":{"conversation_id","step_index","state":
  "ACTIVE|DONE","step_type":"user_input|agent_response|tool|checkpoint","tool_name",
  "text_delta","duration_seconds","usage","tool_info":{"name","parameters","output",...},
  "subagent_info"}}``, then ``{"event":"result","conversation_id","status":"SUCCESS|ERROR|
  CANCELED|INTERRUPTED|INVALID|WAITING|RUNNING","response","usage":{"input_tokens",
  "output_tokens","thinking_tokens","cache_read_tokens","total_tokens"}}``;
  ``--dangerously-skip-permissions`` auto-approves tool calls.
- https://antigravity.google/docs/cli/commands/resume and
  https://antigravity.google/docs/cli/conversations/ -- ``--conversation <id>`` resumes a
  conversation by id; ``-c``/``--continue`` resumes the most recent one for the workspace.
- https://antigravity.google/docs/cli/subagents/ and https://antigravity.google/docs/subagents
  -- the parent calls ``invoke_subagent`` to spawn a concurrent child session; the docs name
  subagent states (``Running``/``Idle``/``Killed`` on one page, ``running``/``done``/
  ``killed``/``error`` on the other) and ``send_message`` by conversation id, and say
  transcripts stay readable as JSONL logs, but publish neither the tool schema nor how a
  child's completion is delivered to the parent.
- https://github.com/google-antigravity/antigravity-cli/issues/7 (open) reports that plain
  ``--print`` text output never surfaces the conversation id; the structured formats above
  document one.

The ``invoke_subagent`` argument names used here (``TypeName``, ``Workspace``, ``Role``) come
from ``platforms/shared-agents/dispatch.md``, not from the public docs.
"""

import json
from pathlib import Path

from tests.hosts import HostSpec

DONE_STATES = {"done", "idle", "completed"}
ID_KEYS = ("conversation_id", "subagent_id", "agent_id", "id")


def command(prompt_path, resume=None):
    """``agy -p <prompt> --output-format stream-json``; the prompt text rides in argv."""
    args = ["agy", "-p", Path(prompt_path).read_text(), "--output-format", "stream-json", "--dangerously-skip-permissions"]
    if resume:
        args += ["--conversation", resume]
    return args


def _events(lines):
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if isinstance(ev, dict):
            yield ev


def parse_events(lines):
    session = final = usage = None
    for ev in _events(lines):
        session = ev.get("conversation_id") or ev.get("step_update", {}).get("conversation_id") or session
        if ev.get("event") == "result":
            final, usage = ev.get("response"), ev.get("usage")
    return {"session_id": session, "final_message": final, "usage": usage}


def _as_dict(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def _first(mapping, keys):
    return next((mapping[k] for k in keys if mapping.get(k)), None)


def bind_child(run_root, child_id):
    """Bind the ``invoke_subagent`` step whose ``Role`` is the logical task name to a completion.

    Spawn evidence: a DONE ``tool`` step whose ``tool_info.name`` is ``invoke_subagent`` and
    whose ``parameters.Role`` equals ``child_id``; the child id is taken from the tool output.
    Completion evidence: a later ``subagent_info`` for that child id whose status/state is in
    ``DONE_STATES``. The docs do not say how completion reaches the parent, so anything
    less raises ``LookupError`` instead of assuming the child finished.
    """
    spawns, completions = {}, {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            step = ev.get("step_update") if isinstance(ev, dict) else None
            if not isinstance(step, dict):
                continue
            info = _as_dict(step.get("tool_info"))
            if step.get("step_type") == "tool" and step.get("state") == "DONE" and info.get("name") == "invoke_subagent":
                params = _as_dict(info.get("parameters"))
                if params.get("Role") == child_id:
                    output = info.get("output")
                    decoded = output
                    if isinstance(output, str):
                        try:
                            decoded = json.loads(output)
                        except ValueError:
                            pass
                    cid = _first(decoded, ID_KEYS) if isinstance(decoded, dict) else decoded
                    if not isinstance(cid, str) or not cid.strip():
                        continue
                    spawns[cid] = {"run": events.parent.name, "step_index": step.get("step_index"),
                                   "parameters": {k: v for k, v in params.items() if k not in ("prompt", "message")},
                                   "output": str(output)[:4000]}
            sub = _as_dict(step.get("subagent_info"))
            cid = _first(sub, ID_KEYS)
            state = str(sub.get("status") or sub.get("state") or "").lower()
            if isinstance(cid, str) and cid.strip() and cid in spawns and state in DONE_STATES:
                completions[cid] = {"run": events.parent.name, "step_index": step.get("step_index"), "subagent_info": sub}
    if not spawns:
        raise LookupError(f"no DONE invoke_subagent step with Role {child_id!r} in {run_root}")
    if not completions:
        raise LookupError(f"invoke_subagent for {child_id!r} spawned {sorted(map(str, spawns))} but no subagent_info reports a "
                          f"{sorted(DONE_STATES)} state; completion delivery is undocumented, confirm it on a live CLI")
    cid = list(completions)[-1]
    return {"child_id": child_id, "status": "completed", "child_api": "invoke_subagent", "child_conversation_id": cid,
            "spawn": spawns[cid], "completion": completions[cid]}


SPEC = HostSpec(
    name="antigravity", install_flag="--antigravity", skill_root=".agents/skills", invocation="/gsd-path",
    child_api="invoke_subagent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=False,
    notes=(
        "Documentation-derived; never run against a live agy. Confirm on a machine with the CLI: "
        "(1) `agy -p` accepts a multi-kilobyte prompt in argv and the stream-json event/field names above; "
        "(2) `--conversation <id>` resumes headlessly and keeps the same conversation_id; "
        "(3) the invoke_subagent step_update shape: tool_info.parameters keys (TypeName/Workspace/Role) and "
        "which field of tool_info.output carries the child conversation id; "
        "(4) how a child's completion reaches the parent stream (subagent_info status values; the docs "
        "disagree between Idle and done) and whether an /agents-style listing tool exists to call after the "
        "coder reports; (5) the on-disk JSONL transcript path (the docs mention JSONL logs, not a path) if "
        "stream evidence proves insufficient; (6) that --dangerously-skip-permissions covers subagent spawns."
    ),
)
