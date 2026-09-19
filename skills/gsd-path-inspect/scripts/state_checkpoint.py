#!/usr/bin/env python3
# gsd-path project runtime
"""Checkpoint plan and roadmap approvals and classify plan drift for pipeline_state."""

from __future__ import annotations

import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True

import hashlib
import json
import os
import re
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

try:
    from isolation import IsolationError, checkpoint as isolation_checkpoint, require_commit, require_full_sha, PROJECT_ENTRIES
except ModuleNotFoundError as error:  # pragma: no cover - package imports used by tests
    if error.name != "isolation":
        raise
    from scripts.isolation import IsolationError, checkpoint as isolation_checkpoint, require_commit, require_full_sha, PROJECT_ENTRIES


if __package__:
    from . import roadmap
else:
    import roadmap

if __package__:  # imported as scripts.state_checkpoint
    from . import pipeline_state
    from .pipeline_state import (
        CHECKPOINT_JOURNAL_NAME,
        CHECKPOINT_KINDS,
        CHECKPOINT_SCHEMA,
        PLAN_APPROVAL_SUBJECT,
        PROMOTION_TRACKS,
        SLUG_RE,
        TASK_FILE_RE,
        TASK_ID_RE,
        ApprovedTaskContract,
        PipelineState,
        PipelineStateError,
    )
else:  # standalone script or sibling import
    import pipeline_state
    from pipeline_state import (
        CHECKPOINT_JOURNAL_NAME,
        CHECKPOINT_KINDS,
        CHECKPOINT_SCHEMA,
        PLAN_APPROVAL_SUBJECT,
        PROMOTION_TRACKS,
        SLUG_RE,
        TASK_FILE_RE,
        TASK_ID_RE,
        ApprovedTaskContract,
        PipelineState,
        PipelineStateError,
    )


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _tree_digest(path: Path, excluded: Sequence[str] = ()) -> str:
    if path.is_symlink() or not path.is_dir():
        raise PipelineStateError(f"promotion path must be a real directory: {path}")
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise PipelineStateError(f"promotion path contains a symlink: {child}")
        relative = child.relative_to(path).as_posix()
        if PurePosixPath(relative).parts[0] in excluded:
            continue
        if child.is_dir():
            digest.update(f"d\0{relative}\0".encode())
        elif child.is_file():
            digest.update(f"f\0{relative}\0".encode())
            digest.update(child.read_bytes())
        else:
            raise PipelineStateError(f"promotion path is not a file or directory: {child}")
    return digest.hexdigest()


def _checkpoint_artifact_digest(project: Path, mutable_paths: set[str]) -> str:
    """Hash every approval artifact except the helper-owned metadata files."""
    digest = hashlib.sha256()
    for child in sorted(project.rglob("*")):
        if child.is_symlink():
            raise PipelineStateError(f"checkpoint path contains a symlink: {child}")
        relative = child.relative_to(project).as_posix()
        # Unsupported entries (OS junk) are refused by the checkpoint itself; leaving them
        # out lets a refused approval resume after the owner removes them.
        if relative in mutable_paths or relative.split("/", 1)[0] not in PROJECT_ENTRIES:
            continue
        if child.is_dir():
            digest.update(f"d\0{relative}\0".encode())
        elif child.is_file():
            digest.update(f"f\0{relative}\0".encode())
            digest.update(child.read_bytes())
        else:
            raise PipelineStateError(f"checkpoint path is not a file or directory: {child}")
    return digest.hexdigest()


def _activate_roadmap_milestone(text: str, milestone: str) -> str:
    try:
        return roadmap.activate_milestone(text, milestone)
    except roadmap.RoadmapError as error:
        raise PipelineStateError(str(error)) from error

def _approval_details(
    kind: str,
    state: PipelineState,
    selected_milestone: Optional[str],
) -> tuple[dict[str, Optional[str]], str, str, str]:
    if kind == "roadmap-reslice":
        if state.status != "active" or state.archive is not None:
            raise PipelineStateError("roadmap re-slice requires active, unarchived state")
        if state.phase in {"inspect", "define"} and selected_milestone == state.milestone and state.milestone:
            changes = {}
            event = "program roadmap re-slice approved"
        elif state.phase == "roadmap" and state.milestone is None and selected_milestone and SLUG_RE.fullmatch(selected_milestone):
            changes = {"phase": "inspect", "milestone": selected_milestone}
            event = "roadmap approved after abandoned milestone"
        else:
            raise PipelineStateError("roadmap re-slice must preserve the active milestone or select after abandon")
        return changes, event, "roadmap: program roadmap approved", "Why: approved roadmap checkpoint"
    if kind == "plan":
        if selected_milestone is not None:
            raise PipelineStateError("plan approval does not accept a selected milestone")
        if (state.phase, state.status) != ("plan", "active"):
            raise PipelineStateError("plan approval requires STATE plan/active")
        return (
            {"status": "done"},
            "plan approved",
            "plan: build plan approved",
            "Why: approved plan checkpoint\n"
            f"Milestone: {state.milestone or 'none'}",
        )
    if kind == "roadmap":
        if (state.phase, state.status) != ("roadmap", "active"):
            raise PipelineStateError("roadmap approval requires STATE roadmap/active")
        if selected_milestone is None or not SLUG_RE.fullmatch(selected_milestone):
            raise PipelineStateError("roadmap approval requires a selected milestone slug")
        return (
            {"status": "done", "milestone": selected_milestone},
            "program roadmap approved",
            "roadmap: program roadmap approved",
            "Why: approved roadmap checkpoint",
        )
    raise PipelineStateError(f"unsupported approval kind: {kind}")


