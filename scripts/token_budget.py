#!/usr/bin/env python3
"""Persist observed Codex output usage and block admission after exhaustion.

This is an admission gate, not an in-flight generation cap. Codex CLI does not
expose a hard output-token cap. Unobserved calls are not budget evidence.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from _common import atomic_write
    from loop_run import log_lock
except ModuleNotFoundError:  # pragma: no cover - package imports
    from scripts._common import atomic_write
    from scripts.loop_run import log_lock


SCHEMA = "gsd-path/token-budget/v1"


def positive(value):
    result = int(value)
    if result <= 0:
        raise argparse.ArgumentTypeError("budget must be positive")
    return result


def output_usage(path: Path) -> int:
    usages = []
    child_usage = None
    child = False
    starts = 0
    complete = False
    for line in path.read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        if "raw" in event:
            event = json.loads(event["raw"])
        if event.get("type") == "turn.completed":
            usages.append(event["usage"]["output_tokens"])
        payload = event.get("payload", {})
        if event.get("type") == "session_meta":
            source = payload.get("source", {})
            child = isinstance(source, dict) and "subagent" in source
        if event.get("type") == "event_msg":
            if payload.get("type") == "task_started":
                starts += 1
                complete = False
            elif payload.get("type") == "token_count" and payload.get("info"):
                child_usage = payload["info"]["total_token_usage"]["output_tokens"]
            elif payload.get("type") == "task_complete":
                complete = True
    if not usages and child and starts == 1 and complete and child_usage is not None:
        # Only a single native invocation has an unambiguous cumulative counter.
        usages = [child_usage]
    if not usages or any(type(value) is not int or value < 0 for value in usages):
        raise ValueError("complete supported output usage is unavailable; budget is unproven")
    return sum(usages)


def operate(args):
    ledger = args.ledger.absolute()
    if ledger.is_symlink():
        raise ValueError("ledger must be a real file")
    with log_lock({"log": str(ledger)}):
        if args.action == "configure":
            policy = {"schema": SCHEMA, "host": "codex-cli", "metric": "output_tokens",
                      "task_limit": args.task_limit, "session_limit": args.session_limit,
                      "authority": args.authority}
            if ledger.exists():
                data = json.loads(ledger.read_text())
                if any(data.get(key) != value for key, value in policy.items()):
                    raise ValueError("existing session policy differs; configuration cannot reset usage")
            else:
                data = {**policy, "observations": {}}
                atomic_write(ledger, json.dumps(data, indent=2) + "\n")
            return {"status": "configured", "hard_cap_supported": False}
        data = json.loads(ledger.read_text())
        if data.get("schema") != SCHEMA or data.get("host") != "codex-cli":
            raise ValueError("unsupported budget ledger")
        if args.action == "record":
            source = str(args.events.resolve())
            observation = {"task": args.task, "output_tokens": output_usage(args.events)}
            previous = data["observations"].get(source)
            if previous and (previous["task"] != args.task or
                             previous["output_tokens"] > observation["output_tokens"]):
                raise ValueError("observation cannot change task or reduce recorded usage")
            data["observations"][source] = observation
            atomic_write(ledger, json.dumps(data, indent=2) + "\n")
            return {"status": "recorded", **observation, "hard_cap_supported": False}
        observations = data["observations"].values()
        task_used = sum(row["output_tokens"] for row in observations if row["task"] == args.task)
        session_used = sum(row["output_tokens"] for row in observations)
        task_remaining = max(0, data["task_limit"] - task_used)
        session_remaining = max(0, data["session_limit"] - session_used)
        reason = "observed usage is within budget; unobserved and in-flight usage is unproven"
        blocked = not task_remaining or not session_remaining
        if blocked:
            reason = "observed output budget exhausted"
        if args.require_hard_cap:
            blocked = True
            reason = "hard generation cap unsupported by Codex CLI"
        return {"decision": "blocked" if blocked else "admit", "reason": reason,
                "task_output_tokens": task_used, "session_output_tokens": session_used,
                "task_remaining": task_remaining, "session_remaining": session_remaining,
                "hard_cap_supported": False, "enforcement": "observed-admission-only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    for name in ("configure", "record", "admit"):
        command = subparsers.add_parser(name)
        command.add_argument("--ledger", type=Path, required=True)
        if name == "configure":
            command.add_argument("--task-limit", type=positive, required=True)
            command.add_argument("--session-limit", type=positive, required=True)
            command.add_argument("--authority", required=True)
        else:
            command.add_argument("--task", required=True)
        if name == "record":
            command.add_argument("--events", type=Path, required=True)
        if name == "admit":
            command.add_argument("--require-hard-cap", action="store_true")
    try:
        result = operate(parser.parse_args(argv))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"decision": "blocked", "reason": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 1 if result.get("decision") == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
