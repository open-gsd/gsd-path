#!/usr/bin/env python3
"""Prepare and validate a crash-resumable GSD Path milestone archive."""

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence


ARCHIVE_PATTERN = re.compile(r"^(\d{3,})-([a-z0-9][a-z0-9-]*)$")
TASK_FILE_PATTERN = re.compile(r"^T\d{3}-[a-z0-9][a-z0-9-]*\.md$")
WAVE_FILE_PATTERN = re.compile(r"^wave-([1-9]\d*)\.cycle([1-9]\d*)\.md$")
FINAL_CRITERION_PATTERN = re.compile(r"^### SC([1-9]\d*) — (.+)$")
FINAL_GAP_FILE_PATTERN = re.compile(r"^final-gap-([1-9]\d*)\.md$")
FINAL_GAP_HEADING_PATTERN = re.compile(r"^# Gap Review — ([1-9]\d*): (.+)$")
DIRECTORIES_TO_ARCHIVE = ("intent", "research", "plan", "tasks", "review")
FILES_TO_ARCHIVE = ("BOARD.md",)
MANIFEST_FIELDS = (
    "Milestone:",
    "Shipped:",
    "Final verdict:",
    "Waves:",
    "Carried forward:",
)
MANIFEST_HEADINGS = ("## Success criteria at ship", "## Contents", "## Notes")
CARRY_TEMP_NAME = ".DOCS-AUDIT.md.gsd-path-tmp"
STATE_TEMP_NAME = ".STATE.md.gsd-path-tmp"
MANIFEST_TEMP_NAME = ".MANIFEST.md.gsd-path-tmp"
# Evidence files are per-dispatched-dimension: the research phase gate owns
# their existence, so the archive requires only the always-produced core.
REQUIRED_ARCHIVE_FILES = (
    "intent/INTENT.md",
    "research/SYNTHESIS.md",
    "plan/PLAN.md",
    "review/FINAL.md",
    "BOARD.md",
)

# Template placeholders look like <name> or <one line>. Comparison text such
# as "120ms < 200ms" or "a -> b" is legitimate evidence, not a placeholder.
PLACEHOLDER_PATTERN = re.compile(r"<[a-zA-Z][^<>\n]*>")


def contains_placeholder(value: str) -> bool:
    return PLACEHOLDER_PATTERN.search(value) is not None


def split_manifest_row(line: str) -> Sequence[str]:
    """Split a manifest table row, honoring \\| as an escaped literal pipe."""
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells = []
    current = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\\" and index + 1 < len(text) and text[index + 1] == "|":
            current.append("|")
            index += 2
            continue
        if char == "|":
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


class ArchiveError(RuntimeError):
    pass


PIPELINE_MARKER = "gsd-path/v1"


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.parent / STATE_TEMP_NAME
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        temporary_path.write_text(content, encoding="utf-8")
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def frontmatter_value(content: str, key: str) -> Optional[str]:
    lines = content.splitlines()
    if not lines or lines[0] != "---":
        raise ArchiveError("STATE.md is missing YAML frontmatter")
    for line in lines[1:]:
        if line == "---":
            break
        match = re.match(rf"^{re.escape(key)}:\s*([^#]*?)\s*(?:#.*)?$", line)
        if match:
            value = match.group(1).strip().strip('"').strip("'")
            return value
    return None


def set_frontmatter_value(content: str, key: str, value: str) -> str:
    lines = content.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise ArchiveError("STATE.md is missing YAML frontmatter")

    closing_index: Optional[int] = None
    key_index: Optional[int] = None
    for index, line in enumerate(lines[1:], start=1):
        stripped = line.rstrip("\r\n")
        if stripped == "---":
            closing_index = index
            break
        if re.match(rf"^{re.escape(key)}:", stripped):
            key_index = index

    if closing_index is None:
        raise ArchiveError("STATE.md frontmatter is not closed")

    replacement = f"{key}: {value}\n"
    if key_index is None:
        lines.insert(closing_index, replacement)
    else:
        lines[key_index] = replacement
    return "".join(lines)


def normalized_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


def is_unset(value: Optional[str]) -> bool:
    return not value or value.lower() in {"null", "none"} or value.startswith("<")


def milestone_slug(state: str) -> str:
    milestone = frontmatter_value(state, "milestone")
    if is_unset(milestone):
        raise ArchiveError("STATE.md does not name a milestone")
    return normalized_slug(milestone or "")


def require_archive_milestone(archive_name: str, state: str) -> None:
    match = ARCHIVE_PATTERN.fullmatch(archive_name)
    if not match or match.group(2) != milestone_slug(state):
        raise ArchiveError("persisted archive slug does not match normalized STATE.milestone")


def require_project_layout(project: Path) -> Path:
    active_root = project / ".project"
    if active_root.is_symlink() or not active_root.is_dir():
        raise ArchiveError(f".project must be a real directory inside the repository: {active_root}")
    if active_root.resolve().parent != project:
        raise ArchiveError(f".project resolves outside the repository: {active_root}")
    state_path = active_root / "STATE.md"
    if state_path.is_symlink() or not state_path.is_file():
        raise ArchiveError(f"missing real state file: {state_path}")
    return active_root


