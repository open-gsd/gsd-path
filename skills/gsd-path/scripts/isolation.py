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
FIELD_PATTERN = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>[^#]*?)(?:\s+#.*)?$")
INLINE_LIST_PATTERN = re.compile(r"^\[(?P<body>.*)\]$")
LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<value>.*?)\s*(?:\s+#.*)?$")


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


def validate_allowed_changes(
    repo: Path, base: str, pending: Set[str], allowed: Set[str]
) -> None:
    if not pending:
        raise IsolationError("no changes to land")
    since_base = committed_paths_since(repo, base) | pending
    unexpected = sorted(path for path in since_base if path not in allowed)
    if unexpected:
        raise IsolationError("unexpected paths: " + ", ".join(unexpected))


def commit_allowed_changes(
    repo: Path,
    base: str,
    subject: str,
    allowed: Set[str],
    body: str,
) -> str:
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
    committed = run_git(repo, "commit", "-q", "-m", subject, "-m", body)
    if committed.returncode != 0:
        raise IsolationError(
            (committed.stderr or committed.stdout).strip() or "commit failed"
        )
    return current_sha(repo)


def split_frontmatter(text: str) -> tuple[list[str], str]:
    """Return (frontmatter lines without the --- fences, body text)."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        raise IsolationError("task file has no frontmatter")
    for index in range(1, len(lines)):
        if lines[index].rstrip("\r\n") == "---":
            return [line.rstrip("\r\n") for line in lines[1:index]], "".join(lines[index + 1 :])
    raise IsolationError("task file frontmatter is not closed")


def _unquote(value: str) -> str:
    return value.strip().strip("\"'")


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
        value = match.group("value").strip()
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
            found.add(key)
            lines.append(f"{key}: {values[key]}")
        else:
            lines.append(line)
    missing = sorted(values.keys() - found)
    if missing:
        raise IsolationError("task frontmatter missing landing fields: " + ", ".join(missing))
    return "---\n" + "\n".join(lines) + "\n---\n" + body


def stamp_task_landed(task_path: Path, base: str) -> None:
    """Write the orchestrator-owned landing state into the task frontmatter."""
    text = task_path.read_text(encoding="utf-8")
    task_path.write_text(_landed_task_text(text, base), encoding="utf-8")


def _restore_landing_state(
    worktree: Path, task_path: Path, task_bytes: bytes, index_tree: str
) -> None:
    errors = []
    try:
        task_path.write_bytes(task_bytes)
    except OSError as error:
        errors.append(str(error))
    restored = run_git(worktree, "read-tree", index_tree)
    if restored.returncode != 0:
        errors.append((restored.stderr or restored.stdout).strip() or "index restore failed")
    if errors:
        raise IsolationError("could not restore landing state: " + "; ".join(errors))


def _stamp_and_commit(
    worktree: Path, base: str, subject: str, task_file: str, allowed: Set[str]
) -> str:
    task_path = worktree / task_file
    task_bytes = task_path.read_bytes()
    stamped = _landed_task_text(task_bytes.decode("utf-8"), base).encode("utf-8")
    pending = uncommitted_paths(worktree)
    if stamped != task_bytes:
        pending.add(task_file)
    validate_allowed_changes(worktree, base, pending, allowed)
    original_head = current_sha(worktree)
    index_tree = git_output(worktree, "write-tree")
    try:
        task_path.write_bytes(stamped)
        body = task_commit_body(task_file, uncommitted_paths(worktree), base)
        return commit_allowed_changes(worktree, base, subject, allowed, body)
    except Exception as error:
        if current_sha(worktree) != original_head:
            raise IsolationError("landing failed after HEAD changed; refusing rollback") from error
        try:
            _restore_landing_state(worktree, task_path, task_bytes, index_tree)
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
        commit = _stamp_and_commit(primary, resolved_base, subject, relative_posix(task_file), allowed)
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
        source_commit = _stamp_and_commit(
            source, resolved_base, subject, relative_posix(task_file), allowed
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
            relative_posix(task_file), changed_paths, resolved_base
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


def _patch_id(repo: Path, rev_range: str) -> str:
    diff = git_output(repo, "diff", rev_range)
    result = run_git(repo, "patch-id", "--stable", input=diff + "\n") if diff else None
    return result.stdout.split()[0] if result and result.stdout.strip() else ""


def git_text(repo: Path, *arguments: str) -> str:
    result = run_git(repo, *arguments)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git command failed"
        raise IsolationError(detail)
    return result.stdout


def _frontmatter_key(line: str) -> Optional[str]:
    match = FIELD_PATTERN.match(line)
    return match.group("key") if match is not None else None


def _landing_transition_error(
    before_head: Sequence[str],
    after_head: Sequence[str],
    before_fields: Dict[str, object],
    after_fields: Dict[str, object],
    base: str,
) -> Optional[str]:
    for key in LANDING_MUTABLE_FIELDS:
        if sum(_frontmatter_key(line) == key for line in before_head) != 1:
            return f"parent task frontmatter must contain one {key} field"
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
        return "parent task is already done"
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
        return None, "parent task frontmatter has invalid files"
    try:
        return {relative_posix(item) for item in raw_files}, None
    except IsolationError as error:
        return None, str(error)


def _prove_task_commit(
    repo: Path,
    sha: str,
    body: str,
    task_file: str,
    expected_base: str,
    current_task_text: str,
) -> tuple[Optional[str], Optional[str]]:
    """Return (base, None) when `sha` is this task's landing commit, else (None, reason)."""
    base = next((line[6:].strip() for line in body.splitlines() if line.startswith("Base: ")), None)
    if not base:
        return None, "body has no Base: field"
    if base != expected_base:
        return None, "body Base: differs from the task's recorded base"
    if run_git(repo, "merge-base", "--is-ancestor", base, f"{sha}^").returncode != 0:
        return None, "commit does not descend from its Base:"
    try:
        before_text = git_text(repo, "show", f"{sha}^:{task_file}")
        after_text = git_text(repo, "show", f"{sha}:{task_file}")
        before_head, before_body = split_frontmatter(before_text)
        after_head, after_body = split_frontmatter(after_text)
    except IsolationError as error:
        return None, str(error)
    before_fields, before_error = task_frontmatter(before_text)
    after_fields, after_error = task_frontmatter(after_text)
    if before_error or before_fields is None:
        return None, before_error or "parent task frontmatter is unreadable"
    if after_error or after_fields is None:
        return None, after_error or "landed task frontmatter is unreadable"
    files, files_error = _declared_task_paths(before_fields)
    if files_error or files is None:
        return None, files_error or "parent task files are unreadable"
    changed = set(git_output(repo, "diff-tree", "--no-commit-id", "--name-only", "-r", sha).splitlines())
    if task_file not in changed:
        return None, "commit does not touch the task file"
    stray = sorted(changed - {task_file, *files})
    if stray:
        return None, f"commit touches undeclared paths: {', '.join(stray)}"
    if body != task_commit_body(task_file, changed, base).strip():
        return None, "body Task:/Files: fields do not match the changed paths"
    transition_error = _landing_transition_error(
        before_head, after_head, before_fields, after_fields, base
    )
    if transition_error:
        return None, transition_error
    if not after_body.startswith(before_body):
        return None, "task file body is not append-only"
    if after_text != current_task_text:
        return None, "current done task differs from its landing commit"
    return base, None


def _worktree_report(path: Path) -> Optional[Dict[str, object]]:
    if not path.is_dir() or run_git(path, "rev-parse", "--git-dir").returncode != 0:
        return None
    return {
        "path": str(path),
        "branch": require_attached(path),
        "clean": not git_output(path, "status", "--porcelain", "--untracked-files=all"),
    }


def _recover_task(
    primary: Path,
    path: Path,
    history: Dict[str, list[tuple[str, str]]],
    branches: Set[str],
    head: str,
) -> Dict[str, object]:
    task_text = path.read_text(encoding="utf-8")
    fields, error = task_frontmatter(task_text)
    task_file = relative_posix(str(path.relative_to(primary)))
    report: Dict[str, object] = {"task": task_file}

    def result(verdict: str, **extra: object) -> Dict[str, object]:
        return {**report, "verdict": verdict, **extra}

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
    report["worktree"] = _worktree_report(sidecar_root(primary, "task", task_id))
    report["rejected"] = []

    if status != "done":
        if status == "in-progress" or branch_exists or report["worktree"] is not None:
            if branch_exists:
                base = git_output(primary, "merge-base", head, task_branch)
            else:
                recorded_base = str(fields.get("base", ""))
                try:
                    base = require_commit(primary, require_full_sha(recorded_base))
                except IsolationError as error:
                    return result("block", reason=f"in-progress task has invalid base: {error}")
                report["worktree"] = _worktree_report(primary)
            return result("resume", base=base, task_branch=task_branch if branch_exists else None)
        return result("none", reason=f"status {status!r} needs no recovery")

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
        if branch_exists and _patch_id(primary, f"{base}..{task_branch}") != _patch_id(primary, f"{commit}^..{commit}"):
            return result("block", reason="retained task branch differs from the landing commit")
        return result("recovered", commit=commit, base=base)
    return result("block", reason="done but no landing commit proves it")


def recover(primary: Path, tasks_dir: Path) -> Dict[str, object]:
    """Prove each task's landing state from git. Read-only.

    Verdicts: `recovered` (exactly one proven landing commit; `commit` and
    `base` returned), `resume` (in flight: no landing yet, derived `base` and
    any retained `task_branch`/worktree returned), `block` (missing or
    conflicting proof), `none` (nothing to recover). Verify is not rerun: a
    proven landing commit is its own evidence.
    """
    primary = require_directory(primary, "primary worktree")
    if worktree_root(primary) != primary:
        raise IsolationError(f"primary is not its Git root: {primary}")
    bound = require_attached(primary)
    tasks_dir = tasks_dir if tasks_dir.is_absolute() else primary / tasks_dir
    if not tasks_dir.is_dir():
        raise IsolationError(f"tasks directory missing: {tasks_dir}")
    history: Dict[str, list[tuple[str, str]]] = {}
    log = git_output(primary, "log", "--first-parent", "--format=%x1e%H%x00%s%x00%b", bound)
    for record in filter(None, log.split("\x1e")):
        sha, subject, body = record.split("\x00", 2)
        history.setdefault(subject, []).append((sha, body.strip()))
    branches = set(
        git_output(primary, "for-each-ref", "--format=%(refname:short)", f"refs/heads/{TASK_BRANCH_PREFIX}").splitlines()
    )
    head = current_sha(primary)
    tasks = [_recover_task(primary, path, history, branches, head) for path in sorted(tasks_dir.glob("*.md"))]
    return {
        "bound_branch": bound,
        "tasks": tasks,
        "verdict": "block" if any(t["verdict"] == "block" for t in tasks) else "ok",
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

    recover_parser = subparsers.add_parser(
        "recover", help="prove landed task commits from git; read-only"
    )
    recover_parser.add_argument("--repo", type=Path, required=True)
    recover_parser.add_argument("--tasks-dir", type=Path, default=Path(".project/tasks"))

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
        elif arguments.command == "recover":
            result = recover(arguments.repo, arguments.tasks_dir)
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
