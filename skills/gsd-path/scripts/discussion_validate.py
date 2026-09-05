#!/usr/bin/env python3
# gsd-path project runtime
"""Validate discussion records, reviews and the manifest for archive_milestone."""

import json
import re
import shutil
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

try:
    from pipeline_state import PipelineState
    import _common
except ImportError:  # pragma: no cover - package import used by tests
    from scripts.pipeline_state import PipelineState
    from scripts import _common


atomic_replace = _common.atomic_replace
run_git = _common.run_git


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
    if not archive_milestone.is_real_file(dialogue) or not archive_milestone.is_real_file(answers):
        raise ArchiveError("discussion archive records must be real files")

    dialogue_content = dialogue.read_text(encoding="utf-8")
    answer_content = answers.read_text(encoding="utf-8")
    dialogue_lines = dialogue_content.splitlines()
    answer_lines = answer_content.splitlines()
    if archive_milestone.contains_placeholder("\n".join((*dialogue_lines, *answer_lines))):
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
    archive_milestone.atomic_write(transaction, json.dumps(payload, sort_keys=True) + "\n")
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
            archive_milestone.atomic_write(transaction, json.dumps(payload, sort_keys=True) + "\n")
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
    if archive_milestone.pending_ruling_count(archived_audit) == 0:
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

    repository_root = archive_milestone.require_git_success(
        run_git(project, "rev-parse", "--show-toplevel"),
        "resolve Git root",
    )
    if Path(repository_root).resolve() != project:
        raise ArchiveError(f"--repo must be the Git worktree root: {repository_root}")

    expected_branch = state.branch
    current_branch = archive_milestone.require_git_success(
        run_git(project, "branch", "--show-current"),
        "resolve current branch",
    )
    if archive_milestone.is_unset(expected_branch):
        raise ArchiveError("STATE.md does not name a bound build branch")
    if current_branch != expected_branch:
        raise ArchiveError(
            f"current branch {current_branch!r} does not match STATE.branch {expected_branch!r}"
        )

    non_project_status = archive_milestone.require_git_success(
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
    if len(values) != 1 or not values[0] or archive_milestone.contains_placeholder(values[0]):
        raise ArchiveError(f"{artifact} requires one completed {field} field")
    return values[0]


def completed_bullet_field(lines: Sequence[str], field: str, artifact: str) -> str:
    pattern = re.compile(rf"^- \*\*{re.escape(field)}\*\*:\s*(.*)$")
    values = []
    for line in lines:
        match = pattern.fullmatch(line)
        if match:
            values.append(match.group(1).strip().strip("`"))
    if len(values) != 1 or not values[0] or archive_milestone.contains_placeholder(values[0]):
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
    if not archive_milestone.is_real_file(intent):
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
    try:
        import check_handoffs
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import check_handoffs

    final = archive / "review" / "FINAL.md"
    if not archive_milestone.is_real_file(final):
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
    intent_text = (archive / "intent" / "INTENT.md").read_text(encoding="utf-8")
    try:
        surfaces = (
            check_handoffs._surfaces(intent_text, "INTENT.md")
            if re.search(r"(?m)^Surfaces:", intent_text) else []
        )
    except check_handoffs.HandoffError as error:
        raise ArchiveError(str(error)) from error
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
        surface_values = [
            line.removeprefix("- **Surface**:").strip().strip("`")
            for line in lines[section_start:section_end]
            if line.startswith("- **Surface**:")
        ]
        surface_evidence = len(surface_values) == 1 and any(
            # Older final gates stripped terminal Markdown code delimiters.
            " ".join(surface_values[0].split()).casefold()
            == " ".join(surface.split()).strip("`").casefold()
            for surface in surfaces
        )
        if tuple(values) != expected_fields:
            raise ArchiveError(f"FINAL.md criterion is incomplete: {criterion}")
        for field, value in values.items():
            if surface_evidence and field in {"Check", "Observed"}:
                try:
                    check_handoffs._surface_value(value, f"FINAL.md surface {field}")
                except check_handoffs.HandoffError as error:
                    raise ArchiveError(str(error)) from error
            elif not value or archive_milestone.contains_placeholder(value):
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
        if not match or not archive_milestone.is_real_file(path):
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
            or archive_milestone.contains_placeholder(headings[0].group(2))
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
    for path in archive_milestone.canonical_task_files(archive / "tasks"):
        content = path.read_text(encoding="utf-8")
        task_id = archive_milestone.frontmatter_value(content, "id")
        title = archive_milestone.frontmatter_value(content, "title")
        wave_text = archive_milestone.frontmatter_value(content, "wave")
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
        if archive_milestone.contains_placeholder(title):
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
        if not acceptance or archive_milestone.contains_placeholder(acceptance):
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


def plan_wave_depths(plan_text: str) -> tuple[Sequence[int], dict[int, str]]:
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
    return wave_numbers, wave_depths


def review_cycle_counts(archive: Path) -> Sequence[int]:
    plan = archive / "plan" / "PLAN.md"
    plan_text = plan.read_text(encoding="utf-8")
    wave_numbers, wave_depths = plan_wave_depths(plan_text)
    wave_tasks = archived_wave_tasks(archive, wave_numbers)
    wave_criteria = plan_wave_criteria(archive, plan_text, wave_tasks)

    artifacts = {}
    panel_config = archive_milestone.plan_review_panel_config(plan_text)
    panel_skip_receipts = archive_milestone.canonical_wave_panel_skip_files(archive / "review")
    wave_artifacts = archive_milestone.canonical_wave_files(archive / "review")
    archive_milestone.validate_wave_skeptic_files(archive / "review", wave_depths, wave_artifacts)
    for path, wave, cycle, lens in wave_artifacts:
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
                    archive_milestone.validate_panel_skip_receipt(
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
    active_root = archive_milestone.require_project_layout(project)
    state, _, loaded_state_path = archive_milestone.strict_state(project)
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
    archive = archive_milestone.archive_from_state(project, configured)
    archive_milestone.require_archive_milestone(archive.name, state)
    archive_milestone.require_uncommitted_archive(project, configured)
    if archive.is_symlink() or not archive.is_dir():
        raise ArchiveError("archive is missing")
    archive_milestone.require_canonical_archive(archive)
    archive_milestone.require_clean_active_root(active_root, archive)

    reviewed_head, criteria = parse_final_review(archive)
    validate_gap_reviews(archive, reviewed_head)
    tasks, attested = archive_milestone.landed_task_evidence(project, archive / "tasks", reviewed_head)
    cycles = review_cycle_counts(archive)
    carried_forward = archive_milestone.pending_ruling_count(archive / "research" / "DOCS-AUDIT.md")
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
        + (f"  Attested: {attested}" if attested else "")
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
    if archive_milestone.contains_placeholder(placeholder_content):
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
    task_files, attested = archive_milestone.landed_task_evidence(project, archive / "tasks", reviewed_head)
    cycle_counts = review_cycle_counts(archive)
    wave_count = len(cycle_counts)
    counts = re.fullmatch(
        r"(\d+)\s+Tasks:\s+(\d+) done / (\d+) total\s+Review cycles used:\s+([1-9]\d*(?:/[1-9]\d*)*)"
        r"(?:\s+Attested:\s+([1-9]\d*))?",
        fields["Waves:"],
    )
    if not counts:
        raise ArchiveError("manifest Waves field has an invalid format")
    recorded_waves, done_tasks, total_tasks = (int(counts.group(index)) for index in (1, 2, 3))
    cycles = [int(value) for value in counts.group(4).split("/")]
    recorded_attested = int(counts.group(5) or 0)
    if (
        recorded_waves != wave_count
        or done_tasks != len(task_files)
        or total_tasks != len(task_files)
        or cycles != list(cycle_counts)
        or recorded_attested != attested
    ):
        raise ArchiveError("manifest wave, task, or review-cycle counts do not match the archive")

    carried_forward = archive_milestone.pending_ruling_count(archive / "research" / "DOCS-AUDIT.md")
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
        cells = archive_milestone.split_manifest_row(line)
        if cells and (cells[0] == "Criterion" or set(cells[0]) <= {"-", ":"}):
            continue
        criteria_rows.append(cells)
    if not criteria_rows or any(
        len(row) != 3
        or not row[0]
        or row[1] != "met"
        or not row[2]
        or row[2] == "none"
        or any(archive_milestone.contains_placeholder(cell) for cell in row)
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
    if not notes or any(not note or archive_milestone.contains_placeholder(note) for note in notes):
        raise ArchiveError("manifest Notes section is incomplete")
    return actual, reviewed_head


# archive_milestone imports this module, so the parent is resolved after the
# definitions above. Parent functions are looked up on the module at call time
# so patches applied to archive_milestone stay visible here.
if __package__:  # imported as scripts.discussion_validate
    from . import archive_milestone
    from .archive_milestone import (
        ANSWER_HEADING_PATTERN,
        CARRY_TEMP_NAME,
        DIALOGUE_HEADING_PATTERN,
        DISCUSSION_FILES,
        DISCUSSION_PHASES,
        DISCUSSION_TRANSACTION_NAME,
        DISPOSITION_HEADING_PATTERN,
        EMPTY_DISCUSSION_FILES,
        FINAL_CRITERION_PATTERN,
        FINAL_GAP_FILE_PATTERN,
        FINAL_GAP_HEADING_PATTERN,
        HTML_COMMENT_PATTERN,
        INTENT_CRITERION_PATTERN,
        MANIFEST_FIELDS,
        MANIFEST_HEADINGS,
        MANIFEST_TEMP_NAME,
        PLAN_COVERAGE_ROW_PATTERN,
        WAVE_SC_HEADING_PATTERN,
        WAVE_TASK_HEADING_PATTERN,
        ArchiveError,
    )
else:  # standalone script or sibling import
    import archive_milestone
    from archive_milestone import (
        ANSWER_HEADING_PATTERN,
        CARRY_TEMP_NAME,
        DIALOGUE_HEADING_PATTERN,
        DISCUSSION_FILES,
        DISCUSSION_PHASES,
        DISCUSSION_TRANSACTION_NAME,
        DISPOSITION_HEADING_PATTERN,
        EMPTY_DISCUSSION_FILES,
        FINAL_CRITERION_PATTERN,
        FINAL_GAP_FILE_PATTERN,
        FINAL_GAP_HEADING_PATTERN,
        HTML_COMMENT_PATTERN,
        INTENT_CRITERION_PATTERN,
        MANIFEST_FIELDS,
        MANIFEST_HEADINGS,
        MANIFEST_TEMP_NAME,
        PLAN_COVERAGE_ROW_PATTERN,
        WAVE_SC_HEADING_PATTERN,
        WAVE_TASK_HEADING_PATTERN,
        ArchiveError,
    )
