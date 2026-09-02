#!/usr/bin/env python3
# gsd-path project runtime
"""Helpers shared by the gsd-path scripts.

Every consuming script binds the names it used before (for example
``run_git = _common.run_git``) so callers and tests that patch the name on the
consuming module keep working.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Optional

PIPELINE_MARKER = "gsd-path/v2"
BOUND_BRANCH_RE = re.compile(r"^gsd-path/M(\d{3,})$")

FIELD_PATTERN = re.compile(r"^(?P<key>[a-z_]+):\s*(?P<value>.*)$")
INLINE_LIST_PATTERN = re.compile(r"^\[(?P<body>.*)\]$")
LIST_ITEM_PATTERN = re.compile(r"^\s*-\s+(?P<value>.*)$")


def run_command(
    *arguments: str, cwd: Optional[Path] = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )


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


def atomic_replace(path: Path, temporary_path: Path, content: str) -> None:
    temporary_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()
        descriptor = os.open(
            temporary_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o666,
        )
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
        descriptor = None
        with handle:
            handle.write(content)
        os.replace(temporary_path, path)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path.exists() or temporary_path.is_symlink():
            temporary_path.unlink()


def atomic_write(path: Path, content: str) -> None:
    atomic_replace(path, path.parent / f".{path.name}.gsd-path-tmp", content)


def strip_yaml_comment(value: str) -> str:
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


def unquote(value: str) -> str:
    cleaned = strip_yaml_comment(value).strip()
    if (
        len(cleaned) >= 2
        and cleaned[0] == cleaned[-1]
        and cleaned[0] in {"'", '"'}
    ):
        return cleaned[1:-1]
    return cleaned
