#!/usr/bin/env python3
# gsd-path project runtime
"""Interpret Roadmap text for selection, approval, promotion and milestone close."""
from __future__ import annotations

import re
from typing import Optional


class RoadmapError(RuntimeError):
    pass


class NoEligibleMilestone(RoadmapError):
    pass


ROADMAP_HEADING_RE = re.compile(r"^### (M\d{3,}) — (.+)$")
STRICT_HEADING_RE = re.compile(r"^### (M\d{3,}) — ([a-z0-9][a-z0-9-]*)\s*$")
MUTABLE_ROADMAP_FIELDS_RE = re.compile(r"^(Status|Archive|Integrated):")

def normalized_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"

def roadmap_blocks(content: str) -> list[dict]:
    lines = content.splitlines(keepends=True)
    headings = []
    for index, line in enumerate(lines):
        match = ROADMAP_HEADING_RE.fullmatch(line.rstrip("\r\n"))
        if match:
            headings.append((index, match.group(1), match.group(2).strip()))
    blocks = []
    for position, (start, milestone_id, title) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        fields = {}
        for index in range(start + 1, end):
            match = re.match(
                r"^(Status|Archive|Integrated|Depends on):\s*([^#]*?)\s*(?:#.*)?$",
                lines[index].rstrip("\r\n"),
            )
            if match:
                if match.group(1) in fields:
                    raise RoadmapError(
                        f"roadmap milestone {milestone_id} has duplicate "
                        f"{match.group(1)} field"
                    )
                fields[match.group(1)] = (index, match.group(2).strip())
        blocks.append(
            {
                "id": milestone_id,
                "title": title,
                "start": start,
                "end": end,
                "fields": fields,
            }
        )
    return blocks


def milestone_block(content: str, milestone: str) -> dict:
    normalized = normalized_slug(milestone)
    matches = [
        block
        for block in roadmap_blocks(content)
        if normalized_slug(block["title"]) == normalized
    ]
    if len(matches) != 1:
        raise RoadmapError(f"ROADMAP.md must contain exactly one entry for {milestone}")
    return matches[0]


def dependency_ids(block: dict) -> list[str]:
    dependencies = block["fields"].get("Depends on")
    if dependencies is None:
        raise RoadmapError(f"roadmap milestone {block['id']} lacks dependencies")
    dependency_list = re.fullmatch(
        r"\[\s*(M\d{3,}(?:\s*,\s*M\d{3,})*)?\s*\]",
        dependencies[1],
    )
    if dependency_list is None:
        raise RoadmapError(f"roadmap milestone {block['id']} has invalid dependencies")
    return re.findall(r"M\d{3,}", dependency_list.group(1) or "")


def next_eligible_pending(content: str, active_milestone: Optional[str] = None) -> dict:
    blocks = roadmap_blocks(content)
    blocks_by_id = {block["id"]: block for block in blocks}
    if len(blocks_by_id) != len(blocks):
        raise RoadmapError("ROADMAP.md milestone ids must be unique")
    active_id = None
    if active_milestone is not None:
        active = milestone_block(content, active_milestone)
        if active["fields"].get("Status", (-1, ""))[1] != "active":
            raise RoadmapError(f"roadmap milestone {active_milestone} is not active")
        active_id = active["id"]
    for block in blocks:
        if block["fields"].get("Status", (-1, ""))[1] != "pending":
            continue
        dependencies = dependency_ids(block)
        if all(
            dependency in blocks_by_id
            and (
                blocks_by_id[dependency]["fields"].get("Status", (-1, ""))[1]
                == "shipped"
                or dependency == active_id
            )
            for dependency in dependencies
        ):
            return block
    raise NoEligibleMilestone("ROADMAP.md has no dependency-ready pending milestone")


def selection_payload(selected: dict) -> dict:
    milestone = normalized_slug(selected["title"])
    return {
        "status": "selected",
        "id": selected["id"],
        "milestone": milestone,
        "branch": f"gsd-path/{selected['id']}",
    }


def select_lookahead(content: str, active_milestone: Optional[str] = None) -> dict:
    try:
        selected = next_eligible_pending(content, active_milestone)
    except NoEligibleMilestone:
        blocks = roadmap_blocks(content)
        if blocks and all(
            block["fields"].get("Status", (-1, ""))[1]
            in {"shipped", "abandoned"}
            for block in blocks
        ):
            return {"status": "complete"}
        return {"status": "none"}
    return selection_payload(selected)


def roadmap_contract(content: str, milestone: str) -> tuple[str, ...]:
    block = milestone_block(content, milestone)
    lines = content.splitlines()
    return tuple(
        line.rstrip()
        for line in lines[block["start"] : block["end"]]
        if not MUTABLE_ROADMAP_FIELDS_RE.match(line)
    )


def compare_roadmap_entry(
    before: str,
    after: str,
    milestone: str,
    active_milestone: Optional[str] = None,
) -> dict:
    before_contract = roadmap_contract(before, milestone)
    try:
        after_contract = roadmap_contract(after, milestone)
        selected = milestone_block(after, milestone)
        eligible = next_eligible_pending(after, active_milestone)
    except RoadmapError:
        after_contract = ()
        selected = None
        eligible = None
    status = (
        "unchanged"
        if before_contract == after_contract
        and selected is not None
        and eligible is not None
        and selected["id"] == eligible["id"]
        else "changed"
    )
    return {"status": status, "milestone": milestone}