def _reslice_roadmap(before: str, candidate: str, state: PipelineState, selected: str) -> str:
    try:
        return roadmap.reslice(before, candidate, state.phase, selected)
    except roadmap.RoadmapError as error:
        raise PipelineStateError(str(error)) from error

def _checkpoint_request_fields(
    kind: str,
    project_dir: str,
    selected_milestone: Optional[str],
    expected_head: str,
) -> dict[str, object]:
    return {
        "kind": kind,
        "project_dir": project_dir,
        "selected_milestone": selected_milestone,
        "expected_head": expected_head,
    }


def _checkpoint_file(repo: Path, relative: str, label: str) -> Path:
    path_value = PurePosixPath(relative)
    if (
        path_value.is_absolute()
        or ".." in path_value.parts
        or not path_value.parts
        or path_value.parts[0] != ".project"
    ):
        raise PipelineStateError(f"checkpoint {label} path is invalid: {relative}")
    path = repo.joinpath(*path_value.parts)
    if path.is_symlink() or not path.is_file():
        raise PipelineStateError(f"checkpoint {label} must be a real file: {path}")
    return path


def _approval_journal(repo: Path, journal: Mapping[str, object]) -> dict[str, object]:
    expected_keys = {
        "schema",
        "repo",
        "kind",
        "project_dir",
        "selected_milestone",
        "expected_head",
        "event",
        "event_date",
        "subject",
        "body",
        "artifact_digest",
        "state_path",
        "state_before",
        "state_after",
        "roadmap_path",
        "roadmap_before",
        "roadmap_after",
    }
    if journal.get("kind") == "roadmap-reslice":
        expected_keys.add("baseline_before")
        if not isinstance(journal.get("baseline_before"), str):
            raise PipelineStateError("checkpoint journal has an invalid re-slice baseline")
    if set(journal) != expected_keys:
        raise PipelineStateError("checkpoint journal has invalid fields")
    if journal.get("schema") != CHECKPOINT_SCHEMA or journal.get("repo") != str(repo):
        raise PipelineStateError("checkpoint journal does not belong to this worktree")
    string_fields = (
        "kind",
        "project_dir",
        "expected_head",
        "event",
        "event_date",
        "subject",
        "body",
        "artifact_digest",
        "state_path",
        "state_before",
        "state_after",
    )
    if any(not isinstance(journal.get(field), str) for field in string_fields):
        raise PipelineStateError("checkpoint journal has invalid string fields")
    if journal["kind"] not in CHECKPOINT_KINDS:
        raise PipelineStateError("checkpoint journal has invalid approval kind")
    if journal["project_dir"] not in {".project", ".project/next"}:
        raise PipelineStateError("checkpoint journal has invalid project directory")
    selected = journal["selected_milestone"]
    if selected is not None and not isinstance(selected, str):
        raise PipelineStateError("checkpoint journal has invalid selected milestone")
    roadmap_values = (
        journal["roadmap_path"],
        journal["roadmap_before"],
        journal["roadmap_after"],
    )
    if any(value is not None and not isinstance(value, str) for value in roadmap_values):
        raise PipelineStateError("checkpoint journal has invalid roadmap fields")

    expected_head = str(journal["expected_head"])
    resolved_head = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{expected_head}^{{commit}}",
    ).stdout.strip()
    if resolved_head != expected_head:
        raise PipelineStateError("checkpoint journal expected-head is not an exact commit SHA")

    project_dir = str(journal["project_dir"])
    expected_state_path = f"{project_dir}/STATE.md"
    if journal["state_path"] != expected_state_path:
        raise PipelineStateError("checkpoint journal has an invalid STATE path")
    before = pipeline_state._state_from_text(str(journal["state_before"]), "checkpoint before STATE.md")
    changes, event, subject, body = _approval_details(
        str(journal["kind"]),
        before,
        selected if isinstance(selected, str) else None,
    )
    expected = {
        "phase": before.phase,
        "status": before.status,
        "milestone": before.milestone,
        "branch": before.branch,
        "archive": before.archive,
    }
    _, after, rendered = pipeline_state._render_transition(
        before,
        str(journal["state_before"]),
        expected,
        changes,
        event,
        project_dir,
        str(journal["event_date"]),
        str(journal["kind"]),
    )
    if (
        journal["event"] != event
        or journal["subject"] != subject
        or journal["body"] != body
        or journal["state_after"] != rendered
    ):
        raise PipelineStateError("checkpoint journal approval contract is invalid")
    if journal["kind"] in {"roadmap", "roadmap-reslice"}:
        if project_dir != ".project":
            raise PipelineStateError("roadmap approval is legal only on the active track")
        if journal["roadmap_path"] != ".project/ROADMAP.md":
            raise PipelineStateError("checkpoint journal has an invalid ROADMAP path")
        expected_roadmap = _reslice_roadmap(
            str(journal["baseline_before"]), str(journal["roadmap_before"]), before, str(selected),
        ) if journal["kind"] == "roadmap-reslice" else _activate_roadmap_milestone(
            str(journal["roadmap_before"]),
            str(selected),
        )
        if journal["roadmap_after"] != expected_roadmap:
            raise PipelineStateError("checkpoint journal has an invalid ROADMAP result")
    elif any(value is not None for value in roadmap_values):
        raise PipelineStateError("plan checkpoint journal unexpectedly owns ROADMAP.md")
    pipeline_state._validate_state_context(after, project_dir, "checkpoint after STATE.md")
    return dict(journal)


