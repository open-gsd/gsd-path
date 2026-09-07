#!/usr/bin/env python3
# gsd-path project runtime
"""Named checkouts for task isolation, verify sidecars, and task landing.

The orchestrator calls this helper instead of inventing git worktree, commit,
or cherry-pick commands. Every checkout this module creates is a named branch;
it never detaches HEAD.
"""

from __future__ import annotations

import argparse
import hashlib
import io
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
    from pipeline_git import (
        attest_commit_body,
        attest_commit_subject,
        is_bound_branch,
        ship_commit_body,
        ship_subject,
        task_commit_body,
        task_commit_subject,
    )
    import _common
except ImportError:  # pragma: no cover - package import used by tests
    from scripts.pipeline_git import (
        attest_commit_body,
        attest_commit_subject,
        is_bound_branch,
        ship_commit_body,
        ship_subject,
        task_commit_body,
        task_commit_subject,
    )
    from scripts import _common


TASK_BRANCH_PREFIX = "gsd-path-task/"
TASK_AUTHORIZATION_PREFIX = "refs/gsd-path/task-authorizations/"
VERIFY_BRANCH_PREFIX = "gsd-path-verify/"
DISCUSSION_PATHS = frozenset(
    {".project/discuss/DIALOGUE.md", ".project/discuss/ANSWERS.md"}
)
VERIFY_LEDGER_PATH = _common.VERIFY_LEDGER_PATH
# recover verdicts that count as a landed task
LANDED_VERDICTS = frozenset({"recovered", "attested"})
# Orchestrator bookkeeping that may stay uncommitted in the primary while a
# parallel task lands; the next `.project` checkpoint commits it.
BOOKKEEPING_PATHS = DISCUSSION_PATHS | {VERIFY_LEDGER_PATH}
# Bookkeeping path prefixes: pipeline records plus the guard's own install
# artifacts. git_guard and the post-adoption proof share this one definition.
BOOKKEEPING_PREFIXES = (
    ".project/",
    ".gsd-path/",
    ".claude/settings.json",
    ".codex/hooks.json",
    ".cursor/hooks.json",
)
TASK_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*$")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
FIELD_PATTERN = _common.FIELD_PATTERN
INLINE_LIST_PATTERN = _common.INLINE_LIST_PATTERN
LIST_ITEM_PATTERN = _common.LIST_ITEM_PATTERN
COLLECT_JOURNAL_SCHEMA = "gsd-path/collect-artifact/v1"
NULL_SHA = "0" * 40


class IsolationError(RuntimeError):
    """Raised when isolation, landing, or retirement cannot proceed."""


run_git = _common.run_git


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


def require_bound(repo: Path) -> str:
    branch = require_attached(repo)
    if not is_bound_branch(branch):
        raise IsolationError(
            f"primary branch must be canonical gsd-path/M00N, found {branch}"
        )
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


def task_authorization_ref(task_id: str) -> str:
    return f"{TASK_AUTHORIZATION_PREFIX}{validate_task_id(task_id)}"


def _delete_task_authorization(primary: Path, branch: str) -> None:
    if branch.startswith(TASK_BRANCH_PREFIX):
        task_id = validate_task_id(branch.removeprefix(TASK_BRANCH_PREFIX))
        deleted = run_git(
            primary, "update-ref", "-d", task_authorization_ref(task_id)
        )
        if deleted.returncode != 0:
            detail = deleted.stderr.strip() or deleted.stdout.strip()
            raise IsolationError(
                detail or f"could not clear task authorization for {task_id}"
            )


def authorized_task_worktree(worktree: Path, bound_branch: str) -> bool:
    try:
        worktree = require_directory(worktree, "task worktree")
        branch = require_attached(worktree)
        if not branch.startswith(TASK_BRANCH_PREFIX):
            return False
        task_id = validate_task_id(branch.removeprefix(TASK_BRANCH_PREFIX))
        records = _registered_worktrees(worktree)
        primary_matches = [
            path
            for path, record_branch in records.items()
            if record_branch == f"refs/heads/{bound_branch}"
        ]
        if len(primary_matches) != 1:
            return False
        primary = primary_matches[0]
        if (
            worktree != sidecar_root(primary, "task", task_id).resolve()
            or common_git_dir(worktree) != common_git_dir(primary)
        ):
            return False
        head = current_sha(worktree)
        authorization = run_git(
            worktree, "rev-parse", "--verify", task_authorization_ref(task_id)
        )
        if authorization.returncode != 0 or authorization.stdout.strip() != head:
            return False
        matches = []
        tasks_dir = worktree / ".project" / "tasks"
        if tasks_dir.is_symlink() or tasks_dir.resolve() != tasks_dir:
            return False
        for task_path in tasks_dir.glob("*.md") if tasks_dir.is_dir() else ():
            if task_path.is_symlink() or not task_path.is_file():
                return False
            fields, error = task_frontmatter(task_path.read_text(encoding="utf-8"))
            if error is None and fields is not None and fields.get("id") == task_id:
                matches.append(fields)
        if len(matches) != 1:
            return False
        fields = matches[0]
        agent = fields.get("agent")
        return (
            fields.get("status") == "in-progress"
            and fields.get("base") == head
            and fields.get("task_branch") == branch
            and Path(str(fields.get("worktree", ""))).resolve() == worktree
            and isinstance(agent, str)
            and agent not in {"", "null"}
        )
    except (IsolationError, OSError, UnicodeError):
        return False


def verify_branch_name(name: str) -> str:
    return f"{VERIFY_BRANCH_PREFIX}{validate_name(name, 'verify name')}"


def relative_posix(path: str) -> str:
    parsed = PurePosixPath(path)
    if parsed.is_absolute() or ".." in parsed.parts:
        raise IsolationError(f"path must be relative without '..': {path}")
    return parsed.as_posix()


def _real_file(root: Path, relative: str, label: str) -> Path:
    normalized = relative_posix(relative)
    if normalized in {"", "."}:
        raise IsolationError(f"{label} must name a file")
    path = root / normalized
    if not path.is_file() or path.is_symlink():
        raise IsolationError(f"{label} is not a real file: {normalized}")
    try:
        path.resolve().relative_to(root)
    except ValueError as error:
        raise IsolationError(f"{label} escapes its worktree: {normalized}") from error
    return path


def _safe_destination(root: Path, relative: str) -> Path:
    normalized = relative_posix(relative)
    if normalized in {"", "."} or not normalized.startswith(".project/"):
        raise IsolationError("artifact destination must be a file under .project/")
    current = root
    parts = PurePosixPath(normalized).parts
    for part in parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise IsolationError(f"artifact destination has a symlink parent: {normalized}")
    destination = root / normalized
    if destination.is_symlink() or (destination.exists() and not destination.is_file()):
        raise IsolationError(f"artifact destination is not a real file: {normalized}")
    return destination


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _collect_journal_path(primary: Path, request: Dict[str, object]) -> Path:
    key = hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return common_git_dir(primary) / "gsd-path" / "collect-artifact" / f"{key}.json"


def _write_collect_journal(path: Path, payload: Dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".collect-artifact-",
            delete=False,
        ) as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_name = handle.name
        os.replace(temporary_name, path)
        temporary_name = None
    finally:
        if temporary_name:
            Path(temporary_name).unlink(missing_ok=True)


