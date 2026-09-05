#!/usr/bin/env python3
# gsd-path project runtime
"""Validate the durable hand-off packets that bridge GSD Path phases."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple

try:
    from pipeline_state import PipelineStateError, load_state
    import _common
except ImportError:  # pragma: no cover - package imports used by tests
    from scripts.pipeline_state import PipelineStateError, load_state
    from scripts import _common


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
TASK_FILE_NAME = re.compile(r"^(?P<id>T\d{3})-[a-z0-9][a-z0-9-]*\.md$")
OWNED_CRITERION_PATTERN = re.compile(r"^- (None|SC[1-9]\d*)$")
VERIFY_BLOCK_PATTERN = _common.VERIFY_BLOCK_PATTERN
FILES_FIELD_PATTERN = re.compile(r"^files:\s*(?P<value>[^#]*?)(?:\s+#.*)?$")
INLINE_LIST_PATTERN = _common.INLINE_LIST_PATTERN
LIST_ITEM_PATTERN = _common.LIST_ITEM_PATTERN
PLACEHOLDER_PATTERN = re.compile(r"<[a-zA-Z][^<>\n]*>")
VERIFY_PATH_SPLIT = re.compile(r"[=,:]")
WAVE_REVIEW_NAME = re.compile(
    r"wave-(?P<wave>[1-9]\d*)\.cycle(?P<cycle>[1-9]\d*)"
    r"(?:\.(?P<lens>contract|adversarial))?\.md$"
)
WAVE_SC_HEADING = re.compile(r"^### (SC[1-9]\d*) — (.+)$")
WAVE_TASK_HEADING = re.compile(
    r"^## (?P<task>T\d{3}) — (?P<title>.+): (?P<verdict>pass|fail)$"
)
WAVE_FIELD_PATTERN = re.compile(r"(?m)^wave:\s*(\d+)\s*(?:#.*)?$")
PLAN_WAVE_HEADING = re.compile(r"(?m)^## Wave (?P<wave>\d+) — (?P<title>.+)$")
PLAN_TASK_ROW = re.compile(
    r"^\|\s*(?P<task>T\d{3})\s*\|\s*(?P<title>[^|]+?)\s*\|"
    r"\s*(?P<deps>[^|]+?)\s*\|\s*(?P<files>[^|]+?)\s*\|\s*$"
)
MILESTONE_HEADING = re.compile(
    r"(?m)^### (?P<id>M\d{3}) — (?P<slug>\S.*?)\s*$"
)
SURFACE_HEADING = re.compile(
    r"(?m)^### (?P<surface>\S.*?) — (?P<task>T\d{3})\s*$"
)
SURFACE_CONTRACT_HEADING = re.compile(r"(?m)^## Surface contract\s*$")
GAP_NAME_PATTERN = re.compile(r"^final-gap-(?P<number>[1-9]\d*)\.md$")
GAP_HEADING_PATTERN = re.compile(
    r"^# Gap Review — (?P<number>[1-9]\d*): (?P<risk>\S.*)$"
)


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


_strip_yaml_comment = _common.strip_yaml_comment


def _strip_quotes(value: str) -> str:
    cleaned = value.strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        return cleaned[1:-1]
    return cleaned


def _reject_placeholder(value: str, label: str) -> None:
    placeholder = PLACEHOLDER_PATTERN.search(value)
    if placeholder is not None:
        raise HandoffError(
            f"{label} still contains the placeholder {placeholder.group(0)}; "
            "replace it with the real value"
        )


def _strict_frontmatter(text: str, label: str) -> Dict[str, object]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise HandoffError(f"{label} is missing YAML frontmatter")
    values: Dict[str, object] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == "---":
            return values
        if not line.strip() or line.lstrip().startswith("#"):
            index += 1
            continue
        match = re.fullmatch(r"([a-z_]+):\s*(.*)", line)
        if match is None:
            raise HandoffError(f"{label} has malformed frontmatter: {line}")
        key, raw = match.groups()
        if key in values:
            raise HandoffError(f"{label} repeats frontmatter field: {key}")
        raw = _strip_yaml_comment(raw)
        inline = INLINE_LIST_PATTERN.fullmatch(raw)
        if inline is not None:
            values[key] = [
                _strip_quotes(item)
                for item in inline.group("body").split(",")
                if item.strip()
            ]
            index += 1
            continue
        if raw:
            values[key] = _strip_quotes(raw)
            index += 1
            continue
        items: List[str] = []
        index += 1
        while index < len(lines):
            item = LIST_ITEM_PATTERN.fullmatch(lines[index])
            if item is None:
                break
            items.append(_strip_quotes(_strip_yaml_comment(item.group("value"))))
            index += 1
        values[key] = items
    raise HandoffError(f"{label} frontmatter is not closed")


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if not path.is_file() or path.is_symlink():
        raise HandoffError(f"missing real hand-off file: {relative}")
    return path.read_text(encoding="utf-8")


def _require_pipeline(root: Path, project_dir: str) -> Dict[str, str]:
    try:
        state, _text, _path = load_state(root.resolve(), project_dir)
    except PipelineStateError as error:
        raise HandoffError(str(error)) from error
    return {
        key: "null" if value is None else value
        for key, value in state.json().items()
    }


def _require_state(root: Path, phase: str, status: str, project_dir: str) -> None:
    values = _require_pipeline(root, project_dir)
    if values.get("phase") != phase or values.get("status") != status:
        raise HandoffError(
            f"STATE.md must be {phase}/{status}, found "
            f"{values.get('phase', '<missing>')}/{values.get('status', '<missing>')}"
        )


def _require_state_one_of(
    root: Path,
    expected: Set[Tuple[str, str]],
    project_dir: str,
) -> None:
    values = _require_pipeline(root, project_dir)
    actual = (values["phase"], values["status"])
    if actual not in expected:
        rendered = ", ".join(f"{phase}/{status}" for phase, status in sorted(expected))
        raise HandoffError(
            f"STATE.md must be one of {rendered}, found {actual[0]}/{actual[1]}"
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
    body = _common.section_body(text, heading)
    if body is None:
        raise HandoffError(f"missing ## {heading} section")
    return body


def _non_placeholder(value: str, label: str) -> str:
    cleaned = value.strip().strip("`")
    if not cleaned or cleaned.casefold() in {"none", "n/a", "null"}:
        raise HandoffError(f"{label} is empty")
    _reject_placeholder(cleaned, label)
    return cleaned


def _unquoted(value: str) -> str:
    cleaned = value.strip()
    while (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in "`\"'"
    ):
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _surface_value(value: str, label: str) -> str:
    cleaned = _unquoted(value)
    if not cleaned or cleaned.casefold() in {"none", "n/a", "null"}:
        raise HandoffError(f"{label} is empty")
    if re.fullmatch(r"<[^<>]*>", cleaned):
        raise HandoffError(f"{label} is still a placeholder")
    return cleaned


def _evidence_field(text: str, field: str, relative: str) -> str:
    matches = re.findall(
        rf"(?m)^- \*\*{re.escape(field)}\*\*:\s*(.*)$", text
    )
    if len(matches) != 1:
        raise HandoffError(
            f"{relative} finding must contain exactly one {field} field"
        )
    return _non_placeholder(matches[0], f"{relative} finding {field}")


def _validate_evidence(
    root: Path,
    relative: str,
    dimension: str,
    assigned_questions: Sequence[str],
) -> None:
    text = _read(root, relative)
    if len(re.findall(rf"(?m)^# Evidence — {re.escape(dimension)}\s*$", text)) != 1:
        raise HandoffError(f"{relative} must name evidence dimension {dimension}")
    dimension_values = re.findall(r"(?m)^Dimension:\s*(.*)$", text)
    if len(dimension_values) != 1 or _non_placeholder(
        dimension_values[0], f"{relative} Dimension"
    ) != dimension:
        raise HandoffError(f"{relative} Dimension must be {dimension}")
    question_values = re.findall(r"(?m)^Questions assigned:\s*(.*)$", text)
    expected_questions = "; ".join(assigned_questions) if assigned_questions else "none"
    if len(question_values) != 1 or question_values[0].strip() != expected_questions:
        raise HandoffError(
            f"{relative} Questions assigned must be {expected_questions!r}"
        )

    headings = list(re.finditer(r"(?m)^## (?P<title>.+?)\s*$", text))
    findings = []
    for index, heading in enumerate(headings):
        title = heading.group("title")
        if not title.startswith("Finding"):
            continue
        if not title.startswith("Finding: "):
            raise HandoffError(f"{relative} has a malformed Finding heading")
        _non_placeholder(title[len("Finding: ") :], f"{relative} finding heading")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        findings.append(text[heading.end() : end])
    if not findings:
        raise HandoffError(f"{relative} has no findings")
    for finding in findings:
        _evidence_field(finding, "Claim", relative)
        _evidence_field(finding, "Source", relative)
        confidence = _evidence_field(finding, "Confidence", relative)
        if confidence not in {"high", "medium", "low"}:
            raise HandoffError(f"{relative} finding has invalid Confidence: {confidence}")
        _evidence_field(finding, "Why it matters here", relative)

    answer_headings = [
        (index, heading)
        for index, heading in enumerate(headings)
        if heading.group("title") == "Assigned questions — answers"
    ]
    if len(answer_headings) != 1:
        raise HandoffError(
            f"{relative} must contain one ## Assigned questions — answers section"
        )
    index, heading = answer_headings[0]
    end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
    answer_lines = [line.strip() for line in text[heading.end() : end].splitlines() if line.strip()]
    if not assigned_questions:
        if answer_lines != ["- none"]:
            raise HandoffError(f"{relative} must record no assigned-question answers")
        return
    answers = []
    for line in answer_lines:
        match = re.fullmatch(r"- (?P<question>.+?) → (?P<answer>.+)", line)
        if match is None:
            raise HandoffError(f"{relative} has a malformed assigned-question answer")
        question = match.group("question").strip()
        answer = _non_placeholder(
            match.group("answer"), f"{relative} answer for {question}"
        )
        answers.append((question, answer))
    if [question for question, _answer in answers] != list(assigned_questions):
        raise HandoffError(
            f"{relative} assigned-question answers do not match RESEARCH.md"
        )


def _research_questions(intent: str) -> List[str]:
    return [
        match.group(1).strip()
        for match in re.finditer(r"(?m)^\s*- \[RESEARCH\] (.+?)\s*$", intent)
    ]


def _research_assignments(section: str) -> List[Tuple[str, str]]:
    assignments = []
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    if lines == ["- none"]:
        return assignments
    for line in lines:
        if line == "- none":
            raise HandoffError("RESEARCH.md mixes none with question assignments")
        match = QUESTION_PATTERN.fullmatch(line)
        if match is None:
            raise HandoffError("RESEARCH.md has a malformed question assignment")
        assignments.append((match.group("question").strip(), match.group("dimension")))
    return assignments


def validate_research(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate the research-to-synthesis hand-off and return its summary."""

    _require_state(root, "research", "active", project_dir)
    return validate_research_artifacts(root, project_dir)


