#!/usr/bin/env python3
# gsd-path project runtime
"""Lint build task briefs against the layer base before dispatch."""

import argparse
import json
import re
import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple

if __package__:
    from . import _common
else:
    try:
        import _common
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import _common


DEFAULT_TASKS_DIR = ".project/tasks"
REQUIRED_FIELDS = (
    "id",
    "title",
    "wave",
    "deps",
    "status",
    "agent",
    "base",
    "worktree",
    "task_branch",
    "files",
)
FORBIDDEN_FIELDS = ("commit",)
REQUIRED_SECTIONS = (
    "Context",
    "Approach",
    "Interface contract",
    "Intent coverage",
    "Acceptance criteria",
    "Verify",
    "Log",
)
PROSE_SECTIONS = ("Context", "Approach", "Interface contract")
FIELD_PATTERN = _common.FIELD_PATTERN
INLINE_LIST_PATTERN = _common.INLINE_LIST_PATTERN
LIST_ITEM_PATTERN = _common.LIST_ITEM_PATTERN
HEADING_PATTERN = re.compile(r"(?m)^## (?P<name>.+?)\s*$")
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
BACKTICK_PATTERN = re.compile(r"`([^`\n]+)`")
PATH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._~/-]+")
VERIFY_BLOCK_PATTERN = re.compile(r"```bash[ \t]*\n(?P<block>.*?)```", re.DOTALL)
TEXT_TOOL_COMMANDS = frozenset({"awk", "egrep", "fgrep", "gawk", "grep", "gsed", "rg", "sed"})
REGEX_PATTERN_CHARS = frozenset("|*+?[]()^$.\\")
PIPELINE_WORKSPACE_DIRS = ("review", "discuss", "build", "plan")


class BriefError(RuntimeError):
    """Raised when task briefs fail the layer-prep lint or inputs are unusable."""


_run_git = _common.run_git


def _resolve_base(repo: Path, base: str) -> str:
    result = _run_git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if result.returncode != 0:
        raise BriefError(f"--base does not resolve to a commit: {base}")
    return result.stdout.strip()


def _base_exists(repo: Path, base: str, path: str) -> bool:
    return _run_git(repo, "cat-file", "-e", f"{base}:{path}").returncode == 0


def _project_track(task: Path, repo: Path) -> Optional[str]:
    try:
        track = task.parent.parent.relative_to(repo).as_posix()
    except ValueError:
        return None
    if track not in {".project", ".project/next"}:
        return None
    return track


def _supplied_contract(repo: Path, task: Path, token: str) -> bool:
    """Plan approval checkpoints these supplied inputs after the brief gate."""
    track = _project_track(task, repo)
    if track is None:
        return False
    if token not in {
        f"{track}/intent/INTENT.md",
        f"{track}/research/SYNTHESIS.md",
    }:
        return False
    path = repo / token
    return path.is_file() and path.resolve() == repo.resolve() / token


def _pipeline_workspace_file(repo: Path, task: Path, token: str) -> bool:
    """Pipeline-owned paths may exist only in the working tree before checkpoint."""
    track = _project_track(task, repo)
    if track is None:
        return False
    prefixes = tuple(f"{track}/{name}/" for name in PIPELINE_WORKSPACE_DIRS)
    if not any(token.startswith(prefix) for prefix in prefixes):
        return False
    path = repo / token
    return path.is_file() and path.resolve() == repo.resolve() / token


_strip_yaml_comment = _common.strip_yaml_comment
_unquote = _common.unquote


