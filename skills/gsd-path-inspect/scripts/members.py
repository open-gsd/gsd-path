#!/usr/bin/env python3
# gsd-path project runtime
"""Record and validate the member repositories of a multi-repo coordinator.

The coordinator's `.project/MEMBERS.md` lists members in ship order
(docs/adr/0002-multi-repo-coordinator.md). `add` writes that file and an
untracked marker in the member's shared Git directory. The next approval
checkpoint commits MEMBERS.md with the other `.project` artifacts.
`member_role` verifies the marker from any worktree of the member.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True
from pathlib import Path
from typing import Optional, Sequence

if __package__:
    from . import _common, pipeline_state
else:
    import _common
    import pipeline_state


MEMBERS_FILE = "MEMBERS.md"
MARKER_SCHEMA = "gsd-path/member/v1"
MARKER_KEYS = {"schema", "coordinator", "project", "name"}
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
FIELDS = ("Checkout", "Remote", "Integration")
INTEGRATIONS = ("default", "direct", "pull-request")
GITHUB_REMOTE_RE = re.compile(
    r"(?:https://github\.com/|git@github\.com:|ssh://git@github\.com/)([^/\s]+)/([^/\s]+)"
)
# Member-side Path refs carry the coordinator name, so they cannot collide with
# a member's own Path history.
MEMBER_BRANCH_FORMATS = ("gsd-path/{}-", "gsd-path-task/{}-", "gsd-path-verify/{}-", "gsd-path-integrate/{}-")
MEMBER_TAG_FORMAT = "refs/tags/milestone/{}-"
# The coordinator records one authorization per (ref, object) before it
# publishes a member Path ref; member pre-push accepts only a matching one.
AUTHORIZATION_PREFIX = "refs/gsd-path/authorizations/"
LOCK_PATH = ".project/build/members.json"
LOCK_SCHEMA = "gsd-path/member-lock/v1"
HEADER = (
    "# Members\n\n"
    "<!-- Written by members.py add. One section per member repository, in\n"
    "     ship order. Fixed format; change it only through members.py. -->\n"
)


class MembersError(RuntimeError):
    pass


def _git(repo: Path, *arguments: str) -> str:
    result = _common.run_git(repo, *arguments)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git command failed"
        raise MembersError(f"{repo}: git {' '.join(arguments)}: {detail}")
    return result.stdout.strip()


def _coordinator(repo: Path) -> tuple[Path, pipeline_state.PipelineState]:
    try:
        root = pipeline_state._repo_root(Path(repo))
        state, _, _ = pipeline_state.load_state(root)
    except pipeline_state.PipelineStateError as error:
        raise MembersError(f"coordinator: {error}") from error
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise MembersError(f"coordinator is not a Git root: {root}")
    return root, state


def _remote_identity(remote: str) -> Optional[tuple[str, str]]:
    match = GITHUB_REMOTE_RE.fullmatch(remote)
    if match is None:
        return None
    return match.group(1).lower(), match.group(2).removesuffix(".git").lower()


def _common_dir(checkout: Path) -> Path:
    return Path(_git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()


def _marker_path(checkout: Path) -> Path:
    directory = _common_dir(checkout) / "gsd-path"
    if directory.is_symlink() or (directory.exists() and not directory.is_dir()):
        raise MembersError(f"member marker directory must be real: {directory}")
    path = directory / "member.json"
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise MembersError(
            f"member marker is not a regular file: {path}; "
            "remove it by hand, then run members.py repair --repo <coordinator>"
        )
    return path


def _read_marker(path: Path) -> Optional[dict[str, str]]:
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink() or not path.is_file():
            raise MembersError(
                f"member marker is not a regular file: {path}; "
                "remove it by hand, then run members.py repair --repo <coordinator>"
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict) or set(data) != MARKER_KEYS
                or any(not isinstance(data[key], str) or not data[key].strip() for key in MARKER_KEYS)
                or data["schema"] != MARKER_SCHEMA
                or not Path(data["coordinator"]).is_absolute()):
            raise ValueError("unexpected content")
    except (OSError, ValueError) as error:
        raise MembersError(
            f"member marker is unreadable: {path}: {error}; "
            "run members.py repair --repo <coordinator>"
        ) from error
    return data


def _write_marker(checkout: Path, coordinator: Path, project: str, name: str) -> None:
    path = _marker_path(checkout)
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = {"schema": MARKER_SCHEMA, "coordinator": str(coordinator), "project": project, "name": name}
    _common.atomic_write(path, json.dumps(marker, sort_keys=True) + "\n")


def _refuse_foreign_marker(checkout: Path, coordinator: Path, project: str, name: str) -> None:
    path = _marker_path(checkout)
    try:
        marker = _read_marker(path)
    except MembersError:
        return
    if marker is not None and (marker["project"], marker["name"]) != (project, name):
        raise MembersError(f"{checkout} is already a member of {marker['project']}")
    if marker is not None:
        try:
            role = member_role(checkout)
        except MembersError:
            return
        if role is not None and role["coordinator"] != coordinator:
            raise MembersError(f"{checkout} is already a member of {role['coordinator']}")


def marker_coordinator(checkout: Path) -> Optional[Path]:
    """The coordinator a member marker names, unverified; None without a marker."""
    marker = _read_marker(_marker_path(Path(checkout)))
    return None if marker is None else Path(marker["coordinator"])


def member_role(checkout: Path) -> Optional[dict[str, object]]:
    """The verified coordinator of a member checkout, or None outside a member."""
    checkout = Path(checkout)
    marker = _read_marker(_marker_path(checkout))
    if marker is None:
        return None
    stale = MembersError(
        f"member marker for {marker['name']} is stale; "
        "run members.py repair --repo <coordinator>"
    )
    try:
        root, state = _coordinator(Path(marker["coordinator"]))
        listed = read_members(root)
        common = _common_dir(checkout)
        for member in listed:
            if member["name"] == marker["name"] and _common_dir(Path(member["checkout"])) == common:
                if state.project != marker["project"]:
                    break
                return {"coordinator": root, "project": state.project, "name": member["name"]}
    except (MembersError, OSError) as error:
        raise stale from error
    raise stale


def detect_member(checkout: Path) -> dict[str, object]:
    """Whether a repo is a member: its coordinator, name, and whether its marker is current."""
    checkout = Path(checkout).resolve()
    try:
        named = marker_coordinator(checkout)
    except MembersError as error:
        return {"member": True, "current": False, "checkout": str(checkout), "reason": str(error)}
    if named is None:
        return {"member": False, "checkout": str(checkout)}
    try:
        role = member_role(checkout)
    except MembersError as error:
        return {"member": True, "current": False, "checkout": str(checkout),
                "coordinator": str(named), "reason": str(error)}
    return {"member": True, "current": True, "checkout": str(checkout), "coordinator": str(role["coordinator"]),
            "project": role["project"], "name": role["name"]}


def read_members(coordinator: Path) -> list[dict[str, str]]:
    """Parse MEMBERS.md; an absent file means a single-repo project."""
    path = coordinator / ".project" / MEMBERS_FILE
    if not path.exists() and not path.is_symlink():
        return []
    if path.is_symlink() or not path.is_file():
        raise MembersError("MEMBERS.md must be a regular file")
    members: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    preamble: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("## "):
            name = line[3:].strip()
            if not NAME_RE.fullmatch(name):
                raise MembersError(f"MEMBERS.md line {number}: invalid member name {name!r}")
            current = {"name": name}
            members.append(current)
            continue
        if current is None:
            preamble.append(line)
            continue
        if not line.strip():
            continue
        key, separator, value = line.partition(":")
        if not separator or key not in FIELDS or key.lower() in current:
            raise MembersError(f"MEMBERS.md line {number}: unexpected line {line!r}")
        current[key.lower()] = value.strip()
    if not preamble or preamble[0] != "# Members":
        raise MembersError("MEMBERS.md format error: expected # Members")
    rest = preamble[1:]
    while rest and not rest[0]:
        rest.pop(0)
    comment = HEADER.splitlines()[2:]
    if rest[:len(comment)] == comment:
        rest = rest[len(comment):]
    if any(rest):
        raise MembersError("MEMBERS.md format error: unexpected pre-section content")
    names = [member["name"] for member in members]
    if len(set(names)) != len(names):
        raise MembersError("MEMBERS.md repeats a member name")
    for member in members:
        missing = [field for field in FIELDS if not member.get(field.lower())]
        if missing:
            raise MembersError(f"MEMBERS.md member {member['name']} lacks {', '.join(missing)}")
        if member["integration"] not in INTEGRATIONS:
            raise MembersError(
                f"MEMBERS.md member {member['name']} has invalid Integration: {member['integration']}"
            )
        if not Path(member["checkout"]).is_absolute():
            raise MembersError(f"MEMBERS.md member {member['name']} Checkout must be absolute")
    return members


def check_member(
    coordinator: Path,
    coordinator_name: str,
    checkout: Path,
    recorded_remote: Optional[str] = None,
    refuse_reserved_refs: bool = True,
) -> str:
    """Refuse a checkout that cannot join; return its origin URL."""
    if checkout.is_symlink() or not checkout.is_dir():
        raise MembersError(f"member checkout is not a real directory: {checkout}")
    checkout = checkout.resolve()
    if coordinator in checkout.parents or checkout in coordinator.parents:
        raise MembersError(f"member checkout is nested with the coordinator: {checkout}")
    if Path(_git(checkout, "rev-parse", "--show-toplevel")).resolve() != checkout:
        raise MembersError(f"member checkout must be its Git root: {checkout}")
    if _git(checkout, "rev-parse", "--show-superproject-working-tree"):
        raise MembersError(f"member checkout is a submodule: {checkout}")
    common = Path(_git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    coordinator_common = Path(
        _git(coordinator, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    if common.resolve() == coordinator_common.resolve():
        raise MembersError("the coordinator cannot be its own member")
    if _git(checkout, "status", "--porcelain", "--untracked-files=all"):
        raise MembersError(f"member has uncommitted changes: {checkout}")
    # The configured URL, not `get-url`, which expands local insteadOf rewrites.
    remote = _git(checkout, "config", "--get", "remote.origin.url")
    if not GITHUB_REMOTE_RE.fullmatch(remote):
        raise MembersError(f"member requires a GitHub.com origin: {remote}")
    if recorded_remote is not None and remote != recorded_remote:
        raise MembersError(f"member origin changed: {recorded_remote} -> {remote}")
    default = _common.run_git(checkout, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
    if default.returncode != 0 or default.stdout.strip() != "origin/main":
        raise MembersError(f"member remote default must be main: {checkout}")
    require_origin_main(checkout)
    member_state = checkout / ".project" / "STATE.md"
    if member_state.exists() or member_state.is_symlink():
        if member_state.is_symlink() or not member_state.is_file():
            raise MembersError("member STATE.md is unreadable")
        try:
            state, _, _ = pipeline_state.load_state(checkout)
        except pipeline_state.PipelineStateError as error:
            raise MembersError(f"member STATE.md is unreadable: {error}") from error
        if state.milestone is not None and (state.phase, state.status) != ("shipped", "done"):
            raise MembersError(f"member has an active milestone: {state.milestone}")
    if refuse_reserved_refs:
        prefixes = member_ref_prefixes(coordinator_name) + tuple(
            "refs/remotes/origin/" + branch.format(coordinator_name) for branch in MEMBER_BRANCH_FORMATS
        )
        refs = _git(checkout, "for-each-ref", "--format=%(refname)").splitlines()
        colliding = [ref for ref in refs if ref.startswith(prefixes)]
        if colliding:
            raise MembersError("member refs collide with coordinator names: " + ", ".join(colliding))
    return remote


MEMBER_CLOSE_SCHEMA = "gsd-path/member-close/v1"


def member_close_path(common: Path, archive_name: str) -> Path:
    """Ship's member-close journal; outside the archive so the archive inventory is unchanged."""
    return common / "gsd-path" / "member-close" / f"{archive_name}.json"


