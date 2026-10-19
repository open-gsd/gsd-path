from __future__ import annotations

import functools
import os
import re
import subprocess
from typing import Dict, Iterable, List, Optional, Tuple

from .flavors import foreign_flavors
from .model import PATH_FLAVOR
from .probe import is_not_started, is_project_root
from .gitinfo import _git
from . import subprocess_platform

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def _normalized(paths: Iterable[str]) -> List[str]:
    return [os.path.abspath(os.path.expanduser(p)) for p in paths]


def _is_excluded(path: str, excludes: List[str]) -> bool:
    # normcase only for the comparison: it lowercases on Windows, and
    # discovered roots keep their original case for storage and display.
    path = os.path.normcase(os.path.realpath(path))
    for excluded in excludes:
        excluded = os.path.normcase(os.path.realpath(excluded))
        if path == excluded or path.startswith(excluded + os.sep):
            return True
    return False


def _git_common_dir(root: str) -> Optional[str]:
    try:
        result = subprocess_platform.run(
            ["git", "-C", root, "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    common = result.stdout.strip()
    if not common:
        return None
    if not os.path.isabs(common):
        common = os.path.join(root, common)
    return os.path.realpath(common)


def _dedupe_rank(root: str) -> Tuple[int, int, str]:
    branch = _git(root, "branch", "--show-current") or ""
    rank = 0 if re.fullmatch(r"gsd-path/M\d{3,}", branch) else 1
    if rank and not os.path.isdir(os.path.join(root, ".git")):
        rank = 2
    return (rank, len(root), root)


def _bound_worktrees(root: str) -> List[str]:
    records = _git(root, "worktree", "list", "--porcelain", "-z") or ""
    found = []
    for record in records.split("\0\0"):
        fields = record.split("\0")
        if not any(re.fullmatch(r"branch refs/heads/gsd-path/M\d{3,}", field) for field in fields):
            continue
        for field in fields:
            if field.startswith("worktree "):
                # Git for Windows reports C:/... paths; normpath matches them to
                # the backslashed roots the walk found so dedupe sees one root.
                path = os.path.normpath(field.removeprefix("worktree "))
                if is_project_root(path):
                    found.append(path)
    return found


def _dedupe_worktrees(roots: List[str]) -> List[str]:
    groups: Dict[str, List[str]] = {}
    for root in roots:
        groups.setdefault(os.path.normcase(_git_common_dir(root) or root), []).append(root)
    # A started project wins over a not-started install in the same repository.
    return [min(members, key=lambda root: (not is_project_root(root), _dedupe_rank(root)))
            for members in groups.values()]


def scan_projects(parents: Iterable[str], excludes: Iterable[str] = (),
                  max_depth: int = 6) -> List[Tuple[str, str]]:
    """(root, flavor) for every project card: GSD Path, gsd-pi and gsd-core."""
    excluded = _normalized(excludes)
    found: List[str] = []
    foreign: List[Tuple[str, str]] = []
    for parent in _normalized(parents):
        if _is_excluded(parent, excluded) or not os.path.isdir(parent):
            continue
        _walk(parent, 0, max_depth, excluded, found, foreign)
    for root in list(found):
        found.extend(path for path in _bound_worktrees(root) if not _is_excluded(path, excluded))
    return sorted([(root, PATH_FLAVOR) for root in _dedupe_worktrees(found)] + _dedupe_foreign(foreign))


def scan(parents: Iterable[str], excludes: Iterable[str] = (), max_depth: int = 6) -> List[str]:
    return [root for root, flavor in scan_projects(parents, excludes, max_depth) if flavor == PATH_FLAVOR]


@functools.lru_cache(maxsize=None)
def _git_location(root: str) -> Tuple[Optional[str], Optional[str]]:
    """(common dir, checkout top) of a gsd-pi/gsd-core folder, once per daemon run.
    ponytail: a folder that becomes or stops being a worktree is seen after a daemon restart."""
    common = _git_common_dir(root)
    return common, (_git(root, "rev-parse", "--show-toplevel") if common else None)


def _dedupe_foreign(pairs: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    # One card per framework per folder: the same folder in a worktree merges into the main checkout.
    groups: Dict[Tuple[str, str, str], List[Tuple[str, str]]] = {}
    for root, flavor in pairs:
        common, top = _git_location(root)
        relative = os.path.relpath(os.path.realpath(root), os.path.realpath(top)) if top else ""
        groups.setdefault((os.path.normcase(common or root), os.path.normcase(relative), flavor), []).append((root, top or root))
    return [(min(members, key=lambda m: (not os.path.isdir(os.path.join(m[1], ".git")), len(m[0]), m[0]))[0], flavor)
            for (_, _, flavor), members in groups.items()]


def _walk(current: str, depth: int, max_depth: int, excluded: List[str],
          found: List[str], foreign: List[Tuple[str, str]]) -> None:
    if depth > max_depth or _is_excluded(current, excluded):
        return
    # Other frameworks never stop the walk, so they never hide a GSD Path project below them.
    foreign.extend((current, flavor) for flavor in foreign_flavors(current))
    if is_project_root(current):
        found.append(current)
        return
    before = len(found)
    try:
        entries = sorted(os.scandir(current), key=lambda entry: entry.name)
    except OSError:
        return
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
        except OSError:
            continue
        name = entry.name
        if name in SKIP_DIRS or name.startswith("."):
            continue
        _walk(entry.path, depth + 1, max_depth, excluded, found, foreign)
    # A project install with no milestone is listed as "Not started", but only
    # when no project is below it, so it never hides a started project.
    if len(found) == before and is_not_started(current):
        found.append(current)