def _remove_checkpoint_temporary(path: Path) -> None:
    temporary = path.parent / f".{path.name}.gsd-path-tmp"
    if temporary.is_symlink():
        raise PipelineStateError(f"checkpoint temporary path is a symlink: {temporary}")
    if temporary.exists():
        if not temporary.is_file():
            raise PipelineStateError(f"checkpoint temporary path is invalid: {temporary}")
        temporary.unlink()


def _converge_checkpoint_file(path: Path, before: str, after: str, label: str) -> None:
    _remove_checkpoint_temporary(path)
    current = pipeline_state._read_real_file(path, label)
    if current not in {before, after}:
        raise PipelineStateError(f"{label} drifted during checkpoint recovery")
    if current != after:
        pipeline_state._atomic_write(path, after)


def _unlink_checkpoint_journal(path: Path) -> None:
    path.unlink()
    descriptor = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _resume_checkpoint_locked(
    repo: Path,
    project: Path,
    journal_path: Path,
    journal: Mapping[str, object],
) -> dict[str, object]:
    transaction = _approval_journal(repo, journal)
    state_path = _checkpoint_file(repo, str(transaction["state_path"]), "STATE.md")
    mutable = {state_path.relative_to(project).as_posix()}
    baseline = project / "ROADMAP.before-reslice.md" if transaction["kind"] == "roadmap-reslice" else None
    if baseline is not None:
        mutable.add(baseline.name)
        if baseline.exists() or baseline.is_symlink():
            if pipeline_state._read_real_file(baseline, "re-slice baseline") != transaction["baseline_before"]:
                raise PipelineStateError("re-slice baseline drifted during checkpoint recovery")
    roadmap_path: Optional[Path] = None
    if transaction["roadmap_path"] is not None:
        roadmap_path = _checkpoint_file(
            repo,
            str(transaction["roadmap_path"]),
            "ROADMAP.md",
        )
        mutable.add(roadmap_path.relative_to(project).as_posix())
    _remove_checkpoint_temporary(state_path)
    if roadmap_path is not None:
        _remove_checkpoint_temporary(roadmap_path)
    if _checkpoint_artifact_digest(project, mutable) != transaction["artifact_digest"]:
        raise PipelineStateError("approval artifacts drifted after checkpoint preparation")
    outside = [path for path in pipeline_state._worktree_changes(repo) if not path.startswith(".project/")]
    if outside:
        raise PipelineStateError(
            "checkpoint found changes outside .project: " + ", ".join(outside)
        )

    head = pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    expected_head = str(transaction["expected_head"])
    if head == expected_head:
        _converge_checkpoint_file(
            state_path,
            str(transaction["state_before"]),
            str(transaction["state_after"]),
            "STATE.md",
        )
        if roadmap_path is not None:
            _converge_checkpoint_file(
                roadmap_path,
                str(transaction["roadmap_before"]),
                str(transaction["roadmap_after"]),
                "ROADMAP.md",
            )
    else:
        if pipeline_state._worktree_changes(repo):
            raise PipelineStateError("completed checkpoint has worktree drift")
        if pipeline_state._read_real_file(state_path, "STATE.md") != transaction["state_after"]:
            raise PipelineStateError("completed checkpoint has the wrong STATE.md")
        if roadmap_path is not None and (
            pipeline_state._read_real_file(roadmap_path, "ROADMAP.md")
            != transaction["roadmap_after"]
        ):
            raise PipelineStateError("completed checkpoint has the wrong ROADMAP.md")

    try:
        if baseline is not None and baseline.exists():
            baseline.unlink()
        committed = isolation_checkpoint(
            repo,
            expected_head,
            str(transaction["subject"]),
            str(transaction["body"]),
            [".project"],
        )
    except IsolationError as error:
        if baseline is not None and pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip() == expected_head:
            pipeline_state._atomic_write(baseline, str(transaction["baseline_before"]))
        raise PipelineStateError(f"approval checkpoint failed: {error}") from error
    if committed.get("commit") != pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip():
        raise PipelineStateError("approval checkpoint returned the wrong commit")
    _unlink_checkpoint_journal(journal_path)
    state = pipeline_state._state_from_text(str(transaction["state_after"]))
    return {
        "schema": CHECKPOINT_SCHEMA,
        "status": "approved",
        "kind": transaction["kind"],
        "project_dir": transaction["project_dir"],
        "commit": committed["commit"],
        "paths": committed.get("paths"),
        "state": state.json(),
    }


