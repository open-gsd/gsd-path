#!/usr/bin/env python3
"""Named checkouts for task isolation, verify sidecars, and task landing.

The orchestrator calls this helper instead of inventing git worktree, commit,
or cherry-pick commands. Every checkout this module creates is a named branch;
it never detaches HEAD.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
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
FIELD_PATTERN = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*)$")
INLINE_LIST_PATTERN = re.compile(r"^\[(?P<body>.*)\]$")
LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<value>.*)$")


class IsolationError(RuntimeError):
    """Raised when isolation, landing, or retirement cannot proceed."""


def run_git(
    repo: Path, *arguments: str, input: Optional[str] = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        input=input,
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
    return primary.parent / f"{primary.name}.gsd-path" / kind / name


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
    if os.path.lexists(destination):
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


def validate_allowed_changes(
    repo: Path, base: str, pending: Set[str], allowed: Set[str]
) -> None:
    if not pending:
        raise IsolationError("no changes to land")
    since_base = committed_paths_since(repo, base) | pending
    unexpected = sorted(path for path in since_base if path not in allowed)
    if unexpected:
        raise IsolationError("unexpected paths: " + ", ".join(unexpected))


def _clean_blob_oid(repo: Path, path: str, text: str, *, write: bool) -> str:
    arguments = ["hash-object"]
    if write:
        arguments.append("-w")
    arguments.extend((f"--path={path}", "--stdin"))
    result = run_git(repo, *arguments, input=text)
    oid = result.stdout.strip()
    if result.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40,64}", oid):
        detail = (result.stderr or result.stdout).strip() or "clean filter failed"
        raise IsolationError(detail)
    return oid


def commit_allowed_changes(
    repo: Path,
    base: str,
    subject: str,
    allowed: Set[str],
    body: str,
) -> tuple[str, str, Dict[str, Optional[tuple[str, str]]]]:
    require_attached(repo)
    pending = uncommitted_paths(repo)
    validate_allowed_changes(repo, base, pending, allowed)
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
    verified_tree = git_output(repo, "write-tree")
    verified_delta = _tree_delta(repo, base, verified_tree)
    committed = run_git(repo, "commit", "-q", "-m", subject, "-m", body)
    if committed.returncode != 0:
        raise IsolationError(
            (committed.stderr or committed.stdout).strip() or "commit failed"
        )
    return current_sha(repo), verified_tree, verified_delta


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines without the --- fences, body text)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise IsolationError("task file has no frontmatter")
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return [line.rstrip("\r\n") for line in lines[1:index]], "".join(lines[index + 1 :])
    raise IsolationError("task file frontmatter is not closed")


def _strip_yaml_comment(value: str) -> str:
    quote = None
    previous_significant = None
    inline_list = value.lstrip().startswith("[")
    index = 0
    while index < len(value):
        character = value[index]
        if quote == '"':
            if character == "\\" and index + 1 < len(value):
                index += 2
                continue
            if character == quote:
                quote = None
        elif quote == "'":
            if (
                character == quote
                and index + 1 < len(value)
                and value[index + 1] == quote
            ):
                index += 2
                continue
            if character == quote:
                quote = None
        else:
            if character in {"'", '"'} and (
                previous_significant is None
                or (inline_list and previous_significant in {"[", ","})
            ):
                quote = character
            elif character == "#" and (
                index == 0 or value[index - 1].isspace()
            ):
                return value[:index].rstrip()
        if quote is None and not character.isspace():
            previous_significant = character
        index += 1
    return value.strip()


def _unquote(value: str) -> str:
    cleaned = _strip_yaml_comment(value).strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        return cleaned[1:-1]
    return cleaned


def task_frontmatter(text: str) -> tuple[Optional[Dict[str, object]], Optional[str]]:
    try:
        lines, _ = split_frontmatter(text)
    except IsolationError as error:
        return None, str(error)
    fields: Dict[str, object] = {}
    index = 0
    while index < len(lines):
        match = FIELD_PATTERN.match(lines[index])
        if match is None:
            index += 1
            continue
        key = match.group("key")
        value = _strip_yaml_comment(match.group("value"))
        inline = INLINE_LIST_PATTERN.fullmatch(value)
        if inline is not None:
            fields[key] = [
                _unquote(item)
                for item in inline.group("body").split(",")
                if item.strip()
            ]
            index += 1
            continue
        if value:
            fields[key] = _unquote(value)
            index += 1
            continue
        items = []
        cursor = index + 1
        while cursor < len(lines):
            item = LIST_ITEM_PATTERN.match(lines[cursor])
            if item is None:
                break
            items.append(_unquote(item.group("value")))
            cursor += 1
        fields[key] = items
        index = cursor
    return fields, None


LANDED_FIELDS = {"status": "done", "worktree": "null", "task_branch": "null"}
LANDING_MUTABLE_FIELDS = ("status", "agent", "base", "worktree", "task_branch")


def _landed_task_text(text: str, base: str) -> str:
    head, body = split_frontmatter(text)
    values = {**LANDED_FIELDS, "base": base}
    found = set()
    lines = []
    for line in head:
        key = line.split(":", 1)[0]
        if key in values:
            if key in found:
                raise IsolationError(f"task frontmatter repeats {key}")
            if key == "base":
                recorded_base = _unquote(line.split(":", 1)[1])
                if recorded_base not in {"null", base}:
                    raise IsolationError(
                        "task frontmatter base must be null or match landing base"
                    )
            found.add(key)
            lines.append(f"{key}: {values[key]}")
        else:
            lines.append(line)
    missing = sorted(values.keys() - found)
    if missing:
        raise IsolationError("task frontmatter missing landing fields: " + ", ".join(missing))
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def _read_regular_file(path: Path) -> tuple[bytes, int]:
    descriptor = -1
    try:
        initial = path.lstat()
        if not stat.S_ISREG(initial.st_mode):
            raise IsolationError(f"task path is not a regular file: {path}")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        metadata = os.fstat(descriptor)
        current = path.lstat()
        initial_identity = (initial.st_dev, initial.st_ino)
        opened_identity = (metadata.st_dev, metadata.st_ino)
        current_identity = (current.st_dev, current.st_ino)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or initial_identity != opened_identity
            or current_identity != opened_identity
        ):
            raise IsolationError(f"task path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            return stream.read(), stat.S_IMODE(metadata.st_mode)
    except OSError as error:
        raise IsolationError(f"task path is not a regular file: {path}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _read_task_text(path: Path) -> tuple[str, int]:
    data, mode = _read_regular_file(path)
    try:
        return data.decode("utf-8"), mode
    except UnicodeDecodeError as error:
        raise IsolationError(f"task file is not UTF-8: {path}") from error


def _replace_regular_file(path: Path, data: bytes, mode: int) -> None:
    descriptor = -1
    temporary_path: Optional[Path] = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent, prefix=f".{path.name}."
        )
        temporary_path = Path(temporary_name)
        os.chmod(temporary_path, mode)
        with os.fdopen(descriptor, "wb") as stream:
            descriptor = -1
            stream.write(data)
        os.replace(temporary_path, path)
        temporary_path = None
    except OSError as error:
        raise IsolationError(f"could not replace task file {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def stamp_task_landed(task_path: Path, base: str) -> None:
    """Write the orchestrator-owned landing state into the task frontmatter."""
    text, mode = _read_task_text(task_path)
    _replace_regular_file(
        task_path, _landed_task_text(text, base).encode("utf-8"), mode
    )


def _restore_landing_state(
    worktree: Path, task_path: Path, task_bytes: bytes, task_mode: int, index_tree: str
) -> None:
    errors = []
    try:
        _replace_regular_file(task_path, task_bytes, task_mode)
    except IsolationError as error:
        errors.append(str(error))
    restored = run_git(worktree, "read-tree", index_tree)
    if restored.returncode != 0:
        errors.append((restored.stderr or restored.stdout).strip() or "index restore failed")
    if errors:
        raise IsolationError("could not restore landing state: " + "; ".join(errors))


def _restore_rejected_commit(
    repo: Path, commit: str, parent: str, worktree_tree: str
) -> None:
    if current_sha(repo) != commit:
        raise IsolationError("HEAD moved after the rejected landing commit")
    moved = run_git(repo, "update-ref", "HEAD", parent, commit)
    if moved.returncode != 0:
        detail = (moved.stderr or moved.stdout).strip() or "could not restore HEAD"
        raise IsolationError(detail)
    restored = run_git(repo, "read-tree", "--reset", "-u", worktree_tree)
    if restored.returncode != 0:
        detail = (
            (restored.stderr or restored.stdout).strip()
            or "could not restore the verified tree"
        )
        raise IsolationError(detail)


def _stamp_and_commit(
    worktree: Path, base: str, subject: str, task_file: str, allowed: Set[str]
) -> tuple[str, Dict[str, Optional[tuple[str, str]]]]:
    task_path = worktree / task_file
    task_text, task_mode = _read_task_text(task_path)
    task_bytes = task_text.encode("utf-8")
    stamped_text = _landed_task_text(task_text, base)
    stamped = stamped_text.encode("utf-8")
    _, landing_error = _landing_state(
        worktree,
        base,
        task_file,
        stamped_text,
        subject,
        allowed,
        clean_after=True,
    )
    if landing_error:
        raise IsolationError(landing_error)
    pending = uncommitted_paths(worktree)
    if stamped != task_bytes:
        pending.add(task_file)
    validate_allowed_changes(worktree, base, pending, allowed)
    original_head = current_sha(worktree)
    index_tree = git_output(worktree, "write-tree")
    try:
        _replace_regular_file(task_path, stamped, task_mode)
        body = task_commit_body(task_file, uncommitted_paths(worktree), base)
        commit, verified_tree, verified_delta = commit_allowed_changes(
            worktree, base, subject, allowed, body
        )
        proof_error = _landing_commit_proof_error(
            worktree,
            commit,
            original_head,
            task_file,
            base,
            allowed,
            verified_delta,
        )
        if proof_error:
            try:
                _restore_rejected_commit(
                    worktree, commit, original_head, verified_tree
                )
            except IsolationError as restore_error:
                raise IsolationError(
                    f"landing commit proof failed: {proof_error}; {restore_error}"
                ) from restore_error
            raise IsolationError(f"landing commit proof failed: {proof_error}")
        return commit, verified_delta
    except BaseException as error:
        if current_sha(worktree) != original_head:
            raise IsolationError(
                f"landing failed after HEAD changed; refusing rollback: {error}"
            ) from error
        try:
            _restore_landing_state(
                worktree, task_path, task_bytes, task_mode, index_tree
            )
        except IsolationError as restore_error:
            raise IsolationError(f"{error}; {restore_error}") from error
        raise


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
        if current_sha(primary) != resolved_base:
            raise IsolationError("serial landing requires HEAD to equal the recorded base")
        commit, _ = _stamp_and_commit(
            primary,
            resolved_base,
            subject,
            relative_posix(task_file),
            allowed,
        )
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
    source_dirty = bool(uncommitted_paths(source))
    if source_dirty:
        if current_sha(source) != resolved_base:
            raise IsolationError("dirty parallel source HEAD must equal the recorded base")
        source_commit, source_delta = _stamp_and_commit(
            source, resolved_base, subject, relative_posix(task_file), allowed
        )
    else:
        source_commit = current_sha(source)
        if source_commit == resolved_base:
            raise IsolationError("no changes to land")
        source_delta = _tree_delta(source, resolved_base, source_commit)
    source_parent, parent_error = _single_parent(source, source_commit)
    if parent_error or source_parent != resolved_base:
        raise IsolationError(
            parent_error or "clean parallel source commit parent must equal the recorded base"
        )
    if uncommitted_paths(source):
        raise IsolationError("source worktree is dirty after creating the task commit")
    source_body = git_output(source, "log", "-1", "--format=%b", source_commit)
    _, proof_error = _prove_task_commit(
        source,
        source_commit,
        source_body,
        relative_posix(task_file),
        resolved_base,
        None,
        allowed,
    )
    if proof_error:
        raise IsolationError(f"source commit body/task proof failed: {proof_error}")
    landing_parent = current_sha(primary)
    picked = run_git(primary, "cherry-pick", source_commit)
    if picked.returncode != 0:
        run_git(primary, "cherry-pick", "--abort")
        if git_output(primary, "status", "--porcelain"):
            raise IsolationError("cherry-pick failed and primary is not clean after abort")
        if require_attached(primary) != bound:
            raise IsolationError("cherry-pick failed and primary is no longer on the bound branch")
        detail = (picked.stderr or picked.stdout).strip() or "cherry-pick conflict"
        raise IsolationError(f"conflict: {detail}")
    commit = current_sha(primary)
    proof_error = _landing_commit_proof_error(
        primary,
        commit,
        landing_parent,
        relative_posix(task_file),
        resolved_base,
        allowed,
        source_delta,
    )
    if proof_error:
        try:
            _restore_rejected_commit(
                primary, commit, landing_parent, landing_parent
            )
        except IsolationError as restore_error:
            raise IsolationError(
                f"landing commit proof failed: {proof_error}; {restore_error}"
            ) from restore_error
        raise IsolationError(f"landing commit proof failed: {proof_error}")
    return {
        "bound_branch": bound,
        "commit": commit,
        "mode": "parallel",
        "source_commit": source_commit,
        "subject": subject,
    }


def git_text(repo: Path, *arguments: str) -> str:
    result = run_git(repo, *arguments)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git command failed"
        raise IsolationError(detail)
    return result.stdout


def _tree_delta(
    repo: Path, before: str, after: str
) -> Dict[str, Optional[tuple[str, str]]]:
    raw = git_text(
        repo,
        "diff",
        "--raw",
        "--no-abbrev",
        "--no-renames",
        "-z",
        before,
        after,
        "--",
    )
    records = raw.split("\0")
    if records and records[-1] == "":
        records.pop()
    if len(records) % 2:
        raise IsolationError("could not parse tree delta")
    delta: Dict[str, Optional[tuple[str, str]]] = {}
    for metadata, path in zip(records[0::2], records[1::2]):
        fields = metadata.split()
        if (
            len(fields) != 5
            or not fields[0].startswith(":")
            or not path
            or path in delta
        ):
            raise IsolationError("could not parse tree delta")
        mode = fields[1]
        oid = fields[3]
        delta[path] = None if mode == "000000" else (mode, oid)
    return delta


def _frontmatter_key(line: str) -> Optional[str]:
    match = FIELD_PATTERN.match(line)
    return match.group("key") if match is not None else None


def _single_parent(repo: Path, sha: str) -> tuple[Optional[str], Optional[str]]:
    parents = git_output(repo, "show", "-s", "--format=%P", sha).split()
    if len(parents) != 1:
        return None, "task commit must have exactly one parent"
    return parents[0], None


def _landing_transition_error(
    before_head: Sequence[str],
    after_head: Sequence[str],
    before_fields: Dict[str, object],
    after_fields: Dict[str, object],
    base: str,
) -> Optional[str]:
    for key in LANDING_MUTABLE_FIELDS:
        if sum(_frontmatter_key(line) == key for line in before_head) != 1:
            return f"base task frontmatter must contain one {key} field"
        if sum(_frontmatter_key(line) == key for line in after_head) != 1:
            return f"landed task frontmatter must contain one {key} field"
    immutable_before = [
        line for line in before_head if _frontmatter_key(line) not in LANDING_MUTABLE_FIELDS
    ]
    immutable_after = [
        line for line in after_head if _frontmatter_key(line) not in LANDING_MUTABLE_FIELDS
    ]
    if immutable_after != immutable_before:
        return "task frontmatter changes fields outside landing metadata"
    if before_fields.get("status") == "done":
        return "base task is already done"
    expected = {**LANDED_FIELDS, "base": base}
    for key, value in expected.items():
        if after_fields.get(key) != value:
            return f"landed task frontmatter has invalid {key}"
    agent = after_fields.get("agent")
    if not isinstance(agent, str) or agent in {"", "null"}:
        return "landed task frontmatter has no assigned agent"
    return None


def _declared_task_paths(
    fields: Dict[str, object],
) -> tuple[Optional[Set[str]], Optional[str]]:
    raw_files = fields.get("files")
    if not isinstance(raw_files, list) or not all(
        isinstance(item, str) for item in raw_files
    ):
        return None, "base task frontmatter has invalid files"
    try:
        return {relative_posix(item) for item in raw_files}, None
    except IsolationError as error:
        return None, str(error)


def _regular_blob_oid(repo: Path, revision: str, path: str) -> str:
    entries = git_output(repo, "ls-tree", revision, "--", path).splitlines()
    if len(entries) != 1:
        raise IsolationError(f"task path is not a regular file in {revision}: {path}")
    parts = entries[0].split(maxsplit=3)
    if len(parts) != 4 or parts[0] not in {"100644", "100755"} or parts[1] != "blob":
        raise IsolationError(f"task path is not a regular file in {revision}: {path}")
    return parts[2]


def _base_task_contract(
    repo: Path, base: str, task_file: str
) -> tuple[list[str], str, Dict[str, object], Set[str]]:
    _regular_blob_oid(repo, base, task_file)
    text = git_text(repo, "show", f"{base}:{task_file}")
    head, body = split_frontmatter(text)
    fields, error = task_frontmatter(text)
    if error or fields is None:
        raise IsolationError(error or "base task frontmatter is unreadable")
    files, files_error = _declared_task_paths(fields)
    if files_error or files is None:
        raise IsolationError(files_error or "base task files are unreadable")
    return head, body, fields, {task_file, *files}


def _clean_task_text(repo: Path, path: str, text: str) -> str:
    oid = _clean_blob_oid(repo, path, text, write=True)
    return git_text(repo, "cat-file", "blob", oid)


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _landing_state(
    repo: Path,
    base: str,
    task_file: str,
    after_text: str,
    subject: str,
    allowed: Optional[Set[str]],
    *,
    clean_after: bool = False,
) -> tuple[Optional[Set[str]], Optional[str]]:
    try:
        before_head, before_body, before_fields, contract_paths = _base_task_contract(
            repo, base, task_file
        )
        if clean_after:
            after_text = _clean_task_text(repo, task_file, after_text)
        after_head, after_body = split_frontmatter(after_text)
    except IsolationError as error:
        return None, str(error)
    after_fields, after_error = task_frontmatter(after_text)
    if after_error or after_fields is None:
        return contract_paths, after_error or "landed task frontmatter is unreadable"
    try:
        expected_subject = task_commit_subject(
            str(before_fields.get("id", "")), str(before_fields.get("title", ""))
        )
    except ValueError as error:
        return contract_paths, str(error)
    if subject != expected_subject:
        return (
            contract_paths,
            f"source commit subject is {subject!r}, expected {expected_subject!r}",
        )
    if allowed is not None and allowed != contract_paths:
        missing = sorted(contract_paths - allowed)
        extra = sorted(allowed - contract_paths)
        details = []
        if missing:
            details.append("missing " + ", ".join(missing))
        if extra:
            details.append("extra " + ", ".join(extra))
        return (
            contract_paths,
            "landing allow-list differs from the base task: " + "; ".join(details),
        )
    transition_error = _landing_transition_error(
        before_head, after_head, before_fields, after_fields, base
    )
    if transition_error:
        return contract_paths, transition_error
    if not _normalize_newlines(after_body).startswith(
        _normalize_newlines(before_body)
    ):
        return contract_paths, "task file body is not append-only"
    return contract_paths, None


def _landing_retry_error(
    repo: Path, base: str, task_file: str, task_text: str, subject: str
) -> Optional[str]:
    contract_paths, error = _landing_state(
        repo, base, task_file, task_text, subject, None
    )
    if error or contract_paths is None:
        return error or "base task contract is unreadable"
    pending = uncommitted_paths(repo)
    if task_file not in pending:
        return "interrupted landing does not retain the task change"
    try:
        validate_allowed_changes(repo, base, pending, contract_paths)
    except IsolationError as validation_error:
        return str(validation_error)
    return None


def _prove_task_commit(
    repo: Path,
    sha: str,
    body: str,
    task_file: str,
    expected_base: str,
    current_task_text: Optional[str],
    allowed: Optional[Set[str]] = None,
) -> tuple[Optional[str], Optional[str]]:
    """Return (base, None) when `sha` is this task's landing commit, else (None, reason)."""
    base = next((line[6:].strip() for line in body.splitlines() if line.startswith("Base: ")), None)
    if not base:
        return None, "body has no Base: field"
    if base != expected_base:
        return None, "body Base: differs from the task's recorded base"
    parent, parent_error = _single_parent(repo, sha)
    if parent_error or parent is None:
        return None, parent_error or "task commit parent is unreadable"
    if run_git(repo, "merge-base", "--is-ancestor", base, parent).returncode != 0:
        return None, "commit does not descend from its Base:"
    try:
        after_oid = _regular_blob_oid(repo, sha, task_file)
        after_text = git_text(repo, "show", f"{sha}:{task_file}")
    except IsolationError as error:
        return None, str(error)
    subject = git_output(repo, "log", "-1", "--format=%s", sha)
    contract_paths, landing_error = _landing_state(
        repo, base, task_file, after_text, subject, allowed
    )
    if contract_paths is None:
        return None, landing_error or "base task contract is unreadable"
    changed = set(
        git_output(
            repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha
        ).splitlines()
    )
    if task_file not in changed:
        return None, "commit does not touch the task file"
    stray = sorted(changed - contract_paths)
    if stray:
        return None, f"commit touches undeclared paths: {', '.join(stray)}"
    if landing_error:
        return None, landing_error
    if body != task_commit_body(task_file, changed, base).strip():
        return None, "body Task:/Files: fields do not match the changed paths"
    if current_task_text is not None:
        try:
            current_head_oid = _regular_blob_oid(repo, "HEAD", task_file)
            current_oid = _clean_blob_oid(
                repo, task_file, current_task_text, write=False
            )
        except IsolationError as error:
            return None, str(error)
        if after_oid != current_head_oid or after_oid != current_oid:
            return None, "current done task differs from its landing commit"
    return base, None


