#!/usr/bin/env python3
"""Prepare, apply or restore one explicitly selected standalone Core hook."""

import argparse
import base64
import json
import os
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import tempfile


def read_regular(path):
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise ValueError(f"expected an unlinked regular file: {path}")
    return path.read_bytes()


def plan(args):
    if args.settings is None or args.repo is None or args.location is None:
        raise ValueError("plan requires --settings, --repo and --location")
    before = read_regular(args.settings)
    data = json.loads(before)
    location = json.loads(args.location)
    if not isinstance(location, list) or len(location) < 2 or location[0] not in ("hooks", "statusLine") or location[-1] != "command":
        raise ValueError("location must select a hooks or statusLine command")
    entry = data
    for key in location[:-1]:
        if isinstance(entry, dict) and isinstance(key, str):
            entry = entry[key]
        elif isinstance(entry, list) and type(key) is int and key >= 0:
            entry = entry[key]
        else:
            raise ValueError("invalid command location")
    if not isinstance(entry, dict) or entry.get("type", "command") != "command":
        raise ValueError("selected hook is not a command hook")
    original = entry.get("command")
    if not isinstance(original, str) or not original.strip():
        raise ValueError("selected command must be a nonempty string")
    repo = args.repo.resolve(strict=True)
    if not repo.is_dir():
        raise ValueError("--repo must be a directory")
    gate = Path(__file__).resolve().with_name("core_hook_gate.py")
    if not gate.is_file():
        raise ValueError(f"missing installed hook gate: {gate}")
    argv = [sys.executable, "-B", str(gate), "--repo", str(repo), "--command", original]
    replacement = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    entry["command"] = replacement
    after = (json.dumps(data, indent=2) + "\n").encode()
    receipt = {
        "schema": "gsd-path/core-hook-change/v1",
        "settings": str(args.settings.absolute()),
        "repo": str(repo), "location": location,
        "original_command": original, "replacement_command": replacement,
        "before": base64.b64encode(before).decode(),
        "after": base64.b64encode(after).decode(),
    }
    # Settings may contain secrets; the review/rollback copy is owner-only.
    with open(args.receipt, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as handle:
        json.dump(receipt, handle, indent=2)
        handle.write("\n")
    return {"status": "planned", "receipt": str(args.receipt.absolute())}


def change(args):
    if args.settings is not None or args.repo is not None or args.location is not None:
        raise ValueError("apply and restore accept only --receipt")
    receipt = json.loads(read_regular(args.receipt))
    if not isinstance(receipt, dict) or receipt.get("schema") != "gsd-path/core-hook-change/v1":
        raise ValueError("unsupported hook change receipt")
    path = Path(receipt["settings"])
    if not path.is_absolute():
        raise ValueError("receipt settings path must be absolute")
    before = base64.b64decode(receipt["before"], validate=True)
    after = base64.b64decode(receipt["after"], validate=True)
    expected, desired = (before, after) if args.action == "apply" else (after, before)
    current = read_regular(path)
    if current == desired:
        return {"status": args.action, "settings": str(path), "changed": False}
    if current != expected:
        raise ValueError("settings changed since planning; refusing to overwrite later edits")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(desired)
        os.chmod(temporary, stat.S_IMODE(path.stat().st_mode))
        if read_regular(path) != expected:
            raise ValueError("settings changed during update")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"status": args.action, "settings": str(path), "changed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply", "restore"))
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--location", help="JSON array locating the selected command")
    args = parser.parse_args()
    try:
        result = plan(args) if args.action == "plan" else change(args)
        print(json.dumps(result))
    except (OSError, ValueError, KeyError, IndexError, TypeError) as error:
        print(f"hook settings error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
