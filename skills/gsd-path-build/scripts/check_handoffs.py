#!/usr/bin/env python3
"""Validate the durable hand-off packets that bridge GSD Path phases."""

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple


PIPELINE = "gsd-path/v2"
DEFAULT_PROJECT_DIR = ".project"
STANDARD_DIMENSIONS = ("domain", "stack", "pitfalls", "similar")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DISPATCH_PATTERN = re.compile(
    r"^- `(?P<dimension>[^`]+)` — (?P<status>dispatched|skipped) "
    r"→ (?P<output>[^—]+) — (?P<reason>.+)$"
)
QUESTION_PATTERN = re.compile(r"^- `\[RESEARCH\] (?P<question>[^`]+)` → `(?P<dimension>[^`]+)`$")
FINDING_PATTERN = re.compile(r"^### (?P<id>P\d{3}) — (?P<title>.+)$")
CRITERION_LOCATOR_PATTERN = re.compile(r"^SC[1-9]\d*$")
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
NUMBERED_ITEM_PATTERN = re.compile(r"^(\d+)\.\s+(\S.*)$")
COVERAGE_ROW_PATTERN = re.compile(
    r"^\|\s*(?P<criterion>SC[1-9]\d*)\s*\|\s*(?P<task>T\d{3})\s*"
    r"\|\s*(?P<acceptance>AC[1-9]\d*)\s*\|"
)
TASK_ID_PATTERN = re.compile(r"(?m)^id:\s*(T\d{3})\s*(?:#.*)?$")
OWNED_CRITERION_PATTERN = re.compile(r"^- (None|SC[1-9]\d*)$")
VERIFY_BLOCK_PATTERN = re.compile(r"```bash[ \t]*\n(?P<block>.*?)```", re.DOTALL)
WAVE_REVIEW_NAME = re.compile(
    r"wave-(?P<wave>\d+)\.cycle\d+(?:\.(?:contract|adversarial))?\.md$"
)
WAVE_SC_HEADING = re.compile(r"^### (SC[1-9]\d*) — (.+)$")
WAVE_FIELD_PATTERN = re.compile(r"(?m)^wave:\s*(\d+)\s*(?:#.*)?$")


def _source_pattern(project_dir: str) -> "re.Pattern[str]":
    return re.compile(
        rf"^{re.escape(project_dir)}/review/(?:FINAL\.md|final-gap-\d+\.md)$"
    )


def _project_dir(value: str) -> str:
    """Argparse type for --project-dir: a relative POSIX-style path."""

    path = PurePosixPath(value)
    if path.is_absolute():
        raise argparse.ArgumentTypeError(
            f"--project-dir must be a relative path, found absolute: {value}"
        )
    if ".." in path.parts:
        raise argparse.ArgumentTypeError(
            f"--project-dir must not contain '..', found: {value}"
        )
    return str(path)


class HandoffError(RuntimeError):
    """Raised when a phase hand-off is absent, stale, or incomplete."""


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise HandoffError(f"missing real hand-off file: {relative}")
    return path.read_text(encoding="utf-8")


def _frontmatter(state: str) -> Dict[str, str]:
    lines = state.splitlines()
    if not lines or lines[0] != "---":
        raise HandoffError("STATE.md is missing YAML frontmatter")
    values: Dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        match = re.fullmatch(r"([a-z_]+):\s*([^#]*?)(?:\s+#.*)?", line)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    raise HandoffError("STATE.md frontmatter is not closed")


def _require_pipeline(root: Path, project_dir: str) -> Dict[str, str]:
    values = _frontmatter(_read(root, f"{project_dir}/STATE.md"))
    if values.get("pipeline") != PIPELINE:
        raise HandoffError("STATE.md has the wrong pipeline marker")
    return values


