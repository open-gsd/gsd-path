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
build output, and managed GSD Path installation artifacts. `.project/` is
never a brownfield signal; it only decides owned vs orphan. A title-only root
README, with or without a Markdown suffix, is not substantive documentation.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path, PurePosixPath, PureWindowsPath
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

GREENFIELD_DOC_STEMS = {
    "license",
    "licence",
    "copying",
}

MANAGED_EXACT_FILES = {
    "AGENTS.md",
    "WORKFLOW.md",
    ".claude/CLAUDE.md",
}

PIPELINE_LINE = re.compile(r"^pipeline:\s*(\S+)", re.MULTILINE)
ATX_TITLE = re.compile(r" {0,3}#{1,6}(?:[ \t]+.*)?")
SETEXT_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
MANAGED_BACKUP = re.compile(r"disabled-gsd-skills(?:-\d+)?")
SETEXT_BLOCK_START = re.compile(
    r" {0,3}(?:>|[-+*](?:[ \t]+|$)|\d{1,9}[.)](?:[ \t]+|$)|"
    r"`{3,}|~{3,}|\[[^]]+\]:)"
)
HTML_BLOCK_START = re.compile(
    r" {0,3}(?:"
    r"<(?:script|pre|style|textarea)(?:[ \t]+|>|$)"
    r"|<!--|<\?|<![A-Z]|<!\[CDATA\["
    r"|</?(?:address|article|aside|base|basefont|blockquote|body|caption|center|"
    r"col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|figure|"
    r"footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|li|"
    r"link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|"
    r"section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)"
    r"(?:[ \t]+|/?>|$)"
    r"|</?[A-Za-z][A-Za-z0-9-]*(?:[ \t]+[^>]*)?/?>[ \t]*$)",
    re.IGNORECASE,
)
ANCHORED_EVIDENCE_SUPPORTED = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)


class DetectError(RuntimeError):
    pass


def posix_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_ignored(relative: str) -> bool:
    return any(part in IGNORE_DIRS for part in PurePosixPath(relative).parts)


def is_managed_pipeline_path(parts: tuple[str, ...], *, descendant: bool) -> bool:
    return any(
        (
            MANAGED_BACKUP.fullmatch(part)
            and (not descendant or index + 1 < len(parts))
        )
        or (
            (
                part.casefold() in ("ogsd", "gsd-path")
                or part.casefold().startswith(("ogsd-", "gsd-path-"))
            )
            and (not descendant or index + 1 < len(parts))
        )
        for index, part in enumerate(parts)
    )


def is_managed_pipeline_directory(relative: str) -> bool:
    return is_managed_pipeline_path(
        PurePosixPath(relative).parts,
        descendant=False,
    )


def is_managed_pipeline_artifact(relative: str) -> bool:
    parts = PurePosixPath(relative).parts
    if relative in MANAGED_EXACT_FILES or is_managed_pipeline_path(
        parts,
        descendant=True,
    ):
        return True
    if (
        len(parts) >= 2
        and parts[-2].casefold() == "agents"
        and parts[-1].casefold() == "gsd-path.md"
    ):
        return True
    return (
        len(parts) == 2
        and parts[0] == ".gsd-path"
        and PurePosixPath(parts[1]).suffix.casefold() == ".py"
    )


def lstat_evidence(path: Path, *, missing_ok: bool) -> Optional[os.stat_result]:
    try:
        return os.lstat(path)
    except FileNotFoundError as error:
        if missing_ok:
            return None
        raise DetectError(f"filesystem evidence disappeared: {path}") from error
    except OSError as error:
        raise DetectError(
            f"cannot inspect filesystem evidence: {path}: {error}"
        ) from error


