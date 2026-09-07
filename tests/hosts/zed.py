"""Zed agent host module (documentation-derived, NOT verified live; Zed is not installed here).

What the official sources say (read 2026-09-06, zed-industries/zed main @ 1870e269):

- CLI reference https://zed.dev/docs/reference/cli : ``zed [OPTIONS] [PATHS]...`` with
  --wait/--new/--add/--reuse/--existing/--diff/--foreground/--user-data-dir/--version/
  --completions/--uninstall/--zed (+ --stable/--preview/--nightly on macOS). No flag runs
  the agent, sends a prompt, or exposes a headless/ACP mode.
- External agents https://zed.dev/docs/ai/external-agents : Zed is the Agent Client
  Protocol *client*; ``agent_servers`` launches other agents as ACP servers. Zed's own
  agent is not offered as an ACP server, so it cannot be driven over ACP from outside
  (ACP session/new, session/prompt, session/update shapes:
  https://agentclientprotocol.com/protocol/session-setup ,
  https://agentclientprotocol.com/protocol/prompt-turn ). Discussion
  https://github.com/zed-industries/zed/discussions/59146 (open) asks for exactly this
  and confirms the agent is "limited to use from within Zed".
- Agent panel https://zed.dev/docs/ai/agent-panel : threads live in Thread History;
  ``agent: open active thread as markdown`` is the only documented export.
- Tools https://zed.dev/docs/ai/tools : ``spawn_agent`` "Spawns a subagent with its own
  context window"; ``skill`` loads skills from ``<worktree>/.agents/skills`` or
  ``~/.agents/skills`` ( https://zed.dev/docs/ai/skills ), invoked as ``/<name>``.
- The only headless runner is the developer crate ``crates/eval_cli``
  ( https://github.com/zed-industries/zed/blob/main/crates/eval_cli/README.md ,
  https://github.com/zed-industries/zed/blob/main/crates/eval_cli/src/main.rs ): built
  with ``cargo build --release -p eval_cli``; ``eval-cli --workdir D --model P/M
  --instruction TEXT --timeout S --output-dir OUT`` (instruction from stdin when
  --instruction is omitted); writes ``result.json`` (status/error/duration_secs/model/
  input_tokens/output_tokens/cache_creation_input_tokens/cache_read_input_tokens/
  step_count/tool_call_count/tool_calls), ``thread.md`` and ``thread.json`` (the
  DbThread) to --output-dir; every log line, including ``[eval-cli] result: <json>``
  and ``[eval-cli] subagent spawned: <session_id>``, goes to stderr; stdout stays empty.
  Exit codes 0 finished / 1 error / 2 timeout / 3 interrupted. No resume flag.
- spawn_agent contract
  https://github.com/zed-industries/zed/blob/main/crates/agent/src/tools/spawn_agent_tool.rs :
  input ``{"label", "message", "session_id"?}``; success output serialises as
  ``{"session_id": ..., "output": <child final message>}``, error as
  ``{"session_id"?, "error"}``. The tool doc says the returned session_id can be reused
  for follow-ups, which contradicts platforms/shared-agents/dispatch.md ("Zed children
  are not resumable"); a live check must settle it.
- Persistence https://github.com/zed-industries/zed/blob/main/crates/agent/src/db.rs :
  DbThread {title, messages, cumulative_token_usage, subagent_context, ...};
  DbThreadMetadata carries ``parent_session_id`` for subagent threads. eval-cli's
  thread.json is the root DbThread only.

Consequences for this module: ``command`` raises NotImplementedError, ``parse_events``
returns None for what stdout never carries, and ``bind_child`` reads only a recorded
``thread.json`` under ``quick/run-*/``.
"""

import hashlib
import json
from pathlib import Path

from tests.hosts import HostSpec

RESULT_PREFIX = "[eval-cli] result: "
SUBAGENT_PREFIX = "[eval-cli] subagent spawned: "
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def command(prompt_path, resume=None):
    raise NotImplementedError(
        "Zed has no documented headless agent invocation: the `zed` CLI reference exposes no agent/prompt "
        "flag, and Zed's own agent is an ACP client, not an ACP server, so it cannot be driven over the "
        "Agent Client Protocol. Documented alternative: build the developer binary `cargo build --release "
        "-p eval_cli` from zed-industries/zed and run `eval-cli --workdir <repo> --model <provider/model> "
        "--output-dir <run-dir>` with the prompt on stdin; it logs to stderr only and has no resume flag."
        + (" A resume id was requested; eval-cli cannot resume." if resume else "")
    )


