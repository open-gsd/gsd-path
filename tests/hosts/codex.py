"""Codex CLI headless runner (verified live 2026-09-06, codex-cli 0.153.4).

`codex exec --json -` prints one JSON event per line and reads the prompt on stdin.
The `--json` stream shows only ``wait`` collaboration calls; the ``spawn_agent`` call,
its output and ``list_agents`` status rows are in the session rollout transcript, so
``bind_child`` reads that transcript (found by thread id under the Codex sessions
directories).
"""

import json
import os
from pathlib import Path

from tests.hosts import HostSpec

SESSION_ROOTS = (
    Path.home() / ".codex" / "sessions",
    Path.home() / "Library" / "Application Support" / "orca" / "codex-accounts",
)


def command(prompt_path, resume=None):
    model = os.environ.get("GSD_CODEX_MODEL", "gpt-6-astra")
    reasoning = os.environ.get("GSD_CODEX_REASONING", "high")
    args = ["codex", "exec", "--sandbox", "danger-full-access"]
    if resume:
        args += ["resume", resume]
    args += ["--ignore-user-config", "--model", model, "-c", f'model_reasoning_effort="{reasoning}"', "--json", "-"]
    return args


def parse_events(lines):
    thread = final = usage = None
    for line in lines:
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "thread.started":
            thread = ev.get("thread_id")
        item = ev.get("item", {})
        if item.get("type") == "agent_message":
            final = item.get("text")
        if ev.get("type") == "turn.completed":
            usage = ev.get("usage")
    return {"session_id": thread, "final_message": final, "usage": usage}


def transcript_for(thread_id):
    for root in SESSION_ROOTS:
        if root.exists():
            for path in sorted(root.rglob(f"rollout-*{thread_id}*.jsonl")):
                return path
    raise LookupError(f"no Codex rollout transcript for thread {thread_id}")


def bind_child(run_root, child_id):
    run_root = Path(run_root)
    threads = set()
    for events in run_root.glob("quick/run-*/events.jsonl"):
        for line in events.read_text().splitlines():
            try:
                ev = json.loads(json.loads(line)["raw"])
            except (ValueError, KeyError):
                continue
            if ev.get("type") == "thread.started" and ev.get("thread_id"):
                threads.add(ev["thread_id"])
    if len(threads) != 1:
        raise LookupError(f"expected one Codex thread in {run_root}, found {sorted(threads)}")
    thread = threads.pop()
    transcript = transcript_for(thread)
    attempts = {}
    list_calls = set()
    for line in transcript.read_text().splitlines():
        try:
            p = json.loads(line).get("payload", {})
        except ValueError:
            continue
        call_id = p.get("call_id")
        if p.get("type") == "function_call":
            if p.get("name") == "list_agents":
                list_calls.add(call_id)
            elif p.get("name") == "spawn_agent" and call_id:
                try:
                    args = json.loads(p.get("arguments", ""))
                except ValueError:
                    continue
                if not isinstance(args, dict) or args.get("task_name") != child_id:
                    continue
                args.pop("message", None)
                attempts[call_id] = {
                    "spawn_call": {"call_id": call_id, "namespace": p.get("namespace"), "arguments": args},
                    "list_agents_states": [],
                }
        elif p.get("type") == "function_call_output":
            try:
                output = json.loads(p.get("output", ""))
            except (ValueError, TypeError):
                continue
            if not isinstance(output, dict):
                continue
            if call_id in attempts:
                name = output.get("task_name")
                if isinstance(name, str) and name.endswith("/" + child_id):
                    attempts[call_id].update(spawn_output=p["output"], agent_name=name)
            elif call_id in list_calls:
                for state in output.get("agents", []):
                    for attempt in attempts.values():
                        if attempt.get("agent_name") and state.get("agent_name") == attempt["agent_name"]:
                            attempt["list_agents_states"].append(state)
    completed = []
    for attempt in attempts.values():
        for state in attempt["list_agents_states"]:
            status = state.get("agent_status")
            if status == "completed" or (isinstance(status, dict) and "completed" in status):
                completed.append(attempt)
                break
    if not completed:
        raise LookupError(f"transcript {transcript.name} has no completed spawn_agent attempt for {child_id}; ask the orchestrator to call list_agents after the child returns")
    return {"child_id": child_id, "status": "completed", "child_api": "collaboration.spawn_agent", "thread": thread,
            "transcript": transcript.name, **completed[-1]}


SPEC = HostSpec(
    name="codex", install_flag="--codex", skill_root=".agents/skills", invocation="$gsd-path",
    child_api="collaboration.spawn_agent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, verified_live=True,
    notes="--ignore-user-config keeps operator MCP servers and hooks out of the run; it also means no project hook loads (git-only tier, so not required).",
)