def _frontmatter(text: str) -> Tuple[Optional[Dict[str, object]], Optional[str]]:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        return None, "missing YAML frontmatter"
    fields: Dict[str, object] = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line == "---":
            return fields, None
        match = FIELD_PATTERN.match(line)
        if match:
            key = match.group("key")
            if key in fields:
                return None, f"frontmatter repeats field: {key}"
            value = _strip_yaml_comment(match.group("value"))
            inline = INLINE_LIST_PATTERN.fullmatch(value)
            if inline is not None:
                body = inline.group("body").strip()
                fields[key] = [
                    _unquote(item)
                    for item in body.split(",")
                    if item.strip()
                ]
                index += 1
                continue
            if value:
                fields[key] = _unquote(value)
                index += 1
                continue
            items: List[str] = []
            cursor = index + 1
            while cursor < len(lines):
                item = LIST_ITEM_PATTERN.match(lines[cursor])
                if not item:
                    break
                items.append(_unquote(item.group("value")))
                cursor += 1
            fields[key] = items
            index = cursor
            continue
        if line.strip() and not line.lstrip().startswith("#"):
            return None, f"malformed frontmatter line: {line}"
        index += 1
    return None, "frontmatter is not closed"


def _sections(text: str) -> Dict[str, str]:
    headings = list(HEADING_PATTERN.finditer(text))
    sections: Dict[str, str] = {}
    for position, heading in enumerate(headings):
        end = headings[position + 1].start() if position + 1 < len(headings) else len(text)
        sections[heading.group("name")] = text[heading.end() : end]
    return sections


def _clean(body: str) -> str:
    return COMMENT_PATTERN.sub("", body).strip()


def _slash_token_shape(token: str) -> bool:
    return (
        "/" in token
        and PATH_TOKEN_PATTERN.fullmatch(token) is not None
        and "://" not in token
        and not token.startswith(("-", "/"))  # /api/users is a route, not a repo path
        and "<" not in token
        and ">" not in token
    )


def _last_segment_has_extension(token: str) -> bool:
    name = PurePosixPath(token).name
    return "." in name and not name.startswith(".")


def _looks_like_path(
    token: str,
    *,
    repo: Path,
    git_root: Path,
    base: str,
    task: Path,
) -> bool:
    if not _slash_token_shape(token):
        return False
    if _last_segment_has_extension(token):
        return True
    if _base_exists(git_root, base, token):
        return True
    if _pipeline_workspace_file(repo, task, token):
        return True
    return False


def _looks_like_regex_pattern(token: str) -> bool:
    return any(character in token for character in REGEX_PATTERN_CHARS)


def _text_tool_command(command: str) -> bool:
    return Path(command).name.casefold() in TEXT_TOOL_COMMANDS


def _normalize(path: str) -> str:
    return str(PurePosixPath(path))


def _prose_tokens(
    body: str,
    *,
    repo: Path,
    git_root: Path,
    base: str,
    task: Path,
) -> List[str]:
    cleaned = COMMENT_PATTERN.sub("", body)
    tokens: List[str] = []
    for match in BACKTICK_PATTERN.finditer(cleaned):
        candidate = match.group(1).strip()
        if _looks_like_path(
            candidate, repo=repo, git_root=git_root, base=base, task=task
        ):
            tokens.append(_normalize(candidate))
    return tokens


def _verify_tokens(
    block: str,
    *,
    repo: Path,
    git_root: Path,
    base: str,
    task: Path,
) -> List[str]:
    tokens: List[str] = []
    for line in block.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        command = parts[0]
        extended_grep = False
        index = 1
        while index < len(parts) and parts[index].startswith("-") and "=" not in parts[index]:
            flag = parts[index]
            if flag in {"-E", "-G"} or flag.startswith("-E"):
                extended_grep = True
            index += 1
        text_tool = _text_tool_command(command)
        for raw in parts[index:]:
            quoted = raw.startswith(("'", '"'))
            token = raw.strip("\"'")
            if text_tool and quoted:
                continue
            if text_tool and command.casefold() == "grep" and extended_grep and _looks_like_regex_pattern(token):
                continue
            if _looks_like_path(token, repo=repo, git_root=git_root, base=base, task=task):
                tokens.append(_normalize(token))
    return tokens


