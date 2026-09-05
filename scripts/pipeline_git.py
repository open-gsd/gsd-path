#!/usr/bin/env python3
# gsd-path project runtime
"""Deterministic GSD Path branch names and pipeline commit messages.

Bound work lives on `gsd-path/M00N` for that milestone. The required remote
default `main` stays a separate trunk. Ship merges the bound branch onto main;
the next milestone binds a new unused `gsd-path/M00N` and retires the
integrated previous branch, locally and on origin.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path
from typing import Optional, Sequence

try:
    import _common
except ImportError:  # pragma: no cover - package import used by tests
    from scripts import _common


ARCHIVE_NAME_RE = re.compile(r"^(\d{3,})-([a-z0-9][a-z0-9-]*)$")
BOUND_BRANCH_RE = _common.BOUND_BRANCH_RE
MILESTONE_ID_RE = re.compile(r"^M(\d{3,})$")

LEGACY_SHIP_PREFIX = "ship: "
LEGACY_INTEGRATE_PREFIX = "integrate: "
LEGACY_BIND_NEXT_JOURNAL_SCHEMA = "gsd-path/bind-next-journal/v1"
BIND_NEXT_JOURNAL_SCHEMA = "gsd-path/bind-next-journal/v2"
BIND_NEXT_JOURNAL_DIR = "gsd-path-bind-next"


class PipelineGitError(ValueError):
    """Raised when a milestone id, archive name, or branch cannot be derived."""


def milestone_id(number: int) -> str:
    if number < 1:
        raise PipelineGitError(f"milestone number must be >= 1, got {number}")
    return f"M{number:03d}"


def milestone_number(token: str) -> int:
    bound = BOUND_BRANCH_RE.fullmatch(token)
    if bound:
        number = int(bound.group(1))
        if number < 1:
            raise PipelineGitError(f"milestone number must be >= 1, got {number}")
        return number
    milestone = MILESTONE_ID_RE.fullmatch(token)
    if milestone:
        number = int(milestone.group(1))
        if number < 1:
            raise PipelineGitError(f"milestone number must be >= 1, got {number}")
        return number
    archive = ARCHIVE_NAME_RE.fullmatch(token)
    if archive:
        number = int(archive.group(1))
        if number < 1:
            raise PipelineGitError(f"milestone number must be >= 1, got {number}")
        return number
    raise PipelineGitError(f"not a milestone id, bound branch, or archive name: {token}")


def bound_branch_name(number: int) -> str:
    return f"gsd-path/{milestone_id(number)}"


def is_bound_branch(name: str) -> bool:
    match = BOUND_BRANCH_RE.fullmatch(name)
    return match is not None and int(match.group(1)) >= 1


def archive_slug(archive_name: str) -> str:
    match = ARCHIVE_NAME_RE.fullmatch(archive_name)
    if not match:
        raise PipelineGitError(f"invalid archive name: {archive_name}")
    milestone_number(archive_name)
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


def attest_commit_subject(task_id: str, title: str) -> str:
    cleaned = title.strip()
    if not cleaned:
        raise PipelineGitError("title is empty")
    return f"attest: {task_id} — {cleaned}"


def attest_commit_body(
    task_file: str,
    base: str,
    head: str,
    paths: Sequence[str],
    verify_command: str,
    ruling: str,
    *,
    legacy: bool = False,
) -> str:
    lines = [f"Task: {task_file}", f"Base: {base}", f"Head: {head}", "Files:"]
    lines.extend(f"- {path}" for path in sorted(paths))
    if legacy:
        lines.append(f"Verify: {' '.join(verify_command.split())}")
    else:
        lines.append("Attestation: gsd-path/attestation/v2")
        lines.append(f"Verify-JSON: {json.dumps(verify_command)}")
    lines.append(f"Ruling: {' '.join(ruling.split())}")
    return "\n".join(lines) + "\n"


def task_commit_body(task_file: str, paths: Sequence[str], base: str) -> str:
    ordered = sorted(paths)
    lines = [f"Task: {task_file}", f"Base: {base}", "Files:"]
    if ordered:
        lines.extend(f"- {path}" for path in ordered)
    else:
        lines.append("- (none)")
    return "\n".join(lines) + "\n"


def default_branch_name(remote_default: str) -> str:
    if remote_default.startswith("origin/"):
        return remote_default.removeprefix("origin/")
    return remote_default


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


def _origin_remote_exists(repo: Path) -> bool:
    result = _run_git(repo, "remote", "get-url", "origin", check=False)
    return result.returncode == 0


def _require_worktree_root(repo: Path) -> Path:
    if repo.is_symlink() or not repo.is_dir():
        raise PipelineGitError(f"repo must be a real worktree directory: {repo}")
    resolved = repo.resolve()
    top = _run_git(resolved, "rev-parse", "--show-toplevel").stdout.strip()
    if Path(top).resolve() != resolved:
        raise PipelineGitError(f"repo must be the worktree root: {resolved}")
    return resolved


def _symbolic_branch(repo: Path) -> str:
    result = _run_git(
        repo,
        "symbolic-ref",
        "--quiet",
        "--short",
        "HEAD",
        check=False,
    )
    if result.returncode != 0:
        raise PipelineGitError("primary worktree must be on a named branch")
    return result.stdout.strip()


def _branch_worktrees(repo: Path) -> dict[str, Path]:
    """Return every checked-out local branch from Git's worktree registry."""
    output = _run_git(repo, "worktree", "list", "--porcelain", "-z").stdout
    worktrees: dict[str, Path] = {}
    current_path: Optional[Path] = None
    for field in output.split("\0"):
        if field.startswith("worktree "):
            current_path = Path(field.removeprefix("worktree ")).resolve()
        elif field.startswith("branch ") and current_path is not None:
            ref = field.removeprefix("branch ")
            prefix = "refs/heads/"
            if ref.startswith(prefix):
                worktrees[ref.removeprefix(prefix)] = current_path
    return worktrees