def _landing_commit_proof_error(
    repo: Path,
    commit: str,
    expected_parent: str,
    task_file: str,
    expected_base: str,
    allowed: Set[str],
    expected_delta: Dict[str, Optional[tuple[str, str]]],
) -> Optional[str]:
    parent, parent_error = _single_parent(repo, commit)
    if parent_error or parent != expected_parent:
        return parent_error or "landing commit parent differs from the pre-landing HEAD"
    try:
        current_task_text, _ = _read_task_text(repo / task_file)
        body = git_output(repo, "log", "-1", "--format=%b", commit)
    except IsolationError as error:
        return str(error)
    _, proof_error = _prove_task_commit(
        repo,
        commit,
        body,
        task_file,
        expected_base,
        current_task_text,
        allowed,
    )
    if proof_error:
        return proof_error
    try:
        actual_delta = _tree_delta(repo, expected_parent, commit)
    except IsolationError as error:
        return str(error)
    if actual_delta != expected_delta:
        return "landing commit tree differs from the verified changes"
    pending = uncommitted_paths(repo)
    if pending:
        return "landing left uncommitted paths: " + ", ".join(sorted(pending))
    return None


def _task_branch_proof_error(
    repo: Path, branch: str, base: str, landed_commit: str
) -> Optional[str]:
    branch_commit = require_commit(repo, branch)
    branch_parent, branch_parent_error = _single_parent(repo, branch_commit)
    if branch_parent_error or branch_parent != base:
        return branch_parent_error or "retained task branch parent differs from Base:"
    landed_parent, landed_parent_error = _single_parent(repo, landed_commit)
    if landed_parent_error or landed_parent is None:
        return landed_parent_error or "landing commit parent is unreadable"
    if run_git(repo, "merge-base", "--is-ancestor", base, landed_parent).returncode != 0:
        return "landing commit does not descend from Base:"
    branch_subject = git_output(repo, "log", "-1", "--format=%s", branch_commit)
    landed_subject = git_output(repo, "log", "-1", "--format=%s", landed_commit)
    branch_body = git_output(repo, "log", "-1", "--format=%b", branch_commit)
    landed_body = git_output(repo, "log", "-1", "--format=%b", landed_commit)
    if branch_subject != landed_subject or branch_body != landed_body:
        return "retained task branch message differs from the landing commit"
    try:
        branch_delta = _tree_delta(repo, base, branch_commit)
        landed_delta = _tree_delta(repo, landed_parent, landed_commit)
    except IsolationError as error:
        return str(error)
    if branch_delta != landed_delta:
        return "retained task branch differs from the landing commit"
    return None