def _validate_plan_briefs(repo: Path, kind: str, project_dir: str) -> None:
    if kind != "plan":
        return
    if project_dir == ".project":
        pipeline_state._build_recovery().validate_plan(repo)
    head = pipeline_state._run_git(repo, "rev-parse", "--verify", "HEAD", check=False)
    if head.returncode != 0:
        # Pre-Git approval defers base-dependent checks to build.
        return
    try:
        from check_task_briefs import BriefError, validate_task_briefs
    except ModuleNotFoundError as error:  # pragma: no cover - package imports
        if error.name != "check_task_briefs":
            raise
        from scripts.check_task_briefs import BriefError, validate_task_briefs
    try:
        import check_handoffs
    except ModuleNotFoundError as error:
        if error.name != "check_handoffs":
            raise
        from scripts import check_handoffs
    try:
        tasks, dependency_files = check_handoffs.plan_brief_inputs(repo, project_dir)
        landed_bases = {}
        for task_id, text in tasks.items():
            if check_handoffs._task_scalar(text, task_id, "status") != "done":
                continue
            agent = check_handoffs._task_scalar(text, task_id, "agent")
            if agent in {"", "null"}:
                raise BriefError(f"{task_id} landed task has no recorded agent")
            recorded_base = check_handoffs._task_scalar(text, task_id, "base")
            try:
                landed_bases[task_id] = require_commit(repo, require_full_sha(recorded_base))
            except IsolationError as error:
                raise BriefError(f"{task_id} landed task has invalid historical base: {error}") from error
            dependency_files[task_id] = set()
        validate_task_briefs(
            repo, head.stdout.strip(), f"{project_dir}/tasks",
            dependency_files=dependency_files, landed_bases=landed_bases,
        )
    except (BriefError, check_handoffs.HandoffError) as error:
        raise PipelineStateError(f"task brief validation failed: {error}") from error


