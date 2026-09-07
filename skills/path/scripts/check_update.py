#!/usr/bin/env python3
"""Print a one-line notice when a newer GSD Path is published to npm.

Installed beside the router skill; the installer stamps ../VERSION. Silent on
any failure (offline, unpublished package, missing stamp) and rate-limited by
a 24h cache, so the router can run it unconditionally.
"""

import json
import time
import urllib.request
from pathlib import Path

REGISTRY_URL = "https://registry.npmjs.org/gsd-path/latest"
CACHE_PATH = Path.home() / ".cache" / "gsd-path" / "update-check.json"
CACHE_TTL_SECONDS = 24 * 3600
NETWORK_TIMEOUT_SECONDS = 3


def parse_version(value):
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except (ValueError, AttributeError):
        return None


def is_newer(latest, installed):
    latest_parts = parse_version(latest)
    installed_parts = parse_version(installed)
    return (
        latest_parts is not None
        and installed_parts is not None
        and latest_parts > installed_parts
    )


def _write_cache(now, latest):
    try:
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(
            json.dumps({"checked_at": now, "latest": latest}), encoding="utf-8"
        )
    except OSError:
        pass


def latest_version():
    now = time.time()
    try:
        cached = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
        if now - cached["checked_at"] < CACHE_TTL_SECONDS:
            return cached["latest"]
    except Exception:
        pass
    try:
        with urllib.request.urlopen(
            REGISTRY_URL, timeout=NETWORK_TIMEOUT_SECONDS
        ) as response:
            latest = json.load(response)["version"]
    except Exception:
        # Cache the failure too, so offline or pre-publish routers do not
        # retry the network on every conversation within the TTL.
        _write_cache(now, None)
        return None
    _write_cache(now, latest)
    return latest


def notice():
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    try:
        installed = version_file.read_text(encoding="utf-8").strip()
        latest = latest_version()
    except Exception:
        return None
    if is_newer(latest, installed):
        return (
            f"GSD Path {latest} is available (installed {installed}). "
            "Update: npx gsd-path@latest --update "
            "(add --local for a project install)."
        )
    return None


def main():
    line = notice()
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
