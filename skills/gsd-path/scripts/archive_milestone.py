#!/usr/bin/env python3
"""Prepare, render, validate, integrate, and abandon GSD Path milestone archives.

Also validates milestone integration: the read-only validate-integrated
command checks the shipped transaction, the integration merge commit on the
remote default branch, and the milestone tag without any network access.
"""

import argparse
import filecmp
import json
import os
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterator, NamedTuple, Optional, Sequence

try:
    from isolation import (
        IsolationError,
        checkpoint as isolation_checkpoint,
        verify_landed_task_files,
    )
    from pipeline_git import (
        bound_branch_name,
        default_branch_name,
        integrate_commit_body,
        integrate_subject,
        is_bound_branch,
        is_integrate_subject,
        is_ship_subject,
        milestone_id,
        milestone_number,
        ship_commit_body,
        ship_subject,
    )
    from review_panel import KNOWN_FAMILIES, ReviewPanelError, parse_sources
    from pipeline_state import (
        PipelineState,
        PipelineStateError,
        load_state,
        transition_state,
    )
except ImportError:  # pragma: no cover - package import used by tests
    from scripts.isolation import (
        IsolationError,
        checkpoint as isolation_checkpoint,
        verify_landed_task_files,
    )
    from scripts.pipeline_git import (
        bound_branch_name,
        default_branch_name,
        integrate_commit_body,
        integrate_subject,
        is_bound_branch,
        is_integrate_subject,
        is_ship_subject,
        milestone_id,
        milestone_number,
        ship_commit_body,
        ship_subject,
    )
    from scripts.review_panel import KNOWN_FAMILIES, ReviewPanelError, parse_sources
    from scripts.pipeline_state import (
        PipelineState,
        PipelineStateError,
        load_state,
        transition_state,
    )

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl


ARCHIVE_PATTERN = re.compile(r"^(\d{3,})-([a-z0-9][a-z0-9-]*)$")
TASK_FILE_PATTERN = re.compile(r"^T\d{3}-[a-z0-9][a-z0-9-]*\.md$")
WAVE_FILE_PATTERN = re.compile(
    r"^wave-([1-9]\d*)\.cycle([1-9]\d*)(\.(?:contract|adversarial|panel))?\.md$"
)
WAVE_PANEL_SKIP_PATTERN = re.compile(
    r"^wave-([1-9]\d*)\.cycle([1-9]\d*)\.panel\.skipped\.json$"
)
FINAL_CRITERION_PATTERN = re.compile(r"^### SC([1-9]\d*) — (.+)$")
INTENT_CRITERION_PATTERN = re.compile(r"^([1-9]\d*)\.\s+(\S.*)$")
HTML_COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
FINAL_GAP_FILE_PATTERN = re.compile(r"^final-gap-([1-9]\d*)\.md$")
FINAL_GAP_HEADING_PATTERN = re.compile(r"^# Gap Review — ([1-9]\d*): (.+)$")
WAVE_TASK_HEADING_PATTERN = re.compile(r"^## (T\d{3}) — (.+): (pass|fail)$")
WAVE_SC_HEADING_PATTERN = re.compile(
    r"^### (SC[1-9]\d*) — (.+): (pass|fail)$"
)
PLAN_COVERAGE_ROW_PATTERN = re.compile(
    r"^\|\s*(SC[1-9]\d*)\s*\|\s*(T\d{3})\s*\|\s*([^|]+?)\s*\|$"
)
DIALOGUE_HEADING_PATTERN = re.compile(
    r"^### D(\d{3}) — (\d{4}-\d{2}-\d{2}) — "
    r"([a-z-]+)/(active|blocked|done) — (.+)$"
)
ANSWER_HEADING_PATTERN = re.compile(
    r"^## Answer A(\d{3}) — (\d{4}-\d{2}-\d{2}) — .+$"
)
DISPOSITION_HEADING_PATTERN = re.compile(
    r"^## Disposition X(\d{3}) — (\d{4}-\d{2}-\d{2})$"
)
DISCUSSION_PHASES = {
    "inspect",
    "define",
    "research",
    "decide",
    "roadmap",
    "plan",
    "build",
    "ship",
}
DISCUSSION_FILES = ("DIALOGUE.md", "ANSWERS.md")
EMPTY_DISCUSSION_FILES = {
    "DIALOGUE.md": """# GSD Path Discussion — Dialogue

<!-- Written by $gsd-path-discuss. Append turns; never rewrite prior turns. -->

## Turns
""",
    "ANSWERS.md": """# GSD Path Discussion — Answers

<!-- Written by $gsd-path-discuss. Append one record per turn; never rewrite prior answers. -->
""",
}
DISCUSSION_TRANSACTION_NAME = ".discussion-archive-transaction.json"
DIRECTORIES_TO_ARCHIVE = ("intent", "research", "plan", "tasks", "review")
OPTIONAL_DIRECTORIES_TO_ARCHIVE = ("discuss",)
TRANSACTION_DIRECTORIES = (*DIRECTORIES_TO_ARCHIVE, *OPTIONAL_DIRECTORIES_TO_ARCHIVE)
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
ABANDON_JOURNAL_SCHEMA = "gsd-path/abandon/v1"
ABANDON_JOURNAL_NAME = "gsd-path-abandon.json"
ROADMAP_HEADING_PATTERN = re.compile(
    r"^### (M\d{3,}) — ([a-z0-9][a-z0-9-]*)\s*$"
)
# Evidence files are per-dispatched-dimension: the research phase gate owns
# their existence, so the archive requires only the always-produced core.
REQUIRED_ARCHIVE_FILES = (
    "intent/INTENT.md",
    "research/SYNTHESIS.md",
    "plan/PLAN.md",
    "review/FINAL.md",
)
# Abandon runs from build: review/ may hold only wave files, but an approved
# plan implies these artifacts existed.
ABANDON_REQUIRED_ARCHIVE_FILES = (
    "intent/INTENT.md",
    "research/SYNTHESIS.md",
    "plan/PLAN.md",
)
ABANDON_REQUIRED_DIRECTORIES = ("intent", "research", "plan", "tasks")

# Template placeholders look like <name> or <one line>. Comparison text such
# as "120ms < 200ms" or "a -> b" is legitimate evidence, not a placeholder.
PLACEHOLDER_PATTERN = re.compile(r"<[a-zA-Z][^<>\n]*>")


def contains_placeholder(value: str) -> bool:
    return PLACEHOLDER_PATTERN.search(value) is not None


def plan_review_panel_config(plan_text: str) -> dict:
    """Parse PLAN review-panel policy with the canonical fail-closed parser."""
    try:
        return parse_sources(plan_text, None)
    except ReviewPanelError as error:
        raise ArchiveError(f"PLAN.md review_panel config is invalid: {error}") from error


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


PIPELINE_MARKER = "gsd-path/v2"


@contextmanager
def discussion_lock(active_root: Path) -> Iterator[None]:
    if sys.platform == "win32":
        lock_value = require_git_success(
            run_git(
                active_root.parent,
                "rev-parse",
                "--git-path",
                "gsd-path-discussion.lock",
            ),
            "resolve discussion lock",
        )
        lock_path = Path(lock_value)
        if not lock_path.is_absolute():
            lock_path = active_root.parent / lock_path
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            try:
                yield
            finally:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    descriptor = os.open(active_root, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def atomic_replace(path: Path, temporary_path: Path, content: str) -> None:
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666,
        )
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None
        with handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def atomic_write(path: Path, content: str) -> None:
    atomic_replace(path, path.parent / STATE_TEMP_NAME, content)


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


def milestone_slug(state: PipelineState) -> str:
    milestone = state.milestone
    if is_unset(milestone):
        raise ArchiveError("STATE.md does not name a milestone")
    return normalized_slug(milestone or "")


def require_archive_milestone(archive_name: str, state: PipelineState) -> None:
    match = ARCHIVE_PATTERN.fullmatch(archive_name)
    if (
        not match
        or int(match.group(1)) < 1
        or match.group(2) != milestone_slug(state)
    ):
        raise ArchiveError("persisted archive slug does not match normalized STATE.milestone")
    branch = state.branch
    if (
        branch is None
        or not is_bound_branch(branch)
        or int(match.group(1)) != milestone_number(branch)
    ):
        raise ArchiveError("persisted archive sequence does not match STATE.branch")


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
        raise ArchiveError(
            f"archive root must be a real, non-symlink directory: {archive_root}"
        )
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


def strict_state(project: Path) -> tuple[PipelineState, str, Path]:
    try:
        return load_state(project, ".project")
    except PipelineStateError as error:
        raise ArchiveError(f"STATE.md is invalid: {error}") from error


def archive_sequence_entries(project: Path) -> dict[int, Path]:
    archive_root = project / ".project" / "archive"
    if not archive_root.exists() and not archive_root.is_symlink():
        return {}
    archive_root = safe_archive_root(project)
    entries = {}
    for candidate in archive_root.iterdir():
        match = ARCHIVE_PATTERN.fullmatch(candidate.name)
        if match is None or not candidate.is_dir():
            raise ArchiveError(f"archive root has a noncanonical entry: {candidate.name}")
        number = int(match.group(1))
        if number == 0:
            raise ArchiveError("archive milestone number must be >= 1")
        if number in entries:
            raise ArchiveError(
                f"archive sequence {number:03d} has multiple milestone directories"
            )
        entries[number] = candidate
    return entries


def resolved_archive_target(
    project: Path, slug: str, parsed_state: PipelineState
) -> Path:
    branch = parsed_state.branch
    if not isinstance(branch, str) or not is_bound_branch(branch):
        raise ArchiveError("STATE.branch must be a canonical gsd-path/M00N branch")
    expected_number = milestone_number(branch)
    configured = parsed_state.archive
    entries = archive_sequence_entries(project)
    missing_prior = [
        number for number in range(1, expected_number) if number not in entries
    ]
    later = sorted(number for number in entries if number > expected_number)
    if missing_prior or later:
        raise ArchiveError(
            f"archive sequence does not match bound branch {branch}: "
            f"missing={missing_prior}, later={later}"
        )

    if configured is not None:
        archive = archive_from_state(project, configured)
        if milestone_number(archive.name) != expected_number:
            raise ArchiveError("persisted archive sequence does not match STATE.branch")
        collision = entries.get(expected_number)
        if collision is not None and collision.resolve() != archive.resolve():
            raise ArchiveError(
                f"archive sequence {expected_number:03d} collides with {collision.name}"
            )
        return archive

    if expected_number in entries:
        raise ArchiveError(
            f"archive sequence {expected_number:03d} already exists before persistence"
        )
    archive_root = project / ".project" / "archive"
    return archive_root / f"{expected_number:03d}-{normalized_slug(slug)}"


def persisted_archive(
    project: Path, state_path: Path, slug: str, parsed_state: PipelineState
) -> Path:
    archive = resolved_archive_target(project, slug, parsed_state)
    if parsed_state.archive is not None:
        return archive
    create_archive_root(project)
    relative_archive = archive.relative_to(project).as_posix()
    state_text = state_path.read_text(encoding="utf-8")
    atomic_write(state_path, set_frontmatter_value(state_text, "archive", relative_archive))
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

    for name in OPTIONAL_DIRECTORIES_TO_ARCHIVE:
        source = active_root / name
        destination = archive / name
        if source.exists() and destination.exists():
            if name == "discuss":
                require_append_only_discussion(source, destination)
                continue
            raise ArchiveError(f"archive collision: both {source} and {destination} exist")



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
    candidates = sorted(tasks.iterdir())
    if any(
        not TASK_FILE_PATTERN.fullmatch(path.name) or not is_real_file(path)
        for path in candidates
    ):
        raise ArchiveError("canonical task artifacts must be real T###-slug.md files")
    return candidates


def completed_task_files(
    project: Path, tasks: Path, reviewed_head: str
) -> Sequence[Path]:
    """Return task artifacts only when each records landed completion evidence."""
    candidates = canonical_task_files(tasks)
    try:
        verify_landed_task_files(
            project,
            candidates,
            ".project/tasks",
            reviewed_head,
        )
    except (IsolationError, ValueError) as error:
        raise ArchiveError(f"task landing proof failed: {error}") from error
    return candidates


