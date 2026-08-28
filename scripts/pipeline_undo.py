#!/usr/bin/env python3
"""Helper-owned undo for unpublished GSD Path pipeline commits and worktrees.

Preview is read-only. Apply mutates only after the caller supplies the exact
HEAD SHA returned by preview. The helper never force-pushes, never rewrites a
commit that is an ancestor of origin/main, and never invents a git reset the
model did not ask this command to perform.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

def _load_pipeline_modules():
    try:
        import archive_milestone
        import isolation
        import pipeline_git
        import pipeline_state
        return archive_milestone, isolation, pipeline_git, pipeline_state
    except ImportError:
        pass
    try:
        from scripts import archive_milestone, isolation, pipeline_git, pipeline_state
        return archive_milestone, isolation, pipeline_git, pipeline_state
    except ImportError:
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        sys.path.insert(0, str(shared))
        import archive_milestone
        import isolation
        import pipeline_git
        import pipeline_state
        return archive_milestone, isolation, pipeline_git, pipeline_state


archive_milestone, isolation, pipeline_git, pipeline_state = _load_pipeline_modules()
ArchiveError = archive_milestone.ArchiveError
IsolationError = isolation.IsolationError
PLAN_APPROVAL_SUBJECT = pipeline_state.PLAN_APPROVAL_SUBJECT
PipelineStateError = pipeline_state.PipelineStateError
_activate_roadmap_milestone = pipeline_state._activate_roadmap_milestone
_approval_details = pipeline_state._approval_details
_commit_subject_body = pipeline_state._commit_subject_body
_optional_rev = pipeline_state._optional_rev
_render_transition = pipeline_state._render_transition
_repo_root = pipeline_state._repo_root
_run_git = pipeline_state._run_git
_state_from_text = pipeline_state._state_from_text
load_state = pipeline_state.load_state
status_state = pipeline_state.status_state
is_bound_branch = pipeline_git.is_bound_branch
is_ship_subject = pipeline_git.is_ship_subject


UNDO_SCHEMA = "gsd-path/undo/v1"
ROADMAP_APPROVAL_SUBJECT = "roadmap: program roadmap approved"
TASK_SUBJECT_RE = re.compile(r"^(T\d{3,}): .+")
KINDS = ("checkpoint", "task", "uncommitted-archive", "lookahead")
PROMOTION_PREFIX = "router: promote lookahead milestone "
ABANDON_PREFIX = "build: abandon milestone "
INTEGRATE_PREFIX = "integrate: "


class UndoError(RuntimeError):
    """Raised when undo cannot be proven or applied safely."""


def _normalize_archive(value: str) -> str:
    return value.rstrip("/")


def _archive_in_head(repo: Path, archive: str) -> bool:
    relative = _normalize_archive(archive)
    listed = _run_git(
        repo,
        "ls-tree",
        "-r",
        "--name-only",
        "HEAD",
        "--",
        relative,
        f"{relative}/",
        check=False,
    )
    return listed.returncode == 0 and bool(listed.stdout.strip())


def _parent_sha(repo: Path, head: str) -> Optional[str]:
    result = _run_git(repo, "rev-parse", "--verify", f"{head}^", check=False)
    sha = result.stdout.strip()
    return sha if result.returncode == 0 and sha else None


def _product_dirty(dirty: Sequence[str]) -> list[str]:
    return [path for path in dirty if not path.startswith(".project/")]


def _active_journals(journals: dict[str, Optional[str]]) -> dict[str, str]:
    return {key: value for key, value in journals.items() if value}


def _blocked(reasons: Sequence[str]) -> dict[str, object]:
    return {
        "kind": None,
        "head": None,
        "parent": None,
        "subject": None,
        "effects": [],
        "blocked": list(reasons),
    }


def _git_text(repo: Path, revision: str, relative: str) -> str:
    result = _run_git(repo, "show", f"{revision}:{relative}", check=False)
    if result.returncode != 0:
        raise UndoError(f"missing {relative} in {revision}")
    return result.stdout


def _checkpoint_proof_error(
    repo: Path, head: str, parent: str, subject: str
) -> Optional[str]:
    changed = set(
        _run_git(
            repo,
            "diff-tree",
            "--no-commit-id",
            "--name-only",
            "-r",
            head,
        ).stdout.splitlines()
    )
    if not changed or any(not path.startswith(".project/") for path in changed):
        return "checkpoint changes paths outside .project"
    state_paths = [
        path
        for path in (".project/STATE.md", ".project/next/STATE.md")
        if path in changed
    ]
    if len(state_paths) != 1:
        return "checkpoint must change exactly one owned STATE.md"
    state_path = state_paths[0]
    project_dir = str(PurePosixPath(state_path).parent)
    try:
        before_text = _git_text(repo, parent, state_path)
        after_text = _git_text(repo, head, state_path)
        before = _state_from_text(before_text, f"{parent}:{state_path}")
        after = _state_from_text(after_text, f"{head}:{state_path}")
        body = _commit_subject_body(repo, head)[1].strip()
        if subject == PLAN_APPROVAL_SUBJECT:
            kind = "plan"
            selected = None
        elif subject == ROADMAP_APPROVAL_SUBJECT:
            kind = "roadmap"
            selected = after.milestone
        else:
            return "checkpoint subject is not canonical"
        changes, event, expected_subject, expected_body = _approval_details(
            kind, before, selected
        )
        if subject != expected_subject or body != expected_body:
            return "checkpoint message does not match its state transition"
        added_dates = re.findall(
            rf"^- (\d{{4}}-\d{{2}}-\d{{2}}) — {kind} — {re.escape(event)}$",
            after_text,
            re.MULTILINE,
        )
        if not added_dates:
            return "checkpoint state lacks its canonical event"
        expected = {
            "phase": before.phase,
            "status": before.status,
            "milestone": before.milestone,
            "branch": before.branch,
            "archive": before.archive,
        }
        _, expected_state, rendered = _render_transition(
            before,
            before_text,
            expected,
            changes,
            event,
            project_dir,
            added_dates[-1],
            kind,
        )
        if rendered != after_text or expected_state != after:
            return "checkpoint STATE.md is not the canonical approval result"
        if kind == "roadmap":
            roadmap_before = _git_text(repo, parent, ".project/ROADMAP.md")
            roadmap_after = _git_text(repo, head, ".project/ROADMAP.md")
            if roadmap_after != _activate_roadmap_milestone(
                roadmap_before, str(selected)
            ):
                return "checkpoint ROADMAP.md is not the canonical approval result"
    except (PipelineStateError, UndoError) as error:
        return str(error)
    return None


def _task_proof_error(repo: Path, head: str) -> Optional[str]:
    try:
        recovered = isolation.recover(repo, Path(".project/tasks"))
    except IsolationError as error:
        return str(error)
    matches = [
        task
        for task in recovered.get("tasks", [])
        if task.get("verdict") == "recovered" and task.get("commit") == head
    ]
    if recovered.get("verdict") != "ok" or len(matches) != 1:
        return "HEAD is not the uniquely proven last task landing"
    return None


def _discussion_extension(repo: Path, archive: str) -> Optional[dict[str, bytes]]:
    active = repo / ".project" / "discuss"
    if not active.exists() and not active.is_symlink():
        return None
    archived = repo / archive / "discuss"
    try:
        archive_milestone.require_append_only_discussion(active, archived)
    except (ArchiveError, OSError) as error:
        raise UndoError(f"discussion records cannot be preserved: {error}") from error
    return {
        name: (active / name).read_bytes()
        for name in archive_milestone.DISCUSSION_FILES
    }


def _restore_discussion(repo: Path, files: dict[str, bytes]) -> None:
    discussion = repo / ".project" / "discuss"
    if discussion.is_symlink() or (discussion.exists() and not discussion.is_dir()):
        raise UndoError("discussion restore destination is unsafe")
    discussion.mkdir(exist_ok=True)
    for name, data in files.items():
        temporary_name: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(dir=discussion, delete=False) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_name = handle.name
            os.replace(temporary_name, discussion / name)
            temporary_name = None
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
    try:
        archive_milestone.validate_discussion_directory(discussion)
    except ArchiveError as error:
        raise UndoError(f"restored discussion records are invalid: {error}") from error


def classify_undo(repo: Path) -> dict[str, object]:
    resolved = _repo_root(repo)
    status = status_state(resolved)
    state_fields = status["state"]
    git = status["git"]
    head = git.get("head")
    branch = git.get("branch")
    dirty = list(git.get("dirty") or [])
    subject = str(git.get("subject") or "")
    journals = _active_journals(status["journals"])
    recorded_branch = state_fields.get("branch")
    archive = state_fields.get("archive")

    if not head:
        return _blocked(["HEAD has no commit"])
    if recorded_branch is None or not is_bound_branch(str(recorded_branch)):
        return _blocked(["undo requires STATE.branch to be a bound gsd-path/M00N branch"])
    if branch != recorded_branch:
        return _blocked(
            [f"current branch {branch or '<detached>'} != STATE.branch {recorded_branch}"]
        )
    if journals:
        names = ", ".join(sorted(journals))
        return _blocked(
            [f"an in-progress helper journal exists ({names}); resume that transaction first"]
        )
    if git.get("ancestor_of_origin_main"):
        return _blocked(["HEAD is an ancestor of origin/main; undo would rewrite shipped history"])

    product = _product_dirty(dirty)
    if product:
        return _blocked(
            ["worktree has changes outside .project/: " + ", ".join(product)]
        )

    if archive:
        archive_path = _normalize_archive(str(archive))
        if not _archive_in_head(resolved, archive_path):
            try:
                _discussion_extension(resolved, archive_path)
            except UndoError as error:
                return _blocked([str(error)])
            return {
                "kind": "uncommitted-archive",
                "head": head,
                "parent": head,
                "subject": subject,
                "archive": archive_path,
                "effects": [
                    "restore tracked .project/ files to HEAD",
                    f"delete untracked {archive_path}",
                ],
                "blocked": [],
            }

    next_dir = resolved / ".project" / "next"
    next_tracked = _run_git(
        resolved,
        "ls-files",
        "--",
        ".project/next",
        check=False,
    ).stdout.splitlines()
    if (next_dir.exists() or next_dir.is_symlink()) and not any(
        line.strip() for line in next_tracked
    ):
        extra = [path for path in dirty if path != ".project/next" and not path.startswith(".project/next/")]
        if extra:
            return _blocked(
                ["lookahead discard requires a clean worktree except .project/next/"]
            )
        return {
            "kind": "lookahead",
            "head": head,
            "parent": head,
            "subject": subject,
            "effects": ["delete untracked .project/next/"],
            "blocked": [],
        }

    if dirty:
        return _blocked(["worktree is dirty; restore or commit before undoing HEAD"])

    _, body = _commit_subject_body(resolved, head)
    parent = _parent_sha(resolved, head)
    if parent is None:
        return _blocked(["HEAD has no parent; undo refuses to delete the only commit"])
    if git.get("published"):
        return _blocked(
            [
                f"HEAD is published on origin/{recorded_branch}; undo never force-pushes"
            ]
        )

    if subject in {PLAN_APPROVAL_SUBJECT, ROADMAP_APPROVAL_SUBJECT}:
        kind = "plan" if subject == PLAN_APPROVAL_SUBJECT else "roadmap"
        proof_error = _checkpoint_proof_error(resolved, head, parent, subject)
        if proof_error:
            return _blocked([f"checkpoint ownership is unproven: {proof_error}"])
        return {
            "kind": "checkpoint",
            "checkpoint": kind,
            "head": head,
            "parent": parent,
            "subject": subject,
            "effects": [
                f"reset {recorded_branch} to {parent}",
                f"STATE returns to {kind}/active",
            ],
            "blocked": [],
        }

    if TASK_SUBJECT_RE.fullmatch(subject) and body.lstrip().startswith("Task:"):
        proof_error = _task_proof_error(resolved, head)
        if proof_error:
            return _blocked([f"task landing ownership is unproven: {proof_error}"])
        return {
            "kind": "task",
            "head": head,
            "parent": parent,
            "subject": subject,
            "effects": [
                f"reset {recorded_branch} to {parent}",
                "the last task landing commit is dropped",
            ],
            "blocked": [],
        }

    slug = state_fields.get("milestone") or ""
    archive_name = ""
    if archive:
        archive_name = Path(_normalize_archive(str(archive))).name
    if archive_name and is_ship_subject(subject, archive_name):
        return _blocked(
            ["HEAD is a ship commit; finish integration with $gsd-path-ship"]
        )
    if subject.startswith(PROMOTION_PREFIX):
        return _blocked(["HEAD is a lookahead promotion commit; undo refuses it"])
    if subject.startswith(ABANDON_PREFIX):
        return _blocked(["HEAD is a milestone-abandon commit; abandoned entries are immutable"])
    if subject.startswith(INTEGRATE_PREFIX):
        return _blocked(["HEAD is an integration merge; undo never rewrites main"])
    return _blocked([f"HEAD is not an undoable pipeline commit: {subject or '<empty>'}"])


def preview(repo: Path) -> dict[str, object]:
    resolved = _repo_root(repo)
    target = classify_undo(resolved)
    state, _, path = load_state(resolved)
    return {
        "schema": UNDO_SCHEMA,
        "status": "preview",
        "path": str(path),
        "state": state.json(),
        "target": target,
        "apply": None
        if target.get("kind") is None
        else {
            "command": "apply",
            "kind": target["kind"],
            "expected_head": target["head"],
        },
    }


def _reset_to(repo: Path, revision: str) -> None:
    result = _run_git(repo, "reset", "--hard", revision, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git reset failed"
        raise UndoError(f"git reset --hard {revision} failed: {detail}")


def _remove_untracked_tree(repo: Path, relative: str) -> None:
    normalized = PurePosixPath(relative)
    if normalized.is_absolute() or ".." in normalized.parts or not normalized.parts:
        raise UndoError(f"refusing to delete an invalid path: {relative}")
    current = repo
    for part in normalized.parts[:-1]:
        current /= part
        if current.is_symlink():
            raise UndoError(f"refusing to delete through a symlink parent: {relative}")
    path = repo.joinpath(*normalized.parts)
    if path.is_symlink():
        path.unlink()
        return
    if path.is_dir():
        shutil.rmtree(path)
        return
    if path.exists():
        path.unlink()


def apply_undo(repo: Path, kind: str, expected_head: str) -> dict[str, object]:
    if kind not in KINDS:
        raise UndoError(f"unsupported undo kind: {kind}")
    resolved = _repo_root(repo)
    previewed = preview(resolved)
    target = previewed["target"]
    if target.get("kind") is None:
        raise UndoError("; ".join(target.get("blocked") or ["undo is blocked"]))
    if target["kind"] != kind:
        raise UndoError(
            f"preview kind is {target['kind']}, not {kind}; rerun preview"
        )
    if target["head"] != expected_head:
        raise UndoError("expected-head does not match current HEAD from preview")
    head = _optional_rev(resolved, "HEAD")
    if head != expected_head:
        raise UndoError("HEAD moved after preview; rerun preview")

    if kind in {"checkpoint", "task"}:
        parent = target["parent"]
        if not parent:
            raise UndoError("parent revision is not a safe reset target")
        _reset_to(resolved, str(parent))
    elif kind == "uncommitted-archive":
        archive = str(target["archive"])
        discussion = _discussion_extension(resolved, archive)
        _reset_to(resolved, expected_head)
        if discussion is not None:
            _restore_discussion(resolved, discussion)
        if not _archive_in_head(resolved, archive):
            _remove_untracked_tree(resolved, archive)
    else:
        _remove_untracked_tree(resolved, ".project/next")

    after = preview(resolved)
    return {
        "schema": UNDO_SCHEMA,
        "status": "applied",
        "kind": kind,
        "head_before": expected_head,
        "head_after": after["target"].get("head") or _optional_rev(resolved, "HEAD"),
        "state": after["state"],
        "remaining": after["target"],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    preview_parser = subparsers.add_parser("preview")
    preview_parser.add_argument("--repo", required=True, type=Path)
    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--repo", required=True, type=Path)
    apply_parser.add_argument("--kind", required=True, choices=KINDS)
    apply_parser.add_argument("--expected-head", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "preview":
            result = preview(args.repo)
        elif args.command == "apply":
            result = apply_undo(args.repo, args.kind, args.expected_head)
        else:  # pragma: no cover - argparse rejects unknown commands
            raise UndoError(f"unknown command: {args.command}")
    except (UndoError, PipelineStateError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
