"""Qwen Code headless runner (documentation-derived, NOT verified live; the CLI is not installed here).

Sources (read 2026-09-06):

- Headless mode, output formats, resume:
  https://qwenlm.github.io/qwen-code-docs/en/users/features/headless/
  (source: https://github.com/QwenLM/qwen-code/blob/main/docs/users/features/headless.md)
- ``agent`` tool arguments and completion behaviour:
  https://github.com/QwenLM/qwen-code/blob/main/docs/developers/tools/task.md
- Subagents, background completion notifications, ``list_agents``:
  https://qwenlm.github.io/qwen-code-docs/en/users/features/sub-agents/
- Background notification records carry a structured task status:
  https://github.com/QwenLM/qwen-code/blob/main/docs/design/task-notification-transcript-placement.md

Documented interface: ``qwen -p "<prompt>" --output-format stream-json`` prints one JSON
object per line: ``{"type":"system","subtype":"session_start","session_id":...}``,
``{"type":"assistant","message":{...},"parent_tool_use_id":...}`` and
``{"type":"result","subtype":"success","is_error":...,"result":...,"usage":...}``.
``--resume <sessionId> -p "..."`` resumes a project-scoped session; ``--yolo``
auto-approves tools. Children are ``agent`` tool calls with ``description``,
``prompt`` and ``subagent_type`` (``general-purpose`` is the documented default). A
foreground child (``run_in_background: false``) returns its result inline; a background
child reports through a completion notification and is listed by ``list_agents`` with a
``task_id`` and status.
"""

import hashlib
import json
import re
from pathlib import Path

from tests.hosts import HostSpec


def command(prompt_path, resume=None):
    args = ["qwen", "--yolo", "--output-format", "stream-json"]
    if resume:
        args += ["--resume", resume]
    return args + ["-p", Path(prompt_path).read_text()]


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


def _json_in(content):
    """First JSON value inside a tool_result content (a string or a list of text blocks)."""
    texts = [content] if isinstance(content, str) else [c.get("text", "") for c in content or [] if isinstance(c, dict)]
    for text in texts:
        try:
            return json.loads(text)
        except (TypeError, ValueError):
            continue
    return None


def _agent_rows(value):
    rows = value.get("agents") if isinstance(value, dict) else value
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def bind_child(run_root, child_id):
    """Bind the ``agent`` tool_use whose description is the logical task name to its completion.

    Foreground launch (``run_in_background`` false): a non-error tool_result for the same
    tool_use id. Background launch (documented default): a ``list_agents`` tool_result whose
    row for this child (matched by the launch ``task_id``, or by ``description`` only
    when no task id was recorded) reports status ``completed``. The background completion notification's
    stream-json shape is not documented, so it is not used as evidence.
    """
    attempts = {}
    list_results = []
    pending_lists = {}
    for events in sorted(Path(run_root).glob("quick/run-*/events.jsonl")):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError, TypeError):
                continue
            if ev.get("type") == "assistant" and not ev.get("parent_tool_use_id"):
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") != "tool_use":
                        continue
                    if c.get("name") == "agent" and c.get("input", {}).get("description") == child_id:
                        attempts[c["id"]] = {"run": events.parent.name, "tool_use": {
                            "id": c["id"], "input": {k: v for k, v in c["input"].items() if k != "prompt"},
                            "prompt_sha256": hashlib.sha256(c["input"].get("prompt", "").encode()).hexdigest()}}
                    elif c.get("name") == "list_agents":
                        pending_lists[c["id"]] = set(attempts)
            elif ev.get("type") == "user":
                for c in ev.get("message", {}).get("content", []):
                    if not isinstance(c, dict) or c.get("type") != "tool_result":
                        continue
                    if c.get("tool_use_id") in attempts:
                        a = attempts[c["tool_use_id"]]
                        a["tool_result"] = {"is_error": bool(c.get("is_error")), "content": str(c.get("content"))[:4000]}
                        m = re.search(r'task_id\W+([A-Za-z0-9_.:-]+)', str(c.get("content")))
                        if m:
                            a["task_id"] = m.group(1)
                    elif c.get("tool_use_id") in pending_lists:
                        list_results.append({"attempts": pending_lists[c["tool_use_id"]], "rows": _agent_rows(_json_in(c.get("content")))})
    completed = []
    for call_id, a in attempts.items():
        if a.get("tool_result", {}).get("is_error"):
            continue
        if a["tool_use"]["input"].get("run_in_background") is False:
            if a.get("tool_result"):
                completed.append(a)
            continue
        match_by = "task_id" if a.get("task_id") else "description"
        match_value = a.get("task_id") or child_id
        states = [row for lr in list_results if call_id in lr["attempts"] for row in lr["rows"]
                  if row.get(match_by) == match_value]
        if any(row.get("status") == "completed" for row in states):
            completed.append({**a, "list_agents_states": states, "completion_match": match_by})
    if not completed:
        if attempts:
            raise LookupError(f"agent child {child_id!r} in {run_root} has no inline result and no list_agents row with status completed; "
                              "ask the orchestrator to call list_agents after the child returns")
        raise LookupError(f"no agent child with description {child_id!r} in {run_root}")
    return {"child_id": child_id, "status": "completed", "child_api": "agent", **completed[-1]}


SPEC = HostSpec(
    name="qwen", install_flag="--qwen", skill_root=".qwen/skills", invocation="/gsd-path",  # slash-command form documented for Gemini-style CLIs; unverified live
    child_api="agent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, prompt_on_stdin=False, verified_live=False,
    notes=(
        "Documentation-derived; Qwen Code is not installed on the authoring machine, so nothing here was run live. "
        "Confirm on a machine with the CLI: "
        "(1) `-p <text>` with stdin closed enters headless mode and keeps the whole multi-line prompt "
        "(the docs also show `echo prompt | qwen`; switch to prompt_on_stdin=True if argv is rejected); "
        "(2) `--resume <id> -p ...` resumes non-interactively when the id is given; "
        "(3) stream-json emits `tool_use` blocks in assistant messages and `tool_result` blocks in user messages "
        "with `tool_use_id`/`is_error` (only `parent_tool_use_id` and bounded `tool_result.content` are documented); "
        "(4) the stream-json shape of a background completion notification (undocumented; bind_child ignores it); "
        "(5) the `list_agents` result: only `task_id`, a status, and `resume_blocked_reason` are documented, so the "
        "`agents` list wrapper, the `description` key and the literal status `completed` are assumptions; "
        "(6) whether the launch tool_result of a background agent quotes its task_id; "
        "(7) `--yolo` loads project skills and hooks (no documented flag keeps operator config out without also "
        "disabling skills, which `--safe-mode` does)."
    ),
)