def checkpoint_approval(
    repo: Path,
    kind: str,
    expected_head: str,
    project_dir: str = ".project",
    selected_milestone: Optional[str] = None,
) -> dict[str, object]:
    """Approve plan or roadmap metadata and commit it as one resumable transaction."""
    resolved = pipeline_state._repo_root(repo)
    if project_dir not in {".project", ".project/next"}:
        raise PipelineStateError("approval project-dir must be .project or .project/next")
    project = pipeline_state._track_root(resolved, ".project")
    journal_path = pipeline_state._git_path(resolved, CHECKPOINT_JOURNAL_NAME)
    request = _checkpoint_request_fields(
        kind,
        project_dir,
        selected_milestone,
        expected_head,
    )
    with pipeline_state._state_lock(project):
        if journal_path.exists() or journal_path.is_symlink():
            transaction = _approval_journal(resolved, pipeline_state._read_json(journal_path))
            mismatches = {
                key: {"expected": value, "actual": transaction.get(key)}
                for key, value in request.items()
                if transaction.get(key) != value
            }
            if mismatches:
                raise PipelineStateError(
                    "checkpoint journal does not match request: "
                    + json.dumps(mismatches, sort_keys=True)
                )
            return _resume_checkpoint_locked(resolved, project, journal_path, transaction)

        resolved_head = pipeline_state._run_git(
            resolved,
            "rev-parse",
            "--verify",
            f"{expected_head}^{{commit}}",
        ).stdout.strip()
        if resolved_head != expected_head:
            raise PipelineStateError("expected-head must be an exact full commit SHA")
        if pipeline_state._run_git(resolved, "rev-parse", "HEAD").stdout.strip() != expected_head:
            raise PipelineStateError("approval must start at expected-head")
        active_state, _, _ = pipeline_state.load_state(resolved)
        if active_state.branch is None or pipeline_state._current_branch(resolved) != active_state.branch:
            raise PipelineStateError("approval requires the active bound branch")
        outside = [path for path in pipeline_state._worktree_changes(resolved) if not path.startswith(".project/")]
        if outside:
            raise PipelineStateError(
                "checkpoint found changes outside .project: " + ", ".join(outside)
            )

        state, state_before, state_path = pipeline_state.load_state(resolved, project_dir)
        changes, event, subject, body = _approval_details(kind, state, selected_milestone)
        _validate_plan_briefs(resolved, kind, project_dir)
        if kind == "plan" and project_dir == ".project":
            pipeline_state._build_recovery().restore_unchanged_reviews(resolved)
        expected = {
            "phase": state.phase,
            "status": state.status,
            "milestone": state.milestone,
            "branch": state.branch,
            "archive": state.archive,
        }
        event_date = date.today().isoformat()
        _, _, state_after = pipeline_state._render_transition(
            state,
            state_before,
            expected,
            changes,
            event,
            project_dir,
            event_date,
            kind,
        )
        roadmap_path: Optional[Path] = None
        roadmap_before: Optional[str] = None
        roadmap_after: Optional[str] = None
        baseline_before = None
        if kind in {"roadmap", "roadmap-reslice"}:
            if project_dir != ".project":
                raise PipelineStateError("roadmap approval is legal only on the active track")
            assert selected_milestone is not None
            roadmap_path = project / "ROADMAP.md"
            roadmap_before = pipeline_state._read_real_file(roadmap_path, "ROADMAP.md")
            if kind == "roadmap-reslice":
                baseline_before = pipeline_state._read_real_file(project / "ROADMAP.before-reslice.md", "re-slice baseline")
            roadmap_after = _reslice_roadmap(
                baseline_before, roadmap_before, state, selected_milestone,
            ) if kind == "roadmap-reslice" else _activate_roadmap_milestone(
                roadmap_before,
                selected_milestone,
            )

        state_relative = state_path.relative_to(project).as_posix()
        mutable = {state_relative}
        if roadmap_path is not None:
            mutable.add(roadmap_path.relative_to(project).as_posix())
        if baseline_before is not None:
            mutable.add("ROADMAP.before-reslice.md")
        journal: dict[str, object] = {
            "schema": CHECKPOINT_SCHEMA,
            "repo": str(resolved),
            **request,
            "event": event,
            "event_date": event_date,
            "subject": subject,
            "body": body,
            "artifact_digest": _checkpoint_artifact_digest(project, mutable),
            "state_path": f".project/{state_relative}",
            "state_before": state_before,
            "state_after": state_after,
            "roadmap_path": ".project/ROADMAP.md" if roadmap_path is not None else None,
            "roadmap_before": roadmap_before,
            "roadmap_after": roadmap_after,
        }
        if baseline_before is not None:
            journal["baseline_before"] = baseline_before
        pipeline_state._write_json(journal_path, journal)
        return _resume_checkpoint_locked(resolved, project, journal_path, journal)


def _checkpoint_deferral_error(repo: Path, kind: str, patch: bool) -> Optional[str]:
    """Return why a deferred approval is illegal, or None when it is allowed."""
    if patch:
        return None if kind == "plan" else "--patch applies only to --kind plan"
    if pipeline_state._run_git(repo, "rev-parse", "--verify", "HEAD", check=False).returncode != 0:
        return None
    binding = repo / ".project" / "REPOSITORY.md"
    if binding.is_file() and not binding.is_symlink():
        kinds = [
            line.removeprefix("Kind:").strip()
            for line in binding.read_text(encoding="utf-8").splitlines()
            if line.startswith("Kind:")
        ]
        if kinds == ["new-github"]:
            return None
    return (
        "checkpoint deferral requires no Git HEAD, a Kind: new-github "
        "REPOSITORY.md, or --patch; run: pipeline_state.py approve "
        f"--kind {kind} --expected-head <full HEAD>"
    )


