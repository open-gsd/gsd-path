#!/usr/bin/env python3
"""Deterministic gates for a GSD Path LOOP.md loop spec.

The loop skill (a model) reads the prose sections of a LOOP.md; this helper
reads only its fixed machine fields — exact `key: value` lines, one per
line, no nesting. `check` decides run/skip from status, cooldown,
skip_when, and period budgets; `verify` re-runs the spec's verifier
commands independently of any worker; `record` appends one JSON line to the
spec's log; `status` aggregates the log into counters. Relative paths
(spec `log:`, skip_when, verify commands) resolve against the caller's
working directory — invoke from the repository root.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence


class LoopError(RuntimeError):
    pass


MANDATORY_FIELDS = ("loop", "status", "trigger", "verify", "max_iterations", "wall_clock", "log")
OPTIONAL_FIELDS = ("cooldown", "skip_when", "period", "period_budget")
KNOWN_FIELDS = frozenset((*MANDATORY_FIELDS, *OPTIONAL_FIELDS))
REPEATABLE_FIELDS = frozenset({"verify"})
STATUSES = ("active", "paused", "done")
RESULTS = ("pass", "fail", "blocked", "skipped")
FIELD_LINE = re.compile(r"^(?P<key>[a-z_]+):(?P<rest>[ \t].*)?$")
TRAILING_COMMENT = re.compile(r"[ \t]*<!--.*?-->[ \t]*$")
DURATION = re.compile(r"^(?P<amount>\d+)(?P<unit>s|m|h|d)?$")
UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, None: 1}
OUTPUT_TAIL_LINES = 20


def parse_duration(raw: str, field: str) -> int:
    match = DURATION.fullmatch(raw.strip())
    if not match:
        raise LoopError(f"{field} must be a duration like 300s, 15m, 2h, or 1d")
    return int(match.group("amount")) * UNIT_SECONDS[match.group("unit")]


def parse_spec(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise LoopError(f"spec must be a real file: {path}")
    fields: dict[str, object] = {"verify": []}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        match = FIELD_LINE.match(line)
        if not match or match.group("key") not in KNOWN_FIELDS:
            continue
        key = match.group("key")
        rest = match.group("rest")
        value = TRAILING_COMMENT.sub("", rest).strip() if rest else ""
        if not value:
            raise LoopError(f"{path}:{number}: field {key} has no value")
        if key in REPEATABLE_FIELDS:
            fields[key].append(value)
        elif key in fields:
            raise LoopError(f"{path}:{number}: duplicate field {key}")
        else:
            fields[key] = value
    missing = [key for key in MANDATORY_FIELDS if not fields.get(key)]
    if missing:
        raise LoopError(f"{path}: missing mandatory fields: {', '.join(missing)}")
    if fields["status"] not in STATUSES:
        raise LoopError(f"{path}: status must be one of {', '.join(STATUSES)}")
    fields["max_iterations"] = parse_positive_int(fields["max_iterations"], "max_iterations")
    fields["wall_clock"] = parse_duration(fields["wall_clock"], "wall_clock")
    for key in ("cooldown", "period", "period_budget"):
        if key in fields:
            fields[key] = parse_duration(fields[key], key)
    if "period_budget" in fields and "period" not in fields:
        raise LoopError(f"{path}: period_budget requires period")
    return fields


def parse_positive_int(raw: str, field: str) -> int:
    try:
        value = int(raw)
    except ValueError as error:
        raise LoopError(f"{field} must be a positive integer") from error
    if value < 1:
        raise LoopError(f"{field} must be a positive integer")
    return value


def log_path(fields: dict) -> Path:
    return Path(fields["log"])


def load_log(fields: dict) -> list[dict]:
    path = log_path(fields)
    if not path.exists():
        return []
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise LoopError(f"{path}:{number}: log line is not valid JSON") from error
        if not isinstance(record, dict):
            raise LoopError(f"{path}:{number}: log line must be a JSON object")
        records.append(record)
    return records


def parse_timestamp(record: dict, path: Path, number: int) -> datetime:
    raw = record.get("timestamp")
    if not isinstance(raw, str):
        raise LoopError(f"{path}:{number}: log record lacks a timestamp")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        raise LoopError(f"{path}:{number}: log record timestamp is invalid") from error
    if parsed.tzinfo is None:
        raise LoopError(f"{path}:{number}: log record timestamp must be timezone-aware")
    return parsed


def command_check(fields: dict) -> dict:
    if fields["status"] != "active":
        return {"decision": "skip", "reason": f"status {fields['status']}"}
    if "skip_when" in fields:
        exit_code, _ = run_shell(fields["skip_when"], fields["wall_clock"])
        if exit_code == 0:
            return {"decision": "skip", "reason": "skip_when matched"}
    path = log_path(fields)
    records = load_log(fields)
    now = datetime.now(timezone.utc)
    timestamps = [
        parse_timestamp(record, path, number)
        for number, record in enumerate(records, 1)
    ]
    remaining_cooldown = 0
    if "cooldown" in fields and timestamps:
        elapsed = (now - max(timestamps)).total_seconds()
        remaining_cooldown = max(0, int(fields["cooldown"] - elapsed))
        if remaining_cooldown > 0:
            return {
                "decision": "skip",
                "reason": f"cooldown active ({remaining_cooldown}s remaining)",
            }
    remaining_budget = None
    if "period_budget" in fields:
        window_start = now - timedelta(seconds=fields["period"])
        consumed = 0
        for number, record in enumerate(records, 1):
            if parse_timestamp(record, path, number) >= window_start:
                consumed += int(record.get("wall_clock_used", 0))
        remaining_budget = max(0, fields["period_budget"] - consumed)
        if remaining_budget == 0:
            return {"decision": "skip", "reason": "period budget exhausted"}
    return {
        "decision": "run",
        "reason": "gates green",
        "remaining": {
            "cooldown_seconds": remaining_cooldown,
            "period_budget_seconds": remaining_budget,
            "wall_clock_seconds": fields["wall_clock"],
            "max_iterations": fields["max_iterations"],
        },
    }


def run_shell(command: str, timeout: int) -> tuple[Optional[int], str]:
    """Run one spec command; a hung command counts as failed (exit None)."""
    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as expired:
        output = (expired.stdout or b"").decode(errors="replace") + (expired.stderr or b"").decode(errors="replace")
        return None, f"{output}\ntimed out after {timeout}s"
    return completed.returncode, completed.stdout + completed.stderr


def command_verify(fields: dict) -> dict:
    failures = []
    for command in fields["verify"]:
        exit_code, output = run_shell(command, fields["wall_clock"])
        if exit_code != 0:
            lines = output.splitlines()
            failures.append(
                {
                    "command": command,
                    "exit_code": exit_code,
                    "output_tail": "\n".join(lines[-OUTPUT_TAIL_LINES:]),
                }
            )
    if failures:
        return {"result": "fail", "failures": failures}
    return {"result": "pass", "commands": len(fields["verify"])}


def command_record(fields: dict, arguments: argparse.Namespace) -> dict:
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "loop": fields["loop"],
        "trigger": fields["trigger"],
        "iterations": arguments.iterations,
        "result": arguments.result,
        "wall_clock_used": parse_duration(arguments.used, "--used"),
        "rescue": arguments.rescue,
        "notes": arguments.notes,
    }
    path = log_path(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
    return {"recorded": record["result"], "log": str(path)}


def command_status(fields: dict) -> dict:
    records = load_log(fields)
    counts = {result: 0 for result in RESULTS}
    wall_clock_used = 0
    human_rescues = 0
    for record in records:
        result = record.get("result")
        if result in counts:
            counts[result] += 1
        wall_clock_used += int(record.get("wall_clock_used", 0))
        if record.get("rescue"):
            human_rescues += 1
    return {
        "loop": fields["loop"],
        "runs": len(records),
        "accepted": counts["pass"],
        "rejected": counts["fail"],
        "blocked": counts["blocked"],
        "skipped": counts["skipped"],
        "human_rescues": human_rescues,
        "wall_clock_used_seconds": wall_clock_used,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("check", "verify", "record", "status"))
    result.add_argument("--spec", type=Path, required=True)
    result.add_argument("--result", choices=RESULTS)
    result.add_argument("--iterations", type=int, default=0)
    result.add_argument("--used", default="0s")
    result.add_argument("--notes", default="")
    result.add_argument("--rescue", action="store_true")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        fields = parse_spec(arguments.spec)
        if arguments.command == "check":
            payload = command_check(fields)
        elif arguments.command == "verify":
            payload = command_verify(fields)
        elif arguments.command == "record":
            if arguments.result is None:
                raise LoopError("record requires --result")
            if arguments.iterations < 0:
                raise LoopError("--iterations must be zero or positive")
            payload = command_record(fields, arguments)
        else:
            payload = command_status(fields)
    except LoopError as error:
        print(str(error), file=sys.stderr)
        return 2
    print(json.dumps(payload, sort_keys=True))
    if arguments.command == "verify" and payload["result"] == "fail":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
