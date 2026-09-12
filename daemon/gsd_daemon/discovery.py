from __future__ import annotations

import os
import subprocess
from typing import Dict, Iterable, List, Optional, Tuple

from .probe import is_project_root

SKIP_DIRS = {".git", "node_modules", ".venv", "__pycache__"}


def _normalized(paths: Iterable[str]) -> List[str]:
    return [os.path.normcase(os.path.abspath(os.path.expanduser(p))) for p in paths]


def _is_excluded(path: str, excludes: List[str]) -> bool:
    for excluded in excludes:
        if path == excluded or path.startswith(excluded + os.sep):
            return True
    return False


def _git_common_dir(root: str) -> Optional[str]:
    try:
        result = subprocess.run(
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
    return (0 if os.path.isdir(os.path.join(root, ".git")) else 1, len(root), root)


def _dedupe_worktrees(roots: List[str]) -> List[str]:
    groups: Dict[str, List[str]] = {}
    for root in roots:
        groups.setdefault(_git_common_dir(root) or root, []).append(root)
    return [min(members, key=_dedupe_rank) for members in groups.values()]


def scan(parents: Iterable[str], excludes: Iterable[str] = (), max_depth: int = 6) -> List[str]:
    excluded = _normalized(excludes)
    found: List[str] = []
    for parent in _normalized(parents):
        if _is_excluded(parent, excluded) or not os.path.isdir(parent):
            continue
        _walk(parent, 0, max_depth, excluded, found)
    return sorted(_dedupe_worktrees(found))


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