def read_member_close(common: Path, archive_name: str) -> list[dict]:
    path = member_close_path(common, archive_name)
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("schema") != MEMBER_CLOSE_SCHEMA or not isinstance(data.get("members"), list):
        raise MembersError(f"member-close journal is invalid: {path}")
    return data["members"]


def milestone_member_close(common: Path, milestone: int) -> list[dict]:
    """Member-close rows of milestone M<milestone>, whatever archive name it closed under."""
    rows: list[dict] = []
    for path in sorted((common / "gsd-path" / "member-close").glob(f"{milestone:03d}-*.json")):
        rows.extend(read_member_close(common, path.stem))
    return rows


def write_member_close(common: Path, archive_name: str, rows: list[dict]) -> None:
    path = member_close_path(common, archive_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    _common.atomic_write(path, json.dumps({"schema": MEMBER_CLOSE_SCHEMA, "members": rows}, indent=2) + "\n")


def require_origin_main(checkout: Path) -> None:
    baseline = _common.run_git(
        checkout, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}"
    )
    if baseline.returncode != 0:
        raise MembersError("member requires refs/remotes/origin/main; run git fetch origin")


def member_ref_prefixes(project: str) -> tuple[str, ...]:
    """Ref prefixes a member repo reserves for the coordinator named `project`."""
    return tuple(
        "refs/heads/" + branch.format(project) for branch in MEMBER_BRANCH_FORMATS
    ) + (MEMBER_TAG_FORMAT.format(project),)


