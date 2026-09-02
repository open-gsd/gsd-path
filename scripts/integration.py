#!/usr/bin/env python3
# gsd-path project runtime
"""Integrate a shipped milestone by merge, pull request and tag for archive_milestone."""

import json
import re
from pathlib import Path, PurePosixPath
from typing import Optional

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
    from pipeline_state import PipelineState
    import _common
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
    from scripts.pipeline_state import PipelineState
    from scripts import _common


run_git = _common.run_git
run_command = _common.run_command


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


def publish_bound_branch(project: Path, branch: str, ship_commit: str) -> None:
    remote_ref = f"refs/heads/{branch}"
    remote_sha = live_remote_ref(project, remote_ref)
    if remote_sha is None:
        archive_milestone.require_git_success(
            run_git(
                project,
                "push",
                f"--force-with-lease={remote_ref}:",
                "origin",
                f"{ship_commit}:{remote_ref}",
            ),
            "create bound branch with absent-ref lease",
        )
    elif remote_sha != ship_commit:
        raise ArchiveError(
            f"origin/{branch} moved or collides: {remote_sha} != {ship_commit}"
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


def integration_names(project: Path, archive_name: str) -> tuple[str, Path]:
    identifier = milestone_id(milestone_number(archive_name))
    branch = f"gsd-path-integrate/{identifier}"
    worktree = project.parent / f".{project.name}-gsd-path-integrate-{identifier}"
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
        raise ArchiveError("stale integration merge is already published on origin/main")
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
                + f"; run: git -C {project} merge {default_name} on {bound_branch}, "
                "resolve those paths, re-ship, then rerun integrate"
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
        run_git(project, "remote", "get-url", "origin"),
        "resolve origin URL",
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
) -> None:
    if pull["base"].get("ref") != "main":
        raise ArchiveError("GitHub pull request base is not main")
    if pull["head"].get("ref") != branch:
        raise ArchiveError("GitHub pull request head is not the bound branch")
    if pull["head"].get("sha") != ship_commit:
        raise ArchiveError("GitHub pull request head is not the ship commit")
    if not pull_request_head_matches_repository(pull, repository):
        raise ArchiveError("GitHub pull request head repository is not origin")


def find_pull_request(repository: str, branch: str, ship_commit: str) -> Optional[dict]:
    pulls = require_pull_request_pages(
        github_api_json(
            f"repos/{repository}/pulls",
            "--method",
            "GET",
            "-f",
            "state=all",
            "-f",
            "base=main",
            "--paginate",
            "--slurp",
        )
    )
    pulls = [
        pull
        for pull in pulls
        if pull["base"].get("ref") == "main"
        and (
            pull["head"].get("sha") == ship_commit
            or (
                pull["head"].get("ref") == branch
                and pull_request_head_matches_repository(pull, repository)
            )
        )
    ]
    if len(pulls) > 1:
        raise ArchiveError("multiple pull requests target main from the ship commit")
    if not pulls:
        return None
    pull = pulls[0]
    require_pull_request_identity(repository, pull, branch, ship_commit)
    return pull


def pull_request_body(archive_path: str, ship_commit: str, branch: str) -> str:
    return (
        f"{integrate_commit_body(archive_path, ship_commit, 'main', branch)}"
        f"\n\n---\n{PR_CREDIT_LINE}"
    )


def update_pull_request_body(
    repository: str,
    pull: dict,
    archive_path: str,
    ship_commit: str,
    branch: str,
) -> dict:
    expected = pull_request_body(archive_path, ship_commit, branch)
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
    require_pull_request_identity(repository, updated, branch, ship_commit)
    if updated.get("body") != expected:
        raise ArchiveError("updated GitHub pull request is missing the credit footer")
    return updated


def create_pull_request(
    repository: str,
    branch: str,
    archive_path: str,
    archive_name: str,
    ship_commit: str,
) -> dict:
    body = pull_request_body(archive_path, ship_commit, branch)
    response = github_api_json(
        f"repos/{repository}/pulls",
        "--method",
        "POST",
        "-f",
        f"title={integrate_subject(archive_name, 'main')}",
        "-f",
        f"head={branch}",
        "-f",
        "base=main",
        "-f",
        f"body={body}",
    )
    pull = require_pull_request_shape(response)
    require_pull_request_identity(repository, pull, branch, ship_commit)
    return pull


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
    message = archive_milestone.require_git_success(
        run_git(project, "for-each-ref", "--format=%(contents)", tag_ref),
        "inspect pull-request milestone tag",
    )
    fields: dict[str, str] = {}
    for line in message.splitlines():
        match = re.fullmatch(r"(Mode|Pull-Request|Ship|Landing): (.+)", line)
        if match:
            if match.group(1) in fields:
                raise ArchiveError("pull-request milestone tag repeats metadata")
            fields[match.group(1)] = match.group(2)
    if set(fields) != {"Mode", "Pull-Request", "Ship", "Landing"}:
        raise ArchiveError("pull-request milestone tag is missing metadata")
    if fields["Mode"] != "pull-request":
        raise ArchiveError("pull-request milestone tag has the wrong mode")
    return fields