def _read_collect_journal(path: Path) -> Dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise IsolationError(f"artifact collection journal is not a real file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IsolationError(f"artifact collection journal is unreadable: {path}") from error
    if not isinstance(payload, dict):
        raise IsolationError("artifact collection journal must contain an object")
    return payload


def _validated_collect_journal(primary: Path, path: Path) -> Dict[str, object]:
    journal = _read_collect_journal(path)
    request_fields = {
        "schema",
        "primary_worktree",
        "source_worktree",
        "base",
        "branch",
        "source",
        "destination",
        "expected_destination",
    }
    expected_fields = request_fields | {
        "bytes", "previous_sha256", "replaced", "sha256", "stage",
    }
    if set(journal) != expected_fields:
        raise IsolationError("artifact collection journal has invalid fields")
    if journal.get("schema") != COLLECT_JOURNAL_SCHEMA:
        raise IsolationError("artifact collection journal has invalid schema")
    string_fields = request_fields - {"schema", "expected_destination"}
    if any(not isinstance(journal.get(field), str) for field in string_fields):
        raise IsolationError("artifact collection journal has invalid request fields")
    if journal.get("primary_worktree") != str(primary):
        raise IsolationError("artifact collection journal belongs to another worktree")
    try:
        require_full_sha(str(journal["base"]))
        relative_posix(str(journal["source"]))
        relative_posix(str(journal["destination"]))
    except IsolationError as error:
        raise IsolationError(
            f"artifact collection journal has an invalid request: {error}"
        ) from error
    source_worktree = Path(str(journal["source_worktree"]))
    if not source_worktree.is_absolute():
        raise IsolationError("artifact collection source worktree must be absolute")
    if not str(journal["branch"]).startswith(VERIFY_BRANCH_PREFIX):
        raise IsolationError("artifact collection journal has an invalid verify branch")
    if journal.get("stage") not in {"prepared", "collected", "complete"}:
        raise IsolationError("artifact collection journal has an invalid stage")
    count = journal.get("bytes")
    if not isinstance(count, int) or isinstance(count, bool):
        raise IsolationError("artifact collection journal has invalid byte count")
    if not isinstance(journal.get("replaced"), bool):
        raise IsolationError("artifact collection journal has invalid replacement state")
    if not re.fullmatch(r"[0-9a-f]{64}", str(journal.get("sha256", ""))):
        raise IsolationError("artifact collection journal has invalid content hash")
    previous = journal.get("previous_sha256")
    if previous is not None and not re.fullmatch(r"[0-9a-f]{64}", str(previous)):
        raise IsolationError("artifact collection journal has invalid previous hash")
    expected = journal.get("expected_destination")
    if expected is not None and expected != "base" and not re.fullmatch(
        r"[0-9a-f]{64}", str(expected)
    ):
        raise IsolationError("artifact collection journal has invalid expected destination")
    return journal


def collect_artifact_recoveries(primary: Path) -> list[Dict[str, object]]:
    """Return validated incomplete artifact collection transactions."""
    primary = require_directory(primary, "primary worktree")
    root = common_git_dir(primary) / "gsd-path" / "collect-artifact"
    if not root.exists() and not root.is_symlink():
        return []
    if root.is_symlink() or not root.is_dir():
        raise IsolationError(f"artifact collection journal root is unsafe: {root}")
    recoveries = []
    for path in sorted(root.iterdir()):
        if path.suffix != ".json" or path.is_symlink() or not path.is_file():
            raise IsolationError(f"artifact collection journal entry is unsafe: {path}")
        journal = _validated_collect_journal(primary, path)
        if journal["stage"] != "complete":
            recoveries.append({**journal, "journal": str(path)})
    return recoveries


def _git_file(repo: Path, revision: str, path: str) -> bytes:
    result = subprocess.run(
        ("git", "-C", str(repo), "show", f"{revision}:{path}"),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise IsolationError(f"file is missing at {revision}: {path}")
    return result.stdout


def _registered_worktrees(primary: Path) -> Dict[Path, Optional[str]]:
    result = run_git(primary, "worktree", "list", "--porcelain")
    if result.returncode != 0:
        raise IsolationError(
            (result.stderr or result.stdout).strip() or "could not list worktrees"
        )
    records: Dict[Path, Optional[str]] = {}
    for block in result.stdout.strip().split("\n\n"):
        fields = block.splitlines()
        if not fields or not fields[0].startswith("worktree "):
            continue
        path = Path(fields[0].removeprefix("worktree ")).resolve()
        branch = next(
            (
                line.removeprefix("branch ")
                for line in fields[1:]
                if line.startswith("branch ")
            ),
            None,
        )
        records[path] = branch
    return records


def _same_directory(path: Path, expected: os.stat_result) -> bool:
    try:
        current = path.lstat()
    except OSError:
        return False
    return stat.S_ISDIR(current.st_mode) and os.path.samestat(current, expected)


def _cleanup_reserved_worktree(
    primary: Path,
    branch: str,
    destination: Path,
    base: str,
    reserved_directory: os.stat_result,
) -> None:
    ref = f"refs/heads/{branch}"
    records = _registered_worktrees(primary)
    registered = records.get(destination.resolve())
    if registered == ref and _same_directory(destination, reserved_directory):
        run_git(primary, "worktree", "remove", "--force", str(destination))
        records = _registered_worktrees(primary)
    elif registered is None and _same_directory(destination, reserved_directory):
        try:
            destination.rmdir()
        except OSError:
            pass
    if ref not in records.values():
        run_git(primary, "update-ref", "-d", ref, base)


def create_named_worktree(primary: Path, branch: str, destination: Path, base: str) -> None:
    bound = require_bound(primary)
    if branch == bound:
        raise IsolationError(
            f"refusing to check out the bound branch {bound} in a second worktree"
        )
    if os.path.lexists(destination):
        raise IsolationError(f"worktree path already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    ref = f"refs/heads/{branch}"
    reserved = run_git(primary, "update-ref", ref, base, NULL_SHA)
    if reserved.returncode != 0:
        raise IsolationError(f"branch already exists: {branch}")
    try:
        destination.mkdir()
    except FileExistsError as error:
        run_git(primary, "update-ref", "-d", ref, base)
        raise IsolationError(f"worktree path already exists: {destination}") from error
    except OSError as error:
        run_git(primary, "update-ref", "-d", ref, base)
        raise IsolationError(f"cannot reserve worktree path {destination}: {error}") from error
    reserved_directory = destination.lstat()
    result = run_git(
        primary,
        "worktree",
        "add",
        str(destination),
        branch,
    )
    if result.returncode != 0:
        _cleanup_reserved_worktree(
            primary, branch, destination, base, reserved_directory
        )
        detail = (result.stderr or result.stdout).strip() or "git worktree add failed"
        raise IsolationError(detail)
    current = git_output(destination, "branch", "--show-current")
    if current != branch:
        _cleanup_reserved_worktree(
            primary, branch, destination, base, reserved_directory
        )
        raise IsolationError(
            f"worktree HEAD is not {branch} (got {current or 'detached'})"
        )
    if git_output(destination, "rev-parse", "HEAD") != base:
        _cleanup_reserved_worktree(
            primary, branch, destination, base, reserved_directory
        )
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
    bound = require_bound(primary)
    resolved_base = require_commit(primary, require_full_sha(base))
    validate_task_id(task_id)
    if round_size < 1:
        raise IsolationError("round-size must be >= 1")
    if current_sha(primary) != resolved_base:
        raise IsolationError("task isolation requires primary HEAD to equal the recorded base")
    dirty = uncommitted_paths(primary)
    if dirty:
        raise IsolationError(
            "task isolation requires a clean primary worktree: "
            + ", ".join(sorted(dirty))
        )
    if round_size == 1:
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


def isolate_verify(primary: Path, base: str, name: str, historical_task: Optional[str] = None) -> Dict[str, object]:
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_bound(primary)
    resolved_base = require_commit(primary, require_full_sha(base))
    if historical_task is not None:
        reports = recover(primary, Path(".project/tasks"))["tasks"]
        matches = [report for report in reports if report.get("task_id") == historical_task]
        if (len(matches) != 1 or matches[0].get("verdict") != "recovered"
                or matches[0].get("commit") != resolved_base):
            raise IsolationError("historical verification requires this task's recovery-proven landing")
    elif current_sha(primary) != resolved_base:
        raise IsolationError("verify isolation requires primary HEAD to equal the recorded base")
    product_dirt = sorted(
        path for path in uncommitted_paths(primary) if not path.startswith(".project/")
    )
    if product_dirt:
        raise IsolationError(
            "verify isolation refuses non-.project primary changes: "
            + ", ".join(product_dirt)
        )
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


def clean_verify(primary: Path, worktree: Path, base: str, branch: str) -> Dict[str, object]:
    """Discard command-created files only in the named verification sidecar."""
    primary = require_directory(primary, "primary worktree")
    worktree = require_directory(worktree, "verification worktree")
    if worktree == primary or not branch.startswith(VERIFY_BRANCH_PREFIX):
        raise IsolationError("verification cleanup requires a sidecar branch")
    if worktree != _sidecar_path_for_branch(primary, branch):
        raise IsolationError("verification cleanup path differs from its branch")
    if worktree_root(worktree) != worktree or common_git_dir(worktree) != common_git_dir(primary):
        raise IsolationError("verification cleanup requires the primary repository's sidecar")
    if require_attached(worktree) != branch:
        raise IsolationError("verification cleanup branch changed")
    expected = require_commit(primary, require_full_sha(base))
    if current_sha(primary) != expected or current_sha(worktree) != expected:
        raise IsolationError("verification cleanup HEAD changed")
    git_output(worktree, "restore", "--source=HEAD", "--staged", "--worktree", "--", ".")
    removed = git_output(worktree, "clean", "-fdx", "--", ".")
    return {"worktree": str(worktree), "branch": branch, "base": expected, "removed": removed}


def _split_paths(block: str) -> Set[str]:
    return {line.strip() for line in block.splitlines() if line.strip()}


def uncommitted_paths(repo: Path) -> Set[str]:
    tracked = git_output(
        repo, "diff", "--no-renames", "--name-only", "--relative", "HEAD"
    )
    cached = git_output(
        repo, "diff", "--no-renames", "--name-only", "--cached", "--relative"
    )
    untracked = git_output(repo, "ls-files", "--others", "--exclude-standard")
    return _split_paths(tracked) | _split_paths(cached) | _split_paths(untracked)


def committed_paths_since(repo: Path, base: str) -> Set[str]:
    if current_sha(repo) == base:
        return set()
    return _split_paths(
        git_output(
            repo, "diff", "--no-renames", "--name-only", "--relative", base, "HEAD"
        )
    )


def _commit_pending(repo: Path, pending: Set[str], subject: str, body: str) -> str:
    reset = run_git(repo, "reset", "-q", "HEAD")
    if reset.returncode != 0:
        raise IsolationError("could not clear the index before commit")
    for path in sorted(pending):
        added = run_git(repo, "add", "-A", "--", path)
        if added.returncode != 0:
            raise IsolationError(f"could not stage {path}")
    staged = _split_paths(
        git_output(
            repo,
            "diff",
            "--no-renames",
            "--cached",
            "--name-only",
            "--relative",
        )
    )
    if staged != pending:
        raise IsolationError("staged paths do not match the uncommitted change set")
    committed = run_git(repo, "commit", "-q", "-m", subject, "-m", body)
    if committed.returncode != 0:
        raise IsolationError((committed.stderr or committed.stdout).strip() or "commit failed")
    return current_sha(repo)


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


_strip_yaml_comment = _common.strip_yaml_comment
_unquote = _common.unquote


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


def _activated_task_text(
    text: str,
    task_id: str,
    agent: str,
    base: str,
    worktree: Path,
    task_branch: Optional[str],
) -> str:
    head, body = split_frontmatter(text)
    fields, error = task_frontmatter(text)
    if error is not None or fields is None:
        raise IsolationError(error or "task frontmatter is unreadable")
    pending = {
        "id": task_id,
        "status": "pending",
        "agent": "null",
        "base": "null",
        "worktree": "null",
        "task_branch": "null",
    }
    values = {
        "status": "in-progress",
        "agent": agent,
        "base": base,
        "worktree": str(worktree),
        "task_branch": task_branch or "null",
    }
    active = {"id": task_id, **values}
    if all(fields.get(key) == value for key, value in active.items()):
        return text
    for key, value in pending.items():
        if fields.get(key) != value:
            raise IsolationError(f"task activation requires {key}: {value}")
    found = set()
    lines = []
    for line in head:
        key = _frontmatter_key(line)
        if key in values:
            if key in found:
                raise IsolationError(f"task frontmatter repeats {key}")
            found.add(key)
            lines.append(f"{key}: {values[key]}")
        else:
            lines.append(line)
    missing = sorted(values.keys() - found)
    if missing:
        raise IsolationError(
            "task frontmatter missing activation fields: " + ", ".join(missing)
        )
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def activate_task(
    worktree: Path,
    base: str,
    task_id: str,
    agent: str,
    task_file: str,
    task_branch: Optional[str],
) -> Dict[str, object]:
    worktree = require_directory(worktree, "task worktree")
    if worktree_root(worktree) != worktree:
        raise IsolationError(f"task worktree is not its Git root: {worktree}")
    resolved_base = require_commit(worktree, require_full_sha(base))
    if current_sha(worktree) != resolved_base:
        raise IsolationError(
            "task activation requires worktree HEAD at the recorded base"
        )
    task_id = validate_task_id(task_id)
    if not agent or agent == "null" or "\n" in agent:
        raise IsolationError("task activation requires an assigned agent")
    branch = require_attached(worktree)
    if task_branch is None:
        if branch.startswith(TASK_BRANCH_PREFIX):
            raise IsolationError("parallel task activation requires --task-branch")
    elif task_branch != task_branch_name(task_id) or branch != task_branch:
        raise IsolationError("task activation branch does not match the task worktree")
    normalized_task = relative_posix(task_file)
    if not normalized_task.startswith(".project/tasks/"):
        raise IsolationError("task activation file must stay under .project/tasks/")
    task_path = _real_file(worktree, normalized_task, "task activation file")
    text, mode = _read_task_text(task_path)
    activated = _activated_task_text(
        text, task_id, agent, resolved_base, worktree, task_branch
    )
    _replace_regular_file(task_path, activated.encode("utf-8"), mode)
    if task_branch is not None:
        authorization_ref = task_authorization_ref(task_id)
        authorized = run_git(
            worktree,
            "update-ref",
            authorization_ref,
            resolved_base,
            "0" * len(resolved_base),
        )
        if authorized.returncode != 0:
            existing = run_git(
                worktree,
                "rev-parse",
                "--verify",
                authorization_ref,
            )
            if existing.returncode != 0 or existing.stdout.strip() != resolved_base:
                _replace_regular_file(task_path, text.encode("utf-8"), mode)
                raise IsolationError("could not record task worktree authorization")
    return {
        "agent": agent,
        "base": resolved_base,
        "status": "in-progress",
        "task_branch": task_branch,
        "task_file": normalized_task,
        "worktree": str(worktree),
    }


def deactivate_task(
    worktree: Path, task_id: str, task_branch: str
) -> Dict[str, object]:
    worktree = require_directory(worktree, "task worktree")
    if worktree_root(worktree) != worktree:
        raise IsolationError(f"task worktree is not its Git root: {worktree}")
    task_id = validate_task_id(task_id)
    expected_branch = task_branch_name(task_id)
    if (
        task_branch != expected_branch
        or require_attached(worktree) != expected_branch
    ):
        raise IsolationError("task deactivation branch does not match the task worktree")
    _delete_task_authorization(worktree, task_branch)
    return {
        "status": "deactivated",
        "task_branch": task_branch,
        "task_id": task_id,
        "worktree": str(worktree),
    }


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
    bound = require_bound(primary)
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
    dirty = sorted(uncommitted_paths(primary) - BOOKKEEPING_PATHS)
    if dirty:
        raise IsolationError(
            "primary worktree is dirty; refusing to cherry-pick: "
            + ", ".join(dirty)
            + "; commit or remove those paths in the primary worktree first"
        )
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


def _immutable_frontmatter(lines: Sequence[str]) -> list[str]:
    return [line for line in lines if _frontmatter_key(line) not in LANDING_MUTABLE_FIELDS]


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
    if _immutable_frontmatter(after_head) != _immutable_frontmatter(before_head):
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
    compare_head: bool = True,
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
            current_oid = _clean_blob_oid(
                repo, task_file, current_task_text, write=False
            )
            current_head_oid = (
                _regular_blob_oid(repo, "HEAD", task_file)
                if compare_head
                else after_oid
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
    pending = uncommitted_paths(repo) - BOOKKEEPING_PATHS
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
    if _immutable_frontmatter(isolate_head) != _immutable_frontmatter(current_head):
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
    canonical_task_file: Optional[str] = None,
) -> Dict[str, object]:
    task_file = canonical_task_file or relative_posix(str(path.relative_to(primary)))
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
    candidates = history.get(subject, [])
    for sha, body in candidates:
        base, why = _prove_task_commit(
            primary,
            sha,
            body,
            task_file,
            recorded_base,
            task_text,
            compare_head=canonical_task_file is None,
        )
        if why is None:
            proven.append((sha, base))
        else:
            rejected.append({"commit": sha, "reason": why})
    report["rejected"] = rejected
    if len(proven) > 1:
        return result("block", reason="multiple proven landing commits: " + ", ".join(sha for sha, _ in proven))
    attested = []
    for sha, body in history.get(attest_commit_subject(task_id, title), []):
        base, why = _prove_attest_commit(
            primary, sha, body, task_file, task_text, compare_head=canonical_task_file is None
        )
        if why is None:
            attested.append((sha, base))
        else:
            rejected.append({"commit": sha, "reason": why})
    if proven and attested:
        return result("block", reason="task has both a landing commit and an attestation")
    if len(attested) > 1:
        return result("block", reason="multiple attestations: " + ", ".join(sha for sha, _ in attested))
    if attested:
        commit, base = attested[0]
        if worktree is not None and not bool(worktree["clean"]):
            return result("block", reason="attested task retains a dirty worktree", commit=commit, base=base)
        return result("attested", commit=commit, base=base)
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
    if not retained and len(candidates) == 1:
        landing = candidates[0][0]
        project_root = path.parent.parent  # .project or .project/archive/<n>
        try:
            rebased_base = _prove_rebase_adoption(
                primary, project_root, task_file, head, landing, task_text
            )
        except IsolationError as error:
            return result("block", reason=f"rebase adoption receipt is invalid: {error}")
        if rebased_base is not None:
            return result(
                "attested",
                commit=landing,
                base=rebased_base,
                provenance="owner-authorized-rebase",
            )
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


def _first_parent_records(repo: Path, revision: str) -> list[tuple[str, str, str]]:
    """First-parent commits of `revision` as (sha, subject, stripped body) in log order."""
    log = git_output(repo, "log", "--first-parent", "--format=%x1e%H%x00%s%x00%b", revision)
    records = []
    for record in filter(None, log.split("\x1e")):
        sha, subject, body = record.split("\x00", 2)
        records.append((sha, subject, body.strip()))
    return records


def _first_parent_history(repo: Path, revision: str) -> Dict[str, list[tuple[str, str]]]:
    """Map each first-parent commit subject to its [(sha, body)] in log order."""
    history: Dict[str, list[tuple[str, str]]] = {}
    for sha, subject, body in _first_parent_records(repo, revision):
        history.setdefault(subject, []).append((sha, body))
    return history


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
    history = _first_parent_history(primary, bound)
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


def verify_landed_task_files(
    primary: Path,
    task_paths: Sequence[Path],
    canonical_tasks_dir: str,
    head: str,
) -> Dict[str, object]:
    """Prove archived task files against their canonical landing commits."""

    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_attached(primary)
    resolved_head = require_commit(primary, require_full_sha(head))
    canonical_dir = relative_posix(canonical_tasks_dir)
    history = _first_parent_history(primary, resolved_head)
    branches = set(
        git_output(
            primary,
            "for-each-ref",
            "--format=%(refname:short)",
            f"refs/heads/{TASK_BRANCH_PREFIX}",
        ).splitlines()
    )
    tasks = []
    for path in task_paths:
        resolved = path.resolve()
        if path.is_symlink() or not path.is_file():
            raise IsolationError(f"task artifact is missing or unsafe: {path}")
        try:
            resolved.relative_to(primary)
        except ValueError as error:
            raise IsolationError(f"task artifact is outside the primary: {path}") from error
        canonical = relative_posix(f"{canonical_dir}/{path.name}")
        task_text, _ = _read_task_text(resolved)
        fields, error = task_frontmatter(task_text)
        if error or fields is None:
            raise IsolationError(error or f"unreadable task frontmatter: {path.name}")
        if fields.get("status") != "done":
            raise IsolationError(
                f"{fields.get('id', path.name)}: task must have status: done"
            )
        tasks.append(
            _recover_task(
                primary,
                resolved,
                history,
                branches,
                resolved_head,
                bound,
                canonical,
            )
        )
    blocked = [task for task in tasks if task["verdict"] not in LANDED_VERDICTS]
    if blocked:
        def failure_reason(task: Dict[str, object]) -> str:
            rejected = task.get("rejected")
            if isinstance(rejected, list) and rejected:
                details = ", ".join(
                    str(item.get("reason", "rejected"))
                    for item in rejected
                    if isinstance(item, dict)
                )
                if details:
                    return details
            return str(task.get("reason", task["verdict"]))

        reasons = "; ".join(
            f"{task.get('task_id', task['task'])}: {failure_reason(task)}"
            for task in blocked
        )
        raise IsolationError(reasons)
    return {"bound_branch": bound, "head": resolved_head, "tasks": tasks}


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
def collect_artifact(
    primary: Path,
    source: Path,
    base: str,
    branch: str,
    source_path: str,
    destination_path: str,
    expected_destination: Optional[str] = None,
) -> Dict[str, object]:
    """Atomically collect one artifact and retain an idempotent receipt."""

    primary = require_directory(primary, "primary worktree")
    source = require_directory(source, "source worktree")
    if worktree_root(primary) != primary or worktree_root(source) != source:
        raise IsolationError("primary and source must each be their Git root")
    if common_git_dir(primary) != common_git_dir(source):
        raise IsolationError("source worktree belongs to another repository")
    resolved_base = require_commit(primary, require_full_sha(base))
    if current_sha(primary) != resolved_base:
        raise IsolationError("primary worktree HEAD differs from the recorded base")
    if current_sha(source) != resolved_base:
        raise IsolationError("source worktree HEAD differs from the recorded base")
    if not branch.startswith(VERIFY_BRANCH_PREFIX) or require_attached(source) != branch:
        raise IsolationError("source worktree is not on the expected verify branch")
    normalized_source = relative_posix(source_path)
    normalized_destination = relative_posix(destination_path)
    destination = _safe_destination(primary, normalized_destination)
    request: Dict[str, object] = {
        "schema": COLLECT_JOURNAL_SCHEMA,
        "primary_worktree": str(primary),
        "source_worktree": str(source),
        "base": resolved_base,
        "branch": branch,
        "source": normalized_source,
        "destination": normalized_destination,
        "expected_destination": expected_destination,
    }
    journal_path = _collect_journal_path(primary, request)
    changed = uncommitted_paths(source)
    journal: Optional[Dict[str, object]] = None
    if journal_path.exists() or journal_path.is_symlink():
        journal = _validated_collect_journal(primary, journal_path)
        if any(
            journal.get(key) != value for key, value in request.items()
        ):
            raise IsolationError("artifact collection journal does not match request")
        if journal["stage"] == "complete" and changed == {normalized_source}:
            journal = None  # a later sidecar run reuses the same branch and paths

    if journal is None:
        if changed != {normalized_source}:
            unexpected = sorted(changed - {normalized_source})
            detail = ", ".join(unexpected) if unexpected else "expected artifact is unchanged"
            raise IsolationError(f"unexpected sidecar paths: {detail}")
        source_file = _real_file(source, normalized_source, "artifact source")
        data = source_file.read_bytes()
        previous_data = destination.read_bytes() if destination.exists() else None
        if previous_data is not None and previous_data != data:
            actual_hash = _sha256(previous_data)
            if expected_destination == "base":
                expected_hash = _sha256(
                    _git_file(primary, resolved_base, normalized_destination)
                )
            elif expected_destination and re.fullmatch(
                r"[0-9a-f]{64}", expected_destination
            ):
                expected_hash = expected_destination
            else:
                raise IsolationError(
                    "artifact destination has different content without a proven expected version"
                )
            if actual_hash != expected_hash:
                raise IsolationError(
                    "artifact destination changed after its expected version was recorded"
                )
        journal = {
            **request,
            "bytes": len(data),
            "previous_sha256": _sha256(previous_data) if previous_data is not None else None,
            "replaced": previous_data is not None and previous_data != data,
            "sha256": _sha256(data),
            "stage": "prepared",
        }
        _write_collect_journal(journal_path, journal)
    else:
        current_hash = _sha256(destination.read_bytes()) if destination.exists() else None
        if not changed:
            if current_hash != journal["sha256"]:
                raise IsolationError(
                    "artifact receipt exists but the collected destination changed"
                )
            journal["stage"] = "complete"
            _write_collect_journal(journal_path, journal)
            return {
                key: journal[key]
                for key in (
                    "base",
                    "branch",
                    "bytes",
                    "destination",
                    "previous_sha256",
                    "replaced",
                    "sha256",
                    "source",
                )
            }
        if changed != {normalized_source}:
            unexpected = sorted(changed - {normalized_source})
            raise IsolationError(
                "unexpected sidecar paths: " + ", ".join(unexpected)
            )
        source_file = _real_file(source, normalized_source, "artifact source")
        data = source_file.read_bytes()
        if _sha256(data) != journal["sha256"]:
            raise IsolationError("artifact source changed after collection was prepared")
        if current_hash not in {journal["previous_sha256"], journal["sha256"]}:
            raise IsolationError(
                "artifact destination changed after collection was prepared"
            )

    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or _sha256(destination.read_bytes()) != journal["sha256"]:
        temporary_name: Optional[str] = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=".gsd-path-artifact-",
                delete=False,
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_name = handle.name
            os.replace(temporary_name, destination)
            temporary_name = None
        finally:
            if temporary_name:
                Path(temporary_name).unlink(missing_ok=True)
    if _sha256(destination.read_bytes()) != journal["sha256"]:
        raise IsolationError("artifact destination does not match the prepared receipt")
    journal["stage"] = "collected"
    _write_collect_journal(journal_path, journal)

    reset = run_git(source, "reset", "-q", "HEAD", "--", normalized_source)
    if reset.returncode != 0:
        raise IsolationError("artifact was collected but its staged state could not be cleared")
    tracked = run_git(source, "ls-files", "--error-unmatch", "--", normalized_source)
    if tracked.returncode == 0:
        restored = run_git(source, "restore", "--worktree", "--", normalized_source)
        if restored.returncode != 0:
            raise IsolationError("artifact was collected but the source could not be restored")
    else:
        source_file.unlink()
    if uncommitted_paths(source):
        raise IsolationError("artifact was collected but the source worktree is still dirty")
    journal["stage"] = "complete"
    _write_collect_journal(journal_path, journal)
    return {
        key: journal[key]
        for key in (
            "base",
            "branch",
            "bytes",
            "destination",
            "previous_sha256",
            "replaced",
            "sha256",
            "source",
        )
    }


def _validate_checkpoint_message(subject: str, body: str) -> None:
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if subject == "roadmap: program roadmap approved":
        if lines != ["Why: approved roadmap checkpoint"]:
            raise IsolationError("roadmap checkpoint body is not canonical")
        return
    if subject == "plan: build plan approved":
        if (
            len(lines) != 2
            or lines[0] != "Why: approved plan checkpoint"
            or not re.fullmatch(r"Milestone: \S+", lines[1])
        ):
            raise IsolationError("plan checkpoint body is not canonical")
        return
    if re.fullmatch(r"build: abandon milestone [a-z0-9][a-z0-9-]*", subject):
        if len(lines) != 1 or not lines[0].startswith("Why: "):
            raise IsolationError("abandon checkpoint body must contain one Why line")
        reason = lines[0][len("Why: ") :]
        if not reason or reason != " ".join(reason.split()):
            raise IsolationError("abandon checkpoint reason must be normalized")
        return
    if re.fullmatch(r"build: \S.*", subject):
        if not lines or not re.fullmatch(r"Why: \S.*", lines[0]):
            raise IsolationError("build checkpoint body must start with Why")
        seen = set()
        for line in lines[1:]:
            match = re.fullmatch(r"(Wave|Tasks|Base): \S.*", line)
            if not match or match.group(1) in seen:
                raise IsolationError("build checkpoint body has an invalid field")
            seen.add(match.group(1))
        return
    raise IsolationError("unsupported pipeline checkpoint subject")


task_verify_command = _common.task_verify_command


def _ledger_pass(entries: Sequence[Dict[str, object]], command: str, commit: str) -> bool:
    entry = _common.latest_verify_entry(entries, command, commit)
    return entry is not None and entry["result"] == "pass"


def _verify_ledger_pass(repo: Path, command: str, commit: str) -> bool:
    """True when the worktree verify ledger's latest run of command at commit passed."""
    path = repo.joinpath(*PurePosixPath(VERIFY_LEDGER_PATH).parts)
    if path.is_symlink():
        raise IsolationError(f"{VERIFY_LEDGER_PATH} must be a regular file")
    try:
        return _ledger_pass(_common.verify_ledger_entries(path), command, commit)
    except ValueError as error:
        raise IsolationError(str(error)) from error


def _task_contract_error(base_text: str, text: str, label: str) -> Optional[str]:
    """Only landing metadata and an appended log may differ from the base task."""
    try:
        base_head, base_body = split_frontmatter(base_text)
        head, body = split_frontmatter(text)
    except IsolationError as error:
        return str(error)
    base_fields, _ = task_frontmatter(base_text)
    if base_fields is not None and base_fields.get("status") == "done":
        return "base task is already done"
    if _immutable_frontmatter(base_head) != _immutable_frontmatter(head) or not (
        _normalize_newlines(body).startswith(_normalize_newlines(base_body))
    ):
        return f"{label} changes the task contract recorded at its base"
    return None


def _attest_body_fields(body: str) -> tuple[Dict[str, str], list[str]]:
    fields: Dict[str, str] = {}
    files: list[str] = []
    for line in body.splitlines():
        if line.startswith("- "):
            files.append(line[2:].strip())
        else:
            key, separator, value = line.partition(":")
            if separator and key in {"Task", "Base", "Head", "Verify", "Ruling", "Attestation", "Verify-JSON"}:
                fields[key] = value.strip()
    return fields, files


def _attested_changes(repo: Path, base: str, head: str, declared: Set[str]) -> list[str]:
    """Declared paths that changed between base and head, matched literally like land."""
    changed = set(git_output(repo, "diff", "--name-only", base, head).splitlines())
    return sorted(changed & declared)


def _prove_attest_commit(
    repo: Path,
    sha: str,
    body: str,
    task_file: str,
    task_text: str,
    compare_head: bool = True,
) -> tuple[Optional[str], Optional[str]]:
    """Return (base, None) when `sha` attests this task, else (None, reason)."""
    fields, files = _attest_body_fields(body)
    base, head = fields.get("Base", ""), fields.get("Head", "")
    if fields.get("Task") != task_file:
        return None, "body Task: differs from the task file"
    if not fields.get("Ruling"):
        return None, "attestation has no Ruling:"
    try:
        base = require_commit(repo, require_full_sha(base))
        head = require_commit(repo, require_full_sha(head))
    except IsolationError as error:
        return None, f"attestation Base:/Head: are invalid: {error}"
    parent, parent_error = _single_parent(repo, sha)
    if parent_error or parent != head:
        return None, parent_error or "attestation parent differs from its Head:"
    if run_git(repo, "merge-base", "--is-ancestor", base, head).returncode != 0:
        return None, "attestation Head: does not descend from its Base:"
    changed = set(git_output(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines())
    if task_file not in changed or not changed <= {task_file, VERIFY_LEDGER_PATH}:
        return None, "attestation commit must change only the task file and the verify ledger"
    try:
        before_text = git_text(repo, "show", f"{head}:{task_file}")
        after_text = git_text(repo, "show", f"{sha}:{task_file}")
        before_head, before_body = split_frontmatter(before_text)
        after_head, after_body = split_frontmatter(after_text)
    except IsolationError as error:
        return None, str(error)
    after_fields, after_error = task_frontmatter(after_text)
    if after_error or after_fields is None:
        return None, after_error or "attested task frontmatter is unreadable"
    if _immutable_frontmatter(before_head) != _immutable_frontmatter(after_head) or not after_body.startswith(before_body):
        return None, "attestation changes the task outside landing metadata and an appended log"
    for key, value in {**LANDED_FIELDS, "base": base}.items():
        if after_fields.get(key) != value:
            return None, f"attested task frontmatter has invalid {key}"
    agent = after_fields.get("agent")
    if not isinstance(agent, str) or agent in {"", "null"}:
        return None, "attested task frontmatter has no assigned agent"
    try:
        contract_error = _task_contract_error(
            git_text(repo, "show", f"{base}:{task_file}"), after_text, "attestation"
        )
    except IsolationError as error:
        return None, str(error)
    if contract_error:
        return None, contract_error
    verify = task_verify_command(after_text)
    legacy = "Attestation" not in fields
    if legacy:
        verify = " ".join(verify.split())
        recorded_verify = fields.get("Verify")
    else:
        if fields["Attestation"] != "gsd-path/attestation/v2":
            return None, "unknown attestation version"
        try:
            recorded_verify = json.loads(fields.get("Verify-JSON", ""))
        except json.JSONDecodeError:
            return None, "attestation Verify-JSON is invalid"
    if not verify.strip() or recorded_verify != verify:
        return None, "body Verify: differs from the task's ## Verify command"
    ledger = run_git(repo, "show", f"{sha}:{VERIFY_LEDGER_PATH}")
    if ledger.returncode != 0:
        return None, "attestation commit carries no verify ledger"
    try:
        entries = _common.parse_verify_ledger(ledger.stdout)
        if legacy:
            matches = [e for e in entries if e.get("schema") is None and e["command"] == verify and e["commit"] == head]
            passed = bool(matches) and matches[-1]["result"] == "pass"
        else:
            passed = _ledger_pass(entries, verify, head)
        if not passed:
            return None, "verify ledger in the attestation has no passing run at Head:"
    except ValueError as error:
        return None, str(error)
    declared, declared_error = _declared_task_paths(after_fields)
    if declared_error or declared is None:
        return None, declared_error or "attested task files are unreadable"
    expected_files = _attested_changes(repo, base, head, declared)
    if not expected_files:
        return None, "no declared file changed between Base: and Head:"
    if files != expected_files:
        return None, "body Files: does not match the declared changes between Base: and Head:"
    expected_body = attest_commit_body(
        task_file, base, head, expected_files, verify, fields["Ruling"], legacy=legacy
    )
    if body.strip() != expected_body.strip():
        return None, "attestation body is not canonical"
    try:
        current_oid = _clean_blob_oid(repo, task_file, task_text, write=False)
        after_oid = _regular_blob_oid(repo, sha, task_file)
        head_oid = _regular_blob_oid(repo, "HEAD", task_file) if compare_head else after_oid
    except IsolationError as error:
        return None, str(error)
    if current_oid != after_oid or head_oid != after_oid:
        return None, "current done task differs from its attestation"
    return base, None


REBASE_ADOPTION_SCHEMA = "gsd-path/rebase-adoption/v1"
REBASE_ADOPTION_RECEIPT = "build/rebase-adoption.json"
REBASE_ADOPTION_PATH = ".project/" + REBASE_ADOPTION_RECEIPT


def _one_landing(history: Dict[str, list[tuple[str, str]]], subject: str) -> tuple[str, str]:
    """The single (sha, body) landing for `subject`; adoption needs exactly one."""
    candidates = history.get(subject, [])
    if len(candidates) != 1:
        raise IsolationError("rebase adoption requires one landing: " + subject)
    return candidates[0]


def _committed_task_paths(repo: Path, revision: str) -> list[str]:
    return git_text(repo, "ls-tree", "-r", "--name-only", revision, "--", ".project/tasks").splitlines()


def _ordered_edits(repo: Path, sha: str) -> list[bytes]:
    """Every changed byte, path, mode and binary payload of `sha`; hunk
    coordinates and content-addressed index headers excluded."""
    result = subprocess.run(
        ("git", "-C", str(repo), "diff", "--binary", "--full-index", "--no-renames",
         "--unified=0", sha + "^", sha),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", errors="replace").strip()
        raise IsolationError(detail or "git command failed")
    return [line for line in io.BytesIO(result.stdout)
            if not line.startswith((b"index ", b"@@ "))]


def _task_contract_section(text: str) -> str:
    """Everything before the task's `## Log`: the part adoption keeps immutable."""
    before, separator, _ = text.partition("\n## Log\n")
    if not separator:
        raise IsolationError("task is missing its Log boundary")
    return before


def _task_proof(
    repo: Path,
    path: str,
    original: tuple[str, str],
    rebased: tuple[str, str],
    adopted: str,
    current_text: str,
) -> Dict[str, object]:
    """One receipt row: `rebased` replays the strictly proven `original` landing."""
    (original_sha, original_body), (rebased_sha, rebased_body) = original, rebased
    original_text = git_text(repo, "show", f"{original_sha}:{path}")
    fields, error = task_frontmatter(original_text)
    if error or fields is None:
        raise IsolationError(error or "invalid original task")
    base = str(fields.get("base", ""))
    _, error = _prove_task_commit(repo, original_sha, original_body, path, base, None)
    if error:
        raise IsolationError("original landing is invalid: " + error)
    parent, error = _single_parent(repo, rebased_sha)
    if error or parent is None:
        raise IsolationError(error or "invalid rebased parent")
    # Subjects already match: both landings were looked up under the same subject.
    if original_body != rebased_body:
        raise IsolationError("rebased landing message differs")
    if _ordered_edits(repo, original_sha) != _ordered_edits(repo, rebased_sha):
        raise IsolationError("rebased landing changes different bytes, paths or modes")
    if _regular_blob_oid(repo, original_sha, path) != _regular_blob_oid(repo, rebased_sha, path):
        raise IsolationError("rebased task differs from original landing")
    _regular_blob_oid(repo, adopted, path)  # rejects a symlinked task at the adopted head
    if _task_contract_section(current_text) != _task_contract_section(original_text):
        raise IsolationError("adopted task contract differs from original landing")
    return {"path": path, "original_landing": original_sha, "rebased_landing": rebased_sha,
            "original_base": base, "original_task": original_text,
            "adopted_task": current_text,
            "context_changed": git_text(repo, "diff", "--binary", original_sha + "^", original_sha)
                               != git_text(repo, "diff", "--binary", rebased_sha + "^", rebased_sha)}


def adopt_rebase(primary: Path, original_head: str, head: str, ruling: str) -> Dict[str, object]:
    """Compute the owner-ruled receipt adopting every done task's rebased landing.

    Adoption attests a pinned rebased revision, not behavioral equivalence or
    final acceptance: each done task needs its original canonical landing on
    `original_head`, one landing with identical message and ordered edits on
    `head`, and an unchanged task contract. Pending tasks are skipped; tasks in
    flight cannot be adopted.
    """
    if not ruling.strip():
        raise IsolationError("an explicit owner ruling is required")
    for sha in (original_head, head):
        require_commit(primary, require_full_sha(sha))
    if original_head == head:
        raise IsolationError("original and adopted heads must differ")
    old, new = _first_parent_history(primary, original_head), _first_parent_history(primary, head)
    paths = _committed_task_paths(primary, head)
    if not paths:
        raise IsolationError("no committed task inventory")
    tasks = []
    for path in paths:
        text = git_text(primary, "show", f"{head}:{path}")
        fields, error = task_frontmatter(text)
        if error or fields is None:
            raise IsolationError(f"{path}: {error or 'unreadable task frontmatter'}")
        status = str(fields.get("status", ""))
        if status == "pending":
            continue
        if status != "done":
            raise IsolationError(f"rebasing a {status} task is unsupported: {path}")
        subject = task_commit_subject(str(fields.get("id", "")), str(fields.get("title", "")))
        tasks.append(_task_proof(primary, path, _one_landing(old, subject), _one_landing(new, subject), head, text))
    return {"schema": REBASE_ADOPTION_SCHEMA, "original_head": original_head, "head": head,
            "ruling": ruling.strip(), "tasks": tasks}


# Proof outcomes per process, including failures: git objects are immutable, so
# a receipt or range that failed once fails for every task that asks again.
_ADOPTION_MEMO: Dict[tuple, tuple[bool, object]] = {}


def _memoized(key: tuple, compute):
    if key not in _ADOPTION_MEMO:
        try:
            _ADOPTION_MEMO[key] = (True, compute())
        except IsolationError as error:
            _ADOPTION_MEMO[key] = (False, error)
    ok, value = _ADOPTION_MEMO[key]
    if not ok:
        raise value
    return value


def _require_landings_after(repo: Path, adopted: str, head: str) -> None:
    """After adoption every product change must be a strictly proven landing."""
    _memoized(("landings", str(repo), adopted, head), lambda: _check_landings_after(repo, adopted, head))


def _check_landings_after(repo: Path, adopted: str, head: str) -> None:
    if run_git(repo, "merge-base", "--is-ancestor", adopted, head).returncode:
        raise IsolationError("adopted revision is not an ancestor")
    inventory = set(_committed_task_paths(repo, head))
    archived_paths = git_text(
        repo, "ls-tree", "-r", "--name-only", head, "--", ".project/archive"
    ).splitlines()
    for path in archived_paths:
        match = re.fullmatch(r"\.project/archive/[^/]+/tasks/([^/]+\.md)", path)
        if match:
            inventory.add(".project/tasks/" + match.group(1))
    for sha, _, body in _first_parent_records(repo, f"{adopted}..{head}"):
        changed = git_output(repo, "diff", "--name-only", sha + "^", sha).splitlines()
        # Bookkeeping, including real attestations, cannot change product paths.
        if all(path.startswith(BOOKKEEPING_PREFIXES) for path in changed):
            continue
        fields, _ = _attest_body_fields(body)
        task_file, base = fields.get("Task", ""), fields.get("Base", "")
        if task_file in inventory and re.fullmatch(r"[0-9a-f]{40}", base):
            _, error = _prove_task_commit(repo, sha, body, task_file, base, None)
            if error is None:
                continue
        raise IsolationError("product changed outside a proven landing after the adopted revision")


def _receipt_path(project_root: Path) -> Path:
    """The adoption receipt beside a live (.project/) or archived project root."""
    path = project_root / REBASE_ADOPTION_RECEIPT
    try:
        resolved = path.resolve()
    except (RuntimeError, OSError) as error:
        raise IsolationError(f"unsafe rebase adoption receipt path: {error}") from error
    if resolved != path.absolute():
        raise IsolationError("unsafe rebase adoption receipt path")
    return path


def _receipt_bytes(project_root: Path) -> Optional[bytes]:
    """The receipt's bytes, or None when the project root has no receipt."""
    path = _receipt_path(project_root)
    if not os.path.lexists(path):
        return None
    if not path.is_file():
        raise IsolationError("rebase adoption receipt is not a regular file")
    try:
        return path.read_bytes()
    except OSError as error:
        raise IsolationError(str(error)) from error


def _validated_receipt(repo: Path, raw: bytes) -> Dict[str, object]:
    """Parse and recompute a receipt once per process; git objects are immutable."""
    key = ("receipt", str(repo), hashlib.sha256(raw).hexdigest())
    return _memoized(key, lambda: _validate_receipt(repo, raw))


def _validate_receipt(repo: Path, raw: bytes) -> Dict[str, object]:
    try:
        receipt = json.loads(raw)
        if not isinstance(receipt, dict) or receipt.get("schema") != REBASE_ADOPTION_SCHEMA:
            raise IsolationError("unknown schema")
        for field in ("original_head", "head"):
            if not isinstance(receipt.get(field), str):
                raise IsolationError(f"{field} must be a full lowercase SHA")
            require_full_sha(receipt[field])
        if not isinstance(receipt.get("ruling"), str) or not receipt["ruling"].strip():
            raise IsolationError("ruling must be a non-empty string")
        if not isinstance(receipt.get("tasks"), list) or any(
            not isinstance(row, dict) for row in receipt["tasks"]
        ):
            raise IsolationError("tasks must be a list of objects")
        expected = adopt_rebase(repo, receipt["original_head"], receipt["head"], receipt["ruling"])
    except (KeyError, TypeError, ValueError) as error:
        raise IsolationError(str(error)) from error
    if receipt != expected:
        raise IsolationError("receipt does not match recomputed Git evidence")
    return receipt


def _prove_rebase_adoption(
    repo: Path, project_root: Path, task_file: str, head: str, landing: str, current_text: str
) -> Optional[str]:
    """Return the original base the receipt binds to `landing`; None without a receipt.

    `project_root` is the task artifact's own root: `.project` for live tasks,
    `.project/archive/<n>` for archived ones.
    """
    raw = _receipt_bytes(project_root)
    if raw is None:
        return None
    receipt = _validated_receipt(repo, raw)
    if receipt["head"] != head:
        _require_landings_after(repo, receipt["head"], head)
    rows = [row for row in receipt["tasks"] if row["path"] == task_file]
    if len(rows) != 1 or rows[0]["rebased_landing"] != landing:
        raise IsolationError("receipt does not bind this landing")
    if rows[0]["adopted_task"] != current_text:
        raise IsolationError("current task differs from adopted task")
    return str(rows[0]["original_base"])


def record_rebase_adoption(
    primary: Path, original_head: str, head: str, ruling: str
) -> Dict[str, object]:
    """Write the adoption receipt for the bound milestone worktree at `head`."""
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_bound(primary)
    if current_sha(primary) != head:
        raise IsolationError("HEAD differs from approved adopted revision")
    receipt = adopt_rebase(primary, original_head, head, ruling)
    existing = _receipt_bytes(primary / ".project")
    try:
        if existing is not None and json.loads(existing) != receipt:
            raise IsolationError("another adoption receipt already exists")
    except ValueError as error:
        raise IsolationError(f"unreadable existing receipt: {error}") from error
    target = _receipt_path(primary / ".project")
    _common.atomic_write(target, json.dumps(receipt, indent=2) + "\n")
    return {"bound_branch": bound, "head": head, "path": str(target),
            "tasks": len(receipt["tasks"]), "verdict": "adopted"}


def publication_base(repo: Path, branch: str, ship_commit: str) -> Optional[str]:
    """The adopted head a shipped, owner-adopted milestone may advance from.

    Returns None when the milestone is not an adopted one; raises when the
    archived receipt, ship commit, or archived tasks fail proof.
    """
    try:
        from pipeline_state import load_state
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts.pipeline_state import load_state
    repo = require_directory(repo, "repository")
    state, state_text, _ = load_state(repo)
    if (state.phase, state.status, state.integration, state.branch) != (
        "shipped", "done", "direct", branch
    ) or state.archive is None:
        return None
    raw = _receipt_bytes(repo / state.archive)
    if raw is None:
        return None
    if current_sha(repo) != ship_commit or uncommitted_paths(repo):
        raise IsolationError("publication requires the clean ship commit")
    if git_text(repo, "show", f"{ship_commit}:.project/STATE.md") != state_text:
        raise IsolationError("ship state differs from committed state")
    receipt = _validated_receipt(repo, raw)
    parent, error = _single_parent(repo, ship_commit)
    if error or parent != receipt["head"]:
        raise IsolationError("ship parent is not the adopted revision")
    changed = git_output(repo, "diff", "--name-only", parent, ship_commit).splitlines()
    if any(not name.startswith(".project/") for name in changed):
        raise IsolationError("ship commit changes product files")
    expected = (ship_subject(Path(state.archive).name) + "\n\n"
                + ship_commit_body(state.archive, parent)).strip()
    if git_text(repo, "show", "-s", "--format=%B", ship_commit).strip() != expected:
        raise IsolationError("ship commit message is not canonical")
    for row in receipt["tasks"]:
        name = Path(str(row["path"])).name
        task = _real_file(repo, f"{state.archive}/tasks/{name}", "archived task")
        if _read_task_text(task)[0] != row["adopted_task"]:
            raise IsolationError("archived task differs from adopted record")
    return parent


def attest(
    primary: Path, task_file: str, ruling: str, base: Optional[str] = None
) -> Dict[str, object]:
    """Record an owner ruling that a done task's work is already on the branch.

    The attestation is one .project/-only commit that stamps the task's landed
    state (and carries an uncommitted verify-ledger line) and names the base,
    the attested HEAD, the declared files that changed between them, the task
    Verify recorded as passing at that HEAD, and the ruling verbatim. `recover`
    reports it as `attested`, never `recovered`.
    """
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_bound(primary)
    task_file = relative_posix(task_file)
    if not task_file.startswith(".project/tasks/"):
        raise IsolationError("task file must live under .project/tasks/")
    ruling_text = " ".join(ruling.split())
    if not ruling_text:
        raise IsolationError("--ruling must not be empty")
    pending = uncommitted_paths(primary)
    dirty = sorted(pending - BOOKKEEPING_PATHS)
    if dirty:
        raise IsolationError("primary worktree is dirty: " + ", ".join(dirty))
    head = current_sha(primary)
    task_path = primary / task_file
    task_text, task_mode = _read_task_text(task_path)
    fields, error = task_frontmatter(task_text)
    if error or fields is None:
        raise IsolationError(error or "unreadable task frontmatter")
    task_id, title = str(fields.get("id", "")), str(fields.get("title", ""))
    validate_task_id(task_id)
    if fields.get("status") != "done":
        raise IsolationError("only a done task can be attested")
    try:
        subject = attest_commit_subject(task_id, title)
    except ValueError as exc:
        raise IsolationError(str(exc)) from exc
    report = recover(primary, Path(task_file).parent)
    mine = next((task for task in report["tasks"] if task.get("task_id") == task_id), None)
    if mine is None:
        raise IsolationError(f"task recovery did not report {task_id}: {report.get('reason', '')}")
    if mine["verdict"] in LANDED_VERDICTS:
        raise IsolationError(f"task is already {mine['verdict']} at {mine['commit']}")
    reason = str(mine.get("reason", ""))
    if mine["verdict"] != "block" or not reason.startswith(
        ("done but no landing commit proves it", "done task has invalid base")
    ):
        raise IsolationError(f"task recovery is not a missing landing: {reason or mine['verdict']}")
    if mine.get("rejected"):
        raise IsolationError(
            "task has rejected landing evidence on the branch; resolve it before attesting: "
            + "; ".join(str(item.get("reason", "")) for item in mine["rejected"])
        )
    if mine.get("worktree") is not None or mine.get("task_branch") is not None:
        raise IsolationError("task retains isolation; retire it before attesting")
    recorded = str(fields.get("base", ""))
    resolved_base = require_commit(primary, base or recorded)
    if base and recorded not in {"", "null"} and not resolved_base.startswith(recorded):
        raise IsolationError("--base may only repair the recorded base, not replace it")
    if run_git(primary, "merge-base", "--is-ancestor", resolved_base, head).returncode != 0:
        raise IsolationError("base is not an ancestor of HEAD")
    _regular_blob_oid(primary, resolved_base, task_file)
    contract_error = _task_contract_error(
        git_text(primary, "show", f"{resolved_base}:{task_file}"), task_text, "task"
    )
    if contract_error:
        raise IsolationError(contract_error + "; only landing metadata and an appended log may change")
    declared, declared_error = _declared_task_paths(fields)
    if declared_error or declared is None:
        raise IsolationError(declared_error or "task files are unreadable")
    changed = _attested_changes(primary, resolved_base, head, declared)
    if not changed:
        raise IsolationError("no declared file changed between the base and HEAD; nothing to attest")
    verify = task_verify_command(task_text)
    if not verify:
        raise IsolationError("task has no ## Verify bash command")
    if not _verify_ledger_pass(primary, verify, head):
        raise IsolationError(
            f"verify ledger has no passing run of the task Verify at {head}; "
            "run it and record it with build_state.py verify-record first"
        )
    frontmatter, body = split_frontmatter(task_text)
    frontmatter = [
        f"base: {resolved_base}" if _frontmatter_key(line) == "base" else line
        for line in frontmatter
    ]
    normalized = "---\n" + "\n".join(frontmatter) + "\n---\n" + body
    stamped = _landed_task_text(normalized, resolved_base)
    if not stamped.endswith("\n"):
        stamped += "\n"
    stamped += f"- attested: {ruling_text}\n"
    task_bytes = task_text.encode("utf-8")
    index_tree = git_output(primary, "write-tree")
    commit_body = attest_commit_body(task_file, resolved_base, head, changed, verify, ruling_text)
    try:
        _replace_regular_file(task_path, stamped.encode("utf-8"), task_mode)
        # The ledger line proving Verify at HEAD travels inside the attestation.
        commit = _commit_pending(
            primary, {task_file, *(pending & {VERIFY_LEDGER_PATH})}, subject, commit_body
        )
    except BaseException as error:
        try:
            _restore_landing_state(primary, task_path, task_bytes, task_mode, index_tree)
        except IsolationError as restore_error:
            raise IsolationError(f"{error}; {restore_error}") from error
        raise
    _, proof_error = _prove_attest_commit(primary, commit, commit_body.strip(), task_file, stamped)
    if proof_error:
        # Move HEAD back and restore the index and task file; leave every other
        # worktree path (ledger, discussion records) exactly as it was.
        if current_sha(primary) != commit:
            raise IsolationError("HEAD moved after the rejected attestation commit")
        moved = run_git(primary, "update-ref", "HEAD", head, commit)
        if moved.returncode != 0:
            raise IsolationError((moved.stderr or moved.stdout).strip() or "could not restore HEAD")
        _restore_landing_state(primary, task_path, task_bytes, task_mode, index_tree)
        raise IsolationError(f"attestation proof failed: {proof_error}")
    return {
        "bound_branch": bound,
        "commit": commit,
        "base": resolved_base,
        "head": head,
        "files": changed,
        "subject": subject,
        "verdict": "attested",
    }


def checkpoint(
    repo: Path,
    expected_head: str,
    subject: str,
    body: str,
    allow_paths: Sequence[str],
) -> Dict[str, object]:
    """Create one allowlisted pipeline checkpoint with a canonical message."""

    repo = require_directory(repo, "primary worktree")
    if worktree_root(repo) != repo:
        raise IsolationError(f"primary is not its Git root: {repo}")
    require_bound(repo)
    expected = require_commit(repo, require_full_sha(expected_head))
    _validate_checkpoint_message(subject.strip(), body)
    allowed = [relative_posix(path).rstrip("/") for path in allow_paths]
    if not allowed or any(
        path in {"", "."}
        or not (path == ".project" or path.startswith(".project/"))
        for path in allowed
    ):
        raise IsolationError("checkpoint allow paths must stay under .project/")
    current = current_sha(repo)
    if current != expected:
        parents = git_output(repo, "show", "-s", "--format=%P", current).split()
        actual_subject = git_output(repo, "show", "-s", "--format=%s", current)
        actual_body = git_output(repo, "show", "-s", "--format=%b", current)
        paths = committed_paths_since(repo, expected) if parents == [expected] else set()
        paths_allowed = paths and all(
            any(
                path == allowed_path or path.startswith(allowed_path + "/")
                for allowed_path in allowed
            )
            for path in paths
        )
        if (
            parents == [expected]
            and actual_subject == subject.strip()
            and actual_body == body.strip()
            and paths_allowed
            and not uncommitted_paths(repo)
        ):
            return {
                "commit": current,
                "paths": sorted(paths),
                "status": "already-complete",
                "subject": subject.strip(),
            }
        raise IsolationError("primary HEAD differs from --expected-head")
    pending = uncommitted_paths(repo)
    if not pending:
        raise IsolationError("no changes to checkpoint")
    unexpected = sorted(
        path
        for path in pending
        if not any(
            path == allowed_path or path.startswith(allowed_path + "/")
            for allowed_path in allowed
        )
    )
    if unexpected:
        raise IsolationError("unexpected paths: " + ", ".join(unexpected))
    normalized_subject = subject.strip()
    if normalized_subject.startswith("build:"):
        # Build owns fix-task additions and brief repairs, never the task
        # inventory: a deleted or renamed brief is a replan. Abandon moves
        # briefs into .project/archive/ inside the same checkpoint.
        abandon = re.fullmatch(
            r"build: abandon milestone [a-z0-9][a-z0-9-]*", normalized_subject
        )
        archived = set()
        if abandon:
            for path in pending:
                match = re.fullmatch(
                    r"\.project/archive/[^/]+/tasks/([^/]+\.md)", path
                )
                if match and (repo / path).is_file():
                    archived.add(match.group(1))
        removed = sorted(
            path
            for path in pending
            if path.startswith(".project/tasks/")
            and path.endswith(".md")
            and "/" not in path[len(".project/tasks/") :]
            and not (repo / path).is_file()
            and path.rsplit("/", 1)[1] not in archived
        )
        if removed:
            raise IsolationError(
                "build checkpoints never delete or rename task briefs: "
                + ", ".join(removed)
            )
    return {
        "commit": _commit_pending(repo, pending, normalized_subject, body),
        "paths": sorted(pending),
        "status": "committed",
        "subject": normalized_subject,
    }


def _unlanded_task_commits(repo: Path, bound: str, branch: str) -> list[str]:
    """Return branch commits whose patch is not on the bound branch."""
    return [
        line[2:]
        for line in git_output(repo, "cherry", bound, branch).splitlines()
        if line.startswith("+ ")
    ]


def _require_landed_task_branch(
    primary: Path,
    bound: str,
    branch: str,
    landed_commit: Optional[str],
    task_file: Optional[str],
) -> None:
    """Refuse to delete a task branch while it still holds unlanded commits."""
    unlanded = _unlanded_task_commits(primary, bound, branch)
    if not unlanded:
        return
    if landed_commit:
        landed = require_commit(primary, require_full_sha(landed_commit))
        _require_first_parent_commit(primary, bound, landed)
        base = _landing_base(primary, landed)
        proof_error = _task_branch_proof_error(primary, branch, base, landed)
    elif task_file:
        proof_error = _failed_task_branch_proof_error(primary, branch, task_file)
    else:
        proof_error = (
            "pass --landed-commit <landing commit> or --task-file <failed task file>"
        )
    if proof_error:
        raise IsolationError(
            f"refusing to retire {branch}: {len(unlanded)} commit(s) are not landed "
            f"on {bound}: {', '.join(unlanded)}; {proof_error}; run: "
            f"python3 {Path(__file__).resolve()} recover --repo {primary}"
        )


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
            if branch == bound:
                raise IsolationError("refusing to delete the bound branch")
            if not (
                branch.startswith(TASK_BRANCH_PREFIX)
                or branch.startswith(VERIFY_BRANCH_PREFIX)
            ):
                raise IsolationError(f"refusing to retire unrecognized branch {branch}")
            _delete_task_authorization(primary, branch)
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
    if retire_branch.startswith(TASK_BRANCH_PREFIX):
        _require_landed_task_branch(
            primary, bound, retire_branch, landed_commit, task_file
        )
    _delete_task_authorization(primary, retire_branch)
    if not force:
        dirty = git_output(
            resolved_worktree, "status", "--porcelain", "--untracked-files=all"
        )
        if dirty:
            raise IsolationError(
                "worktree is dirty; pass --force only from the retry-retirement path"
            )
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

    activate_task_parser = subparsers.add_parser(
        "activate-task", help="record one helper-owned task dispatch"
    )
    activate_task_parser.add_argument("--repo", type=Path, required=True)
    activate_task_parser.add_argument("--base", required=True)
    activate_task_parser.add_argument("--task-id", required=True)
    activate_task_parser.add_argument("--agent", required=True)
    activate_task_parser.add_argument("--task-file", required=True)
    activate_task_parser.add_argument("--task-branch")

    deactivate_task_parser = subparsers.add_parser(
        "deactivate-task", help="revoke one helper-owned task dispatch"
    )
    deactivate_task_parser.add_argument("--repo", type=Path, required=True)
    deactivate_task_parser.add_argument("--task-id", required=True)
    deactivate_task_parser.add_argument("--task-branch", required=True)

    isolate_verify_parser = subparsers.add_parser(
        "isolate-verify", help="create a named verify sidecar"
    )
    isolate_verify_parser.add_argument("--repo", type=Path, required=True)
    isolate_verify_parser.add_argument("--base", required=True)
    isolate_verify_parser.add_argument("--name", required=True)
    isolate_verify_parser.add_argument("--historical-task")

    land_parser = subparsers.add_parser("land", help="commit a task onto the bound branch")
    land_parser.add_argument("--repo", type=Path, required=True)
    land_parser.add_argument("--source", type=Path, required=True)
    land_parser.add_argument("--base", required=True)
    land_parser.add_argument("--task-id", required=True)
    land_parser.add_argument("--title", required=True)
    land_parser.add_argument("--task-file", required=True)
    land_parser.add_argument("--allow-path", action="append", default=[], dest="allow_paths")

    attest_parser = subparsers.add_parser(
        "attest", help="record an owner ruling that a done task's work is already on the branch"
    )
    attest_parser.add_argument("--repo", type=Path, required=True)
    attest_parser.add_argument("--task-file", required=True)
    attest_parser.add_argument("--ruling", required=True)
    attest_parser.add_argument("--base", help="full or abbreviated base SHA; defaults to the task's recorded base")

    adopt_parser = subparsers.add_parser(
        "adopt-rebase", help="record an owner ruling adopting every done task's rebased landing"
    )
    adopt_parser.add_argument("--repo", type=Path, required=True)
    adopt_parser.add_argument("--original-head", required=True, help="preserved original tip, full SHA")
    adopt_parser.add_argument("--head", required=True, help="rebased HEAD being adopted, full SHA")
    adopt_parser.add_argument("--ruling", required=True)

    recover_parser = subparsers.add_parser(
        "recover", help="prove landed task commits from git; read-only"
    )
    recover_parser.add_argument("--repo", type=Path, required=True)
    recover_parser.add_argument("--tasks-dir", type=Path, default=Path(".project/tasks"))

    collect_parser = subparsers.add_parser(
        "collect-artifact", help="atomically collect one verified sidecar artifact"
    )
    collect_parser.add_argument("--repo", type=Path, required=True)
    collect_parser.add_argument("--source", type=Path, required=True)
    collect_parser.add_argument("--base", required=True)
    collect_parser.add_argument("--branch", required=True)
    collect_parser.add_argument("--source-path", required=True)
    collect_parser.add_argument("--destination-path", required=True)
    collect_parser.add_argument(
        "--expected-destination",
        help="base or the recorded SHA-256 of an existing destination",
    )

    checkpoint_parser = subparsers.add_parser(
        "checkpoint", help="commit allowlisted pipeline bookkeeping"
    )
    checkpoint_parser.add_argument("--repo", type=Path, required=True)
    checkpoint_parser.add_argument("--expected-head", required=True)
    checkpoint_parser.add_argument("--subject", required=True)
    checkpoint_parser.add_argument("--body", required=True)
    checkpoint_parser.add_argument(
        "--allow-path", action="append", required=True, dest="allow_paths"
    )

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
        elif arguments.command == "activate-task":
            result = activate_task(
                arguments.repo,
                arguments.base,
                arguments.task_id,
                arguments.agent,
                arguments.task_file,
                arguments.task_branch,
            )
        elif arguments.command == "deactivate-task":
            result = deactivate_task(
                arguments.repo,
                arguments.task_id,
                arguments.task_branch,
            )
        elif arguments.command == "isolate-verify":
            result = isolate_verify(arguments.repo, arguments.base, arguments.name, arguments.historical_task)
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
        elif arguments.command == "attest":
            result = attest(
                arguments.repo, arguments.task_file, arguments.ruling, arguments.base
            )
        elif arguments.command == "adopt-rebase":
            result = record_rebase_adoption(
                arguments.repo, arguments.original_head, arguments.head, arguments.ruling
            )
        elif arguments.command == "recover":
            result = recover(arguments.repo, arguments.tasks_dir)
        elif arguments.command == "collect-artifact":
            result = collect_artifact(
                arguments.repo,
                arguments.source,
                arguments.base,
                arguments.branch,
                arguments.source_path,
                arguments.destination_path,
                arguments.expected_destination,
            )
        elif arguments.command == "checkpoint":
            result = checkpoint(
                arguments.repo,
                arguments.expected_head,
                arguments.subject,
                arguments.body,
                arguments.allow_paths,
            )
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
