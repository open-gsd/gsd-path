#!/usr/bin/env python3
"""Promote or recover a GSD Path lookahead track transaction."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

import archive_milestone
import detect_project


SCHEMA = "gsd-path/lookahead-promotion/v1"
JOURNAL_NAME = ".lookahead-promotion.json"
ARTIFACTS = ("intent", "research", "plan", "tasks")
PHASES = {"inspect", "define", "research", "decide", "plan"}
STATUSES = {"active", "blocked", "done"}
BRANCH_RE = re.compile(r"^gsd-path/M\d{3,}$")
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ROADMAP_HEADING_RE = re.compile(r"^### (M\d{3,}) — (.+)$")


class LookaheadError(RuntimeError):
    pass


class NeedsRecovery(LookaheadError):
    def __init__(self, milestone: str, reason: str):
        super().__init__(reason)
        self.milestone = milestone
        self.reason = reason


def read_text(path: Path, description: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise LookaheadError(f"cannot read {description} {path}: {error}") from error


def path_mode(path: Path) -> Optional[int]:
    try:
        return path.lstat().st_mode
    except (FileNotFoundError, NotADirectoryError):
        return None
    except OSError as error:
        raise LookaheadError(f"cannot inspect path {path}: {error}") from error


def require_directory(path: Path, description: str) -> None:
    mode = path_mode(path)
    if mode is None or not stat.S_ISDIR(mode):
        raise LookaheadError(f"{description} must be a real directory: {path}")


def require_file(path: Path, description: str) -> None:
    mode = path_mode(path)
    if mode is None or not stat.S_ISREG(mode):
        raise LookaheadError(f"{description} must be a real file: {path}")


def atomic_write(path: Path, content: str) -> None:
    archive_milestone.atomic_replace(
        path,
        path.parent / f".{path.name}.gsd-path-tmp",
        content,
    )


def state_value(content: str, key: str) -> str:
    try:
        value = archive_milestone.frontmatter_value(content, key)
    except archive_milestone.ArchiveError as error:
        raise LookaheadError(str(error)) from error
    return value or ""


def update_state(content: str, values: dict[str, str]) -> str:
    try:
        for key, value in values.items():
            content = archive_milestone.set_frontmatter_value(content, key, value)
    except archive_milestone.ArchiveError as error:
        raise LookaheadError(str(error)) from error
    return content


def normalized_path(value: str) -> str:
    return value.rstrip("/")


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
    normalized = archive_milestone.normalized_slug(milestone)
    matches = [
        block
        for block in roadmap_blocks(content)
        if archive_milestone.normalized_slug(block["title"]) == normalized
    ]
    if len(matches) != 1:
        raise LookaheadError(f"ROADMAP.md must contain exactly one entry for {milestone}")
    return matches[0]


def roadmap_transition(
    content: str,
    milestone: str,
    archive: str,
    integrate: str,
) -> str:
    lines = content.splitlines(keepends=True)
    selected = milestone_block(content, milestone)
    status = selected["fields"].get("Status")
    if status is None or status[1] != "pending":
        raise LookaheadError(f"lookahead milestone {milestone} is not pending")
    dependencies = selected["fields"].get("Depends on")
    if dependencies is None:
        raise LookaheadError(f"lookahead milestone {milestone} lacks dependencies")
    dependency_list = re.fullmatch(
        r"\[\s*(M\d{3,}(?:\s*,\s*M\d{3,})*)?\s*\]",
        dependencies[1],
    )
    if dependency_list is None:
        raise LookaheadError(f"lookahead milestone {milestone} has invalid dependencies")
    dependency_ids = (
        re.findall(r"M\d{3,}", dependency_list.group(1))
        if dependency_list.group(1)
        else []
    )
    blocks_by_id = {block["id"]: block for block in roadmap_blocks(content)}
    unready = [
        dependency
        for dependency in dependency_ids
        if dependency not in blocks_by_id
        or blocks_by_id[dependency]["fields"].get("Status", (-1, ""))[1]
        != "shipped"
    ]
    if unready:
        raise LookaheadError(
            f"lookahead milestone {milestone} has unshipped dependencies: "
            + ", ".join(unready)
        )
    previous = [
        block
        for block in roadmap_blocks(content)
        if normalized_path(block["fields"].get("Archive", (-1, ""))[1])
        == normalized_path(archive)
    ]
    if len(previous) != 1 or previous[0]["id"] == selected["id"]:
        raise LookaheadError("ROADMAP.md does not identify the shipped milestone")
    previous_status = previous[0]["fields"].get("Status")
    if previous_status is None or previous_status[1] != "shipped":
        raise LookaheadError("previous roadmap milestone is not shipped")
    integrated = previous[0]["fields"].get("Integrated")
    if integrated is None:
        raise LookaheadError("previous roadmap milestone lacks Integrated field")
    if integrated[1] not in {"null", integrate}:
        raise LookaheadError("previous roadmap milestone has a different integration SHA")
    lines[status[0]] = "Status: active\n"
    lines[integrated[0]] = f"Integrated: {integrate}\n"
    return "".join(lines)


def roadmap_is_complete(
    content: str,
    milestone: str,
    branch: str,
    integrate: str,
) -> bool:
    try:
        selected = milestone_block(content, milestone)
    except LookaheadError:
        return False
    status = selected["fields"].get("Status")
    return bool(
        status
        and status[1] == "active"
        and branch == f"gsd-path/{selected['id']}"
        and any(
            block["fields"].get("Integrated", (-1, ""))[1] == integrate
            for block in roadmap_blocks(content)
        )
    )


def ruling_rows(audit: Path) -> list[str]:
    require_file(audit, "DOCS-AUDIT.md")
    in_rulings = False
    rows = []
    for line in read_text(audit, "DOCS-AUDIT.md").splitlines():
        if line == "## User rulings":
            in_rulings = True
            continue
        if in_rulings and line.startswith("## "):
            break
        if not in_rulings or not line.lstrip().startswith("|"):
            continue
        fields = [field.strip() for field in line.strip().strip("|").split("|")]
        if not fields or fields[0] in {"Queue #", "---------"}:
            continue
        rows.append(line)
    return rows


def pending_rows(rows: Sequence[str]) -> bool:
    return any(
        [field.strip() for field in row.strip().strip("|").split("|")][-1] == "no"
        for row in rows
    )


def directory_fingerprint(path: Path) -> str:
    require_directory(path, "artifact directory")
    digest = hashlib.sha256()

    def walk_error(error: OSError) -> None:
        raise LookaheadError(f"cannot scan artifact directory {path}: {error}") from error

    for directory, dirnames, filenames in os.walk(
        path,
        followlinks=False,
        onerror=walk_error,
    ):
        current = Path(directory)
        dirnames.sort()
        filenames.sort()
        for name in dirnames:
            child = current / name
            mode = path_mode(child)
            if mode is None or not stat.S_ISDIR(mode):
                raise LookaheadError(f"artifact directories must not contain links: {child}")
            digest.update(f"D:{child.relative_to(path).as_posix()}\0".encode())
        for name in filenames:
            child = current / name
            mode = path_mode(child)
            if mode is None or not stat.S_ISREG(mode):
                raise LookaheadError(f"artifact files must be regular files: {child}")
            digest.update(f"F:{child.relative_to(path).as_posix()}\0".encode())
            try:
                digest.update(child.read_bytes())
            except OSError as error:
                raise LookaheadError(f"cannot read artifact file {child}: {error}") from error
            digest.update(b"\0")
    return digest.hexdigest()


def carry_matches(active_research: Path, archived_audit: Path) -> bool:
    if path_mode(active_research) is None:
        return False
    require_directory(active_research, "active research carry-forward")
    entries = list(active_research.iterdir())
    if len(entries) != 1 or entries[0].name != "DOCS-AUDIT.md":
        return False
    require_file(entries[0], "active DOCS-AUDIT carry-forward")
    try:
        return entries[0].read_bytes() == archived_audit.read_bytes()
    except OSError as error:
        raise LookaheadError(f"cannot compare DOCS-AUDIT carry-forward: {error}") from error


def required_artifacts(phase: str, status: str) -> set[str]:
    required: set[str] = set()
    if phase == "inspect" and status == "done":
        required.add("research")
    elif phase == "define":
        required.add("research")
        if status == "done":
            required.add("intent")
    elif phase in {"research", "decide", "plan"}:
        required.update({"intent", "research"})
        if phase == "plan" and status == "done":
            required.update({"plan", "tasks"})
    return required


def validate_git(repo: Path, branch: str, integrate: str) -> None:
    if not BRANCH_RE.fullmatch(branch):
        raise LookaheadError(f"invalid bound branch: {branch}")
    if not SHA_RE.fullmatch(integrate):
        raise LookaheadError("integrate must be a full lowercase commit SHA")
    current = subprocess.run(
        ["git", "-C", str(repo), "symbolic-ref", "--quiet", "--short", "HEAD"],
        capture_output=True,
        text=True,
    )
    if current.returncode != 0 or current.stdout.strip() != branch:
        raise LookaheadError(f"current branch must be {branch}")
    resolved = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--verify", f"{integrate}^{{commit}}"],
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != integrate:
        raise LookaheadError("integrate SHA does not resolve exactly")
    ancestor = subprocess.run(
        ["git", "-C", str(repo), "merge-base", "--is-ancestor", integrate, "HEAD"],
        capture_output=True,
        text=True,
    )
    if ancestor.returncode != 0:
        raise LookaheadError("integrate SHA is not an ancestor of the bound branch")


def validate_integration(
    root: Path,
    active_state: str,
    archive: Path,
    configured_archive: str,
    integrate: str,
) -> None:
    try:
        remote_default = archive_milestone.resolve_remote_default(root)
        default_name = archive_milestone.default_branch_name(remote_default)
        expected_subject = archive_milestone.integrate_subject(
            archive.name,
            default_name,
        )
        log = archive_milestone.require_git_success(
            archive_milestone.run_git(
                root,
                "log",
                "--first-parent",
                "--format=%H%x00%s",
                remote_default,
            ),
            "inspect integration history",
        )
        matches = [
            commit
            for record in log.splitlines()
            if "\x00" in record
            for commit, subject in [record.split("\x00", 1)]
            if archive_milestone.is_integrate_subject(
                subject,
                archive.name,
                default_name,
            )
        ]
        if not matches or matches[0] != integrate:
            raise LookaheadError(
                f"integrate SHA is not the validated {expected_subject!r} commit"
            )
        parents = archive_milestone.require_git_success(
            archive_milestone.run_git(
                root,
                "rev-list",
                "--parents",
                "-n",
                "1",
                integrate,
            ),
            "inspect integration parents",
        ).split()
        if len(parents) != 3:
            raise LookaheadError("integration commit is not a two-parent merge")
        ship_commit = parents[2]
        ship_subject = archive_milestone.require_git_success(
            archive_milestone.run_git(root, "log", "-1", "--format=%s", ship_commit),
            "inspect ship commit subject",
        )
        if not archive_milestone.is_ship_subject(ship_subject, archive.name):
            raise LookaheadError("integration second parent is not the shipped milestone")
        bound_branch = state_value(active_state, "branch")
        archive_milestone.require_canonical_commit_body(
            root,
            integrate,
            expected_subject,
            archive_milestone.integrate_commit_body(
                configured_archive,
                ship_commit,
                default_name,
                bound_branch,
            ),
            "integration",
        )
        tag_ref = f"refs/tags/milestone/{archive.name}"
        tag_type = archive_milestone.require_git_success(
            archive_milestone.run_git(root, "cat-file", "-t", tag_ref),
            "inspect milestone tag",
        )
        tag_target = archive_milestone.require_git_success(
            archive_milestone.run_git(root, "rev-parse", f"{tag_ref}^{{commit}}"),
            "resolve milestone tag",
        )
        if tag_type != "tag" or tag_target != integrate:
            raise LookaheadError("milestone tag does not identify the integration merge")
    except archive_milestone.ArchiveError as error:
        raise LookaheadError(str(error)) from error


def safe_project(repo: Path) -> tuple[Path, Path]:
    root = repo.resolve()
    require_directory(root, "repository")
    project = root / ".project"
    require_directory(project, ".project")
    try:
        verdict = detect_project.classify(root)
    except detect_project.DetectError as error:
        raise LookaheadError(str(error)) from error
    if verdict["verdict"] != "owned":
        raise LookaheadError(f"project classifier returned {verdict['verdict']}")
    require_file(project / "STATE.md", "active STATE.md")
    require_file(project / "ROADMAP.md", "ROADMAP.md")
    return root, project


def transaction_archive(root: Path, active_state: str) -> tuple[str, Path]:
    configured = state_value(active_state, "archive")
    if archive_milestone.is_unset(configured):
        raise LookaheadError("active STATE.md does not name the shipped archive")
    try:
        archive = archive_milestone.archive_from_state(root, configured)
    except archive_milestone.ArchiveError as error:
        raise LookaheadError(str(error)) from error
    require_directory(archive, "shipped archive")
    return normalized_path(configured), archive


def prepare_transaction(
    root: Path,
    project: Path,
    branch: str,
    integrate: str,
    allow_audit_mismatch: bool,
) -> dict:
    status_result = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
    )
    if status_result.returncode != 0:
        raise LookaheadError("cannot inspect worktree status before promotion")
    dirty_paths = {
        line[3:]
        for line in status_result.stdout.splitlines()
        if len(line) >= 4
    }
    unexpected_dirty = dirty_paths - {".project/STATE.md"}
    if unexpected_dirty:
        raise LookaheadError(
            "unexpected worktree changes before promotion: "
            + ", ".join(sorted(unexpected_dirty))
        )
    next_root = project / "next"
    require_directory(next_root, "lookahead root")
    next_state_path = next_root / "STATE.md"
    require_file(next_state_path, "lookahead STATE.md")
    names = {entry.name for entry in next_root.iterdir()}
    unexpected = names - {"STATE.md", *ARTIFACTS}
    if unexpected:
        raise LookaheadError(f"lookahead root has unexpected entries: {', '.join(sorted(unexpected))}")

    active_state_path = project / "STATE.md"
    roadmap_path = project / "ROADMAP.md"
    active_state = read_text(active_state_path, "active STATE.md")
    track_state = read_text(next_state_path, "lookahead STATE.md")
    roadmap = read_text(roadmap_path, "ROADMAP.md")
    if state_value(active_state, "pipeline") != archive_milestone.PIPELINE_MARKER:
        raise LookaheadError("active STATE.md is not owned by gsd-path/v2")
    if (
        state_value(active_state, "phase"),
        state_value(active_state, "status"),
    ) != ("shipped", "done"):
        raise LookaheadError("active STATE.md must be shipped/done")
    if state_value(track_state, "pipeline") != archive_milestone.PIPELINE_MARKER:
        raise LookaheadError("lookahead STATE.md is not owned by gsd-path/v2")
    phase = state_value(track_state, "phase")
    status = state_value(track_state, "status")
    milestone = state_value(track_state, "milestone")
    if phase not in PHASES or status not in STATUSES:
        raise LookaheadError(f"invalid lookahead state: {phase}/{status}")
    if archive_milestone.is_unset(milestone):
        raise LookaheadError("lookahead STATE.md does not name a milestone")
    if not archive_milestone.is_unset(state_value(track_state, "branch")):
        raise LookaheadError("lookahead STATE.md must not bind a branch")
    if not archive_milestone.is_unset(state_value(track_state, "archive")):
        raise LookaheadError("lookahead STATE.md must not own an archive")

    configured_archive, archive = transaction_archive(root, active_state)
    validate_integration(
        root,
        active_state,
        archive,
        configured_archive,
        integrate,
    )
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    archived_audit_mode = path_mode(archived_audit)
    if archived_audit_mode is None:
        archived_rows = []
    elif stat.S_ISREG(archived_audit_mode):
        archived_rows = ruling_rows(archived_audit)
    else:
        raise LookaheadError(
            f"archived DOCS-AUDIT.md must be a regular file: {archived_audit}"
        )
    pending = pending_rows(archived_rows)
    active_research = project / "research"
    if pending:
        if not carry_matches(active_research, archived_audit):
            raise LookaheadError("active DOCS-AUDIT carry-forward differs from the shipped archive")
    elif path_mode(active_research) is not None:
        raise LookaheadError("active research exists without pending carry-forward rulings")

    artifacts = {}
    for name in ARTIFACTS:
        source = next_root / name
        destination = project / name
        destination_mode = path_mode(destination)
        if destination_mode is not None and not (
            name == "research"
            and pending
            and carry_matches(destination, archived_audit)
        ):
            raise LookaheadError(f"unowned promotion destination exists: {destination}")
        source_mode = path_mode(source)
        if source_mode is None:
            continue
        if not stat.S_ISDIR(source_mode):
            raise LookaheadError(f"lookahead artifact must be a real directory: {source}")
        artifacts[name] = directory_fingerprint(source)
    missing = required_artifacts(phase, status) - set(artifacts)
    if missing:
        raise LookaheadError(f"lookahead state lacks required artifacts: {', '.join(sorted(missing))}")

    if "research" in artifacts:
        track_audit = next_root / "research" / "DOCS-AUDIT.md"
        try:
            track_rows = ruling_rows(track_audit)
        except LookaheadError as error:
            if not allow_audit_mismatch:
                raise NeedsRecovery(milestone, str(error)) from error
            track_rows = []
        missing_rows = [row for row in archived_rows if row not in track_rows]
        if missing_rows and not allow_audit_mismatch:
            raise NeedsRecovery(
                milestone,
                "lookahead DOCS-AUDIT does not preserve shipped user rulings",
            )

    final_state = update_state(
        active_state,
        {
            "phase": phase,
            "status": status,
            "milestone": milestone,
            "branch": branch,
            "archive": "null",
        },
    )
    final_roadmap = roadmap_transition(
        roadmap,
        milestone,
        configured_archive,
        integrate,
    )
    selected = milestone_block(roadmap, milestone)
    if branch != f"gsd-path/{selected['id']}":
        raise LookaheadError(
            f"bound branch {branch} does not match roadmap milestone {selected['id']}"
        )
    return {
        "schema": SCHEMA,
        "action": "promote",
        "branch": branch,
        "integrate": integrate,
        "milestone": milestone,
        "archive": configured_archive,
        "active_state_before": active_state,
        "track_state": track_state,
        "final_state": final_state,
        "roadmap_before": roadmap,
        "final_roadmap": final_roadmap,
        "artifacts": artifacts,
        "pending_carry": pending,
    }


def journal_path(project: Path) -> Path:
    return project / JOURNAL_NAME


def write_journal(project: Path, transaction: dict) -> None:
    atomic_write(journal_path(project), json.dumps(transaction, sort_keys=True) + "\n")


def load_journal(project: Path, branch: str, integrate: str) -> Optional[dict]:
    path = journal_path(project)
    if path_mode(path) is None:
        return None
    require_file(path, "lookahead promotion journal")
    try:
        transaction = json.loads(read_text(path, "lookahead promotion journal"))
    except json.JSONDecodeError as error:
        raise LookaheadError(f"lookahead promotion journal is invalid: {error}") from error
    required = {
        "schema",
        "action",
        "branch",
        "integrate",
        "milestone",
        "archive",
        "active_state_before",
        "track_state",
        "final_state",
        "roadmap_before",
        "final_roadmap",
        "artifacts",
        "pending_carry",
    }
    if not isinstance(transaction, dict) or not required <= set(transaction):
        raise LookaheadError("lookahead promotion journal has invalid fields")
    if transaction["schema"] != SCHEMA:
        raise LookaheadError("lookahead promotion journal has the wrong schema")
    string_fields = required - {"artifacts", "pending_carry"}
    if any(not isinstance(transaction[field], str) for field in string_fields):
        raise LookaheadError("lookahead promotion journal has invalid text fields")
    if transaction["action"] not in {"promote", "rewind", "discard"}:
        raise LookaheadError("lookahead promotion journal has an invalid action")
    if transaction["branch"] != branch or transaction["integrate"] != integrate:
        raise LookaheadError("lookahead promotion journal belongs to another handoff")
    if (
        not isinstance(transaction["artifacts"], dict)
        or not set(transaction["artifacts"]) <= set(ARTIFACTS)
        or any(
            not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
            for value in transaction["artifacts"].values()
        )
        or not isinstance(transaction["pending_carry"], bool)
    ):
        raise LookaheadError("lookahead promotion journal has invalid artifacts")
    return transaction


def verify_artifact(path: Path, expected: str) -> None:
    if directory_fingerprint(path) != expected:
        raise LookaheadError(f"lookahead artifact changed during transaction: {path}")


def remove_artifact(path: Path, expected: str, archived_audit: Path) -> None:
    if path_mode(path) is None:
        return
    if path.name == "research" and carry_matches(path, archived_audit):
        shutil.rmtree(path)
        return
    verify_artifact(path, expected)
    shutil.rmtree(path)


def finish_next(project: Path, transaction: dict) -> None:
    next_root = project / "next"
    if path_mode(next_root) is None:
        return
    require_directory(next_root, "lookahead root")
    state = next_root / "STATE.md"
    if path_mode(state) is not None:
        require_file(state, "lookahead STATE.md")
        if read_text(state, "lookahead STATE.md") != transaction["track_state"]:
            raise LookaheadError("lookahead STATE.md changed during transaction")
        state.unlink()
    remaining = list(next_root.iterdir())
    if remaining:
        raise LookaheadError(
            "lookahead cleanup has unexpected entries: "
            + ", ".join(sorted(path.name for path in remaining))
        )
    next_root.rmdir()


def write_transition_files(project: Path, transaction: dict) -> None:
    state_path = project / "STATE.md"
    roadmap_path = project / "ROADMAP.md"
    state = read_text(state_path, "active STATE.md")
    allowed_states = {
        transaction["active_state_before"],
        transaction["final_state"],
    }
    if "prior_final_state" in transaction:
        allowed_states.add(transaction["prior_final_state"])
    if state not in allowed_states:
        raise LookaheadError("active STATE.md changed during promotion")
    roadmap = read_text(roadmap_path, "ROADMAP.md")
    allowed_roadmaps = {
        transaction["roadmap_before"],
        transaction["final_roadmap"],
    }
    if roadmap not in allowed_roadmaps:
        raise LookaheadError("ROADMAP.md changed during promotion")
    atomic_write(state_path, transaction["final_state"])
    atomic_write(roadmap_path, transaction["final_roadmap"])


def resume_promotion(root: Path, project: Path, transaction: dict) -> dict:
    next_root = project / "next"
    archive = root / transaction["archive"]
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    for name in ARTIFACTS:
        if name not in transaction["artifacts"]:
            continue
        expected = transaction["artifacts"][name]
        source = next_root / name
        destination = project / name
        source_exists = path_mode(source) is not None
        destination_exists = path_mode(destination) is not None
        if source_exists:
            verify_artifact(source, expected)
        if source_exists and destination_exists:
            if name != "research" or not transaction["pending_carry"]:
                raise LookaheadError(f"promotion collision: {destination}")
            if not carry_matches(destination, archived_audit):
                raise LookaheadError("active carry-forward changed during promotion")
            shutil.rmtree(destination)
            destination_exists = False
        if source_exists and not destination_exists:
            os.replace(source, destination)
        elif not source_exists and destination_exists:
            verify_artifact(destination, expected)
        elif not source_exists and not destination_exists:
            raise LookaheadError(f"promotion artifact disappeared: {name}")
    write_transition_files(project, transaction)
    finish_next(project, transaction)
    journal_path(project).unlink()
    return {
        "status": "promoted",
        "milestone": transaction["milestone"],
        "phase": state_value(transaction["final_state"], "phase"),
        "state_status": state_value(transaction["final_state"], "status"),
    }


def already_transitioned(project: Path, branch: str, integrate: str, recovery: bool) -> Optional[dict]:
    if path_mode(project / "next") is not None:
        return None
    state = read_text(project / "STATE.md", "active STATE.md")
    milestone = state_value(state, "milestone")
    phase = state_value(state, "phase")
    status = state_value(state, "status")
    if (
        state_value(state, "branch") != branch
        or not archive_milestone.is_unset(state_value(state, "archive"))
        or archive_milestone.is_unset(milestone)
        or not roadmap_is_complete(
            read_text(project / "ROADMAP.md", "ROADMAP.md"),
            milestone,
            branch,
            integrate,
        )
    ):
        return None
    if recovery and (phase, status) != ("inspect", "active"):
        return None
    return {
        "status": "already-recovered" if recovery else "already-promoted",
        "milestone": milestone,
        "phase": phase,
        "state_status": status,
    }


def promote(repo: Path, branch: str, integrate: str) -> dict:
    root, project = safe_project(repo)
    validate_git(root, branch, integrate)
    with archive_milestone.discussion_lock(project):
        transaction = load_journal(project, branch, integrate)
        if transaction is None:
            complete = already_transitioned(project, branch, integrate, recovery=False)
            if complete:
                return complete
            transaction = prepare_transaction(
                root,
                project,
                branch,
                integrate,
                allow_audit_mismatch=False,
            )
            write_journal(project, transaction)
        if transaction["action"] != "promote":
            raise LookaheadError("lookahead journal is a recovery transaction")
        return resume_promotion(root, project, transaction)


def recovery_transaction(
    transaction: dict,
    strategy: str,
) -> dict:
    transaction = dict(transaction)
    if transaction["action"] in {"rewind", "discard"} and transaction["action"] != strategy:
        raise LookaheadError("recovery strategy differs from the journaled choice")
    if transaction["action"] == "promote":
        transaction["prior_final_state"] = transaction["final_state"]
    transaction["action"] = strategy
    transaction["final_state"] = update_state(
        transaction["active_state_before"],
        {
            "phase": "inspect",
            "status": "active",
            "milestone": transaction["milestone"],
            "branch": transaction["branch"],
            "archive": "null",
        },
    )
    return transaction


def resume_recovery(root: Path, project: Path, transaction: dict) -> dict:
    next_root = project / "next"
    archive = root / transaction["archive"]
    archived_audit = archive / "research" / "DOCS-AUDIT.md"
    for name, expected in transaction["artifacts"].items():
        remove_artifact(next_root / name, expected, archived_audit)
        remove_artifact(project / name, expected, archived_audit)
    active_research = project / "research"
    if transaction["pending_carry"]:
        if path_mode(active_research) is not None and not carry_matches(active_research, archived_audit):
            raise LookaheadError("cannot restore carry-forward over changed active research")
        active_research.mkdir(exist_ok=True)
        archive_milestone.atomic_copy(
            archived_audit,
            active_research / "DOCS-AUDIT.md",
        )
    elif path_mode(active_research) is not None:
        raise LookaheadError("active research remains after recovery cleanup")
    write_transition_files(project, transaction)
    finish_next(project, transaction)
    journal_path(project).unlink()
    return {
        "status": "recovered",
        "strategy": transaction["action"],
        "milestone": transaction["milestone"],
        "phase": "inspect",
        "state_status": "active",
    }


def recover(repo: Path, branch: str, integrate: str, strategy: str) -> dict:
    root, project = safe_project(repo)
    validate_git(root, branch, integrate)
    with archive_milestone.discussion_lock(project):
        transaction = load_journal(project, branch, integrate)
        if transaction is None:
            complete = already_transitioned(project, branch, integrate, recovery=True)
            if complete:
                complete["strategy"] = strategy
                return complete
            try:
                prepare_transaction(
                    root,
                    project,
                    branch,
                    integrate,
                    allow_audit_mismatch=False,
                )
            except NeedsRecovery:
                transaction = prepare_transaction(
                    root,
                    project,
                    branch,
                    integrate,
                    allow_audit_mismatch=True,
                )
            else:
                raise LookaheadError("lookahead recovery is not required")
        transaction = recovery_transaction(transaction, strategy)
        write_journal(project, transaction)
        return resume_recovery(root, project, transaction)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    promote_parser = subparsers.add_parser("promote")
    promote_parser.add_argument("--repo", required=True, type=Path)
    promote_parser.add_argument("--branch", required=True)
    promote_parser.add_argument("--integrate", required=True)
    recover_parser = subparsers.add_parser("recover")
    recover_parser.add_argument("--repo", required=True, type=Path)
    recover_parser.add_argument("--branch", required=True)
    recover_parser.add_argument("--integrate", required=True)
    recover_parser.add_argument(
        "--strategy",
        required=True,
        choices=("rewind", "discard"),
    )
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "promote":
            result = promote(arguments.repo, arguments.branch, arguments.integrate)
        else:
            result = recover(
                arguments.repo,
                arguments.branch,
                arguments.integrate,
                arguments.strategy,
            )
    except NeedsRecovery as error:
        print(
            json.dumps(
                {
                    "status": "needs-recovery",
                    "milestone": error.milestone,
                    "reason": error.reason,
                },
                sort_keys=True,
            )
        )
        return 2
    except (LookaheadError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