def defer_approval(
    repo: Path,
    kind: str,
    project_dir: str = ".project",
    selected_milestone: Optional[str] = None,
    patch: bool = False,
) -> dict[str, object]:
    """Approve plan or roadmap metadata without a checkpoint commit.

    Legal only before Git exists, during a new-repository transaction, or for
    a patch plan; the next build transition commit owns the artifacts.
    """
    resolved = pipeline_state._repo_root(repo)
    if project_dir not in {".project", ".project/next"}:
        raise PipelineStateError("approval project-dir must be .project or .project/next")
    error = _checkpoint_deferral_error(resolved, kind, patch)
    if error:
        raise PipelineStateError(error)
    project = pipeline_state._track_root(resolved, ".project")
    with pipeline_state._state_lock(project):
        state, state_before, state_path = pipeline_state.load_state(resolved, project_dir)
        changes, event, _, _ = _approval_details(kind, state, selected_milestone)
        if project_dir == ".project":
            recovery = pipeline_state._build_recovery().context(resolved, state_before)
            if recovery and recovery["active"]:
                raise PipelineStateError("build recovery requires a plan checkpoint")
        _validate_plan_briefs(resolved, kind, project_dir)
        if patch:
            event = "patch plan approved"
        expected = {
            "phase": state.phase,
            "status": state.status,
            "milestone": state.milestone,
            "branch": state.branch,
            "archive": state.archive,
        }
        _, after, state_after = pipeline_state._render_transition(
            state,
            state_before,
            expected,
            changes,
            event,
            project_dir,
            approval_kind=kind,
        )
        baseline = None
        if kind in {"roadmap", "roadmap-reslice"}:
            if project_dir != ".project":
                raise PipelineStateError("roadmap approval is legal only on the active track")
            assert selected_milestone is not None
            roadmap_path = project / "ROADMAP.md"
            roadmap_before = pipeline_state._read_real_file(roadmap_path, "ROADMAP.md")
            if kind == "roadmap-reslice":
                baseline = project / "ROADMAP.before-reslice.md"
                roadmap_after = _reslice_roadmap(
                    pipeline_state._read_real_file(baseline, "re-slice baseline"),
                    roadmap_before, state, selected_milestone,
                )
            else:
                roadmap_after = _activate_roadmap_milestone(roadmap_before, selected_milestone)
            pipeline_state._atomic_write(roadmap_path, roadmap_after)
        pipeline_state._atomic_write(state_path, state_after)
        if baseline is not None:
            baseline.unlink()
    return {
        "schema": CHECKPOINT_SCHEMA,
        "status": "approved",
        "kind": kind,
        "project_dir": project_dir,
        "commit": None,
        "deferred": True,
        "state": after.json(),
    }


def resume_checkpoint(repo: Path) -> dict[str, object]:
    """Resume the single journaled plan or roadmap approval transaction."""
    resolved = pipeline_state._repo_root(repo)
    project = pipeline_state._track_root(resolved, ".project")
    journal_path = pipeline_state._git_path(resolved, CHECKPOINT_JOURNAL_NAME)
    with pipeline_state._state_lock(project):
        if not journal_path.exists() and not journal_path.is_symlink():
            raise PipelineStateError("no approval checkpoint journal exists")
        return _resume_checkpoint_locked(
            resolved,
            project,
            journal_path,
            pipeline_state._read_json(journal_path),
        )


def _task_files(text: str, label: str) -> tuple[str, list[str]]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise PipelineStateError(f"{label} is missing YAML frontmatter")
    task_id = ""
    files: list[str] = []
    closing: Optional[int] = None
    for index, line in enumerate(lines[1:], start=1):
        if line == "---":
            closing = index
            break
        id_match = re.fullmatch(r"id:\s*([^#\s]+)(?:\s+#.*)?", line)
        if id_match:
            if task_id:
                raise PipelineStateError(f"{label} repeats task id")
            task_id = id_match.group(1).strip("\"'")
        files_match = re.fullmatch(r"files:\s*(.*?)(?:\s+#.*)?", line)
        if files_match is None:
            continue
        inline = re.fullmatch(r"\[(.*)\]", files_match.group(1).strip())
        if inline:
            files = [
                value.strip().strip("\"'")
                for value in inline.group(1).split(",")
                if value.strip()
            ]
            continue
        cursor = index + 1
        while cursor < len(lines):
            item = re.match(r"^\s+-\s+(.+?)(?:\s+#.*)?$", lines[cursor])
            if item is None:
                break
            files.append(item.group(1).strip().strip("\"'"))
            cursor += 1
    if closing is None:
        raise PipelineStateError(f"{label} frontmatter is not closed")
    if not TASK_ID_RE.fullmatch(task_id):
        raise PipelineStateError(f"{label} has invalid task id: {task_id}")
    if not files:
        raise PipelineStateError(f"{label} has no declared files")
    return task_id, files