def _remote_ref_sha(repo: Path, ref: str) -> Optional[str]:
    if not _origin_remote_exists(repo):
        raise PipelineGitError("origin remote is not configured")
    result = _run_git(
        repo,
        "ls-remote",
        "--exit-code",
        "--heads",
        "origin",
        ref,
        check=False,
    )
    if result.returncode == 0:
        rows = [line.split("\t", 1) for line in result.stdout.splitlines() if line]
        if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
            raise PipelineGitError(f"origin returned ambiguous ref data for {ref}")
        return rows[0][0]
    if result.returncode == 2:
        return None
    raise PipelineGitError(f"could not inspect {ref} on origin: git ls-remote failed")


def _remote_branch_exists(repo: Path, branch: str) -> bool:
    return _remote_ref_sha(repo, f"refs/heads/{branch}") is not None


def _pull_request_tag_fields(repo: Path, ref: str) -> dict[str, str]:
    tag_type = _run_git(repo, "cat-file", "-t", ref, check=False)
    if tag_type.returncode != 0 or tag_type.stdout.strip() != "tag":
        return {}
    contents = _run_git(repo, "for-each-ref", "--format=%(contents)", ref).stdout
    fields: dict[str, str] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"(Mode|Pull-Request|Ship|Landing): (.+)", line)
        if match:
            if match.group(1) in fields:
                raise PipelineGitError("pull-request milestone tag repeats metadata")
            fields[match.group(1)] = match.group(2)
    return fields