def require_pull_request_merge(
    project: Path,
    merge_commit: str,
    ship_commit: str,
    remote_default: str,
) -> None:
    resolved = optional_ref(project, merge_commit)
    if resolved != merge_commit:
        raise ArchiveError("GitHub merge commit is unavailable after fetch")
    parents = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--parents", "-n", "1", merge_commit),
        "inspect pull-request merge parents",
    ).split()
    if len(parents) != 3:
        raise ArchiveError("pull-request integration must use a two-parent merge commit")
    if parents[2] != ship_commit:
        raise ArchiveError("pull-request merge second parent is not the ship commit")
    first_parent = archive_milestone.require_git_success(
        run_git(project, "rev-list", "--first-parent", remote_default),
        "inspect remote-default first-parent history",
    ).splitlines()
    if merge_commit not in first_parent:
        raise ArchiveError("pull-request merge is not on origin/main first-parent history")


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
    pull = find_pull_request(repository, branch, ship_commit)
    if pull is None:
        publish_bound_branch(project, branch, ship_commit)
        pull = create_pull_request(
            repository,
            branch,
            archive_path,
            archive_name,
            ship_commit,
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
    require_pull_request_merge(project, merge_commit, ship_commit, remote_default)
    pull = update_pull_request_body(
        repository,
        pull,
        archive_path,
        ship_commit,
        branch,
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


def integrate(repo: Path, slug: str) -> dict:
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
    if default_name != "main":
        raise ArchiveError(f"remote default must be main, got {default_name!r}")
    if bound_branch == default_name:
        raise ArchiveError("bound branch must not be the remote default")
    remote_default_sha = archive_milestone.require_git_success(
        run_git(project, "rev-parse", remote_default), "resolve remote default"
    )
    if state.integration == "pull-request":
        return integrate_pull_request(
            project,
            state,
            archive_path,
            archive_name,
            ship_commit,
        )
    integration_branch, worktree = integration_names(project, archive_name)
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
            + "; resolve those paths on the bound branch, re-ship, then rerun integrate"
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
                "push integration merge to main",
            )
            archive_milestone.require_git_success(
                run_git(project, "update-ref", remote_default, merge_commit),
                "refresh local remote-default ref",
            )
        elif published_merge.returncode != 0:
            archive_milestone.require_git_success(published_merge, "inspect published integration merge")

        publish_bound_branch(project, bound_branch, ship_commit)
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


def validate_integrated(repo: Path, slug: str) -> dict:
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
    shipped = archive_milestone.validate(repo)
    configured = shipped["archive"]
    ship_commit = shipped["commit"]
    archive_name = PurePosixPath(configured).name

    if state.integration == "pull-request":
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
            "ship merges onto main, never onto the work branch"
        )
    if default_name != "main":
        raise ArchiveError(f"remote default must be main, got {default_name!r}")

    # (b) Resolve the integration proof selected before build.
    tag_name = f"milestone/{archive_name}"
    tag_ref = f"refs/tags/{tag_name}"
    pull_request = None
    if state.integration == "pull-request":
        if run_git(project, "rev-parse", "--verify", "--quiet", tag_ref).returncode != 0:
            raise ArchiveError(f"missing milestone tag: {tag_name}")
        metadata = pull_request_tag_metadata(project, tag_ref)
        if metadata["Ship"] != ship_commit:
            raise ArchiveError("pull-request milestone tag names the wrong ship commit")
        merge_commit = metadata["Landing"]
        pull_request = metadata["Pull-Request"]
        require_github_authentication()
        repository = github_repository(project)
        pull = find_pull_request(repository, bound_branch, ship_commit)
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
        require_pull_request_merge(project, merge_commit, ship_commit, remote_default)
        require_annotated_tag(
            project,
            tag_ref,
            merge_commit,
            f"milestone tag {tag_name}",
            pull_request_tag_message(
                archive_name,
                pull_request,
                ship_commit,
                merge_commit,
            ),
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

    # (e) The bound branch tip and annotated tag must be published on origin.
    require_published_integration(
        project,
        bound_branch,
        ship_commit,
        tag_name,
        merge_commit,
        allow_missing_bound=state.integration == "pull-request",
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
    if pull_request is not None:
        result["pull_request"] = pull_request
    return result


def require_published_integration(
    project: Path,
    bound_branch: str,
    ship_commit: str,
    tag_name: str,
    merge_commit: str,
    allow_missing_bound: bool = False,
) -> None:
    if allow_missing_bound:
        published_ship = live_remote_ref(project, f"refs/heads/{bound_branch}")
        if published_ship is not None and published_ship != ship_commit:
            raise ArchiveError(
                f"origin/{bound_branch} is {published_ship}, expected ship commit {ship_commit}"
            )
        published_tag = live_remote_ref(project, f"refs/tags/{tag_name}")
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
        if not allow_missing_bound:
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


# archive_milestone imports this module, so the parent is resolved after the
# definitions above. Parent functions are looked up on the module at call time
# so patches applied to archive_milestone stay visible here.
if __package__:  # imported as scripts.integration
    from . import archive_milestone
    from .archive_milestone import (
        GITHUB_HOST,
        PR_CREDIT_LINE,
        ArchiveError,
    )
else:  # standalone script or sibling import
    import archive_milestone
    from archive_milestone import (
        GITHUB_HOST,
        PR_CREDIT_LINE,
        ArchiveError,
    )