def _member_bases(root: Path):
    """Resolve a member name to (checkout, origin/main SHA), reading MEMBERS.md once."""
    cache: Dict[str, Optional[Tuple[Path, str]]] = {}

    def locate(name: str) -> Optional[Tuple[Path, str]]:
        if name not in cache:
            if __package__:
                from . import members
            else:
                try:
                    import members
                except ImportError:  # pragma: no cover - package import used by tests
                    from scripts import members
            try:
                listed = {member["name"]: Path(member["checkout"]) for member in members.read_members(root)}
                checkout = listed.get(name)
                if checkout is None:
                    cache[name] = None
                else:
                    # A build lock selects the bound tip, including during Plan recovery;
                    # without the lock, use origin/main before the first build start.
                    lock = root / members.LOCK_PATH
                    locked = [entry for entry in (json.loads(lock.read_text(encoding="utf-8"))["members"]
                                                  if lock.is_file() else []) if entry["name"] == name]
                    if locked:
                        cache[name] = (checkout, _resolve_base(checkout, f"refs/heads/{locked[0]['branch']}"))
                    else:
                        members.require_origin_main(checkout)
                        cache[name] = (checkout, _resolve_base(checkout, "refs/remotes/origin/main"))
            except (members.MembersError, BriefError) as error:
                raise BriefError(f"member {name} is unavailable: {error}") from error
        return cache[name]

    return locate


def _lint_task(
    repo: Path, base: str, path: Path,
    dependency_files: Optional[Dict[str, Set[str]]] = None,
    landed_bases: Optional[Dict[str, str]] = None,
    member_base=None,
) -> Tuple[str, List[str], Optional[str], int]:
    text = path.read_text(encoding="utf-8")
    fields, error = _frontmatter(text)
    task_id = path.stem
    if fields and isinstance(fields.get("id"), str):
        task_id = fields["id"]  # type: ignore[assignment]
    base = (landed_bases or {}).get(task_id, base)
    problems: List[str] = []
    checked = 0
    if fields is None:
        return task_id, [error or "invalid frontmatter"], None, checked
    # A member task's paths resolve in the member at its origin/main, where the
    # member bound branch starts; `repo:` absent means the coordinator.
    git_root = repo
    member = fields.get("repo")
    if member is not None:
        located = member_base(member) if isinstance(member, str) and member and member_base else None
        if located is None:
            return task_id, [f"repo: names no member in MEMBERS.md: {member}"], None, checked
        git_root, base = located[0], (landed_bases or {}).get(task_id, located[1])

    for field in REQUIRED_FIELDS:
        if field not in fields:
            problems.append(f"missing frontmatter field: {field}")
    for field in FORBIDDEN_FIELDS:
        if field in fields:
            problems.append(f"forbidden frontmatter field: {field}")

    sections = _sections(text)
    for name in REQUIRED_SECTIONS:
        body = sections.get(name)
        if body is None:
            problems.append(f"missing ## {name} section")
        elif not _clean(body):
            problems.append(f"## {name} section is empty")

    supplied = (dependency_files or {}).get(task_id, set())
    declared: Set[str] = set()
    files = fields.get("files")
    if isinstance(files, str):
        problems.append("frontmatter files must be a list")
    elif isinstance(files, list):
        for entry in files:
            candidate = PurePosixPath(entry)
            if candidate.is_absolute():
                problems.append(f"files entry is not repo-relative: {entry}")
                continue
            if ".." in candidate.parts:
                problems.append(f"files entry must not contain '..': {entry}")
                continue
            normalized = str(candidate)
            declared.add(normalized)
            checked += 1
            if ".git" in candidate.parts:
                problems.append(f"files entry must not enter .git: {normalized}")
                continue
            for parent in candidate.parents:
                if str(parent) == ".":
                    break
                kind = _run_git(git_root, "cat-file", "-t", f"{base}:{parent}")
                if kind.returncode == 0 and kind.stdout.strip() != "tree":
                    problems.append(
                        f"files entry {normalized} has non-directory ancestor "
                        f"{parent} at the layer base"
                    )
                    break

    for name in PROSE_SECTIONS:
        body = sections.get(name)
        if body is None or not _clean(body):
            continue
        for token in _prose_tokens(
            body, repo=repo, git_root=git_root, base=base, task=path
        ):
            checked += 1
            if (
                token not in declared
                and token not in supplied
                and not _supplied_contract(repo, path, token)
                and not _pipeline_workspace_file(repo, path, token)
                and not _base_exists(git_root, base, token)
            ):
                problems.append(f"## {name} names a path missing at the layer base: {token}")

    verify_body = sections.get("Verify")
    if verify_body is not None and _clean(verify_body):
        block = VERIFY_BLOCK_PATTERN.search(verify_body)
        if block is None or not block.group("block").strip():
            problems.append("## Verify must contain a non-empty fenced bash block")
        else:
            verify_script = block.group("block").removesuffix("\n")
            for token in _verify_tokens(
                verify_script,
                repo=repo,
                git_root=git_root,
                base=base,
                task=path,
            ):
                checked += 1
                if (
                    token not in declared
                    and token not in supplied
                    and not _pipeline_workspace_file(repo, path, token)
                    and not _base_exists(git_root, base, token)
                ):
                    problems.append(f"## Verify names a path missing at the layer base: {token}")
            denial = _common.verify_shell_denial(verify_script, git_root)
            if denial is not None:
                problems.append(
                    "## Verify command is denied by the host guard: "
                    + denial.replace("\n", " ")
                )

    contract = None
    contract_body = sections.get("Interface contract")
    if contract_body is not None:
        normalized = " ".join(_clean(contract_body).split())
        if normalized and normalized not in {"None", "- None"}:
            contract = _clean(contract_body)

    return task_id, problems, contract, checked


