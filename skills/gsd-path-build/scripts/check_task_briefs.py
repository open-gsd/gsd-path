#!/usr/bin/env python3
"""Lint build task briefs against the layer base before dispatch."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Sequence, Set, Tuple


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
FIELD_PATTERN = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*)$")
INLINE_LIST_PATTERN = re.compile(r"^\[(?P<body>.*)\]$")
LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<value>.*)$")
HEADING_PATTERN = re.compile(r"(?m)^## (?P<name>.+?)\s*$")
COMMENT_PATTERN = re.compile(r"<!--.*?-->", re.DOTALL)
BACKTICK_PATTERN = re.compile(r"`([^`\n]+)`")
PATH_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9._~/-]+")
VERIFY_BLOCK_PATTERN = re.compile(r"```bash[ \t]*\n(?P<block>.*?)```", re.DOTALL)


class BriefError(RuntimeError):
    """Raised when task briefs fail the layer-prep lint or inputs are unusable."""


def _run_git(repo: Path, *arguments: str) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )


def _resolve_base(repo: Path, base: str) -> str:
    result = _run_git(repo, "rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    if result.returncode != 0:
        raise BriefError(f"--base does not resolve to a commit: {base}")
    return result.stdout.strip()


def _base_exists(repo: Path, base: str, path: str) -> bool:
    return _run_git(repo, "cat-file", "-e", f"{base}:{path}").returncode == 0


def _strip_yaml_comment(value: str) -> str:
    quote: Optional[str] = None
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
        elif character in {"'", '"'}:
            quote = character
        elif character == "#" and (index == 0 or value[index - 1].isspace()):
            return value[:index].rstrip()
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


def _looks_like_path(token: str) -> bool:
    return (
        "/" in token
        and PATH_TOKEN_PATTERN.fullmatch(token) is not None
        and "://" not in token
        and not token.startswith("-")
        and "<" not in token
        and ">" not in token
    )


def _normalize(path: str) -> str:
    return str(PurePosixPath(path))


def _prose_tokens(body: str) -> List[str]:
    cleaned = COMMENT_PATTERN.sub("", body)
    return [
        _normalize(match.group(1).strip())
        for match in BACKTICK_PATTERN.finditer(cleaned)
        if _looks_like_path(match.group(1).strip())
    ]


def _verify_tokens(block: str) -> List[str]:
    tokens = []
    for line in block.splitlines():
        parts = line.split()
        for token in parts[1:]:
            token = token.strip("\"'")
            if _looks_like_path(token):
                tokens.append(_normalize(token))
    return tokens


def _lint_task(repo: Path, base: str, path: Path) -> Tuple[str, List[str], Optional[str], int]:
    text = path.read_text(encoding="utf-8")
    fields, error = _frontmatter(text)
    task_id = path.stem
    if fields and isinstance(fields.get("id"), str):
        task_id = fields["id"]  # type: ignore[assignment]
    problems: List[str] = []
    checked = 0
    if fields is None:
        return task_id, [error or "invalid frontmatter"], None, checked

    for field in REQUIRED_FIELDS:
        if field not in fields:
            problems.append(f"missing frontmatter field: {field}")

    sections = _sections(text)
    for name in REQUIRED_SECTIONS:
        body = sections.get(name)
        if body is None:
            problems.append(f"missing ## {name} section")
        elif not _clean(body):
            problems.append(f"## {name} section is empty")

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
            parent = str(candidate.parent)
            checked += 1
            if parent != "." and not _base_exists(repo, base, parent):
                problems.append(
                    f"files entry {normalized} has no parent directory {parent} "
                    "at the layer base"
                )

    for name in PROSE_SECTIONS:
        body = sections.get(name)
        if body is None or not _clean(body):
            continue
        for token in _prose_tokens(body):
            checked += 1
            if token not in declared and not _base_exists(repo, base, token):
                problems.append(f"## {name} names a path missing at the layer base: {token}")

    verify_body = sections.get("Verify")
    if verify_body is not None and _clean(verify_body):
        block = VERIFY_BLOCK_PATTERN.search(verify_body)
        if block is None or not block.group("block").strip():
            problems.append("## Verify must contain a non-empty fenced bash block")
        else:
            for token in _verify_tokens(block.group("block")):
                checked += 1
                if token not in declared and not _base_exists(repo, base, token):
                    problems.append(f"## Verify names a path missing at the layer base: {token}")

    contract = None
    contract_body = sections.get("Interface contract")
    if contract_body is not None:
        normalized = " ".join(_clean(contract_body).split())
        if normalized and normalized not in {"None", "- None"}:
            contract = normalized

    return task_id, problems, contract, checked


def validate_task_briefs(
    root: Path, base: str, tasks_dir: str = DEFAULT_TASKS_DIR
) -> Dict[str, object]:
    """Lint every task brief in tasks_dir against the layer base commit."""

    resolved_base = _resolve_base(root, base)
    tasks_path = root / tasks_dir
    if not tasks_path.is_dir():
        raise BriefError(f"tasks directory not found: {tasks_dir}")

    problems: List[str] = []
    contracts: Dict[str, str] = {}
    checked = 0
    task_files = sorted(tasks_path.glob("*.md"))
    if not task_files:
        raise BriefError(f"no task briefs found in {tasks_dir}")
    for path in task_files:
        task_id, task_problems, contract, task_checked = _lint_task(
            root, resolved_base, path
        )
        problems.extend(f"{task_id}: {problem}" for problem in task_problems)
        if contract is not None:
            contracts[task_id] = contract
        checked += task_checked

    for task_id, contract in contracts.items():
        if sum(1 for other in contracts.values() if other == contract) < 2:
            problems.append(
                f"{task_id}: interface contract is not shared by any other task"
            )

    if problems:
        raise BriefError("\n".join(problems))
    return {"base": resolved_base, "checked": checked, "tasks": len(task_files)}


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
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
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
