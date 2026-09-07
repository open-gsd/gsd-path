#!/usr/bin/env python3
"""Create or resume an approved GitHub repository and GSD Path worktree."""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, Sequence

try:
    import _common
except ImportError:  # pragma: no cover - package import used by tests
    from scripts import _common


class BootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class BootstrapRequest:
    workspace: str
    owner: str
    repo: str
    visibility: str
    default_checkout: str
    worktree: str
    branch: str
    description: Optional[str]

    @property
    def repository(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def slug(self) -> str:
        return normalized_slug(self.repo)

    @property
    def workspace_path(self) -> Path:
        return Path(self.workspace)

    @property
    def checkout_path(self) -> Path:
        return Path(self.default_checkout)

    @property
    def worktree_path(self) -> Path:
        return Path(self.worktree)

    @property
    def journal_path(self) -> Path:
        name = f"{self.owner}--{self.repo}.json"
        return self.workspace_path / ".gsd-path-transactions" / name


def normalized_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if not slug:
        raise BootstrapError("repository name does not produce a project slug")
    return slug


run = _common.run_command


def require_success(result: subprocess.CompletedProcess[str], action: str) -> str:
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise BootstrapError(f"{action} failed: {detail}")
    return result.stdout.strip()


def require_real_directory(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_dir():
        raise BootstrapError(f"{label} must be a real directory: {path}")


def require_outside_worktree(path: Path, label: str) -> None:
    result = run("git", "-C", str(path), "rev-parse", "--is-inside-work-tree")
    if result.returncode == 0:
        raise BootstrapError(f"{label} must not be inside a Git worktree: {path}")


def request_from_arguments(arguments: argparse.Namespace) -> BootstrapRequest:
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})", arguments.owner):
        raise BootstrapError("GitHub owner is invalid")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", arguments.repo):
        raise BootstrapError("GitHub repository name is invalid")
    if arguments.visibility not in {"public", "private", "internal"}:
        raise BootstrapError("visibility must be public, private, or internal")

    workspace = arguments.workspace.resolve()
    checkout = arguments.default_checkout.resolve()
    worktree = arguments.worktree.resolve()
    require_real_directory(workspace, "workspace")
    require_real_directory(checkout.parent, "default-checkout parent")
    require_real_directory(worktree.parent, "worktree parent")
    require_outside_worktree(checkout.parent, "default-checkout parent")
    require_outside_worktree(worktree.parent, "worktree parent")
    if checkout == worktree:
        raise BootstrapError("default checkout and linked worktree must be distinct")

    _ = normalized_slug(arguments.repo)
    return BootstrapRequest(
        workspace=str(workspace),
        owner=arguments.owner,
        repo=arguments.repo,
        visibility=arguments.visibility,
        default_checkout=str(checkout),
        worktree=str(worktree),
        branch="gsd-path/M001",
        description=arguments.description,
    )


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.gsd-path-tmp"
    try:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()


def transaction_directory(request: BootstrapRequest, create: bool = False) -> Path:
    directory = request.journal_path.parent
    if directory.is_symlink():
        raise BootstrapError(f"transaction directory must be real: {directory}")
    if directory.exists() and not directory.is_dir():
        raise BootstrapError(f"transaction directory must be real: {directory}")
    if directory.exists():
        expected_parent = request.workspace_path.resolve()
        if directory.resolve().parent != expected_parent:
            raise BootstrapError(f"transaction directory escapes workspace: {directory}")
    elif create:
        directory.mkdir()
    return directory


def request_payload(request: BootstrapRequest) -> dict:
    return {"schema": "gsd-path/new-github/v1", **asdict(request)}