def _worktree_report(
    primary: Path, path: Path, expected_branch: str
) -> tuple[Optional[Dict[str, object]], Optional[str]]:
    if not os.path.lexists(path):
        return None, None
    if path.is_symlink() or not path.is_dir() or path.resolve() != path:
        return None, f"sidecar path is not an owned worktree: {path}"
    try:
        if worktree_root(path) != path:
            return None, f"sidecar path is not its Git root: {path}"
        if common_git_dir(path) != common_git_dir(primary):
            return None, f"sidecar belongs to another repository: {path}"
        branch = require_attached(path)
        if branch != expected_branch:
            return None, f"sidecar is on {branch}, expected {expected_branch}"
        return {
            "path": str(path),
            "branch": branch,
            "clean": not git_output(
                path, "status", "--porcelain", "--untracked-files=all"
            ),
        }, None
    except IsolationError as error:
        return None, f"invalid sidecar worktree {path}: {error}"


def _retained_task_contract_error(
    current_text: str, isolate_text: str
) -> Optional[str]:
    try:
        current_head, current_body = split_frontmatter(current_text)
        isolate_head, isolate_body = split_frontmatter(isolate_text)
    except IsolationError as error:
        return str(error)
    current_contract = [
        line
        for line in current_head
        if _frontmatter_key(line) not in LANDING_MUTABLE_FIELDS
    ]
    isolate_contract = [
        line
        for line in isolate_head
        if _frontmatter_key(line) not in LANDING_MUTABLE_FIELDS
    ]
    if isolate_contract != current_contract:
        return "retained task contract differs from the current task"
    if not _normalize_newlines(isolate_body).startswith(
        _normalize_newlines(current_body)
    ):
        return "retained task body does not extend the current task"
    return None


