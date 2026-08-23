#!/usr/bin/env python3
"""Classify or initialize a working tree.

The router, define, and inspect phases call this instead of inferring
brownfield vs greenfield from a directory listing. classify is read-only.
initialize creates .project/STATE.md after classifying a new brownfield or
greenfield project.

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
from datetime import date
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Iterable, NamedTuple, Optional, Sequence


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

VERIFIED_INSTALLER_SKILL_ROOTS = {
    (".agents", "skills"),
    (".claude", "skills"),
    (".cursor", "skills"),
    (".github", "skills"),
    (".grok", "skills"),
    (".kiro", "skills"),
    (".kimi-code", "skills"),
    (".opencode", "skills"),
    (".qwen", "skills"),
}

PIPELINE_LINE = re.compile(r"^pipeline:\s*(\S+)", re.MULTILINE)
ATX_TITLE = re.compile(r" {0,3}#{1,6}(?:[ \t]+.*)?")
SETEXT_UNDERLINE = re.compile(r" {0,3}(?:=+|-+)[ \t]*")
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
REPARSE_NAME_SURROGATE = 0x20000000
ANCHORED_EVIDENCE_SUPPORTED = (
    hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
    and os.open in os.supports_dir_fd
    and os.stat in os.supports_dir_fd
    and os.stat in os.supports_follow_symlinks
)
LISTDIR_DIR_FD_SUPPORTED = os.listdir in getattr(os, "supports_fd", ())
ANCHORED_STATE_CREATE_SUPPORTED = (
    ANCHORED_EVIDENCE_SUPPORTED
    and LISTDIR_DIR_FD_SUPPORTED
    and os.mkdir in getattr(os, "supports_dir_fd", ())
    and os.unlink in getattr(os, "supports_dir_fd", ())
)
GIT_OVERRIDE_VARS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_PREFIX",
    "GIT_NAMESPACE",
)


class DetectError(RuntimeError):
    pass


class GitIndexEntry(NamedTuple):
    path: str
    mode: int
    oid: str
    stage: int


def is_link_like_status(status: os.stat_result) -> bool:
    if stat.S_ISLNK(status.st_mode):
        return True
    if getattr(status, "st_reparse_tag", 0) & REPARSE_NAME_SURROGATE:
        return True
    return False


def is_link_like(path: Path, status: os.stat_result) -> bool:
    if is_link_like_status(status):
        return True
    isjunction = getattr(os.path, "isjunction", None)
    if os.name != "nt" or isjunction is None:
        return False
    try:
        return bool(isjunction(path))
    except OSError as error:
        raise DetectError(f"cannot inspect link-like evidence: {path}: {error}") from error


def posix_relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def is_ignored(relative: str) -> bool:
    return any(part in IGNORE_DIRS for part in PurePosixPath(relative).parts)


def is_skill_bundle_name(name: str) -> bool:
    folded = name.casefold()
    return folded in {"ogsd", "gsd-path"} or folded.startswith(("ogsd-", "gsd-path-"))


def is_verified_installer_bundle(parts: tuple[str, ...]) -> bool:
    parent = tuple(part.casefold() for part in parts[:-1])
    return parent in VERIFIED_INSTALLER_SKILL_ROOTS


def has_safe_bundle_path(root: Path, parts: tuple[str, ...]) -> bool:
    current = root
    for part in parts:
        current /= part
        status = lstat_evidence(current, missing_ok=True)
        if (
            status is None
            or is_link_like(current, status)
            or not stat.S_ISDIR(status.st_mode)
        ):
            return False
    return True


def is_verified_skill_bundle(relative: str, root: Path) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts:
        return False
    name = parts[-1]
    if not is_skill_bundle_name(name):
        return False
    if not has_safe_bundle_path(root, parts):
        return False
    if is_verified_installer_bundle(parts):
        return True
    skill = root.joinpath(*parts) / "SKILL.md"
    status = lstat_evidence(skill, missing_ok=True)
    return status is not None and stat.S_ISREG(status.st_mode)


def is_managed_pipeline_directory(relative: str, root: Path) -> bool:
    return is_verified_skill_bundle(relative, root)


def is_verified_skill_bundle_at(relative: str, directory_fd: int) -> bool:
    parts = PurePosixPath(relative).parts
    if not parts or not is_skill_bundle_name(parts[-1]):
        return False
    if is_verified_installer_bundle(parts):
        return True
    try:
        status = os.stat(
            "SKILL.md",
            dir_fd=directory_fd,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return False
    except OSError as error:
        raise DetectError(
            f"cannot inspect managed skill bundle: {relative}: {error}"
        ) from error
    return not is_link_like_status(status) and stat.S_ISREG(status.st_mode)


def is_fixed_managed_pipeline_artifact(relative: str) -> bool:
    if relative in MANAGED_EXACT_FILES:
        return True
    parts = PurePosixPath(relative).parts
    if (
        len(parts) >= 2
        and parts[-2].casefold() == "agents"
        and parts[-1].casefold() == "gsd-path.md"
    ):
        return True
    if (
        len(parts) == 2
        and parts[0] == ".gsd-path"
        and PurePosixPath(parts[1]).suffix.casefold() == ".py"
    ):
        return True
    return False


def is_managed_pipeline_artifact(relative: str, root: Path) -> bool:
    if is_fixed_managed_pipeline_artifact(relative):
        return True
    parts = PurePosixPath(relative).parts
    return any(
        is_verified_skill_bundle("/".join(parts[:end]), root)
        for end in range(1, len(parts))
    )


def git_environment() -> dict[str, str]:
    env = os.environ.copy()
    for key in GIT_OVERRIDE_VARS:
        env.pop(key, None)
    env["GIT_NO_LAZY_FETCH"] = "1"
    env["GIT_NO_REPLACE_OBJECTS"] = "1"
    return env


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
    if ANCHORED_EVIDENCE_SUPPORTED:
        return read_anchored_evidence(
            relative,
            root,
            missing_ok=missing_ok,
            evidence_name=evidence_name,
        )
    return read_lstat_open_evidence(
        relative,
        root,
        missing_ok=missing_ok,
        evidence_name=evidence_name,
    )


def directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def file_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
    )


def read_anchored_evidence(
    relative: Path,
    root: Path,
    *,
    missing_ok: bool,
    evidence_name: str,
) -> Optional[str]:
    directory_open = directory_flags()
    file_open = file_flags()
    descriptors = []
    try:
        descriptors.append(os.open(root, directory_open))
        if not stat.S_ISDIR(os.fstat(descriptors[-1]).st_mode):
            raise DetectError(f"repo evidence is not a directory: {root}")
        for index, part in enumerate(relative.parts):
            current = root.joinpath(*relative.parts[: index + 1])
            expected = os.stat(
                part,
                dir_fd=descriptors[-1],
                follow_symlinks=False,
            )
            if is_link_like(current, expected):
                raise DetectError(
                    f"link-like {evidence_name} evidence is not allowed: {current}"
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
            flags = file_open if final else directory_open
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
        raise DetectError(f"filesystem evidence disappeared: {root / relative}") from error
    except DetectError:
        raise
    except OSError as error:
        raise DetectError(
            f"cannot read {evidence_name} evidence: {root / relative}"
        ) from error
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError(
            f"cannot read {evidence_name} evidence: {root / relative}"
        ) from error


def read_lstat_open_evidence(
    relative: Path,
    root: Path,
    *,
    missing_ok: bool,
    evidence_name: str,
) -> Optional[str]:
    current = root
    expected = None
    try:
        for index, part in enumerate(relative.parts):
            current = current / part
            expected = os.stat(current, follow_symlinks=False)
            if is_link_like(current, expected):
                raise DetectError(
                    f"link-like {evidence_name} evidence is not allowed: {current}"
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
        descriptor = os.open(current, file_flags())
        try:
            actual = os.fstat(descriptor)
            if not stat.S_ISREG(actual.st_mode) or not os.path.samestat(
                expected,
                actual,
            ):
                raise DetectError(
                    f"{evidence_name} evidence changed while reading: {current}"
                )
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = None
                data = stream.read()
        finally:
            if descriptor is not None:
                os.close(descriptor)
    except FileNotFoundError as error:
        if missing_ok:
            return None
        raise DetectError(f"filesystem evidence disappeared: {current}") from error
    except DetectError:
        raise
    except OSError as error:
        raise DetectError(f"cannot read {evidence_name} evidence: {current}") from error
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError(f"cannot read {evidence_name} evidence: {current}") from error


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


def normalize_html_comments(text: str) -> tuple[str, bool]:
    output = []
    in_comment = False
    shares_content_line = False
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        ending = line[len(content) :]
        indentation = content[: len(content) - len(content.lstrip(" \t"))]
        if not in_comment and (len(indentation) > 3 or "\t" in indentation):
            output.append(line)
            continue
        visible = []
        cursor = 0
        line_has_comment = in_comment
        while cursor < len(content):
            if in_comment:
                closing = content.find("-->", cursor)
                if closing < 0:
                    cursor = len(content)
                    continue
                cursor = closing + 3
                in_comment = False
                continue
            opening = content.find("<!--", cursor)
            if opening < 0:
                visible.append(content[cursor:])
                cursor = len(content)
                continue
            line_has_comment = True
            visible.append(content[cursor:opening])
            cursor = opening + 4
            in_comment = True
        visible_line = "".join(visible)
        if line_has_comment and visible_line.strip():
            shares_content_line = True
        output.append(visible_line)
        if ending:
            output.append(ending)
        elif line_has_comment and not visible_line:
            output.append("\n")
    return "".join(output), shares_content_line


def markdown_has_body(text: str) -> bool:
    normalized, comment_shares_content = normalize_html_comments(text)
    if comment_shares_content:
        return True
    lines = [line.rstrip() for line in normalized.splitlines()]
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


def file_kind(
    relative: str,
    root: Path,
    *,
    tracked: bool,
    index_oid: Optional[str] = None,
) -> Optional[str]:
    if (
        is_ignored(relative)
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
        if text is None and tracked:
            if index_oid is None:
                raise DetectError(f"missing staged Markdown blob identity: {relative}")
            text = read_git_index_blob(root, relative, index_oid)
        if text is None:
            return None
        if not markdown_has_body(text):
            return None
        return "docs"
    return None


def read_git_index_blob(root: Path, relative: str, oid: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "cat-file", "blob", oid],
            capture_output=True,
            check=False,
            env=git_environment(),
        )
    except OSError as error:
        raise DetectError(f"git cat-file failed: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise DetectError(
            f"cannot read staged Markdown evidence: {relative}{suffix}"
        )
    try:
        return result.stdout.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError(f"cannot read Markdown evidence: {relative}") from error


def parse_git_index_record(raw: bytes) -> GitIndexEntry:
    try:
        metadata, encoded_path = raw.split(b"\t", 1)
        encoded_mode, encoded_oid, encoded_stage = metadata.split(b" ")
    except ValueError as error:
        raise DetectError("git ls-files returned malformed staged data") from error
    if (
        re.fullmatch(rb"[0-7]{6}", encoded_mode) is None
        or re.fullmatch(rb"[0-9a-fA-F]+", encoded_oid) is None
        or re.fullmatch(rb"[0-3]", encoded_stage) is None
    ):
        raise DetectError("git ls-files returned malformed staged data")
    try:
        relative = encoded_path.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DetectError("git ls-files returned non-UTF-8 paths") from error
    return GitIndexEntry(
        path=validated_git_path(relative),
        mode=int(encoded_mode, 8),
        oid=encoded_oid.decode("ascii").lower(),
        stage=int(encoded_stage),
    )


def raise_walk_error(error: OSError) -> None:
    raise DetectError(f"cannot traverse filesystem evidence: {error}") from error


def iter_worktree_files(root: Path) -> Iterable[str]:
    if ANCHORED_EVIDENCE_SUPPORTED and LISTDIR_DIR_FD_SUPPORTED:
        yield from iter_worktree_files_anchored(root)
        return
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
                or is_managed_pipeline_directory(relative, root)
            ):
                continue
            path = current / name
            status = lstat_evidence(path, missing_ok=False)
            if is_link_like(path, status):
                continue
            if not stat.S_ISDIR(status.st_mode):
                raise DetectError(f"walk entry is not a directory: {path}")
            kept_directories.append(name)
        dirnames[:] = kept_directories
        for name in filenames:
            path = current / name
            relative = f"{relative_dir}/{name}" if relative_dir else name
            if is_ignored(relative) or is_managed_pipeline_artifact(relative, root):
                continue
            status = lstat_evidence(path, missing_ok=False)
            if is_link_like(path, status) or not stat.S_ISREG(status.st_mode):
                continue
            yield relative


def iter_worktree_files_anchored(root: Path) -> Iterable[str]:
    flags = directory_flags()
    try:
        root_fd = os.open(root, flags)
    except OSError as error:
        raise DetectError(f"cannot traverse filesystem evidence: {error}") from error
    try:
        try:
            root_status = os.fstat(root_fd)
        except OSError as error:
            raise DetectError(f"cannot traverse filesystem evidence: {error}") from error
        if not stat.S_ISDIR(root_status.st_mode):
            raise DetectError(f"repo evidence is not a directory: {root}")
        yield from iter_from_dir_fd(root_fd, "", root)
    finally:
        os.close(root_fd)


def iter_from_dir_fd(
    dir_fd: int, relative_dir: str, root: Path
) -> Iterable[str]:
    try:
        names = os.listdir(dir_fd)
    except OSError as error:
        raise DetectError(f"cannot traverse filesystem evidence: {error}") from error
    for name in names:
        relative = f"{relative_dir}/{name}" if relative_dir else name
        if is_ignored(relative) or name == ".project":
            continue
        path = root.joinpath(*PurePosixPath(relative).parts)
        try:
            status = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except OSError as error:
            raise DetectError(
                f"cannot inspect filesystem evidence: {relative}: {error}"
            ) from error
        if is_link_like(path, status):
            continue
        if stat.S_ISDIR(status.st_mode):
            try:
                child = os.open(name, directory_flags(), dir_fd=dir_fd)
            except OSError as error:
                raise DetectError(
                    f"cannot traverse filesystem evidence: {relative}: {error}"
                ) from error
            try:
                try:
                    actual = os.fstat(child)
                except OSError as error:
                    raise DetectError(
                        f"cannot traverse filesystem evidence: {relative}: {error}"
                    ) from error
                if not stat.S_ISDIR(actual.st_mode) or not os.path.samestat(
                    status, actual
                ):
                    raise DetectError(
                        f"filesystem evidence changed while traversing: {relative}"
                    )
                if is_verified_skill_bundle_at(relative, child):
                    continue
                yield from iter_from_dir_fd(child, relative, root)
            finally:
                os.close(child)
            continue
        if not stat.S_ISREG(status.st_mode):
            continue
        if is_fixed_managed_pipeline_artifact(relative):
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


def git_tracked_files(root: Path) -> tuple[GitIndexEntry, ...]:
    git_dir = root / ".git"
    if lstat_evidence(git_dir, missing_ok=True) is None:
        return ()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--stage", "-z"],
            capture_output=True,
            check=False,
            env=git_environment(),
        )
    except OSError as error:
        raise DetectError(f"git ls-files failed: {error}") from error
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", "replace").strip()
        suffix = f": {detail}" if detail else ""
        raise DetectError(f"git ls-files failed{suffix}")
    entries = []
    for raw in result.stdout.split(b"\0"):
        if not raw:
            continue
        entry = parse_git_index_record(raw)
        if is_ignored(entry.path):
            continue
        if entry.stage != 0:
            raise DetectError(f"git index contains unmerged entry: {entry.path}")
        if not stat.S_ISREG(entry.mode):
            continue
        entries.append(entry)
    return tuple(entries)


def occupied_project_paths(project: Path, root: Path) -> tuple[str, ...]:
    project_status = lstat_evidence(project, missing_ok=True)
    if project_status is None:
        return ()
    if is_link_like(project, project_status) or not stat.S_ISDIR(
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
            path = current / name
            status = lstat_evidence(path, missing_ok=False)
            if is_link_like(path, status):
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
    if (
        project_status is not None
        and not is_link_like(project, project_status)
        and stat.S_ISDIR(project_status.st_mode)
    ):
        state_status = lstat_evidence(state, missing_ok=True)
        if (
            state_status is not None
            and not is_link_like(state, state_status)
            and stat.S_ISREG(state_status.st_mode)
        ):
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
    for entry in git_tracked_files(root):
        relative = entry.path
        if is_managed_pipeline_artifact(relative, root):
            continue
        kind = file_kind(
            relative,
            root,
            tracked=True,
            index_oid=entry.oid,
        )
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


def project_slug(root: Path) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", root.name.casefold()).strip("-")
    return slug or "project"


def filled_state_template(template: str, slug: str, phase: str) -> str:
    if "<slug>" not in template:
        raise DetectError("state template missing slug placeholder")
    text = template.replace("<slug>", slug)
    text, count = re.subn(r"(?m)^phase: define\b", f"phase: {phase}", text, count=1)
    if count != 1:
        raise DetectError("state template missing phase: define line")
    stamp = f"{date.today().isoformat()} — {phase} — project initialized"
    text = text.replace("YYYY-MM-DD — <phase> — project initialized", stamp)
    if "<slug>" in text or "YYYY-MM-DD" in text:
        raise DetectError("state template placeholder remains")
    return text


def write_all(descriptor: int, payload: bytes) -> None:
    remaining = memoryview(payload)
    while remaining:
        written = os.write(descriptor, remaining)
        if written <= 0:
            raise DetectError("cannot create STATE.md: write made no progress")
        remaining = remaining[written:]


def rollback_created_state(
    project_fd: int,
    created_status: Optional[os.stat_result],
) -> None:
    if created_status is None:
        try:
            os.unlink("STATE.md", dir_fd=project_fd)
        except FileNotFoundError:
            return
        except OSError as error:
            raise DetectError(f"cannot roll back STATE.md: {error}") from error
        return
    try:
        current = os.stat("STATE.md", dir_fd=project_fd, follow_symlinks=False)
    except FileNotFoundError:
        return
    except OSError as error:
        raise DetectError(f"cannot roll back STATE.md: {error}") from error
    if (
        is_link_like(Path("STATE.md"), current)
        or not stat.S_ISREG(current.st_mode)
        or not os.path.samestat(created_status, current)
    ):
        return
    try:
        os.unlink("STATE.md", dir_fd=project_fd)
    except OSError as error:
        raise DetectError(f"cannot roll back STATE.md: {error}") from error


def close_file_descriptors(
    *descriptors: Optional[int],
) -> None:
    for descriptor in descriptors:
        if descriptor is None:
            continue
        try:
            os.close(descriptor)
        except OSError:
            pass


def write_state_anchored(
    root: Path,
    content: str,
    expected_root: os.stat_result,
    expected_project: Optional[os.stat_result],
) -> None:
    if not ANCHORED_STATE_CREATE_SUPPORTED:
        raise DetectError("anchored no-follow STATE.md creation is unavailable")
    payload = content.encode("utf-8")
    flags = directory_flags()
    root_fd = None
    project_fd = None
    state_fd = None
    state_created = False
    created_status = None
    try:
        try:
            root_fd = os.open(root, flags)
        except OSError as error:
            raise DetectError(
                f"cannot open repo for STATE.md creation: {error}"
            ) from error
        opened_root = os.fstat(root_fd)
        if (
            is_link_like(root, opened_root)
            or not stat.S_ISDIR(opened_root.st_mode)
            or not os.path.samestat(expected_root, opened_root)
        ):
            raise DetectError("repo changed after classification")
        if expected_project is None:
            try:
                os.mkdir(".project", dir_fd=root_fd)
            except FileExistsError as error:
                raise DetectError(".project changed after classification") from error
            except OSError as error:
                raise DetectError(f"cannot create .project: {error}") from error
        try:
            named_project = os.stat(
                ".project",
                dir_fd=root_fd,
                follow_symlinks=False,
            )
        except OSError as error:
            raise DetectError(
                f"cannot inspect .project for STATE.md creation: {error}"
            ) from error
        if is_link_like(root / ".project", named_project) or not stat.S_ISDIR(
            named_project.st_mode
        ):
            raise DetectError("cannot create state through a non-directory .project")
        try:
            project_fd = os.open(".project", flags, dir_fd=root_fd)
        except OSError as error:
            raise DetectError(
                f"cannot open .project for STATE.md creation: {error}"
            ) from error
        opened_project = os.fstat(project_fd)
        if (
            not stat.S_ISDIR(opened_project.st_mode)
            or not os.path.samestat(named_project, opened_project)
            or (
                expected_project is not None
                and not os.path.samestat(expected_project, opened_project)
            )
        ):
            raise DetectError(".project changed after classification")
        if os.listdir(project_fd):
            raise DetectError(".project changed after classification")
        create = (
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | os.O_NOFOLLOW
            | getattr(os, "O_BINARY", 0)
        )
        try:
            state_fd = os.open("STATE.md", create, 0o644, dir_fd=project_fd)
        except FileExistsError as error:
            raise DetectError("STATE.md already exists") from error
        state_created = True
        created_status = os.fstat(state_fd)
        if is_link_like(
            root / ".project" / "STATE.md", created_status
        ) or not stat.S_ISREG(created_status.st_mode):
            raise DetectError("created STATE.md is not a regular file")
        write_all(state_fd, payload)
        current_root = lstat_evidence(root, missing_ok=False)
        current_project = os.stat(
            ".project",
            dir_fd=root_fd,
            follow_symlinks=False,
        )
        current_project_fd = os.fstat(project_fd)
        current_state = os.stat(
            "STATE.md",
            dir_fd=project_fd,
            follow_symlinks=False,
        )
        if (
            is_link_like(root, current_root)
            or not os.path.samestat(opened_root, current_root)
            or is_link_like(root / ".project", current_project)
            or not stat.S_ISDIR(current_project.st_mode)
            or not os.path.samestat(opened_project, current_project)
            or not os.path.samestat(opened_project, current_project_fd)
        ):
            raise DetectError("project identity changed while creating STATE.md")
        if (
            is_link_like(root / ".project" / "STATE.md", current_state)
            or not stat.S_ISREG(current_state.st_mode)
            or not os.path.samestat(created_status, current_state)
        ):
            raise DetectError("STATE.md changed while writing")
        if set(os.listdir(project_fd)) != {"STATE.md"}:
            raise DetectError(".project contents changed while creating STATE.md")
        closing_state_fd = state_fd
        state_fd = None
        try:
            os.close(closing_state_fd)
        except OSError as error:
            raise DetectError(f"cannot close STATE.md: {error}") from error
    except BaseException as error:
        if state_created and project_fd is not None:
            try:
                rollback_created_state(
                    project_fd,
                    created_status,
                )
            except DetectError as rollback_error:
                raise rollback_error from error
        if isinstance(error, DetectError):
            raise
        if isinstance(error, OSError):
            raise DetectError(f"cannot create STATE.md: {error}") from error
        raise
    finally:
        close_file_descriptors(state_fd, project_fd, root_fd)


def initialize(
    repo: Path, template: Path, phase: Optional[str] = None
) -> dict:
    if phase is not None and phase not in {"inspect", "define"}:
        raise DetectError(f"initialize phase must be inspect or define: {phase}")
    try:
        raw = template.read_text(encoding="utf-8")
    except OSError as error:
        raise DetectError(f"cannot read state template: {error}") from error
    root = repo.resolve()
    root_status = lstat_evidence(root, missing_ok=True)
    if root_status is None or is_link_like(root, root_status) or not stat.S_ISDIR(
        root_status.st_mode
    ):
        raise DetectError(f"repo is not a directory: {root}")
    project_status = lstat_evidence(root / ".project", missing_ok=True)
    payload = classify(root)
    if payload["verdict"] not in {"brownfield", "greenfield"}:
        payload["wrote_state"] = False
        return payload
    expected = "inspect" if payload["verdict"] == "brownfield" else "define"
    if phase is None:
        phase = expected
    elif phase != expected:
        raise DetectError(
            f"initialize phase {phase} does not match verdict {payload['verdict']}"
        )
    if not ANCHORED_STATE_CREATE_SUPPORTED:
        payload["wrote_state"] = False
        payload["error"] = "anchored no-follow STATE.md creation is unavailable"
        return payload
    write_state_anchored(
        root,
        filled_state_template(raw, project_slug(root), phase),
        root_status,
        project_status,
    )
    payload["wrote_state"] = True
    return payload


def emit(payload: dict, exit_code: int = 0) -> int:
    json.dump(payload, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return exit_code


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("command", choices=("classify", "initialize"))
    result.add_argument("--repo", type=Path, required=True)
    result.add_argument("--template", type=Path)
    result.add_argument("--phase", choices=("inspect", "define"))
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "classify":
            return emit(classify(arguments.repo))
        if arguments.command == "initialize":
            if arguments.template is None:
                raise DetectError("initialize requires --template")
            payload = initialize(
                arguments.repo, arguments.template, arguments.phase
            )
            return emit(payload, 2 if payload.get("error") else 0)
        raise DetectError(f"unknown command: {arguments.command}")
    except DetectError as error:
        json.dump({"status": "error", "error": str(error)}, sys.stdout, indent=2)
        sys.stdout.write("\n")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