def _require_state(root: Path, phase: str, status: str, project_dir: str) -> None:
    values = _require_pipeline(root, project_dir)
    if values.get("phase") != phase or values.get("status") != status:
        raise HandoffError(
            f"STATE.md must be {phase}/{status}, found "
            f"{values.get('phase', '<missing>')}/{values.get('status', '<missing>')}"
        )


def _line_value(text: str, label: str) -> str:
    match = re.search(rf"(?m)^{re.escape(label)}\s*(.+)$", text)
    if not match:
        raise HandoffError(f"missing {label.strip()}")
    value = match.group(1).strip().strip("`")
    if not value or value.startswith("<") or value.endswith(">"):
        raise HandoffError(f"{label.strip()} is empty or still a placeholder")
    return value


def _section(text: str, heading: str) -> str:
    match = re.search(
        rf"(?ms)^## {re.escape(heading)}\s*\n(?P<body>.*?)(?=^## |\Z)", text
    )
    if not match:
        raise HandoffError(f"missing ## {heading} section")
    return match.group("body")


def _non_placeholder(value: str, label: str) -> str:
    cleaned = value.strip().strip("`")
    if not cleaned or cleaned.casefold() in {"none", "n/a", "null"}:
        raise HandoffError(f"{label} is empty")
    if "<" in cleaned or ">" in cleaned:
        raise HandoffError(f"{label} is still a placeholder")
    return cleaned


def _validate_evidence(root: Path, relative: str) -> None:
    text = _read(root, relative)
    findings = re.split(r"(?m)^## Finding:\s*", text)[1:]
    if not findings:
        raise HandoffError(f"{relative} has no findings")
    required = ("**Claim**:", "**Source**:", "**Confidence**:", "**Why it matters here**:")
    for finding in findings:
        for field in required:
            if field not in finding:
                raise HandoffError(f"{relative} finding is missing {field}")


def _research_questions(intent: str) -> List[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*- \[RESEARCH\] (.+?)\s*$", intent)
    ]


def _research_assignments(section: str) -> List[Tuple[str, str]]:
    assignments = []
    for line in section.splitlines():
        if line.strip() == "- none":
            continue
        match = QUESTION_PATTERN.fullmatch(line.strip())
        if match:
            assignments.append((match.group("question").strip(), match.group("dimension")))
    return assignments


