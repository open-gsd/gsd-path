#!/usr/bin/env python3
"""Deterministic GSD Path branch names and pipeline commit messages.

Bound work lives on `gsd-path/M00N` for that milestone. The required remote
default `main` stays a separate trunk. Ship merges the bound branch onto main;
the next milestone binds a new unused `gsd-path/M00N`.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence


ARCHIVE_NAME_RE = re.compile(r"^(\d{3,})-([a-z0-9][a-z0-9-]*)$")
BOUND_BRANCH_RE = re.compile(r"^gsd-path/M(\d{3,})$")
MILESTONE_ID_RE = re.compile(r"^M(\d{3,})$")
ROADMAP_HEADING_RE = re.compile(r"^### (M\d{3,}) — .+$")
ROADMAP_STATUS_RE = re.compile(r"^Status:\s*(\S+)", re.MULTILINE)

LEGACY_SHIP_PREFIX = "ship: "
LEGACY_INTEGRATE_PREFIX = "integrate: "


class PipelineGitError(ValueError):
    """Raised when a milestone id, archive name, or branch cannot be derived."""


def milestone_id(number: int) -> str:
    if number < 1:
        raise PipelineGitError(f"milestone number must be >= 1, got {number}")
    return f"M{number:03d}"


def milestone_number(token: str) -> int:
    bound = BOUND_BRANCH_RE.fullmatch(token)
    if bound:
        return int(bound.group(1))
    milestone = MILESTONE_ID_RE.fullmatch(token)
    if milestone:
        return int(milestone.group(1))
    archive = ARCHIVE_NAME_RE.fullmatch(token)
    if archive:
        return int(archive.group(1))
    raise PipelineGitError(f"not a milestone id, bound branch, or archive name: {token}")


def bound_branch_name(number: int) -> str:
    return f"gsd-path/{milestone_id(number)}"


def is_bound_branch(name: str) -> bool:
    return BOUND_BRANCH_RE.fullmatch(name) is not None


def archive_slug(archive_name: str) -> str:
    match = ARCHIVE_NAME_RE.fullmatch(archive_name)
    if not match:
        raise PipelineGitError(f"invalid archive name: {archive_name}")
    return match.group(2)


def ship_subject(archive_name: str) -> str:
    number = milestone_number(archive_name)
    return f"ship: {milestone_id(number)} — {archive_slug(archive_name)}"


def integrate_subject(archive_name: str, default_branch: str) -> str:
    if not default_branch or default_branch.startswith("origin/"):
        raise PipelineGitError(f"default branch is invalid: {default_branch}")
    number = milestone_number(archive_name)
    return (
        f"integrate: {milestone_id(number)} — "
        f"merge {bound_branch_name(number)} into {default_branch}"
    )


def legacy_ship_subject(archive_name: str) -> str:
    return f"{LEGACY_SHIP_PREFIX}{archive_name}"


def legacy_integrate_subject(archive_name: str) -> str:
    return f"{LEGACY_INTEGRATE_PREFIX}{archive_name}"


def is_ship_subject(subject: str, archive_name: str) -> bool:
    return subject in {ship_subject(archive_name), legacy_ship_subject(archive_name)}


def is_integrate_subject(subject: str, archive_name: str, default_branch: str) -> bool:
    return subject in {
        integrate_subject(archive_name, default_branch),
        legacy_integrate_subject(archive_name),
    }


def ship_commit_body(archive_path: str, reviewed_head: str) -> str:
    return f"Archive: {archive_path}\nReviewed-HEAD: {reviewed_head}\n"


def integrate_commit_body(
    archive_path: str,
    ship_commit: str,
    default_branch: str,
    bound_branch: str,
) -> str:
    return (
        f"Archive: {archive_path}\n"
        f"Ship: {ship_commit}\n"
        f"Default: {default_branch}\n"
        f"Branch: {bound_branch}\n"
    )


def task_commit_subject(task_id: str, title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise PipelineGitError("title is empty")
    return f"{task_id}: {cleaned}"


def task_commit_body(task_file: str, paths: Sequence[str]) -> str:
    ordered = sorted(paths)
    lines = [f"Task: {task_file}", "Files:"]
    if ordered:
        lines.extend(f"- {path}" for path in ordered)
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def pipeline_commit_body(fields: Iterable[tuple[str, str]]) -> str:
    lines = [f"{name}: {value}" for name, value in fields if value]
    if not lines:
        raise PipelineGitError("pipeline commit body has no fields")
    return "\n".join(lines) + "\n"


def default_branch_name(remote_default: str) -> str:
    if remote_default.startswith("origin/"):
        return remote_default.removeprefix("origin/")
    return remote_default


def next_milestone_number(
    archive_names: Sequence[str],
    active_roadmap_id: Optional[str] = None,
) -> int:
    if active_roadmap_id:
        return milestone_number(active_roadmap_id)
    numbers = [milestone_number(name) for name in archive_names]
    if not numbers:
        return 1
    return max(numbers) + 1


def active_roadmap_milestone_id(roadmap_text: str) -> Optional[str]:
    current_id = None
    for line in roadmap_text.splitlines():
        heading = ROADMAP_HEADING_RE.fullmatch(line.strip())
        if heading:
            current_id = heading.group(1)
            continue
        if current_id is None:
            continue
        status = ROADMAP_STATUS_RE.match(line.strip())
        if status:
            if status.group(1) == "active":
                return current_id
            current_id = None
    return None


def _run_git(
    repo: Path,
    *args: str,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
    )
    if check and result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineGitError(f"git {' '.join(args)} failed: {detail}")
    return result


def _ref_exists(repo: Path, ref: str) -> bool:
    result = _run_git(
        repo,
        "show-ref",
        "--verify",
        "--quiet",
        ref,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise PipelineGitError(f"could not inspect bound branch: {ref}")
    return result.returncode == 0


def bind_next_milestone_branch(
    repo: Path,
    branch: str,
    previous_branch: str,
    ship: str,
    remote_default: str,
    base: str,
) -> dict[str, str]:
    """Move a clean primary worktree onto a new bound branch after integration."""
    if not is_bound_branch(branch):
        raise PipelineGitError(f"invalid bound branch: {branch}")
    if not is_bound_branch(previous_branch):
        raise PipelineGitError(f"invalid previous bound branch: {previous_branch}")
    if milestone_number(branch) <= milestone_number(previous_branch):
        raise PipelineGitError(f"next branch {branch} must follow {previous_branch}")
    if remote_default != "origin/main":
        raise PipelineGitError(f"remote default must be origin/main, got {remote_default}")

    default_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{remote_default}^{{commit}}",
    ).stdout.strip()
    base_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{base}^{{commit}}",
    ).stdout.strip()
    if base != base_sha:
        raise PipelineGitError(f"base must be the full commit SHA: {base}")
    if base_sha != default_sha:
        raise PipelineGitError(
            f"validated base is stale: {base_sha} != {remote_default} {default_sha}"
        )
    previous_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"refs/heads/{previous_branch}^{{commit}}",
    ).stdout.strip()
    ship_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{ship}^{{commit}}",
    ).stdout.strip()
    if ship != ship_sha:
        raise PipelineGitError(f"ship must be the full commit SHA: {ship}")
    if previous_sha != ship_sha:
        raise PipelineGitError(
            f"previous branch moved after ship: {previous_sha} != {ship_sha}"
        )
    integrated = _run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        previous_sha,
        base_sha,
        check=False,
    )
    if integrated.returncode == 1:
        raise PipelineGitError(f"{previous_branch} is not integrated into {remote_default}")
    if integrated.returncode != 0:
        detail = integrated.stderr.strip() or integrated.stdout.strip()
        raise PipelineGitError(f"could not verify integrated branch: {detail}")

    symbolic_branch = _run_git(
        repo,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
    )
    if symbolic_branch.returncode != 0:
        raise PipelineGitError("primary worktree must be on a named branch")
    current = symbolic_branch.stdout.strip()
    remote_branch_ref = f"refs/remotes/origin/{branch}"
    if _ref_exists(repo, remote_branch_ref):
        raise PipelineGitError(f"bound branch already exists: {remote_branch_ref}")

    if current == branch:
        head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
        if head != base_sha:
            raise PipelineGitError(
                f"existing {branch} is not at {remote_default}: {head} != {default_sha}"
            )
        return {
            "base": default_sha,
            "branch": branch,
            "previous_branch": previous_branch,
        }

    if current != previous_branch:
        raise PipelineGitError(
            f"current branch {current} does not match previous branch {previous_branch}"
        )
    if _run_git(repo, "status", "--porcelain").stdout:
        raise PipelineGitError("primary worktree is not clean")

    local_branch_ref = f"refs/heads/{branch}"
    if _ref_exists(repo, local_branch_ref):
        raise PipelineGitError(f"bound branch already exists: {local_branch_ref}")

    _run_git(repo, "switch", "--no-track", "-c", branch, base_sha)
    return {
        "base": default_sha,
        "branch": branch,
        "previous_branch": previous_branch,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bind_next = subparsers.add_parser(
        "bind-next",
        help="bind the next milestone branch at the integrated remote default",
    )
    bind_next.add_argument("--repo", required=True, type=Path)
    bind_next.add_argument("--branch", required=True)
    bind_next.add_argument("--previous-branch", required=True)
    bind_next.add_argument("--ship", required=True)
    bind_next.add_argument("--remote-default", required=True)
    bind_next.add_argument("--base", required=True)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "bind-next":
            result = bind_next_milestone_branch(
                args.repo,
                args.branch,
                args.previous_branch,
                args.ship,
                args.remote_default,
                args.base,
            )
        else:  # pragma: no cover - argparse rejects unknown commands
            raise PipelineGitError(f"unknown command: {args.command}")
    except PipelineGitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
