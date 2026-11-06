#!/usr/bin/env python3
# gsd-path project runtime
"""Own milestone integration, publication, tags, and completion proof."""

import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True

import json
import re
import contextlib
import shutil
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Mapping, Optional, Sequence

if __package__:
    from .pipeline_git import (
        bound_branch_name,
        default_branch_name,
        integrate_commit_body,
        integrate_subject,
        is_bound_branch,
        milestone_id,
        milestone_number,
        ship_subject,
    )
    from .pipeline_state import PipelineState, transition_state
    from .isolation import publication_base, _unlink_link_like, IsolationError
    from . import _common
    from . import roadmap
    from . import worktree_paths
else:
    try:
        from pipeline_git import (
            bound_branch_name,
            default_branch_name,
            integrate_commit_body,
            integrate_subject,
            is_bound_branch,
            milestone_id,
            milestone_number,
            ship_subject,
        )
        from pipeline_state import PipelineState, transition_state
        from isolation import publication_base, _unlink_link_like, IsolationError
        import _common
        import roadmap
        import worktree_paths
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts.pipeline_git import (
            bound_branch_name,
            default_branch_name,
            integrate_commit_body,
            integrate_subject,
            is_bound_branch,
            milestone_id,
            milestone_number,
            ship_subject,
        )
        from scripts.pipeline_state import PipelineState, transition_state
        from scripts.isolation import publication_base, _unlink_link_like, IsolationError
        from scripts import _common
        from scripts import roadmap
        from scripts import worktree_paths


if __package__:
    from . import archive_milestone
    from .archive_milestone import ArchiveError
else:
    import archive_milestone
    from archive_milestone import ArchiveError


PR_CREDIT_LINE = (
    "PR prepared with [GSD Path](https://github.com/open-gsd/gsd-path)."
)
GITHUB_HOST = "github.com"


run_git = _common.run_git
run_command = _common.run_command


def _defuse_links(tree: Path) -> None:
    try:
        _unlink_link_like(tree)  # never traverse links (#462)
    except IsolationError as error:
        raise ArchiveError(str(error)) from error


def resolve_remote_default(project: Path) -> str:
    result = run_git(project, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD")
    remote_ref = result.stdout.strip()
    prefix = "refs/remotes/"
    if result.returncode != 0 or not remote_ref.startswith(prefix):
        raise ArchiveError("origin/HEAD is unresolved; fetch before validating integration")
    return remote_ref.removeprefix(prefix)


def live_remote_ref(project: Path, ref: str) -> Optional[str]:
    result = run_git(
        project,
        "ls-remote",
        "--exit-code",
        "--refs",
        "origin",
        ref,
    )
    if result.returncode == 2:
        return None
    if result.returncode != 0:
        raise ArchiveError(f"could not inspect {ref} on origin: git ls-remote failed")
    rows = [line.split("\t", 1) for line in result.stdout.splitlines() if line]
    if len(rows) != 1 or len(rows[0]) != 2 or rows[0][1] != ref:
        raise ArchiveError(f"origin returned ambiguous ref data for {ref}")
    return rows[0][0]


def live_remote_refs(project: Path, refs: Sequence[str]) -> dict:
    """The live origin SHA of every fully-qualified ref, in one ls-remote (#558).

    Six serial round trips made the daemon's status exceed its 10 s budget on
    an ordinary wide-area origin; one batched query answers the whole set.
    An absent ref maps to None. Callers pass fully-qualified refs, so the
    rows match exactly and ambiguity stays an error.
    """
    if not refs:
        return {}
    result = run_git(project, "ls-remote", "--refs", "origin", *refs)
    if result.returncode != 0:
        raise ArchiveError(f"could not inspect origin refs: git ls-remote failed")
    published: dict = {ref: None for ref in refs}
    for line in result.stdout.splitlines():
        if not line:
            continue
        row = line.split("\t", 1)
        if len(row) != 2 or row[1] not in published:
            raise ArchiveError("origin returned ambiguous ref data")
        if published[row[1]] is not None:
            raise ArchiveError(f"origin returned ambiguous ref data for {row[1]}")
        published[row[1]] = row[0]
    return published


def publishable_bound_branch(
    project: Path, branch: str, ship_commit: str, adopt_published: Optional[str] = None
) -> Optional[str]:
    """The live origin SHA the bound ref may move from: absent, the ship
    commit, an owner-adopted rebased head proven by its archived receipt, or a
    user-attested strict ancestor adopted through --adopt-published-bound
    (#464: a build task legitimately pushed the bound branch as a deploy pin)."""
    remote_sha = live_remote_ref(project, f"refs/heads/{branch}")
    if remote_sha is None or remote_sha == ship_commit:
        return remote_sha
    if adopt_published is not None:
        if remote_sha != adopt_published:
            raise ArchiveError(
                f"origin/{branch} moved or collides: {remote_sha} != {adopt_published}")
        if run_git(project, "merge-base", "--is-ancestor", remote_sha, ship_commit).returncode != 0:
            raise ArchiveError(
                f"origin/{branch} {remote_sha} diverges from the ship commit; "
                "an adoption cannot rewind")
        return remote_sha
    try:
        approved_base = publication_base(project, branch, ship_commit)
    except (RuntimeError, OSError) as error:
        raise ArchiveError(f"rebase publication proof failed: {error}") from error
    if remote_sha != approved_base:
        raise ArchiveError(f"origin/{branch} moved or collides: {remote_sha} != {ship_commit}")
    return remote_sha


def publish_bound_branch(
    project: Path, branch: str, ship_commit: str, adopt_published: Optional[str] = None
) -> None:
    remote_ref = f"refs/heads/{branch}"
    remote_sha = publishable_bound_branch(project, branch, ship_commit, adopt_published)
    if remote_sha != ship_commit:
        # An absent ref carries an empty lease; an adopted head leases its exact SHA.
        archive_milestone.require_git_success(
            run_git(
                project,
                "push",
                f"--force-with-lease={remote_ref}:{remote_sha or ''}",
                "origin",
                f"{ship_commit}:{remote_ref}",
            ),
            "publish bound branch under its observed lease",
        )

    confirmed_sha = live_remote_ref(project, remote_ref)
    if confirmed_sha != ship_commit:
        raise ArchiveError(f"origin/{branch} does not equal the ship commit after publish")
    archive_milestone.require_git_success(
        run_git(
            project,
            "update-ref",
            f"refs/remotes/origin/{branch}",
            ship_commit,
        ),
        "refresh local bound-branch ref",
    )


def refresh_origin(repo: Path) -> dict:
    """Fetch origin, refresh origin/HEAD, and mirror milestone tags."""
    project = repo.resolve()
    archive_milestone.require_git_success(run_git(project, "fetch", "--prune", "origin"), "fetch origin")
    archive_milestone.require_git_success(
        run_git(project, "remote", "set-head", "origin", "--auto"),
        "refresh origin/HEAD",
    )
    mirrored = run_git(
        project,
        "fetch",
        "--prune",
        "origin",
        "refs/tags/milestone/*:refs/remotes/origin/tags/milestone/*",
    )
    if mirrored.returncode != 0:
        detail = (mirrored.stderr or mirrored.stdout).strip()
        if "couldn't find remote ref" not in detail.casefold() and detail:
            raise ArchiveError(f"could not refresh published milestone tags: {detail}")
    remote_default = resolve_remote_default(project)
    return {"remote_default": remote_default}


def optional_ref(project: Path, ref: str) -> Optional[str]:
    result = run_git(project, "rev-parse", "--verify", "--quiet", ref)
    return result.stdout.strip() if result.returncode == 0 else None


def integration_names(project: Path, archive_name: str, *, pin: bool = False) -> tuple[str, Path]:
    identifier = milestone_id(milestone_number(archive_name))
    branch = f"gsd-path-integrate/{identifier}"
    try:
        worktree = worktree_paths.worktree_path(project, "integrate", identifier, pin=pin)
    except (ValueError, OSError) as error:
        raise ArchiveError(str(error)) from error
    return branch, worktree


def registered_worktree(project: Path, branch: str) -> Optional[Path]:
    output = archive_milestone.require_git_success(
        run_git(project, "worktree", "list", "--porcelain"),
        "inspect integration worktrees",
    )
    branch_ref = f"branch refs/heads/{branch}"
    matches = []
    for record in output.split("\n\n"):
        lines = record.splitlines()
        if branch_ref not in lines:
            continue
        worktree_lines = [
            line.removeprefix("worktree ")
            for line in lines
            if line.startswith("worktree ")
        ]
        if len(worktree_lines) != 1:
            raise ArchiveError(
                f"integration branch {branch} has a malformed worktree record"
            )
        matches.append(Path(worktree_lines[0]).resolve())
    if len(matches) > 1:
        raise ArchiveError(f"integration branch {branch} is checked out more than once")
    return matches[0] if matches else None


def remove_registered_worktree(project: Path, branch: str, expected_path: Path) -> None:
    registered = registered_worktree(project, branch)
    if registered is None:
        if expected_path.exists() or expected_path.is_symlink():
            raise ArchiveError(f"unregistered integration worktree path exists: {expected_path}")
        return
    if registered != expected_path.resolve():
        raise ArchiveError(
            f"integration branch {branch} is checked out at unexpected path: {registered}"
        )
    status = archive_milestone.require_git_success(
        run_git(registered, "status", "--porcelain", "--untracked-files=all"),
        "inspect integration worktree status",
    )
    if status:
        raise ArchiveError("integration worktree is dirty; refusing cleanup")
    if registered.is_dir():
        _defuse_links(registered)
    archive_milestone.require_git_success(
        run_git(project, "worktree", "remove", str(registered)),
        "remove integration worktree",
    )


def delete_integration_branch(project: Path, branch: str, expected: str) -> None:
    ref = f"refs/heads/{branch}"
    actual = optional_ref(project, ref)
    if actual is None:
        return
    if actual != expected:
        raise ArchiveError(f"integration branch {branch} moved unexpectedly")
    archive_milestone.require_git_success(
        run_git(project, "update-ref", "-d", ref, expected),
        "delete integration branch",
    )


def require_generated_integration_commit(
    project: Path,
    commit: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    default_name: str,
    bound_branch: str,
    first_parent: Optional[str] = None,
) -> None:
    subject = archive_milestone.require_git_success(
        run_git(project, "show", "-s", "--format=%s", commit),
        "inspect integration commit subject",
    )
    expected_subject = integrate_subject(archive_name, default_name)
    if subject != expected_subject:
        raise ArchiveError(f"integration commit subject must be {expected_subject!r}")
    archive_milestone.require_canonical_commit_body(
        project,
        commit,
        expected_subject,
        integrate_commit_body(archive_path, ship_commit, default_name, bound_branch),
        "integration",
    )
    parents = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", commit),
        "inspect integration merge parents",
    ).split()
    if len(parents) != 3 or parents[2] != ship_commit:
        raise ArchiveError("integration commit is not the canonical merge of the ship commit")
    if first_parent is not None and parents[1] != first_parent:
        raise ArchiveError("integration merge was created from a stale remote default")


def discard_unpublished_stale_integration(
    project: Path,
    branch: str,
    merge_commit: str,
    remote_default_sha: str,
    default_name: str,
    archive_name: str,
    bound_branch: str,
) -> None:
    live_default = live_remote_ref(project, f"refs/heads/{default_name}")
    if live_default != remote_default_sha:
        raise ArchiveError(f"origin/{default_name} advanced again; rerun integrate")
    published = run_git(
        project, "merge-base", "--is-ancestor", merge_commit, remote_default_sha
    )
    if published.returncode == 0:
        raise ArchiveError(
            f"stale integration merge is already published on origin/{default_name}"
        )
    if published.returncode != 1:
        archive_milestone.require_git_success(published, "inspect stale integration publication")

    bound_ref = f"refs/heads/{bound_branch}"
    if live_remote_ref(project, bound_ref) is not None:
        raise ArchiveError(
            "stale integration recovery requires the remote bound branch to be absent"
        )
    tag_name = f"milestone/{archive_name}"
    published_tag_ref = f"refs/tags/{tag_name}"
    if live_remote_ref(project, published_tag_ref) is not None:
        raise ArchiveError(
            "stale integration recovery requires the remote milestone tag to be absent"
        )

    local_tag_ref = f"refs/tags/{tag_name}"
    local_tag_object = optional_ref(project, local_tag_ref)
    if local_tag_object is not None:
        require_annotated_tag(
            project,
            local_tag_ref,
            merge_commit,
            f"stale milestone tag {tag_name}",
        )
        archive_milestone.require_git_success(
            run_git(project, "update-ref", "-d", local_tag_ref, local_tag_object),
            "delete unpublished stale milestone tag",
        )

    tracking_tag_ref = f"refs/remotes/origin/tags/{tag_name}"
    tracking_tag_object = optional_ref(project, tracking_tag_ref)
    if tracking_tag_object is not None:
        if local_tag_object is None or tracking_tag_object != local_tag_object:
            raise ArchiveError("local published-tag tracking ref is not safely recoverable")
        archive_milestone.require_git_success(
            run_git(
                project,
                "update-ref",
                "-d",
                tracking_tag_ref,
                tracking_tag_object,
            ),
            "delete stale published-tag tracking ref",
        )
    delete_integration_branch(project, branch, merge_commit)