def validate_task_briefs(
    root: Path, base: str, tasks_dir: str = DEFAULT_TASKS_DIR,
    *, dependency_files: Optional[Dict[str, Set[str]]] = None,
    landed_bases: Optional[Dict[str, str]] = None,
    member_base=None,
) -> Dict[str, object]:
    """Lint task briefs using the caller's validation bases.

    Dispatch uses the layer base without overrides. Plan approval supplies
    transitive dependency files for pending tasks and resolved historical bases
    for landed tasks, whose immutable briefs must survive later file changes.
    The caller validates the task graph and landed metadata before supplying
    these mappings; landed tasks receive no dependency-file allowance.
    """

    resolved_base = _resolve_base(root, base)
    tasks_path = root / tasks_dir
    if not tasks_path.is_dir():
        raise BriefError(f"tasks directory not found: {tasks_dir}")

    problems: List[str] = []
    contracts: Dict[str, Set[str]] = {}
    checked = 0
    task_files = sorted(tasks_path.glob("*.md"))
    if not task_files:
        raise BriefError(f"no task briefs found in {tasks_dir}")
    if member_base is None:
        member_base = _member_bases(root)
    for path in task_files:
        task_id, task_problems, contract, task_checked = _lint_task(
            root, resolved_base, path, dependency_files, landed_bases, member_base
        )
        problems.extend(f"{task_id}: {problem}" for problem in task_problems)
        if contract is not None:
            for entry in re.split(r"(?m)^-[ \t]+", contract):
                shape = " ".join(entry.split())
                if shape:
                    contracts.setdefault(shape, set()).add(task_id)
        checked += task_checked

    for shape, task_ids in contracts.items():
        if len(task_ids) == 1:
            task_id = next(iter(task_ids))
            problems.append(
                f"{task_id}: interface contract is not shared by any other task: {shape}"
            )

    if problems:
        raise BriefError("\n".join(problems))
    return {"base": resolved_base, "checked": checked, "tasks": len(task_files)}


