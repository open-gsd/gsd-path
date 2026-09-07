"""Antigravity CLI (``agy``) headless runner (verified live 2026-09-07, agy 1.1.27).

Live observations (probe: one ``invoke_subagent`` child with Role ``build_probe``):

- The spawn's ACTIVE step is ``step_type: tool`` with ``tool_info.parameters.Subagents[]``
  (``Prompt``/``Role``/``TypeName``); its DONE step is ``step_type: subagent`` and carries
  ``subagent_info.subagents[]`` with ``role``, ``conversation_id`` and a ``log_uri``
  (``file://.../.gemini/antigravity-cli/brain/<child>/.system_generated/logs/transcript.jsonl``).
- Completion reaches the parent as a ``system_message`` step without content; the proof used
  here is the ``manage_subagents`` (``Action: list``) tool output, a text line followed by a
  JSON list whose entries carry ``conversationId`` and ``state`` (``idle`` once finished),
  and the child's own transcript whose last record is ``status: DONE``.
- ``result`` nests ``conversation_id``, ``response`` and ``usage`` under ``result``.


Resume: ``--conversation <id>`` replayed the probe conversation headlessly with the same
conversation_id and answered from its history.

Documentation sources (2026-09-06): https://antigravity.google/docs/cli/headless/,
.../cli/commands/resume, .../cli/conversations/, .../cli/subagents/ (subagent state names
differ between pages), and google-antigravity/antigravity-cli issue #7.
"""

import json
from pathlib import Path

from tests.hosts import HostSpec

DONE_STATES = {"done", "idle", "completed"}


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


def _as_dict(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return {}
    return value if isinstance(value, dict) else {}


def parse_events(lines):
    session = final = usage = None
    for ev in _events(lines):
        res = _as_dict(ev.get("result"))
        session = ev.get("conversation_id") or res.get("conversation_id") or _as_dict(ev.get("step_update")).get("conversation_id") or session
        if ev.get("event") == "result":
            final, usage = res.get("response"), res.get("usage")
    return {"session_id": session, "final_message": final, "usage": usage}


def _listing(output):
    """``manage_subagents`` output: a text line, then a JSON list of ``{role, conversationId, state, ...}``."""
    text = str(output or "")
    start = text.find("[")
    try:
        items = json.loads(text[start:]) if start >= 0 else []
    except ValueError:
        items = []
    return [i for i in items if isinstance(i, dict)]


def _transcript_done(log_uri):
    """The child's own JSONL transcript when its last record is DONE; None otherwise."""
    uri = str(log_uri or "")
    path = Path(uri[len("file://"):] if uri.startswith("file://") else uri)
    if not path.is_file():
        return None
    steps = list(_events(path.read_text().splitlines()))
    last = steps[-1] if steps else {}
    if last.get("status") != "DONE":
        return None
    return {"path": str(path), "steps": len(steps), "last_type": last.get("type"), "final_content": str(last.get("content", ""))[:4000]}


def bind_child(run_root, child_id):
    """Bind the ``invoke_subagent`` child whose ``role`` is the logical task name to its completion.

    Spawn evidence: a DONE step with ``tool_name`` ``invoke_subagent`` whose ``subagent_info.subagents``
    entry has ``role == child_id`` and a ``conversation_id``. Completion evidence: a later DONE
    ``manage_subagents`` listing that shows that conversation in a ``DONE_STATES`` state, or the child's
    transcript (``log_uri``) ending in a DONE record. Anything less raises ``LookupError``.
    """
    spawns, listings = {}, {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            step = _as_dict(ev.get("step_update")) if isinstance(ev, dict) else {}
            if step.get("state") != "DONE":
                continue
            if step.get("tool_name") == "invoke_subagent":
                for sub in _as_dict(step.get("subagent_info")).get("subagents") or []:
                    if isinstance(sub, dict) and sub.get("role") == child_id and isinstance(sub.get("conversation_id"), str) and sub["conversation_id"].strip():
                        spawns[sub["conversation_id"]] = {"run": events.parent.name, "step_index": step.get("step_index"),
                                                          "subagent": {k: v for k, v in sub.items() if k != "initial_prompt"}}
            elif step.get("tool_name") == "manage_subagents":
                for item in _listing(_as_dict(step.get("tool_info")).get("output")):
                    cid = item.get("conversationId")
                    if cid in spawns and str(item.get("state", "")).lower() in DONE_STATES:
                        listings[cid] = {"run": events.parent.name, "step_index": step.get("step_index"), "entry": item}
    if not spawns:
        raise LookupError(f"no DONE invoke_subagent step with role {child_id!r} in {run_root}")
    for cid in reversed(list(spawns)):
        transcript = _transcript_done(spawns[cid]["subagent"].get("log_uri"))
        if transcript or cid in listings:
            return {"child_id": child_id, "status": "completed", "child_api": "invoke_subagent", "child_conversation_id": cid,
                    "spawn": spawns[cid], "listing": listings.get(cid), "transcript": transcript}
    raise LookupError(f"invoke_subagent for {child_id!r} spawned {sorted(spawns)} but no manage_subagents listing shows a "
                      f"{sorted(DONE_STATES)} state and no child transcript ends DONE; wait for the child before finishing")


SPEC = HostSpec(
    name="antigravity", install_flag="--antigravity", skill_root=".agents/skills", invocation="/gsd-path",
    child_api="invoke_subagent", guard_tier="git-only", command=command, parse_events=parse_events,
    child_name_key="role",
    bind_child=bind_child, prompt_on_stdin=False, verified_live=True,
    notes="Verified live (agy 1.1.27, 2026-09-07); see the module docstring. Not verified: the installed /gsd-path "
          "skill end to end, a multi-kilobyte prompt in argv, and whether --dangerously-skip-permissions covers every "
          "tool a milestone run needs.",
)