def _validated_shipped_state(repo: Path) -> dict[str, object]:
    validator = Path(__file__).with_name("pipeline_state.py")
    result = subprocess.run(
        [
            sys.executable,
            str(validator),
            "validate",
            "--repo",
            str(repo),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PipelineGitError(f"could not validate shipped STATE.md: {detail}")
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise PipelineGitError("pipeline state validator returned invalid JSON") from error
    state = payload.get("state") if isinstance(payload, dict) else None
    if not isinstance(state, dict):
        raise PipelineGitError("pipeline state validator omitted state")
    return state


def _require_pull_request_integration_proof(
    repo: Path,
    ship: str,
    base: str,
    previous_branch: str,
) -> str:
    state = _validated_shipped_state(repo)
    if state.get("phase") != "shipped" or state.get("status") != "done":
        raise PipelineGitError("bind-next requires shipped/done state")
    if state.get("branch") != previous_branch:
        raise PipelineGitError("shipped state does not name the previous branch")
    if state.get("integration") != "pull-request":
        raise PipelineGitError("shipped integration mode is not pull-request")
    archive = state.get("archive")
    if not isinstance(archive, str):
        raise PipelineGitError("shipped state does not name an archive")
    archive_pattern = r"\.project/archive/(\d{3,}-[a-z0-9][a-z0-9-]*)/?"
    match = re.fullmatch(archive_pattern, archive)
    if match is None or milestone_number(match.group(1)) != milestone_number(
        previous_branch
    ):
        raise PipelineGitError("shipped archive does not match the previous branch")
    ref = f"refs/tags/milestone/{match.group(1)}"
    fields = _pull_request_tag_fields(repo, ref)
    if set(fields) != {"Mode", "Pull-Request", "Ship", "Landing"}:
        raise PipelineGitError("pull-request integration proof is incomplete")
    if fields["Mode"] != "pull-request" or fields["Ship"] != ship:
        raise PipelineGitError("pull-request integration proof does not match shipped state")
    pull_request = fields["Pull-Request"]
    if re.fullmatch(
        r"https://github\.com/[^/]+/[^/]+/pull/[1-9][0-9]*",
        pull_request,
    ) is None:
        raise PipelineGitError("pull-request integration proof has an invalid PR URL")
    landing = fields["Landing"]
    if re.fullmatch(r"[0-9a-f]{40}", landing) is None:
        raise PipelineGitError("pull-request integration proof has an invalid landing")
    local_object = _run_git(repo, "rev-parse", ref).stdout.strip()
    local_target = _run_git(repo, "rev-parse", f"{ref}^{{commit}}").stdout.strip()
    if local_target != landing:
        raise PipelineGitError("pull-request integration tag does not point at landing")
    remote = _run_git(
        repo,
        "ls-remote",
        "--exit-code",
        "--tags",
        "origin",
        ref,
        f"{ref}^{{}}",
        check=False,
    )
    if remote.returncode != 0:
        raise PipelineGitError("pull-request integration tag is not published")
    rows = dict(
        line.split("\t", 1)[::-1]
        for line in remote.stdout.splitlines()
        if "\t" in line
    )
    if rows != {ref: local_object, f"{ref}^{{}}": landing}:
        raise PipelineGitError("published pull-request integration tag differs")
    parents = _run_git(
        repo,
        "rev-list",
        "--parents",
        "-n",
        "1",
        landing,
    ).stdout.split()
    if len(parents) != 3 or parents[2] != ship:
        raise PipelineGitError("pull-request integration proof has invalid merge topology")
    first_parent = _run_git(repo, "rev-list", "--first-parent", base).stdout.splitlines()
    if landing not in first_parent:
        raise PipelineGitError(
            "pull-request integration landing is not on main first-parent history"
        )
    return landing


def _git_path(repo: Path, name: str) -> Path:
    value = _run_git(repo, "rev-parse", "--git-path", name).stdout.strip()
    path = Path(value)
    if not path.is_absolute():
        path = repo / path
    return path.resolve()


def bind_next_journal_path(repo: Path, branch: str) -> Path:
    """Return the durable ownership journal path for one target branch."""
    if not is_bound_branch(branch):
        raise PipelineGitError(f"invalid bound branch: {branch}")
    return _git_path(repo, BIND_NEXT_JOURNAL_DIR) / f"M{milestone_number(branch):03d}.json"


def _read_bind_next_journal(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise PipelineGitError(f"bind-next journal must be a real file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PipelineGitError(f"bind-next journal is unreadable: {path}: {error}") from error
    if not isinstance(value, dict):
        raise PipelineGitError(f"bind-next journal must contain an object: {path}")
    return value


def _write_bind_next_journal(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise PipelineGitError(f"bind-next journal temporary path exists: {temporary}")
    descriptor: Optional[int] = None
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
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


def _initial_binding_snapshot(repo: Path) -> Optional[tuple]:
    """Admit only clean work or the validated, untracked initializer state."""
    dirty = _run_git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=all").stdout
    if not dirty:
        return None
    if dirty != "?? .project/STATE.md\0":
        raise PipelineGitError("primary worktree is not clean")
    try:
        import pipeline_state
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import pipeline_state

    project = repo / ".project"
    path = project / "STATE.md"
    try:
        directory = project.lstat()
        state_file = path.lstat()
        if (not stat.S_ISDIR(directory.st_mode)
                or not stat.S_ISREG(state_file.st_mode)
                or state_file.st_nlink != 1
                or set(project.iterdir()) != {path}):
            raise PipelineGitError("initial state must be the sole regular, unlinked .project file")
        state = pipeline_state.validate_state(repo)["state"]
        if (state["phase"] not in {"inspect", "define"}
                or state["status"] != "active"
                or any(state[key] is not None for key in ("branch", "milestone", "archive"))):
            raise PipelineGitError("untracked state is not an unbound initial state")
        return (directory.st_dev, directory.st_ino, state_file.st_dev,
                state_file.st_ino, path.read_bytes())
    except (OSError, pipeline_state.PipelineStateError) as error:
        raise PipelineGitError(f"invalid initial state: {error}") from error


def bind_initial_milestone_branch(
    repo: Path,
    branch: str,
    remote_default: str,
    base: str,
) -> dict[str, str]:
    """Bind the first milestone at an exact fetched remote-default SHA."""
    resolved = _require_worktree_root(repo)
    if not is_bound_branch(branch):
        raise PipelineGitError(f"invalid bound branch: {branch}")
    if remote_default != "origin/main":
        raise PipelineGitError(f"remote default must be origin/main, got {remote_default}")

    default_sha = _run_git(
        resolved,
        "rev-parse",
        "--verify",
        f"{remote_default}^{{commit}}",
    ).stdout.strip()
    base_sha = _run_git(
        resolved,
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
    remote_sha = _remote_ref_sha(resolved, "refs/heads/main")
    if remote_sha != default_sha:
        raise PipelineGitError(
            f"fetched {remote_default} is stale relative to origin"
        )
    initial_state = _initial_binding_snapshot(resolved)

    current = _symbolic_branch(resolved)
    head = _run_git(resolved, "rev-parse", "HEAD").stdout.strip()
    if head != base_sha:
        raise PipelineGitError(
            f"primary worktree is not at {remote_default}: {head} != {default_sha}"
        )
    worktrees = _branch_worktrees(resolved)
    if current not in worktrees or worktrees[current] != resolved:
        raise PipelineGitError("repo is not the registered path for its current worktree")
    owner = worktrees.get(branch)
    if owner is not None and owner != resolved:
        raise PipelineGitError(f"bound branch is checked out by another worktree: {owner}")
    if _remote_branch_exists(resolved, branch):
        raise PipelineGitError(f"bound branch already exists: refs/heads/{branch} on origin")

    if current == branch:
        status = "already-bound"
    else:
        if is_bound_branch(current):
            raise PipelineGitError(
                f"current branch is already bound to another milestone: {current}"
            )
        local_ref = f"refs/heads/{branch}"
        if _ref_exists(resolved, local_ref):
            raise PipelineGitError(f"bound branch already exists: {local_ref}")
        if _initial_binding_snapshot(resolved) != initial_state:
            raise PipelineGitError("initial state changed before branch binding")
        _run_git(resolved, "switch", "--no-track", "-c", branch, base_sha)
        status = "bound"

    if _initial_binding_snapshot(resolved) != initial_state:
        raise PipelineGitError("initial state changed during branch binding")

    return {
        "schema": "gsd-path/bind-initial/v1",
        "status": status,
        "base": default_sha,
        "branch": branch,
        "previous_branch": current,
    }


def retire_previous_branch(
    repo: Path,
    previous_branch: str,
    expected_sha: str,
    *,
    allow_remote_absent: bool = False,
) -> None:
    """Delete an integrated previous bound branch, locally and on origin.

    Retirement is hygiene, never reachability: callers prove the branch tip is
    an ancestor of the validated remote default first, and the milestone tag
    preserves the integration merge. The live remote branch is deleted first
    with an expected-SHA lease; local cleanup follows only after that proof.
    """
    local_ref = f"refs/heads/{previous_branch}"
    if _ref_exists(repo, local_ref):
        local_sha = _run_git(repo, "rev-parse", f"{local_ref}^{{commit}}").stdout.strip()
        if local_sha != expected_sha:
            raise PipelineGitError(
                f"previous branch moved after ship: {local_sha} != {expected_sha}"
            )

    remote_ref = f"refs/heads/{previous_branch}"
    remote_sha = _remote_ref_sha(repo, remote_ref)
    if remote_sha is None:
        if not allow_remote_absent:
            raise PipelineGitError(f"origin/{previous_branch} is missing before retirement")
    else:
        if remote_sha != expected_sha:
            raise PipelineGitError(
                f"origin/{previous_branch} moved after ship: {remote_sha} != {expected_sha}"
            )
        push = _run_git(
            repo,
            "push",
            f"--force-with-lease={remote_ref}:{expected_sha}",
            "origin",
            "--delete",
            previous_branch,
            check=False,
        )
        if push.returncode != 0:
            detail = (push.stderr or push.stdout).strip()
            raise PipelineGitError(
                f"could not delete origin/{previous_branch} with expected-SHA lease: {detail}"
            )
        if _remote_ref_sha(repo, remote_ref) is not None:
            raise PipelineGitError(f"origin/{previous_branch} still exists after retirement")

    tracking_ref = f"refs/remotes/origin/{previous_branch}"
    if _ref_exists(repo, tracking_ref):
        _run_git(repo, "update-ref", "-d", tracking_ref)
    if _ref_exists(repo, local_ref):
        _run_git(repo, "branch", "-d", previous_branch)


def bind_next_milestone_branch(
    repo: Path,
    branch: str,
    previous_branch: str,
    ship: str,
    remote_default: str,
    base: str,
    landing: str,
    allow_remote_absent: bool = False,
) -> dict[str, str]:
    """Move a clean primary worktree onto a new bound branch after integration."""
    repo = _require_worktree_root(repo)
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
    live_default_sha = _remote_ref_sha(repo, "refs/heads/main")
    if live_default_sha != default_sha:
        raise PipelineGitError(f"fetched {remote_default} is stale relative to origin")
    ship_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{ship}^{{commit}}",
    ).stdout.strip()
    if ship != ship_sha:
        raise PipelineGitError(f"ship must be the full commit SHA: {ship}")
    landing_sha = _run_git(
        repo,
        "rev-parse",
        "--verify",
        f"{landing}^{{commit}}",
    ).stdout.strip()
    if landing != landing_sha:
        raise PipelineGitError(f"landing must be the full commit SHA: {landing}")
    previous_ref = f"refs/heads/{previous_branch}"
    if _ref_exists(repo, previous_ref):
        previous_sha = _run_git(
            repo,
            "rev-parse",
            "--verify",
            f"{previous_ref}^{{commit}}",
        ).stdout.strip()
        if previous_sha != ship_sha:
            raise PipelineGitError(
                f"previous branch moved after ship: {previous_sha} != {ship_sha}"
            )
    integrated = _run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        ship_sha,
        landing_sha,
        check=False,
    )
    if integrated.returncode == 1:
        raise PipelineGitError("milestone landing does not contain the ship commit")
    if integrated.returncode != 0:
        detail = integrated.stderr.strip() or integrated.stdout.strip()
        raise PipelineGitError(f"could not verify milestone landing: {detail}")
    landing_integrated = _run_git(
        repo,
        "merge-base",
        "--is-ancestor",
        landing_sha,
        base_sha,
        check=False,
    )
    if landing_integrated.returncode == 1:
        raise PipelineGitError("milestone landing is not integrated into the validated base")
    if landing_integrated.returncode != 0:
        detail = landing_integrated.stderr.strip() or landing_integrated.stdout.strip()
        raise PipelineGitError(f"could not verify integrated branch: {detail}")
    if allow_remote_absent:
        proven_landing = _require_pull_request_integration_proof(
            repo,
            ship_sha,
            base_sha,
            previous_branch,
        )
        if proven_landing != landing_sha:
            raise PipelineGitError(
                "validated landing does not match pull-request integration proof"
            )

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
    status = "already-bound" if current == branch else "bound"
    if _run_git(repo, "status", "--porcelain", "--untracked-files=all").stdout:
        raise PipelineGitError("primary worktree is not clean")
    if _remote_branch_exists(repo, branch):
        raise PipelineGitError(f"bound branch already exists: refs/heads/{branch} on origin")

    request: dict[str, object] = {
        "schema": BIND_NEXT_JOURNAL_SCHEMA,
        "repo": str(repo),
        "branch": branch,
        "previous_branch": previous_branch,
        "ship": ship_sha,
        "remote_default": remote_default,
        "base": base_sha,
        "landing": landing_sha,
    }
    if allow_remote_absent:
        request["allow_remote_absent"] = True
    journal_path = bind_next_journal_path(repo, branch)
    new_journal = False
    if journal_path.exists() or journal_path.is_symlink():
        journal = _read_bind_next_journal(journal_path)
        legacy = journal.get("schema") == LEGACY_BIND_NEXT_JOURNAL_SCHEMA
        expected_fields = set(request) | {"stage"}
        if legacy:
            legacy_fields = expected_fields - {"landing"}
            if set(journal) != legacy_fields and set(journal) != expected_fields:
                raise PipelineGitError("bind-next journal has unsupported fields")
        elif set(journal) != expected_fields:
            raise PipelineGitError("bind-next journal has unsupported fields")
        mismatches = {
            key: {"expected": value, "actual": journal.get(key)}
            for key, value in request.items()
            if key != "schema"
            and (key != "landing" or "landing" in journal)
            and journal.get(key) != value
        }
        if not legacy and journal.get("schema") != BIND_NEXT_JOURNAL_SCHEMA:
            mismatches["schema"] = {
                "expected": BIND_NEXT_JOURNAL_SCHEMA,
                "actual": journal.get("schema"),
            }
        if mismatches:
            raise PipelineGitError(
                f"bind-next journal does not match request: {json.dumps(mismatches, sort_keys=True)}"
            )
        if journal.get("stage") not in {"prepared", "switched", "retired"}:
            raise PipelineGitError("bind-next journal has invalid stage")
        if legacy:
            journal["schema"] = BIND_NEXT_JOURNAL_SCHEMA
            journal["landing"] = landing_sha
            _write_bind_next_journal(journal_path, journal)
    else:
        if current == branch:
            raise PipelineGitError(
                f"current target branch {branch} has no matching bind-next journal"
            )
        if current != previous_branch:
            raise PipelineGitError(
                f"current branch {current} does not match previous branch {previous_branch}"
            )
        local_branch_ref = f"refs/heads/{branch}"
        if _ref_exists(repo, local_branch_ref):
            raise PipelineGitError(f"bound branch already exists: {local_branch_ref}")
        journal = {**request, "stage": "prepared"}
        new_journal = True

    stage = journal["stage"]
    if current not in {previous_branch, branch}:
        raise PipelineGitError(
            f"current branch {current} does not match bind-next journal ownership"
        )
    if current == previous_branch and stage != "prepared":
        raise PipelineGitError(
            f"bind-next journal stage {stage} conflicts with current {previous_branch}"
        )
    if current == branch:
        head = _run_git(repo, "rev-parse", "HEAD").stdout.strip()
        if head != base_sha:
            raise PipelineGitError(
                f"existing {branch} is not at {remote_default}: {head} != {default_sha}"
            )
        if stage == "prepared":
            journal["stage"] = "switched"
            _write_bind_next_journal(journal_path, journal)

    remote_previous = _remote_ref_sha(repo, f"refs/heads/{previous_branch}")
    if remote_previous is None:
        if not allow_remote_absent and (
            current != branch or journal["stage"] not in {"switched", "retired"}
        ):
            raise PipelineGitError(
                f"origin/{previous_branch} is missing before retirement"
            )
    elif remote_previous != ship_sha:
        raise PipelineGitError(
            f"origin/{previous_branch} moved after ship: {remote_previous} != {ship_sha}"
        )

    if current == previous_branch:
        if new_journal:
            _write_bind_next_journal(journal_path, journal)
        _run_git(repo, "switch", "--no-track", "-c", branch, base_sha)
        journal["stage"] = "switched"
        _write_bind_next_journal(journal_path, journal)

    retire_previous_branch(
        repo,
        previous_branch,
        ship_sha,
        allow_remote_absent=(
            allow_remote_absent or journal["stage"] in {"switched", "retired"}
        ),
    )
    journal["stage"] = "retired"
    _write_bind_next_journal(journal_path, journal)
    return {
        "schema": "gsd-path/bind-next/v1",
        "status": status,
        "base": default_sha,
        "landing": landing_sha,
        "branch": branch,
        "previous_branch": previous_branch,
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    bind_next = subparsers.add_parser(
        "bind-next",
        help=(
            "bind the next milestone branch at the integrated remote default "
            "and retire the previous bound branch"
        ),
    )
    bind_next.add_argument("--repo", required=True, type=Path)
    bind_next.add_argument("--branch", required=True)
    bind_next.add_argument("--previous-branch", required=True)
    bind_next.add_argument("--ship", required=True)
    bind_next.add_argument("--remote-default", required=True)
    bind_next.add_argument("--base", required=True)
    bind_next.add_argument("--landing", required=True)
    bind_next.add_argument("--allow-missing-previous", action="store_true")
    bind_initial = subparsers.add_parser(
        "bind-initial",
        help="bind the first milestone branch at the exact fetched remote default",
    )
    bind_initial.add_argument("--repo", required=True, type=Path)
    bind_initial.add_argument("--branch", required=True)
    bind_initial.add_argument("--remote-default", required=True)
    bind_initial.add_argument("--base", required=True)
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
                args.landing,
                args.allow_missing_previous,
            )
        elif args.command == "bind-initial":
            result = bind_initial_milestone_branch(
                args.repo,
                args.branch,
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