def _json_after(lines, start):
    """Parse the JSON object that starts on ``lines[start]`` (after the prefix) and may span lines."""
    text = lines[start][len(RESULT_PREFIX):]
    for extra in lines[start + 1:]:
        try:
            return json.loads(text)
        except ValueError:
            text += "\n" + extra
    try:
        return json.loads(text)
    except ValueError:
        return None


def parse_events(lines):
    """Read recorded lines. eval-cli stdout is empty, so all values stay None unless the
    caller passes its stderr/result lines; even then no session id or final message is printed."""
    usage = status = None; subagents = []
    lines = list(lines)
    for i, line in enumerate(lines):
        if line.startswith(RESULT_PREFIX):
            result = _json_after(lines, i)
            if isinstance(result, dict):
                status = result.get("status")
                found = {k: result[k] for k in USAGE_KEYS if k in result}
                usage = found or None
        elif line.startswith(SUBAGENT_PREFIX):
            subagents.append(line[len(SUBAGENT_PREFIX):].strip())
    return {"session_id": None, "final_message": None, "usage": usage, "status": status, "subagent_sessions": subagents}


def _walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


def bind_child(run_root, child_id):
    """Bind the spawn_agent call whose ``label`` is the logical task name to its non-error result.

    Reads ``quick/run-*/thread.json`` (eval-cli's DbThread dump). A completed child is a
    spawn_agent tool use whose result is not an error and whose content parses as the
    documented ``{"session_id", "output"}`` success payload.
    """
    threads = sorted(Path(run_root).glob("quick/run-*/thread.json"))
    if not threads:
        raise LookupError(f"no recorded thread.json under {run_root}/quick/run-*/ (eval-cli --output-dir)")
    completed = []
    for path in threads:
        try:
            thread = json.loads(path.read_text())
        except ValueError:
            continue
        uses = {}
        for d in _walk(thread):
            inp = d.get("input")
            if d.get("name") == "spawn_agent" and isinstance(inp, dict) and inp.get("label") == child_id and d.get("id"):
                uses[d["id"]] = {"run": path.parent.name, "tool_use": {
                    "id": d["id"], "input": {k: v for k, v in inp.items() if k != "message"},
                    "prompt_sha256": hashlib.sha256(str(inp.get("message", "")).encode()).hexdigest()}}
        for d in _walk(thread):
            if d.get("tool_use_id") in uses and "tool_use" in uses[d["tool_use_id"]]:
                content = d.get("content")
                try:
                    payload = json.loads(content) if isinstance(content, str) else content
                except ValueError:
                    payload = None
                ok = not d.get("is_error") and isinstance(payload, dict) and "output" in payload and "error" not in payload
                uses[d["tool_use_id"]]["tool_result"] = {"is_error": bool(d.get("is_error")), "completed": ok,
                                                         "session_id": (payload or {}).get("session_id") if isinstance(payload, dict) else None,
                                                         "content": str(content)[:4000]}
        completed += [u for u in uses.values() if u.get("tool_result", {}).get("completed")]
    if not completed:
        raise LookupError(f"no completed spawn_agent child with label {child_id!r} in {run_root}")
    a = completed[-1]
    return {"child_id": child_id, "status": "completed", "child_api": "spawn_agent", "child_session_id": a["tool_result"]["session_id"], **a}


SPEC = HostSpec(
    name="zed", install_flag="--zed", skill_root=".agents/skills", invocation="/gsd-path",
    child_api="spawn_agent", guard_tier="git-only", command=command, parse_events=parse_events,
    child_name_key="label",
    bind_child=bind_child, verified_live=False,
    notes=(
        "Documentation-derived; Zed is not installed on the authoring machine and nothing here was run. "
        "Confirm on a machine with Zed: (1) whether any shipped `zed` build accepts a prompt headlessly "
        "(none documented); (2) whether eval-cli built from source loads project skills from "
        ".agents/skills and honours /gsd-path; (3) the exact JSON key names in eval-cli thread.json for "
        "tool uses and tool results (bind_child matches by name/input.label/id/tool_use_id generically); "
        "(4) whether stdout is really empty and `[eval-cli] result:` is on stderr; (5) whether a "
        "spawn_agent session_id can be resumed (tool doc says yes, dispatch.md says no); (6) where the "
        "child's own thread and parent_session_id are persisted outside eval-cli's root thread.json; "
        "(7) the git-only guard tier: Zed has no hook API, so guard evidence must come from Git hooks."
    ),
)