def read_regular_evidence(
    path: Path,
    root: Path,
    *,
    missing_ok: bool,
    evidence_name: str,
) -> Optional[str]:
    try:
        relative = path.relative_to(root)
    except ValueError as error:
        raise DetectError(
            f"{evidence_name} evidence escapes repo: {path}"
        ) from error
    if not relative.parts:
        raise DetectError(f"{evidence_name} evidence path is empty: {path}")
    if not ANCHORED_EVIDENCE_SUPPORTED:
        raise DetectError(
            f"secure {evidence_name} evidence reads are unavailable"
        )
    directory_flags = (
        os.O_RDONLY
        | os.O_DIRECTORY
        | os.O_NOFOLLOW
        | getattr(os, "O_NONBLOCK", 0)
    )
    file_flags = (
        os.O_RDONLY
        | os.O_NOFOLLOW
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )
    descriptors = []
    try:
        descriptors.append(os.open(root, directory_flags))
        if not stat.S_ISDIR(os.fstat(descriptors[-1]).st_mode):
            raise DetectError(f"repo evidence is not a directory: {root}")
        for index, part in enumerate(relative.parts):
            current = root.joinpath(*relative.parts[: index + 1])
            expected = os.stat(
                part,
                dir_fd=descriptors[-1],
                follow_symlinks=False,
            )
            if stat.S_ISLNK(expected.st_mode):
                raise DetectError(
                    f"symlinked {evidence_name} evidence is not allowed: {current}"
                )
            final = index == len(relative.parts) - 1
            if not final and not stat.S_ISDIR(expected.st_mode):
                raise DetectError(
                    f"{evidence_name} evidence parent is not a directory: {current}"
                )
            if final and not stat.S_ISREG(expected.st_mode):
                raise DetectError(
                    f"{evidence_name} evidence is not a regular file: {current}"
                )
            flags = file_flags if final else directory_flags
            descriptor = os.open(part, flags, dir_fd=descriptors[-1])
            descriptors.append(descriptor)
            actual = os.fstat(descriptor)
            expected_kind = stat.S_ISREG if final else stat.S_ISDIR
            if not expected_kind(actual.st_mode) or not os.path.samestat(
                expected,
                actual,
            ):
                raise DetectError(
                    f"{evidence_name} evidence changed while reading: {current}"
                )
        with os.fdopen(descriptors.pop(), "rb") as stream:
            data = stream.read()
    except FileNotFoundError as error:
        if missing_ok:
            return None
        raise DetectError(f"filesystem evidence disappeared: {path}") from error
    except DetectError:
        raise
    except OSError as error:
        raise DetectError(f"cannot read {evidence_name} evidence: {path}") from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError(f"cannot read {evidence_name} evidence: {path}") from error


def is_thematic_break(line: str) -> bool:
    leading = len(line) - len(line.lstrip(" "))
    if leading > 3:
        return False
    compact = re.sub(r"[ \t]", "", line[leading:])
    return (
        len(compact) >= 3
        and compact[0] in "*-_"
        and all(character == compact[0] for character in compact)
    )


def is_setext_title(line: str) -> bool:
    indentation = line[: len(line) - len(line.lstrip(" \t"))]
    return not (
        len(indentation) > 3
        or "\t" in indentation
        or ATX_TITLE.fullmatch(line)
        or SETEXT_UNDERLINE.fullmatch(line)
        or SETEXT_BLOCK_START.match(line)
        or HTML_BLOCK_START.match(line)
        or is_thematic_break(line)
    )


def strip_standalone_html_comments(text: str) -> str:
    output = []
    in_comment = False
    for line in text.splitlines(keepends=True):
        remaining = line
        if in_comment:
            closing = remaining.find("-->")
            if closing < 0:
                continue
            remaining = remaining[closing + 3 :]
            in_comment = False
        while True:
            stripped = remaining.lstrip(" ")
            indentation = len(remaining) - len(stripped)
            if indentation > 3 or not stripped.startswith("<!--"):
                break
            closing = stripped.find("-->", 4)
            if closing < 0:
                in_comment = True
                remaining = ""
                break
            remaining = stripped[closing + 3 :]
        if remaining.strip():
            output.append(remaining)
        elif remaining and not in_comment:
            output.append(remaining)
    return "".join(output)


def markdown_has_body(text: str) -> bool:
    lines = [
        line.rstrip()
        for line in strip_standalone_html_comments(text).splitlines()
    ]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return False
    if len(lines) == 1 and ATX_TITLE.fullmatch(lines[0]):
        return False
    if (
        len(lines) >= 2
        and all(line.strip() for line in lines)
        and SETEXT_UNDERLINE.fullmatch(lines[-1])
        and all(is_setext_title(line) for line in lines[:-1])
    ):
        return False
    return True


def file_kind(relative: str, root: Path, *, tracked: bool) -> Optional[str]:
    if (
        is_ignored(relative)
        or is_managed_pipeline_artifact(relative)
        or relative == ".project"
        or relative.startswith(".project/")
    ):
        return None
    relative_path = PurePosixPath(relative)
    path = root.joinpath(*relative_path.parts)
    name = relative_path.name
    stem = PurePosixPath(name).stem.casefold()
    suffix = PurePosixPath(name).suffix
    if name in MANIFEST_NAMES or suffix in MANIFEST_SUFFIXES:
        return "manifest"
    if suffix.casefold() in SOURCE_SUFFIXES:
        return "source"
    if (
        suffix.casefold() in MARKDOWN_SUFFIXES or name.casefold() == "readme"
    ) and stem not in GREENFIELD_DOC_STEMS:
        text = read_regular_evidence(
            path,
            root,
            missing_ok=tracked,
            evidence_name="Markdown",
        )
        if text is None:
            return None
        if not markdown_has_body(text):
            return None
        return "docs"
    return None


