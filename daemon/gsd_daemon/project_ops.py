"""Project setup actions for the native app.

Each action runs one helper from the plugin source (``install.py`` or
``members.py``) and returns its output. The helper owns every rule; this
module only chooses the command and refuses a project the daemon does not watch.
Two exceptions: a hook action migrates a legacy runtime first, and ``hooks-init``
without hosts uses the agents installed on this computer.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List

from .model import is_path_card
from .plugin import GIT_HOOK_NAMES, OP_LOCK, _tail

# op -> installer flag. Each takes "--project <root>". hooks-init also takes host
# flags: the request's `hosts`, or the agents with GSD Path installed on this computer.
INSTALLER_OPS = {
    "hooks-init": "--hooks-init",
    "hooks-refresh": "--hooks-refresh",
    "hooks-refresh-full": "--hooks-refresh-full",
    "runtime-restore": "--runtime-restore",
    "doctor": "--doctor",
}
# The installer refuses these on the old .gsd-path/runtime/ layout until it is migrated.
HOOK_OPS = ("hooks-init", "hooks-refresh", "hooks-refresh-full")
OPS = (*INSTALLER_OPS, "members", "member-add", "member-hooks", "member-repair")
# Same text as MEMBER_HOOK_MARKER in install.py, which writes these hooks.
MEMBER_HOOK_MARKER = "gsd-path member guard"
NO_AGENT_ERROR = "No agent has GSD Path skills installed on this computer. Install the skills for an agent first."
NO_SOURCE_ERROR = "plugin source is not installed yet; install or update the skills first"


class Busy(Exception):
    status = 409


def _members_helper(plugin, *args: str):
    return plugin.runner([sys.executable, str(plugin.src_dir / "scripts" / "members.py"), *args])


def _validated(plugin, root: str) -> dict:
    rc, stdout, stderr = _members_helper(plugin, "validate", "--repo", root)
    if rc != 0:
        return {"ok": False, "members": [], "error": _tail(stderr) or _tail(stdout)}
    return {"ok": True, "members": json.loads(stdout)["members"], "error": None}


def _members(plugin, root: str) -> dict:
    result = _validated(plugin, root)
    for member in result["members"]:
        rc, stdout, _stderr = _members_helper(plugin, "detect", "--checkout", member["checkout"])
        detected = json.loads(stdout) if rc == 0 else {}
        member["marker"] = {"current": detected.get("current") is True, "reason": detected.get("reason")}
        hooks_dir = plugin._git_hooks_dir(Path(member["checkout"]))
        member["hooks"] = hooks_dir is not None and all(
            plugin._marker_file(hooks_dir / name, MEMBER_HOOK_MARKER) for name in GIT_HOOK_NAMES
        )
    return result


def board_members(plugin, root: str) -> dict:
    """The members of a coordinator for the board, or {} when the project has no MEMBERS.md.

    A failure returns no members and the error, so one bad coordinator never breaks the status read.
    """
    members_file = Path(root) / ".project" / "MEMBERS.md"
    if not members_file.exists() and not members_file.is_symlink():
        return {}
    if not (plugin.src_dir / "scripts" / "members.py").is_file():
        return {"members": [], "members_error": NO_SOURCE_ERROR}
    try:
        result = _members(plugin, root)
    except Exception as error:  # a helper that cannot run or unexpected helper output
        return {"members": [], "members_error": str(error)}
    return {"members": result["members"], "members_error": result["error"]}


def _member_add_args(root: str, body: dict) -> List[str]:
    """`members.py add` arguments from the request. members.py checks every rule.

    Each value goes in one `--flag=value` argument, so a value that starts with
    "-" stays a value and cannot become another option.
    """
    fields = {key: body.get(key) for key in ("name", "checkout", "integration", "create", "visibility")}
    for key, value in fields.items():
        if value is not None and not isinstance(value, str):
            raise ValueError(f"{key} must be text")
    for key in ("name", "checkout"):
        if not (fields[key] or "").strip():
            raise ValueError(f"{key} is required")
    args = ["add", "--repo", root, f"--name={fields['name'].strip()}",
            f"--checkout={os.path.expanduser(fields['checkout'].strip())}",
            f"--integration={fields['integration'] or 'default'}"]
    # Greenfield: members.py creates the GitHub repository and clones it to the checkout.
    if fields["create"]:
        args.append(f"--create={fields['create'].strip()}")
    if fields["visibility"]:
        args.append(f"--visibility={fields['visibility']}")
    return args


def _dispatch(plugin, root: str, op: str, body: dict) -> dict:
    preview: List[str] = ["--dry-run"] if body.get("dry_run") else []
    if op in INSTALLER_OPS:
        hosts: List[str] = []
        if op == "hooks-init":
            chosen = plugin._validate_hosts(body.get("hosts") or []) or [
                host for host, state in plugin.detect_global().items() if state["installed"]
            ]
            if not chosen:
                return {"ok": False, "stdout_tail": "", "error": NO_AGENT_ERROR}
            hosts = [f"--{host}" for host in chosen]
        migrated = None
        if op in HOOK_OPS and plugin._legacy_runtime(Path(root)):
            # One click in the app: migrate the old layout, then do the hook action.
            # A preview stops here; the hook action cannot be previewed before migration.
            migrated = plugin._run_installer("runtime-migrate", ["--runtime-migrate", "--project", root, *preview])
            if preview or not migrated["ok"]:
                return migrated
        result = plugin._run_installer(op, [INSTALLER_OPS[op], *hosts, "--project", root, *preview])
        if migrated:
            result["stdout_tail"] = "\n".join(part for part in (migrated["stdout_tail"], result["stdout_tail"]) if part)
        return result
    plugin.ensure_source()
    if op == "members":
        return _members(plugin, root)
    if op == "member-add":
        if preview:
            raise ValueError("adding a member has no preview; members.py add checks every rule before it writes")
        rc, stdout, stderr = _members_helper(plugin, *_member_add_args(root, body))
        return {"ok": rc == 0, "stdout_tail": _tail(stdout), "error": (_tail(stderr) or _tail(stdout)) if rc else None}
    if op == "member-repair":
        if preview:
            raise ValueError("member repair has no preview; it rewrites only missing or stale markers")
        rc, stdout, stderr = _members_helper(plugin, "repair", "--repo", root)
        return {"ok": rc == 0, "stdout_tail": _tail(stdout), "error": (_tail(stderr) or _tail(stdout)) if rc else None}
    # member-hooks: only into a repository the coordinator records as its member.
    recorded = _validated(plugin, root)
    if body.get("member") not in [member["checkout"] for member in recorded["members"]]:
        raise ValueError(recorded["error"] or "member is not a recorded member of this project")
    return plugin._run_installer(op, ["--member-of", root, "--project", body["member"], *preview])


def run(handler, body: dict) -> dict:
    """POST /api/project/op ``{root, op, dry_run?, member?, hosts?, name?, checkout?, integration?, create?, visibility?}``."""
    root, op = body.get("root"), body.get("op")
    if not is_path_card(handler.watcher.projects, root):
        raise ValueError("root is not a watched project")
    if op not in OPS:
        raise ValueError(f"op must be one of: {', '.join(OPS)}")
    if not OP_LOCK.acquire(blocking=False):
        raise Busy("operation in progress")
    try:
        return _dispatch(handler.plugin, root, op, body)
    finally:
        OP_LOCK.release()
