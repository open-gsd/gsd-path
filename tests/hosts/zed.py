"""Zed agent host module (verified live 2026-09-07 through the source-built eval-cli).

Zed itself has no headless mode: the ``zed`` CLI exposes no agent or prompt flag, and Zed's
agent is an Agent Client Protocol client, not a server (zed-industries/zed discussion
59146). The developer crate ``crates/eval_cli`` (``cargo build --release -p eval_cli``;
needs cmake and, on macOS 26, ``xcodebuild -downloadComponent MetalToolchain``) runs the
same agent loop without a GUI: prompt on stdin, ``result.json``/``thread.json``/``thread.md``
to ``--output-dir``, ``[eval-cli] result: <json>`` and ``[eval-cli] subagent spawned: <id>``
on stderr, stdout empty, no resume flag. At 4a217d5 its generated agent-settings JSON has a
stray quote after the closing brace ("trailing characters at line 14"); the local build
carries a one-character fix. The DbThread layout is documented on ``bind_child`` and in
``tests/test_host_zed.py``.

Sources: crates/eval_cli/README.md and src/main.rs, crates/agent/src/tools/spawn_agent_tool.rs
(input ``{"label", "message", "session_id"?}``, success output ``{"session_id", "output"}``),
crates/agent/src/db.rs (DbThread), https://zed.dev/docs/ai/skills (``.agents/skills``).
"""

import hashlib
import json
import os
import shutil
from pathlib import Path

from tests.hosts import HostSpec

RESULT_PREFIX = "[eval-cli] result: "
SUBAGENT_PREFIX = "[eval-cli] subagent spawned: "
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def command(prompt_path, resume=None):
    """``eval-cli --workdir . --output-dir <run dir>`` with the prompt on stdin.

    The binary is ``ZED_EVAL_CLI`` or ``eval-cli`` on PATH or the source build under
    ``~/github/zed-industries/zed``; ``ZED_EVAL_MODEL`` (``provider/model``) is passed as
    ``--model`` when set, otherwise eval-cli's own default applies. ``result.json`` and
    ``thread.json`` land beside the prompt, in the run directory. eval-cli has no resume
    flag, so a resume request starts a new session in the same workdir and relies on the
    pipeline's persisted ``.project`` state; the resumed thread is a new ``thread.json``.
    """
    exe = os.environ.get("ZED_EVAL_CLI") or shutil.which("eval-cli") or str(Path.home() / "github/zed-industries/zed/target/release/eval-cli")
    args = [exe, "--workdir", ".", "--output-dir", str(Path(prompt_path).resolve().parent)]
    model = os.environ.get("ZED_EVAL_MODEL")
    if model:
        args += ["--model", model]
    return args


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

    Reads ``quick/run-*/thread.json`` (eval-cli's DbThread dump): tool uses are
    ``{"id", "name", "input": {"type": "json", "value": {...}}}`` and ``tool_results`` entries
    carry ``tool_use_id``, ``is_error``, ``content: [{"Text": ...}]`` and the structured
    ``output`` (``{"session_id", "output"}`` on success).
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
        uses, results = {}, {}
        for d in _walk(thread):
            inp = d.get("input") if isinstance(d.get("input"), dict) else {}
            inp = inp.get("value") if inp.get("type") == "json" else inp
            if d.get("name") == "spawn_agent" and isinstance(inp, dict) and inp.get("label") == child_id and d.get("id"):
                uses[d["id"]] = {"run": path.parent.name, "tool_use": {
                    "id": d["id"], "input": {k: v for k, v in inp.items() if k != "message"},
                    "prompt_sha256": hashlib.sha256(str(inp.get("message", "")).encode()).hexdigest()}}
            elif d.get("tool_use_id") and isinstance(d.get("content"), list):
                output = d.get("output") if isinstance(d.get("output"), dict) else {}
                results[d["tool_use_id"]] = {
                    "is_error": bool(d.get("is_error")),
                    "completed": not d.get("is_error") and "output" in output and "error" not in output,
                    "session_id": output.get("session_id"),
                    "content": "".join(c.get("Text", "") for c in d["content"] if isinstance(c, dict))[:4000]}
        for call_id, use in uses.items():
            if call_id in results:
                use["tool_result"] = results[call_id]
        completed += [u for u in uses.values() if u.get("tool_result", {}).get("completed")]
    if not completed:
        raise LookupError(f"no completed spawn_agent child with label {child_id!r} in {run_root}")
    a = completed[-1]
    return {"child_id": child_id, "status": "completed", "child_api": "spawn_agent", "child_session_id": a["tool_result"]["session_id"], **a}


SPEC = HostSpec(
    name="zed", install_flag="--zed", skill_root=".agents/skills", invocation="/gsd-path",
    child_api="spawn_agent", guard_tier="git-only", command=command, parse_events=parse_events,
    child_name_key="label",
    bind_child=bind_child, verified_live=True,
    notes=(
        "Verified live 2026-09-07 (source-built eval-cli, model via OpenRouter): a spawn_agent child labelled "
        "build_probe completed and its session_id and output landed in thread.json. Not verified: the installed "
        "/gsd-path skill end to end under eval-cli, resuming a child session_id, and continuing an owner-gated "
        "pipeline across separate eval-cli sessions (eval-cli cannot resume). Guard tier is git-only: Zed has no "
        "hook API."
    ),
)
