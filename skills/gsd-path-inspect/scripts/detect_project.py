#!/usr/bin/env python3
"""Classify a working tree as owned, orphan, brownfield, or greenfield.

The router, define, and inspect phases call this instead of inferring
brownfield vs greenfield from a directory listing. It does not create
STATE.md or mutate the tree.

Verdicts:

- owned — `.project/STATE.md` exists; route by that file, not detection
- orphan — no STATE.md, but `.project/` contains a file or directory
- brownfield — no STATE.md, `.project/` empty or absent, and at least one
  in-scope signal (package/build manifest, source file, tracked signal in
  git, or substantive system documentation)
- greenfield — no STATE.md, `.project/` empty or absent, and no signal

Ignored path components: `.git`, `node_modules`, vendored/generated trees,
and build output. `.project/` is never a brownfield signal; it only decides
owned vs orphan. A title-only root README is not substantive documentation
(the new-GitHub bootstrap README shape).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence


IGNORE_DIRS = {
    ".git",
    "node_modules",
    "dist",
    "build",
    "out",
    "target",
    "vendor",
    ".venv",
    "venv",
    "__pycache__",
    ".next",
    "coverage",
    ".turbo",
    ".cache",
    "generated",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "bower_components",
}

MANIFEST_NAMES = {
    "package.json",
    "pnpm-workspace.yaml",
    "lerna.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements.txt",
    "Pipfile",
    "Cargo.toml",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "settings.gradle",
    "settings.gradle.kts",
    "CMakeLists.txt",
    "Makefile",
    "makefile",
    "meson.build",
    "composer.json",
    "mix.exs",
    "Package.swift",
    "deno.json",
    "deno.jsonc",
    "flake.nix",
    "WORKSPACE",
    "WORKSPACE.bazel",
    "MODULE.bazel",
    "pubspec.yaml",
}

MANIFEST_SUFFIXES = {".csproj", ".fsproj", ".vbproj", ".sln"}

SOURCE_SUFFIXES = {
    ".py",
    ".pyi",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".cjs",
    ".go",
    ".rs",
    ".java",
    ".kt",
    ".kts",
    ".scala",
    ".rb",
    ".php",
    ".cs",
    ".fs",
    ".swift",
    ".m",
    ".mm",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hpp",
    ".hxx",
    ".lua",
    ".ex",
    ".exs",
    ".erl",
    ".hs",
    ".ml",
    ".mli",
    ".clj",
    ".cljs",
    ".dart",
    ".zig",
    ".nim",
    ".vue",
    ".svelte",
    ".r",
    ".jl",
}

MARKDOWN_SUFFIXES = {".md", ".mdx", ".markdown"}

NON_SYSTEM_DOC_STEMS = {
    "license",
    "licence",
    "copying",
    "code-of-conduct",
    "code_of_conduct",
    "security",
    "contributing",
    "changelog",
    "changes",
    "authors",
    "notice",
    "patents",
    "credits",
    "maintainers",
    "codeowners",
}

PIPELINE_LINE = re.compile(r"^pipeline:\s*(\S+)", re.MULTILINE)


class DetectError(RuntimeError):
    pass


def posix_relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def is_ignored(relative: str) -> bool:
    return any(part in IGNORE_DIRS for part in Path(relative).parts)


def markdown_has_body(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("<!--") or stripped.endswith("-->"):
            continue
        if set(stripped) <= set("-*_ "):
            continue
        return True
    return False


def file_kind(relative: str, root: Path, *, require_doc_body: bool) -> Optional[str]:
    if is_ignored(relative) or relative == ".project" or relative.startswith(".project/"):
        return None
    path = root / relative
    name = Path(relative).name
    stem = Path(name).stem.casefold()
    suffix = Path(name).suffix
    if name in MANIFEST_NAMES or suffix in MANIFEST_SUFFIXES:
        return "manifest"
    if suffix.casefold() in SOURCE_SUFFIXES:
        return "source"
    if suffix.casefold() in MARKDOWN_SUFFIXES and stem not in NON_SYSTEM_DOC_STEMS:
        if require_doc_body and path.is_file() and not markdown_has_body(path):
            return None
        if require_doc_body and not path.is_file():
            return None
        return "docs"
    return None


def iter_worktree_files(root: Path) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(dirpath)
        relative_dir = "" if current.resolve() == root else posix_relative(current, root)
        dirnames[:] = [
            name
            for name in dirnames
            if name not in IGNORE_DIRS
            and name != ".project"
            and not (current / name).is_symlink()
        ]
        for name in filenames:
            path = current / name
            if path.is_symlink() or not path.is_file():
                continue
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if not is_ignored(relative):
                yield relative


def git_tracked_files(root: Path) -> tuple[str, ...]:
    git_dir = root / ".git"
    if not git_dir.exists():
        return ()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return ()
    return tuple(
        path.replace("\\", "/")
        for path in result.stdout.decode("utf-8", "replace").split("\0")
        if path and not is_ignored(path)
    )


def occupied_project_paths(project: Path, root: Path) -> tuple[str, ...]:
    if not project.exists():
        return ()
    try:
        next(project.iterdir())
    except StopIteration:
        return ()
    except OSError:
        return (posix_relative(project, root),)
    paths = []
    for dirpath, dirnames, filenames in os.walk(project, followlinks=False):
        dirnames[:] = [name for name in dirnames if not (Path(dirpath) / name).is_symlink()]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink():
                continue
            paths.append(posix_relative(path, root))
        if not filenames and not dirnames and Path(dirpath) != project:
            paths.append(posix_relative(Path(dirpath), root))
    if not paths:
        return tuple(
            sorted(
                posix_relative(project / name, root) for name in os.listdir(project)
            )
        )
    return tuple(sorted(paths))


def pipeline_marker(state: Path) -> Optional[str]:
    try:
        text = state.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    match = PIPELINE_LINE.search(text)
    return match.group(1) if match else None


def classify(repo: Path) -> dict:
    root = repo.resolve()
    if not root.is_dir():
        raise DetectError(f"repo is not a directory: {root}")
    project = root / ".project"
    state = project / "STATE.md"
    if state.exists():
        return {
            "verdict": "owned",
            "pipeline": pipeline_marker(state),
            "signals": [],
            "orphan_paths": [],
            "route": "existing-state",
        }
    orphan_paths = occupied_project_paths(project, root)
    if orphan_paths:
        return {
            "verdict": "orphan",
            "pipeline": None,
            "signals": [],
            "orphan_paths": list(orphan_paths),
            "route": "recover-orphan",
        }
    signals = []
    seen = set()
    for relative in iter_worktree_files(root):
        kind = file_kind(relative, root, require_doc_body=True)
        if kind is None:
            continue
        item = (kind, relative)
        if item in seen:
            continue
        seen.add(item)
        signals.append({"kind": kind, "path": relative})
    for relative in git_tracked_files(root):
        kind = file_kind(relative, root, require_doc_body=True)
        if kind is None:
            continue
        item = ("git", relative)
        if item in seen or (kind, relative) in seen:
            continue
        seen.add(item)
        signals.append({"kind": "git", "path": relative})
    signals.sort(key=lambda item: (item["kind"], item["path"]))
    if signals:
        return {
            "verdict": "brownfield",
            "pipeline": None,
            "signals": signals,
            "orphan_paths": [],
            "route": "inspect",
        }
    return {
        "verdict": "greenfield",
        "pipeline": None,
        "signals": [],
        "orphan_paths": [],
        "route": "define",
    }


def emit(payload: dict) -> int:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("classify",))
    result.add_argument("--repo", type=Path, required=True)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "classify":
            return emit(classify(arguments.repo))
        raise DetectError(f"unknown command: {arguments.command}")
    except DetectError as error:
        json.dump({"status": "error", "error": str(error)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
