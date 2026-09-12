from __future__ import annotations

import subprocess
from typing import Optional


def _git(root: str, *args: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "-C", root, *args],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def git_branch_head_dirty(root) -> dict:
    root = str(root)
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    head = _git(root, "rev-parse", "HEAD")
    porcelain = _git(root, "status", "--porcelain")
    return {
        "branch": branch or None,
        "head": head or None,
        "dirty": bool(porcelain) if porcelain is not None else None,
    }
