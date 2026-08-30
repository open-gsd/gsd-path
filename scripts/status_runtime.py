#!/usr/bin/env python3
"""Launch the project status runtime across an atomic refresh handoff."""

import errno
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence

PROJECT_STATUS_MARKER = "gsd-path project status launcher"
INSTALL_LOCK_OWNER = "owner.json"
INSTALL_LOCK_SCHEMA = "gsd-path/install-lock/v2"


def process_identity(pid: int):
    if os.name == "nt":
        command = [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            f"(Get-Process -Id {pid} -ErrorAction Stop).StartTime.ToUniversalTime().Ticks",
        ]
    else:
        command = ["ps", "-o", "lstart=", "-p", str(pid)]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
    except OSError:
        return None
    value = result.stdout.strip()
    return f"{os.name}:{value}" if result.returncode == 0 and value else None


def runtime_identity(runtime: Path):
    try:
        status = runtime.stat()
    except FileNotFoundError:
        return None
    return (status.st_dev, status.st_ino, status.st_mtime_ns, status.st_size)


def process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError as error:
        return error.errno == errno.EPERM
    return True


def install_lock_active(lock: Path) -> bool:
    if lock.is_symlink() or not lock.is_dir():
        return False
    try:
        owner = json.loads((lock / INSTALL_LOCK_OWNER).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    pid = owner.get("pid")
    valid_pid = isinstance(pid, int) and not isinstance(pid, bool) and pid > 0
    identity = owner.get("identity")
    if (
        owner.get("schema") != INSTALL_LOCK_SCHEMA
        or not valid_pid
        or not isinstance(identity, str)
    ):
        return False
    current_identity = process_identity(pid)
    if current_identity is None:
        return process_alive(pid)
    return current_identity == identity


def launch(repo: Path) -> int:
    parent = repo / ".gsd-path"
    runtime = parent / "runtime" / "pipeline_state.py"
    lock = repo / ".gsd-path-install-lock"
    command = [sys.executable, "-B", str(runtime), "status", "--repo", str(repo)]
    while True:
        if install_lock_active(lock):
            time.sleep(0.05)
            continue
        before = runtime_identity(runtime)
        if before is None:
            print(f"GSD Path status runtime is unavailable: {runtime}", file=sys.stderr)
            return 2
        try:
            result = subprocess.run(command, capture_output=True, check=False)
        except OSError as error:
            print(f"GSD Path status runtime failed: {error}", file=sys.stderr)
            return 2
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
