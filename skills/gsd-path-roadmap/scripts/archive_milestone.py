#!/usr/bin/env python3
# gsd-path project runtime
"""Prepare, render, validate, integrate, and abandon GSD Path milestone archives.

Also validates milestone integration: the read-only validate-integrated
command checks the shipped transaction, the selected mode's two-parent merge
on the remote default branch, and the milestone tag. Pull-request validation
requires network access to verify live origin publication.
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
    import _common
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
    from scripts import _common

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
WAVE_SKEPTIC_PATTERN = re.compile(
    r"^wave-([1-9]\d*)\.cycle([1-9]\d*)\.skeptic-"
    r"([a-z0-9]+(?:_[a-z0-9]+)*)\.md$"
)
WAVE_REPAIR_PATTERN = re.compile(
    r"^wave-([1-9]\d*)\.cycle([1-9]\d*)\.repair-(T\d{3})\.json$"
)
# A review file claims to be wave-cycle evidence when its name starts with a
# wave number followed by "cycle" (a missing dot is a typo, not a note). Other
# wave-* names are free-form review notes like any non-canonical review file.
WAVE_CYCLE_CLAIM_PATTERN = re.compile(r"^wave-\d+\.?cycle")
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
# build/ holds the verify ledger; it archives with the milestone when present.
OPTIONAL_DIRECTORIES_TO_ARCHIVE = ("discuss", "build")
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
PLACEHOLDER_PATTERN = re.compile(r"(?<!\w)<[a-zA-Z][^<>\n]*>")
CODE_SPAN_PATTERN = re.compile(r"(?<!`)(`+)(?!`)[\s\S]*?(?<!`)\1(?!`)")


def contains_placeholder(value: str) -> bool:
    # A wholly unfilled value is a placeholder even when quoted.
    cleaned = value.strip().strip("`")
    if PLACEHOLDER_PATTERN.fullmatch(cleaned):
        return True
    # Scan with code spans blanked out: quoted code such as a TypeScript
    # generic is not an unfilled placeholder.
    return PLACEHOLDER_PATTERN.search(CODE_SPAN_PATTERN.sub(" ", value)) is not None


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


PIPELINE_MARKER = _common.PIPELINE_MARKER


# discussion_validate calls back into this module and imports its constants
# and ArchiveError, so this import must stay below those definitions.
if __package__:  # imported as scripts.archive_milestone
    from .discussion_validate import (
        record_sections,
        required_dialogue_block,
        require_contiguous_ids,
        require_iso_date,
        require_bullet_fields,
        validate_discussion_directory,
        require_append_only_discussion,
        reconcile_append_only_discussion,
        require_safe_discussion_destination,
        finish_discussion_reconciliation,
        remove_interrupted_discussion_copies,
        remove_interrupted_carry_copy,
        require_transaction_context,
        completed_field,
        completed_bullet_field,
        section_lines,
        archived_intent_criteria,
        parse_final_review,
        validate_gap_reviews,
        meaningful_review_evidence,
        archived_wave_tasks,
        plan_wave_criteria,
        validate_wave_review,
        plan_wave_depths,
        review_cycle_counts,
        manifest_cell,
        archive_file_inventory,
        render_manifest,
        validate_manifest,
    )
else:  # standalone script or sibling import
    if __name__ == "__main__":
        sys.modules.setdefault("archive_milestone", sys.modules[__name__])
    try:
        from discussion_validate import (
            record_sections,
            required_dialogue_block,
            require_contiguous_ids,
            require_iso_date,
            require_bullet_fields,
            validate_discussion_directory,
            require_append_only_discussion,
            reconcile_append_only_discussion,
            require_safe_discussion_destination,
            finish_discussion_reconciliation,
            remove_interrupted_discussion_copies,
            remove_interrupted_carry_copy,
            require_transaction_context,
            completed_field,
            completed_bullet_field,
            section_lines,
            archived_intent_criteria,
            parse_final_review,
            validate_gap_reviews,
            meaningful_review_evidence,
            archived_wave_tasks,
            plan_wave_criteria,
            validate_wave_review,
            plan_wave_depths,
            review_cycle_counts,
            manifest_cell,
            archive_file_inventory,
            render_manifest,
            validate_manifest,
        )
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts.discussion_validate import (
            record_sections,
            required_dialogue_block,
            require_contiguous_ids,
            require_iso_date,
            require_bullet_fields,
            validate_discussion_directory,
            require_append_only_discussion,
            reconcile_append_only_discussion,
            require_safe_discussion_destination,
            finish_discussion_reconciliation,
            remove_interrupted_discussion_copies,
            remove_interrupted_carry_copy,
            require_transaction_context,
            completed_field,
            completed_bullet_field,
            section_lines,
            archived_intent_criteria,
            parse_final_review,
            validate_gap_reviews,
            meaningful_review_evidence,
            archived_wave_tasks,
            plan_wave_criteria,
            validate_wave_review,
            plan_wave_depths,
            review_cycle_counts,
            manifest_cell,
            archive_file_inventory,
            render_manifest,
            validate_manifest,
        )


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


atomic_replace = _common.atomic_replace


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
    return landed_task_evidence(project, tasks, reviewed_head)[0]


def landed_task_evidence(
    project: Path, tasks: Path, reviewed_head: str
) -> tuple[Sequence[Path], int]:
    """(task artifacts, attested count) once every task proves landed or attested."""
    candidates = canonical_task_files(tasks)
    try:
        proven = verify_landed_task_files(
            project,
            candidates,
            ".project/tasks",
            reviewed_head,
        )
    except (IsolationError, ValueError) as error:
        raise ArchiveError(f"task landing proof failed: {error}") from error
    attested = sum(1 for task in proven["tasks"] if task.get("verdict") == "attested")
    return candidates, attested


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


class SkepticArtifact(NamedTuple):
    path: Path
    wave: int
    cycle: int
    locator: str


class RepairArtifact(NamedTuple):
    path: Path
    wave: int
    cycle: int
    task: str


def canonical_wave_files(reviews: Path) -> Sequence[WaveArtifact]:
    if reviews.is_symlink() or not reviews.is_dir():
        return ()
    candidates = sorted(
        path for path in reviews.iterdir() if WAVE_CYCLE_CLAIM_PATTERN.match(path.name)
    )
    matches = [(path, WAVE_FILE_PATTERN.fullmatch(path.name)) for path in candidates]
    if any(
        (
            match is None
            and WAVE_PANEL_SKIP_PATTERN.fullmatch(path.name) is None
            and WAVE_SKEPTIC_PATTERN.fullmatch(path.name) is None
            and WAVE_REPAIR_PATTERN.fullmatch(path.name) is None
        )
        or not is_real_file(path)
        for path, match in matches
    ):
        raise ArchiveError(
            "canonical wave artifacts must be real wave-N.cycleC.md files "
            "(a .contract, .adversarial, or .panel lens suffix is allowed), "
            "canonical .panel.skipped.json receipts, or auxiliary "
            ".skeptic-<locator>.md and .repair-T###.json evidence"
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


def canonical_wave_skeptic_files(reviews: Path) -> Sequence[SkepticArtifact]:
    if reviews.is_symlink() or not reviews.is_dir():
        return ()
    artifacts = []
    for path in sorted(reviews.iterdir()):
        match = WAVE_SKEPTIC_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        if not is_real_file(path):
            raise ArchiveError(f"skeptic evidence must be a real file: {path.name}")
        artifacts.append(
            SkepticArtifact(
                path,
                int(match.group(1)),
                int(match.group(2)),
                match.group(3),
            )
        )
    return artifacts


def validate_wave_skeptic_files(
    reviews: Path,
    wave_depths: dict[int, str],
    wave_artifacts: Sequence[WaveArtifact],
) -> None:
    deep_cycles = {}
    for artifact in wave_artifacts:
        if artifact.lens in {"contract", "adversarial"}:
            deep_cycles.setdefault((artifact.wave, artifact.cycle), set()).add(
                artifact.lens
            )
    required_lenses = {"contract", "adversarial"}
    for artifact in canonical_wave_skeptic_files(reviews):
        key = (artifact.wave, artifact.cycle)
        if (
            wave_depths.get(artifact.wave) != "deep"
            or deep_cycles.get(key) != required_lenses
        ):
            raise ArchiveError(
                f"{artifact.path.name} does not match a canonical deep review cycle"
            )
        lines = artifact.path.read_text(encoding="utf-8").splitlines()
        heading = f"# Skeptic — wave {artifact.wave}, cycle {artifact.cycle}"
        if lines.count(heading) != 1:
            raise ArchiveError(
                f"{artifact.path.name} heading does not match its filename"
            )
        completed_field(lines, "- Criterion:", artifact.path.name)
        locator = completed_field(lines, "- Criterion locator:", artifact.path.name)
        if locator != artifact.locator:
            raise ArchiveError(
                f"{artifact.path.name} Criterion locator does not match its filename"
            )


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


def canonical_wave_repair_files(reviews: Path) -> Sequence[RepairArtifact]:
    if reviews.is_symlink() or not reviews.is_dir():
        return ()
    artifacts = []
    for path in sorted(reviews.iterdir()):
        match = WAVE_REPAIR_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        if not is_real_file(path):
            raise ArchiveError(f"repair receipt must be a real file: {path.name}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise ArchiveError(f"{path.name} is not valid repair-evidence JSON") from error
        wave = int(match.group(1))
        cycle = int(match.group(2))
        task = match.group(3)
        if (
            not isinstance(payload, dict)
            or payload.get("command") != "repair-evidence"
            or payload.get("status") != "ok"
            or payload.get("source") != {"wave": wave, "cycle": cycle}
            or not isinstance(payload.get("repair"), dict)
            or payload["repair"].get("task") != task
        ):
            raise ArchiveError(
                f"{path.name} identity does not match its repair-evidence payload"
            )
        artifacts.append(RepairArtifact(path, wave, cycle, task))
    return artifacts


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
    wave_artifacts = canonical_wave_files(reviews)
    if not wave_artifacts:
        missing.append("review/wave-N.cycleC.md")
    plan = selected_transaction_path(active_root, archive, "plan/PLAN.md")
    if missing:
        raise ArchiveError(f"canonical milestone artifacts are missing: {', '.join(missing)}")
    plan_text = plan.read_text(encoding="utf-8")
    _, wave_depths = plan_wave_depths(plan_text)
    validate_wave_skeptic_files(reviews, wave_depths, wave_artifacts)
    canonical_wave_repair_files(reviews)
    require_plan_panel_evidence(
        plan_text,
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
    if configured is None:
        # Prove the inputs before STATE.archive is persisted or any directory exists.
        # Archiving a stale final review cannot be undone, so check it here, not only in preflight.
        final = active_root / "review" / "FINAL.md"
        reviewed = re.search(r"(?m)^Reviewed HEAD:\s*(\S+)", final.read_text(encoding="utf-8")) if final.is_file() else None
        head = require_git_success(run_git(project, "rev-parse", "HEAD"), "resolve HEAD").strip()
        if reviewed and reviewed.group(1) != head:
            raise ArchiveError(
                f"FINAL.md Reviewed HEAD {reviewed.group(1)} does not match current HEAD {head}; "
                "re-run the final review on the current commit before archiving"
            )
        target = resolved_archive_target(project, slug, parsed_state)
        require_archive_milestone(target.name, parsed_state)
        require_complete_transaction_inputs(active_root, target)
        require_canonical_transaction_inputs(active_root, target)

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
            if name == "discuss":
                require_append_only_discussion(source, destination)
                continue
            raise ArchiveError(f"archive collision: both {source} and {destination} exist")


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


run_git = _common.run_git
run_command = _common.run_command


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

    project_drift = require_git_success(
        run_git(project, "diff", "--name-only", ship_commit, "HEAD", "--", ".project"),
        "inspect .project history after the ship commit",
    )
    if project_drift:
        raise ArchiveError(
            ".project changed in history after the ship commit: "
            + ", ".join(project_drift.splitlines())
            + f"; run: git -C {project} revert <commits after {ship_commit[:12]} that touch .project>"
        )

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

    manifest_parser = subparsers.add_parser(
        "render-manifest",
        help="render the current uncommitted archive manifest from validated evidence",
    )
    manifest_parser.add_argument("--repo", required=True, type=Path)

    validate_parser = subparsers.add_parser("validate", help="validate the committed ship transaction")
    validate_parser.add_argument("--repo", required=True, type=Path)

    validate_integrated_parser = subparsers.add_parser(
        "validate-integrated",
        help=(
            "validate the committed ship transaction and its default-branch integration; "
            "pull-request mode requires origin network access"
        ),
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
        if arguments.command in {"validate-integrated", "refresh-origin", "integrate"}:
            if __package__:
                from . import integration
            else:
                import integration
        if arguments.command == "prepare":
            result = prepare(arguments.repo, arguments.slug)
        elif arguments.command == "render-manifest":
            result = render_manifest(arguments.repo)
        elif arguments.command == "preflight":
            result = preflight(arguments.repo)
        elif arguments.command == "abandon":
            result = abandon(arguments.repo, arguments.slug, arguments.reason)
        elif arguments.command == "validate-integrated":
            result = integration.validate_integrated(arguments.repo, arguments.slug)
        elif arguments.command == "refresh-origin":
            result = integration.refresh_origin(arguments.repo)
        elif arguments.command == "integrate":
            result = integration.integrate(arguments.repo, arguments.slug)
        else:
            result = validate(arguments.repo)
    except (ArchiveError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