def strict_sections(text: str) -> dict[str, tuple[str, int, int]]:
    lines = text.splitlines(keepends=True)
    headings: list[tuple[str, str, int]] = []
    for index, line in enumerate(lines):
        match = STRICT_HEADING_RE.fullmatch(line.rstrip("\r\n"))
        if match:
            if int(match.group(1).removeprefix("M")) < 1:
                raise RoadmapError(f"ROADMAP.md has invalid milestone id: {match.group(1)}")
            headings.append((match.group(1), match.group(2), index))
    sections: dict[str, tuple[str, int, int]] = {}
    for position, (milestone_id, slug, start) in enumerate(headings):
        end = headings[position + 1][2] if position + 1 < len(headings) else len(lines)
        if slug in sections:
            raise RoadmapError(f"ROADMAP.md repeats milestone slug: {slug}")
        sections[slug] = (milestone_id, start, end)
    return sections


def replace_field(
    lines: list[str],
    start: int,
    end: int,
    field: str,
    expected: set[str],
    value: str,
) -> None:
    found: Optional[int] = None
    for index in range(start, end):
        raw = lines[index].rstrip("\r\n")
        ending = lines[index][len(raw) :]
        match = re.match(rf"^({re.escape(field)}:\s*)(\S+)(.*)$", raw)
        if match is None:
            continue
        if found is not None:
            raise RoadmapError(f"ROADMAP.md repeats {field} in one milestone")
        if match.group(2) not in expected:
            raise RoadmapError(
                f"ROADMAP.md {field} is {match.group(2)}, expected {sorted(expected)}"
            )
        lines[index] = f"{match.group(1)}{value}{match.group(3)}{ending}"
        found = index
    if found is None:
        raise RoadmapError(f"ROADMAP.md milestone is missing {field}")


def milestone_status(lines: list[str], start: int, end: int) -> str:
    values = []
    for line in lines[start:end]:
        match = re.fullmatch(r"Status:\s*(\S+)\s*", line.rstrip("\r\n"))
        if match:
            values.append(match.group(1))
    if len(values) != 1:
        raise RoadmapError("ROADMAP.md milestone must have one Status field")
    return values[0]


def activate_milestone(text: str, milestone: str) -> str:
    sections = strict_sections(text)
    if milestone not in sections:
        raise RoadmapError(f"ROADMAP.md is missing selected milestone: {milestone}")
    lines = text.splitlines(keepends=True)
    active = [
        slug
        for slug, (_, start, end) in sections.items()
        if milestone_status(lines, start, end) == "active"
    ]
    if active:
        raise RoadmapError(
            "ROADMAP.md already has an active milestone: " + ", ".join(active)
        )
    _, start, end = sections[milestone]
    replace_field(lines, start, end, "Status", {"pending"}, "active")
    return "".join(lines)


def reslice(before: str, candidate: str, phase: str, selected: str) -> str:
    old_blocks = roadmap_blocks(before)
    before_lines = before.splitlines(keepends=True)
    candidate_lines = candidate.splitlines(keepends=True)
    for block in old_blocks:
        status = block["fields"].get("Status", (-1, ""))[1]
        if status not in {"active", "shipped", "abandoned"}:
            continue
        slug = normalized_slug(block["title"])
        new = milestone_block(candidate, slug)
        if status == "shipped":
            changed = roadmap_contract(before, slug) != roadmap_contract(candidate, slug)
        else:
            changed = before_lines[block["start"]:block["end"]] != candidate_lines[new["start"]:new["end"]]
        if changed:
            raise RoadmapError(f"{status} roadmap entry changed: {slug}")
    if phase in {"inspect", "define"}:
        active = [b for b in roadmap_blocks(candidate) if b["fields"].get("Status", (-1, ""))[1] == "active"]
        if len(active) != 1 or selection_payload(active[0])["milestone"] != selected:
            raise RoadmapError("roadmap re-slice must retain the active entry")
        return candidate
    if not any(b["fields"].get("Status", (-1, ""))[1] == "abandoned" for b in old_blocks):
        raise RoadmapError("post-abandon re-slice requires an abandoned milestone")
    selection = select_lookahead(candidate)
    if selection.get("milestone") != selected:
        raise RoadmapError("roadmap re-slice must use the selected dependency-ready milestone")
    return activate_milestone(candidate, selected)


def has_questions(text: str, milestone: Optional[str] = None) -> bool:
    """Report open questions for the active entry, or for ``milestone`` when given."""
    lines = text.splitlines()
    active_section: Optional[list[str]] = None
    for index, line in enumerate(lines):
        heading = STRICT_HEADING_RE.fullmatch(line)
        if heading is None:
            continue
        if int(heading.group(1).removeprefix("M")) < 1:
            raise RoadmapError(
                f"ROADMAP.md has invalid milestone id: {heading.group(1)}"
            )
        end = next(
            (
                cursor
                for cursor in range(index + 1, len(lines))
                if STRICT_HEADING_RE.fullmatch(lines[cursor]) is not None
            ),
            len(lines),
        )
        section = lines[index:end]
        if milestone is not None:
            if heading.group(2) == milestone:
                active_section = section
            continue
        if any(re.fullmatch(r"Status:\s*active(?:\s+#.*)?", item) for item in section):
            if active_section is not None:
                raise RoadmapError("ROADMAP.md has more than one active milestone")
            active_section = section
    if active_section is None:
        if milestone is not None:
            raise RoadmapError(f"ROADMAP.md is missing lookahead milestone: {milestone}")
        raise RoadmapError("ROADMAP.md has no active milestone")
    try:
        start = active_section.index("Open questions") + 1
    except ValueError as error:
        raise RoadmapError("active roadmap milestone has no Open questions") from error
    questions = [
        line[2:].strip()
        for line in active_section[start:]
        if line.startswith("- ")
    ]
    return any(question.lower() != "none" for question in questions)