def validate_research(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate the research-to-synthesis hand-off and return its summary."""

    _require_state(root, "research", "done", project_dir)
    intent_path = f"{project_dir}/intent/INTENT.md"
    if not (root / intent_path).is_file():
        # CHARTER.md is program-level: it stays at the real .project/ top level.
        intent_path = f"{DEFAULT_PROJECT_DIR}/CHARTER.md"
    intent = _read(root, intent_path)
    handoff = _read(root, f"{project_dir}/research/RESEARCH.md")
    if _line_value(handoff, "Phase:") != "research":
        raise HandoffError("RESEARCH.md names the wrong phase")
    if _line_value(handoff, "Status:") != "complete":
        raise HandoffError("RESEARCH.md is not complete")
    if _line_value(handoff, "Intent:") != intent_path:
        raise HandoffError(f"RESEARCH.md must point to {intent_path}")

    dispatch_rows = []
    for line in _section(handoff, "Dispatch").splitlines():
        match = DISPATCH_PATTERN.fullmatch(line.strip())
        if match:
            dispatch_rows.append(
                (
                    match.group("dimension"),
                    match.group("status"),
                    match.group("output").strip().strip("`"),
                    _non_placeholder(match.group("reason"), "research reason"),
                )
            )
    if not dispatch_rows:
        raise HandoffError("RESEARCH.md has no dispatch rows")

    dimensions = [row[0] for row in dispatch_rows]
    if len(dimensions) != len(set(dimensions)):
        raise HandoffError("RESEARCH.md repeats a dimension")
    missing = sorted(set(STANDARD_DIMENSIONS) - set(dimensions))
    if missing:
        raise HandoffError("RESEARCH.md omits dimensions: " + ", ".join(missing))

    dispatched: List[str] = []
    skipped: List[str] = []
    for dimension, status, output, _reason in dispatch_rows:
        if status == "dispatched":
            expected = f"{project_dir}/research/evidence-{dimension}.md"
            if output != expected:
                raise HandoffError(
                    f"{dimension} output must be {expected}, found {output}"
                )
            _validate_evidence(root, output)
            dispatched.append(dimension)
        else:
            if output.casefold() != "none":
                raise HandoffError(f"skipped {dimension} must not name an output")
            skipped.append(dimension)

    if not set(STANDARD_DIMENSIONS) & set(dispatched):
        raise HandoffError("RESEARCH.md must dispatch at least one standard dimension")

    assignments = _research_assignments(_section(handoff, "Question assignments"))
    questions = _research_questions(intent)
    assigned_questions = [question for question, _dimension in assignments]
    if sorted(assigned_questions) != sorted(questions):
        raise HandoffError("RESEARCH.md question assignments do not match the intent source")
    if len(assigned_questions) != len(set(assigned_questions)):
        raise HandoffError("RESEARCH.md repeats a question assignment")
    dispatched_set = set(dispatched)
    if any(dimension not in dispatched_set for _question, dimension in assignments):
        raise HandoffError("every assigned question must target a dispatched dimension")

    return {
        "phase": "research",
        "dispatched": sorted(dispatched),
        "skipped": sorted(skipped),
        "questions": len(questions),
    }


def _finding_blocks(text: str) -> List[Tuple[str, str]]:
    # Match any `### P` heading so a malformed finding id becomes its own
    # block and fails FINDING_PATTERN instead of vanishing into the
    # previous block unvalidated.
    matches = list(re.finditer(r"(?m)^### P.*$", text))
    return [
        (match.group(0), text[match.end() : next_match.start() if next_match else len(text)])
        for match, next_match in zip(matches, matches[1:] + [None])
    ]


def _field(block: str, field: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(field)}\*\*:\s*(.+)$", block)
    if not match:
        raise HandoffError(f"patch finding is missing {field}")
    return _non_placeholder(match.group(1), f"patch finding {field}")


def _source_field(block: str, field: str, source: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(field)}\*\*:\s*(.*)$", block)
    if not match:
        raise HandoffError(f"{source} is missing {field}")
    value = match.group(1).strip().strip("`")
    if not value or "<" in value or ">" in value:
        raise HandoffError(f"{source} has an incomplete {field}")
    return value


def _heading_block(text: str, heading: re.Match[str]) -> str:
    body = text[heading.end() :]
    next_heading = re.search(r"(?m)^#{2,3} ", body)
    return body[: next_heading.start() if next_heading else len(body)]


def _source_repair_fields(source: str, text: str, locator: str) -> Tuple[str, str]:
    if source.endswith("FINAL.md"):
        if not CRITERION_LOCATOR_PATTERN.fullmatch(locator):
            raise HandoffError(f"{source} locator must name an SC criterion")
        heading = re.search(rf"(?m)^### {re.escape(locator)} — .+$", text)
        if not heading:
            raise HandoffError(f"{source} does not contain locator {locator}")
        block = _heading_block(text, heading)
        verdict = _source_field(block, "Verdict", source)
        if verdict not in {"not-met", "unverifiable"}:
            raise HandoffError(f"{source} locator {locator} is not a failed criterion")
        evidence = _source_field(block, "Finding", source)
        fix_direction = _source_field(block, "Fix direction", source)
    else:
        if not locator.startswith("Risk: ") or locator not in text.splitlines():
            raise HandoffError(f"{source} does not contain locator {locator}")
        block = _section(text, "Finding")
        evidence = _source_field(block, "Found", source)
        fix_direction = _source_field(block, "Fix direction", source)

    if evidence.casefold() == "none" or fix_direction.casefold() == "none":
        raise HandoffError(f"{source} locator {locator} has no repair evidence")
    return evidence, fix_direction


def _reviewed_head(text: str, source: str) -> str:
    value = _line_value(text, "Reviewed HEAD:")
    if not SHA_PATTERN.fullmatch(value):
        raise HandoffError(f"{source} Reviewed HEAD is not a full commit SHA")
    return value


def _strip_comments(text: str) -> str:
    return COMMENT_PATTERN.sub("", text)


def _numbered_items(section: str) -> Dict[int, str]:
    items: Dict[int, str] = {}
    for line in _strip_comments(section).splitlines():
        match = NUMBERED_ITEM_PATTERN.fullmatch(line.strip())
        if not match:
            continue
        number = int(match.group(1))
        if number in items:
            raise HandoffError(f"repeated numbered item {number}")
        items[number] = match.group(2).strip()
    return items


def _success_criteria(intent: str) -> Dict[str, str]:
    items = _numbered_items(_section(intent, "Success criteria"))
    if not items:
        raise HandoffError("INTENT.md has no success criteria")
    expected = list(range(1, max(items) + 1))
    if sorted(items) != expected:
        raise HandoffError("INTENT.md success criteria must be contiguous from 1")
    return {f"SC{number}": text for number, text in items.items()}


def _coverage_rows(plan: str) -> List[Tuple[str, str, str]]:
    body = _section(plan, "Intent coverage")
    rows: List[Tuple[str, str, str]] = []
    seen = set()
    for line in _strip_comments(body).splitlines():
        match = COVERAGE_ROW_PATTERN.match(line.strip())
        if not match:
            continue
        row = (
            match.group("criterion"),
            match.group("task"),
            match.group("acceptance"),
        )
        if row in seen:
            raise HandoffError(
                f"Intent coverage repeats {row[0]} {row[1]} {row[2]}"
            )
        seen.add(row)
        rows.append(row)
    if not rows:
        raise HandoffError("PLAN.md Intent coverage has no rows")
    return rows


def _task_texts(root: Path, project_dir: str) -> Dict[str, str]:
    tasks_dir = root / project_dir / "tasks"
    if not tasks_dir.is_dir():
        raise HandoffError(f"missing {project_dir}/tasks")
    tasks: Dict[str, str] = {}
    for path in sorted(tasks_dir.glob("*.md")):
        if not path.is_file() or path.is_symlink():
            continue
        text = path.read_text(encoding="utf-8")
        match = TASK_ID_PATTERN.search(text)
        if not match:
            raise HandoffError(f"{path.name} is missing an id")
        task_id = match.group(1)
        if task_id in tasks:
            raise HandoffError(f"duplicate task id {task_id}")
        tasks[task_id] = text
    if not tasks:
        raise HandoffError(f"no task files in {project_dir}/tasks")
    return tasks


def _owned_criteria(task_text: str, task_id: str) -> List[str]:
    body = _section(task_text, "Intent coverage")
    owned: List[str] = []
    saw_none = False
    for line in _strip_comments(body).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        match = OWNED_CRITERION_PATTERN.fullmatch(stripped)
        if not match:
            raise HandoffError(f"{task_id} Intent coverage has an invalid line")
        value = match.group(1)
        if value == "None":
            saw_none = True
            continue
        owned.append(value)
    if saw_none and owned:
        raise HandoffError(f"{task_id} Intent coverage mixes None with SCs")
    if saw_none:
        return []
    if not owned:
        raise HandoffError(f"{task_id} Intent coverage is empty")
    if len(owned) != len(set(owned)):
        raise HandoffError(f"{task_id} repeats an owned criterion")
    return owned


def _acceptance_ids(task_text: str, task_id: str) -> Set[str]:
    items = _numbered_items(_section(task_text, "Acceptance criteria"))
    if not items:
        raise HandoffError(f"{task_id} has no acceptance criteria")
    return {f"AC{number}" for number in items}


def _has_verify(task_text: str) -> bool:
    body = _section(task_text, "Verify")
    block = VERIFY_BLOCK_PATTERN.search(body)
    return bool(block and block.group("block").strip())


def _normalize_ws(value: str) -> str:
    return " ".join(value.split())


def _verify_command(task_text: str) -> str:
    body = _section(task_text, "Verify")
    block = VERIFY_BLOCK_PATTERN.search(body)
    if block is None:
        return ""
    return _normalize_ws(block.group("block"))


def _acceptance_items(task_text: str, task_id: str) -> Dict[int, str]:
    items = _numbered_items(_section(task_text, "Acceptance criteria"))
    if not items:
        raise HandoffError(f"{task_id} has no acceptance criteria")
    return items


def _task_wave(task_text: str, task_id: str) -> int:
    match = WAVE_FIELD_PATTERN.search(task_text)
    if not match:
        raise HandoffError(f"{task_id} is missing a wave")
    return int(match.group(1))


def _intent_path(project_dir: str) -> str:
    return f"{project_dir}/intent/INTENT.md"


def _owned_by_wave(
    tasks: Dict[str, str], assigned: Dict[str, Set[str]], wave: int
) -> List[str]:
    owned: Set[str] = set()
    for task_id, text in tasks.items():
        if _task_wave(text, task_id) == wave:
            owned.update(assigned[task_id])
    return sorted(owned, key=lambda name: int(name[2:]))


def validate_plan(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate INTENT success criteria against PLAN.md coverage and tasks."""

    _require_pipeline(root, project_dir)
    intent = _read(root, _intent_path(project_dir))
    plan = _read(root, f"{project_dir}/plan/PLAN.md")
    criteria = _success_criteria(intent)
    rows = _coverage_rows(plan)
    tasks = _task_texts(root, project_dir)
    assigned: Dict[str, Set[str]] = {task_id: set() for task_id in tasks}
    covered = set()
    for criterion, task_id, acceptance in rows:
        if criterion not in criteria:
            raise HandoffError(f"Intent coverage names unknown {criterion}")
        if task_id not in tasks:
            raise HandoffError(f"Intent coverage names unknown {task_id}")
        items = _acceptance_items(tasks[task_id], task_id)
        number = int(acceptance[2:])
        if number not in items:
            raise HandoffError(f"{task_id} has no {acceptance}")
        if not _has_verify(tasks[task_id]):
            raise HandoffError(f"{task_id} Verify is empty")
        assigned[task_id].add(criterion)
        covered.add(criterion)
    missing = [criterion for criterion in criteria if criterion not in covered]
    if missing:
        raise HandoffError("Intent coverage omits " + ", ".join(missing))
    for task_id, text in tasks.items():
        owned = set(_owned_criteria(text, task_id))
        if owned != assigned[task_id]:
            raise HandoffError(f"{task_id} Intent coverage does not match PLAN.md")
    project_verify = _normalize_ws(_line_value(plan, "Project verify:"))
    for task_id, text in tasks.items():
        command = _verify_command(text)
        if not command or command != project_verify:
            continue
        named = any(
            project_verify in _normalize_ws(criteria[sc_id])
            for sc_id in assigned[task_id]
            if sc_id in criteria
        )
        if not named:
            raise HandoffError(f"{task_id} Verify must not copy Project verify")
    return {
        "phase": "plan",
        "criteria": sorted(criteria),
        "rows": len(rows),
        "tasks": len(tasks),
    }


def validate_wave(
    root: Path,
    project_dir: str = DEFAULT_PROJECT_DIR,
    review: str = "",
) -> Dict[str, object]:
    """Require a wave review to carry a verdict for every owned INTENT SC."""

    _require_pipeline(root, project_dir)
    if not review:
        raise HandoffError("wave validation requires --review")
    name = PurePosixPath(review).name
    named = WAVE_REVIEW_NAME.fullmatch(name)
    if not named:
        raise HandoffError(f"unrecognized wave review file: {name}")
    wave = int(named.group("wave"))
    intent = _read(root, _intent_path(project_dir))
    criteria = _success_criteria(intent)
    rows = _coverage_rows(_read(root, f"{project_dir}/plan/PLAN.md"))
    tasks = _task_texts(root, project_dir)
    assigned: Dict[str, Set[str]] = {task_id: set() for task_id in tasks}
    for criterion, task_id, _acceptance in rows:
        if task_id in assigned and criterion in criteria:
            assigned[task_id].add(criterion)
    owned = _owned_by_wave(tasks, assigned, wave)
    text = _read(root, review)
    try:
        coverage = _section(text, "Intent coverage")
    except HandoffError:
        coverage = None
    if not owned:
        if coverage is not None and WAVE_SC_HEADING.search(_strip_comments(coverage)):
            raise HandoffError(f"{name} Intent coverage names SCs this wave does not own")
        return {"phase": "wave", "wave": wave, "owned": [], "review": review}
    if coverage is None:
        raise HandoffError(f"{name} is missing ## Intent coverage")
    verdicts: Dict[str, str] = {}
    for line in _strip_comments(coverage).splitlines():
        match = WAVE_SC_HEADING.fullmatch(line.strip())
        if not match:
            continue
        sc_id = match.group(1)
        verdict = match.group(2).rsplit(":", 1)[-1].strip()
        if verdict not in {"pass", "fail"}:
            raise HandoffError(f"{name} {sc_id} heading must end with `: pass` or `: fail`")
        if sc_id in verdicts:
            raise HandoffError(f"{name} Intent coverage repeats {sc_id}")
        verdicts[sc_id] = verdict
    if sorted(verdicts, key=lambda n: int(n[2:])) != owned:
        raise HandoffError(f"{name} Intent coverage must cover exactly {', '.join(owned)}")
    overall = _line_value(text, "Wave verdict:")
    if overall not in {"pass", "blocked"}:
        raise HandoffError(f"{name} Wave verdict is invalid")
    if overall == "pass" and "fail" in verdicts.values():
        raise HandoffError(f"{name} Wave verdict is pass while an owned SC failed")
    return {
        "phase": "wave",
        "wave": wave,
        "owned": owned,
        "review": review,
        "verdict": overall,
    }


def validate_final(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Require FINAL.md to give an evidenced verdict for every INTENT SC."""

    _require_pipeline(root, project_dir)
    criteria = _success_criteria(_read(root, _intent_path(project_dir)))
    relative = f"{project_dir}/review/FINAL.md"
    text = _read(root, relative)
    overall = _line_value(text, "Overall verdict:")
    if overall not in {"pass", "blocked"}:
        raise HandoffError("FINAL.md Overall verdict is invalid")
    text = _strip_comments(_section(text, "Success criteria"))
    blocks = list(re.finditer(r"(?m)^### (SC[1-9]\d*) — .+$", text))
    expected = list(criteria)
    found = [match.group(1) for match in blocks]
    if sorted(found, key=lambda n: int(n[2:])) != expected:
        raise HandoffError("FINAL.md Success criteria must cover exactly " + ", ".join(expected))
    verdicts: Dict[str, str] = {}
    for index, heading in enumerate(blocks):
        sc_id = heading.group(1)
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
        block = text[heading.end() : end]
        verdict_match = re.search(r"(?m)^- \*\*Verdict\*\*:\s*(.+)$", block)
        check_match = re.search(r"(?m)^- \*\*Check\*\*:\s*(.+)$", block)
        reference_match = re.search(r"(?m)^- \*\*Reference\*\*:\s*(.+)$", block)
        if not verdict_match:
            raise HandoffError(f"FINAL.md {sc_id} is missing a Verdict")
        verdict = verdict_match.group(1).strip().strip("`")
        if verdict not in {"met", "not-met", "unverifiable"}:
            raise HandoffError(f"FINAL.md {sc_id} Verdict is invalid")
        verdicts[sc_id] = verdict
        check = check_match.group(1).strip().strip("`") if check_match else "none"
        reference = (
            reference_match.group(1).strip().strip("`") if reference_match else "none"
        )
        if overall == "pass":
            if verdict != "met":
                raise HandoffError(f"FINAL.md Overall verdict is pass while {sc_id} is {verdict}")
            if check.casefold() == "none" and reference.casefold() == "none":
                raise HandoffError(f"FINAL.md {sc_id} lacks a Check or Reference")
    return {
        "phase": "ship",
        "criteria": expected,
        "verdict": overall,
    }


def validate_patch_findings(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate the review-to-patch hand-off and return its summary."""

    _require_state(root, "ship", "blocked", project_dir)
    handoff = _read(root, f"{project_dir}/review/PATCH-FINDINGS.md")
    reviewed_head = _reviewed_head(handoff, "PATCH-FINDINGS.md")
    if _line_value(handoff, "State:") != "ship/blocked":
        raise HandoffError("PATCH-FINDINGS.md names the wrong state")

    blocks = _finding_blocks(handoff)
    if not blocks:
        raise HandoffError("PATCH-FINDINGS.md has no findings")
    source_pattern = _source_pattern(project_dir)
    ids = []
    sources = []
    for heading, block in blocks:
        match = FINDING_PATTERN.fullmatch(heading)
        if not match:
            raise HandoffError("patch finding headings must use P### ids")
        finding_id = match.group("id")
        ids.append(finding_id)
        source = _field(block, "Source").strip("`")
        if not source_pattern.fullmatch(source):
            raise HandoffError(f"invalid patch finding source: {source}")
        source_text = _read(root, source)
        source_head = _reviewed_head(source_text, source)
        if source_head != reviewed_head:
            raise HandoffError(f"{source} Reviewed HEAD differs from PATCH-FINDINGS.md")
        if source.endswith("FINAL.md"):
            if _line_value(source_text, "Overall verdict:") != "blocked":
                raise HandoffError("FINAL.md is not a blocked finding source")
        elif _line_value(source_text, "Gap verdict:") != "blocked":
            raise HandoffError(f"{source} is not a blocked finding source")
        locator = _field(block, "Locator")
        evidence = _field(block, "Evidence")
        fix_direction = _field(block, "Fix direction")
        source_evidence, source_fix_direction = _source_repair_fields(
            source, source_text, locator
        )
        if evidence != source_evidence:
            raise HandoffError(f"{source} locator {locator} evidence does not match its source")
        if fix_direction != source_fix_direction:
            raise HandoffError(
                f"{source} locator {locator} fix direction does not match its source"
            )
        sources.append(source)

    expected_ids = [f"P{number:03d}" for number in range(1, len(ids) + 1)]
    if ids != expected_ids:
        raise HandoffError("patch finding ids must be contiguous and ordered")
    return {
        "phase": "ship",
        "reviewed_head": reviewed_head,
        "findings": ids,
        "sources": sorted(set(sources)),
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "phase", choices=("research", "patch", "plan", "wave", "final")
    )
    argument_parser.add_argument("--repo", type=Path, required=True)
    argument_parser.add_argument(
        "--project-dir",
        type=_project_dir,
        default=DEFAULT_PROJECT_DIR,
        help=(
            "relative POSIX-style project directory under --repo that holds the "
            "per-milestone artifacts (default: .project)"
        ),
    )
    argument_parser.add_argument(
        "--review",
        default="",
        help="repo-relative wave review path (required for phase wave)",
    )
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        repo = arguments.repo.resolve()
        if arguments.phase == "wave":
            result = validate_wave(repo, arguments.project_dir, arguments.review)
        else:
            validators = {
                "research": validate_research,
                "patch": validate_patch_findings,
                "plan": validate_plan,
                "final": validate_final,
            }
            result = validators[arguments.phase](repo, arguments.project_dir)
    except HandoffError as error:
        print(f"handoff validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
