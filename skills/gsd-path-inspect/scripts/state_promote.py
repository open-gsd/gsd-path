#!/usr/bin/env python3
# gsd-path project runtime
"""Promote the lookahead track as a resumable transaction for pipeline_state."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional


if __package__:  # imported as scripts.state_promote
    from . import pipeline_state, state_checkpoint
    from .pipeline_state import (
        NULL,
        PROMOTION_RESIDUAL,
        PROMOTION_SCHEMA,
        PROMOTION_TRACKS,
        SLUG_RE,
        PipelineState,
        PipelineStateError,
    )
else:  # standalone script or sibling import
    import pipeline_state
    import state_checkpoint
    from pipeline_state import (
        NULL,
        PROMOTION_RESIDUAL,
        PROMOTION_SCHEMA,
        PROMOTION_TRACKS,
        SLUG_RE,
        PipelineState,
        PipelineStateError,
    )


def _render_roadmap(
    text: str,
    previous_milestone: str,
    milestone: str,
    branch: str,
    integrate: str,
) -> str:
    sections = pipeline_state._roadmap_sections(text)
    if previous_milestone not in sections:
        raise PipelineStateError(f"ROADMAP.md is missing previous milestone: {previous_milestone}")
    if milestone not in sections:
        raise PipelineStateError(f"ROADMAP.md is missing promoted milestone: {milestone}")
    branch_number = pipeline_state._bound_branch_number(branch)
    if branch_number is None:
        raise PipelineStateError(f"invalid promoted branch: {branch}")
    promoted_id, new_start, new_end = sections[milestone]
    if branch_number != int(promoted_id.removeprefix("M")):
        raise PipelineStateError(f"branch {branch} does not match roadmap milestone {promoted_id}")
    _, old_start, old_end = sections[previous_milestone]
    lines = text.splitlines(keepends=True)
    pipeline_state._replace_roadmap_field(lines, old_start, old_end, "Status", {"shipped"}, "shipped")
    pipeline_state._replace_roadmap_field(lines, old_start, old_end, "Integrated", {NULL}, integrate)
    pipeline_state._replace_roadmap_field(lines, new_start, new_end, "Status", {"pending"}, "active")
    return "".join(lines)


def _promotion_event(
    drift: Mapping[str, object],
    branch: str,
    landing: str,
    base: Optional[str] = None,
) -> str:
    prefix = f"lookahead promoted on {branch} from integrate {landing}"
    if base is not None and base != landing:
        prefix = f"{prefix} at main base {base}"
    drift_class = drift["class"]
    if drift_class == "changed":
        task_ids = drift.get("task_ids")
        if isinstance(task_ids, list) and task_ids:
            return f"{prefix}; plan drift flagged tasks {', '.join(task_ids)}"
        return f"{prefix}; plan contract changed after approval"
    if drift_class == "unverifiable":
        return f"{prefix}; plan drift unverifiable because approval checkpoint is missing"
    return prefix


def _promotion_state(
    active_text: str,
    next_state: PipelineState,
    branch: str,
    landing: str,
    drift: Mapping[str, object],
    event_date: Optional[str] = None,
    base: Optional[str] = None,
) -> str:
    status = next_state.status
    if next_state.phase == "plan" and next_state.status == "done" and drift["class"] != "clean":
        status = "active"
    rendered = pipeline_state._set_frontmatter(
        active_text,
        {
            "milestone": next_state.milestone or NULL,
            "phase": next_state.phase,
            "status": status,
            "branch": branch,
            "archive": NULL,
            "integration_default": next_state.integration_default,
            "integration": next_state.integration,
            "integration_source": next_state.integration_source,
        },
    )
    rendered = pipeline_state._append_event(
        rendered,
        next_state.phase,
        _promotion_event(drift, branch, landing, base),
        event_date,
    )
    pipeline_state._state_from_text(rendered)
    return rendered


def _head_with_exact_message(
    repo: Path,
    subject: str,
    body_fields: Mapping[str, str],
) -> Optional[str]:
    head = pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    raw = pipeline_state._run_git(repo, "cat-file", "commit", head).stdout
    try:
        message = raw.split("\n\n", 1)[1]
    except IndexError as error:
        raise PipelineStateError(f"commit {head} has no message body") from error
    return head if message == pipeline_state._commit_message(subject, body_fields) else None


def _tree_entries(
    repo: Path,
    revision: str,
    prefix: str,
) -> dict[str, tuple[str, str]]:
    records = pipeline_state._run_git(
        repo,
        "ls-tree",
        "-r",
        "-z",
        revision,
        "--",
        prefix,
    ).stdout.split("\0")
    entries: dict[str, tuple[str, str]] = {}
    for record in records:
        if not record:
            continue
        metadata, separator, path = record.partition("\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise PipelineStateError(f"could not parse Git tree entry: {record}")
        mode, object_type, object_id = fields
        if object_type != "blob" or mode not in {"100644", "100755"}:
            raise PipelineStateError(f"promotion requires a regular tracked file: {path}")
        entries[path] = (mode, object_id)
    return entries


def _promotion_tree_mapping(
    repo: Path,
    parent: str,
    head: str,
) -> set[str]:
    next_prefix = ".project/next"
    next_entries = _tree_entries(repo, parent, next_prefix)
    state_path = f"{next_prefix}/STATE.md"
    if state_path not in next_entries:
        raise PipelineStateError("promotion parent has no lookahead STATE.md")

    destinations: dict[str, tuple[str, str]] = {}
    used_tracks: set[str] = set()
    for source, entry in next_entries.items():
        if source == state_path:
            continue
        parts = PurePosixPath(source).parts
        if len(parts) < 4 or parts[:2] != (".project", "next"):
            raise PipelineStateError(f"promotion parent has invalid lookahead path: {source}")
        track = parts[2]
        if track not in PROMOTION_TRACKS:
            raise PipelineStateError(f"promotion parent has unowned lookahead path: {source}")
        destination = PurePosixPath(".project", *parts[2:]).as_posix()
        destinations[destination] = entry
        used_tracks.add(track)
    if not destinations:
        raise PipelineStateError("promotion parent has no promotable artifacts")

    if _tree_entries(repo, head, next_prefix):
        raise PipelineStateError("completed promotion retained tracked lookahead artifacts")
    for track in used_tracks:
        prefix = f".project/{track}"
        if _tree_entries(repo, parent, prefix):
            raise PipelineStateError(f"promotion parent already had destination track: {track}")
        actual = _tree_entries(repo, head, prefix)
        expected = {
            path: entry
            for path, entry in destinations.items()
            if path == prefix or path.startswith(f"{prefix}/")
        }
        if actual != expected:
            raise PipelineStateError(f"completed promotion did not preserve track: {track}")

    changed = {
        path
        for path in pipeline_state._run_git(
            repo,
            "diff",
            "--name-only",
            "--no-renames",
            "-z",
            parent,
            head,
        ).stdout.split("\0")
        if path
    }
    expected_changes = {
        ".project/STATE.md",
        ".project/ROADMAP.md",
        *next_entries,
        *destinations,
    }
    if changed != expected_changes:
        missing = sorted(expected_changes - changed)
        extra = sorted(changed - expected_changes)
        raise PipelineStateError(
            "completed promotion has wrong path set: "
            f"missing={missing}, extra={extra}"
        )
    return expected_changes


def _completed_promotion(
    repo: Path,
    project: Path,
    milestone: str,
    branch: str,
    base: str,
    landing: str,
) -> Optional[dict[str, object]]:
    next_root = project / "next"
    if next_root.exists() or next_root.is_symlink():
        return None
    state, _, _ = pipeline_state.load_state(repo)
    if state.milestone != milestone or state.branch != branch or state.archive is not None:
        return None
    if pipeline_state._current_branch(repo) != branch:
        raise PipelineStateError("completed promotion is not on its recorded branch")
    if pipeline_state._worktree_changes(repo):
        raise PipelineStateError("completed promotion worktree is not clean")

    head = pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    parents = pipeline_state._run_git(repo, "show", "-s", "--format=%P", head).stdout.split()
    if parents != [base]:
        raise PipelineStateError(
            "completed promotion must be current HEAD with base as its single parent"
        )
    subject = f"router: promote lookahead milestone {milestone}"
    fields = {
        "Why": "promote lookahead track",
        "Milestone": milestone,
        "Integrate": landing,
    }
    if base != landing:
        fields["Base"] = base
    if _head_with_exact_message(repo, subject, fields) != head:
        raise PipelineStateError("completed promotion has the wrong commit message")

    active_text = state_checkpoint._git_text_at(repo, base, ".project/STATE.md")
    next_text = state_checkpoint._git_text_at(repo, base, ".project/next/STATE.md")
    roadmap_text = state_checkpoint._git_text_at(repo, base, ".project/ROADMAP.md")
    if active_text is None or next_text is None or roadmap_text is None:
        raise PipelineStateError("promotion parent is missing required metadata")
    active_state = pipeline_state._state_from_text(active_text, "promotion parent STATE.md")
    next_state = pipeline_state._state_from_text(next_text, "promotion parent next/STATE.md")
    pipeline_state._validate_state_context(next_state, ".project/next", "promotion parent next/STATE.md")
    if active_state.phase != "shipped" or active_state.status != "done":
        raise PipelineStateError("promotion parent STATE is not shipped/done")
    if active_state.milestone is None:
        raise PipelineStateError("promotion parent STATE has no milestone")
    if next_state.project != active_state.project:
        raise PipelineStateError("promotion parent lookahead belongs to another project")
    if next_state.milestone != milestone:
        raise PipelineStateError("promotion parent lookahead milestone does not match request")
    if next_state.phase not in {"define", "research", "decide", "plan"}:
        raise PipelineStateError(
            f"promotion parent lookahead cannot be in phase {next_state.phase}"
        )

    _promotion_tree_mapping(repo, base, head)
    drift = state_checkpoint._classify_plan_drift(repo, next_state, base, landing)
    expected_roadmap = _render_roadmap(
        roadmap_text,
        active_state.milestone,
        milestone,
        branch,
        landing,
    )
    current_roadmap = state_checkpoint._git_text_at(repo, head, ".project/ROADMAP.md")
    if current_roadmap != expected_roadmap:
        raise PipelineStateError("completed promotion has invalid ROADMAP.md")

    current_state = state_checkpoint._git_text_at(repo, head, ".project/STATE.md")
    if current_state is None:
        raise PipelineStateError("completed promotion has no STATE.md")
    event = re.escape(_promotion_event(drift, branch, landing, base))
    suffix = re.search(
        rf"(?m)^- (\d{{4}}-\d{{2}}-\d{{2}}) — {re.escape(next_state.phase)} — {event}\n\Z",
        current_state,
    )
    if suffix is None:
        raise PipelineStateError("completed promotion has invalid STATE log event")
    expected_state = _promotion_state(
        active_text,
        next_state,
        branch,
        landing,
        drift,
        suffix.group(1),
        base,
    )
    if current_state != expected_state:
        raise PipelineStateError("completed promotion has invalid STATE.md")
    return {
        "schema": PROMOTION_SCHEMA,
        "status": "already-complete",
        "milestone": milestone,
        "branch": branch,
        "integrate": landing,
        "landing": landing,
        "base": base,
        "commit": head,
        "drift": drift,
    }


def _prepare_promotion(
    repo: Path,
    project: Path,
    milestone: str,
    branch: str,
    base: str,
    landing: str,
) -> dict[str, object]:
    if pipeline_state._bound_branch_number(branch) is None:
        raise PipelineStateError(f"invalid promoted branch: {branch}")
    current = pipeline_state._current_branch(repo)
    if current != branch:
        raise PipelineStateError(
            f"current branch {current or '<detached>'} != promoted branch {branch}"
        )
    resolved_base = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{base}^{{commit}}",
    ).stdout.strip()
    if base != resolved_base:
        raise PipelineStateError("base must be an exact full commit SHA")
    resolved_landing = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{landing}^{{commit}}",
    ).stdout.strip()
    if landing != resolved_landing:
        raise PipelineStateError("landing must be an exact full commit SHA")
    head = pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    if head != base:
        raise PipelineStateError(f"promotion must start at base SHA: {head} != {base}")
    remote = pipeline_state._run_git(repo, "rev-parse", "--verify", "origin/main^{commit}").stdout.strip()
    if remote != base:
        raise PipelineStateError(
            f"base SHA is not current origin/main: {base} != {remote}"
        )
    if not pipeline_state._is_ancestor(repo, landing, base):
        raise PipelineStateError("landing is not an ancestor of the current main base")
    if pipeline_state._run_git(repo, "status", "--porcelain", "--untracked-files=all").stdout:
        raise PipelineStateError("promotion must start from a clean worktree")

    active_state, active_text, _ = pipeline_state.load_state(repo)
    if active_state.phase != "shipped" or active_state.status != "done":
        raise PipelineStateError("promotion requires active STATE shipped/done")
    if active_state.milestone is None:
        raise PipelineStateError("active STATE does not name the shipped milestone")
    archive_name = PurePosixPath(active_state.archive or "").name
    tag_ref = f"refs/tags/milestone/{archive_name}"
    published_tag_ref = f"refs/remotes/origin/tags/milestone/{archive_name}"
    tag_type = pipeline_state._run_git(repo, "cat-file", "-t", tag_ref, check=False)
    if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
        raise PipelineStateError("shipped milestone tag is missing or not annotated")
    published_tag_type = pipeline_state._run_git(
        repo,
        "cat-file",
        "-t",
        published_tag_ref,
        check=False,
    )
    if published_tag_type.returncode != 0 or published_tag_type.stdout.strip() != "tag":
        raise PipelineStateError("published milestone tag is missing or not annotated")
    tag_object = pipeline_state._run_git(repo, "rev-parse", "--verify", tag_ref).stdout.strip()
    published_tag_object = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        published_tag_ref,
    ).stdout.strip()
    if tag_object != published_tag_object:
        raise PipelineStateError("local milestone tag does not match published milestone tag")
    tag_landing = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{tag_ref}^{{commit}}",
    ).stdout.strip()
    if tag_landing != landing:
        raise PipelineStateError("milestone tag does not point at landing")
    published_tag_landing = pipeline_state._run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{published_tag_ref}^{{commit}}",
    ).stdout.strip()
    if published_tag_landing != landing:
        raise PipelineStateError("published milestone tag does not point at landing")
    if active_state.integration == "pull-request":
        remote_tag_ref = f"refs/tags/milestone/{archive_name}"
        live_tag_object, live_tag_landing = pipeline_state._live_annotated_tag(
            repo,
            remote_tag_ref,
        )
        if live_tag_object != published_tag_object:
            raise PipelineStateError(
                "published milestone tag does not match the live origin tag"
            )
        if live_tag_landing != landing:
            raise PipelineStateError(
                "live origin milestone tag does not point at landing"
            )
    next_root = project / "next"
    next_state, next_text, _ = pipeline_state.load_state(repo, ".project/next")
    if next_state.project != active_state.project:
        raise PipelineStateError(
            "lookahead STATE project does not match active STATE project"
        )
    if next_state.integration_default != active_state.integration_default:
        raise PipelineStateError(
            "lookahead integration_default does not match the active project"
        )
    if next_state.milestone != milestone:
        raise PipelineStateError(
            f"requested milestone {milestone} != next STATE milestone {next_state.milestone}"
        )
    if next_state.branch is not None or next_state.archive is not None:
        raise PipelineStateError("lookahead STATE branch and archive must be null")

    tracks: dict[str, str] = {}
    for name in PROMOTION_TRACKS:
        source = next_root / name
        destination = project / name
        if source.exists() or source.is_symlink():
            if destination.exists() or destination.is_symlink():
                raise PipelineStateError(f"promotion destination already exists: {destination}")
            tracks[name] = state_checkpoint._tree_digest(source)
    if not tracks:
        raise PipelineStateError("lookahead track has no promotable artifacts")
    drift = state_checkpoint._classify_plan_drift(repo, next_state, base, landing)
    roadmap_path = project / "ROADMAP.md"
    roadmap_text = pipeline_state._read_real_file(roadmap_path, "ROADMAP.md")
    target_state = _promotion_state(
        active_text, next_state, branch, landing, drift, base=base
    )
    target_roadmap = _render_roadmap(
        roadmap_text,
        active_state.milestone,
        milestone,
        branch,
        landing,
    )
    return {
        "schema": PROMOTION_SCHEMA,
        "repo": str(repo),
        "milestone": milestone,
        "previous_milestone": active_state.milestone,
        "branch": branch,
        "integrate": landing,
        "landing": landing,
        "base": base,
        "tracks": tracks,
        "residual_sha256": state_checkpoint._tree_digest(next_root, tuple(tracks)),
        "next_state_sha256": state_checkpoint._sha256(next_text),
        "active_state_sha256": state_checkpoint._sha256(active_text),
        "roadmap_sha256": state_checkpoint._sha256(roadmap_text),
        "target_state": target_state,
        "target_roadmap": target_roadmap,
        "drift": drift,
        "stage": "prepared",
    }


def _require_journal_request(
    journal: Mapping[str, object],
    repo: Path,
    milestone: str,
    branch: str,
    base: str,
    landing: str,
) -> None:
    expected = {
        "schema": PROMOTION_SCHEMA,
        "repo": str(repo),
        "milestone": milestone,
        "branch": branch,
        "integrate": landing,
    }
    mismatches = {
        key: {"expected": value, "actual": journal.get(key)}
        for key, value in expected.items()
        if journal.get(key) != value
    }
    if mismatches:
        raise PipelineStateError(
            f"promotion journal does not match request: {json.dumps(mismatches, sort_keys=True)}"
        )
    journal_base = journal.get("base", journal.get("integrate"))
    if journal_base != base:
        raise PipelineStateError("promotion journal does not match the requested base")


def _resume_track_moves(project: Path, journal: dict[str, object], path: Path) -> None:
    tracks = journal.get("tracks")
    if not isinstance(tracks, dict):
        raise PipelineStateError("promotion journal has invalid tracks")
    next_root = project / "next"
    for name, expected_digest in tracks.items():
        if name not in PROMOTION_TRACKS or not isinstance(expected_digest, str):
            raise PipelineStateError("promotion journal has invalid track entry")
        source = next_root / name
        destination = project / name
        source_exists = source.exists() or source.is_symlink()
        destination_exists = destination.exists() or destination.is_symlink()
        if source_exists and destination_exists:
            raise PipelineStateError(f"promotion has both source and destination: {name}")
        if not source_exists and not destination_exists:
            raise PipelineStateError(f"promotion lost both source and destination: {name}")
        candidate = source if source_exists else destination
        if state_checkpoint._tree_digest(candidate) != expected_digest:
            raise PipelineStateError(f"promotion track drifted: {name}")
        if source_exists:
            source.rename(destination)
            journal["stage"] = f"moved:{name}"
            pipeline_state._write_json(path, journal)


def _resume_metadata(project: Path, journal: dict[str, object], path: Path) -> None:
    targets = (
        (project / "STATE.md", "active_state_sha256", "target_state"),
        (project / "ROADMAP.md", "roadmap_sha256", "target_roadmap"),
    )
    for target, original_key, target_key in targets:
        current = pipeline_state._read_real_file(target, target.name)
        expected_original = journal.get(original_key)
        desired = journal.get(target_key)
        if not isinstance(expected_original, str) or not isinstance(desired, str):
            raise PipelineStateError("promotion journal has invalid metadata")
        if current == desired:
            continue
        if state_checkpoint._sha256(current) != expected_original:
            raise PipelineStateError(f"promotion metadata drifted: {target}")
        pipeline_state._atomic_write(target, desired)
        journal["stage"] = f"updated:{target.name}"
        pipeline_state._write_json(path, journal)


def _resume_next_removal(
    project: Path,
    journal: dict[str, object],
    journal_path: Path,
    residual: Path,
) -> None:
    next_root = project / "next"
    if next_root.exists() or next_root.is_symlink():
        if residual.exists() or residual.is_symlink():
            raise PipelineStateError("promotion has both next track and residual staging")
        next_text = pipeline_state._read_real_file(next_root / "STATE.md", "next/STATE.md")
        if state_checkpoint._sha256(next_text) != journal.get("next_state_sha256"):
            raise PipelineStateError("lookahead STATE drifted during promotion")
        if state_checkpoint._tree_digest(next_root) != journal.get("residual_sha256"):
            raise PipelineStateError("lookahead residual drifted during promotion")
        next_root.rename(residual)
        journal["stage"] = "next-staged"
        pipeline_state._write_json(journal_path, journal)
    elif not residual.exists():
        # Cleanup removes the residual only after recording the commit.
        if journal.get("stage") == "committed" and isinstance(journal.get("commit"), str):
            return
        raise PipelineStateError("promotion lost next track and residual staging")
    if residual.is_symlink() or not residual.is_dir():
        raise PipelineStateError(f"promotion residual must be a real directory: {residual}")
    if state_checkpoint._tree_digest(residual) != journal.get("residual_sha256"):
        raise PipelineStateError("staged lookahead residual drifted during promotion")


def _commit_promotion(
    repo: Path,
    milestone: str,
    landing: str,
    base: str,
    journal: dict[str, object],
    journal_path: Path,
    residual: Path,
) -> str:
    subject = f"router: promote lookahead milestone {milestone}"
    fields = {
        "Why": "promote lookahead track",
        "Milestone": milestone,
        "Integrate": landing,
    }
    if base != landing:
        fields["Base"] = base
    existing = _head_with_exact_message(repo, subject, fields)
    residual_name = residual.relative_to(repo).as_posix()

    def is_residual(path: str) -> bool:
        return path == residual_name or path.startswith(f"{residual_name}/")

    if existing is not None:
        if pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip() != existing:
            raise PipelineStateError("promotion commit exists but is not current HEAD")
        if [path for path in pipeline_state._worktree_changes(repo) if not is_residual(path)]:
            raise PipelineStateError("promotion commit exists with worktree drift")
        return existing
    outside = [
        path
        for path in pipeline_state._worktree_changes(repo)
        if not path.startswith(".project/") and not is_residual(path)
    ]
    if outside:
        raise PipelineStateError(f"promotion found changes outside .project: {outside}")
    pipeline_state._run_git(repo, "add", "-A", "--", ".project")
    staged = [
        path
        for path in pipeline_state._run_git(
            repo,
            "diff",
            "--cached",
            "--name-only",
            "-z",
        ).stdout.split("\0")
        if path
    ]
    if not staged or any(not name.startswith(".project/") for name in staged):
        raise PipelineStateError("promotion commit must contain only .project changes")
    body = "\n".join(f"{key}: {value}" for key, value in fields.items())
    pipeline_state._run_git(repo, "commit", "-m", subject, "-m", body)
    commit = pipeline_state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    journal["stage"] = "committed"
    journal["commit"] = commit
    pipeline_state._write_json(journal_path, journal)
    return commit


def promote_next(
    repo: Path,
    milestone: str,
    branch: str,
    base: str,
    landing: Optional[str] = None,
) -> dict[str, object]:
    """Promote `.project/next` through a journaled, idempotent transaction."""
    resolved = pipeline_state._repo_root(repo)
    if not SLUG_RE.fullmatch(milestone):
        raise PipelineStateError(f"invalid promoted milestone: {milestone}")
    if pipeline_state._bound_branch_number(branch) is None:
        raise PipelineStateError(f"invalid promoted branch: {branch}")
    landing = landing or base
    resolved_base = pipeline_state._run_git(
        resolved,
        "rev-parse",
        "--verify",
        f"{base}^{{commit}}",
    ).stdout.strip()
    if base != resolved_base:
        raise PipelineStateError("base must be an exact full commit SHA")
    project = pipeline_state._track_root(resolved, ".project")
    journal_path = pipeline_state._git_path(resolved, "gsd-path-promote-next.json")
    residual = resolved / PROMOTION_RESIDUAL
    with pipeline_state._state_lock(project):
        if not journal_path.exists():
            completed = _completed_promotion(
                resolved,
                project,
                milestone,
                branch,
                base,
                landing,
            )
            if completed is not None:
                return completed
            if residual.exists() or residual.is_symlink():
                raise PipelineStateError(f"orphaned promotion residual exists: {residual}")
            journal = _prepare_promotion(
                resolved,
                project,
                milestone,
                branch,
                base,
                landing,
            )
            pipeline_state._write_json(journal_path, journal)
        else:
            journal = pipeline_state._read_json(journal_path)
        _require_journal_request(journal, resolved, milestone, branch, base, landing)
        _resume_track_moves(project, journal, journal_path)
        _resume_metadata(project, journal, journal_path)
        _resume_next_removal(project, journal, journal_path, residual)
        commit = _commit_promotion(
            resolved,
            milestone,
            landing,
            base,
            journal,
            journal_path,
            residual,
        )
        if residual.exists():
            shutil.rmtree(residual)
        journal_path.unlink()
    return {
        "schema": PROMOTION_SCHEMA,
        "status": "promoted",
        "milestone": milestone,
        "branch": branch,
        "integrate": landing,
        "landing": landing,
        "base": base,
        "commit": commit,
        "drift": journal["drift"],
    }