def _resume_task_error(
    current_text: str,
    isolate_text: str,
    task_id: str,
    title: str,
    base: str,
    worktree: str,
    task_branch: str,
) -> Optional[str]:
    isolate_head, _ = split_frontmatter(isolate_text)
    isolate_fields, fields_error = task_frontmatter(isolate_text)
    if fields_error or isolate_fields is None:
        return fields_error or "retained task frontmatter is unreadable"
    expected = {
        "id": task_id,
        "title": title,
        "status": "in-progress",
        "base": base,
        "task_branch": task_branch,
    }
    for key, value in expected.items():
        if (
            sum(_frontmatter_key(line) == key for line in isolate_head) != 1
            or isolate_fields.get(key) != value
        ):
            return f"retained task has invalid {key}"
    recorded_worktree = isolate_fields.get("worktree")
    if (
        sum(_frontmatter_key(line) == "worktree" for line in isolate_head) != 1
        or not isinstance(recorded_worktree, str)
        or Path(recorded_worktree).resolve() != Path(worktree).resolve()
    ):
        return "retained task has invalid worktree"
    agent = isolate_fields.get("agent")
    if (
        sum(_frontmatter_key(line) == "agent" for line in isolate_head) != 1
        or not isinstance(agent, str)
        or agent in {"", "null"}
    ):
        return "retained task has no assigned agent"
    return _retained_task_contract_error(current_text, isolate_text)


