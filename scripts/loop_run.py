#!/usr/bin/env python3
"""Deterministic gates for a GSD Path LOOP.md loop spec.

The loop skill (a model) reads the prose sections of a LOOP.md; this helper
reads only its fixed machine fields — exact `key: value` lines, one per
line, no nesting, read only from the header above the first `## `
section. `check` decides run/skip from status, cooldown, and period
budgets without running skip_when; `claim` runs skip_when before
admitting a pass; `verify` re-runs the spec's verifier
commands independently of any worker; `claim` atomically admits one pass and
`finish` closes it append-only from helper-owned timing and verify events;
`status` aggregates completed outcomes and exposes unfinished recovery.
Relative paths (spec `log:`, skip_when, verify commands) resolve against the
caller's working directory — invoke from the repository root.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator, Optional, Sequence

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


class LoopError(RuntimeError):
    pass


MANDATORY_FIELDS = ("loop", "status", "trigger", "verify", "max_iterations", "wall_clock", "log")
OPTIONAL_FIELDS = ("cooldown", "skip_when", "period", "period_budget")
KNOWN_FIELDS = frozenset((*MANDATORY_FIELDS, *OPTIONAL_FIELDS))
REPEATABLE_FIELDS = frozenset({"verify"})
STATUSES = ("active", "paused", "done")
RESULTS = ("pass", "fail", "blocked", "skipped")
CLAIM_EVENT = "claim"
VERIFY_EVENT = "verify"
FINISH_EVENT = "finish"
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
        if line.startswith("## "):
            break  # machine fields live in the header; prose sections follow
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


@contextmanager
def log_lock(fields: dict) -> Iterator[None]:
    path = log_path(fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+b") as handle:
        if sys.platform == "win32":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if sys.platform == "win32":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


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


def append_log(fields: dict, record: dict) -> None:
    path = log_path(fields)
    payload = (json.dumps(record, sort_keys=True) + "\n").encode()
    with path.open("ab", buffering=0) as handle:
        written = handle.write(payload)
        if written != len(payload):
            raise LoopError(f"could not append a complete record to {path}")
        os.fsync(handle.fileno())


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


def claim_id(record: dict, path: Path, number: int) -> str:
    value = record.get("claim")
    if not isinstance(value, str) or not value:
        raise LoopError(f"{path}:{number}: claim event lacks a claim id")
    return value


def require_record_fields(
    record: dict, expected: set[str], path: Path, number: int, event: str
) -> None:
    if set(record) != expected:
        raise LoopError(f"{path}:{number}: {event} record has unsupported fields")


def validate_text_field(record: dict, field: str, path: Path, number: int) -> str:
    value = record.get(field)
    if not isinstance(value, str):
        raise LoopError(f"{path}:{number}: {field} must be text")
    return value


def log_state(
    fields: dict, records: list[dict]
) -> tuple[list[dict], dict, dict, dict, Optional[dict]]:
    path = log_path(fields)
    outcomes = []
    claims = {}
    verifications: dict[str, list[dict]] = {}
    finishes = {}
    for number, record in enumerate(records, 1):
        event = record.get("event")
        if event is None:
            require_record_fields(
                record,
                {
                    "timestamp",
                    "loop",
                    "trigger",
                    "iterations",
                    "result",
                    "wall_clock_used",
                    "rescue",
                    "notes",
                },
                path,
                number,
                "legacy outcome",
            )
            parse_timestamp(record, path, number)
            if record.get("loop") != fields["loop"] or record.get("trigger") != fields["trigger"]:
                raise LoopError(f"{path}:{number}: outcome belongs to another loop")
            if record.get("result") not in RESULTS:
                raise LoopError(f"{path}:{number}: outcome has an invalid result")
            if integer_field(record, "iterations", path, number) > fields["max_iterations"]:
                raise LoopError(f"{path}:{number}: outcome exceeds max_iterations")
            integer_field(record, "wall_clock_used", path, number)
            if not isinstance(record.get("rescue"), bool):
                raise LoopError(f"{path}:{number}: rescue must be boolean")
            validate_text_field(record, "notes", path, number)
            outcomes.append(record)
            continue
        if event not in {CLAIM_EVENT, VERIFY_EVENT, FINISH_EVENT}:
            raise LoopError(f"{path}:{number}: unknown log event {event}")
        identifier = claim_id(record, path, number)
        if event == CLAIM_EVENT:
            require_record_fields(
                record,
                {
                    "event",
                    "claim",
                    "timestamp",
                    "loop",
                    "trigger",
                    "max_iterations",
                    "wall_clock_limit",
                },
                path,
                number,
                "claim",
            )
            if identifier in claims:
                raise LoopError(f"{path}:{number}: duplicate claim {identifier}")
            parse_timestamp(record, path, number)
            if record.get("loop") != fields["loop"] or record.get("trigger") != fields["trigger"]:
                raise LoopError(f"{path}:{number}: claim belongs to another loop")
            if integer_field(record, "max_iterations", path, number) < 1:
                raise LoopError(f"{path}:{number}: claim max_iterations must be positive")
            if integer_field(record, "wall_clock_limit", path, number) < 1:
                raise LoopError(f"{path}:{number}: claim wall_clock_limit must be positive")
            claims[identifier] = record
            continue
        if event == VERIFY_EVENT:
            require_record_fields(
                record,
                {
                    "event",
                    "claim",
                    "timestamp",
                    "sequence",
                    "iteration",
                    "result",
                    "commands",
                },
                path,
                number,
                "verify",
            )
            if identifier not in claims:
                raise LoopError(
                    f"{path}:{number}: verify references unknown claim {identifier}"
                )
            if identifier in finishes:
                raise LoopError(
                    f"{path}:{number}: verify follows finish for claim {identifier}"
                )
            if record.get("result") not in {"pass", "fail"}:
                raise LoopError(
                    f"{path}:{number}: verify result must be pass or fail"
                )
            verified_at = parse_timestamp(record, path, number)
            claim_record = claims[identifier]
            claim_number = records.index(claim_record) + 1
            if verified_at < parse_timestamp(claim_record, path, claim_number):
                raise LoopError(f"{path}:{number}: verify predates its claim")
            sequence = integer_field(record, "sequence", path, number)
            expected = len(verifications.get(identifier, [])) + 1
            if sequence != expected:
                raise LoopError(
                    f"{path}:{number}: verify sequence must be {expected}"
                )
            iteration = integer_field(record, "iteration", path, number)
            if iteration != max(0, sequence - 1):
                raise LoopError(
                    f"{path}:{number}: verify iteration does not match sequence"
                )
            max_iterations = integer_field(
                claim_record, "max_iterations", path, claim_number
            )
            if sequence > max_iterations + 1:
                raise LoopError(f"{path}:{number}: verify exceeds max_iterations")
            if integer_field(record, "commands", path, number) != len(fields["verify"]):
                raise LoopError(f"{path}:{number}: verify command count does not match spec")
            verifications.setdefault(identifier, []).append(record)
            continue
        if identifier not in claims:
            raise LoopError(f"{path}:{number}: finish references unknown claim {identifier}")
        if identifier in finishes:
            raise LoopError(f"{path}:{number}: duplicate finish for claim {identifier}")
        require_record_fields(
            record,
            {
                "event",
                "claim",
                "timestamp",
                "loop",
                "trigger",
                "iterations",
                "result",
                "wall_clock_used",
                "rescue",
                "notes",
            },
            path,
            number,
            "finish",
        )
        claim_record = claims[identifier]
        claim_number = records.index(claim_record) + 1
        started = parse_timestamp(claim_record, path, claim_number)
        finished_at = parse_timestamp(record, path, number)
        if finished_at < started:
            raise LoopError(f"{path}:{number}: finish predates its claim")
        if record.get("loop") != claim_record.get("loop") or record.get("trigger") != claim_record.get("trigger"):
            raise LoopError(f"{path}:{number}: finish does not match its claim")
        verification_records = verifications.get(identifier, [])
        iterations = integer_field(record, "iterations", path, number)
        if iterations != max(0, len(verification_records) - 1):
            raise LoopError(f"{path}:{number}: finish iterations do not match verify events")
        elapsed = max(0, math.ceil((finished_at - started).total_seconds()))
        if integer_field(record, "wall_clock_used", path, number) != elapsed:
            raise LoopError(f"{path}:{number}: finish wall clock does not match claim timestamps")
        result = record.get("result")
        if result not in RESULTS:
            raise LoopError(f"{path}:{number}: finish has an invalid result")
        if not isinstance(record.get("rescue"), bool):
            raise LoopError(f"{path}:{number}: finish rescue must be boolean")
        validate_text_field(record, "notes", path, number)
        latest = verification_records[-1]["result"] if verification_records else None
        if result == "pass" and latest != "pass":
            raise LoopError(f"{path}:{number}: passing finish lacks a passing verify")
        if latest == "pass" and result != "pass":
            raise LoopError(f"{path}:{number}: passing verify must finish as pass")
        if result == "fail":
            max_iterations = integer_field(
                claim_record, "max_iterations", path, claim_number
            )
            wall_clock_limit = integer_field(
                claim_record, "wall_clock_limit", path, claim_number
            )
            if latest != "fail" or (
                iterations < max_iterations and elapsed < wall_clock_limit
            ):
                raise LoopError(f"{path}:{number}: failing finish has no exhausted limit")
        finishes[identifier] = record
        outcomes.append(record)
    active = [record for identifier, record in claims.items() if identifier not in finishes]
    if len(active) > 1:
        raise LoopError(f"{path}: multiple unfinished claims require recovery")
    return outcomes, claims, verifications, finishes, active[0] if active else None


def integer_field(record: dict, field: str, path: Path, number: int) -> int:
    value = record.get(field, 0)
    if isinstance(value, bool):
        raise LoopError(f"{path}:{number}: {field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise LoopError(f"{path}:{number}: {field} must be an integer") from error
    if parsed < 0:
        raise LoopError(f"{path}:{number}: {field} must not be negative")
    return parsed


def remaining_period_budget(fields: dict, outcomes: list[dict], now: datetime) -> Optional[int]:
    if "period_budget" not in fields:
        return None
    path = log_path(fields)
    window_start = now - timedelta(seconds=fields["period"])
    consumed = 0
    for number, record in enumerate(outcomes, 1):
        if parse_timestamp(record, path, number) >= window_start:
            consumed += integer_field(record, "wall_clock_used", path, number)
    return max(0, fields["period_budget"] - consumed)


def precheck(fields: dict, run_skip_when: bool = True) -> Optional[dict]:
    if fields["status"] != "active":
        return {"decision": "skip", "reason": f"status {fields['status']}"}
    if "skip_when" in fields and run_skip_when:
        exit_code, _ = run_shell(fields["skip_when"], fields["wall_clock"])
        if exit_code == 0:
            return {"decision": "skip", "reason": "skip_when matched"}
    return None


def admission(fields: dict, records: list[dict], now: datetime) -> dict:
    outcomes, _claims, _verifications, _finishes, active = log_state(fields, records)
    if active is not None:
        line = records.index(active) + 1
        started = parse_timestamp(active, log_path(fields), line)
        wall_clock_limit = integer_field(
            active, "wall_clock_limit", log_path(fields), line
        )
        elapsed = max(0, int((now - started).total_seconds()))
        expired = elapsed >= wall_clock_limit
        result = {
            "decision": "skip",
            "reason": (
                f"claim {active['claim']} is expired"
                if expired
                else "another loop pass is still active"
            ),
            "recovery": {
                "elapsed_seconds": min(elapsed, wall_clock_limit),
                "wall_clock_limit": wall_clock_limit,
                "recoverable": expired,
            },
        }
        if expired:
            result["claim"] = active["claim"]
        return result
    path = log_path(fields)
    timestamps = [
        parse_timestamp(record, path, number)
        for number, record in enumerate(outcomes, 1)
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
    remaining_budget = remaining_period_budget(fields, outcomes, now)
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


def command_check(fields: dict) -> dict:
    skipped = precheck(fields, run_skip_when=False)
    if skipped is not None:
        return skipped
    decision = admission(fields, load_log(fields), datetime.now(timezone.utc))
    if "skip_when" in fields:
        decision["skip_when"] = "not run by check; claim runs it"
    return decision


def command_claim(fields: dict) -> dict:
    skipped = precheck(fields)
    if skipped is not None:
        return skipped
    with log_lock(fields):
        now = datetime.now(timezone.utc)
        decision = admission(fields, load_log(fields), now)
        if decision["decision"] != "run":
            return decision
        remaining_budget = decision["remaining"]["period_budget_seconds"]
        wall_clock_limit = fields["wall_clock"]
        if remaining_budget is not None:
            wall_clock_limit = min(wall_clock_limit, remaining_budget)
        identifier = uuid.uuid4().hex
        append_log(
            fields,
            {
                "event": CLAIM_EVENT,
                "claim": identifier,
                "timestamp": now.isoformat(),
                "loop": fields["loop"],
                "trigger": fields["trigger"],
                "max_iterations": fields["max_iterations"],
                "wall_clock_limit": wall_clock_limit,
            },
        )
        decision["claim"] = identifier
        decision["remaining"]["wall_clock_seconds"] = wall_clock_limit
        return decision


def run_shell(command: str, timeout: float) -> tuple[Optional[int], str]:
    """Run one spec command; a hung command counts as failed (exit None)."""
    try:
        completed = subprocess.run(
            command, shell=True, capture_output=True, text=True, check=False, timeout=timeout
        )
    except subprocess.TimeoutExpired as expired:
        output = (expired.stdout or b"").decode(errors="replace") + (expired.stderr or b"").decode(errors="replace")
        return None, f"{output}\ntimed out at the admitted wall-clock deadline"
    return completed.returncode, completed.stdout + completed.stderr


def command_verify(fields: dict, claim_identifier: Optional[str]) -> dict:
    if not claim_identifier:
        raise LoopError("verify requires --claim")
    with log_lock(fields):
        records = load_log(fields)
        _outcomes, claims, verifications, _finishes, active = log_state(
            fields, records
        )
        claim = claims.get(claim_identifier)
        if claim is None:
            raise LoopError(f"unknown claim {claim_identifier}")
        if active is None or active.get("claim") != claim_identifier:
            raise LoopError(f"claim {claim_identifier} is not the unfinished claim")
        claim_line = records.index(claim) + 1
        prior = verifications.get(claim_identifier, [])
        max_iterations = integer_field(
            claim, "max_iterations", log_path(fields), claim_line
        )
        if len(prior) > max_iterations:
            raise LoopError(f"claim {claim_identifier} has exhausted max_iterations")
        if prior and prior[-1]["result"] == "pass":
            raise LoopError(f"claim {claim_identifier} already verified pass")
        started = parse_timestamp(claim, log_path(fields), claim_line)
        wall_clock_limit = integer_field(
            claim, "wall_clock_limit", log_path(fields), claim_line
        )
        remaining = (
            started
            + timedelta(seconds=wall_clock_limit)
            - datetime.now(timezone.utc)
        ).total_seconds()
        if remaining <= 0:
            raise LoopError(f"claim {claim_identifier} has exhausted its wall clock")
        deadline = time.monotonic() + remaining
        failures = []
        for command in fields["verify"]:
            command_budget = deadline - time.monotonic()
            if command_budget <= 0:
                failures.append(
                    {
                        "command": command,
                        "exit_code": None,
                        "output_tail": "admitted wall-clock deadline exhausted before command",
                    }
                )
                break
            exit_code, output = run_shell(command, command_budget)
            if exit_code != 0:
                lines = output.splitlines()
                failures.append(
                    {
                        "command": command,
                        "exit_code": exit_code,
                        "output_tail": "\n".join(lines[-OUTPUT_TAIL_LINES:]),
                    }
                )
        result = "fail" if failures else "pass"
        sequence = len(prior) + 1
        iteration = max(0, sequence - 1)
        append_log(
            fields,
            {
                "event": VERIFY_EVENT,
                "claim": claim_identifier,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sequence": sequence,
                "iteration": iteration,
                "result": result,
                "commands": len(fields["verify"]),
            },
        )
    payload = {
        "result": result,
        "claim": claim_identifier,
        "commands": len(fields["verify"]),
        "iteration": iteration,
    }
    if failures:
        payload["failures"] = failures
    return payload


def command_finish(fields: dict, arguments: argparse.Namespace) -> dict:
    if not arguments.claim:
        raise LoopError("finish requires --claim")
    with log_lock(fields):
        records = load_log(fields)
        _outcomes, claims, verifications, finishes, active = log_state(fields, records)
        claim = claims.get(arguments.claim)
        if claim is None:
            raise LoopError(f"unknown claim {arguments.claim}")
        completed = finishes.get(arguments.claim)
        if completed is not None:
            candidate = {
                "result": arguments.result,
                "iterations": arguments.iterations,
                "rescue": arguments.rescue,
                "notes": arguments.notes,
            }
            if any(completed.get(key) != value for key, value in candidate.items()):
                raise LoopError(f"claim {arguments.claim} is already finished differently")
            return {
                "recorded": completed["result"],
                "claim": arguments.claim,
                "log": str(log_path(fields)),
                "reason": "already finished",
            }
        if active is None or active.get("claim") != arguments.claim:
            raise LoopError(f"claim {arguments.claim} is not the unfinished claim")
        claim_line = records.index(claim) + 1
        started = parse_timestamp(claim, log_path(fields), claim_line)
        max_iterations = integer_field(
            claim, "max_iterations", log_path(fields), claim_line
        )
        wall_clock_limit = integer_field(
            claim, "wall_clock_limit", log_path(fields), claim_line
        )
        verification_records = verifications.get(arguments.claim, [])
        iterations = max(0, len(verification_records) - 1)
        if arguments.iterations != iterations:
            raise LoopError(
                f"--iterations must match helper-observed fix cycles "
                f"({arguments.iterations} != {iterations})"
            )
        now = datetime.now(timezone.utc)
        elapsed = max(0, math.ceil((now - started).total_seconds()))
        if elapsed > wall_clock_limit and arguments.result not in {"fail", "blocked"}:
            raise LoopError(
                f"claim {arguments.claim} exhausted its wall clock; "
                "finish with fail or blocked"
            )
        latest_result = verification_records[-1]["result"] if verification_records else None
        if arguments.result == "pass" and latest_result != "pass":
            raise LoopError("pass requires a recorded passing verify")
        if latest_result == "pass" and arguments.result != "pass":
            raise LoopError("a recorded passing verify must finish as pass")
        if arguments.result == "fail" and (
            latest_result != "fail"
            or (iterations < max_iterations and elapsed < wall_clock_limit)
        ):
            raise LoopError("fail requires a failed verify and an exhausted limit")
        record = {
            "event": FINISH_EVENT,
            "claim": arguments.claim,
            "timestamp": now.isoformat(),
            "loop": fields["loop"],
            "trigger": fields["trigger"],
            "iterations": iterations,
            "result": arguments.result,
            "wall_clock_used": elapsed,
            "rescue": arguments.rescue,
            "notes": arguments.notes,
        }
        append_log(fields, record)
    return {
        "recorded": record["result"],
        "claim": arguments.claim,
        "log": str(log_path(fields)),
    }


def command_recover(fields: dict, claim_identifier: Optional[str]) -> dict:
    """Close one expired unfinished claim without caller-reported telemetry."""

    if not claim_identifier:
        raise LoopError("recover requires --claim")
    with log_lock(fields):
        records = load_log(fields)
        _outcomes, claims, verifications, finishes, active = log_state(fields, records)
        claim = claims.get(claim_identifier)
        if claim is None:
            raise LoopError(f"unknown claim {claim_identifier}")
        completed = finishes.get(claim_identifier)
        verification_records = verifications.get(claim_identifier, [])
        latest = verification_records[-1]["result"] if verification_records else None
        recovered_result = latest if latest in {"pass", "fail"} else "blocked"
        recovery_notes = f"recovered unfinished claim as {recovered_result}"
        if completed is not None:
            if (
                completed.get("result") != recovered_result
                or completed.get("notes") != recovery_notes
            ):
                raise LoopError(f"claim {claim_identifier} is already finished differently")
            return {
                "recorded": recovered_result,
                "claim": claim_identifier,
                "log": str(log_path(fields)),
                "reason": "already recovered",
            }
        if active is None or active.get("claim") != claim_identifier:
            raise LoopError(f"claim {claim_identifier} is not the unfinished claim")
        claim_line = records.index(claim) + 1
        started = parse_timestamp(claim, log_path(fields), claim_line)
        wall_clock_limit = integer_field(
            claim, "wall_clock_limit", log_path(fields), claim_line
        )
        now = datetime.now(timezone.utc)
        elapsed_raw = max(0.0, (now - started).total_seconds())
        if elapsed_raw < wall_clock_limit:
            raise LoopError(f"claim {claim_identifier} has not expired")
        iterations = max(0, len(verification_records) - 1)
        record = {
            "event": FINISH_EVENT,
            "claim": claim_identifier,
            "timestamp": now.isoformat(),
            "loop": fields["loop"],
            "trigger": fields["trigger"],
            "iterations": iterations,
            "result": recovered_result,
            "wall_clock_used": math.ceil(elapsed_raw),
            "rescue": False,
            "notes": recovery_notes,
        }
        append_log(fields, record)
    return {
        "recorded": recovered_result,
        "claim": claim_identifier,
        "iterations": iterations,
        "log": str(log_path(fields)),
    }


def command_status(fields: dict) -> dict:
    records = load_log(fields)
    outcomes, _claims, _verifications, _finishes, active = log_state(fields, records)
    counts = {result: 0 for result in RESULTS}
    wall_clock_used = 0
    human_rescues = 0
    path = log_path(fields)
    for number, record in enumerate(outcomes, 1):
        result = record.get("result")
        if result in counts:
            counts[result] += 1
        wall_clock_used += integer_field(record, "wall_clock_used", path, number)
        if record.get("rescue"):
            human_rescues += 1
    accepted = counts["pass"]
    evaluated = accepted + counts["fail"]
    return {
        "loop": fields["loop"],
        "runs": len(outcomes),
        "accepted": accepted,
        "rejected": counts["fail"],
        "blocked": counts["blocked"],
        "skipped": counts["skipped"],
        "human_rescues": human_rescues,
        "wall_clock_used_seconds": wall_clock_used,
        "acceptance_rate": round(accepted / evaluated, 4) if evaluated else None,
        "wall_clock_per_accept_seconds": (
            round(wall_clock_used / accepted, 2) if accepted else None
        ),
        "active_claim": active["claim"] if active is not None else None,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "command", choices=("check", "claim", "verify", "finish", "recover", "status")
    )
    result.add_argument("--spec", type=Path, required=True)
    result.add_argument("--claim")
    result.add_argument("--result", choices=RESULTS)
    result.add_argument("--iterations", type=int, default=0)
    result.add_argument("--notes", default="")
    result.add_argument("--rescue", action="store_true")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        fields = parse_spec(arguments.spec)
        if arguments.command == "check":
            payload = command_check(fields)
        elif arguments.command == "claim":
            payload = command_claim(fields)
        elif arguments.command == "verify":
            payload = command_verify(fields, arguments.claim)
        elif arguments.command == "recover":
            payload = command_recover(fields, arguments.claim)
        elif arguments.command == "finish":
            if arguments.result is None:
                raise LoopError(f"{arguments.command} requires --result")
            payload = command_finish(fields, arguments)
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