def safe_archive_root(project: Path) -> Path:
    active_root = require_project_layout(project)
    archive_root = active_root / "archive"
    if archive_root.is_symlink() or not archive_root.is_dir():
        raise ArchiveError(f"archive root must be a real directory: {archive_root}")
    if archive_root.resolve().parent != active_root.resolve():
        raise ArchiveError(f"archive root resolves outside .project: {archive_root}")
    for candidate in archive_root.iterdir():
        if candidate.is_symlink():
            raise ArchiveError(f"archive entries must not be symlinks: {candidate}")
    return archive_root


def create_archive_root(project: Path) -> Path:
    active_root = require_project_layout(project)
    archive_root = active_root / "archive"
    if archive_root.is_symlink():
        raise ArchiveError(f"archive root must not be a symlink: {archive_root}")
    archive_root.mkdir(parents=True, exist_ok=True)
    return safe_archive_root(project)


def archive_relative_from_state(configured: str) -> PurePosixPath:
    relative = PurePosixPath(configured)
    if (
        relative.parent != PurePosixPath(".project/archive")
        or not ARCHIVE_PATTERN.fullmatch(relative.name)
    ):
        raise ArchiveError(f"STATE.md has an invalid archive path: {configured}")
    return relative


def archive_from_state(project: Path, configured: str) -> Path:
    relative = archive_relative_from_state(configured)
    archive_root = safe_archive_root(project)
    archive = project.joinpath(*relative.parts)
    if archive.is_symlink() or archive.resolve(strict=False).parent != archive_root.resolve():
        raise ArchiveError(f"archive target must not escape through a symlink: {archive}")
    return archive


def persisted_archive(project: Path, state_path: Path, slug: str) -> Path:
    state = state_path.read_text(encoding="utf-8")
    configured = frontmatter_value(state, "archive")
    if not is_unset(configured):
        return archive_from_state(project, configured)

    archive_root = create_archive_root(project)
    sequences = []
    for candidate in archive_root.iterdir():
        match = ARCHIVE_PATTERN.fullmatch(candidate.name)
        if candidate.is_dir() and match:
            sequences.append(int(match.group(1)))
    sequence = max(sequences, default=0) + 1
    archive = archive_root / f"{sequence:03d}-{normalized_slug(slug)}"
    relative_archive = archive.relative_to(project).as_posix()
    atomic_write(state_path, set_frontmatter_value(state, "archive", relative_archive))
    return archive


def pending_ruling_count(audit: Path) -> int:
    if not audit.is_file():
        return 0
    in_rulings = False
    count = 0
    for line in audit.read_text(encoding="utf-8").splitlines():
        if line == "## User rulings":
            in_rulings = True
            continue
        if in_rulings and line.startswith("## "):
            break
        if not in_rulings or not line.lstrip().startswith("|"):
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if fields and fields[-1] == "no":
            count += 1
    return count


def is_existing_carry_forward(source: Path, archived: Path) -> bool:
    entries = list(source.iterdir()) if source.is_dir() else []
    archived_audit = archived / "DOCS-AUDIT.md"
    if not archived_audit.is_file() or pending_ruling_count(archived_audit) == 0:
        return False
    if not entries:
        return True
    return (
        len(entries) == 1
        and entries[0].name == "DOCS-AUDIT.md"
        and filecmp.cmp(entries[0], archived_audit, shallow=False)
    )


def move_directory(source: Path, destination: Path) -> None:
    if source.exists() and destination.exists():
        if source.name == "research" and is_existing_carry_forward(source, destination):
            return
        raise ArchiveError(f"archive collision: both {source} and {destination} exist")
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))


def move_file(source: Path, destination: Path) -> None:
    if source.exists() and destination.exists():
        raise ArchiveError(f"archive collision: both {source} and {destination} exist")
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))


def require_complete_transaction_inputs(active_root: Path, archive: Path) -> None:
    for name in DIRECTORIES_TO_ARCHIVE:
        source = active_root / name
        destination = archive / name
        if source.exists() and destination.exists():
            if name == "research" and is_existing_carry_forward(source, destination):
                continue
            raise ArchiveError(f"archive collision: both {source} and {destination} exist")
        if not source.exists() and not destination.exists():
            raise ArchiveError(f"missing both active and archived {name}")

    for name in FILES_TO_ARCHIVE:
        source = active_root / name
        destination = archive / name
        if source.exists() and destination.exists():
            raise ArchiveError(f"archive collision: both {source} and {destination} exist")
        if not source.exists() and not destination.exists():
            raise ArchiveError(f"missing both active and archived {name}")


