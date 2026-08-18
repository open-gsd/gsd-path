#!/usr/bin/env python3
"""Named checkouts for task isolation, verify sidecars, and task landing.

The orchestrator calls this helper instead of inventing git worktree, commit,
or cherry-pick commands. Every checkout this module creates is a named branch;
it never detaches HEAD.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, Optional, Sequence, Set

try:
    from pipeline_git import task_commit_body, task_commit_subject
except ImportError:  # pragma: no cover - package import used by tests
    from scripts.pipeline_git import task_commit_body, task_commit_subject


TASK_BRANCH_PREFIX = "gsd-path-task/"
VERIFY_BRANCH_PREFIX = "gsd-path-verify/"
TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class IsolationError(RuntimeError):
    """Raised when isolation, landing, or retirement cannot proceed."""


def run_git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )


def git_output(repo: Path, *arguments: str) -> str:
    result = run_git(repo, *arguments)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git command failed"
        raise IsolationError(detail)
    return result.stdout.strip()


def require_directory(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if not resolved.is_dir():
        raise IsolationError(f"{label} is not a directory: {resolved}")
    return resolved


def require_attached(repo: Path) -> str:
    branch = git_output(repo, "branch", "--show-current")
    if not branch:
        raise IsolationError(f"HEAD is detached in {repo}; expected a named branch")
    return branch


def require_commit(repo: Path, value: str) -> str:
    result = run_git(repo, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}")
    if result.returncode != 0:
        raise IsolationError(f"does not resolve to a commit: {value}")
    return result.stdout.strip()


def require_full_sha(value: str) -> str:
    if not re.fullmatch(r"[0-9a-f]{40}", value):
        raise IsolationError(f"base must be a full 40-character SHA: {value}")
    return value


def current_sha(repo: Path) -> str:
    return git_output(repo, "rev-parse", "HEAD")


def worktree_root(repo: Path) -> Path:
    return Path(git_output(repo, "rev-parse", "--show-toplevel")).resolve()


def common_git_dir(repo: Path) -> Path:
    raw = Path(git_output(repo, "rev-parse", "--git-common-dir"))
    if raw.is_absolute():
        return raw.resolve()
    return (repo / raw).resolve()


def sidecar_root(primary: Path, kind: str, name: str) -> Path:
    return (primary.parent / f"{primary.name}.gsd-path" / kind / name).resolve()


def validate_task_id(task_id: str) -> str:
    if not TASK_ID_RE.fullmatch(task_id):
        raise IsolationError(f"invalid task id: {task_id}")
    return task_id


def validate_name(name: str, label: str) -> str:
    if not NAME_RE.fullmatch(name):
        raise IsolationError(f"invalid {label}: {name}")
    return name


def task_branch_name(task_id: str) -> str:
    return f"{TASK_BRANCH_PREFIX}{validate_task_id(task_id)}"


def verify_branch_name(name: str) -> str:
    return f"{VERIFY_BRANCH_PREFIX}{validate_name(name, 'verify name')}"


def relative_posix(path: str) -> str:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise IsolationError(f"path must be relative without '..': {path}")
    return parsed.as_posix()


def create_named_worktree(primary: Path, branch: str, destination: Path, base: str) -> None:
    bound = require_attached(primary)
    if branch == bound:
        raise IsolationError(
            f"refusing to check out the bound branch {bound} in a second worktree"
        )
    existing_branch = run_git(primary, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}")
    if existing_branch.returncode == 0:
        raise IsolationError(f"branch already exists: {branch}")
    if destination.exists():
        raise IsolationError(f"worktree path already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = run_git(
        primary,
        "worktree",
        "add",
        "-b",
        branch,
        str(destination),
        base,
    )
    if result.returncode != 0:
        if destination.exists():
            run_git(primary, "worktree", "remove", "--force", str(destination))
        run_git(primary, "branch", "-D", branch)
        detail = (result.stderr or result.stdout).strip() or "git worktree add failed"
        raise IsolationError(detail)
    current = git_output(destination, "branch", "--show-current")
    if current != branch:
        run_git(primary, "worktree", "remove", "--force", str(destination))
        run_git(primary, "branch", "-D", branch)
        raise IsolationError(
            f"worktree HEAD is not {branch} (got {current or 'detached'})"
        )
    if git_output(destination, "rev-parse", "HEAD") != base:
        run_git(primary, "worktree", "remove", "--force", str(destination))
        run_git(primary, "branch", "-D", branch)
        raise IsolationError("new worktree is not at the recorded base")


def isolate_task(
    primary: Path,
    base: str,
    task_id: str,
    round_size: int,
) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_attached(primary)
    resolved_base = require_commit(primary, require_full_sha(base))
    validate_task_id(task_id)
    if round_size < 1:
        raise IsolationError("round-size must be >= 1")
    if round_size == 1:
        if current_sha(primary) != resolved_base:
            raise IsolationError("serial isolation requires primary HEAD to equal the recorded base")
        return {
            "base": resolved_base,
            "bound_branch": bound,
            "detached": False,
            "kind": "task",
            "mode": "serial",
            "task_branch": None,
            "worktree": str(primary),
        }
    branch = task_branch_name(task_id)
    destination = sidecar_root(primary, "task", task_id)
    create_named_worktree(primary, branch, destination, resolved_base)
    return {
        "base": resolved_base,
        "bound_branch": bound,
        "detached": False,
        "kind": "task",
        "mode": "parallel",
        "task_branch": branch,
        "worktree": str(destination),
    }


def isolate_verify(primary: Path, base: str, name: str) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_attached(primary)
    resolved_base = require_commit(primary, require_full_sha(base))
    branch = verify_branch_name(name)
    destination = sidecar_root(primary, "verify", name)
    create_named_worktree(primary, branch, destination, resolved_base)
    return {
        "base": resolved_base,
        "bound_branch": bound,
        "branch": branch,
        "detached": False,
        "kind": "verify",
        "mode": "sidecar",
        "worktree": str(destination),
    }


def _split_paths(block: str) -> Set[str]:
    return {line.strip() for line in block.splitlines() if line.strip()}


def uncommitted_paths(repo: Path) -> Set[str]:
    tracked = git_output(repo, "diff", "--name-only", "--relative", "HEAD")
    cached = git_output(repo, "diff", "--name-only", "--cached", "--relative")
    untracked = git_output(repo, "ls-files", "--others", "--exclude-standard")
    return _split_paths(tracked) | _split_paths(cached) | _split_paths(untracked)


def committed_paths_since(repo: Path, base: str) -> Set[str]:
    if current_sha(repo) == base:
        return set()
    return _split_paths(git_output(repo, "diff", "--name-only", "--relative", base, "HEAD"))


def commit_allowed_changes(
    repo: Path,
    base: str,
    subject: str,
    allowed: Set[str],
    body: str,
) -> str:
    require_attached(repo)
    pending = uncommitted_paths(repo)
    if not pending:
        raise IsolationError("no changes to land")
    since_base = committed_paths_since(repo, base) | pending
    unexpected = sorted(path for path in since_base if path not in allowed)
    if unexpected:
        raise IsolationError("unexpected paths: " + ", ".join(unexpected))
    reset = run_git(repo, "reset", "-q", "HEAD")
    if reset.returncode != 0:
        raise IsolationError("could not clear the index before landing")
    for path in sorted(pending):
        added = run_git(repo, "add", "-A", "--", path)
        if added.returncode != 0:
            raise IsolationError(f"could not stage {path}")
    staged = _split_paths(
        git_output(repo, "diff", "--cached", "--name-only", "--relative")
    )
    if staged != pending:
        raise IsolationError("staged paths do not match the uncommitted change set")
    committed = run_git(repo, "commit", "-q", "-m", subject, "-m", body)
    if committed.returncode != 0:
        raise IsolationError(
            (committed.stderr or committed.stdout).strip() or "commit failed"
        )
    return current_sha(repo)


def land(
    primary: Path,
    source: Path,
    base: str,
    task_id: str,
    title: str,
    task_file: str,
    allow_paths: Sequence[str],
) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    source = require_directory(source, "source worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    if worktree_root(source) != source:
        raise IsolationError(f"source is not its Git root: {source}")
    if common_git_dir(primary) != common_git_dir(source):
        raise IsolationError("source worktree belongs to another repository")
    bound = require_attached(primary)
    source_branch = require_attached(source)
    resolved_base = require_commit(primary, require_full_sha(base))
    validate_task_id(task_id)
    try:
        subject = task_commit_subject(task_id, title)
    except ValueError as error:
        raise IsolationError(str(error)) from error
    allowed = {relative_posix(task_file)}
    for path in allow_paths:
        allowed.add(relative_posix(path))
    serial = source == primary
    if serial:
        if source_branch != bound:
            raise IsolationError("serial landing requires the bound branch")
        pending = uncommitted_paths(primary)
        body = task_commit_body(relative_posix(task_file), pending)
        commit = commit_allowed_changes(primary, resolved_base, subject, allowed, body)
        return {
            "bound_branch": bound,
            "commit": commit,
            "mode": "serial",
            "source_commit": commit,
            "subject": subject,
        }
    expected_branch = task_branch_name(task_id)
    if source_branch != expected_branch:
        raise IsolationError(
            f"source branch is {source_branch}, expected {expected_branch}"
        )
    if require_attached(primary) != bound:
        raise IsolationError("primary left the bound branch")
    status = git_output(primary, "status", "--porcelain", "--untracked-files=all")
    if status:
        raise IsolationError("primary worktree is dirty; refusing to cherry-pick")
    if uncommitted_paths(source):
        pending = uncommitted_paths(source)
        body = task_commit_body(relative_posix(task_file), pending)
        source_commit = commit_allowed_changes(
            source, resolved_base, subject, allowed, body
        )
    else:
        source_commit = current_sha(source)
        if source_commit == resolved_base:
            raise IsolationError("no changes to land")
        source_subject = git_output(source, "log", "-1", "--format=%s", source_commit)
        if source_subject != subject:
            raise IsolationError(
                f"source commit subject is {source_subject!r}, expected {subject!r}"
            )
        changed_paths = committed_paths_since(source, resolved_base)
        expected_body = task_commit_body(
            relative_posix(task_file), changed_paths
        ).strip()
        source_body = git_output(source, "log", "-1", "--format=%b", source_commit)
        if source_body != expected_body:
            raise IsolationError("source commit body does not match expected task fields")
    picked = run_git(primary, "cherry-pick", source_commit)
    if picked.returncode != 0:
        run_git(primary, "cherry-pick", "--abort")
        if git_output(primary, "status", "--porcelain"):
            raise IsolationError("cherry-pick failed and primary is not clean after abort")
        if require_attached(primary) != bound:
            raise IsolationError("cherry-pick failed and primary is no longer on the bound branch")
        detail = (picked.stderr or picked.stdout).strip() or "cherry-pick conflict"
        raise IsolationError(f"conflict: {detail}")
    return {
        "bound_branch": bound,
        "commit": current_sha(primary),
        "mode": "parallel",
        "source_commit": source_commit,
        "subject": subject,
    }


def retire(
    primary: Path,
    worktree: Path,
    branch: Optional[str],
    force: bool,
) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    bound = require_attached(primary)
    resolved_worktree = worktree.resolve()
    if resolved_worktree == primary:
        if branch and branch == bound:
            raise IsolationError("refusing to retire the bound branch")
        return {
            "bound_branch": bound,
            "branch": None,
            "retired": False,
            "reason": "serial",
            "worktree": str(primary),
        }
    if not resolved_worktree.exists():
        if branch:
            existing = run_git(
                primary, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
            )
            if existing.returncode == 0:
                if branch == bound:
                    raise IsolationError("refusing to delete the bound branch")
                deleted = run_git(primary, "branch", "-d" if not force else "-D", branch)
                if deleted.returncode != 0:
                    raise IsolationError(
                        (deleted.stderr or deleted.stdout).strip()
                        or f"could not delete {branch}"
                    )
        return {
            "bound_branch": bound,
            "branch": branch,
            "retired": True,
            "reason": "already-absent",
            "worktree": str(resolved_worktree),
        }
    if worktree_root(resolved_worktree) != resolved_worktree:
        raise IsolationError(f"worktree is not its Git root: {resolved_worktree}")
    if common_git_dir(primary) != common_git_dir(resolved_worktree):
        raise IsolationError("worktree belongs to another repository")
    current = require_attached(resolved_worktree)
    if current == bound:
        raise IsolationError("refusing to retire a worktree on the bound branch")
    if branch and current != branch:
        raise IsolationError(f"worktree is on {current}, expected {branch}")
    if current.startswith(TASK_BRANCH_PREFIX) or current.startswith(VERIFY_BRANCH_PREFIX):
        retire_branch = current
    else:
        raise IsolationError(f"refusing to retire unrecognized branch {current}")
    if not force:
        dirty = git_output(
            resolved_worktree, "status", "--porcelain", "--untracked-files=all"
        )
        if dirty:
            raise IsolationError("worktree is dirty; pass --force only from the retry-retirement path")
    remove = run_git(
        primary,
        "worktree",
        "remove",
        *(("--force",) if force else ()),
        str(resolved_worktree),
    )
    if remove.returncode != 0:
        raise IsolationError(
            (remove.stderr or remove.stdout).strip() or "git worktree remove failed"
        )
    deleted = run_git(primary, "branch", "-D", retire_branch)
    if deleted.returncode != 0:
        raise IsolationError(
            (deleted.stderr or deleted.stdout).strip() or f"could not delete {retire_branch}"
        )
    return {
        "bound_branch": bound,
        "branch": retire_branch,
        "retired": True,
        "reason": "removed",
        "worktree": str(resolved_worktree),
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    subparsers = argument_parser.add_subparsers(dest="command", required=True)

    isolate_task_parser = subparsers.add_parser(
        "isolate-task", help="create or reuse a named task checkout"
    )
    isolate_task_parser.add_argument("--repo", type=Path, required=True)
    isolate_task_parser.add_argument("--base", required=True)
    isolate_task_parser.add_argument("--task-id", required=True)
    isolate_task_parser.add_argument("--round-size", type=int, required=True)

    isolate_verify_parser = subparsers.add_parser(
        "isolate-verify", help="create a named verify sidecar"
    )
    isolate_verify_parser.add_argument("--repo", type=Path, required=True)
    isolate_verify_parser.add_argument("--base", required=True)
    isolate_verify_parser.add_argument("--name", required=True)

    land_parser = subparsers.add_parser("land", help="commit a task onto the bound branch")
    land_parser.add_argument("--repo", type=Path, required=True)
    land_parser.add_argument("--source", type=Path, required=True)
    land_parser.add_argument("--base", required=True)
    land_parser.add_argument("--task-id", required=True)
    land_parser.add_argument("--title", required=True)
    land_parser.add_argument("--task-file", required=True)
    land_parser.add_argument("--allow-path", action="append", default=[], dest="allow_paths")

    retire_parser = subparsers.add_parser("retire", help="remove a named sidecar checkout")
    retire_parser.add_argument("--repo", type=Path, required=True)
    retire_parser.add_argument("--worktree", type=Path, required=True)
    retire_parser.add_argument("--branch")
    retire_parser.add_argument("--force", action="store_true")
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "isolate-task":
            result = isolate_task(
                arguments.repo,
                arguments.base,
                arguments.task_id,
                arguments.round_size,
            )
        elif arguments.command == "isolate-verify":
            result = isolate_verify(arguments.repo, arguments.base, arguments.name)
        elif arguments.command == "land":
            result = land(
                arguments.repo,
                arguments.source,
                arguments.base,
                arguments.task_id,
                arguments.title,
                arguments.task_file,
                arguments.allow_paths,
            )
        else:
            result = retire(
                arguments.repo,
                arguments.worktree,
                arguments.branch,
                arguments.force,
            )
    except IsolationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