def create_integration_merge(
    project: Path,
    worktree: Path,
    branch: str,
    remote_default_sha: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    default_name: str,
    bound_branch: str,
) -> tuple[str, bool]:
    if worktree.exists() or worktree.is_symlink():
        raise ArchiveError(f"integration worktree path already exists: {worktree}")
    branch_ref = f"refs/heads/{branch}"
    branch_tip = optional_ref(project, branch_ref)
    if branch_tip is None:
        add = run_git(
            project,
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(worktree),
            remote_default_sha,
        )
    elif branch_tip == remote_default_sha:
        add = run_git(project, "worktree", "add", "--quiet", str(worktree), branch)
    else:
        require_generated_integration_commit(
            project,
            branch_tip,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
        parents = archive_milestone.require_git_success(
            run_git(project, "rev-list", "--parents", "-n", "1", branch_tip),
            "inspect existing integration merge parents",
        ).split()
        if parents[1] == remote_default_sha:
            return branch_tip, False
        discard_unpublished_stale_integration(
            project,
            branch,
            branch_tip,
            remote_default_sha,
            default_name,
            archive_name,
            bound_branch,
        )
        add = run_git(
            project,
            "worktree",
            "add",
            "--quiet",
            "-b",
            branch,
            str(worktree),
            remote_default_sha,
        )
    archive_milestone.require_git_success(add, "create integration worktree")

    merge = run_git(
        worktree,
        "merge",
        "--no-ff",
        "-m",
        integrate_subject(archive_name, default_name),
        "-m",
        integrate_commit_body(archive_path, ship_commit, default_name, bound_branch),
        ship_commit,
    )
    if merge.returncode != 0:
        conflicted = optional_ref(worktree, "MERGE_HEAD") is not None
        detail = (merge.stderr or merge.stdout).strip()
        conflicts = ""
        if conflicted:
            conflicts = run_git(
                worktree, "diff", "--name-only", "--diff-filter=U"
            ).stdout.strip()
            archive_milestone.require_git_success(
                run_git(worktree, "merge", "--abort"),
                "abort integration merge",
            )
        remove_registered_worktree(project, branch, worktree)
        delete_integration_branch(project, branch, remote_default_sha)
        if conflicted:
            raise ArchiveError(
                "integration merge conflicted; Git aborted it without resolving files: "
                + ", ".join(conflicts.splitlines())
                + "; closed milestone remains unchanged; run gsd-path-forensics and "
                "obtain a user-approved integration recovery plan; do not merge into or re-ship the bound branch"
            )
        raise ArchiveError(f"create integration merge failed: {detail}")

    merge_commit = archive_milestone.require_git_success(
        run_git(worktree, "rev-parse", "HEAD"), "resolve integration merge"
    )
    require_generated_integration_commit(
        project,
        merge_commit,
        archive_path,
        archive_name,
        ship_commit,
        default_name,
        bound_branch,
        remote_default_sha,
    )
    return merge_commit, True


def require_annotated_tag(
    project: Path,
    ref: str,
    merge_commit: str,
    label: str,
    message: Optional[str] = None,
) -> str:
    object_id = optional_ref(project, ref)
    if object_id is None:
        raise ArchiveError(f"missing {label}")
    tag_type = archive_milestone.require_git_success(
        run_git(project, "cat-file", "-t", ref), f"inspect {label}"
    )
    if tag_type != "tag":
        raise ArchiveError(f"{label} must be annotated")
    target = archive_milestone.require_git_success(
        run_git(project, "rev-parse", f"{ref}^{{commit}}"), f"resolve {label} target"
    )
    if target != merge_commit:
        raise ArchiveError(f"{label} does not point at the integration merge")
    if message is not None:
        actual_message = archive_milestone.require_git_success(
            run_git(project, "for-each-ref", "--format=%(contents)", ref),
            f"inspect {label} message",
        )
        if actual_message != message.strip():
            raise ArchiveError(f"{label} has unexpected metadata")
    return object_id


def ensure_integration_tag(
    project: Path,
    tag_name: str,
    merge_commit: str,
    message: Optional[str] = None,
) -> tuple[str, bool]:
    tag_ref = f"refs/tags/{tag_name}"
    tracking_ref = f"refs/remotes/origin/tags/{tag_name}"
    local_object = optional_ref(project, tag_ref)
    published_object = live_remote_ref(project, tag_ref)
    tracking_object = optional_ref(project, tracking_ref)
    if tracking_object != published_object:
        if published_object is None:
            archive_milestone.require_git_success(
                run_git(project, "update-ref", "-d", tracking_ref, tracking_object),
                "prune local milestone-tag ref",
            )
        else:
            archive_milestone.require_git_success(
                run_git(project, "update-ref", tracking_ref, published_object),
                "refresh local milestone-tag ref",
            )
    if published_object is not None:
        published_object = require_annotated_tag(
            project,
            tracking_ref,
            merge_commit,
            f"published milestone tag {tag_name}",
            message,
        )
    if local_object is None:
        if published_object is not None:
            archive_milestone.require_git_success(
                run_git(project, "update-ref", tag_ref, published_object),
                "restore local milestone tag",
            )
        else:
            tag_message = message or f"milestone {tag_name.removeprefix('milestone/')}"
            archive_milestone.require_git_success(
                run_git(
                    project,
                    "tag",
                    "--no-sign",
                    "-a",
                    "-m",
                    tag_message,
                    tag_name,
                    merge_commit,
                ),
                "create milestone tag",
            )
    local_object = require_annotated_tag(
        project,
        tag_ref,
        merge_commit,
        f"milestone tag {tag_name}",
        message,
    )
    if published_object is not None and published_object != local_object:
        raise ArchiveError(f"local and published milestone tag {tag_name} differ")
    return local_object, published_object is not None


def github_repository(project: Path) -> str:
    remote = archive_milestone.require_git_success(
        run_git(project, "config", "--get", "remote.origin.url"),
        "read configured origin URL",
    )
    patterns = (
        r"https://github\.com/([^/]+/[^/]+?)(?:\.git)?$",
        r"git@github\.com:([^/]+/[^/]+?)(?:\.git)?$",
        r"ssh://git@github\.com/([^/]+/[^/]+?)(?:\.git)?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, remote)
        if match:
            return match.group(1)
    raise ArchiveError("pull-request integration requires a GitHub.com origin")


def require_github_authentication() -> None:
    archive_milestone.require_git_success(
        run_command("gh", "auth", "status", "--hostname", GITHUB_HOST),
        "verify GitHub authentication",
    )


def github_api_json(*arguments: str) -> object:
    output = archive_milestone.require_git_success(
        run_command("gh", "api", "--hostname", GITHUB_HOST, *arguments),
        "call GitHub API",
    )
    try:
        return json.loads(output)
    except json.JSONDecodeError as error:
        raise ArchiveError("GitHub API returned invalid JSON") from error


def require_pull_request_shape(value: object) -> dict:
    if not isinstance(value, dict):
        raise ArchiveError("GitHub pull request response is not an object")
    required = {
        "number",
        "state",
        "html_url",
        "merged_at",
        "merge_commit_sha",
        "base",
        "head",
    }
    if not required.issubset(value):
        raise ArchiveError("GitHub pull request response is missing fields")
    if not isinstance(value["base"], dict) or not isinstance(value["head"], dict):
        raise ArchiveError("GitHub pull request refs are invalid")
    number = value["number"]
    if not isinstance(number, int) or isinstance(number, bool) or number < 1:
        raise ArchiveError("GitHub pull request response has invalid fields")
    if value["state"] not in {"open", "closed"}:
        raise ArchiveError("GitHub pull request response has invalid fields")
    html_url = value["html_url"]
    if not isinstance(html_url, str) or re.fullmatch(
        rf"https://github\.com/[^/]+/[^/]+/pull/{number}", html_url
    ) is None:
        raise ArchiveError("GitHub pull request response has invalid fields")
    merged_at = value["merged_at"]
    if merged_at is not None and not isinstance(merged_at, str):
        raise ArchiveError("GitHub pull request response has invalid fields")
    merge_commit = value["merge_commit_sha"]
    if merge_commit is not None and (
        not isinstance(merge_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", merge_commit) is None
    ):
        raise ArchiveError("GitHub pull request response has invalid fields")
    if not isinstance(value["base"].get("ref"), str):
        raise ArchiveError("GitHub pull request response has invalid fields")
    if not isinstance(value["head"].get("ref"), str):
        raise ArchiveError("GitHub pull request response has invalid fields")
    head_sha = value["head"].get("sha")
    if not isinstance(head_sha, str) or re.fullmatch(r"[0-9a-f]{40}", head_sha) is None:
        raise ArchiveError("GitHub pull request response has invalid fields")
    return value


def require_pull_request_pages(value: object) -> list[dict]:
    if not isinstance(value, list) or any(
        not isinstance(page, list) for page in value
    ):
        raise ArchiveError("GitHub pull request pages are invalid")
    return [require_pull_request_shape(item) for page in value for item in page]


def pull_request_head_matches_repository(pull: dict, repository: str) -> bool:
    head_repository = pull["head"].get("repo")
    full_name = (
        head_repository.get("full_name")
        if isinstance(head_repository, dict)
        else None
    )
    return isinstance(full_name, str) and full_name.casefold() == repository.casefold()


def require_pull_request_identity(
    repository: str,
    pull: dict,
    branch: str,
    ship_commit: str,
    base: str = "main",
) -> None:
    if pull["base"].get("ref") != base:
        raise ArchiveError(f"GitHub pull request base is not {base}")
    if pull["head"].get("ref") != branch:
        raise ArchiveError("GitHub pull request head is not the bound branch")
    if pull["head"].get("sha") != ship_commit:
        raise ArchiveError("GitHub pull request head is not the ship commit")
    if not pull_request_head_matches_repository(pull, repository):
        raise ArchiveError("GitHub pull request head repository is not origin")


def find_pull_request(
    repository: str, branch: str, ship_commit: str, base: str = "main"
) -> Optional[dict]:
    pulls = require_pull_request_pages(
        github_api_json(
            f"repos/{repository}/pulls",
            "--method",
            "GET",
            "-f",
            "state=all",
            "-f",
            f"base={base}",
            "--paginate",
            "--slurp",
        )
    )
    pulls = [
        pull
        for pull in pulls
        if pull["base"].get("ref") == base
        and (
            pull["head"].get("sha") == ship_commit
            # Closed unmerged PRs from an abandoned cycle must not shadow the re-ship.
            or (
                pull["head"].get("ref") == branch
                and pull["state"] == "open"
                and pull_request_head_matches_repository(pull, repository)
            )
        )
    ]
    if len(pulls) > 1:
        raise ArchiveError(f"multiple pull requests target {base} from the ship commit")
    if not pulls:
        return None
    pull = pulls[0]
    require_pull_request_identity(repository, pull, branch, ship_commit, base)
    return pull


def pull_request_body(
    archive_path: str, ship_commit: str, branch: str, base: str = "main"
) -> str:
    return (
        f"{integrate_commit_body(archive_path, ship_commit, base, branch)}"
        f"\n\n---\n{PR_CREDIT_LINE}"
    )


def update_pull_request_body(
    repository: str,
    pull: dict,
    archive_path: str,
    ship_commit: str,
    branch: str,
    expected_body: Optional[str] = None,
    base: str = "main",
) -> dict:
    expected = (
        expected_body if expected_body is not None
        else pull_request_body(archive_path, ship_commit, branch, base)
    )
    current = pull.get("body")
    if isinstance(current, str) and current.rstrip().endswith(PR_CREDIT_LINE):
        return pull
    response = github_api_json(
        f"repos/{repository}/pulls/{pull['number']}",
        "--method",
        "PATCH",
        "-f",
        f"body={expected}",
    )
    updated = require_pull_request_shape(response)
    require_pull_request_identity(repository, updated, branch, ship_commit, base)
    if updated.get("body") != expected:
        raise ArchiveError("updated GitHub pull request is missing the credit footer")
    return updated


def create_pull_request(
    repository: str,
    branch: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    base: str = "main",
) -> dict:
    body = pull_request_body(archive_path, ship_commit, branch, base)
    response = github_api_json(
        f"repos/{repository}/pulls",
        "--method",
        "POST",
        "-f",
        f"title={integrate_subject(archive_name, base)}",
        "-f",
        f"head={branch}",
        "-f",
        f"base={base}",
        "-f",
        f"body={body}",
    )
    pull = require_pull_request_shape(response)
    require_pull_request_identity(repository, pull, branch, ship_commit, base)
    return pull


def close_pull_request(repository: str, pull: dict) -> dict:
    response = github_api_json(
        f"repos/{repository}/pulls/{pull['number']}",
        "--method",
        "PATCH",
        "-f",
        "state=closed",
    )
    updated = require_pull_request_shape(response)
    if updated["state"] != "closed" or updated["merged_at"] is not None:
        raise ArchiveError("GitHub pull request did not close without merging")
    return updated


def pull_request_tag_message(
    archive_name: str,
    pull_request: str,
    ship_commit: str,
    landing: str,
) -> str:
    return (
        f"milestone {archive_name}\n\n"
        "Mode: pull-request\n"
        f"Pull-Request: {pull_request}\n"
        f"Ship: {ship_commit}\n"
        f"Landing: {landing}"
    )


def pull_request_tag_metadata(project: Path, tag_ref: str) -> dict[str, str]:
    fields = archive_milestone.tag_metadata_fields(project, tag_ref)
    if set(fields) != {"Mode", "Pull-Request", "Ship", "Landing"}:
        raise ArchiveError("pull-request milestone tag is missing metadata")
    if fields["Mode"] != "pull-request":
        raise ArchiveError("pull-request milestone tag has the wrong mode")
    return fields


def external_landing_tag_message(
    archive_name: str, ship_commit: str, landing: str
) -> str:
    return (
        f"milestone {archive_name}\n\n"
        "Mode: external-landing\n"
        f"Ship: {ship_commit}\n"
        f"Landing: {landing}"
    )


def external_landing_tag_metadata(project: Path, tag_ref: str) -> dict[str, str]:
    message = archive_milestone.require_git_success(
        run_git(project, "for-each-ref", "--format=%(contents)", tag_ref),
        "inspect external-landing milestone tag",
    )
    fields: dict[str, str] = {}
    for line in message.splitlines():
        match = re.fullmatch(r"(Mode|Ship|Landing): (.+)", line)
        if match:
            if match.group(1) in fields:
                raise ArchiveError("external-landing milestone tag repeats metadata")
            fields[match.group(1)] = match.group(2)
    if set(fields) != {"Mode", "Ship", "Landing"}:
        raise ArchiveError("external-landing milestone tag is missing metadata")
    if fields["Mode"] != "external-landing":
        raise ArchiveError("external-landing milestone tag has the wrong mode")
    return fields


def require_pull_request_merge(
    project: Path,
    merge_commit: str,
    ship_commit: str,
    remote_default: str,
    *,
    allow_rebase: bool = False,
) -> None:
    resolved = optional_ref(project, merge_commit)
    if resolved != merge_commit:
        raise ArchiveError("GitHub merge commit is unavailable after fetch")
    parents = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", merge_commit),
        "inspect pull-request merge parents",
    ).split()
    if allow_rebase and len(parents) == 2:
        problem = _common.rebase_landing_problem(project, ship_commit, merge_commit)
        if problem is not None:
            raise ArchiveError(
                "pull-request integration must use a two-parent merge commit "
                f"or a rebase merge of the ship commits: {problem}"
            )
    elif len(parents) != 3:
        raise ArchiveError("pull-request integration must use a two-parent merge commit")
    elif parents[2] != ship_commit:
        raise ArchiveError("pull-request merge second parent is not the ship commit")
    first_parent = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--first-parent", remote_default),
        "inspect remote-default first-parent history",
    ).splitlines()
    if merge_commit not in first_parent:
        raise ArchiveError(
            f"pull-request merge is not on {remote_default} first-parent history"
        )


def require_pull_request_merge_provenance(
    repository: str,
    number: int,
    merge_commit: Optional[str] = None,
) -> None:
    owner, name = repository.split("/", 1)
    query = """query($owner:String!,$name:String!,$number:Int!){
  repository(owner:$owner,name:$name){
    pullRequest(number:$number){
      mergeQueue:timelineItems(first:1,itemTypes:[ADDED_TO_MERGE_QUEUE_EVENT]){
        nodes{__typename}
      }
      autoMerge:timelineItems(first:1,itemTypes:[AUTO_MERGE_ENABLED_EVENT]){
        nodes{__typename}
      }
      mergeAction:timelineItems(last:1,itemTypes:[MERGED_EVENT]){
        nodes{__typename ... on MergedEvent{actor{__typename login} commit{oid}}}
      }
    }
  }
}"""
    payload = github_api_json(
        "graphql",
        "-f",
        f"query={query}",
        "-F",
        f"owner={owner}",
        "-F",
        f"name={name}",
        "-F",
        f"number={number}",
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    repository_data = data.get("repository") if isinstance(data, dict) else None
    pull_request = (
        repository_data.get("pullRequest")
        if isinstance(repository_data, dict)
        else None
    )
    checks = (
        (
            "mergeQueue",
            "AddedToMergeQueueEvent",
            "GitHub merge-queue provenance is invalid",
            "pull-request integration cannot use a merge queue",
        ),
        (
            "autoMerge",
            "AutoMergeEnabledEvent",
            "GitHub auto-merge provenance is invalid",
            "pull-request integration cannot use auto-merge",
        ),
    )
    for field, typename, invalid_message, rejection_message in checks:
        timeline = pull_request.get(field) if isinstance(pull_request, dict) else None
        nodes = timeline.get("nodes") if isinstance(timeline, dict) else None
        if not isinstance(nodes, list):
            raise ArchiveError(invalid_message)
        if nodes:
            if any(
                not isinstance(node, dict) or node.get("__typename") != typename
                for node in nodes
            ):
                raise ArchiveError(invalid_message)
            raise ArchiveError(rejection_message)
    merge_timeline = (
        pull_request.get("mergeAction")
        if isinstance(pull_request, dict)
        else None
    )
    merge_nodes = (
        merge_timeline.get("nodes")
        if isinstance(merge_timeline, dict)
        else None
    )
    if not isinstance(merge_nodes, list):
        raise ArchiveError("GitHub pull-request merge provenance is invalid")
    if merge_commit is None:
        if merge_nodes:
            raise ArchiveError("open pull request has invalid merge provenance")
        return
    if len(merge_nodes) != 1:
        raise ArchiveError("pull request was not merged by a GitHub merge action")
    merge_node = merge_nodes[0]
    commit = merge_node.get("commit") if isinstance(merge_node, dict) else None
    actor = merge_node.get("actor") if isinstance(merge_node, dict) else None
    if (
        not isinstance(merge_node, dict)
        or merge_node.get("__typename") != "MergedEvent"
        or not isinstance(commit, dict)
        or commit.get("oid") != merge_commit
    ):
        raise ArchiveError("GitHub pull-request merge action does not match landing")
    if (
        not isinstance(actor, dict)
        or actor.get("__typename") != "User"
        or not isinstance(actor.get("login"), str)
        or not actor["login"]
    ):
        raise ArchiveError("pull request must be merged by a human GitHub user")


def integrate_pull_request(
    project: Path,
    state: PipelineState,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
) -> dict:
    branch = state.branch
    if branch is None:
        raise ArchiveError("pull-request integration requires a bound branch")
    require_github_authentication()
    repository = github_repository(project)
    base = state.default_branch
    pull = find_pull_request(repository, branch, ship_commit, base)
    if pull is None:
        publish_bound_branch(project, branch, ship_commit)
        pull = create_pull_request(
            repository,
            branch,
            archive_path,
            archive_name,
            ship_commit,
            base,
        )
    elif pull["merged_at"] is None:
        if pull["state"] != "open":
            raise ArchiveError("GitHub pull request was closed without merging")
        pull = update_pull_request_body(
            repository,
            pull,
            archive_path,
            ship_commit,
            branch,
            base=base,
        )
    if pull["merged_at"] is None:
        if pull["state"] != "open":
            raise ArchiveError("GitHub pull request was closed without merging")
        publish_bound_branch(project, branch, ship_commit)
        require_pull_request_merge_provenance(repository, pull["number"])
        return {
            "status": "awaiting-merge",
            "mode": "pull-request",
            "archive": archive_path,
            "commit": ship_commit,
            "pull_request": pull["html_url"],
        }

    merge_commit = pull["merge_commit_sha"]
    if pull["state"] != "closed" or not isinstance(merge_commit, str):
        raise ArchiveError("GitHub pull request merge metadata is invalid")
    require_pull_request_merge_provenance(
        repository,
        pull["number"],
        merge_commit,
    )
    remote_default = refresh_origin(project)["remote_default"]
    require_pull_request_merge(
        project, merge_commit, ship_commit, remote_default, allow_rebase=True
    )
    pull = update_pull_request_body(
        repository,
        pull,
        archive_path,
        ship_commit,
        branch,
        base=base,
    )
    tag_name = f"milestone/{archive_name}"
    message = pull_request_tag_message(
        archive_name,
        pull["html_url"],
        ship_commit,
        merge_commit,
    )
    tag_object, tag_published = ensure_integration_tag(
        project,
        tag_name,
        merge_commit,
        message,
    )
    if not tag_published:
        archive_milestone.require_git_success(
            run_git(
                project,
                "push",
                "origin",
                f"refs/tags/{tag_name}:refs/tags/{tag_name}",
            ),
            "push milestone tag",
        )
        archive_milestone.require_git_success(
            run_git(
                project,
                "update-ref",
                f"refs/remotes/origin/tags/{tag_name}",
                tag_object,
            ),
            "refresh local milestone-tag ref",
        )
    return validate_integrated(project, archive_milestone.milestone_slug(state))


def integrate_external_landing(
    project: Path,
    state: PipelineState,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
    remote_default: str,
    default_name: str,
    bound_branch: str,
) -> dict:
    if state.branch is None:
        raise ArchiveError("external-landing integration requires a bound branch")
    publishable_bound_branch(project, bound_branch, ship_commit)
    contains_ship = run_git(
        project, "merge-base", "--is-ancestor", ship_commit, remote_default
    )
    if contains_ship.returncode == 1:
        publish_bound_branch(project, bound_branch, ship_commit)
        return {
            "status": "awaiting-merge",
            "mode": "external-landing",
            "archive": archive_path,
            "commit": ship_commit,
            "branch": bound_branch,
            "merge_subject": integrate_subject(archive_name, default_name),
            "merge_body": integrate_commit_body(
                archive_path, ship_commit, default_name, bound_branch
            ),
        }
    if contains_ship.returncode != 0:
        archive_milestone.require_git_success(
            contains_ship, "inspect ship ancestry on the remote default"
        )
        raise AssertionError("unreachable")

    merge_commit = find_integrate_commit(
        project, remote_default, archive_name, ship_commit
    )
    require_generated_integration_commit(
        project,
        merge_commit,
        archive_path,
        archive_name,
        ship_commit,
        default_name,
        bound_branch,
    )
    tag_name = f"milestone/{archive_name}"
    message = external_landing_tag_message(archive_name, ship_commit, merge_commit)
    tag_object, tag_published = ensure_integration_tag(
        project,
        tag_name,
        merge_commit,
        message,
    )
    if not tag_published:
        archive_milestone.require_git_success(
            run_git(
                project,
                "push",
                "origin",
                f"refs/tags/{tag_name}:refs/tags/{tag_name}",
            ),
            "push milestone tag",
        )
        archive_milestone.require_git_success(
            run_git(
                project,
                "update-ref",
                f"refs/remotes/origin/tags/{tag_name}",
                tag_object,
            ),
            "refresh local milestone-tag ref",
        )
    return validate_integrated(project, archive_milestone.milestone_slug(state))


def integrate(repo: Path, slug: str, adopt_published: Optional[str] = None) -> dict:
    project = repo.resolve()
    active_root = archive_milestone.require_project_layout(project)
    state, _, loaded_state_path = archive_milestone.strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    expected_slug = archive_milestone.milestone_slug(state)
    if archive_milestone.normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )

    shipped = archive_milestone.validate(project)
    archive_path = shipped["archive"]
    ship_commit = shipped["commit"]
    archive_name = PurePosixPath(archive_path).name
    bound_branch = state.branch
    expected_branch = bound_branch_name(milestone_number(archive_name))
    if bound_branch != expected_branch:
        raise ArchiveError(f"integration requires canonical bound branch {expected_branch}")
    head = archive_milestone.require_git_success(
        run_git(project, "rev-parse", "HEAD"), "resolve bound branch HEAD"
    )
    if head != ship_commit:
        raise ArchiveError("bound worktree must remain at the ship commit during integration")
    subject = archive_milestone.require_git_success(
        run_git(project, "show", "-s", "--format=%s", ship_commit),
        "inspect ship commit subject",
    )
    if subject != ship_subject(archive_name):
        raise ArchiveError("integration only generates canonical M00N shipment history")

    remote_default = refresh_origin(project)["remote_default"]
    default_name = default_branch_name(remote_default)
    if default_name != state.default_branch:
        raise ArchiveError(
            f"remote default must be {state.default_branch}, got {default_name!r}"
        )
    if bound_branch == default_name:
        raise ArchiveError("bound branch must not be the remote default")
    remote_default_sha = archive_milestone.require_git_success(
        run_git(project, "rev-parse", remote_default), "resolve remote default"
    )
    if adopt_published is not None and state.integration != "direct":
        raise ArchiveError(
            "--adopt-published-bound applies only to direct integration, "
            f"not {state.integration}")
    if state.integration == "pull-request":
        return integrate_pull_request(
            project,
            state,
            archive_path,
            archive_name,
            ship_commit,
        )
    if state.integration == "external-landing":
        return integrate_external_landing(
            project,
            state,
            archive_path,
            archive_name,
            ship_commit,
            remote_default,
            default_name,
            bound_branch,
        )
    publishable_bound_branch(project, bound_branch, ship_commit, adopt_published)
    integration_branch, worktree = integration_names(project, archive_name, pin=True)
    interrupted_worktree = registered_worktree(project, integration_branch)
    if (
        interrupted_worktree is not None
        and optional_ref(interrupted_worktree, "MERGE_HEAD") is not None
    ):
        if interrupted_worktree != worktree.resolve():
            raise ArchiveError(
                f"integration branch {integration_branch} is checked out at unexpected path: "
                f"{interrupted_worktree}"
            )
        conflicts = run_git(
            interrupted_worktree, "diff", "--name-only", "--diff-filter=U"
        ).stdout.strip()
        archive_milestone.require_git_success(
            run_git(interrupted_worktree, "merge", "--abort"),
            "abort interrupted integration merge",
        )
        remove_registered_worktree(project, integration_branch, worktree)
        interrupted_tip = optional_ref(project, f"refs/heads/{integration_branch}")
        if interrupted_tip is not None:
            delete_integration_branch(project, integration_branch, interrupted_tip)
        raise ArchiveError(
            "interrupted integration merge conflicted; Git aborted it without resolving files: "
            + ", ".join(conflicts.splitlines())
            + "; closed milestone remains unchanged; run gsd-path-forensics and "
            "obtain a user-approved integration recovery plan; do not merge into or re-ship the bound branch"
        )
    remove_registered_worktree(project, integration_branch, worktree)
    worktree_active = False

    contains_ship = run_git(
        project, "merge-base", "--is-ancestor", ship_commit, remote_default
    )
    if contains_ship.returncode == 0:
        merge_commit = find_integrate_commit(
            project, remote_default, archive_name, ship_commit
        )
        require_generated_integration_commit(
            project,
            merge_commit,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
    elif contains_ship.returncode == 1:
        merge_commit, worktree_active = create_integration_merge(
            project,
            worktree,
            integration_branch,
            remote_default_sha,
            archive_path,
            archive_name,
            ship_commit,
            default_name,
            bound_branch,
        )
    else:
        archive_milestone.require_git_success(contains_ship, "inspect ship ancestry on the remote default")
        raise AssertionError("unreachable")

    action_error = None
    try:
        tag_name = f"milestone/{archive_name}"
        tag_object, tag_published = ensure_integration_tag(
            project, tag_name, merge_commit
        )

        published_merge = run_git(
            project, "merge-base", "--is-ancestor", merge_commit, remote_default
        )
        if published_merge.returncode == 1:
            archive_milestone.require_git_success(
                run_git(
                    project,
                    "push",
                    "origin",
                    f"{merge_commit}:refs/heads/{default_name}",
                ),
                f"push integration merge to {default_name}",
            )
            archive_milestone.require_git_success(
                run_git(project, "update-ref", f"refs/remotes/{remote_default}", merge_commit),
                "refresh local remote-default ref",
            )
        elif published_merge.returncode != 0:
            archive_milestone.require_git_success(published_merge, "inspect published integration merge")

        publish_bound_branch(project, bound_branch, ship_commit, adopt_published)
        if not tag_published:
            archive_milestone.require_git_success(
                run_git(
                    project,
                    "push",
                    "origin",
                    f"refs/tags/{tag_name}:refs/tags/{tag_name}",
                ),
                "push milestone tag",
            )
            archive_milestone.require_git_success(
                run_git(
                    project,
                    "update-ref",
                    f"refs/remotes/origin/tags/{tag_name}",
                    tag_object,
                ),
                "refresh local milestone-tag ref",
            )
    except (ArchiveError, OSError) as error:
        action_error = error

    try:
        if worktree_active:
            remove_registered_worktree(project, integration_branch, worktree)
    except (ArchiveError, OSError) as cleanup_error:
        if action_error is not None:
            raise ArchiveError(
                f"{action_error}; integration worktree cleanup failed: {cleanup_error}"
            )
        raise
    if action_error is not None:
        raise action_error

    branch_tip = optional_ref(project, f"refs/heads/{integration_branch}")
    if branch_tip is not None:
        if branch_tip != merge_commit:
            ancestor = run_git(
                project, "merge-base", "--is-ancestor", branch_tip, merge_commit
            )
            if ancestor.returncode != 0:
                raise ArchiveError(f"integration branch {integration_branch} moved unexpectedly")
        delete_integration_branch(project, integration_branch, branch_tip)
    return validate_integrated(project, slug)


ABANDON_INTEGRATION_SCHEMA = "gsd-path/abandon-integration/v1"
ABANDON_INTEGRATION_JOURNAL_NAME = "gsd-path-abandon-integration.json"
ABANDON_INTEGRATION_RISK = "published integration checks"
ABANDON_INTEGRATION_FIX_DIRECTION = "Fix the failing forge check; re-run the final gate."


def abandon_integration_journal_path(project: Path) -> Path:
    common = archive_milestone.require_git_success(
        run_git(project, "rev-parse", "--path-format=absolute", "--git-common-dir"),
        "resolve common Git directory",
    )
    path = Path(common)
    if not path.is_absolute():
        path = project / path
    return path.resolve() / ABANDON_INTEGRATION_JOURNAL_NAME


def read_abandon_integration_journal(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ArchiveError(
            f"abandon-integration journal is unreadable: {path}"
        ) from error
    fields = {
        "schema",
        "repo",
        "slug",
        "finding",
        "ship_commit",
        "bound_ref",
        "pr_number",
        "expected_head",
        "abandoned_on",
    }
    if not isinstance(payload, dict) or set(payload) != fields:
        raise ArchiveError("abandon-integration journal has invalid fields")
    if payload["schema"] != ABANDON_INTEGRATION_SCHEMA or any(
        not isinstance(payload[field], str) or not payload[field]
        for field in fields - {"schema", "pr_number"}
    ):
        raise ArchiveError("abandon-integration journal has invalid values")
    number = payload["pr_number"]
    branch = payload["bound_ref"].removeprefix("refs/heads/")
    if (
        not isinstance(number, int)
        or isinstance(number, bool)
        or number < 1
        or not re.fullmatch(r"[0-9a-f]{40,64}", payload["ship_commit"])
        or not re.fullmatch(r"[0-9a-f]{40,64}", payload["expected_head"])
        or payload["bound_ref"] != f"refs/heads/{branch}"
        or not is_bound_branch(branch)
    ):
        raise ArchiveError("abandon-integration journal has invalid transaction metadata")
    try:
        date.fromisoformat(payload["abandoned_on"])
    except ValueError as error:
        raise ArchiveError("abandon-integration journal has invalid transaction date") from error
    return payload


def write_abandon_integration_journal(path: Path, payload: Mapping[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    archive_milestone.atomic_replace(
        path, temporary, json.dumps(payload, sort_keys=True) + "\n"
    )


def require_open_unmerged_pull(
    repository: str,
    branch: str,
    ship_commit: str,
    base: str,
    journal: Optional[dict] = None,
) -> dict:
    pull = find_pull_request(repository, branch, ship_commit, base)
    if pull is None:
        raise ArchiveError(
            "published integration abandon requires the milestone pull request to exist"
        )
    if pull["merged_at"] is not None:
        raise ArchiveError(
            "published integration abandon refuses a merged pull request"
        )
    if pull["state"] != "open":
        if journal is None or pull["number"] != journal["pr_number"]:
            raise ArchiveError(
                "GitHub pull request was closed without merging; "
                "only the abandon-integration journal may adopt a closed request"
            )
    return pull


def restore_abandoned_archive(project: Path, active_root: Path, archive: Path) -> None:
    """Reverse prepare's archive move: back to the active .project/ root."""
    if archive.is_symlink() or not archive.is_dir():
        raise ArchiveError(f"abandoned archive must be a real directory: {archive}")
    archive_device = archive.stat().st_dev
    for name in archive_milestone.TRANSACTION_DIRECTORIES:
        source = archive / name
        destination = active_root / name
        if source.is_symlink() or destination.is_symlink():
            raise ArchiveError(f"restore transaction paths must not be symlinks: {name}")
        if not source.exists():
            if destination.exists():
                continue  # already restored by an earlier interrupted run
            if name in archive_milestone.DIRECTORIES_TO_ARCHIVE:
                raise ArchiveError(f"missing both active and archived {name}")
            continue
        if destination.exists():
            if not (
                name == "research"
                and archive_milestone.is_existing_carry_forward(destination, source)
            ):
                raise ArchiveError(f"restore collision: both {destination} and {source} exist")
            # prepare's carry-forward copy is byte-identical; drop it before the move.
            shutil.rmtree(destination)
        if source.stat().st_dev != archive_device:
            raise ArchiveError(f"restore move crosses filesystems: {source}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
    leftovers = sorted(
        path
        for path in archive.rglob("*")
        if not _common.is_ignored_junk(path)
        and path.name not in {"MANIFEST.md", archive_milestone.MANIFEST_TEMP_NAME}
    )
    if leftovers:
        raise ArchiveError(
            "abandoned archive holds unexpected artifacts: "
            + ", ".join(path.name for path in leftovers)
        )
    shutil.rmtree(archive)


def restore_abandoned_roadmap(active_root: Path, slug: str, configured: str) -> None:
    """Reverse record_shipment's roadmap stamp: the milestone ships again.

    Single-flow milestones keep no ROADMAP.md; a program roadmap's shipped
    row is restored to its pre-ship `Status: active` and `Archive: null` so
    no row claims an archive directory the rollback removed.
    """
    roadmap_path = active_root / "ROADMAP.md"
    if not roadmap_path.exists():
        return
    if roadmap_path.is_symlink() or not roadmap_path.is_file():
        raise ArchiveError(f"program roadmap must be a real file: {roadmap_path}")
    text = roadmap_path.read_text(encoding="utf-8")
    try:
        sections = roadmap.strict_sections(text)
        if slug not in sections:
            raise roadmap.RoadmapError(f"ROADMAP.md is missing milestone {slug}")
        _, start, end = sections[slug]
        lines = text.splitlines(keepends=True)
        roadmap.replace_field(
            lines, start, end, "Status", {"shipped", "active"}, "active"
        )
        roadmap.replace_field(
            lines, start, end, "Archive", {configured, "null"}, "null"
        )
    except roadmap.RoadmapError as error:
        raise ArchiveError(
            f"published integration abandon cannot restore the roadmap: {error}"
        ) from error
    archive_milestone.atomic_replace(
        roadmap_path,
        roadmap_path.with_name(f".{roadmap_path.name}.gsd-path-tmp"),
        "".join(lines),
    )


def abandon_gap_review_text(reviewed_head: str, finding: str, number: int) -> str:
    risk_line = f"Risk: {ABANDON_INTEGRATION_RISK}"
    return (
        f"# Gap Review — {number}: {ABANDON_INTEGRATION_RISK}\n"
        "\n"
        "<!-- Written by archive_milestone.py abandon-integration from the owner's\n"
        "     verbatim failing-check report (#457). -->\n"
        "\n"
        f"Reviewed HEAD: {reviewed_head}\n"
        "Gap verdict: blocked\n"
        f"{risk_line}\n"
        "Waves checked: all\n"
        "\n"
        "## Checked evidence\n"
        "\n"
        "- **Check**: the published pull request's required forge checks\n"
        f"- **Observed**: {finding}\n"
        "- **Reference**: the milestone pull request\n"
        "\n"
        "## Finding\n"
        "\n"
        f"- **Found**: {finding}\n"
        f"- **Fix direction**: {ABANDON_INTEGRATION_FIX_DIRECTION}\n"
    )


def abandon_patch_findings_text(reviewed_head: str, finding: str, source: str) -> str:
    risk_line = f"Risk: {ABANDON_INTEGRATION_RISK}"
    return (
        "# Patch Findings\n"
        "\n"
        "<!-- Written by archive_milestone.py abandon-integration; consumed by patch\n"
        "     planning (#457). -->\n"
        "\n"
        f"Reviewed HEAD: {reviewed_head}\n"
        "State: ship/blocked\n"
        "\n"
        "## Findings\n"
        "\n"
        f"### P001 — {ABANDON_INTEGRATION_RISK}\n"
        "\n"
        f"- **Source**: `{source}`\n"
        f"- **Locator**: {risk_line}\n"
        f"- **Evidence**: {finding}\n"
        f"- **Fix direction**: {ABANDON_INTEGRATION_FIX_DIRECTION}\n"
    )


def abandon_findings_conflict(review: Path, finding: str) -> bool:
    """A PATCH-FINDINGS.md in ``review`` conflicts when this transaction
    cannot recognize its own deterministic bytes in it: a human revision or
    an earlier cycle's file. Checked in the proof phase — before any
    mutation — so the refusal stays one of the documented no-mutation
    blockers instead of firing after the pull request is closed."""

    findings_path = review / "PATCH-FINDINGS.md"
    if findings_path.is_symlink() or (
        findings_path.exists() and not findings_path.is_file()
    ):
        # Not a real file can never carry this transaction's bytes.
        return True
    if not findings_path.is_file():
        return False
    final = review / "FINAL.md"
    final_text: Optional[str] = None
    if archive_milestone.is_real_file(final):
        try:
            final_text = final.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            final_text = None
    reviewed = (
        re.search(r"(?m)^Reviewed HEAD:\s*(\S+)", final_text)
        if final_text is not None
        else None
    )
    if reviewed is None or not re.fullmatch(r"[0-9a-f]{40,64}", reviewed.group(1)):
        # Without FINAL.md's reviewed head the deterministic form cannot be
        # reconstructed, so the bytes cannot be proven ours.
        return True
    try:
        text = findings_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return True
    referenced: set[int] = set()
    for match in re.finditer(r"(?m)^- \*\*Source\*\*:\s*`?([^`\s]+)", text):
        number = archive_milestone.FINAL_GAP_FILE_PATTERN.fullmatch(
            PurePosixPath(match.group(1)).name
        )
        if number is not None:
            referenced.add(int(number.group(1)))
    return text not in {
        abandon_patch_findings_text(
            reviewed.group(1), finding, f".project/review/final-gap-{candidate}.md"
        )
        for candidate in sorted(referenced)
    }


def write_abandon_integration_findings(
    active_root: Path, finding: str
) -> str:
    review = active_root / "review"
    final = review / "FINAL.md"
    if not archive_milestone.is_real_file(final):
        raise ArchiveError("restored review/FINAL.md is missing")
    reviewed = re.search(
        r"(?m)^Reviewed HEAD:\s*(\S+)", final.read_text(encoding="utf-8")
    )
    if reviewed is None or not re.fullmatch(r"[0-9a-f]{40,64}", reviewed.group(1)):
        raise ArchiveError("restored FINAL.md has no valid Reviewed HEAD")

    def gap_text_for(number: int) -> str:
        return abandon_gap_review_text(reviewed.group(1), finding, number)

    def findings_text_for(source: str) -> str:
        return abandon_patch_findings_text(reviewed.group(1), finding, source)

    def gap_relative(number: int) -> str:
        return f".project/review/final-gap-{number}.md"

    existing = {
        int(match.group(1))
        for path in review.iterdir()
        if (match := archive_milestone.FINAL_GAP_FILE_PATTERN.fullmatch(path.name))
        is not None
    }
    findings_path = review / "PATCH-FINDINGS.md"
    if findings_path.is_symlink() or (
        findings_path.exists() and not findings_path.is_file()
    ):
        raise ArchiveError("review/PATCH-FINDINGS.md must be a real file")
    referenced: set[int] = set()
    findings_bytes: Optional[str] = None
    if archive_milestone.is_real_file(findings_path):
        findings_bytes = findings_path.read_text(encoding="utf-8")
        for match in re.finditer(r"(?m)^- \*\*Source\*\*:\s*`?([^`\s]+)", findings_bytes):
            number = archive_milestone.FINAL_GAP_FILE_PATTERN.fullmatch(
                PurePosixPath(match.group(1)).name
            )
            if number is not None:
                referenced.add(int(number.group(1)))
        # Never overwrite findings this transaction did not write: a file
        # whose bytes match no deterministic form of ours (a human revision,
        # a consumed earlier cycle's file) blocks loudly instead of falling
        # through to a replace.
        if findings_bytes not in {
            findings_text_for(gap_relative(candidate))
            for candidate in sorted(referenced)
        }:
            raise ArchiveError(
                "a PATCH-FINDINGS.md already exists with different content; "
                "resolve it before abandoning"
            )
    # Resume: adopt a number only when BOTH files this transaction wrote still
    # carry its deterministic bytes. A human revision to either file makes the
    # number not-ours; the writer then takes a fresh unused number instead of
    # overwriting the revision.
    number: Optional[int] = None
    if findings_bytes is not None:
        for candidate in sorted(referenced):
            if findings_bytes != findings_text_for(gap_relative(candidate)):
                continue
            gap_path = review / f"final-gap-{candidate}.md"
            if archive_milestone.is_real_file(gap_path) and gap_path.read_text(
                encoding="utf-8"
            ) == gap_text_for(candidate):
                number = candidate
                break
    if number is None:
        for candidate in sorted(existing):
            path = review / f"final-gap-{candidate}.md"
            if archive_milestone.is_real_file(path) and path.read_text(
                encoding="utf-8"
            ) == gap_text_for(candidate):
                number = candidate
                break
    if number is None:
        # First number no existing gap review uses and no findings file cites;
        # an earlier gap review is never overwritten.
        number = 1
        while number in existing or number in referenced:
            number += 1
    source = gap_relative(number)
    gap_path = review / f"final-gap-{number}.md"
    archive_milestone.atomic_replace(
        gap_path, gap_path.with_name(f".{gap_path.name}.gsd-path-tmp"), gap_text_for(number)
    )
    archive_milestone.atomic_replace(
        findings_path,
        findings_path.with_name(f".{findings_path.name}.gsd-path-tmp"),
        findings_text_for(source),
    )
    return source


def abandon_integration(repo: Path, slug: str, finding: str) -> dict:
    project = repo.resolve()
    active_root = archive_milestone.require_project_layout(project)
    requested_slug = archive_milestone.normalized_slug(slug)
    cleaned = finding.strip()
    if not cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ArchiveError(
            "abandon-integration requires a single-line --finding of the failing check output"
        )
    journal_path = abandon_integration_journal_path(project)
    if journal_path.is_symlink():
        raise ArchiveError(
            f"abandon-integration journal must not be a symlink: {journal_path}"
        )
    journal: Optional[dict] = None
    if journal_path.is_file():
        journal = read_abandon_integration_journal(journal_path)
    elif journal_path.exists():
        raise ArchiveError(
            f"abandon-integration journal must be a real file: {journal_path}"
        )
    if journal is not None:
        expected = {"repo": str(project), "slug": requested_slug, "finding": cleaned}
        mismatches = [key for key, value in expected.items() if journal[key] != value]
        if mismatches:
            raise ArchiveError(
                "abandon-integration request differs from journal fields: "
                + ", ".join(sorted(mismatches))
            )
        resolved = run_git(
            project, "rev-parse", "--verify", "--quiet", f"{journal['expected_head']}^{{commit}}"
        )
        if resolved.returncode != 0 or resolved.stdout.strip() != journal["expected_head"]:
            raise ArchiveError("abandon-integration journal expected HEAD no longer resolves")
    with archive_milestone.discussion_lock(active_root):
        context = abandon_integration_rollback(
            project, active_root, requested_slug, cleaned, journal_path, journal
        )
    # STATE's own transition takes the .project/ directory lock; run it outside
    # the discussion lock like the build abandon transaction does.
    return abandon_integration_finalize(
        project, active_root, requested_slug, cleaned, journal_path, context
    )


def abandon_integration_rollback(
    project: Path,
    active_root: Path,
    slug: str,
    finding: str,
    journal_path: Path,
    journal: Optional[dict],
) -> dict:
    state, _, loaded_state_path = archive_milestone.strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    if state.integration != "pull-request":
        raise ArchiveError(
            f"abandon-integration requires pull-request integration, not {state.integration}"
        )
    branch = state.branch
    if branch is None or not is_bound_branch(branch):
        raise ArchiveError("abandon-integration requires a canonical gsd-path/M00N branch")

    if journal is None:
        # A fresh entry derives its plan from the proven ship transaction.
        if (state.phase, state.status) != ("shipped", "done") or state.archive is None:
            raise ArchiveError(
                f"published integration abandon is not valid in state: "
                f"{state.phase}/{state.status}"
            )
        if archive_milestone.milestone_slug(state) != slug:
            raise ArchiveError(
                f"--slug {slug!r} does not match normalized STATE.milestone "
                f"{archive_milestone.milestone_slug(state)!r}"
            )
        shipped = archive_milestone.validate(project)
        ship_commit = shipped["commit"]
        configured = shipped["archive"]
        archive_name = PurePosixPath(configured).name
        if branch != bound_branch_name(milestone_number(archive_name)):
            raise ArchiveError(
                f"abandon-integration requires canonical bound branch "
                f"{bound_branch_name(milestone_number(archive_name))}"
            )
        head = archive_milestone.require_git_success(
            run_git(project, "rev-parse", "HEAD"), "resolve bound branch HEAD"
        )
        if head != ship_commit:
            raise ArchiveError(
                "bound worktree must remain at the ship commit during integration"
            )
        subject = archive_milestone.require_git_success(
            run_git(project, "show", "-s", "--format=%s", ship_commit),
            "inspect ship commit subject",
        )
        if subject != ship_subject(archive_name):
            raise ArchiveError(
                "abandon-integration only rolls back canonical M00N shipment history"
            )
    else:
        # A resumed entry replays the plan the journal recorded.
        ship_commit = journal["ship_commit"]
        branch = journal["bound_ref"].removeprefix("refs/heads/")
    bound_ref = f"refs/heads/{branch}"
    archive_name = f"{milestone_number(branch):03d}-{slug}"
    configured = f".project/archive/{archive_name}"
    archive = archive_milestone.archive_from_state(project, configured)
    state, _, _ = archive_milestone.strict_state(project)
    if state.branch != branch or not (
        (
            (state.phase, state.status) == ("shipped", "done")
            and state.archive == configured
        )
        or (state.phase, state.status, state.archive) == ("ship", "blocked", None)
    ):
        raise ArchiveError(
            "abandon-integration transaction has an invalid STATE.md: "
            f"{state.phase}/{state.status}"
        )

    # --- Proofs run on EVERY entry, fresh or resumed, before any mutation:
    # --- the local checkout first (a wrong worktree must refuse before any
    # --- remote mutation), then origin: a merge or tag that lands
    # --- mid-transaction must abort the rollback.
    # The findings refusal is documented as a no-mutation blocker, so whatever
    # review directory is live — the archive's on an early resume, the active
    # root's once the rollback restored it — must carry no foreign
    # PATCH-FINDINGS.md bytes before the pull request is touched.
    for live_review in (active_root / "review", archive / "review"):
        if abandon_findings_conflict(live_review, finding):
            raise ArchiveError(
                "a PATCH-FINDINGS.md already exists with different content; "
                "resolve it before abandoning"
            )
    ship_parent = archive_milestone.require_git_success(
        run_git(project, "rev-parse", f"{ship_commit}^"),
        "resolve the reviewed pre-ship commit",
    )
    current_branch = archive_milestone.require_git_success(
        run_git(project, "branch", "--show-current"), "resolve current branch"
    )
    if current_branch != branch:
        raise ArchiveError(
            f"abandon-integration requires the bound branch {branch} checked out"
        )
    head = archive_milestone.require_git_success(
        run_git(project, "rev-parse", "HEAD"), "resolve HEAD"
    )
    # A fresh entry starts at the ship commit. Whether a resumed entry may sit
    # on the reviewed parent is decided below, once this transaction's remote
    # progress is observable — never before.
    if journal is None and head != ship_commit:
        raise ArchiveError(
            "bound worktree must remain at the ship commit during integration"
        )

    remote_default = refresh_origin(project)["remote_default"]
    if default_branch_name(remote_default) != state.default_branch:
        raise ArchiveError(
            f"remote default must be {state.default_branch}, got "
            f"{default_branch_name(remote_default)!r}"
        )
    require_github_authentication()
    repository = github_repository(project)
    pull = require_open_unmerged_pull(
        repository, branch, ship_commit, state.default_branch, journal
    )
    tag_ref = f"refs/tags/milestone/{archive_name}"
    published = live_remote_refs(project, [bound_ref, tag_ref])
    if published[tag_ref] is not None:
        raise ArchiveError(
            f"milestone tag {tag_ref} already exists on origin; "
            "a tagged milestone is integrated and cannot be abandoned"
        )
    if published[bound_ref] is None:
        if journal is None:
            raise ArchiveError(f"origin/{branch} is absent; nothing published to abandon")
        if pull["state"] == "open":
            # This transaction deletes the published ref only after closing
            # the pull request, so an open pull over a deleted ref is not a
            # checkpoint it can have produced; something else removed the ref.
            raise ArchiveError(
                f"origin/{branch} is absent while the pull request is still "
                "open; this rollback deletes the ref only after closing the "
                "pull request, so the deletion is not ours — investigate "
                "before resuming"
            )
    elif published[bound_ref] != ship_commit:
        raise ArchiveError(
            f"origin/{branch} is not at the ship commit: {published[bound_ref]}"
        )
    merged = run_git(
        project, "merge-base", "--is-ancestor", ship_commit, remote_default
    )
    if merged.returncode == 0:
        raise ArchiveError(
            "the ship commit is already on the remote default branch; "
            "an integrated milestone cannot be abandoned"
        )
    if merged.returncode != 1:
        archive_milestone.require_git_success(
            merged, "inspect ship ancestry on the remote default"
        )

    if journal is not None:
        # The reviewed parent is acceptable only when THIS transaction's remote
        # steps already ran: it closed the pull request (the journal adopted
        # the closed PR) and deleted the published ref. A manual rewind before
        # them must restore the ship commit; the rollback never reached its
        # rewind step, so the remote must not be touched from that state.
        remote_steps_done = pull["state"] != "open" and published[bound_ref] is None
        if head == ship_parent and not remote_steps_done:
            raise ArchiveError(
                "the bound branch sits on the reviewed parent before this "
                "transaction closed the pull request and deleted the published "
                "ref; restore the ship commit before resuming"
            )
        if head not in {ship_commit, ship_parent}:
            raise ArchiveError(
                "bound branch HEAD is neither the ship commit nor its reviewed parent"
            )

    if journal is None:
        journal = {
            "schema": ABANDON_INTEGRATION_SCHEMA,
            "repo": str(project),
            "slug": slug,
            "finding": finding,
            "ship_commit": ship_commit,
            "bound_ref": bound_ref,
            "pr_number": pull["number"],
            "expected_head": ship_commit,
            "abandoned_on": date.today().isoformat(),
        }
        write_abandon_integration_journal(journal_path, journal)

    # --- Journaled mutations; every step is idempotent across a rerun.
    if pull["state"] == "open":
        close_pull_request(repository, pull)

    if published[bound_ref] is not None:
        # Delete under the exact lease just observed; a racing push that moves
        # the ref fails the lease and aborts with no further mutation.
        archive_milestone.require_git_success(
            run_git(
                project,
                "push",
                f"--force-with-lease={bound_ref}:{published[bound_ref]}",
                "origin",
                "--delete",
                bound_ref,
            ),
            "delete the published bound branch under its observed lease",
        )
        if live_remote_refs(project, [bound_ref])[bound_ref] is not None:
            raise ArchiveError(f"origin/{branch} still exists after deletion")
    tracking_ref = f"refs/remotes/origin/{branch}"
    if optional_ref(project, tracking_ref) is not None:
        archive_milestone.require_git_success(
            run_git(project, "update-ref", "-d", tracking_ref),
            "remove the local bound tracking ref",
        )

    head = archive_milestone.require_git_success(
        run_git(project, "rev-parse", "HEAD"), "resolve HEAD"
    )
    if head == ship_commit:
        # A mixed reset leaves the restored tree as working-tree-only changes;
        # the patch-plan checkpoint then stages exactly what it validates.
        archive_milestone.require_git_success(
            run_git(project, "reset", "--mixed", ship_parent),
            "rewind the bound branch to the reviewed commit",
        )
    elif head != ship_parent:
        raise ArchiveError(
            "bound branch HEAD is neither the ship commit nor its reviewed parent"
        )

    if archive.exists() or archive.is_symlink():
        restore_abandoned_archive(project, active_root, archive)
    restore_abandoned_roadmap(active_root, slug, configured)

    return {
        "slug": slug,
        "finding": finding,
        "ship_commit": ship_commit,
        "bound_ref": bound_ref,
        "configured": configured,
        "pr_url": pull["html_url"],
    }


def abandon_integration_finalize(
    project: Path,
    active_root: Path,
    slug: str,
    finding: str,
    journal_path: Path,
    context: Mapping[str, str],
) -> dict:
    branch = context["bound_ref"].removeprefix("refs/heads/")
    state, _, _ = archive_milestone.strict_state(project)
    if (state.phase, state.status) == ("shipped", "done"):
        if state.archive != context["configured"]:
            raise ArchiveError("STATE.archive differs from the abandoned integration")
        transition_state(
            project,
            expected={
                "phase": "shipped",
                "status": "done",
                "milestone": slug,
                "branch": branch,
                "archive": context["configured"],
            },
            changes={"phase": "ship", "status": "blocked", "archive": None},
            event="published integration abandoned",
        )
    elif (state.phase, state.status, state.archive) != ("ship", "blocked", None):
        raise ArchiveError(
            "abandon-integration transaction has an invalid finalized STATE.md"
        )

    write_abandon_integration_findings(active_root, finding)
    journal_path.unlink()
    return {
        "status": "abandoned",
        "pr_closed": context["pr_url"],
        "bound_deleted": True,
        "state": "ship/blocked",
        "finding_recorded": True,
    }


def find_integrate_commit(
    project: Path,
    remote_default: str,
    archive_name: str,
    ship_commit: str,
) -> str:
    default_name = default_branch_name(remote_default)
    expected_subject = integrate_subject(archive_name, default_name)
    log = archive_milestone.require_git_success(
        run_git(project, "log", "--first-parent", "--format=%H%x00%s", remote_default),
        f"inspect {remote_default} first-parent history for the integration merge",
    )
    matches = []
    for record in log.splitlines():
        if "\x00" not in record:
            continue
        commit, subject = record.split("\x00", 1)
        if subject == expected_subject:
            matches.append(commit)
    if not matches:
        raise ArchiveError(
            f"no commit with exact subject {expected_subject!r} "
            f"in {remote_default} first-parent history"
        )
    if len(matches) != 1:
        raise ArchiveError(
            f"multiple commits with exact subject {expected_subject!r} "
            f"in {remote_default} first-parent history"
        )
    merge_commit = matches[0]
    parents = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", merge_commit),
        "inspect integration merge parents",
    ).split()
    if len(parents) != 3:
        raise ArchiveError(f"integration commit for {archive_name} is not a merge commit")
    if parents[2] != ship_commit:
        raise ArchiveError("integration merge second parent is not the ship commit")
    return merge_commit


def validate_integrated(
    repo: Path, slug: str, *, refresh: bool = True, historical: bool = False
) -> dict:
    project = repo.resolve()
    active_root = archive_milestone.require_project_layout(project)
    state, _, loaded_state_path = archive_milestone.strict_state(project)
    if loaded_state_path.resolve() != (active_root / "STATE.md").resolve():
        raise ArchiveError("strict STATE.md loader returned an unexpected path")
    expected_slug = archive_milestone.milestone_slug(state)
    if archive_milestone.normalized_slug(slug) != expected_slug:
        raise ArchiveError(
            f"--slug {slug!r} does not match normalized STATE.milestone {expected_slug!r}"
        )

    # (a) The shipped transaction itself must still validate.
    shipped = archive_milestone.validate(repo, historical=historical)
    configured = shipped["archive"]
    ship_commit = shipped["commit"]
    archive_name = PurePosixPath(configured).name

    # Refresh whenever origin exists so direct mode cannot miss a published tag.
    # Fixtures that only plant refs/remotes/origin/* keep resolve_remote_default.
    has_origin = run_git(project, "remote", "get-url", "origin").returncode == 0
    if has_origin and refresh:
        remote_default = refresh_origin(project)["remote_default"]
    else:
        remote_default = resolve_remote_default(project)
    default_name = default_branch_name(remote_default)
    bound_branch = state.branch
    if bound_branch is None:
        raise ArchiveError("STATE.md does not name a bound build branch")
    expected_branch = bound_branch_name(milestone_number(archive_name))
    ship_subject_text = archive_milestone.require_git_success(
        run_git(project, "log", "-1", "--format=%s", ship_commit),
        "read ship commit subject",
    )
    if ship_subject_text != ship_subject(archive_name):
        raise ArchiveError("current milestone ship commit subject is not canonical")
    if not is_bound_branch(bound_branch):
        raise ArchiveError(f"bound branch {bound_branch!r} is not gsd-path/M00N")
    if is_bound_branch(bound_branch) and bound_branch != expected_branch:
        expected_milestone = expected_branch.removeprefix("gsd-path/")
        raise ArchiveError(
            f"bound branch {bound_branch} does not match archive milestone {expected_milestone}"
        )
    if bound_branch == default_name:
        raise ArchiveError(
            f"bound branch {bound_branch!r} is the remote default; "
            "ship merges onto the default branch, never onto the work branch"
        )
    if default_name != state.default_branch:
        raise ArchiveError(
            f"remote default must be {state.default_branch}, got {default_name!r}"
        )

    # (b) Resolve the integration proof selected before build.
    tag_name = f"milestone/{archive_name}"
    tag_ref = f"refs/tags/{tag_name}"
    pull_request = None
    if state.integration == "pull-request":
        if run_git(project, "rev-parse", "--verify", "--quiet", tag_ref).returncode != 0:
            raise ArchiveError(f"missing milestone tag: {tag_name}")
        metadata = pull_request_tag_metadata(project, tag_ref)
        # A rebase merge rewrites the ship commits, so historical validation
        # over landed history finds the tag's Landing where the bound branch
        # found its Ship (#450); archive validate proved the mapping.
        if metadata["Ship"] != ship_commit and not (
            shipped.get("rebased_ship") == metadata["Ship"]
            and metadata["Landing"] == ship_commit
        ):
            raise ArchiveError("pull-request milestone tag names the wrong ship commit")
        merge_commit = metadata["Landing"]
        pull_request = metadata["Pull-Request"]
        require_github_authentication()
        repository = github_repository(project)
        # The PR head is the original ship commit, which the tag names; a
        # rebase-merged landing rewrites it on the default branch (#450).
        pull = find_pull_request(repository, bound_branch, metadata["Ship"], default_name)
        if pull is None:
            raise ArchiveError("GitHub pull request for the ship commit is missing")
        if pull["html_url"] != pull_request:
            raise ArchiveError("milestone tag names the wrong pull request")
        if (
            pull["state"] != "closed"
            or pull["merged_at"] is None
            or pull["merge_commit_sha"] != merge_commit
        ):
            raise ArchiveError("GitHub pull request is not merged at the tagged landing")
        require_pull_request_merge_provenance(
            repository,
            pull["number"],
            merge_commit,
        )
        # Prove the pair the tag names: the original ship commit, whose objects
        # archive validation already required to resolve (#450).
        require_pull_request_merge(
            project,
            merge_commit,
            metadata["Ship"],
            remote_default,
            allow_rebase=True,
        )
        require_annotated_tag(
            project,
            tag_ref,
            merge_commit,
            f"milestone tag {tag_name}",
            pull_request_tag_message(
                archive_name,
                pull_request,
                metadata["Ship"],
                merge_commit,
            ),
        )
    elif state.integration == "external-landing":
        merge_commit = find_integrate_commit(
            project, remote_default, archive_name, ship_commit
        )
        archive_milestone.require_canonical_commit_body(
            project,
            merge_commit,
            integrate_subject(archive_name, default_name),
            integrate_commit_body(configured, ship_commit, default_name, bound_branch),
            "integration",
        )
        require_pull_request_merge(project, merge_commit, ship_commit, remote_default)
        if run_git(project, "rev-parse", "--verify", "--quiet", tag_ref).returncode != 0:
            raise ArchiveError(f"missing milestone tag: {tag_name}")
        metadata = external_landing_tag_metadata(project, tag_ref)
        if metadata["Ship"] != ship_commit:
            raise ArchiveError("external-landing milestone tag names the wrong ship commit")
        if metadata["Landing"] != merge_commit:
            raise ArchiveError("external-landing milestone tag names the wrong landing")
        require_annotated_tag(
            project,
            tag_ref,
            merge_commit,
            f"milestone tag {tag_name}",
            external_landing_tag_message(archive_name, ship_commit, merge_commit),
        )
    else:
        merge_commit = find_integrate_commit(
            project, remote_default, archive_name, ship_commit
        )
        archive_milestone.require_canonical_commit_body(
            project,
            merge_commit,
            integrate_subject(archive_name, default_name),
            integrate_commit_body(configured, ship_commit, default_name, bound_branch),
            "integration",
        )
        if run_git(project, "rev-parse", "--verify", "--quiet", tag_ref).returncode != 0:
            raise ArchiveError(f"missing milestone tag: {tag_name}")
        require_annotated_tag(
            project,
            tag_ref,
            merge_commit,
            f"milestone tag {tag_name}",
        )

    # (c) The remote default must contain the merge commit.
    contains = run_git(project, "merge-base", "--is-ancestor", merge_commit, remote_default)
    if contains.returncode != 0:
        raise ArchiveError(f"{remote_default} does not contain the integration merge")
    if (historical
            and run_git(project, "branch", "--show-current").stdout.strip() != bound_branch
            and run_git(project, "merge-base", "--is-ancestor", merge_commit, "HEAD").returncode):
        raise ArchiveError("HEAD does not contain the integration merge")

    # (e) The bound branch tip and annotated tag must be published on origin.
    # One batched ls-remote answers every live read below; six serial round
    # trips pushed status past the daemon's budget (#558). The bound ref is
    # always in the set: require_published_integration reads it in the
    # allow_missing_bound modes, not only direct integration.
    prefetch_refs = [
        f"refs/heads/{default_name}",
        f"refs/tags/{tag_name}",
        f"refs/heads/{bound_branch}",
    ]
    remote_refs = live_remote_refs(project, prefetch_refs) if has_origin else None
    require_published_integration(
        project,
        bound_branch,
        ship_commit,
        tag_name,
        merge_commit,
        tag_ship=shipped.get("rebased_ship"),
        allow_missing_bound=state.integration in ("pull-request", "external-landing")
        or (historical and has_origin),
        retired=historical,
        remote_refs=remote_refs,
    )

    result = {
        "archive": configured,
        "commit": ship_commit,
        "integrate": merge_commit,
        "landing": merge_commit,
        "base": archive_milestone.require_git_success(
            run_git(project, "rev-parse", remote_default),
            "resolve integrated remote default",
        ),
        "mode": state.integration,
        "tag": tag_name,
    }
    if has_origin and not refresh:
        # Status must not fetch or write refs. Missing/stale local evidence is
        # unverified; the normal ship validator remains the refresh owner.
        refs = [(f"refs/heads/{default_name}", result["base"]),
                (f"refs/tags/{tag_name}", optional_ref(project, tag_ref))]
        if state.integration == "direct":
            bound_ref = f"refs/heads/{bound_branch}"
            if not historical or remote_refs[bound_ref] is not None:
                refs.append((bound_ref, ship_commit))
        for ref, expected in refs:
            if remote_refs[ref] != expected:
                raise ArchiveError(f"published {ref} differs from local integration evidence")
    if pull_request is not None:
        result["pull_request"] = pull_request
    for row in shipped.get("members", []):
        proven = validate_member_integrated(project, row["name"], configured, row["reviewed_head"], refresh=refresh)
        if (proven["merge"], proven["tag"]) != (row["merge"], row["tag"]):
            raise ArchiveError(f"member {row['name']} integration differs from the ship commit")
    if "members" in shipped:
        result["members"] = shipped["members"]
    return result


def require_published_integration(
    project: Path,
    bound_branch: str,
    ship_commit: str,
    tag_name: str,
    merge_commit: str,
    allow_missing_bound: bool = False,
    retired: bool = False,
    tag_ship: Optional[str] = None,
    remote_refs: Optional[dict] = None,
) -> None:
    if allow_missing_bound:
        bound_ref_name = f"refs/heads/{bound_branch}"
        published_ship = (
            remote_refs[bound_ref_name] if remote_refs is not None
            else live_remote_ref(project, bound_ref_name)
        )
        # A surviving bound branch stays at the original ship commit, which a
        # rebase merge rewrote into the landing validated here (#450).
        expected_ships = {ship_commit} | ({tag_ship} if tag_ship else set())
        if published_ship is not None and published_ship not in expected_ships:
            raise ArchiveError(
                f"origin/{bound_branch} is {published_ship}, expected ship commit {ship_commit}"
            )
        tag_ref_name = f"refs/tags/{tag_name}"
        published_tag = (
            remote_refs[tag_ref_name] if remote_refs is not None
            else live_remote_ref(project, tag_ref_name)
        )
        if published_tag is None:
            raise ArchiveError(f"missing published milestone tag: origin/tags/{tag_name}")
        local_tag = optional_ref(project, f"refs/tags/{tag_name}")
        if local_tag != published_tag:
            raise ArchiveError(f"local and published milestone tag {tag_name} differ")
        require_annotated_tag(
            project,
            published_tag,
            merge_commit,
            f"published milestone tag {tag_name}",
        )
        return

    bound_ref = f"refs/remotes/origin/{bound_branch}"
    if run_git(project, "rev-parse", "--verify", "--quiet", bound_ref).returncode != 0:
        if not retired:
            raise ArchiveError(f"missing published bound branch: origin/{bound_branch}")
    else:
        published_ship = archive_milestone.require_git_success(
            run_git(project, "rev-parse", bound_ref),
            "resolve published bound branch",
        )
        if published_ship != ship_commit:
            raise ArchiveError(
                f"origin/{bound_branch} is {published_ship}, expected ship commit {ship_commit}"
            )

    remote_tag = f"refs/remotes/origin/tags/{tag_name}"
    if run_git(project, "rev-parse", "--verify", "--quiet", remote_tag).returncode != 0:
        raise ArchiveError(f"missing published milestone tag: origin/tags/{tag_name}")
    remote_tag_type = archive_milestone.require_git_success(
        run_git(project, "cat-file", "-t", remote_tag),
        "inspect published milestone tag type",
    )
    if remote_tag_type != "tag":
        raise ArchiveError(f"published milestone tag {tag_name} must be annotated")
    remote_tag_target = archive_milestone.require_git_success(
        run_git(project, "rev-parse", f"{remote_tag}^{{commit}}"),
        "resolve published milestone tag target",
    )
    if remote_tag_target != merge_commit:
        raise ArchiveError(
            f"published milestone tag {tag_name} does not point at the integration merge"
        )


def _member_names(coordinator: Path, member: str, archive_path: str) -> tuple[Path, str, str, str, str, str]:
    """A member's checkout, coordinator project, bound branch, merge subject, tag,
    and the default branch that MEMBERS.md records for it."""
    try:
        import isolation
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import isolation
    try:
        checkout, project = isolation.member_checkout(coordinator.resolve(), member)
        default = isolation.member_default_branch(coordinator.resolve(), member)
    except isolation.IsolationError as error:
        raise ArchiveError(str(error)) from error
    archive_name = PurePosixPath(archive_path).name
    identifier = milestone_id(milestone_number(archive_name))
    bound = f"gsd-path/{project}-{identifier}"
    subject = f"integrate: {project} {identifier} — merge {bound} into {default}"
    return checkout, project, bound, subject, f"milestone/{project}-{archive_name}", default


def _member_merge_body(archive_path: str, member: str, reviewed_head: str) -> str:
    return f"Archive: {archive_path}\nMember: {member}\nReviewed-HEAD: {reviewed_head}"


def member_pull_request_tag_message(tag_name: str, pull_request: str, reviewed_head: str, landing: str) -> str:
    return (f"milestone {tag_name.removeprefix('milestone/')}\n\nMode: pull-request\n"
            f"Pull-Request: {pull_request}\nReviewed-HEAD: {reviewed_head}\nLanding: {landing}")


def member_adopted_tag_message(tag_name: str, reviewed_head: str, landing: str) -> str:
    return (f"milestone {tag_name.removeprefix('milestone/')}\n\nMode: adopted-landing\n"
            f"Reviewed-HEAD: {reviewed_head}\nLanding: {landing}\n\n"
            "The reviewed HEAD reached the member default branch through earlier user-approved "
            "publications; Path made no merge.")


def member_adopted_tag_metadata(contents: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"(Mode|Reviewed-HEAD|Landing): (.+)", line)
        if match:
            if match.group(1) in fields:
                raise ArchiveError("adopted-landing member tag repeats metadata")
            fields[match.group(1)] = match.group(2)
    if set(fields) != {"Mode", "Reviewed-HEAD", "Landing"}:
        raise ArchiveError("adopted-landing member tag is missing metadata")
    if fields["Mode"] != "adopted-landing":
        raise ArchiveError("adopted-landing member tag has the wrong mode")
    return fields


def member_pull_request_tag_metadata(contents: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in contents.splitlines():
        match = re.fullmatch(r"(Mode|Pull-Request|Reviewed-HEAD|Landing): (.+)", line)
        if match:
            if match.group(1) in fields:
                raise ArchiveError("pull-request member tag repeats metadata")
            fields[match.group(1)] = match.group(2)
    if set(fields) != {"Mode", "Pull-Request", "Reviewed-HEAD", "Landing"}:
        raise ArchiveError("pull-request member tag is missing metadata")
    if fields["Mode"] != "pull-request":
        raise ArchiveError("pull-request member tag has the wrong mode")
    return fields


def _find_member_merge(checkout: Path, subject: str, body: str, reviewed_head: str, default: str) -> Optional[str]:
    """The member merge in the first-parent history of origin/<default>, if published."""
    log = archive_milestone.require_git_success(
        run_git(checkout, "log", "--first-parent", "--format=%H%x00%s", f"origin/{default}"),
        f"inspect member origin/{default} first-parent history",
    )
    matches = [commit for commit, _, text in (line.partition("\x00") for line in log.splitlines())
               if text == subject]
    if len(matches) > 1:
        raise ArchiveError(f"multiple member merges named {subject!r} on origin/{default}")
    if not matches:
        return None
    _require_member_merge(checkout, matches[0], subject, body, reviewed_head)
    return matches[0]


def _require_member_merge(checkout: Path, commit: str, subject: str, body: str, reviewed_head: str) -> str:
    """Check a canonical member merge; return its first parent."""
    archive_milestone.require_canonical_commit_body(checkout, commit, subject, body, "member integration")
    parents = archive_milestone.require_git_success(
        run_git(checkout, "rev-list", "--parents", "-n", "1", commit), "inspect member merge parents"
    ).split()
    if len(parents) != 3 or parents[2] != reviewed_head:
        raise ArchiveError("member merge second parent is not the member reviewed HEAD")
    return parents[1]


def _create_member_merge(checkout: Path, project: str, archive_path: str, subject: str, body: str,
                         reviewed_head: str, origin_main: str) -> str:
    identifier = milestone_id(milestone_number(PurePosixPath(archive_path).name))
    branch = f"gsd-path-integrate/{project}-{identifier}"
    try:
        worktree = worktree_paths.worktree_path(checkout, "integrate", f"{project}-{identifier}", pin=True)
    except (ValueError, OSError) as error:
        raise ArchiveError(str(error)) from error
    interrupted = registered_worktree(checkout, branch)
    if interrupted is not None and optional_ref(interrupted, "MERGE_HEAD") is not None:
        archive_milestone.require_git_success(run_git(interrupted, "merge", "--abort"),
                                              "abort interrupted member merge")
    remove_registered_worktree(checkout, branch, worktree)
    tip = optional_ref(checkout, f"refs/heads/{branch}")
    if tip is not None:
        base_tip = run_git(checkout, "merge-base", "--is-ancestor", tip, origin_main)
        if base_tip.returncode != 0:
            if base_tip.returncode != 1:
                archive_milestone.require_git_success(base_tip, "inspect interrupted member integration base")
            if _require_member_merge(checkout, tip, subject, body, reviewed_head) == origin_main:
                return tip
        delete_integration_branch(checkout, branch, tip)
    archive_milestone.require_git_success(
        run_git(checkout, "worktree", "add", "--quiet", "-b", branch, str(worktree), origin_main),
        "create member integration worktree",
    )
    merged = run_git(worktree, "merge", "--no-ff", "-m", subject, "-m", body, reviewed_head)
    if merged.returncode != 0:
        conflicts = run_git(worktree, "diff", "--name-only", "--diff-filter=U").stdout.split()
        if optional_ref(worktree, "MERGE_HEAD") is not None:
            run_git(worktree, "merge", "--abort")
        remove_registered_worktree(checkout, branch, worktree)
        delete_integration_branch(checkout, branch, origin_main)
        raise ArchiveError("member integration merge failed; Git aborted it without resolving files: "
                           + (", ".join(conflicts) or (merged.stderr or merged.stdout).strip()))
    merge = archive_milestone.require_git_success(run_git(worktree, "rev-parse", "HEAD"), "resolve member merge")
    if _require_member_merge(worktree, merge, subject, body, reviewed_head) != origin_main:
        raise ArchiveError("member merge first parent is not the origin default branch")
    remove_registered_worktree(checkout, branch, worktree)
    return merge


def _push_member_ref(checkout: Path, project: str, source: str, ref: str, sha: str, lease: Optional[str]) -> None:
    """Authorize `ref` at `sha` for the member pre-push hook, then publish it."""
    try:
        import members
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import members
    members.authorize_push(checkout, project, ref, sha)
    arguments = ["push"] + ([f"--force-with-lease={ref}:{lease}"] if lease is not None else [])
    archive_milestone.require_git_success(
        run_git(checkout, *arguments, "origin", f"{source}:{ref}"), f"publish member {ref}"
    )


def _publish_member_bound(checkout: Path, project: str, member: str, bound: str, reviewed_head: str) -> None:
    bound_ref = f"refs/heads/{bound}"
    remote_bound = live_remote_ref(checkout, bound_ref)
    if remote_bound is None:
        _push_member_ref(checkout, project, reviewed_head, bound_ref, reviewed_head, "")
    elif remote_bound != reviewed_head:
        raise ArchiveError(f"member {member} origin/{bound} moved: {remote_bound}")


def _require_member_close(checkout: Path, member: str, bound: str, reviewed_head: str, default: str) -> None:
    if optional_ref(checkout, f"refs/heads/{bound}") != reviewed_head:
        raise ArchiveError(f"member {member} {bound} is not at its reviewed HEAD {reviewed_head}")
    live = default_branch_name(refresh_origin(checkout)["remote_default"])
    if live != default:
        raise ArchiveError(f"member {member} remote default must be {default}, got {live!r}")


def integrate_member(coordinator: Path, member: str, archive_path: str, reviewed_head: str,
                     adopt: Optional[str] = None) -> dict:
    """Direct-mode member close: publish the bound branch, merge it into the member
    default branch, then tag."""
    checkout, project, bound, subject, tag_name, default = _member_names(coordinator, member, archive_path)
    origin_default = f"origin/{default}"
    body = _member_merge_body(archive_path, member, reviewed_head)
    _require_member_close(checkout, member, bound, reviewed_head, default)
    merge = _find_member_merge(checkout, subject, body, reviewed_head, default)
    adopted = False
    if merge is None:
        origin_main = archive_milestone.require_git_success(
            run_git(checkout, "rev-parse", origin_default), f"resolve member {origin_default}")
        ancestry = run_git(checkout, "merge-base", "--is-ancestor", reviewed_head, origin_main)
        if ancestry.returncode == 0:
            if live_remote_ref(checkout, f"refs/tags/{tag_name}") is not None:
                return validate_member_integrated(coordinator, member, archive_path, reviewed_head)
            if adopt is None:
                raise ArchiveError(
                    f"member reviewed HEAD reached {origin_default} outside Path; user-approved recovery "
                    f"required: rerun close-members with --adopt-landed-member {member}={origin_main}")
            if adopt != origin_main:
                raise ArchiveError(
                    f"member {member} --adopt-landed-member names {adopt}, "
                    f"but {origin_default} is {origin_main}")
            merge = origin_main
            adopted = True
        elif ancestry.returncode != 1:
            archive_milestone.require_git_success(ancestry, "inspect member reviewed HEAD ancestry")
        elif adopt is not None:
            raise ArchiveError(
                f"member {member} --adopt-landed-member was given, but its reviewed HEAD "
                f"has not reached {origin_default}")
        if merge is None:
            merge = _create_member_merge(checkout, project, archive_path, subject, body, reviewed_head, origin_main)
    # Publish in order: bound branch, default branch, tag; a rerun publishes only what is missing.
    _publish_member_bound(checkout, project, member, bound, reviewed_head)
    if run_git(checkout, "merge-base", "--is-ancestor", merge, origin_default).returncode != 0:
        _push_member_ref(checkout, project, merge, f"refs/heads/{default}", merge, None)
        archive_milestone.require_git_success(
            run_git(checkout, "update-ref", f"refs/remotes/{origin_default}", merge),
            f"refresh member {origin_default}")
    tag_message = (
        member_adopted_tag_message(tag_name, reviewed_head, merge) if adopted else None
    )
    tag_object, tag_published = ensure_integration_tag(checkout, tag_name, merge, tag_message)
    if not tag_published:
        _push_member_ref(checkout, project, f"refs/tags/{tag_name}", f"refs/tags/{tag_name}", tag_object, None)
        archive_milestone.require_git_success(
            run_git(checkout, "update-ref", f"refs/remotes/origin/tags/{tag_name}", tag_object),
            "refresh member milestone-tag ref")
    identifier = milestone_id(milestone_number(PurePosixPath(archive_path).name))
    delete_integration_branch(checkout, f"gsd-path-integrate/{project}-{identifier}", merge)
    return validate_member_integrated(coordinator, member, archive_path, reviewed_head)


def integrate_member_pull_request(coordinator: Path, member: str, archive_path: str, reviewed_head: str) -> dict:
    """Pull-request member close: open one PR for the bound branch; after a human merge, tag it."""
    checkout, project, bound, subject, tag_name, default = _member_names(coordinator, member, archive_path)
    body = _member_merge_body(archive_path, member, reviewed_head)
    _require_member_close(checkout, member, bound, reviewed_head, default)
    require_github_authentication()
    repository = github_repository(checkout)
    pull = find_pull_request(repository, bound, reviewed_head, default)
    if pull is None or pull["merged_at"] is None:
        if pull is not None and pull["state"] != "open":
            raise ArchiveError(f"member {member} pull request was closed without merging")
        _publish_member_bound(checkout, project, member, bound, reviewed_head)
        if pull is None:
            pull = require_pull_request_shape(github_api_json(
                f"repos/{repository}/pulls", "--method", "POST", "-f", f"title={subject}",
                "-f", f"head={bound}", "-f", f"base={default}", "-f", f"body={body}\n\n---\n{PR_CREDIT_LINE}"))
            require_pull_request_identity(repository, pull, bound, reviewed_head, default)
        else:
            pull = update_pull_request_body(
                repository, pull, archive_path, reviewed_head, bound,
                f"{body}\n\n---\n{PR_CREDIT_LINE}", default,
            )
        require_pull_request_merge_provenance(repository, pull["number"])
        return {"status": "awaiting-merge", "mode": "pull-request", "member": member,
                "pull_request": pull["html_url"]}
    merge = pull["merge_commit_sha"]
    if pull["state"] != "closed" or not isinstance(merge, str):
        raise ArchiveError(f"member {member} pull request merge metadata is invalid")
    require_pull_request_merge_provenance(repository, pull["number"], merge)
    refresh_origin(checkout)
    require_pull_request_merge(checkout, merge, reviewed_head, f"origin/{default}")
    pull = update_pull_request_body(
        repository, pull, archive_path, reviewed_head, bound,
        f"{body}\n\n---\n{PR_CREDIT_LINE}", default,
    )
    message = member_pull_request_tag_message(tag_name, pull["html_url"], reviewed_head, merge)
    tag_object, tag_published = ensure_integration_tag(checkout, tag_name, merge, message)
    if not tag_published:
        _push_member_ref(checkout, project, f"refs/tags/{tag_name}", f"refs/tags/{tag_name}", tag_object, None)
        archive_milestone.require_git_success(
            run_git(checkout, "update-ref", f"refs/remotes/origin/tags/{tag_name}", tag_object),
            "refresh member milestone-tag ref")
    return validate_member_integrated(coordinator, member, archive_path, reviewed_head)


def validate_member_integrated(
    coordinator: Path, member: str, archive_path: str, reviewed_head: str, *, refresh: bool = True
) -> dict:
    """Prove the member merge is on the member default branch and its published tag points at it."""
    checkout, _, bound, subject, tag_name, default = _member_names(coordinator, member, archive_path)
    tracking = f"refs/remotes/origin/tags/{tag_name}"
    if refresh:
        refresh_origin(checkout)
        published = live_remote_ref(checkout, f"refs/tags/{tag_name}")
    else:
        published = optional_ref(checkout, tracking)
    contents = ""
    if refresh and published is not None:
        archive_milestone.require_git_success(
            run_git(checkout, "update-ref", tracking, published), "refresh member milestone-tag ref")
    if published is not None:
        contents = run_git(checkout, "for-each-ref", "--format=%(contents)", tracking).stdout
    if "Mode: adopted-landing" in contents.splitlines():
        # A user-approved adoption: the reviewed HEAD reached the member default
        # branch through earlier publications, so the tag proves the landing in
        # place of the canonical merge Path never made (#458). Only a
        # direct-mode member may carry one; a pull-request member validates
        # through its merged PR instead.
        try:
            import members as members_module
        except ImportError:  # pragma: no cover - package import used by tests
            from scripts import members as members_module
        common = Path(archive_milestone.require_git_success(
            run_git(coordinator, "rev-parse", "--path-format=absolute", "--git-common-dir"),
            "resolve Git common dir"))
        try:
            closed_modes = {
                row["name"]: row["mode"]
                for row in members_module.read_member_close(common, PurePosixPath(archive_path).name)
            }
            effective_mode = closed_modes.get(member) or {
                item["name"]: item["integration"]
                for item in members_module.read_members(coordinator)
            }.get(member, "default")
        except members_module.MembersError as error:
            raise ArchiveError(str(error)) from error
        if effective_mode == "default":
            effective_mode = archive_milestone.strict_state(coordinator)[0].integration
        if effective_mode != "direct":
            raise ArchiveError(
                f"member {member} is not direct-mode; an adopted-landing tag cannot close it")
        metadata = member_adopted_tag_metadata(contents)
        if metadata["Reviewed-HEAD"] != reviewed_head:
            raise ArchiveError(f"member {member} tag {tag_name} names a different reviewed HEAD")
        merge = archive_milestone.require_git_success(
            run_git(checkout, "rev-parse", f"{tracking}^{{commit}}"), "resolve member tag target")
        if metadata["Landing"] != merge:
            raise ArchiveError(f"member {member} tag {tag_name} names a different landing")
        require_annotated_tag(
            checkout, tracking, merge, f"member tag {tag_name}",
            member_adopted_tag_message(tag_name, reviewed_head, merge),
        )
        origin_default_ref = f"origin/{default}"
        for earlier, later in ((reviewed_head, merge), (merge, origin_default_ref)):
            if run_git(checkout, "merge-base", "--is-ancestor", earlier, later).returncode != 0:
                raise ArchiveError(
                    f"member {member} adopted landing {merge} does not follow the reviewed HEAD "
                    f"on {origin_default_ref}")
        return {"member": member, "merge": merge, "tag": tag_name, "tag_object": published,
                "adopted": True}
    if "Mode: pull-request" in contents.splitlines():
        metadata = member_pull_request_tag_metadata(contents)
        if metadata["Reviewed-HEAD"] != reviewed_head:
            raise ArchiveError(f"member {member} tag {tag_name} names a different reviewed HEAD")
        merge = archive_milestone.require_git_success(
            run_git(checkout, "rev-parse", f"{tracking}^{{commit}}"), "resolve member tag target")
        if metadata["Landing"] != merge:
            raise ArchiveError(f"member {member} tag {tag_name} names a different landing")
        require_github_authentication()
        repository = github_repository(checkout)
        pull = find_pull_request(repository, bound, reviewed_head, default)
        if pull is None:
            raise ArchiveError(f"member {member} GitHub pull request is missing")
        if pull["html_url"] != metadata["Pull-Request"]:
            raise ArchiveError(f"member {member} tag {tag_name} names the wrong pull request")
        if (pull["state"] != "closed" or pull["merged_at"] is None
                or pull["merge_commit_sha"] != merge):
            raise ArchiveError(f"member {member} GitHub pull request is not merged at the tagged landing")
        require_pull_request_merge_provenance(repository, pull["number"], merge)
        require_pull_request_merge(checkout, merge, reviewed_head, f"origin/{default}")
        require_annotated_tag(
            checkout, tracking, merge, f"member tag {tag_name}",
            member_pull_request_tag_message(tag_name, pull["html_url"], reviewed_head, merge),
        )
    else:
        merge = _find_member_merge(checkout, subject, _member_merge_body(archive_path, member, reviewed_head),
                                   reviewed_head, default)
        if merge is None:
            raise ArchiveError(f"member {member} has no {subject!r} merge on origin/{default}")
        if published is None:
            raise ArchiveError(f"member {member} tag {tag_name} is not published")
        require_annotated_tag(checkout, tracking, merge, f"member tag {tag_name}")
    return {"member": member, "merge": merge, "tag": tag_name, "tag_object": published}


def retire_member(coordinator: Path, member: str, archive_path: str, reviewed_head: str,
                  merge: str, tag: str) -> dict:
    """After integration, delete a member's bound branch everywhere and clear its authorizations."""
    try:
        import members
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import members
    try:
        import isolation
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import isolation
    checkout, project, bound, _, tag_name, default = _member_names(coordinator, member, archive_path)
    proven = validate_member_integrated(coordinator, member, archive_path, reviewed_head)
    if (proven["merge"], proven["tag"]) != (merge, tag):
        raise ArchiveError(f"member {member} integration differs from the ship commit")
    bound_ref = f"refs/heads/{bound}"
    local = optional_ref(checkout, bound_ref)
    if local is not None and local != reviewed_head:
        raise ArchiveError(f"member {member} {bound} moved: {local}")
    holder = registered_worktree(checkout, bound)
    if holder is not None:
        try:
            expected = worktree_paths.worktree_path(
                checkout, "bound", bound.removeprefix("gsd-path/")
            ).resolve()
        except (ValueError, OSError) as error:
            raise ArchiveError(str(error)) from error
        if holder != expected:
            raise ArchiveError(f"member {member} bound checkout is outside Path's workspace: {holder}")
        status = archive_milestone.require_git_success(
            run_git(holder, "status", "--porcelain", "--untracked-files=all"),
            "inspect member bound checkout",
        )
        if status:
            raise ArchiveError(f"member {member} bound checkout is not clean: {holder}")
    remote = live_remote_ref(checkout, bound_ref)
    if remote is not None:
        if remote != reviewed_head:
            raise ArchiveError(f"member {member} origin/{bound} moved: {remote}")
        members.authorize_delete(checkout, project, bound_ref, reviewed_head)
        archive_milestone.require_git_success(
            run_git(checkout, "push", f"--force-with-lease={bound_ref}:{reviewed_head}", "origin", "--delete", bound),
            f"delete member origin/{bound}")
    if holder is not None:
        # The bound checkout may contain submodules: git refuses a plain worktree
        # removal for them regardless of cleanliness. isolation's remover defuses
        # links, deinits submodules, and forces the removal after the clean check
        # above has already guarded the dirty case.
        try:
            isolation._remove_worktree(checkout, holder, force=False)
        except isolation.IsolationError as error:
            raise ArchiveError(f"remove member bound checkout failed: {error}") from error
    if local is not None:
        archive_milestone.require_git_success(run_git(checkout, "update-ref", "-d", bound_ref, reviewed_head),
                                              "delete member bound branch")
    run_git(checkout, "update-ref", "-d", f"refs/remotes/origin/{bound}")
    for kind, ref in (("push", bound_ref), ("push", f"refs/heads/{default}"), ("push", f"refs/tags/{tag_name}"),
                      ("delete", bound_ref)):
        members.clear_authorization(checkout, project, kind, ref)
    # The last sidecar retires here at milestone end; isolation's retires also
    # release the pin whenever the workspace is idle, so a new root can apply.
    with contextlib.suppress(ValueError, OSError):
        worktree_paths.release_workspace(checkout)
    return {"member": member, "retired": bound}


def close_members(repo: Path, adopt: Optional[Mapping[str, str]] = None) -> dict:
    """Close each locked member in lock order before the coordinator ship commit; resumable.

    ``adopt`` carries user-approved ``--adopt-landed-member`` recoveries: the
    member name maps to the exact live default-branch tip whose history
    already contains the reviewed HEAD (#458).
    """
    try:
        import check_handoffs
        import members
        from pipeline_git import ship_commit_body
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import check_handoffs, members
        from scripts.pipeline_git import ship_commit_body
    project = repo.resolve()
    state, _, _ = archive_milestone.strict_state(project)
    if (state.phase, state.status) != ("ship", "active") or state.archive is None:
        raise ArchiveError("close-members requires ship/active with a prepared archive")
    archive = project / state.archive
    final_text = (archive / "review" / "FINAL.md").read_text(encoding="utf-8")
    reviewed = check_handoffs._reviewed_head(final_text, "FINAL.md")
    lock = archive / "build" / "members.json"
    locked = json.loads(lock.read_text(encoding="utf-8"))["members"] if lock.is_file() else []
    try:
        heads = check_handoffs.member_reviewed_heads(final_text, "FINAL.md")
    except check_handoffs.HandoffError as error:
        raise ArchiveError(str(error)) from error
    if sorted(heads) != sorted(entry["name"] for entry in locked):
        raise ArchiveError("FINAL.md Member reviewed HEAD lines must name each locked member")
    common = Path(archive_milestone.require_git_success(
        run_git(project, "rev-parse", "--path-format=absolute", "--git-common-dir"), "resolve Git common dir"))
    archive_name = PurePosixPath(state.archive).name
    try:
        modes = {item["name"]: item["integration"] for item in members.read_members(project)} if locked else {}
        rows = {row["name"]: row for row in members.read_member_close(common, archive_name)}
    except members.MembersError as error:
        raise ArchiveError(str(error)) from error
    if adopt:
        locked_names = {entry["name"] for entry in locked}
        unknown = sorted(set(adopt) - locked_names)
        if unknown:
            raise ArchiveError(
                f"--adopt-landed-member names member(s) not locked in this milestone: {', '.join(unknown)}")
        for adopted_name in sorted(adopt):
            mode = modes.get(adopted_name, "default")
            if mode == "default":
                mode = state.integration
            if mode != "direct":
                raise ArchiveError(
                    f"--adopt-landed-member names {adopted_name}, which is not a direct-mode member")
    def save() -> None:
        members.write_member_close(common, archive_name, [rows[item["name"]] for item in locked if item["name"] in rows])

    closed = []
    for entry in locked:
        name = entry["name"]
        mode = modes.get(name, "default")
        mode = state.integration if mode == "default" else mode
        row = rows.get(name) or {"name": name, "mode": mode, "reviewed_head": heads[name],
                                 "status": "pending", "merge": None, "tag": None}
        if row["reviewed_head"] != heads[name] or row["mode"] != mode:
            raise ArchiveError(f"member-close journal for {name} differs from FINAL.md or MEMBERS.md")
        if row["status"] == "integrated":
            result = validate_member_integrated(project, name, state.archive, heads[name])
            if (result["merge"], result["tag"]) != (row["merge"], row["tag"]):
                raise ArchiveError(f"member {name} integration differs from its member-close journal")
            closed.append(row)
            continue
        # Journal pending before the member moves; a later member waits for this one.
        rows[name] = row
        save()
        if mode == "direct":
            result = integrate_member(project, name, state.archive, heads[name],
                                      adopt=(adopt or {}).get(name))
        else:
            result = integrate_member_pull_request(project, name, state.archive, heads[name])
        if result.get("status") == "awaiting-merge":
            row["pull_request"] = result["pull_request"]
            save()
            return {"status": "awaiting-merge", "member": name, "pull_request": result["pull_request"]}
        row.update(status="integrated", merge=result["merge"], tag=result["tag"],
                   **({"adopted": True} if result.get("adopted") else {}))
        save()
        closed.append(row)
    return {"status": "integrated", "members": closed, "body": ship_commit_body(state.archive, reviewed, closed)}
