#!/usr/bin/env python3
# gsd-path project runtime
"""Placement shared by task isolation, verification, and integration."""

import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True

import hashlib
import json
import os
import tempfile
from pathlib import Path

if __package__:
    from . import _common
else:
    try:
        import _common
    except ImportError:
        from scripts import _common


def _worktree_list_porcelain(primary: Path) -> tuple[str, bool]:
    try:
        if __package__:
            from . import pipeline_git as pg
        else:
            from scripts import pipeline_git as pg
    except ImportError:
        try:
            import pipeline_git as pg
        except ImportError:
            pg = None
    if pg is not None:
        return pg.worktree_list_porcelain(primary)
    try:
        output = _git(primary, "worktree", "list", "--porcelain", "-z")
        return output, True
    except ValueError:
        output = _git(primary, "worktree", "list", "--porcelain")
        return output, False


def _git(primary: Path, *args: str) -> str:
    result = _common.run_git(primary, *args)
    if result.returncode:
        raise ValueError(result.stderr.strip() or "cannot inspect worktree placement")
    return result.stdout.rstrip("\n")


def _identity(path: Path) -> str:
    digest = hashlib.sha256(os.fsencode(path)).hexdigest()
    # Two identities nest in every managed path; full digests would use about
    # 130 of Windows' 260-character MAX_PATH before any repository content.
    return digest[:16] if os.name == "nt" else digest


def _workspace(primary: Path, pin: bool) -> Path:
    common = Path(_git(primary, "rev-parse", "--git-common-dir"))
    common = (primary / common).resolve()
    identity = _identity(primary)
    receipt = common / "gsd-path" / "workspaces" / f"{identity}.json"
    try:
        data = json.loads(receipt.read_text(encoding="utf-8"))
    except FileNotFoundError:
        pass
    else:
        if (not isinstance(data, dict) or data.get("primary") != str(primary)
                or not isinstance(data.get("root"), str)
                or not Path(data["root"]).is_absolute()):
            raise ValueError(f"invalid worktree placement receipt: {receipt}")
        return Path(data["root"])

    root = Path(os.environ.get("GSD_PATH_WORKTREE_ROOT") or Path.home() / ".gsd-path" / "projects").expanduser()
    if not root.is_absolute():
        raise ValueError("GSD_PATH_WORKTREE_ROOT must be absolute")
    root = root.resolve()
    parent = root
    while not parent.exists():
        parent = parent.parent
    ancestor = _common.run_git(parent, "rev-parse", "--git-common-dir")
    same_repository = (
        ancestor.returncode == 0
        and (parent / ancestor.stdout.strip()).resolve() == common
    )
    if root.is_relative_to(primary) or same_repository:
        raise ValueError(f"managed worktree root must be outside this repository's worktrees: {root}")
    workspace = root / _identity(common) / identity
    if pin:
        receipt.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=receipt.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"primary": str(primary), "root": str(workspace)}, handle)
            try:
                os.link(temporary, receipt)
            except FileExistsError:
                return _workspace(primary, False)
        finally:
            os.unlink(temporary)
    return workspace


def release_workspace(primary: Path) -> bool:
    """Forget the pinned placement receipt once no linked worktrees remain.

    Lets GSD_PATH_WORKTREE_ROOT (or a new default) apply again at the next
    milestone's first allocation. Returns True when a receipt was removed;
    any remaining linked worktree (including one only still registered) keeps
    the pin.
    """
    primary = primary.resolve()
    common = Path(_git(primary, "rev-parse", "--git-common-dir"))
    common = (primary / common).resolve()
    receipt = common / "gsd-path" / "workspaces" / f"{_identity(primary)}.json"
    if not receipt.is_file():
        return False
    output, nul_separated = _worktree_list_porcelain(primary)
    records = output.split("\0\0") if nul_separated else [
        block for block in output.strip().split("\n\n") if block.strip()
    ]
    for record in records:
        fields = record.split("\0") if nul_separated else record.splitlines()
        for field in fields:
            if field.startswith("worktree ") and Path(field[len("worktree "):]).resolve() != primary:
                return False
    receipt.unlink()
    return True


def worktree_path(primary: Path, kind: str, name: str, *, pin: bool = False) -> Path:
    primary = primary.resolve()
    if kind not in {"task", "verify", "integrate", "bound"} or not name or Path(name).name != name or name in {".", ".."}:
        raise ValueError("invalid managed worktree kind or name")
    if kind == "bound":
        return _workspace(primary, pin) / kind / name
    legacy = (primary.parent / f".{primary.name}-gsd-path-integrate-{name}"
              if kind == "integrate" else primary.parent / f"{primary.name}.gsd-path" / kind / name)
    branch = f"refs/heads/gsd-path-{kind}/{name}"
    output, nul_separated = _worktree_list_porcelain(primary)
    if nul_separated:
        records = output.split("\0\0")
    else:
        records = [block for block in output.strip().split("\n\n") if block.strip()]
    for record in records:
        fields = record.split("\0") if nul_separated else record.splitlines()
        # Compare as paths: git prints forward slashes on Windows.
        worktrees = [Path(field[len("worktree "):]) for field in fields if field.startswith("worktree ")]
        if legacy in worktrees and f"branch {branch}" in fields:
            return legacy
    # Keep collision checks and missing-directory recovery at the old location.
    if os.path.lexists(legacy):
        return legacy
    return _workspace(primary, pin) / kind / name