def validate_research_artifacts(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Check research contents independently of the caller's state edge."""
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
    evidence_outputs: Dict[str, str] = {}
    for dimension, status, output, _reason in dispatch_rows:
        if status == "dispatched":
            expected = f"{project_dir}/research/evidence-{dimension}.md"
            if output != expected:
                raise HandoffError(
                    f"{dimension} output must be {expected}, found {output}"
                )
            evidence_outputs[dimension] = output
            dispatched.append(dimension)
        else:
            if output.casefold() != "none":
                raise HandoffError(f"skipped {dimension} must not name an output")
            skipped.append(dimension)

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
    for dimension in dispatched:
        dimension_questions = [
            question
            for question, assigned_dimension in assignments
            if assigned_dimension == dimension
        ]
        if not dimension_questions:
            raise HandoffError(f"dispatched {dimension} has no assigned research question")
        _validate_evidence(
            root,
            evidence_outputs[dimension],
            dimension,
            dimension_questions,
        )

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


def _raw_source_field(block: str, field: str, source: str) -> str:
    matches = re.findall(rf"(?m)^- \*\*{re.escape(field)}\*\*:\s*(.*)$", block)
    if not matches:
        raise HandoffError(f"{source} is missing {field}")
    if len(matches) != 1:
        raise HandoffError(f"{source} repeats {field}")
    return matches[0]


def _source_field(block: str, field: str, source: str) -> str:
    value = _raw_source_field(block, field, source).strip().strip("`")
    if not value:
        raise HandoffError(f"{source} has an empty {field}; fill it in")
    _reject_placeholder(value, f"{source} {field}")
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
    if len(re.findall(r"(?m)^Reviewed HEAD:", text)) > 1:
        raise HandoffError(f"{source} repeats Reviewed HEAD")
    value = _line_value(text, "Reviewed HEAD:")
    if not SHA_PATTERN.fullmatch(value):
        raise HandoffError(
            f"{source} Reviewed HEAD must be the full 40-character commit SHA "
            f"from git rev-parse HEAD, not {value or 'empty'}"
        )
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


def _surfaces(text: str, label: str) -> List[str]:
    """Human-facing surfaces one milestone delivers; empty when `none`."""

    matches = re.findall(
        r"(?m)^Surfaces:\s*([^#]*?)(?:\s+#.*)?$", _strip_comments(text)
    )
    if not matches:
        raise HandoffError(f"{label} is missing Surfaces")
    if len(matches) != 1:
        raise HandoffError(f"{label} repeats Surfaces")
    value = _unquoted(matches[0])
    if value.casefold() == "none":
        return []
    _non_placeholder(value, f"{label} Surfaces")
    named: List[str] = []
    seen = set()
    for item in value.split(","):
        if not item.strip():
            continue
        surface = _unquoted(item)
        if surface.casefold() == "none":
            raise HandoffError(f"{label} Surfaces includes reserved value {surface}")
        _non_placeholder(surface, f"{label} Surfaces")
        key = surface.casefold()
        if key in seen:
            raise HandoffError(f"{label} Surfaces repeats {surface}")
        seen.add(key)
        named.append(surface)
    if not named:
        raise HandoffError(f"{label} Surfaces names no surface and is not none")
    return named


def _surface_keys(surfaces: Sequence[str]) -> List[str]:
    return sorted(surface.casefold() for surface in surfaces)


def _roadmap_surfaces(root: Path, milestone: str) -> Optional[List[str]]:
    """Surfaces the program roadmap declares for one milestone, when it has an entry."""

    # The program roadmap always lives at `.project/`; a lookahead track reads
    # program inputs from there, not from its own root.
    relative = f"{DEFAULT_PROJECT_DIR}/ROADMAP.md"
    if not (root / relative).is_file():
        return None
    matches = [
        block
        for _entry, slug, block, _raw in _milestone_blocks(_read(root, relative))
        if slug == milestone
    ]
    if not matches:
        raise HandoffError(f"ROADMAP.md is missing milestone slug {milestone}")
    if len(matches) > 1:
        raise HandoffError(f"ROADMAP.md repeats milestone slug {milestone}")
    return _surfaces(matches[0], f"ROADMAP.md {milestone}")


def _criterion_ids(value: str, label: str) -> List[str]:
    ids = [item.strip().strip("`") for item in value.split(",") if item.strip()]
    if not ids or any(not CRITERION_LOCATOR_PATTERN.fullmatch(item) for item in ids):
        raise HandoffError(f"{label} Criteria must name success criteria: {value}")
    if len(ids) != len(set(ids)):
        raise HandoffError(f"{label} Criteria repeats an id")
    return ids


def _surface_contract(
    plan: str, surfaces: Sequence[str]
) -> Dict[str, Tuple[str, List[str]]]:
    """Map each declared surface to the task that delivers it and its criteria."""

    if len(SURFACE_CONTRACT_HEADING.findall(plan)) > 1:
        raise HandoffError("PLAN.md repeats ## Surface contract")
    body = _strip_comments(_section(plan, "Surface contract"))
    headings = list(SURFACE_HEADING.finditer(body))
    if not surfaces:
        names = ", ".join(heading.group("surface") for heading in headings)
        if names:
            raise HandoffError(
                f"Surface contract names {names}, but INTENT.md declares no surfaces"
            )
        raise HandoffError(
            "PLAN.md has ## Surface contract but INTENT.md declares no surfaces"
        )
    blocks: Dict[str, Tuple[str, str]] = {}
    for heading in headings:
        heading_surface = heading.group("surface")
        key = heading_surface.casefold()
        if key in blocks:
            raise HandoffError(
                f"Surface contract repeats the {heading_surface} surface"
            )
        blocks[key] = (
            heading.group("task"),
            _heading_block(body, heading),
        )
    owners: Dict[str, Tuple[str, List[str]]] = {}
    surface_by_criterion: Dict[str, str] = {}
    for surface in surfaces:
        key = surface.casefold()
        if key not in blocks:
            raise HandoffError(f"Surface contract is missing the {surface} surface")
        task_id, block = blocks.pop(key)
        label = f"{surface} surface"
        for field in ("Entry", "States"):
            # Read the whole line: `#` is legal inside a route or a command.
            values = re.findall(rf"(?m)^{re.escape(field)}:\s*(.*)$", block)
            if len(values) > 1:
                raise HandoffError(f"{label} repeats {field}")
            if not values:
                raise HandoffError(f"missing {field}:")
            _surface_value(values[0], f"{label} {field}")
        walkthrough = _numbered_items(
            _roadmap_segment(block, "Walkthrough:", None, label)
        )
        if not walkthrough:
            raise HandoffError(f"{label} Walkthrough has no steps")
        for number, step in walkthrough.items():
            _surface_value(step, f"{label} Walkthrough step {number}")
        if len(re.findall(r"(?m)^Criteria:", block)) > 1:
            raise HandoffError(f"{label} repeats Criteria")
        criteria = _criterion_ids(_roadmap_field(block, "Criteria", label), label)
        for criterion in criteria:
            previous_surface = surface_by_criterion.get(criterion)
            if previous_surface is not None:
                raise HandoffError(
                    f"Surface contract {criterion} is shared by surfaces "
                    f"{previous_surface} and {surface}"
                )
            surface_by_criterion[criterion] = surface
        owners[surface] = (task_id, criteria)
    if blocks:
        raise HandoffError(
            "Surface contract names undeclared surfaces: "
            + ", ".join(sorted(blocks))
        )
    return owners


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
    for path in sorted(tasks_dir.iterdir()):
        named = TASK_FILE_NAME.fullmatch(path.name)
        if named is None or not path.is_file() or path.is_symlink():
            raise HandoffError(f"non-canonical task artifact: {path.name}")
        text = path.read_text(encoding="utf-8")
        task_id = _strict_frontmatter(text, path.name).get("id")
        if not isinstance(task_id, str) or not re.fullmatch(r"T\d{3}", task_id):
            raise HandoffError(f"{path.name} is missing an id")
        if named.group("id") != task_id:
            raise HandoffError(f"{path.name} does not match task id {task_id}")
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


def _frontmatter_files(task_text: str) -> List[str]:
    values = _strict_frontmatter(task_text, "task")
    raw = values.get("files")
    if raw is None:
        raise HandoffError("task is missing files")
    files = raw if isinstance(raw, list) else [raw]
    return [_canonical_repo_path(str(path), "task files") for path in files]


def _posix_path(value: str) -> str:
    stripped = value.strip().strip("/")
    if not stripped:
        return ""
    return str(PurePosixPath(stripped))


def _verify_mentions_a_file(command: str, files: Sequence[str]) -> bool:
    tokens: List[str] = []
    for raw in command.split():
        for piece in VERIFY_PATH_SPLIT.split(raw.strip("\"'")):
            normalized = _posix_path(piece)
            if normalized and normalized != ".":
                tokens.append(normalized)
    for path in files:
        needle = _posix_path(path)
        if not needle or needle == ".":
            continue
        for token in tokens:
            if token == needle or token.startswith(needle + "/"):
                return True
    return False


def _acceptance_items(task_text: str, task_id: str) -> Dict[int, str]:
    items = _numbered_items(_section(task_text, "Acceptance criteria"))
    if not items:
        raise HandoffError(f"{task_id} has no acceptance criteria")
    return items


def _task_wave(task_text: str, task_id: str) -> int:
    value = _task_scalar(task_text, task_id, "wave")
    if not value.isdigit() or int(value) < 1:
        raise HandoffError(f"{task_id} is missing a wave")
    return int(value)


def _task_scalar(task_text: str, task_id: str, field: str) -> str:
    value = _strict_frontmatter(task_text, task_id).get(field)
    if value is None:
        raise HandoffError(f"{task_id} is missing {field}")
    if not isinstance(value, str):
        raise HandoffError(f"{task_id} {field} must be a scalar")
    return value


def _inline_ids(value: str, prefix: str, label: str) -> List[str]:
    cleaned = value.strip().strip("`")
    if cleaned in {"", "—", "-", "[]"} or cleaned.casefold() == "none":
        return []
    inline = INLINE_LIST_PATTERN.fullmatch(cleaned)
    if inline:
        cleaned = inline.group("body")
    values = [item.strip().strip("`\"'") for item in cleaned.split(",")]
    pattern = re.compile(rf"^{re.escape(prefix)}\d{{3}}$")
    if not values or any(not pattern.fullmatch(item) for item in values):
        raise HandoffError(f"{label} has an invalid id list: {value}")
    if len(values) != len(set(values)):
        raise HandoffError(f"{label} repeats an id")
    return values


def _task_deps(task_text: str, task_id: str) -> List[str]:
    value = _strict_frontmatter(task_text, task_id).get("deps")
    if value is None:
        raise HandoffError(f"{task_id} is missing deps")
    if isinstance(value, list):
        rendered = ",".join(str(item) for item in value)
    else:
        rendered = str(value)
    return _inline_ids(rendered, "T", f"{task_id} deps")


def _canonical_repo_path(value: str, label: str) -> str:
    cleaned = value.strip().strip("`\"'")
    path = PurePosixPath(cleaned)
    if (
        not cleaned
        or cleaned == "."
        or "\\" in cleaned
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != cleaned
    ):
        raise HandoffError(f"{label} has an unsafe or non-canonical path: {value}")
    return cleaned


def _plan_files(value: str, task_id: str) -> List[str]:
    cleaned = value.strip().strip("`")
    files = [
        item.strip().strip("`\"'")
        for item in re.split(r"\s*(?:,|<br\s*/?>)\s*", cleaned)
        if item.strip()
    ]
    if not files or any("<" in item or ">" in item for item in files):
        raise HandoffError(f"PLAN.md {task_id} has an invalid Files cell")
    files = [
        _canonical_repo_path(item, f"PLAN.md {task_id} Files") for item in files
    ]
    if len(files) != len(set(files)):
        raise HandoffError(f"PLAN.md {task_id} repeats a file")
    return files


def _plan_waves(plan: str) -> Tuple[Dict[int, str], List[int]]:
    headings = list(PLAN_WAVE_HEADING.finditer(plan))
    if not headings:
        raise HandoffError("PLAN.md has no waves")
    waves = [int(heading.group("wave")) for heading in headings]
    if waves != list(range(1, len(waves) + 1)):
        raise HandoffError("PLAN.md wave numbers must be unique, ordered, and contiguous")

    depths: Dict[int, str] = {}
    for index, heading in enumerate(headings):
        wave = int(heading.group("wave"))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(plan)
        block = plan[heading.end() : end]
        goal = re.search(r"(?m)^Goal:\s*(.+)$", block)
        depth = re.search(r"(?m)^Review depth:\s*(\S+)", block)
        if not goal:
            raise HandoffError(f"PLAN.md Wave {wave} is missing Goal")
        _non_placeholder(goal.group(1), f"PLAN.md Wave {wave} Goal")
        if not depth or depth.group(1) not in {"full", "deep", "verify-only"}:
            raise HandoffError(f"PLAN.md Wave {wave} has an invalid Review depth")
        if wave == 1 and depth.group(1) == "verify-only":
            raise HandoffError("PLAN.md Wave 1 Review depth must be full or deep")
        depths[wave] = depth.group(1)
    return depths, waves


def _require_task_structure(task_id: str, text: str, *, initial: bool) -> None:
    expected = {
        "status": "pending",
        "agent": "null",
        "base": "null",
        "worktree": "null",
        "task_branch": "null",
    }
    for field, value in expected.items():
        actual = _task_scalar(text, task_id, field)
        if initial and actual != value:
            raise HandoffError(f"{task_id} {field} must initially be {value}")
    for heading in ("Context", "Approach", "Interface contract", "Log"):
        body = _strip_comments(_section(text, heading)).strip()
        if not body:
            raise HandoffError(f"{task_id} {heading} is empty or still a placeholder")
        _reject_placeholder(body, f"{task_id} {heading}")


def _validate_task_graph(
    wave_depths: Dict[int, str], tasks: Dict[str, str], *, initial: bool
) -> None:
    task_ids = list(tasks)
    expected = [f"T{number:03d}" for number in range(1, len(task_ids) + 1)]
    if task_ids != expected:
        raise HandoffError("task ids must be unique, ordered, and contiguous")

    graph: Dict[str, List[str]] = {}
    task_waves: Dict[str, int] = {}
    task_files: Dict[str, List[str]] = {}
    for task_id, text in tasks.items():
        _require_task_structure(task_id, text, initial=initial)
        wave = _task_wave(text, task_id)
        deps = _task_deps(text, task_id)
        files = _frontmatter_files(text)
        if wave not in wave_depths:
            raise HandoffError(f"{task_id} names unknown Wave {wave}")
        graph[task_id] = deps
        task_waves[task_id] = wave
        task_files[task_id] = files
        for dependency in deps:
            if dependency not in tasks:
                raise HandoffError(f"{task_id} names unknown dependency {dependency}")
            if _task_wave(tasks[dependency], dependency) > wave:
                raise HandoffError(f"{task_id} depends on later-wave {dependency}")

    for index, left in enumerate(task_ids):
        for right in task_ids[index + 1 :]:
            if task_waves[left] != task_waves[right]:
                continue
            overlap = sorted(set(task_files[left]) & set(task_files[right]))
            if overlap:
                raise HandoffError(
                    f"same-wave file overlap between {left} and {right}: {', '.join(overlap)}"
                )

    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            raise HandoffError(f"dependency cycle includes {task_id}")
        if task_id in visited:
            return
        visiting.add(task_id)
        for dependency in graph[task_id]:
            visit(dependency)
        visiting.remove(task_id)
        visited.add(task_id)

    for task_id in graph:
        visit(task_id)


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


def _named_field(block: str, field: str, label: str) -> str:
    match = re.search(rf"(?m)^- \*\*{re.escape(field)}\*\*:\s*(.+)$", block)
    if not match:
        raise HandoffError(f"{label} is missing {field}")
    return _non_placeholder(match.group(1), f"{label} {field}")


def validate_decide(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate the structural synthesis contract without judging decisions."""

    _require_state(root, "decide", "active", project_dir)
    return validate_decide_artifacts(root, project_dir)


def validate_decide_artifacts(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Check synthesis contents independently of the caller's state edge."""
    program_scope = (
        project_dir == DEFAULT_PROJECT_DIR
        and (root / project_dir / "CHARTER.md").is_file()
        and not (root / project_dir / "ROADMAP.md").exists()
    )
    relative = (
        f"{project_dir}/SYNTHESIS.md"
        if program_scope
        else f"{project_dir}/research/SYNTHESIS.md"
    )
    text = _read(root, relative)
    for heading in ("Settled", "Decisions", "For the planner", "User rulings", "Still unknown"):
        _section(text, heading)

    decision_section = _strip_comments(_section(text, "Decisions"))
    headings = list(re.finditer(r"(?m)^### (.+?)\s*$", decision_section))
    decisions: List[str] = []
    if not headings and not re.search(r"(?m)^- None\s*$", decision_section):
        raise HandoffError("SYNTHESIS.md Decisions must contain decision blocks or - None")
    for index, heading in enumerate(headings):
        title = _non_placeholder(heading.group(1), "SYNTHESIS.md decision heading")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(decision_section)
        block = decision_section[heading.end() : end]
        label = f"SYNTHESIS.md decision {title}"
        _named_field(block, "Decision", label)
        _named_field(block, "Runner-up", label)
        _named_field(block, "Evidence", label)
        confidence = _named_field(block, "Confidence", label).split("—", 1)[0].strip()
        if confidence not in {"high", "medium", "low"}:
            raise HandoffError(f"{label} Confidence is invalid")
        decisions.append(title)

    planner = _section(text, "For the planner")
    for field in ("Wave-1 blockers", "Walking skeleton", "Pitfalls → tasks"):
        _named_field(planner, field, "SYNTHESIS.md For the planner")
    if re.search(r"<[^>\n]+>", _strip_comments(text)):
        raise HandoffError("SYNTHESIS.md still contains a placeholder")
    return {"phase": "decide", "synthesis": relative, "decisions": decisions}


def _roadmap_field(
    block: str,
    field: str,
    milestone: str,
    *,
    allow_null: bool = False,
    allow_none: bool = False,
) -> str:
    match = re.search(rf"(?m)^{re.escape(field)}:\s*([^#]*?)(?:\s+#.*)?$", block)
    if not match:
        raise HandoffError(f"{milestone} is missing {field}")
    value = match.group(1).strip().strip("`\"'")
    if allow_null and value == "null":
        return value
    if allow_none and value.casefold() == "none":
        return value
    return _non_placeholder(value, f"{milestone} {field}")


def _roadmap_segment(block: str, start: str, end: Optional[str], milestone: str) -> str:
    terminator = rf"(?=^{re.escape(end)}\s*$)" if end else r"\Z"
    match = re.search(
        rf"(?ms)^{re.escape(start)}\s*$\n(?P<body>.*?){terminator}", block
    )
    if not match:
        raise HandoffError(f"{milestone} is missing {start}")
    return match.group("body")


def _roadmap_bullets(body: str, label: str, *, allow_none: bool) -> List[str]:
    values = [
        line.strip()[2:].strip()
        for line in body.splitlines()
        if line.strip().startswith("- ")
    ]
    if not values:
        raise HandoffError(f"{label} has no entries")
    for value in values:
        if "<" in value or ">" in value or (not allow_none and value.casefold() == "none"):
            raise HandoffError(f"{label} has an empty or placeholder entry")
    return values


def _milestone_blocks(text: str) -> List[Tuple[str, str, str, str]]:
    section = _section(text, "Milestones")
    searchable = COMMENT_PATTERN.sub(
        lambda match: re.sub(r"[^\n]", " ", match.group(0)),
        section,
    )
    headings = list(MILESTONE_HEADING.finditer(searchable))
    if not headings:
        raise HandoffError("ROADMAP.md has no milestones")
    blocks = []
    for index, heading in enumerate(headings):
        end = headings[index + 1].start() if index + 1 < len(headings) else len(section)
        blocks.append(
            (
                heading.group("id"),
                _non_placeholder(heading.group("slug"), f"{heading.group('id')} slug"),
                section[heading.end() : end],
                section[heading.start() : end],
            )
        )
    return blocks


def _head_file(root: Path, relative: str) -> Optional[str]:
    result = subprocess.run(
        ["git", "show", f"HEAD:{relative}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.stdout if result.returncode == 0 else None


def _without_roadmap_mutable_fields(block: str) -> str:
    return re.sub(r"(?m)^(?:Status|Archive|Integrated):.*\n?", "", block).strip()


def validate_roadmap(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate roadmap structure and dependency ordering."""

    _require_state(root, "roadmap", "active", project_dir)
    relative = f"{project_dir}/ROADMAP.md"
    text = _read(root, relative)
    if re.search(r"(?m)^## Wave |^\|\s*Task\s*\||^Files:\s*", text):
        raise HandoffError("ROADMAP.md must not contain waves, tasks, or file lists")
    if re.search(r"<[^>\n]+>", _strip_comments(text)):
        raise HandoffError("ROADMAP.md still contains a placeholder")

    blocks = _milestone_blocks(text)
    ids = [milestone for milestone, _, _, _ in blocks]
    expected = [f"M{number:03d}" for number in range(1, len(ids) + 1)]
    if ids != expected:
        raise HandoffError("ROADMAP.md milestone ids must be unique, ordered, and contiguous")

    dependencies: Dict[str, List[str]] = {}
    raw_by_id: Dict[str, str] = {}
    for index, (milestone, _slug, block, raw) in enumerate(blocks):
        raw_by_id[milestone] = raw
        _roadmap_field(block, "Goal", milestone)
        deps = _inline_ids(
            _roadmap_field(block, "Depends on", milestone),
            "M",
            f"{milestone} Depends on",
        )
        earlier = set(ids[:index])
        invalid = [dependency for dependency in deps if dependency not in earlier]
        if invalid:
            raise HandoffError(
                f"{milestone} dependencies must name earlier milestones: {', '.join(invalid)}"
            )
        dependencies[milestone] = deps
        status = _roadmap_field(block, "Status", milestone)
        if status not in {"pending", "active", "shipped", "abandoned"}:
            raise HandoffError(f"{milestone} Status is invalid")
        if status in {"pending", "active"}:
            _surfaces(block, milestone)
        _roadmap_field(block, "Archive", milestone, allow_null=True)
        _roadmap_field(block, "Integrated", milestone, allow_null=True)
        _roadmap_bullets(
            _roadmap_segment(block, "Scope: in", "Scope: out", milestone),
            f"{milestone} Scope: in",
            allow_none=False,
        )
        _roadmap_bullets(
            _roadmap_segment(block, "Scope: out", "Success criteria", milestone),
            f"{milestone} Scope: out",
            allow_none=True,
        )
        criteria = _numbered_items(
            _roadmap_segment(block, "Success criteria", "Risks", milestone)
        )
        if not criteria or sorted(criteria) != list(range(1, len(criteria) + 1)):
            raise HandoffError(f"{milestone} Success criteria must be contiguous from 1")
        _roadmap_bullets(
            _roadmap_segment(block, "Risks", "Open questions", milestone),
            f"{milestone} Risks",
            allow_none=False,
        )
        _roadmap_bullets(
            _roadmap_segment(block, "Open questions", None, milestone),
            f"{milestone} Open questions",
            allow_none=True,
        )

    previous = _head_file(root, relative)
    if previous and previous != text:
        previous_blocks = {
            milestone: raw
            for milestone, _slug, _block, raw in _milestone_blocks(previous)
        }
        for milestone, old_block in previous_blocks.items():
            status = _roadmap_field(old_block, "Status", milestone)
            if milestone not in raw_by_id:
                raise HandoffError(f"ROADMAP.md removed existing {milestone}")
            new_block = raw_by_id[milestone]
            if status == "abandoned" and new_block != old_block:
                raise HandoffError(f"ROADMAP.md changed abandoned {milestone}")
            shipped_changed = _without_roadmap_mutable_fields(
                new_block
            ) != _without_roadmap_mutable_fields(old_block)
            if status == "shipped" and shipped_changed:
                raise HandoffError(f"ROADMAP.md changed immutable content in shipped {milestone}")

    return {"phase": "roadmap", "milestones": ids, "dependencies": dependencies}


def validate_plan(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Validate INTENT success criteria against PLAN.md coverage and tasks."""

    _require_state_one_of(
        root,
        {("plan", "active"), ("build", "active")},
        project_dir,
    )
    intent = _read(root, _intent_path(project_dir))
    plan = _read(root, f"{project_dir}/plan/PLAN.md")
    criteria = _success_criteria(intent)
    rows = _coverage_rows(plan)
    tasks = _task_texts(root, project_dir)
    wave_depths, waves = _plan_waves(plan)
    # Build readiness owns task lifecycle validation; coverage must survive landings.
    state = _require_pipeline(root, project_dir)
    _validate_task_graph(wave_depths, tasks, initial=state["phase"] == "plan")
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
    surfaces = _surfaces(intent, "INTENT.md")
    milestone = state.get("milestone", "null")
    if milestone != "null":
        declared = _roadmap_surfaces(root, milestone)
        if declared is not None and _surface_keys(declared) != _surface_keys(surfaces):
            raise HandoffError(
                f"INTENT.md Surfaces do not match ROADMAP.md {milestone}"
            )
    owners = (
        _surface_contract(plan, surfaces)
        if surfaces or SURFACE_CONTRACT_HEADING.search(plan)
        else {}
    )
    for surface, (task_id, owned_criteria) in owners.items():
        if task_id not in tasks:
            raise HandoffError(f"{surface} surface names unknown {task_id}")
        unowned = [
            criterion
            for criterion in owned_criteria
            if criterion not in assigned[task_id]
        ]
        if unowned:
            raise HandoffError(
                f"{surface} surface criteria are not owned by {task_id}: "
                + ", ".join(unowned)
            )
    project_verify = _normalize_ws(_line_value(plan, "Project verify:"))
    for task_id, text in tasks.items():
        command = _verify_command(text)
        if not command:
            continue
        if command == project_verify:
            named = any(
                project_verify in _normalize_ws(criteria[sc_id])
                for sc_id in assigned[task_id]
                if sc_id in criteria
            )
            if not named:
                raise HandoffError(f"{task_id} Verify must not copy Project verify")
            continue
        if not _verify_mentions_a_file(command, _frontmatter_files(text)):
            raise HandoffError(f"{task_id} Verify must name a path from files")
    return {
        "phase": "plan",
        "criteria": sorted(criteria),
        "rows": len(rows),
        "tasks": len(tasks),
        "waves": waves,
        "surfaces": {surface: task for surface, (task, _) in owners.items()},
    }


def validate_wave(
    root: Path,
    project_dir: str = DEFAULT_PROJECT_DIR,
    review: str = "",
) -> Dict[str, object]:
    """Validate one canonical wave review and its owned INTENT verdicts."""

    _require_state(root, "build", "active", project_dir)
    return validate_wave_evidence(root, project_dir, review)


def validate_wave_evidence(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR, review: str = ""
) -> Dict[str, object]:
    """Check a wave artifact independently of the caller's current phase."""

    if not review:
        raise HandoffError("wave validation requires --review")
    review_path = PurePosixPath(review)
    name = review_path.name
    named = WAVE_REVIEW_NAME.fullmatch(name)
    if not named:
        raise HandoffError(f"unrecognized wave review file: {name}")
    expected_review = PurePosixPath(project_dir) / "review" / name
    if review_path.is_absolute() or ".." in review_path.parts or review_path != expected_review:
        raise HandoffError(
            f"wave review must be the canonical path {expected_review.as_posix()}"
        )
    wave = int(named.group("wave"))
    cycle = int(named.group("cycle"))
    lens = named.group("lens")
    intent = _read(root, _intent_path(project_dir))
    criteria = _success_criteria(intent)
    plan = _read(root, f"{project_dir}/plan/PLAN.md")
    rows = _coverage_rows(plan)
    wave_depths, _waves = _plan_waves(plan)
    tasks = _task_texts(root, project_dir)
    expected_tasks = [
        task_id
        for task_id, task_text in tasks.items()
        if _task_wave(task_text, task_id) == wave
    ]
    if not expected_tasks:
        raise HandoffError(f"PLAN.md has no Wave {wave} tasks")
    if wave not in wave_depths:
        raise HandoffError(f"PLAN.md has no Wave {wave}")
    expected_depth = wave_depths[wave]
    if lens is None and expected_depth == "deep":
        raise HandoffError(f"{name} must name its contract or adversarial lens")
    if lens is not None and expected_depth != "deep":
        raise HandoffError(f"{name} has a lens but PLAN.md depth is {expected_depth}")

    assigned: Dict[str, Set[str]] = {task_id: set() for task_id in tasks}
    for criterion, task_id, _acceptance in rows:
        if task_id in assigned and criterion in criteria:
            assigned[task_id].add(criterion)
    owned = _owned_by_wave(tasks, assigned, wave)
    text = _read(root, review_path.as_posix())
    if _line_value(text, "Cycle:") != str(cycle):
        raise HandoffError(f"{name} Cycle field does not match its filename")
    if _line_value(text, "Depth:") != expected_depth:
        raise HandoffError(f"{name} Depth does not match PLAN.md")
    lens_fields = re.findall(r"(?m)^Lens:\s*(\S.*?)\s*$", text)
    if lens is None and lens_fields:
        raise HandoffError(f"{name} must not declare a review lens")
    if lens is not None and lens_fields != [lens]:
        raise HandoffError(f"{name} Lens field does not match its filename")
    reviewed = _line_value(text, "Tasks reviewed:")
    if not reviewed.isdigit() or int(reviewed) != len(expected_tasks):
        raise HandoffError(f"{name} Tasks reviewed does not match Wave {wave}")

    lines = text.splitlines()
    task_headings = []
    for index, line in enumerate(lines):
        match = WAVE_TASK_HEADING.fullmatch(line)
        if match:
            task_headings.append((index, match))
    reviewed_tasks = [match.group("task") for _, match in task_headings]
    if reviewed_tasks != expected_tasks:
        raise HandoffError(
            f"{name} must review exactly {', '.join(expected_tasks)} in plan order"
        )
    task_verdicts = []
    for heading_index, heading in task_headings:
        task_id = heading.group("task")
        expected_title = _normalize_ws(_task_scalar(tasks[task_id], task_id, "title"))
        if _normalize_ws(heading.group("title")) != expected_title:
            raise HandoffError(f"{name} title for {task_id} differs from task file")
        end = next(
            (
                index
                for index in range(heading_index + 1, len(lines))
                if lines[index].startswith("## ")
            ),
            len(lines),
        )
        verdict = heading.group("verdict")
        marker = "✅" if verdict == "pass" else "❌"
        evidence = [
            line.strip()[len(f"- {marker} ") :]
            for line in lines[heading_index + 1 : end]
            if line.strip().startswith(f"- {marker} ")
        ]
        if not evidence:
            raise HandoffError(f"{name} task {task_id} lacks {verdict} evidence")
        for item in evidence:
            _non_placeholder(item, f"{name} task {task_id} {verdict} evidence")
        task_verdicts.append(verdict)

    overall = _line_value(text, "Wave verdict:")
    if overall not in {"pass", "blocked"}:
        raise HandoffError(f"{name} Wave verdict is invalid")
    if overall == "pass" and "fail" in task_verdicts:
        raise HandoffError(f"{name} Wave verdict is pass while a task failed")
    try:
        coverage = _section(text, "Intent coverage")
    except HandoffError:
        coverage = None
    if not owned:
        if coverage is not None and WAVE_SC_HEADING.search(_strip_comments(coverage)):
            raise HandoffError(f"{name} Intent coverage names SCs this wave does not own")
        return {
            "phase": "wave",
            "wave": wave,
            "cycle": cycle,
            "owned": [],
            "review": review,
            "verdict": overall,
        }
    if coverage is None:
        raise HandoffError(f"{name} is missing ## Intent coverage")
    verdicts: Dict[str, str] = {}
    coverage_lines = _strip_comments(coverage).splitlines()
    sc_headings = [
        (index, match)
        for index, line in enumerate(coverage_lines)
        if (match := WAVE_SC_HEADING.fullmatch(line.strip())) is not None
    ]
    for position, (heading_index, match) in enumerate(sc_headings):
        sc_id = match.group(1)
        heading_text, separator, verdict = match.group(2).rpartition(":")
        verdict = verdict.strip()
        if verdict not in {"pass", "fail"}:
            raise HandoffError(f"{name} {sc_id} heading must end with `: pass` or `: fail`")
        if (
            sc_id in criteria
            and (
                not separator
                or _normalize_ws(heading_text) != _normalize_ws(criteria[sc_id])
            )
        ):
            raise HandoffError(f"{name} {sc_id} heading text differs from INTENT.md")
        if sc_id in verdicts:
            raise HandoffError(f"{name} Intent coverage repeats {sc_id}")
        end = (
            sc_headings[position + 1][0]
            if position + 1 < len(sc_headings)
            else len(coverage_lines)
        )
        marker = "✅" if verdict == "pass" else "❌"
        evidence = [
            line.strip()[len(f"- {marker} ") :]
            for line in coverage_lines[heading_index + 1 : end]
            if line.strip().startswith(f"- {marker} ")
        ]
        if not evidence:
            raise HandoffError(f"{name} {sc_id} lacks {verdict} evidence")
        for item in evidence:
            _non_placeholder(item, f"{name} {sc_id} {verdict} evidence")
        verdicts[sc_id] = verdict
    if sorted(verdicts, key=lambda n: int(n[2:])) != owned:
        raise HandoffError(f"{name} Intent coverage must cover exactly {', '.join(owned)}")
    if overall == "pass" and "fail" in verdicts.values():
        raise HandoffError(f"{name} Wave verdict is pass while an owned SC failed")
    return {
        "phase": "wave",
        "wave": wave,
        "cycle": cycle,
        "owned": owned,
        "review": review,
        "verdict": overall,
    }


def validate_final(
    root: Path, project_dir: str = DEFAULT_PROJECT_DIR, *, final_text: Optional[str] = None
) -> Dict[str, object]:
    """Require FINAL.md to give an evidenced verdict for every INTENT SC."""

    _require_state(root, "ship", "active", project_dir)
    intent = _read(root, _intent_path(project_dir))
    criteria = _success_criteria(intent)
    surface_of: Dict[str, str] = {}
    surfaces = _surfaces(intent, "INTENT.md")
    if surfaces:
        plan = _read(root, f"{project_dir}/plan/PLAN.md")
        for surface, (_task, owned) in _surface_contract(plan, surfaces).items():
            for criterion in owned:
                surface_of[criterion] = surface
    relative = f"{project_dir}/review/FINAL.md"
    text = _read(root, relative) if final_text is None else final_text
    reviewed_head = _reviewed_head(text, relative)
    head_result = subprocess.run(
        ("git", "-C", str(root), "rev-parse", "--verify", "HEAD"),
        capture_output=True,
        text=True,
        check=False,
    )
    if head_result.returncode != 0:
        raise HandoffError("FINAL.md Reviewed HEAD cannot be checked because HEAD is missing")
    current_head = head_result.stdout.strip()
    if reviewed_head != current_head:
        raise HandoffError(
            f"FINAL.md Reviewed HEAD {reviewed_head} is not the current HEAD "
            f"{current_head}; re-run the final review on the current commit"
        )
    overall = _line_value(text, "Overall verdict:")
    if overall not in {"pass", "blocked"}:
        raise HandoffError("FINAL.md Overall verdict is invalid")
    text = _strip_comments(_section(text, "Success criteria"))
    blocks = list(
        re.finditer(r"(?m)^### (?P<id>SC[1-9]\d*) — (?P<title>.+)$", text)
    )
    expected = list(criteria)
    found = [match.group("id") for match in blocks]
    if sorted(found, key=lambda n: int(n[2:])) != expected:
        raise HandoffError("FINAL.md Success criteria must cover exactly " + ", ".join(expected))
    verdicts: Dict[str, str] = {}
    for index, heading in enumerate(blocks):
        sc_id = heading.group("id")
        if _normalize_ws(heading.group("title")) != _normalize_ws(criteria[sc_id]):
            raise HandoffError(f"FINAL.md {sc_id} heading text differs from INTENT.md")
        end = blocks[index + 1].start() if index + 1 < len(blocks) else len(text)
        block = text[heading.end() : end]
        label = f"FINAL.md {sc_id}"
        verdict = _source_field(block, "Verdict", label)
        if verdict not in {"met", "not-met", "unverifiable"}:
            raise HandoffError(f"FINAL.md {sc_id} Verdict is invalid")
        verdicts[sc_id] = verdict
        surface = surface_of.get(sc_id)
        if surface is None:
            check = _source_field(block, "Check", label)
            observed = _source_field(block, "Observed", label)
        else:
            check = _unquoted(_raw_source_field(block, "Check", label))
            observed = _unquoted(_raw_source_field(block, "Observed", label))
        reference = _source_field(block, "Reference", label)
        finding = _source_field(block, "Finding", label)
        fix_direction = _source_field(block, "Fix direction", label)
        if surface is not None:
            named = _source_field(block, "Surface", label)
            if _normalize_ws(named).casefold() != _normalize_ws(surface).casefold():
                raise HandoffError(f"FINAL.md {sc_id} Surface must name {surface}")
            if check.casefold() == "none":
                raise HandoffError(
                    f"FINAL.md {sc_id} lacks the walked Check for the {surface} surface"
                )
            _surface_value(check, f"FINAL.md {sc_id} surface Check")
            _surface_value(observed, f"FINAL.md {sc_id} surface Observed")
        if check.casefold() == "none" and reference.casefold() == "none":
            raise HandoffError(f"FINAL.md {sc_id} lacks a Check or Reference")
        if observed.casefold() == "none":
            raise HandoffError(f"FINAL.md {sc_id} lacks an Observed result")
        if verdict == "met":
            if finding.casefold() != "none" or fix_direction.casefold() != "none":
                raise HandoffError(
                    f"FINAL.md {sc_id} met verdict must have no Finding or Fix direction"
                )
        elif finding.casefold() == "none" or fix_direction.casefold() == "none":
            raise HandoffError(
                f"FINAL.md {sc_id} {verdict} verdict requires a Finding and Fix direction"
            )
        if overall == "pass" and verdict != "met":
            raise HandoffError(f"FINAL.md Overall verdict is pass while {sc_id} is {verdict}")
    review_dir = root / project_dir / "review"
    gaps: Dict[int, str] = {}
    for path in sorted(review_dir.glob("final-gap-*.md")):
        match = GAP_NAME_PATTERN.fullmatch(path.name)
        if not match or not path.is_file() or path.is_symlink():
            raise HandoffError(f"invalid final gap artifact: {path.name}")
        number = int(match.group("number"))
        if number in gaps:
            raise HandoffError(f"duplicate final gap number {number}")
        gap_relative = f"{project_dir}/review/{path.name}"
        gap = _read(root, gap_relative)
        heading = GAP_HEADING_PATTERN.fullmatch(gap.splitlines()[0] if gap else "")
        if not heading or int(heading.group("number")) != number:
            raise HandoffError(f"{gap_relative} heading does not match its file number")
        if _reviewed_head(gap, gap_relative) != reviewed_head:
            raise HandoffError(f"{gap_relative} Reviewed HEAD differs from FINAL.md")
        verdict = _line_value(gap, "Gap verdict:")
        if verdict not in {"pass", "blocked"}:
            raise HandoffError(f"{gap_relative} Gap verdict is invalid")
        risk = _line_value(gap, "Risk:")
        if (
            _normalize_ws(heading.group("risk")).casefold()
            != _normalize_ws(risk).casefold()
        ):
            raise HandoffError(
                f"{gap_relative} heading risk does not match Risk field"
            )
        _line_value(gap, "Waves checked:")
        checked = _section(gap, "Checked evidence")
        check = _source_field(checked, "Check", gap_relative)
        observed = _source_field(checked, "Observed", gap_relative)
        reference = _source_field(checked, "Reference", gap_relative)
        if check.casefold() == "none" and reference.casefold() == "none":
            raise HandoffError(f"{gap_relative} lacks a Check or Reference")
        if observed.casefold() == "none":
            raise HandoffError(f"{gap_relative} lacks an Observed result")
        finding = _section(gap, "Finding")
        found_value = _source_field(finding, "Found", gap_relative)
        fix_direction = _source_field(finding, "Fix direction", gap_relative)
        if found_value.casefold() == "none":
            raise HandoffError(f"{gap_relative} lacks a Finding")
        if verdict == "pass" and fix_direction.casefold() != "none":
            raise HandoffError(f"{gap_relative} pass must use Fix direction: none")
        if verdict == "blocked" and fix_direction.casefold() == "none":
            raise HandoffError(f"{gap_relative} blocked verdict lacks a fix direction")
        gaps[number] = verdict

    expected_gaps = list(range(1, len(gaps) + 1))
    if sorted(gaps) != expected_gaps or not gaps:
        raise HandoffError("final gap artifacts must be present and contiguous from 1")
    if overall == "pass" and any(verdict != "pass" for verdict in gaps.values()):
        raise HandoffError("FINAL.md Overall verdict is pass while a final gap is blocked")
    all_evidence_passes = (
        all(verdict == "met" for verdict in verdicts.values())
        and all(verdict == "pass" for verdict in gaps.values())
    )
    expected_overall = "pass" if all_evidence_passes else "blocked"
    if overall != expected_overall:
        raise HandoffError(
            f"FINAL.md Overall verdict must be {expected_overall} for its SC and gap verdicts"
        )
    return {
        "phase": "ship",
        "criteria": expected,
        "verdict": overall,
        "reviewed_head": reviewed_head,
        "gaps": sorted(gaps),
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
        "phase", choices=("research", "decide", "roadmap", "patch", "plan", "wave", "final")
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
                "decide": validate_decide,
                "roadmap": validate_roadmap,
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
