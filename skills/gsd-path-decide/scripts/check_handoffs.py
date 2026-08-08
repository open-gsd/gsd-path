#!/usr/bin/env python3
"""Validate the durable hand-off packets that bridge GSD Path phases."""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


PIPELINE = "gsd-path/v1"
STANDARD_DIMENSIONS = ("domain", "stack", "pitfalls", "similar")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
DISPATCH_PATTERN = re.compile(
    r"^- `(?P<dimension>[^`]+)` — (?P<status>dispatched|skipped) "
    r"→ (?P<output>[^—]+) — (?P<reason>.+)$"
)
QUESTION_PATTERN = re.compile(r"^- `\[RESEARCH\] (?P<question>[^`]+)` → `(?P<dimension>[^`]+)`$")
FINDING_PATTERN = re.compile(r"^### (?P<id>P\d{3}) — (?P<title>.+)$")
SOURCE_PATTERN = re.compile(r"^\.project/review/(?:FINAL\.md|final-gap-\d+\.md)$")
CRITERION_LOCATOR_PATTERN = re.compile(r"^SC[1-9]\d*$")


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


def _require_state(root: Path, phase: str, status: str) -> None:
    values = _frontmatter(_read(root, ".project/STATE.md"))
    if values.get("pipeline") != PIPELINE:
        raise HandoffError("STATE.md has the wrong pipeline marker")
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


def validate_research(root: Path) -> Dict[str, object]:
    """Validate the research-to-synthesis hand-off and return its summary."""

    _require_state(root, "research", "done")
    intent = _read(root, ".project/intent/INTENT.md")
    handoff = _read(root, ".project/research/RESEARCH.md")
    if _line_value(handoff, "Phase:") != "research":
        raise HandoffError("RESEARCH.md names the wrong phase")
    if _line_value(handoff, "Status:") != "complete":
        raise HandoffError("RESEARCH.md is not complete")
    if _line_value(handoff, "Intent:") != ".project/intent/INTENT.md":
        raise HandoffError("RESEARCH.md must point to INTENT.md")

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
            expected = f".project/research/evidence-{dimension}.md"
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
        raise HandoffError("RESEARCH.md question assignments do not match INTENT.md")
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
    matches = list(re.finditer(r"(?m)^### P\d{3} — .+$", text))
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


def validate_patch_findings(root: Path) -> Dict[str, object]:
    """Validate the review-to-patch hand-off and return its summary."""

    _require_state(root, "review", "blocked")
    handoff = _read(root, ".project/review/PATCH-FINDINGS.md")
    reviewed_head = _reviewed_head(handoff, "PATCH-FINDINGS.md")
    if _line_value(handoff, "State:") != "review/blocked":
        raise HandoffError("PATCH-FINDINGS.md names the wrong state")

    blocks = _finding_blocks(handoff)
    if not blocks:
        raise HandoffError("PATCH-FINDINGS.md has no findings")
    ids = []
    sources = []
    for heading, block in blocks:
        match = FINDING_PATTERN.fullmatch(heading)
        if not match:
            raise HandoffError("patch finding headings must use P### ids")
        finding_id = match.group("id")
        ids.append(finding_id)
        source = _field(block, "Source").strip("`")
        if not SOURCE_PATTERN.fullmatch(source):
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
        "phase": "review",
        "reviewed_head": reviewed_head,
        "findings": ids,
        "sources": sorted(set(sources)),
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("phase", choices=("research", "patch"))
    argument_parser.add_argument("--repo", type=Path, required=True)
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = (
            validate_research(arguments.repo.resolve())
            if arguments.phase == "research"
            else validate_patch_findings(arguments.repo.resolve())
        )
    except HandoffError as error:
        print(f"handoff validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
