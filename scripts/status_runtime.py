#!/usr/bin/env python3
"""Launch the project status runtime across an atomic refresh handoff."""

import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Sequence

PROJECT_STATUS_MARKER = "gsd-path project status launcher"
INSTALL_LOCK_OWNER = "owner.json"
INSTALL_LOCK_SCHEMA = "gsd-path/install-lock/v1"


def runtime_identity(runtime: Path):
    try:
        status = runtime.stat()
    except FileNotFoundError:
        return None
    return (status.st_dev, status.st_ino, status.st_mtime_ns, status.st_size)


def install_lock_active(lock: Path) -> bool:
    if lock.is_symlink() or not lock.is_dir():
        return False
    try:
        owner = json.loads((lock / INSTALL_LOCK_OWNER).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    pid = owner.get("pid")
    valid_pid = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
    if owner.get("schema") != INSTALL_LOCK_SCHEMA or not valid_pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def launch(repo: Path) -> int:
    parent = repo / ".gsd-path"
    runtime = parent / "runtime" / "pipeline_state.py"
    lock = repo / ".gsd-path-install-lock"
    command = [sys.executable, "-B", str(runtime), "status", "--repo", str(repo)]
    while True:
        before = runtime_identity(runtime)
        if before is None:
            if install_lock_active(lock):
                continue
            print(f"GSD Path status runtime is unavailable: {runtime}", file=sys.stderr)
            return 2
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except OSError as error:
            print(f"GSD Path status runtime failed: {error}", file=sys.stderr)
            return 2
        if result.returncode == 0:
            sys.stdout.write(result.stdout.decode())
            sys.stderr.write(result.stderr.decode())
            return 0
        if install_lock_active(lock) or runtime_identity(runtime) != before:
            continue
        sys.stdout.write(result.stdout.decode())
        sys.stderr.write(result.stderr.decode())
        return result.returncode


def main(argv: Sequence[str] = sys.argv[1:]) -> int:
    if len(argv) != 2 or argv[0] != "--repo":
        print("usage: status_runtime.py --repo <absolute-root>", file=sys.stderr)
        return 2
    repo = Path(argv[1])
    if not repo.is_absolute():
        print("GSD Path status repository must be absolute", file=sys.stderr)
        return 2
    return launch(repo.resolve())


if __name__ == "__main__":
    raise SystemExit(main())