def validate_plan_task_briefs(
    root: Path,
    base: str,
    project_dir: str = ".project",
    tasks_dir: Optional[str] = None,
) -> Dict[str, object]:
    """Plan gate validation with dependency files and landed historical bases."""
    if __package__:
        from . import check_handoffs
        from .isolation import IsolationError, require_commit, require_full_sha
    else:
        try:
            import check_handoffs
            from isolation import IsolationError, require_commit, require_full_sha
        except ModuleNotFoundError as error:
            if error.name not in {"check_handoffs", "isolation"}:
                raise
            from scripts import check_handoffs
            from scripts.isolation import IsolationError, require_commit, require_full_sha
    tasks, dependency_files = check_handoffs.plan_brief_inputs(root, project_dir)
    landed_bases: Dict[str, str] = {}
    member_base = _member_bases(root)
    for task_id, text in tasks.items():
        if check_handoffs._task_scalar(text, task_id, "status") != "done":
            continue
        agent = check_handoffs._task_scalar(text, task_id, "agent")
        if agent in {"", "null"}:
            raise BriefError(f"{task_id} landed task has no recorded agent")
        member = check_handoffs._strict_frontmatter(text, task_id).get("repo")
        base_repo = root
        if member is not None:
            located = member_base(member) if isinstance(member, str) and member else None
            if located is None:
                raise BriefError(f"repo: names no member in MEMBERS.md: {member}")
            base_repo = located[0]
        recorded_base = check_handoffs._task_scalar(text, task_id, "base")
        recorded_full = require_full_sha(recorded_base)
        try:
            if member is not None:
                try:
                    landed_bases[task_id] = require_commit(root, recorded_full)
                except IsolationError:
                    landed_bases[task_id] = require_commit(base_repo, recorded_full)
            else:
                landed_bases[task_id] = require_commit(base_repo, recorded_full)
        except IsolationError as error:
            raise BriefError(f"{task_id} landed task has invalid historical base: {error}") from error
        dependency_files[task_id] = set()
    resolved_tasks_dir = tasks_dir or f"{project_dir}/tasks"
    return validate_task_briefs(
        root,
        base,
        resolved_tasks_dir,
        dependency_files=dependency_files,
        landed_bases=landed_bases,
        member_base=member_base,
    )


def _tasks_dir(value: str) -> str:
    """Argparse type for --tasks-dir: a relative POSIX-style path."""

    path = PurePosixPath(value)
    if path.is_absolute():
        raise argparse.ArgumentTypeError(
            f"--tasks-dir must be a relative path, found absolute: {value}"
        )
    if ".." in path.parts:
        raise argparse.ArgumentTypeError(
            f"--tasks-dir must not contain '..', found: {value}"
        )
    return str(path)


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--repo", type=Path, required=True)
    argument_parser.add_argument(
        "--base",
        required=True,
        help="full SHA of the clean layer base commit the briefs are checked against",
    )
    argument_parser.add_argument(
        "--tasks-dir",
        type=_tasks_dir,
        default=DEFAULT_TASKS_DIR,
        help="relative POSIX-style directory under --repo holding the task files "
        "(default: .project/tasks)",
    )
    argument_parser.add_argument(
        "--project-dir",
        default=None,
        help="when set, apply plan-approval dependency files and landed-task bases "
        "(same rules as state_checkpoint plan approval)",
    )
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.project_dir is not None:
            result = validate_plan_task_briefs(
                arguments.repo.resolve(),
                arguments.base,
                arguments.project_dir,
                None if arguments.tasks_dir == DEFAULT_TASKS_DIR else arguments.tasks_dir,
            )
        else:
            result = validate_task_briefs(
                arguments.repo.resolve(), arguments.base, arguments.tasks_dir
            )
    except BriefError as error:
        print(f"task brief validation failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