def _authorization_ref(project: str, kind: str, ref: str) -> str:
    if not NAME_RE.fullmatch(project) or not ref.startswith(("refs/heads/", "refs/tags/")):
        raise MembersError(f"cannot authorize {ref} for {project}")
    return f"{AUTHORIZATION_PREFIX}{project}/{kind}/{ref}"


def _authorize(checkout: Path, project: str, kind: str, ref: str, sha: str) -> None:
    authorization = _authorization_ref(project, kind, ref)
    _git(checkout, "update-ref", authorization, sha)


def clear_authorization(checkout: Path, project: str, kind: str, ref: str) -> None:
    """Remove a push or delete authorization; S4 retirement clears a milestone's own."""
    _git(checkout, "update-ref", "-d", _authorization_ref(project, kind, ref))


def authorize_push(checkout: Path, project: str, ref: str, sha: str) -> None:
    """Authorize `ref` at exactly `sha` until cleared (a commit or tag object)."""
    _authorize(checkout, project, "push", ref, sha)


def authorize_delete(checkout: Path, project: str, ref: str, expected_remote_sha: str) -> None:
    """Allow deleting remote `ref` only while it still points at `expected_remote_sha`."""
    _authorize(checkout, project, "delete", ref, expected_remote_sha)


def authorized(checkout: Path, project: str, kind: str, ref: str, sha: str) -> bool:
    if not ref.startswith(("refs/heads/", "refs/tags/")):
        return False
    result = _common.run_git(
        checkout, "rev-parse", "--verify", "--quiet", _authorization_ref(project, kind, ref)
    )
    return result.returncode == 0 and result.stdout.strip() == sha