def validate_panel_skip_receipt(path: Path, expected_mode: str) -> None:
    if not is_real_file(path):
        raise ArchiveError(f"panel skip receipt must be a real file: {path.name}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ArchiveError(f"{path.name} is not valid review_panel JSON") from error
    expected_keys = {
        "missing",
        "mode",
        "parent_family",
        "reason",
        "selected",
        "skipped",
        "status",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        raise ArchiveError(f"{path.name} is not a canonical skipped-panel receipt")
    if (
        expected_mode != "detected"
        or payload["mode"] != expected_mode
        or payload["status"] != "skipped"
        or payload["reason"] != "no advertised cross-model families"
        or payload["selected"] != []
    ):
        raise ArchiveError(f"{path.name} does not record the expected skipped resolution")
    parent_family = payload["parent_family"]
    if parent_family is not None and not isinstance(parent_family, str):
        raise ArchiveError(f"{path.name} has an invalid parent_family")
    missing = payload["missing"]
    if (
        not isinstance(missing, list)
        or any(item not in KNOWN_FAMILIES for item in missing)
        or len(missing) != len(set(missing))
    ):
        raise ArchiveError(f"{path.name} has invalid missing families")
    skipped = payload["skipped"]
    if not isinstance(skipped, list) or any(
        not isinstance(item, dict)
        or set(item) != {"family", "reason"}
        or item["family"] not in KNOWN_FAMILIES
        or item["reason"] not in {"parent family", "not advertised", "cap"}
        for item in skipped
    ):
        raise ArchiveError(f"{path.name} has invalid skipped families")


def require_plan_panel_evidence(
    plan_text: str, panel: Path, skipped_receipt: Path
) -> dict:
    config = plan_review_panel_config(plan_text)
    panel_exists = is_real_file(panel)
    receipt_exists = is_real_file(skipped_receipt)
    if config["mode"] == "off":
        if receipt_exists:
            raise ArchiveError(
                f"{skipped_receipt.name} conflicts with review_panel mode off"
            )
        return config
    if panel_exists == receipt_exists:
        raise ArchiveError(
            "configured review_panel requires exactly one of review/PLAN-PANEL.md "
            "or review/PLAN-PANEL.skipped.json"
        )
    if receipt_exists:
        validate_panel_skip_receipt(skipped_receipt, str(config["mode"]))
    return config


class WaveArtifact(NamedTuple):
    path: Path
    wave: int
    cycle: int
    lens: Optional[str]


def canonical_wave_files(reviews: Path) -> Sequence[WaveArtifact]:
    if reviews.is_symlink() or not reviews.is_dir():
        return ()
    candidates = sorted(path for path in reviews.iterdir() if path.name.startswith("wave-"))
    matches = [(path, WAVE_FILE_PATTERN.fullmatch(path.name)) for path in candidates]
    if any(
        (match is None and WAVE_PANEL_SKIP_PATTERN.fullmatch(path.name) is None)
        or not is_real_file(path)
        for path, match in matches
    ):
        raise ArchiveError(
            "canonical wave artifacts must be real wave-N.cycleC.md files "
            "(a .contract, .adversarial, or .panel lens suffix is allowed), "
            "or canonical .panel.skipped.json receipts"
        )
    return [
        WaveArtifact(
            path,
            int(match.group(1)),
            int(match.group(2)),
            match.group(3).removeprefix(".") if match.group(3) else None,
        )
        for path, match in matches
        if match is not None
    ]


def canonical_wave_panel_skip_files(reviews: Path) -> dict[tuple[int, int], Path]:
    if reviews.is_symlink() or not reviews.is_dir():
        return {}
    receipts = {}
    for path in sorted(reviews.iterdir()):
        match = WAVE_PANEL_SKIP_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        if not is_real_file(path):
            raise ArchiveError(f"panel skip receipt must be a real file: {path.name}")
        receipts[(int(match.group(1)), int(match.group(2)))] = path
    return receipts


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
    plan = selected_transaction_path(active_root, archive, "plan/PLAN.md")
    if missing:
        raise ArchiveError(f"canonical milestone artifacts are missing: {', '.join(missing)}")
    require_plan_panel_evidence(
        plan.read_text(encoding="utf-8"),
        selected_transaction_path(active_root, archive, "review/PLAN-PANEL.md"),
        selected_transaction_path(
            active_root, archive, "review/PLAN-PANEL.skipped.json"
        ),
    )
    discussion = selected_transaction_path(active_root, archive, "discuss")
    if discussion.exists():
        validate_discussion_directory(discussion)


def require_safe_move_inputs(active_root: Path, archive: Path) -> None:
    archive_device = archive.stat().st_dev
    for name in TRANSACTION_DIRECTORIES:
        source = active_root / name
        destination = archive / name
        if source.is_symlink() or destination.is_symlink():
            raise ArchiveError(f"archive transaction paths must not be symlinks: {name}")
        if source.exists() and source.stat().st_dev != archive_device:
            raise ArchiveError(f"archive move crosses filesystems: {source}")

def atomic_copy(source: Path, destination: Path, temporary_name: str = CARRY_TEMP_NAME) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = destination.parent / temporary_name
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        shutil.copy2(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def record_sections(
    lines: Sequence[str], pattern: re.Pattern, boundaries: Sequence[re.Pattern]
) -> Sequence[tuple]:
    headings = []
    for index, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if match:
            headings.append((index, match))
    sections = []
    for start, match in headings:
        end = next(
            (
                index
                for index in range(start + 1, len(lines))
                if any(boundary.fullmatch(lines[index]) for boundary in boundaries)
            ),
            len(lines),
        )
        sections.append((match, lines[start + 1 : end]))
    return sections


def required_dialogue_block(
    lines: Sequence[str],
    marker: str,
    end_marker: str,
    artifact: str,
    quote: bool = False,
    end_from_last: bool = False,
) -> None:
    if lines.count(marker) != 1:
        raise ArchiveError(f"{artifact} requires one {marker.removeprefix('- **').removesuffix('**:')} block")
    start = lines.index(marker) + 1
    boundaries = [
        index for index in range(start, len(lines)) if lines[index] == end_marker
    ]
    if not boundaries:
        end = len(lines)
    elif end_from_last:
        end = boundaries[-1]
    else:
        end = boundaries[0]
    content = "\n".join(lines[start:end]).strip()
    if quote:
        content = "\n".join(
            line.lstrip().removeprefix(">").strip() for line in content.splitlines()
        ).strip()
    if not content:
        label = "verbatim user" if quote else "assistant"
        raise ArchiveError(f"{artifact} requires a non-empty {label} block")


def require_contiguous_ids(values: Sequence[int], artifact: str) -> None:
    if not values or list(values) != list(range(1, len(values) + 1)):
        raise ArchiveError(f"{artifact} record ids must be contiguous from 001")


def require_iso_date(value: str, artifact: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ArchiveError(f"{artifact} date must be YYYY-MM-DD") from error
    if parsed.isoformat() != value:
        raise ArchiveError(f"{artifact} date must be YYYY-MM-DD")


def require_bullet_fields(
    lines: Sequence[str], artifact: str, fields: Sequence[str]
) -> dict:
    return {
        field: completed_bullet_field(lines, field, artifact) for field in fields
    }


def validate_discussion_directory(
    directory: Path, require_dispositions: bool = True
) -> None:
    if directory.is_symlink() or not directory.is_dir():
        raise ArchiveError("discussion archive must be a real directory")
    entries = sorted(path.name for path in directory.iterdir())
    if entries != sorted(DISCUSSION_FILES):
        raise ArchiveError("discussion archive must contain exactly DIALOGUE.md and ANSWERS.md")
    dialogue, answers = (directory / name for name in DISCUSSION_FILES)
    if not is_real_file(dialogue) or not is_real_file(answers):
        raise ArchiveError("discussion archive records must be real files")

    dialogue_content = dialogue.read_text(encoding="utf-8")
    answer_content = answers.read_text(encoding="utf-8")
    dialogue_lines = dialogue_content.splitlines()
    answer_lines = answer_content.splitlines()
    if contains_placeholder("\n".join((*dialogue_lines, *answer_lines))):
        raise ArchiveError("discussion archive records contain placeholders")

    dialogue_sections = record_sections(
        dialogue_lines, DIALOGUE_HEADING_PATTERN, (DIALOGUE_HEADING_PATTERN,)
    )
    answer_boundaries = (ANSWER_HEADING_PATTERN, DISPOSITION_HEADING_PATTERN)
    answer_sections = record_sections(answer_lines, ANSWER_HEADING_PATTERN, answer_boundaries)
    dialogue_ids = [int(match.group(1)) for match, _ in dialogue_sections]
    answer_ids = [int(match.group(1)) for match, _ in answer_sections]
    if not dialogue_ids and not answer_ids:
        actual = {
            "DIALOGUE.md": dialogue_content,
            "ANSWERS.md": answer_content,
        }
        if actual != EMPTY_DISCUSSION_FILES:
            raise ArchiveError("empty discussion records must use canonical headers")
        return
    require_contiguous_ids(dialogue_ids, "DIALOGUE.md")
    require_contiguous_ids(answer_ids, "ANSWERS.md")
    if dialogue_ids != answer_ids:
        raise ArchiveError("discussion dialogue and answer ids do not correspond")

    dialogue_threads = {}
    dialogue_phases = {}
    dialogue_dates = {}
    for match, section in dialogue_sections:
        identifier = int(match.group(1))
        require_iso_date(match.group(2), "DIALOGUE.md")
        if match.group(3) not in DISCUSSION_PHASES:
            raise ArchiveError("DIALOGUE.md has an invalid phase")
        thread = completed_bullet_field(section, "Thread", "DIALOGUE.md")
        if not re.fullmatch(r"T\d{3}", thread):
            raise ArchiveError("DIALOGUE.md Thread must be T###")
        reply_to = completed_bullet_field(section, "Reply to", "DIALOGUE.md")
        if reply_to != "none" and not re.fullmatch(r"D\d{3}", reply_to):
            raise ArchiveError("DIALOGUE.md Reply to must be none or D###")
        if reply_to != "none" and int(reply_to[1:]) >= identifier:
            raise ArchiveError("DIALOGUE.md Reply to must reference an earlier turn")
        if reply_to != "none" and dialogue_threads[int(reply_to[1:])] != thread:
            raise ArchiveError("DIALOGUE.md Reply to must stay in the same thread")
        values = require_bullet_fields(
            section,
            "DIALOGUE.md",
            ("Evidence checked", "Research", "Thread status"),
        )
        thread_status = values["Thread status"]
        if thread_status not in {"working", "NEEDS-USER", "final"}:
            raise ArchiveError("DIALOGUE.md has an invalid Thread status")
        required_dialogue_block(
            section,
            "- **User (verbatim)**:",
            "- **Assistant**:",
            "DIALOGUE.md",
            quote=True,
        )
        required_dialogue_block(
            section,
            "- **Assistant**:",
            "- **Evidence checked**:",
            "DIALOGUE.md",
            end_from_last=True,
        )
        dialogue_threads[identifier] = thread
        dialogue_phases[identifier] = f"{match.group(3)}/{match.group(4)}"
        dialogue_dates[identifier] = match.group(2)

    answer_threads = {}
    pending_answers = set()
    answer_receipts = {}
    for match, section in answer_sections:
        identifier = int(match.group(1))
        require_iso_date(match.group(2), "ANSWERS.md")
        if match.group(2) != dialogue_dates[identifier]:
            raise ArchiveError("discussion answer date does not match its dialogue turn")
        thread = completed_bullet_field(section, "Thread", "ANSWERS.md")
        if thread != dialogue_threads[identifier]:
            raise ArchiveError("discussion answer Thread does not match its dialogue turn")
        if completed_bullet_field(section, "Turn", "ANSWERS.md") != f"D{identifier:03d}":
            raise ArchiveError("discussion answer Turn does not match its id")
        supersedes = completed_bullet_field(section, "Supersedes", "ANSWERS.md")
        if supersedes != "none" and not re.fullmatch(r"A\d{3}", supersedes):
            raise ArchiveError("ANSWERS.md Supersedes must be none or A###")
        if supersedes != "none" and int(supersedes[1:]) >= identifier:
            raise ArchiveError("ANSWERS.md Supersedes must reference an earlier answer")
        if supersedes != "none" and answer_threads[int(supersedes[1:])] != thread:
            raise ArchiveError("ANSWERS.md Supersedes must stay in the same thread")
        values = require_bullet_fields(
            section,
            "ANSWERS.md",
            (
                "Question",
                "Status",
                "Phase/status",
                "Conclusion",
                "Reasoning / pushback",
                "Evidence",
                "Research",
                "Confidence",
                "Unresolved",
                "Next owner",
                "Target artifact",
                "Follow-up",
            ),
        )
        status = values["Status"]
        if status not in {"working", "NEEDS-USER", "final"}:
            raise ArchiveError("ANSWERS.md has an invalid Status")
        phase_status = values["Phase/status"]
        if not re.fullmatch(r"[a-z-]+/(active|blocked|done)", phase_status):
            raise ArchiveError("ANSWERS.md has an invalid Phase/status")
        if phase_status != dialogue_phases[identifier]:
            raise ArchiveError("discussion answer Phase/status does not match its dialogue turn")
        confidence = values["Confidence"]
        if confidence not in {"high", "medium", "low", "unverifiable"}:
            raise ArchiveError("ANSWERS.md has an invalid Confidence")
        follow_up = values["Follow-up"]
        if follow_up not in {"none", "required"}:
            raise ArchiveError("ANSWERS.md has an invalid Follow-up")
        next_owner = values["Next owner"]
        target = values["Target artifact"]
        answer_key = f"A{identifier:03d}"
        answer_receipts[answer_key] = (next_owner, target)
        if follow_up == "required":
            if status not in {"final", "NEEDS-USER"}:
                raise ArchiveError("required discussion follow-up must be final or NEEDS-USER")
            if next_owner in {"none", "user"}:
                raise ArchiveError("required discussion follow-up needs a phase owner")
            if target == "none":
                raise ArchiveError("required discussion follow-up needs a target artifact")
            pending_answers.add(answer_key)
        answer_threads[identifier] = thread

    disposition_sections = record_sections(
        answer_lines, DISPOSITION_HEADING_PATTERN, answer_boundaries
    )
    disposition_ids = [int(match.group(1)) for match, _ in disposition_sections]
    if disposition_ids:
        require_contiguous_ids(disposition_ids, "ANSWERS.md dispositions")
    seen_answers = set()
    for match, section in disposition_sections:
        require_iso_date(match.group(2), "ANSWERS.md disposition")
        answer = completed_bullet_field(section, "Answer", "ANSWERS.md")
        if not re.fullmatch(r"A\d{3}", answer) or int(answer[1:]) not in answer_ids:
            raise ArchiveError("discussion disposition references an unknown answer")
        if answer in seen_answers:
            raise ArchiveError("discussion answer has multiple dispositions")
        seen_answers.add(answer)
        disposition = completed_bullet_field(section, "Status", "ANSWERS.md")
        if disposition not in {
            "applied",
            "acknowledged-no-change",
            "superseded",
            "rejected-by-user",
        }:
            raise ArchiveError("discussion disposition has an invalid Status")
        receipt = require_bullet_fields(
            section, "ANSWERS.md", ("Owner", "Artifact", "Evidence")
        )
        expected_owner, expected_artifact = answer_receipts[answer]
        expected_owner = (
            "user" if disposition == "rejected-by-user" else expected_owner
        )
        if receipt["Owner"] != expected_owner:
            raise ArchiveError(
                f"discussion disposition owner must be {expected_owner} for {answer}"
            )
        if receipt["Artifact"] != expected_artifact:
            raise ArchiveError(
                "discussion disposition artifact must match the answer target "
                f"for {answer}"
            )
    unresolved = sorted(pending_answers - seen_answers)
    if require_dispositions and unresolved:
        raise ArchiveError(
            f"discussion follow-up lacks a disposition receipt: {', '.join(unresolved)}"
        )


def require_append_only_discussion(
    source: Path,
    destination: Path,
    *,
    require_dispositions: bool = True,
) -> None:
    validate_discussion_directory(source, require_dispositions=require_dispositions)
    validate_discussion_directory(destination, require_dispositions=require_dispositions)
    for name in DISCUSSION_FILES:
        active = (source / name).read_bytes()
        archived = (destination / name).read_bytes()
        if not active.startswith(archived):
            raise ArchiveError(f"active discussion is not an append-only extension of archived {name}")


def reconcile_append_only_discussion(active_root: Path, archive: Path) -> None:
    source = active_root / "discuss"
    destination = archive / "discuss"
    if not source.exists() or not destination.exists():
        return
    require_append_only_discussion(source, destination)
    transaction = active_root / DISCUSSION_TRANSACTION_NAME
    payload = {
        "schema": "gsd-path/discussion-archive/v1",
        "archive": str(archive.resolve()),
        "files": {
            name: (source / name).read_text(encoding="utf-8")
            for name in DISCUSSION_FILES
        },
    }
    atomic_write(transaction, json.dumps(payload, sort_keys=True) + "\n")
    finish_discussion_reconciliation(active_root, archive)


def require_safe_discussion_destination(
    active_root: Path, archive: Path, destination: Path
) -> None:
    archive_root = active_root / "archive"
    if active_root.is_symlink() or not active_root.is_dir():
        raise ArchiveError("discussion reconciliation requires a real .project directory")
    if archive_root.is_symlink() or not archive_root.is_dir():
        raise ArchiveError("discussion reconciliation requires a real archive root")
    if archive.is_symlink() or not archive.is_dir():
        raise ArchiveError("discussion reconciliation requires a real archive directory")
    if archive.resolve().parent != archive_root.resolve():
        raise ArchiveError("discussion reconciliation archive escapes the archive root")
    if destination.is_symlink() or not destination.is_dir():
        raise ArchiveError("discussion reconciliation destination must be a real directory")
    if destination.resolve().parent != archive.resolve():
        raise ArchiveError("discussion reconciliation destination escapes the archive")


def finish_discussion_reconciliation(active_root: Path, archive: Path) -> None:
    transaction = active_root / DISCUSSION_TRANSACTION_NAME
    if not transaction.exists():
        return
    if transaction.is_symlink() or not transaction.is_file():
        raise ArchiveError("discussion reconciliation journal must be a real file")
    try:
        payload = json.loads(transaction.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchiveError(f"discussion reconciliation journal is unreadable: {error}") from error
    if payload.get("schema") != "gsd-path/discussion-archive/v1":
        raise ArchiveError("discussion reconciliation journal has the wrong schema")
    if payload.get("archive") != str(archive.resolve()):
        raise ArchiveError("discussion reconciliation journal targets another archive")
    files = payload.get("files")
    if (
        not isinstance(files, dict)
        or set(files) != set(DISCUSSION_FILES)
        or any(not isinstance(files[name], str) for name in DISCUSSION_FILES)
    ):
        raise ArchiveError("discussion reconciliation journal has invalid files")
    source = active_root / "discuss"
    if source.exists():
        validate_discussion_directory(source)
        active_files = {
            name: (source / name).read_text(encoding="utf-8")
            for name in DISCUSSION_FILES
        }
        if any(not active_files[name].startswith(files[name]) for name in DISCUSSION_FILES):
            raise ArchiveError("active discussion diverged during archive reconciliation")
        if active_files != files:
            files = active_files
            payload["files"] = files
            atomic_write(transaction, json.dumps(payload, sort_keys=True) + "\n")
    destination = archive / "discuss"
    require_safe_discussion_destination(active_root, archive, destination)
    for name in DISCUSSION_FILES:
        temporary = destination / f".{name}.gsd-path-tmp"
        atomic_replace(destination / name, temporary, files[name])
    validate_discussion_directory(destination)
    if source.exists():
        shutil.rmtree(source)
    transaction.unlink()


def remove_interrupted_discussion_copies(active_root: Path, archive: Path) -> None:
    if not (active_root / "discuss").exists():
        return
    directory = archive / "discuss"
    if directory.exists() or directory.is_symlink():
        require_safe_discussion_destination(active_root, archive, directory)
    for name in DISCUSSION_FILES:
        temporary = directory / f".{name}.gsd-path-tmp"
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def remove_interrupted_carry_copy(active_root: Path, archive: Path) -> None:
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    if pending_ruling_count(archived_audit) == 0:
        return
    temporary_path = active_root / "research" / CARRY_TEMP_NAME
    if temporary_path.exists() or temporary_path.is_symlink():
        temporary_path.unlink()


def require_transaction_context(
    project: Path, state: PipelineState, phases: Sequence[str]
) -> None:
    phase = state.phase
    if phase not in phases:
        raise ArchiveError(f"archive transaction is not valid in phase: {phase}")

    repository_root = require_git_success(
        run_git(project, "rev-parse", "--show-toplevel"),
        "resolve Git root",
    )
    if Path(repository_root).resolve() != project:
        raise ArchiveError(f"--repo must be the Git worktree root: {repository_root}")

    expected_branch = state.branch
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


def completed_bullet_field(lines: Sequence[str], field: str, artifact: str) -> str:
    pattern = re.compile(rf"^- \*\*{re.escape(field)}\*\*:\s*(.*)$")
    values = []
    for line in lines:
        match = pattern.fullmatch(line)
        if match:
            values.append(match.group(1).strip().strip("`"))
    if len(values) != 1 or not values[0] or contains_placeholder(values[0]):
        raise ArchiveError(f"{artifact} requires one completed {field} field")
    return values[0]


def section_lines(lines: Sequence[str], heading: str, artifact: str) -> Sequence[str]:
    if lines.count(heading) != 1:
        raise ArchiveError(f"{artifact} requires one {heading} section")
    start = lines.index(heading) + 1
    end = next(
        (index for index in range(start, len(lines)) if lines[index].startswith("## ")),
        len(lines),
    )
    return lines[start:end]


def archived_intent_criteria(archive: Path) -> dict[int, str]:
    intent = archive / "intent" / "INTENT.md"
    if not is_real_file(intent):
        raise ArchiveError("archived intent must be a real INTENT.md file")
    text = HTML_COMMENT_PATTERN.sub("", intent.read_text(encoding="utf-8"))
    lines = text.splitlines()
    section = section_lines(lines, "## Success criteria", "INTENT.md")
    criteria = {}
    for line in section:
        match = INTENT_CRITERION_PATTERN.fullmatch(line.strip())
        if match is None:
            continue
        number = int(match.group(1))
        if number in criteria:
            raise ArchiveError(f"INTENT.md repeats success criterion SC{number}")
        criteria[number] = " ".join(match.group(2).split())
    if not criteria or sorted(criteria) != list(range(1, max(criteria) + 1)):
        raise ArchiveError("INTENT.md success criteria must be contiguous from SC1")
    return criteria


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
    intent_criteria = archived_intent_criteria(archive)
    if len(headings) != len(intent_criteria):
        raise ArchiveError("FINAL.md success criteria do not exactly cover INTENT.md")
    for _, number, criterion in headings:
        if " ".join(criterion.split()) != intent_criteria[number]:
            raise ArchiveError(
                f"FINAL.md SC{number} heading text differs from archived INTENT.md"
            )

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
        risk = completed_field(lines, "Risk:", path.name)
        if risk.casefold() == "none":
            raise ArchiveError(f"{path.name} does not name a completed risk")
        if (
            " ".join(headings[0].group(2).split()).casefold()
            != " ".join(risk.split()).casefold()
        ):
            raise ArchiveError(f"{path.name} heading risk does not match Risk field")
        completed_field(lines, "Waves checked:", path.name)
        evidence = section_lines(lines, "## Checked evidence", path.name)
        check = completed_bullet_field(evidence, "Check", path.name)
        observed = completed_bullet_field(evidence, "Observed", path.name)
        reference = completed_bullet_field(evidence, "Reference", path.name)
        if observed.casefold() == "none":
            raise ArchiveError(f"{path.name} checked evidence has no observed result")
        if check.casefold() == "none" and reference.casefold() == "none":
            raise ArchiveError(f"{path.name} checked evidence has no command or reference")
        finding = section_lines(lines, "## Finding", path.name)
        found = completed_bullet_field(finding, "Found", path.name)
        fix_direction = completed_bullet_field(finding, "Fix direction", path.name)
        if found.casefold() == "none":
            raise ArchiveError(f"{path.name} finding has no observed result")
        if fix_direction.casefold() != "none":
            raise ArchiveError(f"{path.name} pass must use Fix direction: none")


def meaningful_review_evidence(lines: Sequence[str], marker: str) -> bool:
    prefix = f"- {marker} "
    evidence = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        evidence.append(stripped.removeprefix(prefix).strip().strip("`"))
    return bool(evidence) and all(
        item
        and item.casefold() not in {"none", "n/a", "null"}
        and "<" not in item
        and ">" not in item
        for item in evidence
    )


def archived_wave_tasks(
    archive: Path, wave_numbers: Sequence[int]
) -> dict[int, Sequence[tuple[str, str]]]:
    tasks: dict[int, list[tuple[str, str]]] = {
        wave: [] for wave in wave_numbers
    }
    seen = set()
    for path in canonical_task_files(archive / "tasks"):
        content = path.read_text(encoding="utf-8")
        task_id = frontmatter_value(content, "id")
        title = frontmatter_value(content, "title")
        wave_text = frontmatter_value(content, "wave")
        if task_id is None or title is None or wave_text is None:
            raise ArchiveError(f"{path.name} is missing id, title, or wave")
        if task_id in seen or not path.name.startswith(f"{task_id}-"):
            raise ArchiveError(f"{path.name} has an invalid or repeated task id")
        seen.add(task_id)
        try:
            wave = int(wave_text)
        except ValueError as error:
            raise ArchiveError(f"{path.name} has an invalid wave") from error
        if wave not in tasks:
            raise ArchiveError(f"{path.name} names unknown Wave {wave}")
        if contains_placeholder(title):
            raise ArchiveError(f"{path.name} has an incomplete title")
        tasks[wave].append((task_id, title))
    for wave, members in tasks.items():
        if not members:
            raise ArchiveError(f"plan Wave {wave} has no task files")
    return tasks


def plan_wave_criteria(
    archive: Path,
    plan_text: str,
    wave_tasks: dict[int, Sequence[tuple[str, str]]],
) -> dict[int, Sequence[tuple[str, str]]]:
    intent_path = archive / "intent" / "INTENT.md"
    if not intent_path.exists() and not intent_path.is_symlink():
        return {wave: () for wave in wave_tasks}
    criteria = archived_intent_criteria(archive)
    lines = plan_text.splitlines()
    if lines.count("## Intent coverage") != 1:
        raise ArchiveError("PLAN.md requires one Intent coverage section")
    coverage = section_lines(lines, "## Intent coverage", "PLAN.md")
    rows = []
    for line in coverage:
        if not re.match(r"^\|\s*SC\d", line.strip()):
            continue
        match = PLAN_COVERAGE_ROW_PATTERN.fullmatch(line.strip())
        if match is None:
            raise ArchiveError("PLAN.md has a malformed Intent coverage row")
        rows.append((match.group(1), match.group(2), match.group(3).strip()))
    if not rows:
        raise ArchiveError("PLAN.md Intent coverage has no rows")
    known_tasks = {
        task_id for tasks in wave_tasks.values() for task_id, _title in tasks
    }
    seen = set()
    for sc_id, task_id, acceptance in rows:
        number = int(sc_id.removeprefix("SC"))
        if number not in criteria:
            raise ArchiveError(f"PLAN.md Intent coverage names unknown {sc_id}")
        if task_id not in known_tasks:
            raise ArchiveError(f"PLAN.md Intent coverage names unknown {task_id}")
        if not acceptance or contains_placeholder(acceptance):
            raise ArchiveError("PLAN.md Intent coverage has incomplete acceptance evidence")
        if (sc_id, task_id, acceptance) in seen:
            raise ArchiveError("PLAN.md Intent coverage repeats a row")
        seen.add((sc_id, task_id, acceptance))
    result = {}
    for wave, tasks in wave_tasks.items():
        task_ids = {task_id for task_id, _title in tasks}
        owned_numbers = sorted(
            {
                int(sc_id.removeprefix("SC"))
                for sc_id, task_id, _acceptance in rows
                if task_id in task_ids
            }
        )
        result[wave] = tuple(
            (f"SC{number}", criteria[number]) for number in owned_numbers
        )
    return result


def validate_wave_review(
    path: Path,
    expected_tasks: Sequence[tuple[str, str]],
    expected_criteria: Sequence[tuple[str, str]],
    expected_depth: str,
    expected_lens: Optional[str] = None,
) -> Sequence[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    depth = completed_field(lines, "Depth:", path.name)
    if depth != expected_depth:
        raise ArchiveError(f"{path.name} has an invalid review depth")
    if expected_lens is not None:
        lens = completed_field(lines, "Lens:", path.name)
        if lens != expected_lens:
            raise ArchiveError(f"{path.name} Lens field does not match its filename")
    wave_verdict = completed_field(lines, "Wave verdict:", path.name)
    reviewed = completed_field(lines, "Tasks reviewed:", path.name)
    if not reviewed.isdigit() or int(reviewed) < 1:
        raise ArchiveError(f"{path.name} requires a positive task count")

    headings = []
    for index, line in enumerate(lines):
        match = WAVE_TASK_HEADING_PATTERN.fullmatch(line)
        if match:
            headings.append((index, match.group(1), match.group(2), match.group(3)))
    if len(headings) != int(reviewed):
        raise ArchiveError(f"{path.name} task count does not match Tasks reviewed")
    task_ids = [task_id for _, task_id, _, _ in headings]
    if len(task_ids) != len(set(task_ids)):
        raise ArchiveError(f"{path.name} repeats a reviewed task")
    actual_tasks = [(task_id, " ".join(title.split())) for _, task_id, title, _ in headings]
    normalized_expected = [
        (task_id, " ".join(title.split())) for task_id, title in expected_tasks
    ]
    if actual_tasks != normalized_expected:
        raise ArchiveError(
            f"{path.name} tasks and titles do not match its wave task files in order"
        )

    verdicts = []
    for position, (heading_index, _task_id, _title, verdict) in enumerate(headings):
        next_task = (
            headings[position + 1][0]
            if position + 1 < len(headings)
            else len(lines)
        )
        next_section = next(
            (
                index
                for index in range(heading_index + 1, next_task)
                if lines[index].startswith("## ")
            ),
            next_task,
        )
        task_lines = lines[heading_index + 1 : next_section]
        marker = "✅" if verdict == "pass" else "❌"
        if not meaningful_review_evidence(task_lines, marker):
            raise ArchiveError(
                f"{path.name} task {task_ids[position]} lacks non-placeholder evidence"
            )
        verdicts.append(verdict)

    coverage_indexes = [
        index for index, line in enumerate(lines) if line == "## Intent coverage"
    ]
    if not expected_criteria:
        if coverage_indexes:
            start = coverage_indexes[0] + 1
            end = next(
                (
                    index
                    for index in range(start, len(lines))
                    if lines[index].startswith("## ")
                ),
                len(lines),
            )
            if any(WAVE_SC_HEADING_PATTERN.fullmatch(line) for line in lines[start:end]):
                raise ArchiveError(f"{path.name} names unowned success criteria")
        return verdicts
    if len(coverage_indexes) != 1:
        raise ArchiveError(f"{path.name} requires one Intent coverage section")
    coverage_start = coverage_indexes[0] + 1
    coverage_end = next(
        (
            index
            for index in range(coverage_start, len(lines))
            if lines[index].startswith("## ")
        ),
        len(lines),
    )
    criterion_headings = []
    for index in range(coverage_start, coverage_end):
        line = lines[index]
        if not line.startswith("### "):
            continue
        match = WAVE_SC_HEADING_PATTERN.fullmatch(line)
        if match is None:
            raise ArchiveError(f"{path.name} has an invalid Intent coverage heading")
        criterion_headings.append(
            (index, match.group(1), " ".join(match.group(2).split()), match.group(3))
        )
    actual = [(sc_id, text) for _, sc_id, text, _ in criterion_headings]
    normalized_expected_criteria = [
        (sc_id, " ".join(text.split())) for sc_id, text in expected_criteria
    ]
    if actual != normalized_expected_criteria:
        raise ArchiveError(
            f"{path.name} Intent coverage does not match its owned success criteria"
        )
    for position, (heading_index, sc_id, _text, verdict) in enumerate(
        criterion_headings
    ):
        section_end = (
            criterion_headings[position + 1][0]
            if position + 1 < len(criterion_headings)
            else coverage_end
        )
        marker = "✅" if verdict == "pass" else "❌"
        if not meaningful_review_evidence(
            lines[heading_index + 1 : section_end], marker
        ):
            raise ArchiveError(f"{path.name} {sc_id} lacks non-placeholder evidence")
        if verdict == "fail" and wave_verdict == "pass":
            raise ArchiveError(
                f"{path.name} passes while owned success criterion {sc_id} fails"
            )
    return verdicts


def review_cycle_counts(archive: Path) -> Sequence[int]:
    plan = archive / "plan" / "PLAN.md"
    plan_text = plan.read_text(encoding="utf-8")
    wave_matches = list(re.finditer(r"^## Wave (\d+)\b", plan_text, re.MULTILINE))
    wave_numbers = [int(match.group(1)) for match in wave_matches]
    if not wave_numbers or wave_numbers != list(range(1, len(wave_numbers) + 1)):
        raise ArchiveError("plan wave numbers must be ordered and contiguous")
    wave_depths = {}
    for index, match in enumerate(wave_matches):
        section_end = (
            wave_matches[index + 1].start()
            if index + 1 < len(wave_matches)
            else len(plan_text)
        )
        section = plan_text[match.end() : section_end]
        depths = re.findall(
            r"^Review depth:\s*(\S+)",
            section,
            re.MULTILINE,
        )
        wave = int(match.group(1))
        if len(depths) > 1:
            raise ArchiveError(f"plan wave {wave} has multiple review depths")
        depth = depths[0] if depths else "full"
        if depth not in {"full", "deep", "verify-only"}:
            raise ArchiveError(f"plan wave {wave} has an invalid review depth")
        wave_depths[wave] = depth
    wave_tasks = archived_wave_tasks(archive, wave_numbers)
    wave_criteria = plan_wave_criteria(archive, plan_text, wave_tasks)

    artifacts = {}
    panel_config = plan_review_panel_config(plan_text)
    panel_skip_receipts = canonical_wave_panel_skip_files(archive / "review")
    for path, wave, cycle, lens in canonical_wave_files(archive / "review"):
        if lens == "panel":
            artifacts.setdefault(wave, {}).setdefault(cycle, {})[lens] = path
            continue
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
        artifacts.setdefault(wave, {}).setdefault(cycle, {})[lens] = path
    if sorted(artifacts) != wave_numbers:
        raise ArchiveError("review cycle waves do not match PLAN.md")

    counts = []
    for wave in wave_numbers:
        cycles = artifacts[wave]
        if sorted(cycles) != list(range(1, max(cycles) + 1)):
            raise ArchiveError(f"review cycles for wave {wave} are not contiguous")
        wave_verdicts = {}
        task_verdicts = {}
        for cycle, reviews in cycles.items():
            depth = wave_depths[wave]
            gate = {lens: path for lens, path in reviews.items() if lens != "panel"}
            if depth == "deep":
                if set(gate) != {"contract", "adversarial"}:
                    raise ArchiveError(
                        f"wave {wave} cycle {cycle} requires contract and adversarial "
                        "reviews for PLAN depth deep"
                    )
                expected = tuple(
                    (gate[lens], depth, lens) for lens in ("contract", "adversarial")
                )
            else:
                if set(gate) != {None}:
                    raise ArchiveError(
                        f"wave {wave} cycle {cycle} requires one base review "
                        f"for PLAN depth {depth}"
                    )
                expected = ((gate[None], depth, None),)
            receipt = panel_skip_receipts.pop((wave, cycle), None)
            if panel_config["mode"] != "off" and depth in {"full", "deep"}:
                has_panel = "panel" in reviews
                if has_panel == (receipt is not None):
                    raise ArchiveError(
                        f"wave {wave} cycle {cycle} requires exactly one panel artifact "
                        "or canonical skipped-panel receipt"
                    )
                if receipt is not None:
                    validate_panel_skip_receipt(
                        receipt, str(panel_config["mode"])
                    )
            elif receipt is not None:
                raise ArchiveError(f"unexpected skipped-panel receipt: {receipt.name}")

            wave_verdicts[cycle] = []
            task_verdicts[cycle] = []
            for path, depth, lens in expected:
                lines = path.read_text(encoding="utf-8").splitlines()
                wave_verdicts[cycle].append(completed_field(lines, "Wave verdict:", path.name))
                task_verdicts[cycle].extend(
                    validate_wave_review(
                        path,
                        wave_tasks[wave],
                        wave_criteria[wave],
                        depth,
                        lens,
                    )
                )

        last_cycle = max(cycles)
        if any(verdict != "pass" for verdict in wave_verdicts[last_cycle]):
            raise ArchiveError(f"last review cycle for wave {wave} did not pass")
        if any(task_verdict != "pass" for task_verdict in task_verdicts[last_cycle]):
            raise ArchiveError(f"last review cycle for wave {wave} has a failed task")
        counts.append(last_cycle)
    if panel_skip_receipts:
        names = ", ".join(path.name for path in panel_skip_receipts.values())
        raise ArchiveError(f"skipped-panel receipts do not match review cycles: {names}")
    return counts


def manifest_cell(value: str) -> str:
    return value.replace("\\|", "|").replace("|", "\\|")


def archive_file_inventory(archive: Path) -> Sequence[str]:
    contents = []
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise ArchiveError(f"archive contents must not be symlinks: {path}")
        if path.is_file() and path.name != "MANIFEST.md":
            contents.append(path.relative_to(archive).as_posix())
    return sorted(contents)


def render_manifest(repo: Path) -> dict:
    project = repo.resolve()
    active_root = require_project_layout(project)
    state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    require_transaction_context(project, state, ("ship", "shipped"))
    phase = state.phase
    status = state.status
    if (phase, status) not in {("ship", "active"), ("shipped", "done")}:
        raise ArchiveError(
            "manifest rendering requires ship/active or uncommitted shipped/done"
        )

    configured = state.archive
    if configured is None:
        raise ArchiveError("STATE.md does not name the archive transaction")
    archive = archive_from_state(project, configured)
    require_archive_milestone(archive.name, state)
    require_uncommitted_archive(project, configured)
    if archive.is_symlink() or not archive.is_dir():
        raise ArchiveError("archive is missing")
    require_canonical_archive(archive)
    require_clean_active_root(active_root, archive)

    reviewed_head, criteria = parse_final_review(archive)
    validate_gap_reviews(archive, reviewed_head)
    tasks = completed_task_files(project, archive / "tasks", reviewed_head)
    cycles = review_cycle_counts(archive)
    carried_forward = pending_ruling_count(archive / "research" / "DOCS-AUDIT.md")
    carry_text = (
        "none"
        if carried_forward == 0
        else f"{carried_forward} DOCS-AUDIT ruling(s)"
    )
    criteria_rows = "\n".join(
        f"| {manifest_cell(criterion)} | {verdict} | {manifest_cell(evidence)} |"
        for criterion, verdict, evidence in criteria
    )
    listed_contents = "\n".join(f"- {path}" for path in archive_file_inventory(archive))
    cycle_text = "/".join(str(cycle) for cycle in cycles)
    count_text = (
        f"{len(cycles)}  Tasks: {len(tasks)} done / {len(tasks)} total  "
        f"Review cycles used: {cycle_text}"
    )
    content = f"""# Archive — {archive.name}

Milestone: {state.milestone}
Shipped: {date.today().isoformat()}
Final verdict: all criteria met; project verify passed
Waves: {count_text}
Carried forward: {carry_text}

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
{criteria_rows}

## Contents

{listed_contents}

## Notes

- none
"""
    atomic_replace(archive / "MANIFEST.md", archive / MANIFEST_TEMP_NAME, content)
    validate_manifest(project, archive, state)
    return {"archive": configured, "reviewed_head": reviewed_head}


def validate_manifest(project: Path, archive: Path, state: PipelineState) -> tuple:
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

    milestone = state.milestone
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

    reviewed_head, final_criteria = parse_final_review(archive)
    validate_gap_reviews(archive, reviewed_head)
    task_files = completed_task_files(project, archive / "tasks", reviewed_head)
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

    actual = archive_file_inventory(archive)
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
    with discussion_lock(active_root):
        return prepare_locked(project, active_root, slug)


def prepare_locked(project: Path, active_root: Path, slug: str) -> dict:
    state_path = active_root / "STATE.md"
    state_temporary = active_root / STATE_TEMP_NAME

    parsed_state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != state_path.resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    require_transaction_context(project, parsed_state, ("ship", "shipped"))
    phase = parsed_state.phase
    status = parsed_state.status
    if (phase, status) not in {("ship", "active"), ("shipped", "done")}:
        raise ArchiveError(f"archive transaction is not valid in state: {phase}/{status}")
    expected_slug = milestone_slug(parsed_state)
    if normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )
    configured = parsed_state.archive
    if phase == "shipped" and configured is None:
        raise ArchiveError("shipped state has no persisted archive transaction")
    if configured is not None:
        relative_archive = archive_relative_from_state(configured)
        require_archive_milestone(relative_archive.name, parsed_state)
        require_uncommitted_archive(project, configured)
    if state_temporary.exists() or state_temporary.is_symlink():
        state_temporary.unlink()

    archive = persisted_archive(project, state_path, slug, parsed_state)
    require_archive_milestone(archive.name, parsed_state)
    archive.mkdir(parents=True, exist_ok=True)
    manifest_temporary = archive / MANIFEST_TEMP_NAME
    if manifest_temporary.exists() or manifest_temporary.is_symlink():
        manifest_temporary.unlink()

    remove_interrupted_carry_copy(active_root, archive)
    remove_interrupted_discussion_copies(active_root, archive)
    finish_discussion_reconciliation(active_root, archive)
    require_complete_transaction_inputs(active_root, archive)
    require_canonical_transaction_inputs(active_root, archive)
    require_safe_move_inputs(active_root, archive)
    reconcile_append_only_discussion(active_root, archive)
    for name in TRANSACTION_DIRECTORIES:
        move_directory(active_root / name, archive / name)

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


def require_complete_abandon_inputs(active_root: Path, archive: Path) -> None:
    for name in ABANDON_REQUIRED_DIRECTORIES:
        source = active_root / name
        destination = archive / name
        if source.exists() and destination.exists():
            if name == "research" and is_existing_carry_forward(source, destination):
                continue
            raise ArchiveError(f"archive collision: both {source} and {destination} exist")
        if not source.exists() and not destination.exists():
            raise ArchiveError(f"missing both active and archived {name}")

    review_source = active_root / "review"
    review_destination = archive / "review"
    if review_source.exists() and review_destination.exists():
        raise ArchiveError(
            f"archive collision: both {review_source} and {review_destination} exist"
        )

    for name in OPTIONAL_DIRECTORIES_TO_ARCHIVE:
        source = active_root / name
        destination = archive / name
        if source.exists() and destination.exists():
            require_append_only_discussion(source, destination)


def require_canonical_abandon_inputs(active_root: Path, archive: Path) -> None:
    missing = [
        relative
        for relative in ABANDON_REQUIRED_ARCHIVE_FILES
        if not is_real_file(selected_transaction_path(active_root, archive, relative))
    ]
    tasks = selected_transaction_path(active_root, archive, "tasks")
    if tasks.is_symlink() or not tasks.is_dir():
        missing.append("tasks/")
    else:
        canonical_task_files(tasks)
    reviews = selected_transaction_path(active_root, archive, "review")
    if reviews.exists():
        canonical_wave_files(reviews)
    if missing:
        raise ArchiveError(f"canonical milestone artifacts are missing: {', '.join(missing)}")
    discussion = selected_transaction_path(active_root, archive, "discuss")
    if discussion.exists():
        validate_discussion_directory(discussion)


def write_abandon_manifest(
    archive: Path, slug: str, ruling: str, abandoned_on: str
) -> None:
    contents = []
    for path in archive.rglob("*"):
        if path.is_symlink():
            raise ArchiveError(f"archive contents must not be symlinks: {path}")
        if path.is_file() and path.name != "MANIFEST.md":
            contents.append(path.relative_to(archive).as_posix())
    contents.sort()
    listed_contents = "\n".join(f"- {path}" for path in contents)
    atomic_replace(
        archive / "MANIFEST.md",
        archive / MANIFEST_TEMP_NAME,
        f"""# Archive — {archive.name}

Milestone: {slug}
Abandoned: {abandoned_on}
Reason: {ruling}

## Contents

{listed_contents}

## Notes

- none
""",
    )


def validate_abandon_manifest(
    archive: Path, slug: str, ruling: str, abandoned_on: str
) -> None:
    manifest = archive / "MANIFEST.md"
    if manifest.is_symlink() or not manifest.is_file():
        raise ArchiveError("abandoned archive MANIFEST.md must be a real file")
    lines = manifest.read_text(encoding="utf-8").splitlines()
    if lines.count(f"# Archive — {archive.name}") != 1:
        raise ArchiveError("abandon manifest header does not match its archive")
    expected_fields = {
        "Milestone:": slug,
        "Abandoned:": abandoned_on,
        "Reason:": ruling,
    }
    for field, expected in expected_fields.items():
        if completed_field(lines, field, "abandon manifest") != expected:
            raise ArchiveError(f"abandon manifest {field} does not match its transaction")
    try:
        date.fromisoformat(abandoned_on)
    except ValueError as error:
        raise ArchiveError("abandon manifest date is invalid") from error
    if lines.count("## Contents") != 1 or lines.count("## Notes") != 1:
        raise ArchiveError("abandon manifest requires Contents and Notes sections")
    contents_start = lines.index("## Contents") + 1
    listed = []
    for line in lines[contents_start:]:
        if line.startswith("## "):
            break
        if line.startswith("- "):
            listed.append(line[2:].strip().strip("`"))
    if len(listed) != len(set(listed)) or sorted(listed) != archive_file_inventory(archive):
        raise ArchiveError("abandon manifest contents do not match the archive")


def abandon_journal_path(project: Path) -> Path:
    common = require_git_success(
        run_git(project, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        "resolve common Git directory",
    )
    path = Path(common)
    if not path.is_absolute():
        path = project / path
    return path.resolve() / ABANDON_JOURNAL_NAME


def read_abandon_journal(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchiveError(f"abandon journal is unreadable: {path}") from error
    fields = {
        "schema",
        "repo",
        "slug",
        "ruling",
        "expected_head",
        "archive",
        "branch",
        "build_status",
        "abandoned_on",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ArchiveError("abandon journal has invalid fields")
    if payload["schema"] != ABANDON_JOURNAL_SCHEMA or any(
        not isinstance(payload[field], str) for field in fields - {"schema"}
    ):
        raise ArchiveError("abandon journal has invalid values")
    if (
        not re.fullmatch(r"[0-9a-f]{40,64}", payload["expected_head"])
        or payload["build_status"] not in {"active", "blocked"}
        or not is_bound_branch(payload["branch"])
    ):
        raise ArchiveError("abandon journal has invalid transaction metadata")
    try:
        date.fromisoformat(payload["abandoned_on"])
    except ValueError as error:
        raise ArchiveError("abandon journal has invalid transaction date") from error
    return payload


def write_abandon_journal(path: Path, payload: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    atomic_replace(path, temporary, json.dumps(payload, sort_keys=True) + "\n")


def require_abandon_request(
    project: Path, journal: dict, slug: str, ruling: str
) -> None:
    expected = {
        "repo": str(project),
        "slug": slug,
        "ruling": ruling,
    }
    mismatches = [
        key
        for key, value in expected.items()
        if journal[key] != value
    ]
    if mismatches:
        raise ArchiveError(
            "abandon request differs from journal fields: "
            + ", ".join(sorted(mismatches))
        )
    resolved = run_git(
        project,
        "rev-parse",
        "--verify",
        "--quiet",
        f"{journal['expected_head']}^{{commit}}",
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != journal["expected_head"]:
        raise ArchiveError("abandon journal expected HEAD no longer resolves")


def update_abandoned_roadmap(
    path: Path,
    archive_name: str,
    slug: str,
    configured: str,
    *,
    write: bool = True,
) -> None:
    if path.is_symlink() or not path.is_file():
        raise ArchiveError(f"milestone abandon requires a real ROADMAP.md: {path}")
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    headings = []
    for index, line in enumerate(lines):
        match = ROADMAP_HEADING_PATTERN.fullmatch(line.rstrip("\r\n"))
        if match is None:
            continue
        if int(match.group(1).removeprefix("M")) < 1:
            raise ArchiveError("ROADMAP milestone number must be >= 1")
        headings.append((index, match.group(1), match.group(2)))
    identifier = milestone_id(milestone_number(archive_name))
    matches = [item for item in headings if item[1:] == (identifier, slug)]
    if len(matches) != 1:
        raise ArchiveError(
            f"ROADMAP.md requires one exact {identifier} — {slug} milestone entry"
        )
    start = matches[0][0]
    end = next((index for index, _, _ in headings if index > start), len(lines))
    status_indexes = [
        index for index in range(start + 1, end) if lines[index].startswith("Status:")
    ]
    archive_indexes = [
        index for index in range(start + 1, end) if lines[index].startswith("Archive:")
    ]
    if len(status_indexes) != 1 or len(archive_indexes) > 1:
        raise ArchiveError("ROADMAP milestone has ambiguous Status or Archive fields")
    status_index = status_indexes[0]
    status = lines[status_index].rstrip("\r\n")
    if status not in {"Status: active", "Status: abandoned"}:
        raise ArchiveError(f"ROADMAP milestone cannot be abandoned from {status!r}")
    lines[status_index] = "Status: abandoned\n"
    if archive_indexes:
        archive_index = archive_indexes[0]
        current = lines[archive_index].rstrip("\r\n")
        if current not in {"Archive: null", f"Archive: {configured}"}:
            raise ArchiveError("ROADMAP milestone Archive field conflicts with transaction")
        lines[archive_index] = f"Archive: {configured}\n"
    else:
        lines.insert(status_index + 1, f"Archive: {configured}\n")
    if not write:
        return
    temporary = path.with_name(f".{path.name}.gsd-path-tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    atomic_replace(path, temporary, "".join(lines))


def append_abandon_lesson(
    path: Path, archive_name: str, ruling: str, *, write: bool = True
) -> None:
    line = f"- {archive_name} — abandoned: {ruling}"
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise ArchiveError(f"LESSONS.md must be a real file: {path}")
        text = path.read_text(encoding="utf-8")
    else:
        text = "# Lessons\n"
    matches = [
        value
        for value in text.splitlines()
        if value.startswith(f"- {archive_name} — abandoned:")
    ]
    if matches and matches != [line]:
        raise ArchiveError("LESSONS.md has a conflicting abandon ruling")
    if matches == [line]:
        return
    if not write:
        raise ArchiveError("LESSONS.md is missing the canonical abandon ruling")
    rendered = text.rstrip() + f"\n\n{line}\n"
    temporary = path.with_name(f".{path.name}.gsd-path-tmp")
    if temporary.exists() or temporary.is_symlink():
        temporary.unlink()
    atomic_replace(path, temporary, rendered)


def completed_abandon(
    project: Path, active_root: Path, slug: str, ruling: str, state: PipelineState
) -> dict:
    if not (
        state.phase == "roadmap"
        and state.status == "active"
        and state.milestone is None
        and state.archive is None
        and state.branch is not None
    ):
        raise ArchiveError(
            f"milestone abandon is not valid in state: {state.phase}/{state.status}"
        )
    require_transaction_context(project, state, ("roadmap",))
    number = milestone_number(state.branch)
    archive_name = f"{number:03d}-{slug}"
    configured = f".project/archive/{archive_name}"
    archive = archive_from_state(project, configured)
    if archive.is_symlink() or not archive.is_dir():
        raise ArchiveError("completed abandoned archive is missing")
    manifest = archive / "MANIFEST.md"
    if manifest.is_symlink() or not manifest.is_file():
        raise ArchiveError("abandoned archive MANIFEST.md must be a real file")
    manifest_lines = manifest.read_text(encoding="utf-8").splitlines()
    abandoned_on = completed_field(manifest_lines, "Abandoned:", "abandon manifest")
    validate_abandon_manifest(archive, slug, ruling, abandoned_on)
    update_abandoned_roadmap(
        active_root / "ROADMAP.md",
        archive_name,
        slug,
        configured,
        write=False,
    )
    append_abandon_lesson(
        active_root / "LESSONS.md", archive_name, ruling, write=False
    )
    head = require_git_success(run_git(project, "rev-parse", "HEAD"), "resolve HEAD")
    parent = require_git_success(
        run_git(project, "rev-parse", f"{head}^"), "resolve abandon checkpoint parent"
    )
    try:
        checkpoint = isolation_checkpoint(
            project,
            parent,
            f"build: abandon milestone {slug}",
            f"Why: {ruling}",
            [".project"],
        )
    except IsolationError as error:
        raise ArchiveError(f"completed abandon checkpoint is invalid: {error}") from error
    return {
        "archive": configured,
        "carried_forward": pending_ruling_count(
            archive / "research" / "DOCS-AUDIT.md"
        ),
        "commit": checkpoint["commit"],
        "status": checkpoint["status"],
    }


def abandon(repo: Path, slug: str, reason: str) -> dict:
    project = repo.resolve()
    active_root = require_project_layout(project)
    requested_slug = normalized_slug(slug)
    ruling = " ".join(reason.split())
    if not ruling:
        raise ArchiveError("milestone abandon requires a non-empty --reason ruling")
    journal_path = abandon_journal_path(project)
    if journal_path.is_symlink():
        raise ArchiveError(f"abandon journal must not be a symlink: {journal_path}")
    journal = read_abandon_journal(journal_path) if journal_path.is_file() else None
    if journal_path.exists() and journal is None:
        raise ArchiveError(f"abandon journal must be a real file: {journal_path}")
    if journal is not None:
        require_abandon_request(project, journal, requested_slug, ruling)
    else:
        state, _, _ = strict_state(project)
        if state.phase == "roadmap":
            with discussion_lock(active_root):
                return completed_abandon(
                    project, active_root, requested_slug, ruling, state
                )
    with discussion_lock(active_root):
        journal, carried_forward = abandon_locked(
            project,
            active_root,
            requested_slug,
            ruling,
            journal_path,
            journal,
        )

    try:
        state, _, _ = strict_state(project)
        if state.phase == "build":
            transition_state(
                project,
                expected={
                    "phase": "build",
                    "status": journal["build_status"],
                    "milestone": journal["slug"],
                    "branch": journal["branch"],
                    "archive": journal["archive"],
                },
                changes={
                    "phase": "roadmap",
                    "status": "active",
                    "milestone": None,
                    "archive": None,
                },
                event=(
                    f"milestone abandoned: {journal['slug']}; "
                    f"archive: {journal['archive']}; ruling: {journal['ruling']}"
                ),
            )
        elif not (
            state.phase == "roadmap"
            and state.status == "active"
            and state.milestone is None
            and state.branch == journal["branch"]
            and state.archive is None
        ):
            raise ArchiveError("abandon transaction has an invalid finalized STATE.md")

        finalized_state, _, _ = strict_state(project)
        require_transaction_context(project, finalized_state, ("roadmap",))
        checkpoint = isolation_checkpoint(
            project,
            journal["expected_head"],
            f"build: abandon milestone {journal['slug']}",
            f"Why: {journal['ruling']}",
            [".project"],
        )
    except (PipelineStateError, IsolationError) as error:
        raise ArchiveError(f"abandon finalization failed: {error}") from error

    journal_path.unlink()
    return {
        "archive": journal["archive"],
        "carried_forward": carried_forward,
        "commit": checkpoint["commit"],
        "status": checkpoint["status"],
    }


def abandon_locked(
    project: Path,
    active_root: Path,
    slug: str,
    ruling: str,
    journal_path: Path,
    journal: Optional[dict],
) -> tuple[dict, int]:
    state_path = active_root / "STATE.md"
    state_temporary = active_root / STATE_TEMP_NAME

    parsed_state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != state_path.resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    if not is_real_file(active_root / "ROADMAP.md"):
        raise ArchiveError(
            "milestone abandon requires program flow: missing .project/ROADMAP.md"
        )
    require_transaction_context(project, parsed_state, ("build", "roadmap"))
    if journal is None:
        if parsed_state.phase != "build" or parsed_state.status not in {"active", "blocked"}:
            raise ArchiveError(
                f"milestone abandon is not valid in state: "
                f"{parsed_state.phase}/{parsed_state.status}"
            )
        expected_slug = milestone_slug(parsed_state)
        if slug != expected_slug:
            raise ArchiveError(
                f"--slug {slug!r} does not match normalized "
                f"STATE.milestone {expected_slug!r}"
            )
        archive = resolved_archive_target(project, slug, parsed_state)
        configured = archive.relative_to(project).as_posix()
        expected_head = require_git_success(
            run_git(project, "rev-parse", "HEAD"), "resolve abandon base"
        )
        journal = {
            "schema": ABANDON_JOURNAL_SCHEMA,
            "repo": str(project),
            "slug": slug,
            "ruling": ruling,
            "expected_head": expected_head,
            "archive": configured,
            "branch": parsed_state.branch,
            "build_status": parsed_state.status,
            "abandoned_on": date.today().isoformat(),
        }
        write_abandon_journal(journal_path, journal)
    else:
        require_abandon_request(project, journal, slug, ruling)
        if parsed_state.branch != journal["branch"]:
            raise ArchiveError("STATE.branch differs from the abandon journal")

    configured = journal["archive"]
    if parsed_state.phase == "roadmap":
        archive = archive_from_state(project, configured)
        if not (
            parsed_state.status == "active"
            and parsed_state.milestone is None
            and parsed_state.archive is None
        ):
            raise ArchiveError("abandon transaction has an invalid finalized STATE.md")
        if archive.is_symlink() or not archive.is_dir():
            raise ArchiveError("abandoned archive is missing during checkpoint recovery")
        validate_abandon_manifest(
            archive,
            journal["slug"],
            journal["ruling"],
            journal["abandoned_on"],
        )
        update_abandoned_roadmap(
            active_root / "ROADMAP.md", archive.name, journal["slug"], configured
        )
        append_abandon_lesson(
            active_root / "LESSONS.md", archive.name, journal["ruling"]
        )
        require_clean_active_root(active_root, archive)
        return journal, pending_ruling_count(archive / "research" / "DOCS-AUDIT.md")

    if (
        parsed_state.status != journal["build_status"]
        or parsed_state.milestone != journal["slug"]
        or parsed_state.branch != journal["branch"]
    ):
        raise ArchiveError("build STATE.md differs from the abandon journal")
    update_abandoned_roadmap(
        active_root / "ROADMAP.md",
        PurePosixPath(configured).name,
        journal["slug"],
        configured,
        write=False,
    )
    if parsed_state.archive is not None:
        relative_archive = archive_relative_from_state(parsed_state.archive)
        require_archive_milestone(relative_archive.name, parsed_state)
        if parsed_state.archive != configured:
            raise ArchiveError("STATE.archive differs from the abandon journal")
        require_uncommitted_archive(project, configured)
    if state_temporary.exists() or state_temporary.is_symlink():
        state_temporary.unlink()

    archive = persisted_archive(project, state_path, slug, parsed_state)
    if archive.relative_to(project).as_posix() != configured:
        raise ArchiveError("persisted archive differs from the abandon journal")
    require_archive_milestone(archive.name, parsed_state)
    archive.mkdir(parents=True, exist_ok=True)
    manifest_temporary = archive / MANIFEST_TEMP_NAME
    if manifest_temporary.exists() or manifest_temporary.is_symlink():
        manifest_temporary.unlink()

    remove_interrupted_carry_copy(active_root, archive)
    remove_interrupted_discussion_copies(active_root, archive)
    finish_discussion_reconciliation(active_root, archive)
    require_complete_abandon_inputs(active_root, archive)
    require_canonical_abandon_inputs(active_root, archive)
    require_safe_move_inputs(active_root, archive)
    reconcile_append_only_discussion(active_root, archive)
    for name in TRANSACTION_DIRECTORIES:
        move_directory(active_root / name, archive / name)

    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    carried_forward = pending_ruling_count(archived_audit)
    if carried_forward:
        active_audit = active_root / "research" / "DOCS-AUDIT.md"
        active_audit.parent.mkdir(parents=True, exist_ok=True)
        if active_audit.exists() and not filecmp.cmp(active_audit, archived_audit, shallow=False):
            raise ArchiveError(f"carry-forward collision: {active_audit} differs from archived audit")
        if not active_audit.exists():
            atomic_copy(archived_audit, active_audit)

    write_abandon_manifest(
        archive,
        journal["slug"],
        journal["ruling"],
        journal["abandoned_on"],
    )
    validate_abandon_manifest(
        archive,
        journal["slug"],
        journal["ruling"],
        journal["abandoned_on"],
    )
    update_abandoned_roadmap(
        active_root / "ROADMAP.md", archive.name, journal["slug"], configured
    )
    append_abandon_lesson(
        active_root / "LESSONS.md", archive.name, journal["ruling"]
    )
    require_clean_active_root(active_root, archive)
    return journal, carried_forward


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
    plan = archive / "plan" / "PLAN.md"
    for directory in DIRECTORIES_TO_ARCHIVE:
        path = archive / directory
        if path.is_symlink() or not path.is_dir():
            missing.append(f"{directory}/")
    if missing:
        raise ArchiveError(f"canonical archive artifacts are missing: {', '.join(sorted(set(missing)))}")
    require_plan_panel_evidence(
        plan.read_text(encoding="utf-8"),
        archive / "review" / "PLAN-PANEL.md",
        archive / "review" / "PLAN-PANEL.skipped.json",
    )
    discussion = archive / "discuss"
    if discussion.exists() or discussion.is_symlink():
        validate_discussion_directory(discussion)


def require_clean_active_root(active_root: Path, archive: Path) -> None:
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    carried_forward = pending_ruling_count(archived_audit)
    # Persistent project metadata ships but never archives with a milestone.
    allowed = {"STATE.md", "REPOSITORY.md", "archive", "LESSONS.md", "next"}
    if (active_root / "CHARTER.md").is_file():
        # Program flow: these persist at the .project/ top level.
        allowed |= {"CHARTER.md", "ROADMAP.md", "SYNTHESIS.md"}
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

    state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != state_path.resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    require_transaction_context(project, state, phases)

    configured = state.archive
    if configured is None:
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
    archived_files, reviewed_head = validate_manifest(project, archive, state)
    return project, active_root, state, configured, archive, archived_files, reviewed_head


def preflight(repo: Path) -> dict:
    project, _, state, configured, archive, _, reviewed_head = prepared_transaction(
        repo,
        ("ship", "shipped"),
        must_be_uncommitted=True,
    )
    phase = state.phase
    status = state.status
    if (phase, status) not in {("ship", "active"), ("shipped", "done")}:
        raise ArchiveError("archive preflight requires ship/active or uncommitted shipped/done")
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


def require_canonical_commit_body(
    project: Path,
    commit: str,
    canonical_subject: str,
    expected_body: str,
    label: str,
) -> None:
    message = require_git_success(
        run_git(project, "show", "-s", "--format=%s%x00%b", commit),
        f"inspect {label} commit message",
    )
    subject, separator, body = message.partition("\x00")
    if not separator:
        raise ArchiveError(f"{label} commit message is malformed")
    if subject != canonical_subject:
        raise ArchiveError(f"{label} commit subject must be {canonical_subject!r}")
    if body.strip() != expected_body.strip():
        raise ArchiveError(f"{label} commit body does not match required fields")


def find_ship_commit(project: Path, archive_name: str) -> str:
    expected_subject = ship_subject(archive_name)
    log = require_git_success(
        run_git(project, "log", "--first-parent", "--format=%H%x00%s", "HEAD"),
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
    if len(matches) != 1:
        raise ArchiveError(
            f"multiple commits with exact subject {expected_subject!r} in HEAD history"
        )
    return matches[0]


def validate_shipped_roadmap(text: str, state: PipelineState, archive: str) -> None:
    if state.milestone is None or state.branch is None:
        raise ArchiveError("shipped program state must name milestone and branch")
    lines = text.splitlines()
    headings = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := ROADMAP_HEADING_PATTERN.fullmatch(line)) is not None
    ]
    matches = [item for item in headings if item[1].group(2) == state.milestone]
    if len(matches) != 1:
        raise ArchiveError("ROADMAP.md must contain one shipped milestone entry")
    start, heading = matches[0]
    end = next((index for index, _ in headings if index > start), len(lines))
    expected_id = milestone_id(milestone_number(state.branch))
    if heading.group(1) != expected_id:
        raise ArchiveError("ROADMAP.md shipped milestone id differs from STATE.branch")
    section = lines[start:end]
    statuses = [line.split(":", 1)[1].strip() for line in section if line.startswith("Status:")]
    archives = [line.split(":", 1)[1].strip() for line in section if line.startswith("Archive:")]
    if statuses != ["shipped"] or archives != [archive]:
        raise ArchiveError("ROADMAP.md must record Status: shipped and the exact Archive")


def validate(repo: Path) -> dict:
    project, _, state, configured, archive, archived_files, reviewed_head = prepared_transaction(
        repo,
        ("shipped",),
    )
    if state.status != "done":
        raise ArchiveError("STATE.md is not shipped/done")

    project_status = require_git_success(run_git(project, "status", "--porcelain"), "inspect worktree status")
    if project_status:
        raise ArchiveError("ship transaction worktree is not clean")

    ship_commit = find_ship_commit(project, archive.name)
    head = require_git_success(run_git(project, "rev-parse", "HEAD"), "resolve HEAD")
    if head != ship_commit:
        raise ArchiveError("bound worktree HEAD must equal the canonical ship commit")

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

    allowed_active_prefixes = tuple(f".project/{name}/" for name in TRANSACTION_DIRECTORIES)
    persistent_program_files = set()
    charter_path = project / ".project" / "CHARTER.md"
    roadmap_path = project / ".project" / "ROADMAP.md"
    if charter_path.is_symlink() or (charter_path.exists() and not charter_path.is_file()):
        raise ArchiveError("CHARTER.md must be a real file")
    if roadmap_path.is_symlink() or (roadmap_path.exists() and not roadmap_path.is_file()):
        raise ArchiveError("ROADMAP.md must be a real file")
    program_ship = is_real_file(charter_path)
    if program_ship:
        persistent_program_files = {
            ".project/CHARTER.md",
            ".project/ROADMAP.md",
            ".project/SYNTHESIS.md",
        }
    unexpected_project_paths = [
        path
        for path in changed_paths
        if path != ".project/STATE.md"
        and path != ".project/LESSONS.md"
        and path not in persistent_program_files
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
    if program_ship:
        required_paths.add(".project/ROADMAP.md")
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
    require_canonical_commit_body(
        project,
        ship_commit,
        ship_subject(archive.name),
        ship_commit_body(configured, reviewed_head),
        "ship",
    )

    archive_in_parent = run_git(project, "cat-file", "-e", f"{ship_commit}^:{configured}")
    if archive_in_parent.returncode == 0:
        raise ArchiveError("current archive was already committed before the ship commit")

    committed_state = require_git_success(
        run_git(project, "show", f"{ship_commit}:.project/STATE.md"),
        "read committed STATE.md",
    )
    current_state = (project / ".project" / "STATE.md").read_text(
        encoding="utf-8"
    ).strip()
    if committed_state != current_state:
        raise ArchiveError("ship commit does not contain the shipped state transaction")
    if program_ship:
        committed_roadmap = require_git_success(
            run_git(project, "show", f"{ship_commit}:.project/ROADMAP.md"),
            "read committed ROADMAP.md",
        )
        validate_shipped_roadmap(committed_roadmap, state, configured)

    manifest_path = f"{ship_commit}:{configured}/MANIFEST.md"
    require_git_success(run_git(project, "cat-file", "-e", manifest_path), "verify committed manifest")

    project_drift = run_git(project, "diff", "--quiet", ship_commit, "HEAD", "--", ".project")
    if project_drift.returncode != 0:
        raise ArchiveError(".project changed in history after the ship commit")

    return {"archive": configured, "commit": ship_commit}


def resolve_remote_default(project: Path) -> str:
    result = run_git(project, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    remote_ref = result.stdout.strip()
    prefix = "refs/remotes/"
    if result.returncode != 0 or not remote_ref.startswith(prefix):
        raise ArchiveError("origin/HEAD is unresolved; fetch before validating integration")
    return remote_ref.removeprefix(prefix)


def live_remote_ref(project: Path, ref: str) -> Optional[str]:
    result = run_git(
        project,
        "ls-remote",
        "--exit-code",
        "--refs",
        "origin",
        ref,
    )
    if result.returncode == 2:
        return None
    if result.returncode != 0:
        raise ArchiveError(f"could not inspect {ref} on origin: git ls-remote failed")
    rows = [line.split("\t", 1) for line in result.stdout.splitlines() if line]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise ArchiveError(f"origin returned ambiguous ref data for {ref}")
    return rows[0][0]


def publish_bound_branch(project: Path, branch: str, ship_commit: str) -> None:
    remote_ref = f"refs/heads/{branch}"
    remote_sha = live_remote_ref(project, remote_ref)
    if remote_sha is None:
        require_git_success(
            run_git(
                project,
                "push",
                f"--force-with-lease={remote_ref}:",
                "origin",
                f"{ship_commit}:{remote_ref}",
            ),
            "create bound branch with absent-ref lease",
        )
    elif remote_sha != ship_commit:
        raise ArchiveError(
            f"origin/{branch} moved or collides: {remote_sha} != {ship_commit}"
        )

    confirmed_sha = live_remote_ref(project, remote_ref)
    if confirmed_sha != ship_commit:
        raise ArchiveError(f"origin/{branch} does not equal the ship commit after publish")
    require_git_success(
        run_git(
            project,
            "update-ref",
            f"refs/remotes/origin/{branch}",
            ship_commit,
        ),
        "refresh local bound-branch ref",
    )


def refresh_origin(repo: Path) -> dict:
    """Fetch origin, refresh origin/HEAD, and mirror milestone tags."""
    project = repo.resolve()
    require_git_success(run_git(project, "fetch", "--prune", "origin"), "fetch origin")
    require_git_success(
        run_git(project, "remote", "set-head", "origin", "--auto"),
        "refresh origin/HEAD",
    )
    mirrored = run_git(
        project,
        "fetch",
        "origin",
        "refs/tags/milestone/*:refs/remotes/origin/tags/milestone/*",
    )
    if mirrored.returncode != 0:
        detail = (mirrored.stderr or mirrored.stdout).strip()
        if "couldn't find remote ref" not in detail.casefold() and detail:
            raise ArchiveError(f"could not refresh published milestone tags: {detail}")
    remote_default = resolve_remote_default(project)
    return {"remote_default": remote_default}


def optional_ref(project: Path, ref: str) -> Optional[str]:
    result = run_git(project, "rev-parse", "--verify", "--quiet", ref)
    return result.stdout.strip() if result.returncode == 0 else None


def integration_names(project: Path, archive_name: str) -> tuple[str, Path]:
    identifier = milestone_id(milestone_number(archive_name))
    branch = f"gsd-path-integrate/{identifier}"
    worktree = project.parent / f".{project.name}-gsd-path-integrate-{identifier}"
    return branch, worktree


def registered_worktree(project: Path, branch: str) -> Optional[Path]:
    output = require_git_success(
        run_git(project, "worktree", "list", "--porcelain"),
        "inspect integration worktrees",
    )
    branch_ref = f"branch refs/heads/{branch}"
    matches = []
    for record in output.split("\n\n"):
        lines = record.splitlines()
        if branch_ref not in lines:
            continue
        worktree_lines = [
            line.removeprefix("worktree ")
            for line in lines
            if line.startswith("worktree ")
        ]
        if len(worktree_lines) != 1:
            raise ArchiveError(
                f"integration branch {branch} has a malformed worktree record"
            )
        matches.append(Path(worktree_lines[0]).resolve())
    if len(matches) > 1:
        raise ArchiveError(f"integration branch {branch} is checked out more than once")
    return matches[0] if matches else None


def remove_registered_worktree(project: Path, branch: str, expected_path: Path) -> None:
    registered = registered_worktree(project, branch)
    if registered is None:
        if expected_path.exists() or expected_path.is_symlink():
            raise ArchiveError(f"unregistered integration worktree path exists: {expected_path}")
        return
    if registered != expected_path.resolve():
        raise ArchiveError(
            f"integration branch {branch} is checked out at unexpected path: {registered}"
        )
    status = require_git_success(
        run_git(registered, "status", "--porcelain", "--untracked-files=all"),
        "inspect integration worktree status",
    )
    if status:
        raise ArchiveError("integration worktree is dirty; refusing cleanup")
    require_git_success(
        run_git(project, "worktree", "remove", str(registered)),
        "remove integration worktree",
    )


def delete_integration_branch(project: Path, branch: str, expected: str) -> None:
    ref = f"refs/heads/{branch}"
    actual = optional_ref(project, ref)
    if actual is None:
        return
    if actual != expected:
        raise ArchiveError(f"integration branch {branch} moved unexpectedly")
    require_git_success(
        run_git(project, "update-ref", "-d", ref, expected),
        "delete integration branch",
    )


def require_generated_integration_commit(
    project: Path,
    commit: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    default_name: str,
    bound_branch: str,
    first_parent: Optional[str] = None,
) -> None:
    subject = require_git_success(
        run_git(project, "show", "-s", "--format=%s", commit),
        "inspect integration commit subject",
    )
    expected_subject = integrate_subject(archive_name, default_name)
    if subject != expected_subject:
        raise ArchiveError(f"integration commit subject must be {expected_subject!r}")
    require_canonical_commit_body(
        project,
        commit,
        expected_subject,
        integrate_commit_body(archive_path, ship_commit, default_name, bound_branch),
        "integration",
    )
    parents = require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", commit),
        "inspect integration merge parents",
    ).split()
    if len(parents) != 3 or parents[2] != ship_commit:
        raise ArchiveError("integration commit is not the canonical merge of the ship commit")
    if first_parent is not None and parents[1] != first_parent:
        raise ArchiveError("integration merge was created from a stale remote default")


def discard_unpublished_stale_integration(
    project: Path,
    branch: str,
    merge_commit: str,
    remote_default_sha: str,
    default_name: str,
    archive_name: str,
    bound_branch: str,
) -> None:
    live_default = live_remote_ref(project, f"refs/heads/{default_name}")
    if live_default != remote_default_sha:
        raise ArchiveError(f"origin/{default_name} advanced again; rerun integrate")
    published = run_git(
        project, "merge-base", "--is-ancestor", merge_commit, remote_default_sha
    )
    if published.returncode == 0:
        raise ArchiveError("stale integration merge is already published on origin/main")
    if published.returncode != 1:
        require_git_success(published, "inspect stale integration publication")

    bound_ref = f"refs/heads/{bound_branch}"
    if live_remote_ref(project, bound_ref) is not None:
        raise ArchiveError(
            "stale integration recovery requires the remote bound branch to be absent"
        )
    tag_name = f"milestone/{archive_name}"
    published_tag_ref = f"refs/tags/{tag_name}"
    if live_remote_ref(project, published_tag_ref) is not None:
        raise ArchiveError(
            "stale integration recovery requires the remote milestone tag to be absent"
        )

    local_tag_ref = f"refs/tags/{tag_name}"
    local_tag_object = optional_ref(project, local_tag_ref)
    if local_tag_object is not None:
        require_annotated_tag(
            project,
            local_tag_ref,
            merge_commit,
            f"stale milestone tag {tag_name}",
        )
        require_git_success(
            run_git(project, "update-ref", "-d", local_tag_ref, local_tag_object),
            "delete unpublished stale milestone tag",
        )

    tracking_tag_ref = f"refs/remotes/origin/tags/{tag_name}"
    tracking_tag_object = optional_ref(project, tracking_tag_ref)
    if tracking_tag_object is not None:
        if local_tag_object is None or tracking_tag_object != local_tag_object:
            raise ArchiveError("local published-tag tracking ref is not safely recoverable")
        require_git_success(
            run_git(
                project,
                "update-ref",
                "-d",
                tracking_tag_ref,
                tracking_tag_object,
            ),
            "delete stale published-tag tracking ref",
        )
    delete_integration_branch(project, branch, merge_commit)


def create_integration_merge(
    project: Path,
    worktree: Path,
    branch: str,
    remote_default_sha: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    default_name: str,
    bound_branch: str,
) -> tuple[str, bool]:
    if worktree.exists() or worktree.is_symlink():
        raise ArchiveError(f"integration worktree path already exists: {worktree}")
    branch_ref = f"refs/heads/{branch}"
    branch_tip = optional_ref(project, branch_ref)
    if branch_tip is None:
        add = run_git(
            project,
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(worktree),
            remote_default_sha,
        )
    elif branch_tip == remote_default_sha:
        add = run_git(project, "worktree", "add", "--quiet", str(worktree), branch)
    else:
        require_generated_integration_commit(
            project,
            branch_tip,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
        parents = require_git_success(
            run_git(project, "rev-list", "--parents", "-n", "1", branch_tip),
            "inspect existing integration merge parents",
        ).split()
        if parents[1] == remote_default_sha:
            return branch_tip, False
        discard_unpublished_stale_integration(
            project,
            branch,
            branch_tip,
            remote_default_sha,
            default_name,
            archive_name,
            bound_branch,
        )
        add = run_git(
            project,
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(worktree),
            remote_default_sha,
        )
    require_git_success(add, "create integration worktree")

    merge = run_git(
        worktree,
        "merge",
        "--no-ff",
        "-m",
        integrate_subject(archive_name, default_name),
        "-m",
        integrate_commit_body(archive_path, ship_commit, default_name, bound_branch),
        ship_commit,
    )
    if merge.returncode != 0:
        conflicted = optional_ref(worktree, "MERGE_HEAD") is not None
        detail = (merge.stderr or merge.stdout).strip()
        if conflicted:
            require_git_success(
                run_git(worktree, "merge", "--abort"),
                "abort integration merge",
            )
        remove_registered_worktree(project, branch, worktree)
        delete_integration_branch(project, branch, remote_default_sha)
        if conflicted:
            raise ArchiveError(
                "integration merge conflicted; Git aborted it without resolving files"
            )
        raise ArchiveError(f"create integration merge failed: {detail}")

    merge_commit = require_git_success(
        run_git(worktree, "rev-parse", "HEAD"), "resolve integration merge"
    )
    require_generated_integration_commit(
        project,
        merge_commit,
        archive_path,
        archive_name,
        ship_commit,
        default_name,
        bound_branch,
        remote_default_sha,
    )
    return merge_commit, True


def require_annotated_tag(project: Path, ref: str, merge_commit: str, label: str) -> str:
    object_id = optional_ref(project, ref)
    if object_id is None:
        raise ArchiveError(f"missing {label}")
    tag_type = require_git_success(
        run_git(project, "cat-file", "-t", ref), f"inspect {label}"
    )
    if tag_type != "tag":
        raise ArchiveError(f"{label} must be annotated")
    target = require_git_success(
        run_git(project, "rev-parse", f"{ref}^{{commit}}"), f"resolve {label} target"
    )
    if target != merge_commit:
        raise ArchiveError(f"{label} does not point at the integration merge")
    return object_id


def ensure_integration_tag(project: Path, tag_name: str, merge_commit: str) -> tuple[str, bool]:
    local_ref = f"refs/tags/{tag_name}"
    remote_ref = f"refs/remotes/origin/tags/{tag_name}"
    local_object = optional_ref(project, local_ref)
    remote_object = optional_ref(project, remote_ref)
    if remote_object is not None:
        remote_object = require_annotated_tag(
            project, remote_ref, merge_commit, f"published milestone tag {tag_name}"
        )
    if local_object is None:
        if remote_object is not None:
            require_git_success(
                run_git(project, "update-ref", local_ref, remote_object),
                "restore local milestone tag",
            )
        else:
            tag_message = f"milestone {tag_name.removeprefix('milestone/')}"
            require_git_success(
                run_git(
                    project,
                    "tag",
                    "-a",
                    "-m",
                    tag_message,
                    tag_name,
                    merge_commit,
                ),
                "create milestone tag",
            )
    local_object = require_annotated_tag(
        project, local_ref, merge_commit, f"milestone tag {tag_name}"
    )
    if remote_object is not None and remote_object != local_object:
        raise ArchiveError(f"local and published milestone tag {tag_name} differ")
    return local_object, remote_object is not None


def integrate(repo: Path, slug: str) -> dict:
    project = repo.resolve()
    active_root = require_project_layout(project)
    state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    expected_slug = milestone_slug(state)
    if normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )

    shipped = validate(project)
    archive_path = shipped["archive"]
    ship_commit = shipped["commit"]
    archive_name = PurePosixPath(archive_path).name
    bound_branch = state.branch
    expected_branch = bound_branch_name(milestone_number(archive_name))
    if bound_branch != expected_branch:
        raise ArchiveError(f"integration requires canonical bound branch {expected_branch}")
    head = require_git_success(
        run_git(project, "rev-parse", "HEAD"), "resolve bound branch HEAD"
    )
    if head != ship_commit:
        raise ArchiveError("bound worktree must remain at the ship commit during integration")
    subject = require_git_success(
        run_git(project, "show", "-s", "--format=%s", ship_commit),
        "inspect ship commit subject",
    )
    if subject != ship_subject(archive_name):
        raise ArchiveError("integration only generates canonical M00N shipment history")

    remote_default = refresh_origin(project)["remote_default"]
    default_name = default_branch_name(remote_default)
    if default_name != "main":
        raise ArchiveError(f"remote default must be main, got {default_name!r}")
    if bound_branch == default_name:
        raise ArchiveError("bound branch must not be the remote default")
    remote_default_sha = require_git_success(
        run_git(project, "rev-parse", remote_default), "resolve remote default"
    )
    integration_branch, worktree = integration_names(project, archive_name)
    interrupted_worktree = registered_worktree(project, integration_branch)
    if (
        interrupted_worktree is not None
        and optional_ref(interrupted_worktree, "MERGE_HEAD") is not None
    ):
        if interrupted_worktree != worktree.resolve():
            raise ArchiveError(
                f"integration branch {integration_branch} is checked out at unexpected path: "
                f"{interrupted_worktree}"
            )
        require_git_success(
            run_git(interrupted_worktree, "merge", "--abort"),
            "abort interrupted integration merge",
        )
        remove_registered_worktree(project, integration_branch, worktree)
        interrupted_tip = optional_ref(project, f"refs/heads/{integration_branch}")
        if interrupted_tip is not None:
            delete_integration_branch(project, integration_branch, interrupted_tip)
        raise ArchiveError(
            "interrupted integration merge conflicted; Git aborted it without resolving files"
        )
    remove_registered_worktree(project, integration_branch, worktree)
    worktree_active = False

    contains_ship = run_git(
        project, "merge-base", "--is-ancestor", ship_commit, remote_default
    )
    if contains_ship.returncode == 0:
        merge_commit = find_integrate_commit(
            project, remote_default, archive_name, ship_commit
        )
        require_generated_integration_commit(
            project,
            merge_commit,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
    elif contains_ship.returncode == 1:
        merge_commit, worktree_active = create_integration_merge(
            project,
            worktree,
            integration_branch,
            remote_default_sha,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
    else:
        require_git_success(contains_ship, "inspect ship ancestry on the remote default")
        raise AssertionError("unreachable")

    action_error = None
    try:
        tag_name = f"milestone/{archive_name}"
        tag_object, tag_published = ensure_integration_tag(
            project, tag_name, merge_commit
        )

        published_merge = run_git(
            project, "merge-base", "--is-ancestor", merge_commit, remote_default
        )
        if published_merge.returncode == 1:
            require_git_success(
                run_git(
                    project,
                    "push",
                    "origin",
                    f"{merge_commit}:refs/heads/{default_name}",
                ),
                "push integration merge to main",
            )
            require_git_success(
                run_git(project, "update-ref", remote_default, merge_commit),
                "refresh local remote-default ref",
            )
        elif published_merge.returncode != 0:
            require_git_success(published_merge, "inspect published integration merge")

        publish_bound_branch(project, bound_branch, ship_commit)
        if not tag_published:
            require_git_success(
                run_git(
                    project,
                    "push",
                    "origin",
                    f"refs/tags/{tag_name}:refs/tags/{tag_name}",
                ),
                "push milestone tag",
            )
            require_git_success(
                run_git(
                    project,
                    "update-ref",
                    f"refs/remotes/origin/tags/{tag_name}",
                    tag_object,
                ),
                "refresh local milestone-tag ref",
            )
    except (ArchiveError, OSError) as error:
        action_error = error

    try:
        if worktree_active:
            remove_registered_worktree(project, integration_branch, worktree)
    except (ArchiveError, OSError) as cleanup_error:
        if action_error is not None:
            raise ArchiveError(
                f"{action_error}; integration worktree cleanup failed: {cleanup_error}"
            )
        raise
    if action_error is not None:
        raise action_error

    branch_tip = optional_ref(project, f"refs/heads/{integration_branch}")
    if branch_tip is not None:
        if branch_tip != merge_commit:
            ancestor = run_git(
                project, "merge-base", "--is-ancestor", branch_tip, merge_commit
            )
            if ancestor.returncode != 0:
                raise ArchiveError(f"integration branch {integration_branch} moved unexpectedly")
        delete_integration_branch(project, integration_branch, branch_tip)
    return validate_integrated(project, slug)


def find_integrate_commit(
    project: Path,
    remote_default: str,
    archive_name: str,
    ship_commit: str,
) -> str:
    default_name = default_branch_name(remote_default)
    expected_subject = integrate_subject(archive_name, default_name)
    log = require_git_success(
        run_git(project, "log", "--first-parent", "--format=%H%x00%s", remote_default),
        f"inspect {remote_default} first-parent history for the integration merge",
    )
    matches = []
    for record in log.splitlines():
        if "\x00" not in record:
            continue
        commit, subject = record.split("\x00", 1)
        if subject == expected_subject:
            matches.append(commit)
    if not matches:
        raise ArchiveError(
            f"no commit with exact subject {expected_subject!r} "
            f"in {remote_default} first-parent history"
        )
    if len(matches) != 1:
        raise ArchiveError(
            f"multiple commits with exact subject {expected_subject!r} "
            f"in {remote_default} first-parent history"
        )
    merge_commit = matches[0]
    parents = require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", merge_commit),
        "inspect integration merge parents",
    ).split()
    if len(parents) != 3:
        raise ArchiveError(f"integration commit for {archive_name} is not a merge commit")
    if parents[2] != ship_commit:
        raise ArchiveError("integration merge second parent is not the ship commit")
    return merge_commit


def validate_integrated(repo: Path, slug: str) -> dict:
    project = repo.resolve()
    active_root = require_project_layout(project)
    state, _, loaded_state_path = strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    expected_slug = milestone_slug(state)
    if normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )

    # (a) The shipped transaction itself must still validate.
    shipped = validate(repo)
    configured = shipped["archive"]
    ship_commit = shipped["commit"]
    archive_name = PurePosixPath(configured).name

    # Read-only and network-free: only existing origin/* refs are consulted;
    # fetching is the phase's job.
    remote_default = resolve_remote_default(project)
    default_name = default_branch_name(remote_default)
    bound_branch = state.branch
    if bound_branch is None:
        raise ArchiveError("STATE.md does not name a bound build branch")
    expected_branch = bound_branch_name(milestone_number(archive_name))
    ship_subject_text = require_git_success(
        run_git(project, "log", "-1", "--format=%s", ship_commit),
        "read ship commit subject",
    )
    if ship_subject_text != ship_subject(archive_name):
        raise ArchiveError("current milestone ship commit subject is not canonical")
    if not is_bound_branch(bound_branch):
        raise ArchiveError(f"bound branch {bound_branch!r} is not gsd-path/M00N")
    if is_bound_branch(bound_branch) and bound_branch != expected_branch:
        expected_milestone = expected_branch.removeprefix("gsd-path/")
        raise ArchiveError(
            f"bound branch {bound_branch} does not match archive milestone {expected_milestone}"
        )
    if bound_branch == default_name:
        raise ArchiveError(
            f"bound branch {bound_branch!r} is the remote default; "
            "ship merges onto main, never onto the work branch"
        )
    if default_name != "main":
        raise ArchiveError(f"remote default must be main, got {default_name!r}")

    # (b) The integration merge must sit on the remote default's first-parent
    # history with the ship commit as its second parent.
    merge_commit = find_integrate_commit(project, remote_default, archive_name, ship_commit)
    require_canonical_commit_body(
        project,
        merge_commit,
        integrate_subject(archive_name, default_name),
        integrate_commit_body(configured, ship_commit, default_name, bound_branch),
        "integration",
    )

    # (c) The milestone tag must be annotated and point at the merge commit.
    tag_name = f"milestone/{archive_name}"
    tag_ref = f"refs/tags/{tag_name}"
    if run_git(project, "rev-parse", "--verify", "--quiet", tag_ref).returncode != 0:
        raise ArchiveError(f"missing milestone tag: {tag_name}")
    tag_type = require_git_success(
        run_git(project, "cat-file", "-t", tag_ref),
        "inspect milestone tag type",
    )
    if tag_type != "tag":
        raise ArchiveError(f"milestone tag {tag_name} must be annotated")
    tag_target = require_git_success(
        run_git(project, "rev-parse", f"{tag_ref}^{{commit}}"),
        "resolve milestone tag target",
    )
    if tag_target != merge_commit:
        raise ArchiveError(f"milestone tag {tag_name} does not point at the integration merge")

    # (d) The remote default must contain the merge commit.
    contains = run_git(project, "merge-base", "--is-ancestor", merge_commit, remote_default)
    if contains.returncode != 0:
        raise ArchiveError(f"{remote_default} does not contain the integration merge")

    # (e) The bound branch tip and annotated tag must be published on origin.
    require_published_integration(
        project,
        bound_branch,
        ship_commit,
        tag_name,
        merge_commit,
    )

    return {
        "archive": configured,
        "commit": ship_commit,
        "integrate": merge_commit,
        "tag": tag_name,
    }


def require_published_integration(
    project: Path,
    bound_branch: str,
    ship_commit: str,
    tag_name: str,
    merge_commit: str,
) -> None:
    bound_ref = f"refs/remotes/origin/{bound_branch}"
    if run_git(project, "rev-parse", "--verify", "--quiet", bound_ref).returncode != 0:
        raise ArchiveError(f"missing published bound branch: origin/{bound_branch}")
    published_ship = require_git_success(
        run_git(project, "rev-parse", bound_ref),
        "resolve published bound branch",
    )
    if published_ship != ship_commit:
        raise ArchiveError(
            f"origin/{bound_branch} is {published_ship}, expected ship commit {ship_commit}"
        )

    remote_tag = f"refs/remotes/origin/tags/{tag_name}"
    if run_git(project, "rev-parse", "--verify", "--quiet", remote_tag).returncode != 0:
        raise ArchiveError(f"missing published milestone tag: origin/tags/{tag_name}")
    remote_tag_type = require_git_success(
        run_git(project, "cat-file", "-t", remote_tag),
        "inspect published milestone tag type",
    )
    if remote_tag_type != "tag":
        raise ArchiveError(f"published milestone tag {tag_name} must be annotated")
    remote_tag_target = require_git_success(
        run_git(project, "rev-parse", f"{remote_tag}^{{commit}}"),
        "resolve published milestone tag target",
    )
    if remote_tag_target != merge_commit:
        raise ArchiveError(
            f"published milestone tag {tag_name} does not point at the integration merge"
        )


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

    manifest_parser = subparsers.add_parser(
        "render-manifest",
        help="render the current uncommitted archive manifest from validated evidence",
    )
    manifest_parser.add_argument("--repo", required=True, type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate the committed ship transaction")
    validate_parser.add_argument("--repo", required=True, type=Path)

    validate_integrated_parser = subparsers.add_parser(
        "validate-integrated",
        help="validate the committed ship transaction and its default-branch integration",
    )
    validate_integrated_parser.add_argument("--repo", required=True, type=Path)
    validate_integrated_parser.add_argument("--slug", required=True)

    refresh_parser = subparsers.add_parser(
        "refresh-origin",
        help="fetch origin, refresh origin/HEAD, and mirror published milestone tags",
    )
    refresh_parser.add_argument("--repo", required=True, type=Path)

    integrate_parser = subparsers.add_parser(
        "integrate",
        help="resume and publish the shipped milestone integration",
    )
    integrate_parser.add_argument("--repo", required=True, type=Path)
    integrate_parser.add_argument("--slug", required=True)

    abandon_parser = subparsers.add_parser(
        "abandon",
        help="abandon the active build milestone and archive its partial artifacts",
    )
    abandon_parser.add_argument("--repo", required=True, type=Path)
    abandon_parser.add_argument("--slug", required=True)
    abandon_parser.add_argument("--reason", required=True)
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "prepare":
            result = prepare(arguments.repo, arguments.slug)
        elif arguments.command == "render-manifest":
            result = render_manifest(arguments.repo)
        elif arguments.command == "preflight":
            result = preflight(arguments.repo)
        elif arguments.command == "abandon":
            result = abandon(arguments.repo, arguments.slug, arguments.reason)
        elif arguments.command == "validate-integrated":
            result = validate_integrated(arguments.repo, arguments.slug)
        elif arguments.command == "refresh-origin":
            result = refresh_origin(arguments.repo)
        elif arguments.command == "integrate":
            result = integrate(arguments.repo, arguments.slug)
        else:
            result = validate(arguments.repo)
    except (ArchiveError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
