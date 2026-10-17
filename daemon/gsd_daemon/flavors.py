"""Projects run by other GSD frameworks: gsd-pi (.gsd/) and gsd-core (.planning/).

A repository can hold more than one framework, so each framework gets its own
card. The card id is the root for GSD Path (old links keep working) and
"<root>::<flavor>" for the others.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import List, Union

from . import gitinfo, gsd_core, gsd_pi
from .model import PATH_FLAVOR, ProjectStatus
from .probe import compute_attention, health_for, tree_mtime

# The state folder and the files that prove a framework wrote it.
FOREIGN = {
    "gsd-pi": (".gsd", ("STATE.md", "gsd.db", "milestones")),
    "gsd-core": (".planning", ("STATE.md", "ROADMAP.md")),
}


# Each reader fills the card from the state folder and returns extra attention items.
READERS = {"gsd-core": gsd_core.read, "gsd-pi": gsd_pi.read}


def project_id(root: str, flavor: str) -> str:
    return root if flavor == PATH_FLAVOR else f"{root}::{flavor}"


def state_dir(root: Union[str, Path], flavor: str) -> Path:
    return Path(root) / (".project" if flavor == PATH_FLAVOR else FOREIGN[flavor][0])


def foreign_flavors(root: Union[str, Path]) -> List[str]:
    found = []
    for flavor, (folder, markers) in FOREIGN.items():
        base = Path(root) / folder
        if not base.is_dir() or not any((base / marker).exists() for marker in markers):
            continue
        # ~/.gsd is gsd-pi's own home (global gsd.db), not a project.
        if flavor == "gsd-pi" and Path(root).resolve() == Path.home().resolve():
            continue
        found.append(flavor)
    return found


def probe_foreign(root: Union[str, Path], flavor: str) -> ProjectStatus:
    root = str(root)
    mtime = tree_mtime(state_dir(root, flavor))
    status = ProjectStatus(
        root=root,
        id=project_id(root, flavor),
        flavor=flavor,
        **gitinfo.project_identity(root),
        git=gitinfo.git_branch_head_dirty(root),
        state_mtime=mtime,
        last_activity_iso=datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else None,
    )
    extra = READERS[flavor](status, state_dir(root, flavor))
    status.attention = compute_attention(status) + extra
    status.health = health_for(status.attention)
    return status