def _task_members(coordinator: Path) -> set[str]:
    try:
        from check_task_briefs import _frontmatter
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts.check_task_briefs import _frontmatter
    named = set()
    for task in sorted((coordinator / ".project" / "tasks").glob("*.md")):
        fields, error = _frontmatter(task.read_text(encoding="utf-8"))
        if fields is None:
            raise MembersError(f"{task.name}: {error}")
        if fields.get("repo"):
            named.add(str(fields["repo"]))
    return named


def lock_build_members(coordinator: Path) -> Optional[list[dict[str, str]]]:
    """At build start, lock the members tasks name (MEMBERS.md order) and create
    each member's bound branch at its origin/main. None when no task names a member."""
    root, state = _coordinator(coordinator)
    named = _task_members(root)
    lock_path = root / LOCK_PATH
    build_dir = lock_path.parent
    if build_dir.is_symlink() or (build_dir.exists() and not build_dir.is_dir()):
        raise MembersError(f"member lock directory must be real: {build_dir}")
    if lock_path.is_symlink() or (lock_path.exists() and not lock_path.is_file()):
        raise MembersError(f"member lock must be a regular file: {lock_path}")
    if not named:
        lock_path.unlink(missing_ok=True)
        return None
    listed = read_members(root)
    unknown = sorted(named - {member["name"] for member in listed})
    if unknown:
        raise MembersError("tasks name members missing from MEMBERS.md: " + ", ".join(unknown))
    ignore_error = _common.project_ignore_error(root)
    if ignore_error:
        raise MembersError(ignore_error)
    bound = _common.BOUND_BRANCH_RE.fullmatch(state.branch or "")
    if bound is None:
        raise MembersError(f"coordinator branch is not a bound branch: {state.branch}")
    branch = f"gsd-path/{state.project}-M{bound.group(1)}"
    previous = {}
    if lock_path.is_file():
        previous = {entry["name"]: entry for entry in json.loads(lock_path.read_text(encoding="utf-8"))["members"]}
    entries = []
    missing = []
    for member in listed:
        if member["name"] not in named:
            continue
        checkout = Path(member["checkout"])
        role = member_role(checkout)
        if role is None or role["coordinator"] != root or role["name"] != member["name"]:
            raise MembersError(f"member marker for {member['name']} is missing or stale; "
                               f"run members.py repair --repo {root}")
        remote = _git(checkout, "config", "--get", "remote.origin.url")
        if remote != member["remote"]:
            raise MembersError(f"member origin changed: {member['remote']} -> {remote}")
        require_origin_main(checkout)
        base = _git(checkout, "rev-parse", "refs/remotes/origin/main^{commit}")
        existing = _common.run_git(checkout, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}")
        if existing.returncode == 0:
            tip = existing.stdout.strip()
            locked = previous.get(member["name"])
            # Recovery re-entry keeps the locked base; otherwise the branch must be unused.
            if locked and locked["branch"] == branch and _common.run_git(
                checkout, "merge-base", "--is-ancestor", locked["base"], tip
            ).returncode == 0:
                base = locked["base"]
            elif _common.run_git(checkout, "merge-base", "--is-ancestor", tip, base).returncode == 0:
                base = tip
            else:
                raise MembersError(f"member {member['name']} branch {branch} has commits not on origin/main")
        else:
            missing.append((checkout, base))
        entries.append({"name": member["name"], "branch": branch, "base": base})
    for checkout, base in missing:
        _git(checkout, "update-ref", f"refs/heads/{branch}", base, "")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    _common.atomic_write(lock_path, json.dumps({"schema": LOCK_SCHEMA, "members": entries}, indent=2) + "\n")
    return entries


