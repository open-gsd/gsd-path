#!/usr/bin/env python3
"""Prepare a preserved Core project bundle for migration into Path."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys


def hook_inventory(settings):
    if settings.is_symlink() or not settings.is_file():
        raise ValueError(f"expected a regular hook settings file: {settings}")
    raw = settings.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"hook settings must be an object: {settings}")
    for key in ("hooks", "enabledPlugins"):
        if key in data and not isinstance(data[key], dict):
            raise ValueError(f"{key} must be an object: {settings}")
    commands = []

    def collect(value, location):
        if isinstance(value, dict):
            if "command" in value:
                commands.append({"location": location, "command": value["command"]})
            for key, child in value.items():
                collect(child, location + [key])
        elif isinstance(value, list):
            for index, child in enumerate(value):
                collect(child, location + [index])

    for key in ("hooks", "statusLine"):
        collect(data.get(key), [key])
    return {
        "settings": str(settings.absolute()),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "plugins": data.get("enabledPlugins", {}),
        "commands": commands,
        "status": "review-required",
    }


def snapshot(repo):
    return snapshot_source(repo / ".planning")


def snapshot_source(source):
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"expected a real Core directory: {source}")
    files = {}
    for directory, directories, names in os.walk(source, followlinks=False):
        for name in sorted(directories + names):
            path = Path(directory) / name
            metadata = path.lstat()
            if stat.S_ISLNK(metadata.st_mode):
                raise ValueError(f"refusing source symlink: {path}")
            if stat.S_ISDIR(metadata.st_mode):
                continue
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError(f"refusing non-regular source: {path}")
            files[path.relative_to(source).as_posix()] = path.read_bytes()
    if not files:
        raise ValueError(f"no Core evidence to preserve: {source}")
    return files


def verify_bundle(output):
    if output is None or output.is_symlink() or not output.is_dir():
        raise ValueError("verify requires --output naming a real bundle directory")
    path = output / "manifest.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"expected a regular bundle manifest: {path}")
    manifest = json.loads(path.read_bytes())
    if not isinstance(manifest, dict) or manifest.get("schema") != "gsd-path/core-migration/v1":
        raise ValueError("unsupported migration manifest schema")
    if manifest.get("status") != "prepared":
        raise ValueError("migration bundle is not prepared")
    files = snapshot_source(output / "core")
    if manifest.get("files") != inventory(files):
        raise ValueError("bundle evidence differs from its manifest; prepare a new bundle")
    return {
        "status": "verified-bundle",
        "output": str(output.absolute()),
        "files": manifest["files"],
        "hooks_verified": False,
    }


def inventory(files):
    return [
        {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
        for name, content in sorted(files.items())
    ]


def prepare(repo, output, files, manifest):
    if output is None:
        raise ValueError("prepare requires --output outside the source project")
    output = output.absolute()
    if output.is_symlink() or output.exists():
        raise ValueError(f"output already exists: {output}")
    resolved = output.resolve()
    if resolved == repo or repo in resolved.parents:
        raise ValueError("output must be outside the source project")
    # Core must be idle while preparing; reject changes observed during capture.
    if snapshot(repo) != files:
        raise ValueError("Core inputs changed; stop Core work before preparing")
    output.mkdir()
    try:
        for name, content in files.items():
            target = output / "core" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        manifest = dict(manifest, status="prepared", output=str(output))
        (output / "manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
    except BaseException:
        shutil.rmtree(output)
        raise
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preview", "prepare", "verify"))
    parser.add_argument("--repo", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hook-settings", action="append", type=Path, default=[])
    args = parser.parse_args()
    try:
        if args.command == "verify":
            if args.repo is not None or args.hook_settings:
                raise ValueError("verify accepts only --output")
            print(json.dumps(verify_bundle(args.output), indent=2))
            return 0
        if args.repo is None:
            raise ValueError("preview and prepare require --repo")
        repo = args.repo.resolve(strict=True)
        files = snapshot(repo)
        manifest = {
            "schema": "gsd-path/core-migration/v1",
            "status": "preview",
            "source": str(repo / ".planning"),
            "missing_inputs": [name for name in ("PROJECT.md", "REQUIREMENTS.md", "ROADMAP.md", "STATE.md") if name not in files],
            "hooks_verified": False,
            "hook_review": [hook_inventory(path) for path in args.hook_settings],
            "files": inventory(files),
        }
        if args.command == "prepare":
            manifest = prepare(repo, args.output, files, manifest)
        elif args.output is not None:
            raise ValueError("preview does not accept --output")
        print(json.dumps(manifest, indent=2))
    except (OSError, ValueError) as error:
        print(f"migration error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