def read_journal(request: BootstrapRequest) -> Optional[dict]:
    transaction_directory(request)
    journal = request.journal_path
    if not journal.exists():
        return None
    if journal.is_symlink() or not journal.is_file():
        raise BootstrapError(f"transaction journal must be a real file: {journal}")
    try:
        payload = json.loads(journal.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BootstrapError(
            f"transaction journal is unreadable: {journal}: {error}"
        ) from error
    if payload != request_payload(request):
        raise BootstrapError(
            "transaction journal does not match the approved repository targets"
        )
    return payload


def write_journal(request: BootstrapRequest) -> None:
    transaction_directory(request, create=True)
    atomic_write(
        request.journal_path,
        json.dumps(request_payload(request), indent=2, sort_keys=True) + "\n",
    )


def gh_authentication() -> None:
    require_success(run("gh", "auth", "status"), "verify GitHub authentication")


def remote_exists(request: BootstrapRequest) -> bool:
    result = run("gh", "api", "--silent", f"repos/{request.repository}")
    if result.returncode == 0:
        return True
    detail = f"{result.stdout}\n{result.stderr}"
    if re.search(r"\b404\b", detail):
        return False
    raise BootstrapError(f"GitHub repository lookup was ambiguous: {detail.strip()}")


def verify_remote_visibility(request: BootstrapRequest) -> None:
    visibility = require_success(
        run(
            "gh",
            "api",
            f"repos/{request.repository}",
            "--jq",
            ".visibility",
        ),
        "verify GitHub repository visibility",
    ).casefold()
    if visibility != request.visibility:
        raise BootstrapError(
            f"GitHub repository visibility is {visibility}, not {request.visibility}"
        )


def binding_field(content: str, name: str) -> str:
    values = [
        line.removeprefix(f"{name}:").strip()
        for line in content.splitlines()
        if line.startswith(f"{name}:")
    ]
    if len(values) != 1 or not values[0]:
        raise BootstrapError(f"REPOSITORY.md requires one {name} field")
    return values[0]


def completed_binding(request: BootstrapRequest) -> Optional[tuple[str, str]]:
    state = request.worktree_path / ".project" / "STATE.md"
    binding = request.worktree_path / ".project" / "REPOSITORY.md"
    if not state.exists() and not binding.exists():
        return None
    if (
        not state.is_file()
        or not binding.is_file()
        or state.is_symlink()
        or binding.is_symlink()
    ):
        return None
    state_text = state.read_text(encoding="utf-8")
    binding_text = binding.read_text(encoding="utf-8")
    if not re.search(r"^pipeline:\s*gsd-path/v2\s*$", state_text, re.MULTILINE):
        raise BootstrapError("completed bootstrap STATE.md has the wrong pipeline marker")
    if not re.search(
        rf"^branch:\s*{re.escape(request.branch)}\s*(?:#.*)?$",
        state_text,
        re.MULTILINE,
    ):
        raise BootstrapError("completed bootstrap STATE.md has the wrong branch binding")

    expected = {
        "Kind": "new-github",
        "Remote": f"https://github.com/{request.repository}",
        "Visibility": request.visibility,
        "Default checkout": request.default_checkout,
        "GSD Path branch": request.branch,
        "Primary worktree": request.worktree,
    }
    for name, value in expected.items():
        if binding_field(binding_text, name) != value:
            raise BootstrapError(f"completed repository binding has the wrong {name}")
    remote_default = binding_field(binding_text, "Remote default")
    base = binding_field(binding_text, "Remote default SHA")
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise BootstrapError("completed repository binding has an invalid base SHA")
    return remote_default, base


def transaction_stages(request: BootstrapRequest) -> dict:
    binding = completed_binding(request)
    return {
        "remote": remote_exists(request),
        "default_checkout": request.checkout_path.exists(),
        "worktree": request.worktree_path.exists(),
        "pipeline": binding is not None,
    }


def preview(request: BootstrapRequest) -> dict:
    gh_authentication()
    stages = transaction_stages(request)
    if stages["pipeline"]:
        verify_completed_binding(request)
        return {**request_payload(request), "mode": "complete", "stages": stages}
    if read_journal(request) is not None:
        return {**request_payload(request), "mode": "resume", "stages": stages}
    if stages["remote"]:
        raise BootstrapError(
            "GitHub repository already exists without this approved transaction"
        )
    for label, path in (
        ("default checkout", request.checkout_path),
        ("linked worktree", request.worktree_path),
    ):
        if path.exists() or path.is_symlink():
            raise BootstrapError(f"{label} path already exists: {path}")
    return {**request_payload(request), "mode": "create", "stages": stages}


def create_remote(request: BootstrapRequest) -> None:
    command = [
        "gh",
        "repo",
        "create",
        request.repository,
        f"--{request.visibility}",
        "--add-readme",
    ]
    if request.description:
        command.extend(("--description", request.description))
    require_success(
        run(*command, cwd=request.workspace_path), "create GitHub repository"
    )


def git_output(repository: Path, *arguments: str) -> str:
    return require_success(run("git", "-C", str(repository), *arguments), "run Git")


def verify_origin(request: BootstrapRequest) -> None:
    origin = git_output(request.checkout_path, "remote", "get-url", "origin")
    resolved = require_success(
        run(
            "gh",
            "repo",
            "view",
            origin,
            "--json",
            "nameWithOwner",
            "--jq",
            ".nameWithOwner",
        ),
        "verify cloned repository origin",
    )
    if resolved.casefold() != request.repository.casefold():
        raise BootstrapError(
            f"default checkout origin belongs to {resolved!r}, not {request.repository!r}"
        )


def verify_checkout_location(request: BootstrapRequest) -> Path:
    checkout = request.checkout_path
    require_real_directory(checkout, "default checkout")
    top_level = Path(git_output(checkout, "rev-parse", "--show-toplevel")).resolve()
    if top_level != checkout:
        raise BootstrapError(f"default checkout is not its Git root: {checkout}")
    verify_origin(request)
    if git_output(checkout, "status", "--porcelain"):
        raise BootstrapError("default checkout is not clean")
    return checkout


def verify_checkout_branch(checkout: Path, remote_default: str) -> None:
    if git_output(checkout, "branch", "--show-current") != remote_default:
        raise BootstrapError("default checkout is not on the remote default branch")


def verify_checkout_revision(checkout: Path, remote_default: str, base: str) -> None:
    verify_checkout_branch(checkout, remote_default)
    if git_output(checkout, "rev-parse", "HEAD") != base:
        raise BootstrapError("default checkout does not match the remote-default SHA")


def verify_completed_checkout_revision(
    checkout: Path, remote_default: str, creation_sha: str
) -> None:
    verify_checkout_branch(checkout, remote_default)
    verify_creation_ancestry(checkout, creation_sha, "completed default checkout")


def verify_checkout(request: BootstrapRequest) -> tuple[str, str]:
    checkout = verify_checkout_location(request)

    require_success(
        run("git", "-C", str(checkout), "fetch", "--prune", "origin"),
        "refresh remote default branch",
    )
    require_success(
        run("git", "-C", str(checkout), "remote", "set-head", "origin", "--auto"),
        "resolve remote default branch",
    )
    remote_head = run(
        "git",
        "-C",
        str(checkout),
        "symbolic-ref",
        "--quiet",
        "--short",
        "refs/remotes/origin/HEAD",
    )
    remote_ref = require_success(remote_head, "resolve remote default branch")
    if not remote_ref.startswith("origin/"):
        raise BootstrapError(f"remote default ref is invalid: {remote_ref}")
    remote_default = remote_ref.removeprefix("origin/")
    if remote_default == request.branch:
        raise BootstrapError(
            f"remote default {remote_default!r} must stay a trunk; "
            "the GSD Path branch cannot be the GitHub default"
        )
    if remote_default != "main":
        raise BootstrapError(f"remote default must be main, got {remote_default!r}")
    base = git_output(checkout, "rev-parse", remote_ref)
    verify_checkout_revision(checkout, remote_default, base)
    return remote_default, base


def clone_or_verify_checkout(request: BootstrapRequest) -> tuple[str, str]:
    checkout = request.checkout_path
    if not checkout.exists():
        require_success(
            run("gh", "repo", "clone", request.repository, str(checkout)),
            "clone GitHub repository",
        )
    return verify_checkout(request)


def git_common_directory(repository: Path) -> Path:
    value = git_output(repository, "rev-parse", "--git-common-dir")
    path = Path(value)
    if not path.is_absolute():
        path = repository / path
    return path.resolve()


def verify_creation_ancestry(
    repository: Path, creation_sha: str, label: str
) -> None:
    ancestry = run(
        "git",
        "-C",
        str(repository),
        "merge-base",
        "--is-ancestor",
        creation_sha,
        "HEAD",
    )
    if ancestry.returncode != 0:
        raise BootstrapError(
            f"{label} does not descend from the recorded creation SHA"
        )


def allowed_partial_project_status(worktree: Path) -> bool:
    status = git_output(worktree, "status", "--porcelain", "--untracked-files=all")
    if not status:
        return True
    allowed = {".project/STATE.md", ".project/REPOSITORY.md"}
    paths = {line[3:] for line in status.splitlines() if len(line) > 3}
    return bool(paths) and paths <= allowed


def create_or_verify_worktree(request: BootstrapRequest, base: str) -> None:
    checkout = request.checkout_path
    worktree = request.worktree_path
    if not worktree.exists():
        branch_ref = f"refs/heads/{request.branch}"
        branch = run("git", "-C", str(checkout), "rev-parse", "--verify", branch_ref)
        if branch.returncode == 0:
            if branch.stdout.strip() != base:
                raise BootstrapError(
                    "existing GSD Path branch is not at the approved base SHA"
                )
            command = (
                "git",
                "-C",
                str(checkout),
                "worktree",
                "add",
                str(worktree),
                request.branch,
            )
        else:
            command = (
                "git",
                "-C",
                str(checkout),
                "worktree",
                "add",
                "-b",
                request.branch,
                str(worktree),
                base,
            )
        require_success(run(*command), "create linked GSD Path worktree")

    verify_worktree(request, base)


def verify_worktree(request: BootstrapRequest, base: str) -> None:
    worktree = verify_worktree_location(request)
    if git_output(worktree, "rev-parse", "HEAD") != base:
        raise BootstrapError("linked worktree is not at the approved base SHA")
    if not allowed_partial_project_status(worktree):
        raise BootstrapError("linked worktree contains unexpected changes")


def verify_worktree_location(request: BootstrapRequest) -> Path:
    worktree = request.worktree_path

    require_real_directory(worktree, "linked GSD Path worktree")
    top_level = Path(git_output(worktree, "rev-parse", "--show-toplevel")).resolve()
    if top_level != worktree:
        raise BootstrapError(f"linked worktree is not its Git root: {worktree}")
    if git_common_directory(request.checkout_path) != git_common_directory(worktree):
        raise BootstrapError("linked worktree belongs to another repository")
    if git_output(worktree, "branch", "--show-current") != request.branch:
        raise BootstrapError("linked worktree is on the wrong branch")
    return worktree


def verify_completed_worktree(request: BootstrapRequest, creation_sha: str) -> None:
    worktree = verify_worktree_location(request)
    verify_creation_ancestry(worktree, creation_sha, "completed linked worktree")


def verify_completed_binding(request: BootstrapRequest) -> tuple[str, str]:
    binding = completed_binding(request)
    if binding is None:
        raise BootstrapError("completed repository binding is missing")
    expected_default, expected_base = binding
    verify_remote_visibility(request)
    checkout = verify_checkout_location(request)
    try:
        verify_completed_checkout_revision(
            checkout, expected_default, expected_base
        )
    except BootstrapError as error:
        raise BootstrapError(
            f"completed repository binding does not match the checkout: {error}"
        ) from error
    verify_completed_worktree(request, expected_base)
    return expected_default, expected_base


def render_state(template: Path, request: BootstrapRequest) -> str:
    if template.is_symlink() or not template.is_file():
        raise BootstrapError(f"state template must be a real file: {template}")
    content = template.read_text(encoding="utf-8")
    content = content.replace("project: <slug>", f"project: {request.slug}")
    content = content.replace("branch: null", f"branch: {request.branch}")
    content = content.replace(
        "- YYYY-MM-DD — <phase> — project initialized",
        "- repository initialized — binding: .project/REPOSITORY.md",
    )
    if "<slug>" in content or "branch: null" in content:
        raise BootstrapError("state template placeholders were not fully replaced")
    return content


def render_binding(
    template: Path,
    request: BootstrapRequest,
    remote_default: str,
    base: str,
) -> str:
    if template.is_symlink() or not template.is_file():
        raise BootstrapError(f"repository template must be a real file: {template}")
    replacements = {
        "<kind>": "new-github",
        "<remote>": f"https://github.com/{request.repository}",
        "<visibility>": request.visibility,
        "<remote-default>": remote_default,
        "<remote-default-sha>": base,
        "<default-checkout>": request.default_checkout,
        "<branch>": request.branch,
        "<primary-worktree>": request.worktree,
    }
    content = template.read_text(encoding="utf-8")
    for placeholder, value in replacements.items():
        content = content.replace(placeholder, value)
    if any(placeholder in content for placeholder in replacements):
        raise BootstrapError("repository template placeholders were not fully replaced")
    return content


def write_exact(path: Path, content: str) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file():
            raise BootstrapError(f"bootstrap artifact must be a real file: {path}")
        if path.read_text(encoding="utf-8") != content:
            raise BootstrapError(f"bootstrap artifact differs from approved transaction: {path}")
        return
    atomic_write(path, content)


def initialize_pipeline(
    request: BootstrapRequest,
    remote_default: str,
    base: str,
    state_template: Path,
    repository_template: Path,
) -> None:
    project = request.worktree_path / ".project"
    staging = request.worktree_path / ".project.gsd-path-tmp"
    if project.exists() or project.is_symlink():
        if project.is_symlink() or not project.is_dir():
            raise BootstrapError(f"pipeline directory must be a real directory: {project}")
        write_exact(project / "STATE.md", render_state(state_template, request))
        write_exact(
            project / "REPOSITORY.md",
            render_binding(repository_template, request, remote_default, base),
        )
        return
    if staging.exists() or staging.is_symlink():
        if staging.is_symlink() or not staging.is_dir():
            raise BootstrapError(f"pipeline staging path is invalid: {staging}")
        shutil.rmtree(staging)
    staging.mkdir()
    try:
        atomic_write(staging / "STATE.md", render_state(state_template, request))
        atomic_write(
            staging / "REPOSITORY.md",
            render_binding(repository_template, request, remote_default, base),
        )
        os.replace(staging, project)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def remove_journal(request: BootstrapRequest) -> None:
    transaction_directory(request)
    request.journal_path.unlink()
    directory = request.journal_path.parent
    if not any(directory.iterdir()):
        directory.rmdir()


def create(
    request: BootstrapRequest,
    state_template: Path,
    repository_template: Path,
) -> dict:
    gh_authentication()
    if completed_binding(request) is not None:
        remote_default, base = verify_completed_binding(request)
        if request.journal_path.exists():
            read_journal(request)
            remove_journal(request)
        return {
            **request_payload(request),
            "status": "complete",
            "remote_default": remote_default,
            "remote_default_sha": base,
        }

    journal = read_journal(request)
    if journal is None:
        preview_result = preview(request)
        if preview_result["mode"] != "create":
            raise BootstrapError("repository transaction is not ready to create")
        write_journal(request)

    if not remote_exists(request):
        create_remote(request)
    verify_remote_visibility(request)
    remote_default, base = clone_or_verify_checkout(request)
    create_or_verify_worktree(request, base)
    initialize_pipeline(
        request,
        remote_default,
        base,
        state_template.resolve(),
        repository_template.resolve(),
    )
    remove_journal(request)
    return {
        **request_payload(request),
        "status": "complete",
        "remote_default": remote_default,
        "remote_default_sha": base,
    }


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("command", choices=("preview", "create"))
    argument_parser.add_argument("--workspace", type=Path, required=True)
    argument_parser.add_argument("--owner", required=True)
    argument_parser.add_argument("--repo", required=True)
    argument_parser.add_argument(
        "--visibility", choices=("public", "private", "internal"), required=True
    )
    argument_parser.add_argument("--default-checkout", type=Path, required=True)
    argument_parser.add_argument("--worktree", type=Path, required=True)
    argument_parser.add_argument("--description")
    argument_parser.add_argument("--state-template", type=Path)
    argument_parser.add_argument("--repository-template", type=Path)
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        arguments = parser().parse_args(argv)
        request = request_from_arguments(arguments)
        if arguments.command == "preview":
            result = preview(request)
        else:
            if arguments.state_template is None or arguments.repository_template is None:
                raise BootstrapError("create requires both bundled template paths")
            result = create(
                request,
                arguments.state_template,
                arguments.repository_template,
            )
        print(json.dumps(result, sort_keys=True))
        return 0
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