def _recover_task(
    primary: Path,
    path: Path,
    history: Dict[str, list[tuple[str, str]]],
    branches: Set[str],
    head: str,
    bound: str,
) -> Dict[str, object]:
    task_file = relative_posix(str(path.relative_to(primary)))
    report: Dict[str, object] = {"task": task_file}

    def result(verdict: str, **extra: object) -> Dict[str, object]:
        return {**report, "verdict": verdict, **extra}

    try:
        task_text, _ = _read_task_text(path)
    except IsolationError as error:
        return result("block", reason=str(error))
    fields, error = task_frontmatter(task_text)
    if error or fields is None:
        return result("block", reason=error or "unreadable frontmatter")
    task_id, status, title = (str(fields.get(key, "")) for key in ("id", "status", "title"))
    report.update({"task_id": task_id, "status": status})
    try:
        validate_task_id(task_id)
        subject = task_commit_subject(task_id, title)
    except ValueError as error:
        return result("block", reason=str(error))
    except IsolationError as exc:
        return result("block", reason=str(exc))
    task_branch = task_branch_name(task_id)
    branch_exists = task_branch in branches
    worktree, worktree_error = _worktree_report(
        primary, sidecar_root(primary, "task", task_id), task_branch
    )
    report["worktree"] = worktree
    report["task_branch"] = task_branch if branch_exists else None
    report["rejected"] = []

    if worktree_error:
        return result("block", reason=worktree_error)

    valid_statuses = {"pending", "in-progress", "done", "failed", "blocked"}
    if status not in valid_statuses:
        return result("block", reason=f"unknown task status: {status!r}")

    retained = branch_exists or report["worktree"] is not None

    if status in {"pending", "in-progress"}:
        if status == "pending" and not retained:
            return result("none", reason="pending task has no retained isolate")
        if retained:
            if not branch_exists:
                return result("block", reason="sidecar worktree has no retained branch")
            try:
                base = git_output(primary, "merge-base", head, task_branch)
                branch_head = require_commit(primary, task_branch)
            except IsolationError as error:
                return result("block", reason=f"{status} task has invalid base: {error}")
            if worktree is None:
                if branch_head != base:
                    return result("block", reason="retained task branch advanced past its base")
                return result("resume", base=base)
            sidecar = Path(str(worktree["path"]))
            isolate_path = sidecar / task_file
            try:
                isolate_text, _ = _read_task_text(isolate_path)
            except IsolationError as error:
                return result("block", reason=str(error))
            isolate_fields, isolate_error = task_frontmatter(isolate_text)
            if isolate_error or isolate_fields is None:
                return result(
                    "block",
                    reason=isolate_error or "retained task frontmatter is unreadable",
                )
            if status == "pending" and branch_head == base and bool(worktree["clean"]):
                try:
                    base_oid = _regular_blob_oid(primary, base, task_file)
                    current_oid = _clean_blob_oid(
                        primary, task_file, task_text, write=False
                    )
                    isolate_oid = _clean_blob_oid(
                        sidecar, task_file, isolate_text, write=False
                    )
                except IsolationError as error:
                    return result("block", reason=str(error))
                if current_oid == base_oid and isolate_oid == base_oid:
                    return result(
                        "resume",
                        reason="task isolation was created; retry dispatch",
                        dispatch_retry=True,
                        base=base,
                    )
            if isolate_fields.get("status") == "done":
                contract_error = _retained_task_contract_error(
                    task_text, isolate_text
                )
                if contract_error:
                    return result("block", reason=contract_error)
                if branch_head == base:
                    retry_error = _landing_retry_error(
                        sidecar,
                        base,
                        task_file,
                        isolate_text,
                        subject,
                    )
                    source_commit = None
                else:
                    source_commit = branch_head
                    try:
                        parent, parent_error = _single_parent(primary, branch_head)
                        if parent_error or parent != base:
                            retry_error = parent_error or (
                                "retained task commit parent differs from its base"
                            )
                        elif not bool(worktree["clean"]):
                            retry_error = (
                                "retained task commit has uncommitted changes"
                            )
                        else:
                            body = git_output(
                                primary, "log", "-1", "--format=%b", branch_head
                            )
                            _, retry_error = _prove_task_commit(
                                primary,
                                branch_head,
                                body,
                                task_file,
                                base,
                                None,
                            )
                            if retry_error is None:
                                committed_oid = _regular_blob_oid(
                                    primary, branch_head, task_file
                                )
                                checkout_oid = _clean_blob_oid(
                                    sidecar,
                                    task_file,
                                    isolate_text,
                                    write=False,
                                )
                                if committed_oid != checkout_oid:
                                    retry_error = (
                                        "retained task differs from its commit"
                                    )
                    except IsolationError as error:
                        retry_error = str(error)
                if retry_error:
                    return result("block", reason=retry_error)
                return result(
                    "resume",
                    reason="landing was interrupted; retry land without redispatch",
                    landing_retry=True,
                    source_commit=source_commit,
                    base=base,
                )
            if branch_head != base:
                return result("block", reason="retained task branch advanced past its base")
            resume_error = _resume_task_error(
                task_text,
                isolate_text,
                task_id,
                title,
                base,
                str(sidecar),
                task_branch,
            )
        else:
            try:
                base = require_commit(
                    primary, require_full_sha(str(fields.get("base", "")))
                )
            except IsolationError as error:
                return result("block", reason=f"{status} task has invalid base: {error}")
            if head != base:
                return result("block", reason=f"{status} serial task advanced past its base")
            primary_worktree, primary_error = _worktree_report(primary, primary, bound)
            if primary_error:
                return result("block", reason=primary_error)
            report["worktree"] = primary_worktree
            resume_error = _resume_task_error(
                task_text,
                task_text,
                task_id,
                title,
                base,
                str(primary),
                "null",
            )
        if resume_error:
            return result("block", reason=resume_error)
        return result("resume", base=base)

    if status in {"failed", "blocked"}:
        recorded_worktree = str(fields.get("worktree", ""))
        serial_retained = not retained and recorded_worktree == str(primary)
        if not retained and not serial_retained:
            return result("none", reason=f"{status} task has no retained isolate")
        try:
            base = require_commit(
                primary, require_full_sha(str(fields.get("base", "")))
            )
        except IsolationError as error:
            return result("block", reason=f"{status} task has invalid base: {error}")
        if retained:
            expected_worktree = str(sidecar_root(primary, "task", task_id))
            if str(fields.get("worktree", "")) != expected_worktree:
                return result("block", reason=f"{status} task records another worktree")
            if str(fields.get("task_branch", "")) != task_branch:
                return result("block", reason=f"{status} task records another branch")
        if branch_exists and git_output(primary, "merge-base", head, task_branch) != base:
            return result(
                "block", reason=f"{status} task branch differs from its recorded base"
            )
        if serial_retained:
            if str(fields.get("task_branch", "")) != "null":
                return result("block", reason=f"{status} serial task records a task branch")
            if run_git(primary, "merge-base", "--is-ancestor", base, head).returncode != 0:
                return result("block", reason=f"{status} serial task base is not an ancestor")
            primary_worktree, primary_error = _worktree_report(primary, primary, bound)
            if primary_error:
                return result("block", reason=primary_error)
            report["worktree"] = primary_worktree
        return result("reconcile", base=base)

    recorded_base = str(fields.get("base", ""))
    try:
        recorded_base = require_commit(primary, require_full_sha(recorded_base))
    except IsolationError as error:
        return result("block", reason=f"done task has invalid base: {error}")

    proven, rejected = [], []
    for sha, body in history.get(subject, []):
        base, why = _prove_task_commit(
            primary, sha, body, task_file, recorded_base, task_text
        )
        if why is None:
            proven.append((sha, base))
        else:
            rejected.append({"commit": sha, "reason": why})
    report["rejected"] = rejected

    if len(proven) > 1:
        return result("block", reason="multiple proven landing commits: " + ", ".join(sha for sha, _ in proven))
    if proven:
        commit, base = proven[0]
        if branch_exists:
            branch_error = _task_branch_proof_error(primary, task_branch, base, commit)
            if branch_error:
                return result("block", reason=branch_error)
        if worktree is not None and not bool(worktree["clean"]):
            return result(
                "block",
                reason="proven task retains a dirty worktree",
                commit=commit,
                base=base,
            )
        return result("recovered", commit=commit, base=base)
    if not retained and head == recorded_base:
        retry_error = _landing_retry_error(
            primary, recorded_base, task_file, task_text, subject
        )
        if retry_error is None:
            primary_worktree, primary_error = _worktree_report(
                primary, primary, bound
            )
            if primary_error:
                return result("block", reason=primary_error)
            report["worktree"] = primary_worktree
            return result(
                "resume",
                reason="landing was interrupted; retry land without redispatch",
                landing_retry=True,
                source_commit=None,
                base=recorded_base,
            )
    return result("block", reason="done but no landing commit proves it")