def raise_walk_error(error: OSError) -> None:
    raise DetectError(f"cannot traverse filesystem evidence: {error}") from error


def iter_worktree_files(root: Path) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        current = Path(dirpath)
        relative_dir = "" if current == root else posix_relative(current, root)
        kept_directories = []
        for name in dirnames:
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if (
                is_ignored(relative)
                or name == ".project"
                or is_managed_pipeline_directory(relative)
            ):
                continue
            status = lstat_evidence(current / name, missing_ok=False)
            if stat.S_ISLNK(status.st_mode):
                continue
            if not stat.S_ISDIR(status.st_mode):
                raise DetectError(f"walk entry is not a directory: {current / name}")
            kept_directories.append(name)
        dirnames[:] = kept_directories
        for name in filenames:
            path = current / name
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if is_ignored(relative) or is_managed_pipeline_artifact(relative):
                continue
            status = lstat_evidence(path, missing_ok=False)
            if stat.S_ISLNK(status.st_mode) or not stat.S_ISREG(status.st_mode):
                continue
            yield relative


def validated_git_path(relative: str) -> str:
    path = PurePosixPath(relative)
    if (
        relative == "."
        or path.is_absolute()
        or ".." in path.parts
        or (
            os.sep != "/"
            and (os.sep in relative or PureWindowsPath(relative).drive)
        )
    ):
        raise DetectError(f"git ls-files returned unsafe path: {relative!r}")
    return relative


def git_tracked_files(root: Path) -> tuple[str, ...]:
    git_dir = root / ".git"
    if lstat_evidence(git_dir, missing_ok=True) is None:
        return ()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
    except OSError as error:
        raise DetectError(f"git ls-files failed: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise DetectError(f"git ls-files failed{suffix}")
    try:
        tracked = result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError("git ls-files returned non-UTF-8 paths") from error
    paths = []
    for raw in tracked.split("\0"):
        if not raw:
            continue
        relative = validated_git_path(raw)
        if not is_ignored(relative):
            paths.append(relative)
    return tuple(paths)


def occupied_project_paths(project: Path, root: Path) -> tuple[str, ...]:
    project_status = lstat_evidence(project, missing_ok=True)
    if project_status is None:
        return ()
    if stat.S_ISLNK(project_status.st_mode) or not stat.S_ISDIR(
        project_status.st_mode
    ):
        return (posix_relative(project, root),)
    try:
        next(project.iterdir())
    except StopIteration:
        return ()
    except OSError:
        return (posix_relative(project, root),)
    paths = []
    for dirpath, dirnames, filenames in os.walk(
        project,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        current = Path(dirpath)
        linked_directories = []
        for name in dirnames:
            status = lstat_evidence(current / name, missing_ok=False)
            if stat.S_ISLNK(status.st_mode):
                linked_directories.append(name)
        paths.extend(
            posix_relative(current / name, root) for name in linked_directories
        )
        dirnames[:] = [name for name in dirnames if name not in linked_directories]
        for name in filenames:
            paths.append(posix_relative(current / name, root))
        if not filenames and not dirnames and current != project:
            paths.append(posix_relative(current, root))
    if not paths:
        try:
            names = os.listdir(project)
        except OSError as error:
            raise DetectError(
                f"cannot list project evidence: {project}: {error}"
            ) from error
        return tuple(sorted(posix_relative(project / name, root) for name in names))
    return tuple(sorted(paths))


def pipeline_marker(state: Path, root: Path) -> Optional[str]:
    text = read_regular_evidence(
        state,
        root,
        missing_ok=False,
        evidence_name="state",
    )
    if text is None:
        raise DetectError(f"filesystem evidence disappeared: {state}")
    match = PIPELINE_LINE.search(text)
    return match.group(1) if match else None


def classify(repo: Path) -> dict:
    root = repo.resolve()
    root_status = lstat_evidence(root, missing_ok=True)
    if root_status is None or not stat.S_ISDIR(root_status.st_mode):
        raise DetectError(f"repo is not a directory: {root}")
    project = root / ".project"
    state = project / "STATE.md"
    project_status = lstat_evidence(project, missing_ok=True)
    if project_status is not None and stat.S_ISDIR(project_status.st_mode):
        state_status = lstat_evidence(state, missing_ok=True)
        if state_status is not None and stat.S_ISREG(state_status.st_mode):
            return {
                "verdict": "owned",
                "pipeline": pipeline_marker(state, root),
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
        kind = file_kind(relative, root, tracked=False)
        if kind is None:
            continue
        item = (kind, relative)
        if item in seen:
            continue
        seen.add(item)
        signals.append({"kind": kind, "path": relative})
    for relative in git_tracked_files(root):
        kind = file_kind(relative, root, tracked=True)
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
