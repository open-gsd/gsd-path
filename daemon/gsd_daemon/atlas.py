"""Launch preparation for gsd-atlas index panels (issue #447).

Prep only, per the 2026-10-18 owner ruling: no panel UI ships before the
first gsd-atlas release. This module discovers an existing index store and
classifies health envelopes, so the gated panel PRs build on tested rules.

The store rule implemented here is the published default from gsd-atlas
docs/reference/cli.md, "Where the index lives": the store is the
``gsd-atlas`` folder inside the repository's git common directory, shared by
every worktree, and holds ``facts.db``. Only ``build`` creates a store, so
the folder's presence means an index exists. The cache-root fallback and the
``store.dir``/``GSD_ATLAS_STORE_DIR`` override place the store at
``<dir>/<store id>``, and the store-id rule is not published; this module
does not guess those locations. Discovery is filesystem-only: it never runs
gsd-atlas and never opens a database, so it cannot take the writer lease or
fail on a host Node version.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .discovery import _git_common_dir

HEALTH_SCHEMA = "gsd-atlas.atlas-status/1"
STATUS_SCHEMA = "gsd-atlas.status/1"
ERROR_SCHEMA = "gsd-atlas.error/1"

# Exit codes from gsd-atlas docs/reference/cli.md.
EXIT_LEASE_HELD = 3

STATE_OK = "ok"
STATE_DEGRADED = "degraded"
STATE_BUSY = "busy"
STATE_NOT_INSTALLED = "not installed"
STATE_NOT_INDEXED = "not indexed"
STATE_UNSUPPORTED = "unsupported atlas version"
STATE_UNAVAILABLE = "unavailable"

# A degraded health whose only reason is `follower` means an agent's MCP
# server holds the lease; the index is current and the card must stay green
# (probe result 3 of the 2026-10-18 ruling).
FOLLOWER_ONLY = ["follower"]


def discover_store(root: str) -> Optional[str]:
    """Return the gsd-atlas store directory shared by a repo's worktrees.

    None when the repository has no index store (no gsd-atlas folder with a
    facts.db in the git common directory): the card shows no panel. The
    discovery never invokes gsd-atlas, so it works on hosts where the binary
    or a supported Node version is absent.
    """
    common = _git_common_dir(root)
    if common is None:
        return None
    store = Path(common) / "gsd-atlas"
    # gsd-atlas relocates a symlinked store to its cache fallback and keeps
    # facts.db as a regular file (src/fact-store/location.ts), so a link at
    # either entry is not this store.
    if store.is_symlink() or not store.is_dir():
        return None
    facts = store / "facts.db"
    if facts.is_symlink() or not facts.is_file():
        return None
    return str(store)


def interpret_health(
    envelope: Optional[Dict[str, Any]],
    *,
    exit_code: Optional[int],
    binary_present: bool,
) -> Dict[str, Any]:
    """Classify one ``gsd-atlas health`` result for a project card.

    The caller runs the CLI on card refresh (never per file event) and passes
    the parsed JSON envelope (None when the command printed none), the CLI
    exit code (None when the binary could not run at all), and whether a
    gsd-atlas binary exists. The returned dict carries ``state`` plus the
    envelope fields the panel will show.
    """
    result: Dict[str, Any] = {
        "state": STATE_UNAVAILABLE,
        "health": None,
        "reasons": [],
    }
    if not binary_present:
        result["state"] = STATE_NOT_INSTALLED
        return result
    if exit_code == EXIT_LEASE_HELD:
        result["state"] = STATE_BUSY
        return result
    if envelope is None:
        return result
    result["schema"] = envelope.get("schema")
    if envelope.get("ok") is False or envelope.get("schema") == ERROR_SCHEMA:
        # gsd-atlas reports every failure as a gsd-atlas.error/1 envelope
        # with one diagnostic carrying the code (src/query/envelope.ts).
        diagnostics = envelope.get("diagnostics") or []
        code = None
        if diagnostics and isinstance(diagnostics[0], dict):
            code = diagnostics[0].get("code")
        result["code"] = code
        if code == "not_indexed":
            result["state"] = STATE_NOT_INDEXED
        elif code == "lease_held":
            result["state"] = STATE_BUSY
        elif code == "schema_too_new":
            result["state"] = STATE_UNSUPPORTED
        return result
    if envelope.get("schema") != HEALTH_SCHEMA:
        result["state"] = STATE_UNSUPPORTED
        return result
    data = envelope.get("data")
    if not isinstance(data, dict):
        data = {}
    health = data.get("health")
    reasons = data.get("reasons") or []
    result["health"] = health
    result["reasons"] = list(reasons)
    if health == "ok" or list(reasons) == FOLLOWER_ONLY:
        result["state"] = STATE_OK
    else:
        result["state"] = STATE_DEGRADED
    return result