def _approval_checkpoint(
    repo: Path,
    state: PipelineState,
    revision: str = "HEAD",
) -> Optional[str]:
    parents = pipeline_state._run_git(repo, "show", "-s", "--format=%P", revision).stdout.split()
    if len(parents) != 2:
        return None
    base, ship = parents
    if pipeline_state._run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        base,
        ship,
        check=False,
    ).returncode != 0:
        return None
    commits = pipeline_state._run_git(
        repo,
        "rev-list",
        "--first-parent",
        ship,
        f"^{base}",
    ).stdout.splitlines()
    candidates = []
    for commit in commits:
        raw = pipeline_state._run_git(repo, "cat-file", "commit", commit).stdout
        if "\n\n" not in raw:
            continue
        message = raw.split("\n\n", 1)[1]
        expected_message = pipeline_state._commit_message(
            PLAN_APPROVAL_SUBJECT,
            {
                "Why": "approved plan checkpoint",
                "Milestone": state.milestone or "none",
            },
        )
        if message != expected_message:
            continue
        shown = pipeline_state._run_git(
            repo,
            "show",
            f"{commit}:.project/next/STATE.md",
            check=False,
        )
        if shown.returncode != 0:
            continue
        try:
            candidate = pipeline_state._state_from_text(shown.stdout, "checkpoint next/STATE.md")
        except PipelineStateError:
            continue
        if (
            candidate.project == state.project
            and candidate.milestone == state.milestone
            and candidate.phase == "plan"
            and candidate.status == "done"
            and candidate.branch is None
            and candidate.archive is None
        ):
            pipeline_state._validate_state_context(
                candidate,
                ".project/next",
                "checkpoint next/STATE.md",
            )
            _validate_approval_track(repo, commit)
            candidates.append(commit)
    if len(candidates) > 1:
        raise PipelineStateError(
            "current milestone attempt has multiple matching plan approval checkpoints"
        )
    return candidates[0] if candidates else None


def _validate_approval_track(repo: Path, checkpoint: str) -> None:
    prefix = ".project/next"
    entries = [
        line
        for line in pipeline_state._run_git(
            repo,
            "ls-tree",
            "-r",
            checkpoint,
            "--",
            prefix,
        ).stdout.splitlines()
        if line
    ]
    paths = []
    for entry in entries:
        metadata, path = entry.split("\t", 1)
        mode, object_type, _ = metadata.split()
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise PipelineStateError(
                f"approval checkpoint has unsafe lookahead artifact: {path}"
            )
        relative = PurePosixPath(path).relative_to(prefix)
        if not relative.parts or (
            relative.as_posix() != "STATE.md"
            and relative.parts[0] not in PROMOTION_TRACKS
        ):
            raise PipelineStateError(
                f"approval checkpoint has unowned lookahead artifact: {path}"
            )
        paths.append(path)
    required = {
        ".project/next/STATE.md",
        ".project/next/plan/PLAN.md",
    }
    if not required.issubset(paths):
        raise PipelineStateError("approval checkpoint has an incomplete lookahead track")
    tasks = _approved_task_contracts(repo, checkpoint)
    changed = {
        value
        for value in pipeline_state._run_git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            checkpoint,
        ).stdout.splitlines()
        if value
    }
    required_changes = required | {contract.path for contract in tasks.values()}
    if not required_changes.issubset(changed):
        raise PipelineStateError(
            "plan approval commit did not checkpoint its complete plan and task set"
        )


def _safe_declared_paths(task_id: str, paths: Sequence[str]) -> tuple[str, ...]:
    safe: list[str] = []
    for value in paths:
        relative = PurePosixPath(value)
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise PipelineStateError(f"{task_id} declares unsafe path: {value}")
        safe.append(relative.as_posix())
    return tuple(safe)


def _git_text_at(repo: Path, commit: str, path: str) -> Optional[str]:
    shown = pipeline_state._run_git(repo, "show", f"{commit}:{path}", check=False)
    return shown.stdout if shown.returncode == 0 else None


def _approved_task_contracts(
    repo: Path,
    checkpoint: str,
) -> dict[str, ApprovedTaskContract]:
    prefix = PurePosixPath(".project/next/tasks")
    paths = [
        value
        for value in pipeline_state._run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            checkpoint,
            "--",
            prefix.as_posix(),
        ).stdout.split("\0")
        if value
    ]
    contracts: dict[str, ApprovedTaskContract] = {}
    for value in paths:
        relative = PurePosixPath(value)
        match = TASK_FILE_RE.fullmatch(relative.name)
        if relative.parent != prefix or match is None:
            raise PipelineStateError(
                f"approval checkpoint has noncanonical task artifact: {value}"
            )
        text = _git_text_at(repo, checkpoint, value)
        if text is None:
            raise PipelineStateError(f"approval checkpoint lost task artifact: {value}")
        task_id, declared = _task_files(text, value)
        if task_id != match.group(1):
            raise PipelineStateError(f"approval checkpoint task id does not match {value}")
        if task_id in contracts:
            raise PipelineStateError(f"approval checkpoint repeats task id: {task_id}")
        contracts[task_id] = ApprovedTaskContract(
            value,
            text,
            _safe_declared_paths(task_id, declared),
        )
    if not contracts:
        raise PipelineStateError("approval checkpoint has no task contracts")
    return contracts


