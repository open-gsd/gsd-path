from __future__ import annotations

import os
from typing import Iterable, List

from .probe import is_project_root

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def _normalized(paths: Iterable[str]) -> List[str]:
    return [os.path.normcase(os.path.abspath(os.path.expanduser(p))) for p in paths]


def _is_excluded(path: str, excludes: List[str]) -> bool:
    for excluded in excludes:
        if path == excluded or path.startswith(excluded + os.sep):
            return True
    return False


def scan(parents: Iterable[str], excludes: Iterable[str] = (), max_depth: int = 6) -> List[str]:
    excluded = _normalized(excludes)
    found: List[str] = []
    for parent in _normalized(parents):
        if _is_excluded(parent, excluded) or not os.path.isdir(parent):
            continue
        _walk(parent, 0, max_depth, excluded, found)
    return sorted(found)


def _walk(current: str, depth: int, max_depth: int,
          excluded: List[str], found: List[str]) -> None:
    if depth > max_depth or _is_excluded(current, excluded):
        return
    if is_project_root(current):
        found.append(current)
        return
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
        _walk(entry.path, depth + 1, max_depth, excluded, found)