def _recovery_task_inventory(
    primary: Path, tasks_dir: Path, head: str
) -> tuple[list[Path], Optional[str]]:
    requested = tasks_dir if tasks_dir.is_absolute() else primary / tasks_dir
    if os.path.lexists(requested) and not requested.is_dir():
        raise IsolationError(f"tasks directory is not a directory: {requested}")
    resolved = requested.resolve()
    if resolved != requested.absolute():
        raise IsolationError(f"tasks directory must not use symlinks: {requested}")
    try:
        relative_dir = resolved.relative_to(primary)
    except ValueError as error:
        raise IsolationError(
            f"tasks directory is outside the primary worktree: {resolved}"
        ) from error
    relative_posix_dir = PurePosixPath(relative_dir.as_posix())
    revisions = [head]
    parents = git_output(primary, "show", "-s", "--format=%P", head).split()
    if parents:
        revisions.append(parents[0])
    tracked = set()
    for revision in revisions:
        tracked.update(
            path
            for path in git_text(
                primary,
                "ls-tree",
                "-r",
                "--name-only",
                "-z",
                revision,
                "--",
                relative_posix_dir.as_posix(),
            ).split("\0")
            if path
            and PurePosixPath(path).parent == relative_posix_dir
            and PurePosixPath(path).suffix == ".md"
        )
    task_paths = sorted(resolved.glob("*.md")) if resolved.is_dir() else []
    live = {path.relative_to(primary).as_posix() for path in task_paths}
    details = []
    missing = sorted(tracked - live)
    unexpected = sorted(live - tracked)
    if missing:
        details.append("missing " + ", ".join(missing))
    if unexpected:
        details.append("unexpected " + ", ".join(unexpected))
    return task_paths, "; ".join(details) or None


