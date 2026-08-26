#!/usr/bin/env python3
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

import archive_milestone
import detect_project


PHASES = {"inspect", "define", "research", "decide", "plan"}
STATUSES = {"active", "blocked", "done"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")
ROADMAP_HEADING_RE = re.compile(r"^### (M\d{3,}) — (.+)$")
MUTABLE_ROADMAP_FIELDS_RE = re.compile(r"^(Status|Archive|Integrated):")


class LookaheadError(RuntimeError):
    pass


class NoEligibleLookahead(LookaheadError):
    pass


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


def state_fields(content: str) -> dict[str, str]:
    try:
        fields = detect_project.state_frontmatter(content)
    except detect_project.DetectError as error:
        raise LookaheadError(str(error)) from error
    if fields is None:
        raise LookaheadError("STATE.md is missing YAML frontmatter")
    return fields


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
                if match.group(1) in fields:
                    raise LookaheadError(
                        f"roadmap milestone {milestone_id} has duplicate "
                        f"{match.group(1)} field"
                    )
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


def dependency_ids(block: dict) -> list[str]:
    dependencies = block["fields"].get("Depends on")
    if dependencies is None:
        raise LookaheadError(f"roadmap milestone {block['id']} lacks dependencies")
    dependency_list = re.fullmatch(
        r"\[\s*(M\d{3,}(?:\s*,\s*M\d{3,})*)?\s*\]",
        dependencies[1],
    )
    if dependency_list is None:
        raise LookaheadError(f"roadmap milestone {block['id']} has invalid dependencies")
    return re.findall(r"M\d{3,}", dependency_list.group(1) or "")


def next_eligible_pending(content: str, active_milestone: Optional[str] = None) -> dict:
    blocks = roadmap_blocks(content)
    blocks_by_id = {block["id"]: block for block in blocks}
    if len(blocks_by_id) != len(blocks):
        raise LookaheadError("ROADMAP.md milestone ids must be unique")
    active_id = None
    if active_milestone is not None:
        active = milestone_block(content, active_milestone)
        if active["fields"].get("Status", (-1, ""))[1] != "active":
            raise LookaheadError(f"roadmap milestone {active_milestone} is not active")
        active_id = active["id"]
    for block in blocks:
        if block["fields"].get("Status", (-1, ""))[1] != "pending":
            continue
        dependencies = dependency_ids(block)
        if all(
            dependency in blocks_by_id
            and (
                blocks_by_id[dependency]["fields"].get("Status", (-1, ""))[1]
                == "shipped"
                or dependency == active_id
            )
            for dependency in dependencies
        ):
            return block
    raise NoEligibleLookahead("ROADMAP.md has no dependency-ready pending milestone")


def selection_payload(selected: dict) -> dict:
    milestone = archive_milestone.normalized_slug(selected["title"])
    return {
        "status": "selected",
        "id": selected["id"],
        "milestone": milestone,
        "branch": f"gsd-path/{selected['id']}",
    }


def select_lookahead(content: str, active_milestone: Optional[str] = None) -> dict:
    try:
        selected = next_eligible_pending(content, active_milestone)
    except NoEligibleLookahead:
        blocks = roadmap_blocks(content)
        if blocks and all(
            block["fields"].get("Status", (-1, ""))[1]
            in {"shipped", "abandoned"}
            for block in blocks
        ):
            return {"status": "complete"}
        return {"status": "none"}
    return selection_payload(selected)


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


def roadmap_contract(content: str, milestone: str) -> tuple[str, ...]:
    block = milestone_block(content, milestone)
    lines = content.splitlines()
    return tuple(
        line.rstrip()
        for line in lines[block["start"] : block["end"]]
        if not MUTABLE_ROADMAP_FIELDS_RE.match(line)
    )


def compare_roadmap_entry(
    before: str,
    after: str,
    milestone: str,
    active_milestone: Optional[str] = None,
) -> dict:
    before_contract = roadmap_contract(before, milestone)
    try:
        after_contract = roadmap_contract(after, milestone)
        selected = milestone_block(after, milestone)
        eligible = next_eligible_pending(after, active_milestone)
    except LookaheadError:
        after_contract = ()
        selected = None
        eligible = None
    status = (
        "unchanged"
        if before_contract == after_contract
        and selected is not None
        and eligible is not None
        and selected["id"] == eligible["id"]
        else "changed"
    )
    return {"status": status, "milestone": milestone}


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