def _task_contracts_at(
    repo: Path,
    revision: str,
    prefix: str = ".project/next/tasks",
) -> dict[str, tuple[str, str]]:
    root = PurePosixPath(prefix)
    paths = [
        value
        for value in pipeline_state._run_git(
            repo,
            "ls-tree",
            "-r",
            "--name-only",
            "-z",
            revision,
            "--",
            prefix,
        ).stdout.split("\0")
        if value
    ]
    contracts: dict[str, tuple[str, str]] = {}
    for value in paths:
        path = PurePosixPath(value)
        match = TASK_FILE_RE.fullmatch(path.name)
        if path.parent != root or match is None:
            raise PipelineStateError(f"lookahead has noncanonical task artifact: {value}")
        task_id = match.group(1)
        if task_id in contracts:
            raise PipelineStateError(f"lookahead tasks repeat id: {task_id}")
        text = _git_text_at(repo, revision, value)
        if text is None:
            raise PipelineStateError(f"lookahead lost task artifact: {value}")
        contracts[task_id] = (
            value,
            text,
        )
    return contracts


def _classify_plan_drift(
    repo: Path,
    state: PipelineState,
    revision: str,
    landing: Optional[str] = None,
) -> dict[str, object]:
    """Compare the approved plan at the landing's checkpoint with ``revision``."""
    if state.phase != "plan" or state.status != "done":
        return {"class": "not-applicable", "reason": "lookahead track is not plan/done"}
    assert state.milestone is not None
    checkpoint = _approval_checkpoint(repo, state, landing or revision)
    if checkpoint is None:
        return {
            "class": "unverifiable",
            "checkpoint": None,
            "task_ids": [],
            "changed_paths": [],
            "reason": "matching plan approval checkpoint was not found",
        }
    changed = [
        item
        for item in pipeline_state._run_git(
            repo,
            "diff",
            "--name-only",
            "-z",
            checkpoint,
            revision,
        ).stdout.split("\0")
        if item
    ]
    approved_plan_path = ".project/next/plan/PLAN.md"
    approved_plan = _git_text_at(repo, checkpoint, approved_plan_path)
    if approved_plan is None:
        return {
            "class": "unverifiable",
            "checkpoint": checkpoint,
            "task_ids": [],
            "changed_paths": [],
            "contract_paths": [],
            "reason": "plan approval checkpoint has no PLAN.md",
        }
    approved = _approved_task_contracts(repo, checkpoint)
    current = _task_contracts_at(repo, revision)

    contract_paths: set[str] = set()
    flagged_ids: set[str] = set()
    current_plan = _git_text_at(repo, revision, approved_plan_path)
    if current_plan != approved_plan:
        contract_paths.add(approved_plan_path)
    for task_id in set(approved) | set(current):
        approved_contract = approved.get(task_id)
        current_contract = current.get(task_id)
        if (
            approved_contract is None
            or current_contract is None
            or approved_contract.path != current_contract[0]
            or approved_contract.text != current_contract[1]
        ):
            flagged_ids.add(task_id)
            if approved_contract is not None:
                contract_paths.add(approved_contract.path)
            if current_contract is not None:
                contract_paths.add(current_contract[0])

    product_paths: set[str] = set()
    for task_id, contract in approved.items():
        matches = sorted(
            changed_path
            for changed_path in changed
            if any(
                changed_path == path
                or changed_path.startswith(f"{path.rstrip('/')}/")
                for path in contract.files
            )
        )
        if matches:
            flagged_ids.add(task_id)
            product_paths.update(matches)

    changed_paths = sorted(contract_paths | product_paths)
    changed_contract = bool(contract_paths)
    changed_product = bool(product_paths)
    reasons = []
    if changed_contract:
        reasons.append("plan or task contracts changed after approval")
    if changed_product:
        reasons.append("approved declared task paths changed after approval")
    return {
        "class": "changed" if changed_paths else "clean",
        "checkpoint": checkpoint,
        "task_ids": sorted(flagged_ids),
        "changed_paths": changed_paths,
        "contract_paths": sorted(contract_paths),
        "reason": "; ".join(reasons) if reasons else "approval contracts and declared paths are unchanged",
    }