def render(members: Sequence[dict[str, str]]) -> str:
    sections = [
        f"## {member['name']}\n"
        f"Checkout: {member['checkout']}\n"
        f"Remote: {member['remote']}\n"
        f"Integration: {member['integration']}\n"
        for member in members
    ]
    return "\n".join([HEADER, *sections])


def add_member(repo: Path, name: str, checkout: Path, integration: str) -> list[dict[str, str]]:
    root, state = _coordinator(repo)
    if state.phase in {"build", "ship"}:
        raise MembersError("members change only at a milestone boundary, not during build or ship")
    if not NAME_RE.fullmatch(name):
        raise MembersError(f"invalid member name: {name!r}")
    members = read_members(root)
    resolved = checkout.resolve()
    remote = check_member(root, state.project, checkout)
    common = Path(_git(resolved, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    identity = _remote_identity(remote)
    for member in members:
        previous = Path(member["checkout"])
        if (member["name"] == name or previous == resolved
                or _remote_identity(member["remote"]) == identity
                or Path(_git(previous, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve() == common):
            raise MembersError(f"member already recorded: {member['name']}")
    _refuse_foreign_marker(resolved, root, state.project, name)
    members.append(
        {"name": name, "checkout": str(resolved), "remote": remote, "integration": integration}
    )
    _write_marker(resolved, root, state.project, name)
    _common.atomic_write(root / ".project" / MEMBERS_FILE, render(members))
    return members


MEMBER_CREATE_SCHEMA = "gsd-path/member-create/v1"
VISIBILITIES = ("public", "private", "internal")


def _gh(*arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run(["gh", *arguments], capture_output=True, text=True, check=False,
                          env={**os.environ, "GH_HOST": "github.com"})


def create_member(repo: Path, name: str, checkout: Path, integration: str, github: str,
                  visibility: str) -> list[dict[str, str]]:
    """Greenfield member: create the approved GitHub repo, clone it, then join it.

    A journal in the coordinator Git directory keeps the approved target before any
    external action; a rerun resumes each step and never creates a second repo."""
    root, state = _coordinator(repo)
    if state.phase in {"build", "ship"}:
        raise MembersError("members change only at a milestone boundary, not during build or ship")
    if not NAME_RE.fullmatch(name) or not re.fullmatch(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+", github):
        raise MembersError(f"invalid member name or GitHub repository: {name!r} {github!r}")
    if visibility not in VISIBILITIES:
        raise MembersError(f"visibility must be one of {', '.join(VISIBILITIES)}")
    if checkout.is_symlink():
        raise MembersError(f"member checkout path is a symlink: {checkout}")
    resolved = checkout.resolve()
    if resolved == root or root in resolved.parents or resolved in root.parents:
        raise MembersError(f"member checkout is nested with the coordinator: {resolved}")
    if not resolved.parent.is_dir():
        raise MembersError(f"member checkout parent does not exist: {resolved.parent}")
    target = {"schema": MEMBER_CREATE_SCHEMA, "name": name, "github": github, "visibility": visibility,
              "checkout": str(resolved), "integration": integration}
    common = Path(_git(root, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    journal = common / "gsd-path" / "member-create" / f"{name}.json"
    url = f"https://github.com/{github}.git"
    if journal.is_file():
        recorded = json.loads(journal.read_text(encoding="utf-8"))
        if {key: recorded.get(key) for key in target} != target or recorded.get("step") not in {"create", "clone", "join"}:
            raise MembersError(f"member-create journal for {name} holds a different approved target: {journal}")
    else:
        if any(member["name"] == name for member in read_members(root)):
            raise MembersError(f"member already recorded: {name}")
    if resolved.is_symlink() or (resolved.exists() and not resolved.is_dir()):
        raise MembersError(f"member checkout path is occupied: {resolved}")
    occupied = resolved.exists() and any(resolved.iterdir())
    if occupied and Path(_common.run_git(resolved, "rev-parse", "--show-toplevel").stdout.strip()).resolve() != resolved:
        raise MembersError(f"member checkout path is occupied: {resolved}")
    if occupied and _git(resolved, "config", "--get", "remote.origin.url") != url:
        raise MembersError(f"member checkout {resolved} is not a clone of {url}")
    if not journal.is_file():
        journal.parent.mkdir(parents=True, exist_ok=True)
        recorded = {**target, "step": "create"}
        _common.atomic_write(journal, json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    listed = [member for member in read_members(root) if member["name"] == name]
    if listed:
        if (len(listed) != 1 or listed[0] != {"name": name, "checkout": str(resolved), "remote": url,
                                            "integration": integration}
                or member_role(resolved) != {"coordinator": root, "project": state.project, "name": name}):
            raise MembersError(f"member already recorded with a different checkout or marker: {name}")
        journal.unlink()
        return read_members(root)
    viewed = _gh("repo", "view", github, "--json", "visibility")
    if viewed.returncode != 0:
        if "Could not resolve to a Repository" not in f"{viewed.stdout}\n{viewed.stderr}":
            raise MembersError(f"could not inspect {github}: {(viewed.stderr or viewed.stdout).strip()}")
        if recorded["step"] != "create":
            raise MembersError(f"GitHub repository {github} disappeared after creation; refusing to create it again")
        if occupied:
            raise MembersError(f"member checkout {resolved} is a clone of a missing repository: {github}")
        created = _gh("repo", "create", github, f"--{visibility}", "--add-readme")
        if created.returncode != 0:
            raise MembersError(f"could not create {github}: {(created.stderr or created.stdout).strip()}")
        recorded["step"] = "clone"
        _common.atomic_write(journal, json.dumps(recorded, indent=2, sort_keys=True) + "\n")
        viewed = _gh("repo", "view", github, "--json", "visibility")
    if viewed.returncode != 0:
        raise MembersError(f"could not inspect {github}: {(viewed.stderr or viewed.stdout).strip()}")
    try:
        actual_visibility = json.loads(viewed.stdout)["visibility"].lower()
    except (ValueError, KeyError, AttributeError) as error:
        raise MembersError(f"could not read {github} visibility") from error
    if actual_visibility != visibility:
        raise MembersError(f"GitHub repository visibility is {actual_visibility}, not {visibility}")
    recorded["step"] = "clone"
    _common.atomic_write(journal, json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    if occupied:
        fetched = _common.run_git(resolved, "fetch", "-q", "--prune", "origin")
        if fetched.returncode != 0:
            raise MembersError(f"could not fetch member checkout {resolved}: {(fetched.stderr or fetched.stdout).strip()}")
        default = _common.run_git(resolved, "remote", "set-head", "origin", "--auto")
        if default.returncode != 0 or _git(resolved, "symbolic-ref", "--short", "refs/remotes/origin/HEAD") != "origin/main":
            raise MembersError(f"member remote default must be main: {resolved}")
        baseline = _common.run_git(resolved, "rev-parse", "--verify", "--quiet", "refs/remotes/origin/main^{commit}")
        if baseline.returncode != 0:
            raise MembersError(f"member checkout {resolved} has no current origin/main")
        head = _common.run_git(resolved, "rev-parse", "--verify", "--quiet", "HEAD^{commit}")
        if head.returncode == 0:
            if _common.run_git(resolved, "merge-base", "--is-ancestor", "HEAD", "origin/main").returncode != 0:
                raise MembersError(f"member checkout {resolved} has history unrelated to current origin/main")
        else:
            _git(resolved, "checkout", "-B", "main", "origin/main")
    else:
        cloned = _common.run_git(resolved.parent, "clone", "-q", url, str(resolved))
        if cloned.returncode != 0:
            raise MembersError(f"could not clone {url}: {(cloned.stderr or cloned.stdout).strip()}")
    recorded["step"] = "join"
    _common.atomic_write(journal, json.dumps(recorded, indent=2, sort_keys=True) + "\n")
    joined = add_member(root, name, resolved, integration)
    journal.unlink()
    return joined


def validate_members(repo: Path) -> list[dict[str, str]]:
    root, state = _coordinator(repo)
    members = read_members(root)
    for member in members:
        checkout = Path(member["checkout"])
        check_member(root, state.project, checkout, member["remote"], refuse_reserved_refs=False)
        try:
            role = member_role(checkout)
        except MembersError as error:
            raise MembersError(f"{error}; run members.py repair --repo {root}") from error
        if role != {"coordinator": root, "project": state.project, "name": member["name"]}:
            raise MembersError(
                f"member marker for {member['name']} is missing or stale; "
                f"run members.py repair --repo {root}"
            )
    return members


def repair_members(repo: Path) -> list[dict[str, str]]:
    """Rewrite missing or stale markers; never take over another coordinator's member."""
    root, state = _coordinator(repo)
    members = read_members(root)
    for member in members:
        checkout = Path(member["checkout"])
        check_member(root, state.project, checkout, member["remote"], refuse_reserved_refs=False)
        _refuse_foreign_marker(checkout.resolve(), root, state.project, member["name"])
    for member in members:
        checkout = Path(member["checkout"]).resolve()
        try:
            role = member_role(checkout)
        except MembersError:
            role = None
        if role != {"coordinator": root, "project": state.project, "name": member["name"]}:
            _write_marker(checkout, root, state.project, member["name"])
    return members


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    add = commands.add_parser("add", help="record one member repository")
    add.add_argument("--repo", required=True, type=Path, help="coordinator Git root")
    add.add_argument("--name", required=True)
    add.add_argument("--checkout", required=True, type=Path)
    add.add_argument("--integration", choices=INTEGRATIONS, default="default")
    add.add_argument("--create", metavar="OWNER/NAME",
                     help="greenfield: create this GitHub repo and clone it to --checkout first")
    add.add_argument("--visibility", choices=VISIBILITIES, help="visibility for --create")
    validate = commands.add_parser("validate", help="check MEMBERS.md and every member")
    validate.add_argument("--repo", required=True, type=Path, help="coordinator Git root")
    detect = commands.add_parser("detect", help="report whether a repo is a member, and of which coordinator")
    detect.add_argument("--checkout", required=True, type=Path, help="repository to inspect")
    repair = commands.add_parser("repair", help="rewrite missing or stale member markers")
    repair.add_argument("--repo", required=True, type=Path, help="coordinator Git root")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "detect":
            print(json.dumps(detect_member(arguments.checkout), sort_keys=True))
            return 0
        if arguments.command == "add" and arguments.create:
            if arguments.visibility is None:
                raise MembersError("--create requires --visibility")
            members = create_member(arguments.repo, arguments.name, arguments.checkout,
                                    arguments.integration, arguments.create, arguments.visibility)
        elif arguments.command == "add":
            if arguments.visibility is not None:
                raise MembersError("--visibility requires --create")
            members = add_member(
                arguments.repo, arguments.name, arguments.checkout, arguments.integration
            )
        elif arguments.command == "repair":
            members = repair_members(arguments.repo)
        else:
            members = validate_members(arguments.repo)
    except (MembersError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"members": members}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