def selected_transaction_path(active_root: Path, archive: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    active_top = active_root / path.parts[0]
    archived_top = archive / path.parts[0]
    if active_top.exists() and not archived_top.exists():
        return active_root.joinpath(*path.parts)
    return archive.joinpath(*path.parts)


def is_real_file(path: Path) -> bool:
    return not path.is_symlink() and path.is_file()


def canonical_task_files(tasks: Path) -> Sequence[Path]:
    if tasks.is_symlink() or not tasks.is_dir():
        return ()
    candidates = sorted(path for path in tasks.iterdir() if path.name.startswith("T"))
    if any(not TASK_FILE_PATTERN.fullmatch(path.name) or not is_real_file(path) for path in candidates):
        raise ArchiveError("canonical task artifacts must be real T###-slug.md files")
    return candidates


def canonical_wave_files(reviews: Path) -> Sequence[Path]:
    if reviews.is_symlink() or not reviews.is_dir():
        return ()
    candidates = sorted(path for path in reviews.iterdir() if path.name.startswith("wave-"))
    if any(not WAVE_FILE_PATTERN.fullmatch(path.name) or not is_real_file(path) for path in candidates):
        raise ArchiveError("canonical wave artifacts must be real wave-N.cycleC.md files")
    return candidates


def require_canonical_transaction_inputs(active_root: Path, archive: Path) -> None:
    missing = [
        relative
        for relative in REQUIRED_ARCHIVE_FILES
        if not is_real_file(selected_transaction_path(active_root, archive, relative))
    ]
    tasks = selected_transaction_path(active_root, archive, "tasks")
    reviews = selected_transaction_path(active_root, archive, "review")
    if not canonical_task_files(tasks):
        missing.append("tasks/T###-slug.md")
    if not canonical_wave_files(reviews):
        missing.append("review/wave-N.cycleC.md")
    if missing:
        raise ArchiveError(f"canonical milestone artifacts are missing: {', '.join(missing)}")


def require_safe_move_inputs(active_root: Path, archive: Path) -> None:
    archive_device = archive.stat().st_dev
    for name in (*DIRECTORIES_TO_ARCHIVE, *FILES_TO_ARCHIVE):
        source = active_root / name
        destination = archive / name
        if source.is_symlink() or destination.is_symlink():
            raise ArchiveError(f"archive transaction paths must not be symlinks: {name}")
        if source.exists() and source.stat().st_dev != archive_device:
            raise ArchiveError(f"archive move crosses filesystems: {source}")

def atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.parent / CARRY_TEMP_NAME
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        shutil.copy2(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def remove_interrupted_carry_copy(active_root: Path, archive: Path) -> None:
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    if pending_ruling_count(archived_audit) == 0:
        return
    temporary_path = active_root / "research" / CARRY_TEMP_NAME
    if temporary_path.exists() or temporary_path.is_symlink():
        temporary_path.unlink()


def require_transaction_context(project: Path, state: str, phases: Sequence[str]) -> None:
    phase = frontmatter_value(state, "phase")
    if phase not in phases:
        raise ArchiveError(f"archive transaction is not valid in phase: {phase}")

    repository_root = require_git_success(
        run_git(project, "rev-parse", "--show-toplevel"),
        "resolve Git root",
    )
    if Path(repository_root).resolve() != project:
        raise ArchiveError(f"--repo must be the Git worktree root: {repository_root}")

    expected_branch = frontmatter_value(state, "branch")
    current_branch = require_git_success(
        run_git(project, "branch", "--show-current"),
        "resolve current branch",
    )
    if is_unset(expected_branch):
        raise ArchiveError("STATE.md does not name a bound build branch")
    if current_branch != expected_branch:
        raise ArchiveError(
            f"current branch {current_branch!r} does not match STATE.branch {expected_branch!r}"
        )

    non_project_status = require_git_success(
        run_git(
            project,
            "status",
            "--porcelain",
            "--untracked-files=all",
            "--",
            ".",
            ":(exclude).project",
        ),
        "inspect non-project worktree status",
    )
    if non_project_status:
        raise ArchiveError("non-.project worktree changes block the archive transaction")


def completed_field(lines: Sequence[str], field: str, artifact: str) -> str:
    values = [line.removeprefix(field).strip() for line in lines if line.startswith(field)]
    if len(values) != 1 or not values[0] or contains_placeholder(values[0]):
        raise ArchiveError(f"{artifact} requires one completed {field} field")
    return values[0]


def parse_final_review(archive: Path) -> tuple:
    final = archive / "review" / "FINAL.md"
    if not is_real_file(final):
        raise ArchiveError("final review must be a real FINAL.md file")
    lines = final.read_text(encoding="utf-8").splitlines()
    reviewed_head = completed_field(lines, "Reviewed HEAD:", "FINAL.md")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", reviewed_head):
        raise ArchiveError("FINAL.md Reviewed HEAD must be a full commit SHA")
    if completed_field(lines, "Overall verdict:", "FINAL.md") != "pass":
        raise ArchiveError("FINAL.md final review did not pass")
    if lines.count("## Success criteria") != 1:
        raise ArchiveError("FINAL.md requires one Success criteria section")

    start = lines.index("## Success criteria") + 1
    headings = []
    criteria_end = len(lines)
    for index, line in enumerate(lines[start:], start=start):
        if line.startswith("## "):
            criteria_end = index
            break
        if line.startswith("### "):
            match = FINAL_CRITERION_PATTERN.fullmatch(line)
            if not match:
                raise ArchiveError("FINAL.md has an invalid success-criterion heading")
            headings.append((index, int(match.group(1)), match.group(2).strip()))
    if not headings or [number for _, number, _ in headings] != list(range(1, len(headings) + 1)):
        raise ArchiveError("FINAL.md success criteria must be ordered and contiguous")

    expected_fields = ("Verdict", "Check", "Observed", "Reference", "Finding", "Fix direction")
    criteria = []
    for position, (heading_index, _, criterion) in enumerate(headings):
        section_start = heading_index + 1
        section_end = headings[position + 1][0] if position + 1 < len(headings) else criteria_end
        values = {}
        for line in lines[section_start:section_end]:
            match = re.fullmatch(r"- \*\*(Verdict|Check|Observed|Reference|Finding|Fix direction)\*\*:\s*(.*)", line)
            if not match:
                continue
            key, value = match.groups()
            if key in values:
                raise ArchiveError(f"FINAL.md repeats {key} for {criterion}")
            values[key] = value.strip().strip("`")
        if tuple(values) != expected_fields or any(
            not value or contains_placeholder(value) for value in values.values()
        ):
            raise ArchiveError(f"FINAL.md criterion is incomplete: {criterion}")
        if values["Verdict"] != "met":
            raise ArchiveError(f"FINAL.md criterion lacks passing evidence: {criterion}")
        evidence = next(
            (values[field] for field in ("Reference", "Check", "Observed") if values[field] != "none"),
            None,
        )
        if evidence is None:
            raise ArchiveError(f"FINAL.md criterion lacks passing evidence: {criterion}")
        criteria.append((criterion, "met", evidence))
    return reviewed_head.lower(), criteria


def validate_gap_reviews(archive: Path, reviewed_head: str) -> None:
    review = archive / "review"
    candidates = sorted(path for path in review.iterdir() if path.name.startswith("final-gap-"))
    if not candidates:
        raise ArchiveError("final review requires at least one final-gap-N.md artifact")

    numbered = []
    for path in candidates:
        match = FINAL_GAP_FILE_PATTERN.fullmatch(path.name)
        if not match or not is_real_file(path):
            raise ArchiveError("final gap artifacts must be real final-gap-N.md files")
        numbered.append((int(match.group(1)), path))
    numbered.sort(key=lambda item: item[0])
    if [number for number, _ in numbered] != list(range(1, len(numbered) + 1)):
        raise ArchiveError("final gap artifacts must be numbered contiguously")

    for number, path in numbered:
        lines = path.read_text(encoding="utf-8").splitlines()
        headings = [FINAL_GAP_HEADING_PATTERN.fullmatch(line) for line in lines]
        headings = [match for match in headings if match]
        if (
            len(headings) != 1
            or int(headings[0].group(1)) != number
            or contains_placeholder(headings[0].group(2))
        ):
            raise ArchiveError(f"{path.name} heading does not match its number")
        gap_head = completed_field(lines, "Reviewed HEAD:", path.name).lower()
        if gap_head != reviewed_head:
            raise ArchiveError(f"{path.name} Reviewed HEAD does not match FINAL.md")
        if completed_field(lines, "Gap verdict:", path.name) != "pass":
            raise ArchiveError(f"{path.name} gap review did not pass")
        if completed_field(lines, "Risk:", path.name) == "none":
            raise ArchiveError(f"{path.name} does not name a completed risk")


def review_cycle_counts(archive: Path) -> Sequence[int]:
    plan = archive / "plan" / "PLAN.md"
    wave_numbers = [
        int(match.group(1))
        for match in re.finditer(r"^## Wave (\d+)\b", plan.read_text(encoding="utf-8"), re.MULTILINE)
    ]
    if not wave_numbers or wave_numbers != list(range(1, len(wave_numbers) + 1)):
        raise ArchiveError("plan wave numbers must be ordered and contiguous")

    artifacts = {}
    for path in canonical_wave_files(archive / "review"):
        match = WAVE_FILE_PATTERN.fullmatch(path.name)
        assert match is not None
        wave, cycle = (int(value) for value in match.groups())
        lines = path.read_text(encoding="utf-8").splitlines()
        expected_heading = f"# Review — wave {wave}, cycle {cycle}"
        if lines.count(expected_heading) != 1:
            raise ArchiveError(f"{path.name} heading does not match its filename")
        recorded_cycle = completed_field(lines, "Cycle:", path.name)
        if recorded_cycle != str(cycle):
            raise ArchiveError(f"{path.name} Cycle field does not match its filename")
        verdict = completed_field(lines, "Wave verdict:", path.name)
        if verdict not in {"pass", "blocked"}:
            raise ArchiveError(f"{path.name} has an invalid wave verdict")
        artifacts.setdefault(wave, {})[cycle] = path
    if sorted(artifacts) != wave_numbers:
        raise ArchiveError("review cycle waves do not match PLAN.md")

    counts = []
    for wave in wave_numbers:
        cycles = artifacts[wave]
        if sorted(cycles) != list(range(1, max(cycles) + 1)):
            raise ArchiveError(f"review cycles for wave {wave} are not contiguous")
        last = cycles[max(cycles)]
        verdict = completed_field(
            last.read_text(encoding="utf-8").splitlines(),
            "Wave verdict:",
            last.name,
        )
        if verdict != "pass":
            raise ArchiveError(f"last review cycle for wave {wave} did not pass")
        counts.append(max(cycles))
    return counts


def validate_manifest(archive: Path, state: str) -> tuple:
    manifest = archive / "MANIFEST.md"
    if manifest.is_symlink() or not manifest.is_file():
        raise ArchiveError("archive MANIFEST.md must be a real file")
    content = manifest.read_text(encoding="utf-8")
    placeholder_content = content.replace("<!--", "").replace("-->", "")
    if contains_placeholder(placeholder_content):
        raise ArchiveError("manifest contains an unfinished template placeholder")
    lines = content.splitlines()

    if lines.count(f"# Archive — {archive.name}") != 1:
        raise ArchiveError("manifest header does not match the archive name")
    fields = {field: completed_field(lines, field, "manifest") for field in MANIFEST_FIELDS}
    for heading in MANIFEST_HEADINGS:
        if lines.count(heading) != 1:
            raise ArchiveError(f"manifest requires one {heading} section")

    milestone = frontmatter_value(state, "milestone")
    if fields["Milestone:"] != milestone:
        raise ArchiveError(
            f"manifest milestone {fields['Milestone:']!r} does not match STATE.milestone {milestone!r}"
        )
    try:
        date.fromisoformat(fields["Shipped:"])
    except ValueError:
        raise ArchiveError("manifest Shipped field must be an ISO date")
    if fields["Final verdict:"] != "all criteria met; project verify passed":
        raise ArchiveError("manifest final verdict does not record the passed final gate")

    task_files = canonical_task_files(archive / "tasks")
    cycle_counts = review_cycle_counts(archive)
    wave_count = len(cycle_counts)
    counts = re.fullmatch(
        r"(\d+)\s+Tasks:\s+(\d+) done / (\d+) total\s+Review cycles used:\s+([1-9]\d*(?:/[1-9]\d*)*)",
        fields["Waves:"],
    )
    if not counts:
        raise ArchiveError("manifest Waves field has an invalid format")
    recorded_waves, done_tasks, total_tasks = (int(counts.group(index)) for index in (1, 2, 3))
    cycles = [int(value) for value in counts.group(4).split("/")]
    if (
        recorded_waves != wave_count
        or done_tasks != len(task_files)
        or total_tasks != len(task_files)
        or cycles != list(cycle_counts)
    ):
        raise ArchiveError("manifest wave, task, or review-cycle counts do not match the archive")

    carried_forward = pending_ruling_count(archive / "research" / "DOCS-AUDIT.md")
    expected_carry = (
        "none" if carried_forward == 0 else f"{carried_forward} DOCS-AUDIT ruling(s)"
    )
    if fields["Carried forward:"] != expected_carry:
        raise ArchiveError("manifest carried-forward count does not match DOCS-AUDIT.md")

    criteria_start = lines.index("## Success criteria at ship") + 1
    criteria_rows = []
    for line in lines[criteria_start:]:
        if line.startswith("## "):
            break
        if not line.startswith("|"):
            continue
        cells = split_manifest_row(line)
        if cells and (cells[0] == "Criterion" or set(cells[0]) <= {"-", ":"}):
            continue
        criteria_rows.append(cells)
    if not criteria_rows or any(
        len(row) != 3
        or not row[0]
        or row[1] != "met"
        or not row[2]
        or row[2] == "none"
        or any(contains_placeholder(cell) for cell in row)
        for row in criteria_rows
    ):
        raise ArchiveError("manifest success-criteria rows are incomplete")
    reviewed_head, final_criteria = parse_final_review(archive)
    validate_gap_reviews(archive, reviewed_head)
    if [tuple(row) for row in criteria_rows] != list(final_criteria):
        raise ArchiveError("manifest success criteria do not match FINAL.md evidence in order")

    contents_start = lines.index("## Contents") + 1
    listed = []
    for line in lines[contents_start:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            listed.append(line[2:].strip().strip("`"))

    if len(listed) != len(set(listed)):
        raise ArchiveError("manifest contents contain duplicate paths")
    for value in listed:
        path = PurePosixPath(value)
        if not value or path.is_absolute() or ".." in path.parts or value == "MANIFEST.md":
            raise ArchiveError(f"manifest contains an invalid path: {value}")

    actual = []
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise ArchiveError(f"archive contents must not be symlinks: {path}")
        if path.is_file() and path.name != "MANIFEST.md":
            actual.append(path.relative_to(archive).as_posix())
    actual.sort()
    if sorted(listed) != actual:
        missing = sorted(set(actual) - set(listed))
        extra = sorted(set(listed) - set(actual))
        raise ArchiveError(f"manifest contents mismatch; missing={missing}, extra={extra}")

    notes_start = lines.index("## Notes") + 1
    notes = []
    for line in lines[notes_start:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            notes.append(line[2:].strip())
    if not notes or any(not note or contains_placeholder(note) for note in notes):
        raise ArchiveError("manifest Notes section is incomplete")
    return actual, reviewed_head


def prepare(repo: Path, slug: str) -> dict:
    project = repo.resolve()
    active_root = require_project_layout(project)
    state_path = active_root / "STATE.md"
    state_temporary = active_root / STATE_TEMP_NAME

    state = state_path.read_text(encoding="utf-8")
    if frontmatter_value(state, "pipeline") != PIPELINE_MARKER:
        raise ArchiveError(f"STATE.md pipeline marker must be {PIPELINE_MARKER}")
    require_transaction_context(project, state, ("review", "shipped"))
    phase = frontmatter_value(state, "phase")
    status = frontmatter_value(state, "status")
    if (phase, status) not in {("review", "active"), ("shipped", "done")}:
        raise ArchiveError(f"archive transaction is not valid in state: {phase}/{status}")
    expected_slug = milestone_slug(state)
    if normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )
    configured = frontmatter_value(state, "archive")
    if phase == "shipped" and is_unset(configured):
        raise ArchiveError("shipped state has no persisted archive transaction")
    if not is_unset(configured):
        relative_archive = archive_relative_from_state(configured)
        require_archive_milestone(relative_archive.name, state)
        require_uncommitted_archive(project, configured)
    if state_temporary.exists() or state_temporary.is_symlink():
        state_temporary.unlink()

    archive = persisted_archive(project, state_path, slug)
    require_archive_milestone(archive.name, state)
    archive.mkdir(parents=True, exist_ok=True)
    manifest_temporary = archive / MANIFEST_TEMP_NAME
    if manifest_temporary.exists() or manifest_temporary.is_symlink():
        manifest_temporary.unlink()

    remove_interrupted_carry_copy(active_root, archive)
    require_complete_transaction_inputs(active_root, archive)
    require_canonical_transaction_inputs(active_root, archive)
    require_safe_move_inputs(active_root, archive)
    for name in DIRECTORIES_TO_ARCHIVE:
        move_directory(active_root / name, archive / name)
    for name in FILES_TO_ARCHIVE:
        move_file(active_root / name, archive / name)

    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    carried_forward = pending_ruling_count(archived_audit)
    if carried_forward:
        active_audit = active_root / "research" / "DOCS-AUDIT.md"
        active_audit.parent.mkdir(parents=True, exist_ok=True)
        if active_audit.exists() and not filecmp.cmp(active_audit, archived_audit, shallow=False):
            raise ArchiveError(f"carry-forward collision: {active_audit} differs from archived audit")
        if not active_audit.exists():
            atomic_copy(archived_audit, active_audit)

    return {
        "archive": archive.relative_to(project).as_posix(),
        "carried_forward": carried_forward,
    }


def run_git(repo: Path, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )


def require_git_success(result: subprocess.CompletedProcess, action: str) -> str:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise ArchiveError(f"{action} failed: {detail}")
    return result.stdout.strip()


def archive_is_committed(project: Path, configured: str) -> bool:
    return run_git(project, "cat-file", "-e", f"HEAD:{configured}").returncode == 0


def require_uncommitted_archive(project: Path, configured: str) -> None:
    if archive_is_committed(project, configured):
        raise ArchiveError("current archive is already committed; run validate instead")


def require_clean_older_archives(project: Path, configured: str) -> None:
    result = run_git(
        project,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        "--ignored=matching",
        "--",
        ".project/archive",
    )
    if result.returncode != 0:
        require_git_success(result, "inspect archive worktree status")
    status = result.stdout
    current_prefix = f"{configured}/"
    dirty = set()
    ignored_current = set()
    for record in status.split("\0"):
        has_status = len(record) > 3 and record[2] == " "
        code = record[:2] if has_status else ""
        path = record[3:] if has_status else record
        if code == "!!" and (
            path == ".project/archive/"
            or path == configured
            or path.startswith(current_prefix)
        ):
            ignored_current.add(path)
        if (
            path.startswith(".project/archive/")
            and path != configured
            and not path.startswith(current_prefix)
        ):
            dirty.add(path)
    if ignored_current:
        raise ArchiveError(
            f"ignored current archive paths would be omitted from shipment: "
            f"{', '.join(sorted(ignored_current))}"
        )
    if dirty:
        raise ArchiveError(f"dirty older archive paths block shipment: {', '.join(sorted(dirty))}")


def require_canonical_archive(archive: Path) -> None:
    missing = [relative for relative in REQUIRED_ARCHIVE_FILES if not is_real_file(archive / relative)]
    if not canonical_task_files(archive / "tasks"):
        missing.append("tasks/T###-slug.md")
    if not canonical_wave_files(archive / "review"):
        missing.append("review/wave-N.cycleC.md")
    for directory in DIRECTORIES_TO_ARCHIVE:
        path = archive / directory
        if path.is_symlink() or not path.is_dir():
            missing.append(f"{directory}/")
    board = archive / "BOARD.md"
    if board.is_symlink() or not board.is_file():
        missing.append("BOARD.md")
    if missing:
        raise ArchiveError(f"canonical archive artifacts are missing: {', '.join(sorted(set(missing)))}")


def require_clean_active_root(active_root: Path, archive: Path) -> None:
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    carried_forward = pending_ruling_count(archived_audit)
    # LESSONS.md stays active across milestones; it ships but never archives.
    allowed = {"STATE.md", "archive", "LESSONS.md"}
    active_research = active_root / "research"

    if carried_forward:
        allowed.add("research")
        active_audit = active_research / "DOCS-AUDIT.md"
        entries = sorted(path.name for path in active_research.iterdir()) if active_research.is_dir() else []
        if (
            active_research.is_symlink()
            or entries != ["DOCS-AUDIT.md"]
            or active_audit.is_symlink()
            or not active_audit.is_file()
            or not filecmp.cmp(active_audit, archived_audit, shallow=False)
        ):
            raise ArchiveError("pending DOCS-AUDIT rulings lack an exact active carry-forward copy")
    elif active_research.exists() or active_research.is_symlink():
        raise ArchiveError("active research exists without a pending carry-forward queue")

    unexpected = sorted(path.name for path in active_root.iterdir() if path.name not in allowed)
    if unexpected:
        raise ArchiveError(f"unexpected active .project paths remain: {', '.join(unexpected)}")


def require_stageable_carry_forward(project: Path, archive: Path) -> None:
    if pending_ruling_count(archive / "research" / "DOCS-AUDIT.md") == 0:
        return
    carry_path = ".project/research/DOCS-AUDIT.md"
    tracked = run_git(project, "ls-files", "--error-unmatch", "--", carry_path)
    if tracked.returncode == 0:
        return
    if tracked.returncode != 1:
        require_git_success(tracked, "inspect active carry-forward tracking status")
    ignored = run_git(project, "check-ignore", "-q", "--no-index", "--", carry_path)
    if ignored.returncode == 0:
        raise ArchiveError("ignored active carry-forward is not tracked and would be omitted")
    if ignored.returncode != 1:
        require_git_success(ignored, "inspect active carry-forward ignore status")


def require_committed_carry_forward(project: Path, configured: str, archive: Path, ref: str) -> None:
    if pending_ruling_count(archive / "research" / "DOCS-AUDIT.md") == 0:
        return
    active_blob = require_git_success(
        run_git(project, "rev-parse", "--verify", f"{ref}:.project/research/DOCS-AUDIT.md"),
        "verify committed carry-forward",
    )
    archived_blob = require_git_success(
        run_git(
            project,
            "rev-parse",
            "--verify",
            f"{ref}:{configured}/research/DOCS-AUDIT.md",
        ),
        "verify archived carry-forward",
    )
    if active_blob != archived_blob:
        raise ArchiveError("committed carry-forward differs from the archived DOCS-AUDIT.md")


def prepared_transaction(
    repo: Path,
    phases: Sequence[str],
    must_be_uncommitted: bool = False,
) -> tuple:
    project = repo.resolve()
    active_root = require_project_layout(project)
    state_path = active_root / "STATE.md"

    state = state_path.read_text(encoding="utf-8")
    if frontmatter_value(state, "pipeline") != PIPELINE_MARKER:
        raise ArchiveError(f"STATE.md pipeline marker must be {PIPELINE_MARKER}")
    require_transaction_context(project, state, phases)

    configured = frontmatter_value(state, "archive")
    if is_unset(configured):
        raise ArchiveError("STATE.md does not name the archive transaction")
    relative_archive = archive_relative_from_state(configured)
    require_archive_milestone(relative_archive.name, state)
    if must_be_uncommitted:
        require_uncommitted_archive(project, configured)
    archive = archive_from_state(project, configured)
    if archive.is_symlink() or not archive.is_dir() or not (archive / "MANIFEST.md").is_file():
        raise ArchiveError("archive or MANIFEST.md is missing")
    if (archive / MANIFEST_TEMP_NAME).exists() or (archive / MANIFEST_TEMP_NAME).is_symlink():
        raise ArchiveError("interrupted manifest temporary file remains; rerun prepare")

    require_canonical_archive(archive)
    require_clean_active_root(active_root, archive)
    archived_files, reviewed_head = validate_manifest(archive, state)
    return project, active_root, state, configured, archive, archived_files, reviewed_head


def preflight(repo: Path) -> dict:
    project, _, state, configured, archive, _, reviewed_head = prepared_transaction(
        repo,
        ("review", "shipped"),
        must_be_uncommitted=True,
    )
    phase = frontmatter_value(state, "phase")
    status = frontmatter_value(state, "status")
    if (phase, status) not in {("review", "active"), ("shipped", "done")}:
        raise ArchiveError("archive preflight requires review/active or uncommitted shipped/done")
    require_stageable_carry_forward(project, archive)
    require_clean_older_archives(project, configured)
    head = require_git_success(run_git(project, "rev-parse", "HEAD"), "resolve preflight HEAD")
    if reviewed_head != head:
        raise ArchiveError(
            f"FINAL.md Reviewed HEAD {reviewed_head} does not match current HEAD {head}"
        )
    return {
        "archive": configured,
        "carried_forward": pending_ruling_count(archive / "research" / "DOCS-AUDIT.md"),
    }


def find_ship_commit(project: Path, archive_name: str) -> str:
    expected_subject = f"ship: {archive_name}"
    log = require_git_success(
        run_git(project, "log", "--format=%H%x00%s", "HEAD"),
        "inspect HEAD history for the ship commit",
    )
    matches = []
    for record in log.splitlines():
        if "\x00" not in record:
            continue
        commit, subject = record.split("\x00", 1)
        if subject == expected_subject:
            matches.append(commit)
    if not matches:
        raise ArchiveError(f"no commit with exact subject {expected_subject!r} in HEAD history")
    # git log is newest-first: the most recent ship subject owns the
    # transaction, so an empty or malformed duplicate cannot inherit validity.
    return matches[0]


def validate(repo: Path) -> dict:
    project, _, state, configured, archive, archived_files, reviewed_head = prepared_transaction(
        repo,
        ("shipped",),
    )
    if frontmatter_value(state, "status") != "done":
        raise ArchiveError("STATE.md is not shipped/done")

    project_status = require_git_success(run_git(project, "status", "--porcelain"), "inspect worktree status")
    if project_status:
        raise ArchiveError("ship transaction worktree is not clean")

    # The ship commit must be reachable from HEAD but need not be HEAD:
    # product commits after shipping do not disturb a validated shipment.
    ship_commit = find_ship_commit(project, archive.name)

    parents = require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", ship_commit),
        "inspect ship commit parents",
    ).split()
    if len(parents) != 2:
        raise ArchiveError("ship commit must have exactly one parent")

    changed_paths = require_git_success(
        run_git(
            project,
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "--no-renames",
            "-r",
            ship_commit,
        ),
        "inspect ship commit paths",
    ).splitlines()
    outside_project = [path for path in changed_paths if not path.startswith(".project/")]
    if outside_project:
        raise ArchiveError(f"ship commit changes paths outside .project: {', '.join(outside_project)}")

    archive_prefix = f"{configured}/"
    older_archive_changes = [
        path
        for path in changed_paths
        if path.startswith(".project/archive/") and not path.startswith(archive_prefix)
    ]
    if older_archive_changes:
        raise ArchiveError(f"ship commit mutates an older archive: {', '.join(older_archive_changes)}")

    allowed_active_prefixes = tuple(f".project/{name}/" for name in DIRECTORIES_TO_ARCHIVE)
    unexpected_project_paths = [
        path
        for path in changed_paths
        if path != ".project/STATE.md"
        and path != ".project/BOARD.md"
        and path != ".project/LESSONS.md"
        and not path.startswith(archive_prefix)
        and not path.startswith(allowed_active_prefixes)
    ]
    if unexpected_project_paths:
        raise ArchiveError(
            f"ship commit changes unexpected .project paths: {', '.join(unexpected_project_paths)}"
        )

    required_paths = {
        ".project/STATE.md",
        f"{configured}/MANIFEST.md",
        *(f"{configured}/{path}" for path in archived_files),
    }
    missing_from_commit = sorted(required_paths - set(changed_paths))
    if missing_from_commit:
        raise ArchiveError(
            f"ship commit does not record the complete transaction: {', '.join(missing_from_commit)}"
        )
    require_committed_carry_forward(project, configured, archive, ship_commit)

    ship_parent = require_git_success(run_git(project, "rev-parse", f"{ship_commit}^"), "resolve ship parent")
    if reviewed_head != ship_parent:
        raise ArchiveError(
            f"FINAL.md Reviewed HEAD {reviewed_head} does not match ship parent {ship_parent}"
        )

    archive_in_parent = run_git(project, "cat-file", "-e", f"{ship_commit}^:{configured}")
    if archive_in_parent.returncode == 0:
        raise ArchiveError("current archive was already committed before the ship commit")

    committed_state = require_git_success(
        run_git(project, "show", f"{ship_commit}:.project/STATE.md"),
        "read committed STATE.md",
    )
    if (
        frontmatter_value(committed_state, "phase") != "shipped"
        or frontmatter_value(committed_state, "status") != "done"
        or frontmatter_value(committed_state, "archive") != configured
    ):
        raise ArchiveError("ship commit does not contain the shipped state transaction")

    manifest_path = f"{ship_commit}:{configured}/MANIFEST.md"
    require_git_success(run_git(project, "cat-file", "-e", manifest_path), "verify committed manifest")

    project_drift = run_git(project, "diff", "--quiet", ship_commit, "HEAD", "--", ".project")
    if project_drift.returncode != 0:
        raise ArchiveError(".project changed in history after the ship commit")

    return {"archive": configured, "commit": ship_commit}


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    subparsers = argument_parser.add_subparsers(dest="command", required=True)

    prepare_parser = subparsers.add_parser("prepare", help="prepare or resume an archive transaction")
    prepare_parser.add_argument("--repo", required=True, type=Path)
    prepare_parser.add_argument("--slug", required=True)

    preflight_parser = subparsers.add_parser(
        "preflight",
        help="validate the prepared transaction before the ship commit",
    )
    preflight_parser.add_argument("--repo", required=True, type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate the committed ship transaction")
    validate_parser.add_argument("--repo", required=True, type=Path)
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare(arguments.repo, arguments.slug)
        elif arguments.command == "preflight":
            result = preflight(arguments.repo)
        else:
            result = validate(arguments.repo)
    except (ArchiveError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
