#!/usr/bin/env python3
# gsd-path project runtime
"""Select and compare GSD Path lookahead tracks."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

if __package__:
    from . import _common, archive_milestone, detect_project
    from .roadmap import (
        RoadmapError as LookaheadError,
        NoEligibleMilestone as NoEligibleLookahead,
        roadmap_blocks,
        milestone_block,
        dependency_ids,
        next_eligible_pending,
        selection_payload,
        select_lookahead,
        roadmap_contract,
        compare_roadmap_entry,
    )
else:
    from roadmap import (
        RoadmapError as LookaheadError,
        NoEligibleMilestone as NoEligibleLookahead,
        roadmap_blocks,
        milestone_block,
        dependency_ids,
        next_eligible_pending,
        selection_payload,
        select_lookahead,
        roadmap_contract,
        compare_roadmap_entry,
    )
    import _common
    import archive_milestone
    import detect_project


PHASES = {"inspect", "define", "research", "decide", "plan"}
STATUSES = {"active", "blocked", "done"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")


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


atomic_write = _common.atomic_write


def state_fields(content: str) -> dict[str, str]:
    try:
        fields = detect_project.state_frontmatter(content)
    except detect_project.DetectError as error:
        raise LookaheadError(str(error)) from error
    if fields is None:
        raise LookaheadError("STATE.md is missing YAML frontmatter")
    return fields


def select_track_branch(content: str, track_state: str) -> dict:
    fields = state_fields(track_state)
    if fields.get("pipeline", "") != archive_milestone.PIPELINE_MARKER:
        raise LookaheadError("lookahead STATE.md is not owned by gsd-path/v2")
    phase = fields.get("phase", "")
    status = fields.get("status", "")
    milestone = fields.get("milestone", "")
    if phase not in PHASES or status not in STATUSES:
        raise LookaheadError(f"invalid lookahead state: {phase}/{status}")
    if archive_milestone.is_unset(milestone):
        raise LookaheadError("lookahead STATE.md does not name a milestone")
    if not archive_milestone.is_unset(fields.get("branch")):
        raise LookaheadError("lookahead STATE.md must not bind a branch")
    if not archive_milestone.is_unset(fields.get("archive")):
        raise LookaheadError("lookahead STATE.md must not own an archive")
    selected = milestone_block(content, milestone)
    if selected["fields"].get("Status", (-1, ""))[1] != "pending":
        raise LookaheadError(f"lookahead milestone {milestone} is not pending")
    eligible = next_eligible_pending(content)
    if selected["id"] != eligible["id"]:
        raise LookaheadError(
            f"lookahead milestone {milestone} is not the next eligible milestone "
            f"{eligible['id']}"
        )
    return selection_payload(selected)


def snapshot_roadmap(source: Path, destination: Path) -> dict:
    require_file(source, "ROADMAP.md")
    require_directory(destination.parent, "roadmap snapshot parent")
    existing_mode = path_mode(destination)
    if existing_mode is not None:
        require_file(destination, "roadmap baseline snapshot")
        content = read_text(destination, "roadmap baseline snapshot")
        return {
            "status": "existing",
            "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }
    content = read_text(source, "ROADMAP.md")
    temporary = destination.parent / f".{destination.name}.gsd-path-tmp"
    try:
        atomic_write(temporary, content)
        try:
            os.link(temporary, destination)
            status = "created"
        except FileExistsError:
            require_file(destination, "roadmap baseline snapshot")
            content = read_text(destination, "roadmap baseline snapshot")
            status = "existing"
    finally:
        if path_mode(temporary) is not None:
            temporary.unlink()
    return {
        "status": status,
        "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def git_commit_file(root: Path, commit: str, relative: str) -> str:
    require_directory(root, "repository")
    if not SHA_RE.fullmatch(commit):
        raise LookaheadError("base must be a full lowercase commit SHA")
    entry = subprocess.run(
        ["git", "-C", str(root), "ls-tree", "-z", commit, "--", relative],
        capture_output=True,
        check=False,
    )
    metadata, separator, path = entry.stdout.rstrip(b"\0").partition(b"\t")
    fields = metadata.split()
    if (
        entry.returncode != 0
        or not separator
        or path.decode("utf-8", "replace") != relative
        or len(fields) != 3
        or fields[0] not in {b"100644", b"100755"}
        or fields[1] != b"blob"
    ):
        raise LookaheadError(f"{relative} must be a regular file at base {commit}")
    result = subprocess.run(
        ["git", "-C", str(root), "show", f"{commit}:{relative}"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise LookaheadError(f"cannot read {relative} at base {commit}{suffix}")
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise LookaheadError(
            f"cannot decode {relative} at base {commit}: {error}"
        ) from error


def select_fetched_base(
    repo: Path,
    base: str,
    remote_default: str,
    use_lookahead: bool,
) -> dict:
    root = repo.resolve()
    if not re.fullmatch(r"origin/[A-Za-z0-9][A-Za-z0-9._/-]*", remote_default):
        raise LookaheadError("remote default must be an origin branch")
    if ".." in remote_default or "//" in remote_default:
        raise LookaheadError("remote default is invalid")
    resolved = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{remote_default}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    if resolved.returncode != 0 or resolved.stdout.strip() != base:
        raise LookaheadError("base does not match the fetched remote default")
    roadmap = git_commit_file(root, base, ".project/ROADMAP.md")
    if use_lookahead:
        track_state = git_commit_file(root, base, ".project/next/STATE.md")
        result = select_track_branch(roadmap, track_state)
    else:
        result = select_lookahead(roadmap)
    return {**result, "base": base}



def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    subparsers = result.add_subparsers(dest="command", required=True)
    compare_parser = subparsers.add_parser("compare-entry")
    compare_parser.add_argument("--before", required=True, type=Path)
    compare_parser.add_argument("--after", required=True, type=Path)
    compare_parser.add_argument("--milestone", required=True)
    compare_parser.add_argument("--active-milestone")
    select_parser = subparsers.add_parser("select-next")
    select_parser.add_argument("--roadmap", required=True, type=Path)
    select_parser.add_argument("--active-milestone")
    branch_parser = subparsers.add_parser("select-branch")
    branch_parser.add_argument("--roadmap", required=True, type=Path)
    branch_parser.add_argument("--state", required=True, type=Path)
    base_parser = subparsers.add_parser("select-base")
    base_parser.add_argument("--repo", required=True, type=Path)
    base_parser.add_argument("--base", required=True)
    base_parser.add_argument("--remote-default", required=True)
    base_parser.add_argument("--lookahead", action="store_true")
    snapshot_parser = subparsers.add_parser("snapshot-roadmap")
    snapshot_parser.add_argument("--roadmap", required=True, type=Path)
    snapshot_parser.add_argument("--snapshot", required=True, type=Path)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "compare-entry":
            result = compare_roadmap_entry(
                read_text(arguments.before, "previous ROADMAP.md"),
                read_text(arguments.after, "proposed ROADMAP.md"),
                arguments.milestone,
                arguments.active_milestone,
            )
        elif arguments.command == "select-next":
            result = select_lookahead(
                read_text(arguments.roadmap, "ROADMAP.md"),
                arguments.active_milestone,
            )
        elif arguments.command == "select-branch":
            require_file(arguments.state, "lookahead STATE.md")
            result = select_track_branch(
                read_text(arguments.roadmap, "ROADMAP.md"),
                read_text(arguments.state, "lookahead STATE.md"),
            )
        elif arguments.command == "select-base":
            result = select_fetched_base(
                arguments.repo,
                arguments.base,
                arguments.remote_default,
                arguments.lookahead,
            )
        elif arguments.command == "snapshot-roadmap":
            result = snapshot_roadmap(arguments.roadmap, arguments.snapshot)
    except (LookaheadError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
