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
import re
import shutil
import sys
from pathlib import Path
from typing import Optional, Sequence

def _load_pipeline_modules():
    try:
        import pipeline_git
        import pipeline_state
        return pipeline_git, pipeline_state
    except ImportError:
        pass
    try:
        from scripts import pipeline_git, pipeline_state
        return pipeline_git, pipeline_state
    except ImportError:
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        sys.path.insert(0, str(shared))
        import pipeline_git
        import pipeline_state
        return pipeline_git, pipeline_state


pipeline_git, pipeline_state = _load_pipeline_modules()
PLAN_APPROVAL_SUBJECT = pipeline_state.PLAN_APPROVAL_SUBJECT
PipelineStateError = pipeline_state.PipelineStateError
_commit_subject_body = pipeline_state._commit_subject_body
_optional_rev = pipeline_state._optional_rev
_repo_root = pipeline_state._repo_root
_run_git = pipeline_state._run_git
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
    path = (repo / relative).resolve()
    try:
        path.relative_to(repo.resolve())
    except ValueError as error:
        raise UndoError(f"refusing to delete a path outside the repo: {path}") from error
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
        _reset_to(resolved, expected_head)
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
