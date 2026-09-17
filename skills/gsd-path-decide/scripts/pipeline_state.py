#!/usr/bin/env python3
# gsd-path project runtime
"""Validate, route, and change GSD Path state without model-side parsing.

The helper owns the fixed-format STATE.md interface. It checkpoints plan and
roadmap approvals, promotes a lookahead track as a resumable transaction, and
classifies plan drift before the promoted milestone can enter build.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Iterator, Mapping, Optional, Sequence

try:
    from isolation import (
        IsolationError,
        authorized_task_worktree,
        checkpoint as isolation_checkpoint,
        collect_artifact_recoveries,
    )
    import _common
    import roadmap
except ModuleNotFoundError as error:  # pragma: no cover - package imports used by tests
    if error.name not in {"isolation", "_common", "roadmap"}:
        raise
    from scripts.isolation import (
        IsolationError,
        authorized_task_worktree,
        checkpoint as isolation_checkpoint,
        collect_artifact_recoveries,
    )
    from scripts import _common, roadmap

try:  # pragma: no cover - exercised only on Windows
    import fcntl
except ImportError:  # pragma: no cover - exercised only on Windows
    fcntl = None  # type: ignore[assignment]


PIPELINE_MARKER = _common.PIPELINE_MARKER
PHASES = (
    "inspect",
    "define",
    "research",
    "decide",
    "roadmap",
    "plan",
    "build",
    "ship",
    "shipped",
)
STATUSES = ("active", "done", "blocked")
STATE_FIELDS = (
    "pipeline",
    "project",
    "milestone",
    "phase",
    "status",
    "branch",
    "archive",
    "integration_default",
    "integration",
    "integration_source",
)
LEGACY_STATE_FIELDS = STATE_FIELDS[:7]
INTEGRATION_MODES = ("direct", "pull-request")
INTEGRATION_SOURCES = ("default", "milestone")
NULL = "null"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
BOUND_BRANCH_RE = _common.BOUND_BRANCH_RE
ARCHIVE_RE = re.compile(r"^\.project/archive/(\d{3,})-([a-z0-9][a-z0-9-]*)/?$")
FRONTMATTER_RE = re.compile(r"^([a-z_]+):\s*([^#]*?)(?:\s+#.*)?$")
TASK_ID_RE = re.compile(r"^T\d{3,}$")
TASK_FILE_RE = re.compile(r"^(T\d{3,})-[a-z0-9][a-z0-9-]*\.md$")
PLAN_APPROVAL_SUBJECT = "plan: build plan approved"
PROMOTION_SCHEMA = "gsd-path/promote-next/v1"
STATE_SCHEMA = "gsd-path/state/v1"
ROUTE_SCHEMA = "gsd-path/route/v1"
STATUS_SCHEMA = "gsd-path/status/v1"
LEGACY_BIND_NEXT_JOURNAL_SCHEMA = "gsd-path/bind-next-journal/v1"
BIND_NEXT_JOURNAL_SCHEMA = "gsd-path/bind-next-journal/v2"
BIND_NEXT_JOURNAL_DIR = "gsd-path-bind-next"
PROMOTION_TRACKS = ("intent", "research", "plan", "tasks", "review")
LOOKAHEAD_PHASES = ("inspect", "define", "research", "decide", "plan")
LOOKAHEAD_FIXED_ARTIFACTS = {
    "STATE.md": "inspect",
    "research/evidence-codebase.md": "inspect",
    "research/DOCS-AUDIT.md": "inspect",
    "intent/INTENT.md": "define",
    "research/RESEARCH.md": "research",
    "research/SYNTHESIS.md": "decide",
    "plan/PLAN.md": "plan",
    "review/PLAN-PANEL.md": "plan",
    "review/PLAN-PANEL.skipped.json": "plan",
}
LOOKAHEAD_EVIDENCE_RE = re.compile(r"^research/evidence-[a-z0-9][a-z0-9-]*\.md$")
PROMOTION_RESIDUAL = ".gsd-path-promote-next-residual"
CHECKPOINT_SCHEMA = "gsd-path/state-checkpoint/v1"
CHECKPOINT_JOURNAL_NAME = "gsd-path-state-checkpoint.json"
CHECKPOINT_KINDS = ("plan", "roadmap", "roadmap-reslice")
SHIPMENT_SCHEMA = "gsd-path/shipment/v1"
SHIPMENT_JOURNAL_NAME = "gsd-path-shipment.json"
UNDO_TRANSACTION_SCHEMA = "gsd-path/undo-transaction/v2"
UNDO_TRANSACTION_NAME = "gsd-path-undo.json"

CROSS_PHASE_TRANSITIONS = {
    ("inspect", "done", "define", "active"),
    ("define", "done", "research", "active"),
    ("define", "done", "plan", "active"),
    ("research", "done", "decide", "active"),
    ("decide", "done", "roadmap", "active"),
    ("define", "active", "roadmap", "active"),
    ("decide", "done", "plan", "active"),
    ("roadmap", "done", "define", "active"),
    ("plan", "done", "build", "active"),
    ("build", "blocked", "define", "active"),
    ("build", "blocked", "plan", "active"),
    ("build", "active", "ship", "active"),
    ("build", "done", "ship", "active"),
    ("ship", "active", "shipped", "done"),
    ("build", "active", "roadmap", "active"),
    ("build", "blocked", "roadmap", "active"),
    ("ship", "blocked", "plan", "active"),
    ("shipped", "done", "define", "active"),
    ("shipped", "done", "inspect", "active"),
    ("roadmap", "active", "inspect", "active"),
}


class PipelineStateError(RuntimeError):
    """Raised when pipeline state cannot be proven or changed safely."""


@dataclass(frozen=True)
class PipelineState:
    pipeline: str
    project: str
    milestone: Optional[str]
    phase: str
    status: str
    branch: Optional[str]
    archive: Optional[str]
    integration_default: str
    integration: str
    integration_source: str

    def json(self) -> dict[str, Optional[str]]:
        return asdict(self)


@dataclass(frozen=True)
class ApprovedTaskContract:
    path: str
    text: str
    files: tuple[str, ...]


# Standalone transaction imports must reuse this state module and its types.
if __name__ == "__main__":
    sys.modules.setdefault("pipeline_state", sys.modules[__name__])


def _run_git(
    repo: Path,
    *arguments: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *arguments],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineStateError(f"git {' '.join(arguments)} failed: {detail}")
    return result


def _repo_root(repo: Path) -> Path:
    if repo.is_symlink() or not repo.is_dir():
        raise PipelineStateError(f"repo must be a real directory: {repo}")
    resolved = repo.resolve()
    top = _run_git(resolved, "rev-parse", "--show-toplevel", check=False)
    if top.returncode == 0 and Path(top.stdout.strip()).resolve() != resolved:
        raise PipelineStateError(f"repo must be the worktree root: {resolved}")
    return resolved


def _track_root(repo: Path, project_dir: str) -> Path:
    repo = repo.resolve()
    relative = PurePosixPath(project_dir)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise PipelineStateError(f"project-dir must stay inside repo: {project_dir}")
    root = repo.joinpath(*relative.parts)
    if root.is_symlink() or not root.is_dir():
        raise PipelineStateError(f"project directory must be real: {root}")
    if repo not in root.resolve().parents:
        raise PipelineStateError(f"project directory escapes repo: {root}")
    return root


def _read_real_file(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise PipelineStateError(f"{label} must be a real file: {path}")
    return path.read_text(encoding="utf-8")


def _optional_real_file(path: Path, label: str) -> Optional[str]:
    if not path.exists() and not path.is_symlink():
        return None
    return _read_real_file(path, label)


def _parse_frontmatter(text: str, label: str) -> dict[str, str]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise PipelineStateError(f"{label} is missing YAML frontmatter")
    values: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return values
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = FRONTMATTER_RE.fullmatch(line)
        if match is None:
            raise PipelineStateError(f"{label} has unsupported frontmatter: {line}")
        key, raw_value = match.groups()
        if key in values:
            raise PipelineStateError(f"{label} repeats frontmatter field: {key}")
        values[key] = raw_value.strip().strip("\"'")
    raise PipelineStateError(f"{label} frontmatter is not closed")


def _nullable(value: str) -> Optional[str]:
    return None if value == NULL else value


def _bound_branch_number(value: str) -> Optional[int]:
    match = BOUND_BRANCH_RE.fullmatch(value)
    if match is None:
        return None
    number = int(match.group(1))
    return number if number >= 1 else None


def _state_from_text(text: str, label: str = "STATE.md") -> PipelineState:
    values = _parse_frontmatter(text, label)
    missing = [field for field in LEGACY_STATE_FIELDS if field not in values]
    extra = sorted(set(values) - set(STATE_FIELDS))
    if missing:
        raise PipelineStateError(f"{label} is missing fields: {', '.join(missing)}")
    if extra:
        raise PipelineStateError(f"{label} has unknown fields: {', '.join(extra)}")
    integration_pair = {"integration_default", "integration"}
    integration_fields = integration_pair | {"integration_source"}
    present_integration_fields = integration_fields & set(values)
    if present_integration_fields not in (set(), integration_pair, integration_fields):
        raise PipelineStateError(
            f"{label} integration_default and integration must appear together"
        )

    integration_default = values.get("integration_default", "direct")
    integration = values.get("integration", "direct")
    integration_source = values.get("integration_source")
    if integration_source is None:
        integration_source = (
            "default" if integration == integration_default else "milestone"
        )

    state = PipelineState(
        pipeline=values["pipeline"],
        project=values["project"],
        milestone=_nullable(values["milestone"]),
        phase=values["phase"],
        status=values["status"],
        branch=_nullable(values["branch"]),
        archive=_nullable(values["archive"]),
        integration_default=integration_default,
        integration=integration,
        integration_source=integration_source,
    )
    _validate_state_values(state, label)
    return state


def _validate_state_values(state: PipelineState, label: str) -> None:
    if state.pipeline != PIPELINE_MARKER:
        raise PipelineStateError(f"{label} pipeline must be {PIPELINE_MARKER}")
    if state.project == NULL or not SLUG_RE.fullmatch(state.project):
        raise PipelineStateError(f"{label} project must be a slug")
    if state.milestone is not None and not SLUG_RE.fullmatch(state.milestone):
        raise PipelineStateError(f"{label} milestone must be null or a slug")
    if state.phase not in PHASES:
        raise PipelineStateError(f"{label} has invalid phase: {state.phase}")
    if state.status not in STATUSES:
        raise PipelineStateError(f"{label} has invalid status: {state.status}")
    if state.integration_default not in INTEGRATION_MODES:
        raise PipelineStateError(
            f"{label} has invalid integration_default: {state.integration_default}"
        )
    if state.integration not in INTEGRATION_MODES:
        raise PipelineStateError(f"{label} has invalid integration: {state.integration}")
    if state.integration_source not in INTEGRATION_SOURCES:
        raise PipelineStateError(
            f"{label} has invalid integration_source: {state.integration_source}"
        )
    if (
        state.integration_source == "default"
        and state.integration != state.integration_default
    ):
        raise PipelineStateError(
            f"{label} default-sourced integration must match integration_default"
        )
    if state.branch is not None and _bound_branch_number(state.branch) is None:
        raise PipelineStateError(f"{label} has invalid branch: {state.branch}")
    archive_match = ARCHIVE_RE.fullmatch(state.archive or "")
    if state.archive is not None and (
        archive_match is None or int(archive_match.group(1)) < 1
    ):
        raise PipelineStateError(f"{label} has invalid archive: {state.archive}")
    if state.phase == "shipped" and state.status != "done":
        raise PipelineStateError(f"{label} shipped phase requires status done")
    if state.phase == "shipped" and state.archive is None:
        raise PipelineStateError(f"{label} shipped phase requires an archive")
    if state.archive is not None and state.phase not in {"build", "ship", "shipped"}:
        raise PipelineStateError(
            f"{label} archive is only legal during build, ship, or shipped"
        )
    if state.phase in {"ship", "shipped"} and state.branch is None:
        raise PipelineStateError(f"{label} {state.phase} phase requires a branch")
    if archive_match is not None:
        if state.milestone != archive_match.group(2):
            raise PipelineStateError(f"{label} archive does not match milestone")
        branch_number = _bound_branch_number(state.branch or "")
        if branch_number is None or branch_number != int(archive_match.group(1)):
            raise PipelineStateError(f"{label} archive does not match branch")


def _is_lookahead(project_dir: str) -> bool:
    return PurePosixPath(project_dir) == PurePosixPath(".project/next")


def _validate_state_context(
    state: PipelineState,
    project_dir: str,
    label: str,
) -> None:
    if not _is_lookahead(project_dir):
        return
    if state.branch is not None or state.archive is not None:
        raise PipelineStateError(f"{label} lookahead branch and archive must be null")
    if state.phase not in LOOKAHEAD_PHASES:
        raise PipelineStateError(f"{label} lookahead cannot enter {state.phase}")


def load_state(repo: Path, project_dir: str = ".project") -> tuple[PipelineState, str, Path]:
    root = _track_root(repo, project_dir)
    path = root / "STATE.md"
    text = _read_real_file(path, "STATE.md")
    state = _state_from_text(text)
    _validate_state_context(state, project_dir, "STATE.md")
    if _is_lookahead(project_dir):
        _validate_next_layout(root, state)
    return state, text, path


def validate_state(repo: Path, project_dir: str = ".project") -> dict[str, object]:
    resolved = _repo_root(repo)
    state, _, path = load_state(resolved, project_dir)
    return {
        "schema": STATE_SCHEMA,
        "status": "valid",
        "path": str(path),
        "state": state.json(),
    }


def undo_transaction(repo: Path) -> Optional[dict[str, object]]:
    resolved = _repo_root(repo)
    path = _git_path(resolved, UNDO_TRANSACTION_NAME)
    if not path.exists() and not path.is_symlink():
        return None
    value = _read_json(path)
    expected = {
        "schema",
        "repo",
        "kind",
        "expected_head",
        "parent",
        "branch",
        "worktree_fingerprint",
        "archive",
        "archive_fingerprint",
        "discussion",
    }
    if set(value) != expected or value.get("schema") != UNDO_TRANSACTION_SCHEMA:
        raise PipelineStateError("undo transaction has invalid fields")
    if value.get("repo") != str(resolved):
        raise PipelineStateError("undo transaction belongs to another worktree")
    kind = value.get("kind")
    if kind not in {"checkpoint", "uncommitted-archive"}:
        raise PipelineStateError("undo transaction has invalid kind")
    for field in ("expected_head", "parent"):
        field_value = value.get(field)
        if not isinstance(field_value, str) or not re.fullmatch(
            r"[0-9a-f]{40,64}", field_value
        ):
            raise PipelineStateError(f"undo transaction has invalid {field}")
    branch = value.get("branch")
    if not isinstance(branch, str) or BOUND_BRANCH_RE.fullmatch(branch) is None:
        raise PipelineStateError("undo transaction has invalid branch")
    fingerprint = value.get("worktree_fingerprint")
    if not isinstance(fingerprint, str) or not re.fullmatch(
        r"[0-9a-f]{64}", fingerprint
    ):
        raise PipelineStateError("undo transaction has invalid worktree fingerprint")
    archive = value.get("archive")
    archive_fingerprint = value.get("archive_fingerprint")
    if kind == "checkpoint" and (
        archive is not None or archive_fingerprint is not None
    ):
        raise PipelineStateError("checkpoint undo transaction cannot name an archive")
    if kind == "uncommitted-archive" and (
        not isinstance(archive, str) or ARCHIVE_RE.fullmatch(archive) is None
    ):
        raise PipelineStateError("archive undo transaction has invalid archive")
    if kind == "uncommitted-archive" and (
        not isinstance(archive_fingerprint, str)
        or not re.fullmatch(r"[0-9a-f]{64}", archive_fingerprint)
    ):
        raise PipelineStateError(
            "archive undo transaction has invalid archive fingerprint"
        )
    discussion = value.get("discussion")
    if discussion is not None and (
        not isinstance(discussion, dict)
        or set(discussion) != {"DIALOGUE.md", "ANSWERS.md"}
        or any(not isinstance(content, str) for content in discussion.values())
    ):
        raise PipelineStateError("undo transaction has invalid discussion records")
    return value


def transaction_journals(repo: Path) -> dict[str, Optional[str]]:
    """Return paths of any in-progress helper journals. Read-only."""
    resolved = _repo_root(repo)
    found: dict[str, Optional[str]] = {}
    named = {
        "checkpoint": CHECKPOINT_JOURNAL_NAME,
        "shipment": SHIPMENT_JOURNAL_NAME,
        "promotion": "gsd-path-promote-next.json",
        "abandon": "gsd-path-abandon.json",
    }
    for key, name in named.items():
        path = _git_path(resolved, name)
        found[key] = str(path) if path.exists() or path.is_symlink() else None
    state, _, _ = load_state(resolved)
    bind_recovery = _bind_next_recovery(resolved, state)
    found["bind_next"] = (
        str(bind_recovery["route"]["journal"])
        if bind_recovery is not None
        else None
    )
    transaction = undo_transaction(resolved)
    found["undo"] = (
        str(_git_path(resolved, UNDO_TRANSACTION_NAME))
        if transaction is not None
        else None
    )
    try:
        collect = collect_artifact_recoveries(resolved)
    except IsolationError as error:
        raise PipelineStateError(str(error)) from error
    found["collect_artifact"] = str(collect[0]["journal"]) if collect else None
    return found


def _optional_rev(repo: Path, spec: str) -> Optional[str]:
    result = _run_git(repo, "rev-parse", "--verify", "--quiet", spec, check=False)
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    result = _run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        ancestor,
        descendant,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = result.stderr.strip() or result.stdout.strip() or "git ancestry probe failed"
    raise PipelineStateError(detail)


def _live_annotated_tag(repo: Path, tag_ref: str) -> tuple[str, str]:
    result = _run_git(
        repo,
        "ls-remote",
        "--exit-code",
        "origin",
        tag_ref,
        f"{tag_ref}^{{}}",
        check=False,
    )
    if result.returncode == 2:
        raise PipelineStateError("published milestone tag is missing on origin")
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineStateError(
            f"could not inspect published milestone tag on origin: {detail}"
        )
    refs: dict[str, str] = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t", 1)
        if (
            len(fields) != 2
            or fields[1] in refs
            or re.fullmatch(r"[0-9a-f]{40}", fields[0]) is None
        ):
            raise PipelineStateError("origin returned invalid milestone tag data")
        refs[fields[1]] = fields[0]
    peeled_ref = f"{tag_ref}^{{}}"
    if set(refs) != {tag_ref, peeled_ref}:
        raise PipelineStateError("origin milestone tag is missing or not annotated")
    return refs[tag_ref], refs[peeled_ref]


def _commit_subject_body(repo: Path, revision: str = "HEAD") -> tuple[str, str]:
    raw = _run_git(repo, "cat-file", "commit", revision).stdout
    try:
        message = raw.split("\n\n", 1)[1]
    except IndexError as error:
        raise PipelineStateError(f"commit {revision} has no message body") from error
    subject, _, rest = message.partition("\n")
    return subject.strip(), rest.lstrip("\n")


def _pending_answers(repo: Path) -> tuple[list[dict[str, str]], Optional[str]]:
    answers = repo / ".project" / "discuss" / "ANSWERS.md"
    if not answers.exists() and not answers.is_symlink():
        return [], None
    try:
        try:
            from discussion_records import DiscussionError, pending_records
        except ModuleNotFoundError as error:  # pragma: no cover - package imports used by tests
            if error.name != "discussion_records":
                raise
            from scripts.discussion_records import DiscussionError, pending_records
    except ModuleNotFoundError as error:
        if error.name not in {"scripts", "scripts.discussion_records"}:
            raise
        return [], "discussion_records helper is unavailable"
    try:
        records = pending_records(answers.parent)
    except (DiscussionError, OSError, UnicodeDecodeError, ValueError) as error:
        return [], str(error)
    pending: list[dict[str, str]] = []
    for record in records:
        pending.append(
            {
                "answer": str(record.get("answer") or ""),
                "owner": str(record.get("owner") or ""),
                "target": str(record.get("target") or ""),
                "status": str(record.get("status") or ""),
            }
        )
    return pending, None


def _next_skill(route: Mapping[str, object]) -> Optional[str]:
    action = route.get("action")
    phase = route.get("phase")
    if action == "run-phase" and isinstance(phase, str):
        return f"gsd-path-{phase}"
    if action in {
        "bind-initial",
        "resume-checkpoint",
        "resume-shipment",
        "resume-promotion",
        "resume-next-handoff",
        "resume-undo",
        "validate-integrated",
        "block",
    }:
        return "gsd-path-undo" if action == "resume-undo" else "gsd-path"
    return None


def _completion_status(repo: Path, state: Mapping[str, object], project_dir: str) -> dict:
    if project_dir != ".project" or state.get("phase") != "shipped":
        return {"status": "not-shipped"}
    if __package__:
        from . import integration
    else:
        import integration
    try:
        proof = integration.validate_integrated(
            repo, str(state.get("milestone") or ""), refresh=False)
    except (integration.ArchiveError, OSError) as error:
        return {"status": "unverified", "reason": str(error)}
    return {"status": "verified", "proof": proof}


def status_state(repo: Path, project_dir: str = ".project") -> dict[str, object]:
    """Report owned state, route, and git facts without advancing a phase."""
    resolved = _repo_root(repo)
    routed = route_state(resolved, project_dir)
    state = routed["state"]
    route = routed["route"]
    has_git = (
        _run_git(resolved, "rev-parse", "--git-dir", check=False).returncode == 0
    )
    head = _optional_rev(resolved, "HEAD") if has_git else None
    branch = _current_branch(resolved) if has_git else None
    origin_branch = (
        _optional_rev(resolved, f"refs/remotes/origin/{branch}")
        if branch
        else None
    )
    origin_main = (
        _optional_rev(resolved, "refs/remotes/origin/main") if has_git else None
    )
    pending, pending_error = _pending_answers(resolved)
    lookahead = resolved / ".project" / "next"
    subject = ""
    if head is not None:
        subject, _ = _commit_subject_body(resolved, head)
    journals = transaction_journals(resolved) if has_git else {
        "checkpoint": None,
        "shipment": None,
        "promotion": None,
        "abandon": None,
        "bind_next": None,
        "undo": None,
        "collect_artifact": None,
    }
    return {
        "schema": STATUS_SCHEMA,
        "advance": False,
        "completion": _completion_status(resolved, state, project_dir),
        "state": state,
        "route": route,
        "path": str(_track_root(resolved, project_dir) / "STATE.md"),
        "git": {
            "branch": branch,
            "head": head,
            "subject": subject,
            "dirty": _worktree_changes(resolved) if has_git else [],
            "origin_branch": origin_branch,
            "origin_main": origin_main,
            "published": bool(
                head
                and origin_branch
                and _is_ancestor(resolved, head, origin_branch)
            ),
            "ancestor_of_origin_main": bool(
                head and origin_main and _is_ancestor(resolved, head, origin_main)
            ),
        },
        "pending_answers": pending,
        "pending_error": pending_error,
        "lookahead": lookahead.exists() or lookahead.is_symlink(),
        "journals": journals,
        "next_skill": _next_skill(route if isinstance(route, dict) else {}),
        "handoff": phase_handoff(state, route, _track_root(resolved, project_dir) / "STATE.md"),
    }


def phase_handoff(state: Mapping[str, object], route: Mapping[str, object], path: Path) -> dict[str, str]:
    """Present the authoritative route without granting continuation authority."""
    action = route["action"]
    if action == "run-phase":
        next_action = f"Invoke $gsd-path to continue with {route['phase']}."
        router_next = f"Continue with {route['phase']}; honor its input and approval gates."
    else:
        next_action = router_next = f"{action}: {route['reason']}"
    return {
        "outcome": f"{state['phase']}/{state['status']}",
        "review": str(path),
        "next": next_action,
        "phase_next": next_action,
        "router_next": router_next,
    }


def _current_branch(repo: Path) -> Optional[str]:
    result = _run_git(
        repo,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
    )
    if result.returncode == 1:
        return None
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineStateError(f"could not inspect current branch: {detail}")
    return result.stdout.strip()


def _intent_lane(track: Path) -> Optional[str]:
    text = _optional_real_file(track / "intent" / "INTENT.md", "INTENT.md")
    if text is None:
        return None
    match = re.search(r"(?m)^Lane:\s*(standard|quick|milestone)\b", text)
    if match is None:
        return "standard"
    return match.group(1)


def _active_roadmap_has_questions(project: Path, milestone: Optional[str] = None) -> bool:
    text = _read_real_file(project / "ROADMAP.md", "ROADMAP.md")
    try:
        return roadmap.has_questions(text, milestone)
    except roadmap.RoadmapError as error:
        raise PipelineStateError(str(error)) from error

def _valid_patch_findings(repo: Path) -> bool:
    validator = Path(__file__).resolve().with_name("check_handoffs.py")
    if validator.is_symlink() or not validator.is_file():
        raise PipelineStateError(f"patch validator must be a real file: {validator}")
    result = subprocess.run(
        [
            sys.executable,
            "-B",
            str(validator),
            "patch",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _selected_initial_branch(project: Path, state: PipelineState) -> str:
    roadmap = project / "ROADMAP.md"
    if roadmap.exists() or roadmap.is_symlink():
        text = _read_real_file(roadmap, "ROADMAP.md")
        lines = text.splitlines(keepends=True)
        active: list[tuple[str, str]] = []
        for slug, (milestone_id, start, end) in _roadmap_sections(text).items():
            statuses = [
                match.group(1)
                for line in lines[start:end]
                if (match := re.match(r"^Status:\s*(\S+)", line)) is not None
            ]
            if statuses == ["active"]:
                active.append((milestone_id, slug))
        if len(active) != 1:
            raise PipelineStateError("ROADMAP.md must have exactly one active milestone")
        milestone_id, slug = active[0]
        if state.milestone is not None and state.milestone != slug:
            raise PipelineStateError("STATE.milestone does not match active roadmap entry")
        return f"gsd-path/{milestone_id}"

    archive = project / "archive"
    numbers: list[int] = []
    if archive.exists() or archive.is_symlink():
        if archive.is_symlink() or not archive.is_dir():
            raise PipelineStateError(f"archive root must be a real directory: {archive}")
        for child in archive.iterdir():
            match = re.fullmatch(r"(\d{3,})-[a-z0-9][a-z0-9-]*", child.name)
            if (
                child.is_symlink()
                or not child.is_dir()
                or match is None
                or int(match.group(1)) < 1
            ):
                raise PipelineStateError(f"archive root has invalid entry: {child}")
            numbers.append(int(match.group(1)))
    number = max(numbers) + 1 if numbers else 1
    return f"gsd-path/M{number:03d}"


def _route_result(
    state: PipelineState,
    action: str,
    *,
    phase: Optional[str] = None,
    mode: Optional[str] = None,
    reason: str,
) -> dict[str, object]:
    route = {"action": action, "reason": reason}
    if phase is not None:
        route["phase"] = phase
    if mode is not None:
        route["mode"] = mode
    return {"schema": ROUTE_SCHEMA, "state": state.json(), "route": route}


def _legacy_bind_next_landing(repo: Path, state: PipelineState) -> str:
    if ARCHIVE_RE.fullmatch(state.archive or "") is None:
        raise PipelineStateError("legacy bind-next journal requires a shipped archive")
    archive_name = PurePosixPath(state.archive or "").name
    tag_ref = f"refs/tags/milestone/{archive_name}"
    published_ref = f"refs/remotes/origin/tags/milestone/{archive_name}"
    for label, ref in (("local", tag_ref), ("published", published_ref)):
        tag_type = _run_git(repo, "cat-file", "-t", ref, check=False)
        if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
            raise PipelineStateError(
                f"legacy bind-next journal {label} milestone tag is missing or not annotated"
            )
    local_object = _run_git(repo, "rev-parse", "--verify", tag_ref).stdout.strip()
    published_object = _run_git(
        repo,
        "rev-parse",
        "--verify",
        published_ref,
    ).stdout.strip()
    if local_object != published_object:
        raise PipelineStateError(
            "legacy bind-next journal milestone tags do not match"
        )
    landing = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{tag_ref}^{{commit}}",
    ).stdout.strip()
    published_landing = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{published_ref}^{{commit}}",
    ).stdout.strip()
    if landing != published_landing:
        raise PipelineStateError(
            "legacy bind-next journal milestone tag landings do not match"
        )
    return landing


def _bind_next_recovery(
    repo: Path,
    state: PipelineState,
) -> Optional[dict[str, object]]:
    journal_root = _git_path(repo, BIND_NEXT_JOURNAL_DIR)
    if not journal_root.exists() and not journal_root.is_symlink():
        return None
    if journal_root.is_symlink() or not journal_root.is_dir():
        raise PipelineStateError(f"bind-next journal root must be a real directory: {journal_root}")

    matches: list[tuple[Path, dict[str, object]]] = []
    for path in sorted(journal_root.glob("*.json")):
        transaction = _read_json(path)
        if transaction.get("schema") not in {
            LEGACY_BIND_NEXT_JOURNAL_SCHEMA,
            BIND_NEXT_JOURNAL_SCHEMA,
        }:
            raise PipelineStateError(f"bind-next journal has invalid schema: {path}")
        if transaction.get("repo") != str(repo):
            raise PipelineStateError(f"bind-next journal belongs to another worktree: {path}")
        if transaction.get("previous_branch") == state.branch:
            matches.append((path, transaction))
    if not matches:
        return None
    if len(matches) != 1:
        raise PipelineStateError("multiple bind-next journals claim the current STATE branch")
    if state.phase != "shipped" or state.status != "done":
        raise PipelineStateError("bind-next journal requires STATE shipped/done")

    path, transaction = matches[0]
    required = (
        "branch",
        "previous_branch",
        "ship",
        "remote_default",
        "base",
        "stage",
    )
    expected_fields = {"schema", "repo", *required}
    optional_fields = {"allow_remote_absent"}
    if transaction["schema"] == BIND_NEXT_JOURNAL_SCHEMA:
        expected_fields.add("landing")
    else:
        optional_fields.add("landing")
    if (
        not expected_fields <= set(transaction)
        or set(transaction) - expected_fields - optional_fields
    ):
        raise PipelineStateError("bind-next journal has unsupported fields")
    if any(not isinstance(transaction.get(key), str) for key in required):
        raise PipelineStateError("bind-next journal is missing request fields")
    landing_value = transaction.get("landing")
    if transaction["schema"] == BIND_NEXT_JOURNAL_SCHEMA and not isinstance(
        landing_value, str
    ):
        raise PipelineStateError("bind-next journal is missing request fields")
    if landing_value is not None and not isinstance(landing_value, str):
        raise PipelineStateError("bind-next journal has invalid landing")
    allow_remote_absent = transaction.get("allow_remote_absent", False)
    if not isinstance(allow_remote_absent, bool):
        raise PipelineStateError("bind-next journal has invalid allow_remote_absent")
    branch = str(transaction["branch"])
    previous = str(transaction["previous_branch"])
    ship = str(transaction["ship"])
    base = str(transaction["base"])
    stage = str(transaction["stage"])
    branch_number = _bound_branch_number(branch)
    previous_number = _bound_branch_number(previous)
    if branch_number is None or previous_number is None:
        raise PipelineStateError("bind-next journal has invalid branch fields")
    if branch_number <= previous_number:
        raise PipelineStateError("bind-next journal target does not follow previous branch")
    if path.name != f"M{branch_number:03d}.json":
        raise PipelineStateError("bind-next journal path does not match target branch")
    if any(not re.fullmatch(r"[0-9a-f]{40}", value) for value in (ship, base)):
        raise PipelineStateError("bind-next journal has invalid ship or base SHA")
    for label, value in (("ship", ship), ("base", base)):
        resolved = _run_git(
            repo,
            "rev-parse",
            "--verify",
            f"{value}^{{commit}}",
            check=False,
        )
        if resolved.returncode != 0 or resolved.stdout.strip() != value:
            raise PipelineStateError(f"bind-next journal {label} is not an existing full SHA")
    landing = (
        landing_value
        if isinstance(landing_value, str)
        else _legacy_bind_next_landing(repo, state)
    )
    if re.fullmatch(r"[0-9a-f]{40}", landing) is None:
        raise PipelineStateError("bind-next journal has invalid landing SHA")
    resolved_landing = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{landing}^{{commit}}",
        check=False,
    )
    if resolved_landing.returncode != 0 or resolved_landing.stdout.strip() != landing:
        raise PipelineStateError("bind-next journal landing is not an existing full SHA")
    if not _is_ancestor(repo, ship, landing):
        raise PipelineStateError("bind-next journal landing does not contain ship")
    if not _is_ancestor(repo, landing, base):
        raise PipelineStateError("bind-next journal landing is not an ancestor of base")
    if transaction["remote_default"] != "origin/main":
        raise PipelineStateError("bind-next journal has invalid remote default")
    if stage not in {"prepared", "switched", "retired"}:
        raise PipelineStateError("bind-next journal has invalid stage")

    current = _current_branch(repo)
    if current not in {previous, branch}:
        raise PipelineStateError("bind-next journal does not own the current branch")
    if current == previous and stage != "prepared":
        raise PipelineStateError("bind-next journal stage conflicts with previous branch")
    head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
    if current == previous:
        if head != ship:
            raise PipelineStateError("bind-next previous branch is not at journal ship")
        if _run_git(repo, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}", check=False).returncode == 0:
            raise PipelineStateError("bind-next prepared journal collides with target branch")
    else:
        if head != base:
            raise PipelineStateError("bind-next target branch is not at journal base")
    result = _route_result(
        state,
        "resume-next-handoff",
        reason="a matching bind-next ownership journal is incomplete",
    )
    result["route"].update(
        {
            "previous_branch": previous,
            "branch": branch,
            "ship": ship,
            "remote_default": transaction["remote_default"],
            "base": base,
            "landing": landing,
            "allow_remote_absent": allow_remote_absent,
            "journal": str(path),
            "dirty": _worktree_changes(repo),
        }
    )
    return result


def _pending_discussion_block(repo: Path, phase: Optional[str]) -> Optional[str]:
    pending, error = _pending_answers(repo)
    if error:
        return f"pending discussion cannot be validated: {error}"
    if not pending or (phase and all(record["owner"] == f"gsd-path-{phase}" for record in pending)):
        return None
    owners = ", ".join(f"{record['answer']} ({record['owner']})" for record in pending)
    return f"pending discussion requires its owner disposition: {owners}; see {repo / '.project/discuss/ANSWERS.md'}"


def route_state(repo: Path, project_dir: str = ".project") -> dict[str, object]:
    """Route ordinary phase work only when its pending discussion owner can enter."""
    result = _route_state(repo, project_dir)
    route = result["route"]
    if project_dir == ".project" and route["action"] == "run-phase":
        recovery = _build_recovery().context(_repo_root(repo))
        if recovery and recovery["active"]:
            result["recovery"] = recovery
            if route.get("phase") == "define":
                route["mode"] = "corrections"
            elif route.get("phase") == "plan":
                route["mode"] = "build-repair"
    if route["action"] == "run-phase" and result["state"]["archive"] is None:
        reason = _pending_discussion_block(_repo_root(repo), route.get("phase"))
        if reason:
            result["route"] = {"action": "block", "reason": reason}
    return result


def _route_state(repo: Path, project_dir: str = ".project") -> dict[str, object]:
    """Return the next deterministic pipeline action for one state track."""
    resolved = _repo_root(repo)
    state, _, _ = load_state(resolved, project_dir)
    track = _track_root(resolved, project_dir)
    project = _track_root(resolved, ".project")
    lookahead = PurePosixPath(project_dir) == PurePosixPath(".project/next")

    if not lookahead:
        git_dir = _run_git(resolved, "rev-parse", "--git-dir", check=False)
        if git_dir.returncode == 0:
            undo = undo_transaction(resolved)
            if undo is not None:
                result = _route_result(
                    state,
                    "resume-undo",
                    reason="a journaled undo transaction is incomplete",
                )
                result["route"].update(
                    {
                        "kind": undo["kind"],
                        "expected_head": undo["expected_head"],
                        "journal": str(_git_path(resolved, UNDO_TRANSACTION_NAME)),
                    }
                )
                return result
            shipment_journal = _git_path(resolved, SHIPMENT_JOURNAL_NAME)
            if shipment_journal.exists() or shipment_journal.is_symlink():
                transaction = _read_json(shipment_journal)
                expected_keys = {
                    "schema", "repo", "archive", "event", "roadmap_before",
                    "roadmap_after", "state_before", "state_after",
                }
                if set(transaction) != expected_keys or transaction.get("schema") != SHIPMENT_SCHEMA or transaction.get("repo") != str(resolved):
                    raise PipelineStateError("shipment journal is invalid")
                result = _route_result(
                    state,
                    "resume-shipment",
                    reason="a journaled shipment metadata transaction is incomplete",
                )
                result["route"].update(
                    {"archive": transaction["archive"], "event": transaction["event"]}
                )
                return result
            checkpoint_journal = _git_path(resolved, CHECKPOINT_JOURNAL_NAME)
            if checkpoint_journal.exists() or checkpoint_journal.is_symlink():
                if __package__:
                    from . import state_checkpoint
                else:
                    import state_checkpoint
                transaction = state_checkpoint._approval_journal(
                    resolved,
                    _read_json(checkpoint_journal),
                )
                result = _route_result(
                    state,
                    "resume-checkpoint",
                    reason="a journaled plan or roadmap approval is incomplete",
                )
                result["route"].update(
                    {
                        "kind": transaction["kind"],
                        "project_dir": transaction["project_dir"],
                        "journal": str(checkpoint_journal),
                    }
                )
                return result
            promotion_journal = _git_path(
                resolved,
                "gsd-path-promote-next.json",
            )
            if promotion_journal.exists() or promotion_journal.is_symlink():
                transaction = _read_json(promotion_journal)
                required = {
                    "schema": PROMOTION_SCHEMA,
                    "repo": str(resolved),
                }
                if any(transaction.get(key) != value for key, value in required.items()):
                    raise PipelineStateError(
                        "promotion journal does not belong to this pipeline worktree"
                    )
                fields = {
                    key: transaction.get(key)
                    for key in ("milestone", "branch", "integrate")
                }
                if not all(isinstance(value, str) for value in fields.values()):
                    raise PipelineStateError("promotion journal is missing request fields")
                landing = transaction.get("landing", fields["integrate"])
                base = transaction.get("base", fields["integrate"])
                if not isinstance(landing, str) or not isinstance(base, str):
                    raise PipelineStateError("promotion journal has invalid landing or base")
                result = _route_result(
                    state,
                    "resume-promotion",
                    reason="a journaled lookahead promotion is incomplete",
                )
                fields["landing"] = landing
                fields["base"] = base
                result["route"].update(fields)
                result["route"]["journal"] = str(promotion_journal)
                return result
            bind_recovery = _bind_next_recovery(resolved, state)
            if bind_recovery is not None:
                return bind_recovery

    if not lookahead and state.branch is None:
        result = _route_result(
            state,
            "bind-initial",
            reason="active state has no router-owned branch binding",
        )
        result["route"]["branch"] = _selected_initial_branch(project, state)
        return result

    if state.branch is not None:
        current = _current_branch(resolved)
        if current != state.branch:
            isolated_build = (
                state.phase == "build"
                and authorized_task_worktree(resolved, state.branch)
            )
            if not isolated_build:
                return _route_result(
                    state,
                    "block",
                    reason=(
                        f"current branch {current or '<detached>'} != "
                        f"STATE.branch {state.branch}"
                    ),
                )

    if state.archive is not None:
        if state.phase == "build":
            return _route_result(
                state,
                "run-phase",
                phase="build",
                mode="abandon-recovery",
                reason="STATE.archive records an interrupted abandon transaction",
            )
        if state.phase in {"ship", "shipped"}:
            return _route_result(
                state,
                "run-phase",
                phase="ship",
                mode="archive-recovery" if state.phase == "ship" else "validate-integrated",
                reason="STATE.archive records a ship transaction",
            )

    phase, status = state.phase, state.status
    if phase == "inspect":
        return _route_result(
            state,
            "run-phase",
            phase="define" if status == "done" else "inspect",
            mode="brownfield" if status == "done" else "normal",
            reason=f"state is {phase}/{status}",
        )
    if phase == "define" and status != "done":
        return _route_result(
            state,
            "run-phase",
            phase="define",
            reason=f"state is {phase}/{status}",
        )
    if phase == "define":
        lane = _intent_lane(track)
        if lane == "quick":
            return _route_result(
                state,
                "run-phase",
                phase="plan",
                mode="quick",
                reason="INTENT lane is quick",
            )
        if lane == "milestone":
            questions = _active_roadmap_has_questions(
                project,
                state.milestone if lookahead else None,
            )
            entry = "lookahead" if lookahead else "active"
            return _route_result(
                state,
                "run-phase",
                phase="research" if questions else "plan",
                mode="milestone",
                reason=(
                    f"{entry} roadmap milestone has open questions"
                    if questions
                    else f"{entry} roadmap milestone has no open questions"
                ),
            )
        if lane is None:
            charter = _optional_real_file(project / "CHARTER.md", "CHARTER.md")
            if charter is None:
                return _route_result(
                    state,
                    "block",
                    reason="define/done has neither INTENT.md nor CHARTER.md",
                )
            mode = "program"
        else:
            mode = "standard"
        return _route_result(
            state,
            "run-phase",
            phase="research",
            mode=mode,
            reason="define is done",
        )
    if phase == "research":
        return _route_result(
            state,
            "run-phase",
            phase="decide" if status == "done" else "research",
            reason=f"state is {phase}/{status}",
        )
    if phase == "decide" and status != "done":
        return _route_result(
            state,
            "run-phase",
            phase="decide",
            reason=f"state is {phase}/{status}",
        )
    if phase == "decide":
        charter = project / "CHARTER.md"
        roadmap = project / "ROADMAP.md"
        next_phase = "roadmap" if charter.is_file() and not roadmap.exists() else "plan"
        return _route_result(state, "run-phase", phase=next_phase, reason="decide is done")
    if phase == "roadmap":
        return _route_result(
            state,
            "run-phase",
            phase="define" if status == "done" else "roadmap",
            mode="milestone" if status == "done" else "normal",
            reason=f"state is {phase}/{status}",
        )
    if phase == "plan" and status != "done":
        return _route_result(state, "run-phase", phase="plan", reason=f"state is {phase}/{status}")
    if phase == "plan":
        if lookahead:
            return _route_result(
                state,
                "wait",
                mode="lookahead-ready",
                reason="lookahead plan is approved and waits for milestone promotion",
            )
        return _route_result(
            state,
            "run-phase",
            phase="build",
            reason="approved plan and branch binding are ready",
        )
    if phase == "build":
        return _route_result(
            state,
            "run-phase",
            phase="build",
            mode="transition-recovery" if status == "done" else "recovery",
            reason=f"state is {phase}/{status}",
        )
    if phase == "ship":
        if status == "blocked":
            findings = project / "review" / "PATCH-FINDINGS.md"
            if (
                findings.is_file()
                and not findings.is_symlink()
                and _valid_patch_findings(resolved)
            ):
                return _route_result(
                    state,
                    "run-phase",
                    phase="plan",
                    mode="patch",
                    reason="validated patch findings exist",
                )
            return _route_result(
                state,
                "block",
                reason="ship is blocked without valid PATCH-FINDINGS.md",
            )
        return _route_result(
            state,
            "run-phase",
            phase="ship",
            mode="final",
            reason=f"state is {phase}/{status}",
        )
    return _route_result(state, "validate-integrated", reason="state is shipped/done")


def _set_frontmatter(text: str, changes: Mapping[str, str]) -> str:
    lines = text.splitlines(keepends=True)
    closing: Optional[int] = None
    seen: set[str] = set()
    for index, line in enumerate(lines[1:], start=1):
        if line.rstrip("\r\n") == "---":
            closing = index
            break
        match = re.match(r"^([a-z_]+):", line)
        if match and match.group(1) in changes:
            key = match.group(1)
            lines[index] = f"{key}: {changes[key]}\n"
            seen.add(key)
    if closing is None:
        raise PipelineStateError("STATE.md frontmatter is not closed")
    missing = set(changes) - seen
    integration_fields = (
        "integration_default",
        "integration",
        "integration_source",
    )
    unsupported_missing = missing - set(integration_fields)
    if unsupported_missing:
        raise PipelineStateError(f"STATE.md is missing fields: {', '.join(sorted(missing))}")
    for key in integration_fields:
        if key in missing:
            lines.insert(closing, f"{key}: {changes[key]}\n")
            closing += 1
    return "".join(lines)


def _append_event(
    text: str,
    phase: str,
    event: str,
    event_date: Optional[str] = None,
) -> str:
    cleaned = " ".join(event.split())
    if not cleaned or "\n" in event or "\r" in event:
        raise PipelineStateError("state event must be one non-empty line")
    if "## Log" not in text:
        raise PipelineStateError("STATE.md is missing ## Log")
    suffix = "" if text.endswith("\n") else "\n"
    timestamp = event_date or date.today().isoformat()
    try:
        date.fromisoformat(timestamp)
    except ValueError as error:
        raise PipelineStateError(f"state event date is invalid: {timestamp}") from error
    return f"{text}{suffix}- {timestamp} — {phase} — {cleaned}\n"


@contextlib.contextmanager
def _state_lock(project: Path) -> Iterator[None]:
    if fcntl is None:  # pragma: no cover - Windows CI is not used
        raise PipelineStateError("state locking is unavailable on this platform")
    descriptor = os.open(project, os.O_RDONLY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.parent / f".{path.name}.gsd-path-tmp"
    try:
        path_status = path.lstat()
        temporary_status = temporary.lstat()
    except FileNotFoundError:
        pass
    else:
        if (
            stat.S_ISREG(path_status.st_mode)
            and stat.S_ISREG(temporary_status.st_mode)
            and path_status.st_nlink == 2
            and temporary_status.st_nlink == 2
            and os.path.samestat(path_status, temporary_status)
        ):
            temporary.unlink()
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    if temporary.exists() or temporary.is_symlink():
        raise PipelineStateError(f"atomic-write temporary path already exists: {temporary}")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def _validate_transition(
    before: PipelineState,
    after: PipelineState,
    event: str,
    project_dir: str,
    approval_kind: Optional[str] = None,
    allow_integration_configuration: bool = False,
) -> None:
    before_position = (before.phase, before.status)
    after_position = (after.phase, after.status)
    approval_edge = (
        before.phase in CHECKPOINT_KINDS
        and before_position == (before.phase, "active")
        and after_position == (before.phase, "done")
    )
    if approval_edge and approval_kind != before.phase:
        raise PipelineStateError(
            f"{before.phase} approval requires pipeline_state.py approve "
            f"--kind {before.phase}"
        )
    if before.phase == after.phase:
        same_phase_statuses = {
            "active": {"active", "blocked", "done"},
            "blocked": {"blocked", "active"},
            "done": {"done"},
        }
        patch_reopen = (
            before_position == ("plan", "done")
            and after_position == ("plan", "active")
            and event == "patch plan reopened"
        )
        if after.status not in same_phase_statuses[before.status] and not patch_reopen:
            raise PipelineStateError(
                f"illegal state transition: {before_position} -> {after_position}"
            )
    elif (*before_position, *after_position) not in CROSS_PHASE_TRANSITIONS:
        raise PipelineStateError(
            f"illegal state transition: {before_position} -> {after_position}"
        )

    if before.pipeline != after.pipeline or before.project != after.project:
        raise PipelineStateError("pipeline and project are immutable")
    if (
        (*before_position, *after_position)
        == ("define", "active", "roadmap", "active")
        and PurePosixPath(project_dir) != PurePosixPath(".project")
    ):
        raise PipelineStateError("roadmap re-slice is legal only on the active track")

    branch_changed = before.branch != after.branch
    initial_binding = before.branch is None and after.branch is not None
    next_binding = (
        before.phase == "shipped"
        and before.status == "done"
        and after.phase in {"define", "inspect"}
        and after.status == "active"
        and before.branch is not None
        and after.branch is not None
    )
    abandon = (
        before.phase == "build"
        and after.phase == "roadmap"
        and after.status == "active"
        and before.archive is not None
        and after.archive is None
    )
    integration_changed = (
        before.integration_default != after.integration_default
        or before.integration != after.integration
        or before.integration_source != after.integration_source
    )
    if integration_changed and not (next_binding or abandon):
        if before.phase in {"build", "ship", "shipped"}:
            raise PipelineStateError("integration mode is locked when build starts")
        if not allow_integration_configuration:
            raise PipelineStateError(
                "integration mode changes require configure-integration"
            )
    if next_binding:
        before_number = _bound_branch_number(before.branch or "")
        after_number = _bound_branch_number(after.branch or "")
        if (
            before_number is None
            or after_number is None
            or after_number <= before_number
        ):
            raise PipelineStateError(
                "next milestone requires a higher router-bound branch"
            )
        if after.integration_default != before.integration_default:
            raise PipelineStateError("next milestone must preserve integration_default")
        if after.integration != before.integration_default:
            raise PipelineStateError("next milestone must reset its integration override")
        if after.integration_source != "default":
            raise PipelineStateError("next milestone integration must use the project default")
    if abandon:
        if after.integration_default != before.integration_default:
            raise PipelineStateError("milestone abandon must preserve integration_default")
        if after.integration != before.integration_default:
            raise PipelineStateError("milestone abandon must reset its integration override")
        if after.integration_source != "default":
            raise PipelineStateError("milestone abandon integration must use the project default")
    if branch_changed and not (initial_binding or next_binding):
        raise PipelineStateError("illegal STATE.branch transition")
    if initial_binding:
        if before_position != after_position:
            raise PipelineStateError("initial branch binding cannot change phase or status")
        if event != "router bound initial milestone":
            raise PipelineStateError(
                "initial branch binding requires event: router bound initial milestone"
            )

    archive_changed = before.archive != after.archive
    next_milestone = (
        before.phase == "shipped"
        and before.status == "done"
        and after.phase in {"define", "inspect"}
        and after.status == "active"
        and before.archive is not None
        and after.archive is None
    )
    if archive_changed and not (abandon or next_milestone):
        raise PipelineStateError("illegal STATE.archive transition")

    milestone_changed = before.milestone != after.milestone
    define_approval = (
        before_position == ("define", "active")
        and after_position == ("define", "done")
        and after.milestone is not None
        and event == "milestone intent approved"
    )
    roadmap_selection = (
        before_position == ("roadmap", "active")
        and after_position == ("roadmap", "done")
        and after.milestone is not None
        and event == "program roadmap approved"
    )
    post_abandon_selection = (
        before_position == ("roadmap", "active")
        and after_position == ("inspect", "active")
        and before.milestone is None
        and after.milestone is not None
    )
    if milestone_changed and not (
        define_approval
        or roadmap_selection
        or next_milestone
        or abandon
        or post_abandon_selection
    ):
        raise PipelineStateError("illegal STATE.milestone transition")
    if (
        before_position == ("plan", "blocked")
        and after_position == ("plan", "active")
        and event != "planning resumed"
    ):
        raise PipelineStateError("plan recovery requires event: planning resumed")
    if abandon:
        expected_event = (
            f"milestone abandoned: {before.milestone}; archive: {before.archive}; "
        )
        if (
            before.milestone is None
            or after.milestone is not None
            or not event.startswith(expected_event)
            or not event.removeprefix(expected_event).startswith("ruling: ")
            or event == f"{expected_event}ruling:"
        ):
            raise PipelineStateError(
                "milestone abandon event must name its milestone, archive, and ruling"
            )

    edge_events = {
        ("plan", "done", "build", "active"): {"build started"},
        ("build", "active", "ship", "active"): {
            "build done; final review pending"
        },
        ("build", "done", "ship", "active"): {
            "build done; final review pending"
        },
        ("decide", "done", "roadmap", "active"): {"roadmap started"},
        ("define", "active", "roadmap", "active"): {
            "roadmap re-slice started"
        },
        ("define", "done", "plan", "active"): {"planning started"},
        ("decide", "done", "plan", "active"): {"planning started"},
        ("ship", "blocked", "plan", "active"): {"patch plan reopened"},
        ("ship", "active", "shipped", "done"): {
            "archive preflight passed; shipment recorded",
            "archive preflight passed; shipment recorded; program complete",
        },
    }.get((*before_position, *after_position))
    if edge_events is not None and event not in edge_events:
        expected = " or ".join(sorted(edge_events))
        raise PipelineStateError(f"state transition requires event: {expected}")


def transition_state(
    repo: Path,
    expected: Mapping[str, Optional[str]],
    changes: Mapping[str, Optional[str]],
    event: str,
    project_dir: str = ".project",
) -> dict[str, object]:
    """Atomically apply a state change only when expected fields still match."""
    resolved = _repo_root(repo)
    project = _track_root(resolved, project_dir)
    unsupported = (set(expected) | set(changes)) - set(STATE_FIELDS)
    if unsupported:
        raise PipelineStateError(f"unsupported state fields: {', '.join(sorted(unsupported))}")
    if not changes:
        raise PipelineStateError("transition requires at least one changed field")
    required_expected = {"phase", "status", "branch", "archive"} | set(changes)
    missing_expected = sorted(required_expected - set(expected))
    if missing_expected:
        raise PipelineStateError(
            "transition is missing expected fields: " + ", ".join(missing_expected)
        )
    with _state_lock(project):
        state, text, path = load_state(resolved, project_dir)
        before, after, rendered = _render_transition(
            state,
            text,
            expected,
            changes,
            event,
            project_dir,
        )
        recovery_context = _build_recovery().context(resolved, text) if project_dir == ".project" else None
        if recovery_context and recovery_context["active"]:
            if (state.milestone, state.branch, state.archive) != (after.milestone, after.branch, after.archive):
                raise PipelineStateError("build recovery must preserve milestone identity")
        if state.phase == "build" and after.phase in {"define", "plan"}:
            recovery = _build_recovery().begin(resolved, state, after, event)
            rendered = _append_event(
                rendered, after.phase,
                _build_recovery().MARKER + json.dumps(recovery, sort_keys=True),
            )
        if after.status != "blocked":
            reason = _pending_discussion_block(
                resolved, after.phase if after.status == "active" else None
            )
            if reason:
                raise PipelineStateError(reason)
        if state.phase in {"research", "decide"} and (
            after.phase != state.phase or after.status == "done"
        ):
            try:
                import check_handoffs
            except ImportError:  # pragma: no cover - package imports used by tests
                from scripts import check_handoffs
            validator = {
                "research": check_handoffs.validate_research_artifacts,
                "decide": check_handoffs.validate_decide_artifacts,
            }[state.phase]
            try:
                validator(resolved, project_dir)
            except check_handoffs.HandoffError as error:
                raise PipelineStateError(f"{state.phase} handoff failed: {error}") from error
        _atomic_write(path, rendered)
    return {
        "schema": STATE_SCHEMA,
        "status": "transitioned",
        "path": str(path),
        "previous": before,
        "state": after.json(),
    }


def _build_recovery():
    if __package__:
        from scripts import build_recovery
    else:
        import build_recovery
    return build_recovery


def configure_integration(
    repo: Path,
    scope: str,
    mode: str,
    project_dir: str = ".project",
) -> dict[str, object]:
    """Set the project default or current milestone integration before build."""
    if scope not in {"default", "milestone"}:
        raise PipelineStateError(f"invalid integration scope: {scope}")
    if mode not in INTEGRATION_MODES:
        raise PipelineStateError(f"invalid integration mode: {mode}")
    if scope == "default" and _is_lookahead(project_dir):
        raise PipelineStateError(
            "project integration default must be configured on the active track"
        )
    resolved = _repo_root(repo)
    project = _track_root(resolved, project_dir)
    with _state_lock(project):
        state, text, path = load_state(resolved, project_dir)
        if state.phase in {"build", "ship", "shipped"} or (
            project_dir == ".project" and _build_recovery().context(resolved, text)
        ):
            raise PipelineStateError("integration mode is locked when build starts")
        if scope == "default":
            integration = (
                mode if state.integration_source == "default" else state.integration
            )
            changes = {
                "integration_default": mode,
                "integration": integration,
                "integration_source": state.integration_source,
            }
        else:
            changes = {
                "integration_default": state.integration_default,
                "integration": mode,
                "integration_source": "milestone",
            }
        rendered = _set_frontmatter(text, changes)
        rendered = _append_event(
            rendered,
            state.phase,
            f"integration {scope} set to {mode}",
        )
        after = _state_from_text(rendered)
        _validate_state_context(after, project_dir, "STATE.md")
        _validate_transition(
            state,
            after,
            f"integration {scope} set to {mode}",
            project_dir,
            allow_integration_configuration=True,
        )
        _atomic_write(path, rendered)
    return {
        "schema": STATE_SCHEMA,
        "status": "configured",
        "path": str(path),
        "previous": state.json(),
        "state": after.json(),
    }


def _shipment_roadmap(text: str, state: PipelineState, archive: str) -> str:
    if state.milestone is None or state.branch is None:
        raise PipelineStateError("shipment state must name milestone and branch")
    sections = _roadmap_sections(text)
    if state.milestone not in sections:
        raise PipelineStateError("ROADMAP.md is missing the shipped milestone")
    milestone_id, start, end = sections[state.milestone]
    number = _bound_branch_number(state.branch)
    match = ARCHIVE_RE.fullmatch(archive)
    if match is None or number != int(match.group(1)) or milestone_id != f"M{number:03d}":
        raise PipelineStateError("shipment branch, archive, and roadmap milestone differ")
    lines = text.splitlines(keepends=True)
    _replace_roadmap_field(lines, start, end, "Status", {"active", "shipped"}, "shipped")
    _replace_roadmap_field(lines, start, end, "Archive", {NULL, archive}, archive)
    return "".join(lines)


def record_shipment(repo: Path, archive: str, event: str) -> dict[str, object]:
    """Journal and atomically replace ROADMAP and STATE shipment metadata."""
    resolved = _repo_root(repo)
    project = _track_root(resolved, ".project")
    journal_path = _git_path(resolved, SHIPMENT_JOURNAL_NAME)
    with _state_lock(project):
        state, state_text, state_path = load_state(resolved)
        roadmap_path = project / "ROADMAP.md"
        charter_path = project / "CHARTER.md"
        if charter_path.is_symlink() or (
            charter_path.exists() and not charter_path.is_file()
        ):
            raise PipelineStateError("CHARTER.md must be a real file")
        if roadmap_path.is_symlink() or (
            roadmap_path.exists() and not roadmap_path.is_file()
        ):
            raise PipelineStateError("ROADMAP.md must be a real file")
        program = charter_path.is_file()
        if program and not roadmap_path.is_file():
            raise PipelineStateError("program shipment requires ROADMAP.md")
        if program or roadmap_path.is_file():
            roadmap_text: Optional[str] = _read_real_file(roadmap_path, "ROADMAP.md")
            target_roadmap: Optional[str] = _shipment_roadmap(roadmap_text, state, archive)
        else:
            roadmap_text = target_roadmap = None
        journal: Optional[dict[str, object]] = None
        event_date: Optional[str] = None
        if journal_path.exists() or journal_path.is_symlink():
            journal = _read_json(journal_path)
            # Reuse the journaled event date so a next-day resume still matches.
            recorded = re.match(
                r"- (\S+) — ",
                str(journal.get("state_after", "")).rstrip("\n").rsplit("\n", 1)[-1],
            )
            event_date = recorded.group(1) if recorded else None
        if (state.phase, state.status) == ("ship", "active"):
            _, after, target_state = _render_transition(
                state,
                state_text,
                {
                    "phase": "ship",
                    "status": "active",
                    "branch": state.branch,
                    "archive": archive,
                },
                {"phase": "shipped", "status": "done"},
                event,
                ".project",
                event_date,
            )
        elif (state.phase, state.status) == ("shipped", "done"):
            if " ".join(event.split()) not in {
                "archive preflight passed; shipment recorded",
                "archive preflight passed; shipment recorded; program complete",
            }:
                raise PipelineStateError("shipment recovery has an invalid event")
            after, target_state = state, state_text
        else:
            raise PipelineStateError("shipment requires ship/active or shipped/done")
        request = {
            "schema": SHIPMENT_SCHEMA,
            "repo": str(resolved),
            "archive": archive,
            "event": " ".join(event.split()),
        }
        if journal is not None:
            expected_keys = {
                *request,
                "roadmap_before",
                "roadmap_after",
                "state_before",
                "state_after",
            }
            if set(journal) != expected_keys or any(
                journal.get(key) != value for key, value in request.items()
            ):
                raise PipelineStateError("shipment journal does not match request")
            state_after = journal.get("state_after")
            roadmap_after = journal.get("roadmap_after")
            if (
                not isinstance(state_after, str)
                or state_after != target_state
                or roadmap_after != target_roadmap
            ):
                raise PipelineStateError("shipment journal target does not match derived metadata")
        else:
            journal = {
                **request,
                "roadmap_before": roadmap_text,
                "roadmap_after": target_roadmap,
                "state_before": state_text,
                "state_after": target_state,
            }
            _write_json(journal_path, journal)
        targets = [(state_path, "state_before", "state_after")]
        if target_roadmap is not None:
            targets.insert(0, (roadmap_path, "roadmap_before", "roadmap_after"))
        for path, before_key, after_key in targets:
            current = _read_real_file(path, path.name)
            desired = journal.get(after_key)
            if not isinstance(desired, str) or current not in {journal.get(before_key), desired}:
                raise PipelineStateError(f"shipment metadata drifted: {path.name}")
            if current != desired:
                _atomic_write(path, desired)
        journal_path.unlink()
    return {"schema": SHIPMENT_SCHEMA, "status": "recorded", "archive": archive, "state": after.json()}


def _render_transition(
    state: PipelineState,
    text: str,
    expected: Mapping[str, Optional[str]],
    changes: Mapping[str, Optional[str]],
    event: str,
    project_dir: str,
    event_date: Optional[str] = None,
    approval_kind: Optional[str] = None,
) -> tuple[dict[str, Optional[str]], PipelineState, str]:
    before = state.json()
    mismatches = {
        key: {"expected": value, "actual": before[key]}
        for key, value in expected.items()
        if before[key] != value
    }
    if mismatches:
        raise PipelineStateError(
            f"expected state does not match: {json.dumps(mismatches, sort_keys=True)}"
        )
    effective_changes = dict(changes)
    next_binding = (
        state.phase == "shipped"
        and state.status == "done"
        and effective_changes.get("phase", state.phase) in {"define", "inspect"}
        and effective_changes.get("status", state.status) == "active"
        and state.branch is not None
        and effective_changes.get("branch", state.branch) is not None
    )
    if next_binding:
        effective_changes["integration_default"] = state.integration_default
        effective_changes["integration"] = state.integration_default
        effective_changes["integration_source"] = "default"
    abandon = (
        state.phase == "build"
        and effective_changes.get("phase", state.phase) == "roadmap"
        and effective_changes.get("status", state.status) == "active"
        and state.archive is not None
        and effective_changes.get("archive", state.archive) is None
    )
    if abandon:
        effective_changes["integration_default"] = state.integration_default
        effective_changes["integration"] = state.integration_default
        effective_changes["integration_source"] = "default"
    rendered = _set_frontmatter(
        text,
        {
            key: NULL if value is None else value
            for key, value in effective_changes.items()
        },
    )
    next_phase = effective_changes.get("phase", state.phase)
    if not isinstance(next_phase, str):
        raise PipelineStateError("phase cannot be null")
    normalized_event = " ".join(event.split())
    rendered = _append_event(rendered, next_phase, normalized_event, event_date)
    after = _state_from_text(rendered)
    _validate_state_context(after, project_dir, "STATE.md")
    _validate_transition(
        state,
        after,
        normalized_event,
        project_dir,
        approval_kind,
    )
    return before, after, rendered


def _roadmap_sections(text: str) -> dict[str, tuple[str, int, int]]:
    try:
        return roadmap.strict_sections(text)
    except roadmap.RoadmapError as error:
        raise PipelineStateError(str(error)) from error

def _replace_roadmap_field(
    lines: list[str], start: int, end: int, field: str, expected: set[str], value: str,
) -> None:
    try:
        return roadmap.replace_field(lines, start, end, field, expected, value)
    except roadmap.RoadmapError as error:
        raise PipelineStateError(str(error)) from error

def _git_path(repo: Path, name: str) -> Path:
    value = _run_git(repo, "rev-parse", "--git-path", name).stdout.strip()
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def _read_json(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise PipelineStateError(f"transaction journal must be a real file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PipelineStateError(f"transaction journal is unreadable: {path}: {error}") from error
    if not isinstance(value, dict):
        raise PipelineStateError(f"transaction journal must contain an object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")


def _commit_message(subject: str, body_fields: Mapping[str, str]) -> str:
    body = "\n".join(f"{key}: {value}" for key, value in body_fields.items())
    return f"{subject}\n\n{body}\n"


def _validate_next_layout(next_root: Path, state: PipelineState) -> None:
    phase_index = LOOKAHEAD_PHASES.index(state.phase)
    for path in next_root.rglob("*"):
        relative = path.relative_to(next_root)
        if path.is_symlink():
            raise PipelineStateError(f"lookahead artifacts must not be symlinks: {path}")
        if path.is_dir():
            if (
                relative.parent != PurePosixPath(".")
                or path.name not in PROMOTION_TRACKS
            ):
                raise PipelineStateError(f"lookahead has unowned directory: {path}")
            continue
        if not path.is_file():
            raise PipelineStateError(f"lookahead has unsafe artifact: {path}")
        artifact = relative.as_posix()
        required_phase = LOOKAHEAD_FIXED_ARTIFACTS.get(artifact)
        if required_phase is None and LOOKAHEAD_EVIDENCE_RE.fullmatch(artifact):
            required_phase = "research"
        if (
            required_phase is None
            and relative.parent == PurePosixPath("tasks")
            and TASK_FILE_RE.fullmatch(path.name)
        ):
            required_phase = "plan"
        if (
            required_phase is None
            or LOOKAHEAD_PHASES.index(required_phase) > phase_index
        ):
            raise PipelineStateError(
                f"lookahead has artifact not owned by {state.phase}: {path}"
            )


def _worktree_changes(repo: Path) -> list[str]:
    commands = (
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    )
    return sorted(
        {
            path
            for arguments in commands
            for path in _run_git(repo, *arguments).stdout.split("\0")
            if path
        }
    )


def _field_arguments(parser: argparse.ArgumentParser, prefix: str) -> None:
    for field in STATE_FIELDS:
        parser.add_argument(f"--{prefix}-{field}", dest=f"{prefix}_{field}")


def _specified_fields(arguments: argparse.Namespace, prefix: str) -> dict[str, Optional[str]]:
    values: dict[str, Optional[str]] = {}
    for field in STATE_FIELDS:
        value = getattr(arguments, f"{prefix}_{field}")
        if value is not None:
            values[field] = None if value == NULL else value
    return values


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "route", "status", "prepare-build-recovery"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--repo", required=True, type=Path)
        subparser.add_argument("--project-dir", default=".project")
    transition = subparsers.add_parser("transition")
    transition.add_argument("--repo", required=True, type=Path)
    transition.add_argument("--project-dir", default=".project")
    transition.add_argument("--event", required=True)
    _field_arguments(transition, "expect")
    _field_arguments(transition, "set")
    approve = subparsers.add_parser("approve")
    approve.add_argument("--repo", required=True, type=Path)
    approve.add_argument("--kind", required=True, choices=CHECKPOINT_KINDS)
    approve.add_argument("--expected-head")
    approve.add_argument("--project-dir", default=".project")
    approve.add_argument("--milestone")
    approve.add_argument("--defer-checkpoint", action="store_true")
    approve.add_argument("--patch", action="store_true")
    resume = subparsers.add_parser("resume-checkpoint")
    resume.add_argument("--repo", required=True, type=Path)
    promote = subparsers.add_parser("promote-next")
    promote.add_argument("--repo", required=True, type=Path)
    promote.add_argument("--milestone", required=True)
    promote.add_argument("--branch", required=True)
    promote.add_argument("--integrate")
    promote.add_argument("--base")
    promote.add_argument("--landing")
    configure = subparsers.add_parser("configure-integration")
    configure.add_argument("--repo", required=True, type=Path)
    configure.add_argument("--project-dir", default=".project")
    configure.add_argument("--scope", required=True, choices=("default", "milestone"))
    configure.add_argument("--mode", required=True, choices=INTEGRATION_MODES)
    shipment = subparsers.add_parser("record-shipment")
    shipment.add_argument("--repo", required=True, type=Path)
    shipment.add_argument("--archive", required=True)
    shipment.add_argument("--event", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.command in {"approve", "resume-checkpoint"}:
        if __package__:
            from . import state_checkpoint
        else:
            import state_checkpoint
    elif args.command == "promote-next":
        if __package__:
            from . import state_promote
        else:
            import state_promote
    try:
        if args.command == "validate":
            result = validate_state(args.repo, args.project_dir)
        elif args.command == "route":
            result = route_state(args.repo, args.project_dir)
        elif args.command == "status":
            result = status_state(args.repo, args.project_dir)
        elif args.command == "prepare-build-recovery":
            if args.project_dir != ".project":
                raise PipelineStateError("build recovery requires the active track")
            result = _build_recovery().prepare(args.repo)
        elif args.command == "transition":
            result = transition_state(
                args.repo,
                _specified_fields(args, "expect"),
                _specified_fields(args, "set"),
                args.event,
                args.project_dir,
            )
        elif args.command == "approve" and (args.defer_checkpoint or args.patch):
            if args.expected_head is not None:
                raise PipelineStateError(
                    "--expected-head is not accepted with --defer-checkpoint or --patch"
                )
            result = state_checkpoint.defer_approval(
                args.repo,
                args.kind,
                args.project_dir,
                args.milestone,
                args.patch,
            )
        elif args.command == "approve":
            if args.expected_head is None:
                raise PipelineStateError(
                    "approve requires --expected-head unless --defer-checkpoint or --patch"
                )
            result = state_checkpoint.checkpoint_approval(
                args.repo,
                args.kind,
                args.expected_head,
                args.project_dir,
                args.milestone,
            )
        elif args.command == "resume-checkpoint":
            result = state_checkpoint.resume_checkpoint(args.repo)
        elif args.command == "promote-next":
            if args.integrate is not None and (
                args.base is not None or args.landing is not None
            ):
                raise PipelineStateError(
                    "promote-next cannot combine --integrate with --base or --landing"
                )
            base = args.integrate if args.integrate is not None else args.base
            landing = (
                args.integrate
                if args.integrate is not None
                else args.landing or base
            )
            if base is None:
                raise PipelineStateError(
                    "promote-next requires --base or legacy --integrate"
                )
            result = state_promote.promote_next(
                args.repo,
                args.milestone,
                args.branch,
                base,
                landing,
            )
        elif args.command == "record-shipment":
            result = record_shipment(args.repo, args.archive, args.event)
        elif args.command == "configure-integration":
            result = configure_integration(
                args.repo,
                args.scope,
                args.mode,
                args.project_dir,
            )
        else:  # pragma: no cover - argparse rejects unknown commands
            raise PipelineStateError(f"unknown command: {args.command}")
    except PipelineStateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