def recover(primary: Path, tasks_dir: Path) -> Dict[str, object]:
    """Prove each task's landing state from git. Read-only.

    Verdicts: `recovered` (exactly one proven landing commit; `commit` and
    `base` returned), `resume` (pending, in progress, or an exact interrupted
    landing), `reconcile` (a failed or blocked task retains isolation), `block`
    (missing or conflicting proof), and `none` (nothing to recover). Retained
    `task_branch` and worktree state are returned. Verify is not rerun: a proven
    landing commit is its own evidence.
    """
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_attached(primary)
    head = current_sha(primary)
    task_paths, inventory_error = _recovery_task_inventory(primary, tasks_dir, head)
    if inventory_error:
        return {
            "bound_branch": bound,
            "tasks": [],
            "verdict": "block",
            "reason": "task inventory differs from trusted Git state: "
            + inventory_error,
        }
    history: Dict[str, list[tuple[str, str]]] = {}
    log = git_output(primary, "log", "--first-parent", "--format=%x1e%H%x00%s%x00%b", bound)
    for record in filter(None, log.split("\x1e")):
        sha, subject, body = record.split("\x00", 2)
        history.setdefault(subject, []).append((sha, body.strip()))
    branches = set(
        git_output(primary, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{TASK_BRANCH_PREFIX}").splitlines()
    )
    tasks = [
        _recover_task(primary, path, history, branches, head, bound)
        for path in task_paths
    ]
    return {
        "bound_branch": bound,
        "tasks": tasks,
        "verdict": "block" if any(t["verdict"] == "block" for t in tasks) else "ok",
    }


def _sidecar_path_for_branch(primary: Path, branch: str) -> Path:
    if branch.startswith(TASK_BRANCH_PREFIX):
        task_id = branch.removeprefix(TASK_BRANCH_PREFIX)
        validate_task_id(task_id)
        return sidecar_root(primary, "task", task_id)
    if branch.startswith(VERIFY_BRANCH_PREFIX):
        name = branch.removeprefix(VERIFY_BRANCH_PREFIX)
        validate_name(name, "verify name")
        return sidecar_root(primary, "verify", name)
    raise IsolationError(f"refusing to retire unrecognized branch {branch}")


def _landing_base(repo: Path, commit: str) -> str:
    body = git_output(repo, "log", "-1", "--format=%b", commit)
    values = [
        line.removeprefix("Base: ").strip()
        for line in body.splitlines()
        if line.startswith("Base: ")
    ]
    if len(values) != 1:
        raise IsolationError("landing commit body must contain one Base: field")
    return require_commit(repo, require_full_sha(values[0]))


def _require_first_parent_commit(repo: Path, bound: str, commit: str) -> None:
    history = git_output(repo, "rev-list", "--first-parent", bound).splitlines()
    if commit not in history:
        raise IsolationError("landing commit is not on the bound first-parent history")


def _failed_task_branch_proof_error(
    repo: Path, branch: str, task_file: str
) -> Optional[str]:
    task_file = relative_posix(task_file)
    task_path = repo / task_file
    try:
        task_text, _ = _read_task_text(task_path)
    except IsolationError as error:
        return str(error)
    fields, fields_error = task_frontmatter(task_text)
    if fields_error or fields is None:
        return fields_error or "failed task frontmatter is unreadable"
    task_id = str(fields.get("id", ""))
    try:
        if task_branch_name(task_id) != branch:
            return "failed task id does not own the retained branch"
    except IsolationError as error:
        return str(error)
    if fields.get("status") not in {"failed", "blocked"}:
        return "forced rejected-branch retirement requires failed or blocked task state"
    if fields.get("task_branch") != branch:
        return "failed task does not record the retained branch"
    if fields.get("worktree") != str(sidecar_root(repo, "task", task_id)):
        return "failed task does not record the retained worktree"
    try:
        base = require_commit(repo, require_full_sha(str(fields.get("base", ""))))
        branch_commit = require_commit(repo, branch)
    except IsolationError as error:
        return str(error)
    parent, parent_error = _single_parent(repo, branch_commit)
    if parent_error or parent != base:
        return parent_error or "retained rejected branch parent differs from its recorded base"
    body = git_output(repo, "log", "-1", "--format=%b", branch_commit)
    _, proof_error = _prove_task_commit(
        repo, branch_commit, body, task_file, base, None
    )
    return proof_error


def retire(
    primary: Path,
    worktree: Optional[Path],
    branch: Optional[str],
    force: bool,
    landed_commit: Optional[str] = None,
    task_file: Optional[str] = None,
) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    bound = require_attached(primary)
    if branch == bound:
        raise IsolationError("refusing to retire the bound branch")
    expected_worktree = (
        _sidecar_path_for_branch(primary, branch) if branch else None
    )
    if worktree is None:
        if expected_worktree is None:
            raise IsolationError("retire requires --worktree or --branch")
        resolved_worktree = expected_worktree
    else:
        resolved_worktree = worktree.resolve()
        if (
            branch
            and not resolved_worktree.exists()
            and expected_worktree is not None
            and resolved_worktree != expected_worktree
        ):
            raise IsolationError("absent worktree path does not match the sidecar branch")
    if resolved_worktree == primary:
        if branch:
            raise IsolationError("refusing to retire a sidecar branch through the primary")
        return {
            "bound_branch": bound,
            "branch": None,
            "retired": False,
            "reason": "serial",
            "worktree": str(primary),
        }
    if not resolved_worktree.exists():
        branch_retired = False
        if branch:
            existing = run_git(
                primary, "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"
            )
            if existing.returncode == 0:
                deleted = run_git(primary, "branch", "-d", branch)
                if deleted.returncode != 0 and not force:
                    raise IsolationError(
                        (deleted.stderr or deleted.stdout).strip()
                        or f"could not delete {branch}"
                    )
                if deleted.returncode != 0:
                    if not branch.startswith(TASK_BRANCH_PREFIX):
                        raise IsolationError(
                            "forced branch-only retirement requires a task branch"
                        )
                    if landed_commit:
                        landed = require_commit(primary, require_full_sha(landed_commit))
                        _require_first_parent_commit(primary, bound, landed)
                        base = _landing_base(primary, landed)
                        proof_error = _task_branch_proof_error(
                            primary, branch, base, landed
                        )
                    elif task_file:
                        proof_error = _failed_task_branch_proof_error(
                            primary, branch, task_file
                        )
                    else:
                        raise IsolationError(
                            "forced branch-only task retirement requires --landed-commit or --task-file"
                        )
                    if proof_error:
                        raise IsolationError(proof_error)
                    deleted = run_git(primary, "branch", "-D", branch)
                    if deleted.returncode != 0:
                        raise IsolationError(
                            (deleted.stderr or deleted.stdout).strip()
                            or f"could not delete {branch}"
                        )
                branch_retired = True
        return {
            "bound_branch": bound,
            "branch": branch,
            "retired": True,
            "reason": "branch-only" if branch_retired else "already-absent",
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

    recover_parser = subparsers.add_parser(
        "recover", help="prove landed task commits from git; read-only"
    )
    recover_parser.add_argument("--repo", type=Path, required=True)
    recover_parser.add_argument("--tasks-dir", type=Path, default=Path(".project/tasks"))

    retire_parser = subparsers.add_parser("retire", help="remove a named sidecar checkout")
    retire_parser.add_argument("--repo", type=Path, required=True)
    retire_parser.add_argument("--worktree", type=Path)
    retire_parser.add_argument("--branch")
    retire_parser.add_argument("--force", action="store_true")
    retire_parser.add_argument("--landed-commit")
    retire_parser.add_argument("--task-file")
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
        elif arguments.command == "recover":
            result = recover(arguments.repo, arguments.tasks_dir)
        else:
            result = retire(
                arguments.repo,
                arguments.worktree,
                arguments.branch,
                arguments.force,
                arguments.landed_commit,
                arguments.task_file,
            )
    except IsolationError as error:
        print(str(error), file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
