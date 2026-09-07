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
    thread = threads.pop(); transcript = transcript_for(thread)
    spawn = spawn_out = None; call_id = None; statuses = []
    for line in transcript.read_text().splitlines():
        try:
            p = json.loads(line).get("payload", {})
        except ValueError:
            continue
        if p.get("type") == "function_call" and p.get("name") == "spawn_agent" and f'"task_name":"{child_id}"' in p.get("arguments", ""):
            args = json.loads(p["arguments"]); args.pop("message", None)  # the brief is encrypted in the transcript
            spawn = {"call_id": p.get("call_id"), "namespace": p.get("namespace"), "arguments": args}; call_id = p.get("call_id")
        elif p.get("type") == "function_call_output" and p.get("call_id") == call_id and spawn_out is None:
            spawn_out = p.get("output")
        elif p.get("type") == "function_call_output" and isinstance(p.get("output"), str) and "agent_status" in p["output"]:
            try:
                statuses += [ag for ag in json.loads(p["output"]).get("agents", []) if str(ag.get("agent_name", "")).endswith("/" + child_id)]
            except ValueError:
                pass
    done = lambda s: s.get("agent_status") == "completed" or (isinstance(s.get("agent_status"), dict) and "completed" in s["agent_status"])
    if spawn is None or spawn_out is None:
        raise LookupError(f"transcript {transcript.name} has no spawn_agent call/output for {child_id}")
    if not any(done(s) for s in statuses):
        raise LookupError(f"transcript never lists {child_id} as completed via list_agents; ask the orchestrator to call list_agents after the child returns")
    return {"child_id": child_id, "status": "completed", "child_api": "collaboration.spawn_agent", "thread": thread,
            "transcript": transcript.name, "spawn_call": spawn, "spawn_output": spawn_out, "list_agents_states": statuses}


SPEC = HostSpec(
    name="codex", install_flag="--codex", skill_root=".agents/skills", invocation="$gsd-path",
    child_api="collaboration.spawn_agent", guard_tier="git-only", command=command, parse_events=parse_events,
    bind_child=bind_child, verified_live=True,
    notes="--ignore-user-config keeps operator MCP servers and hooks out of the run; it also means no project hook loads (git-only tier, so not required).",
)
