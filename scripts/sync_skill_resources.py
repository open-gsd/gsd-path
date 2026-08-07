#!/usr/bin/env python3
"""Synchronize canonical GSD Path resources into standalone phase skills."""

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


# Single source of truth for the resource tables, shared with install.mjs.
RESOURCE_MANIFEST = json.loads(
    (Path(__file__).resolve().parent / "skill-resources.json").read_text(
        encoding="utf-8"
    )
)
PHASE_RESOURCES = {
    skill: tuple(resources)
    for skill, resources in RESOURCE_MANIFEST["phase_resources"].items()
}
SCRIPT_TARGETS = tuple(tuple(pair) for pair in RESOURCE_MANIFEST["script_targets"])
PHASE_CONTRACT_TARGETS = tuple(
    tuple(pair) for pair in RESOURCE_MANIFEST["phase_contract_targets"]
)
SHARED_DISPATCH_TARGETS = tuple(
    tuple(pair) for pair in RESOURCE_MANIFEST["shared_dispatch_targets"]
)
SKILL_NAMES = tuple(RESOURCE_MANIFEST["skills"])
PACKAGE_FILES = tuple(RESOURCE_MANIFEST["package_files"])


def resource_pairs(root: Path) -> Iterable[Tuple[Path, Path]]:
    for source, destination in SHARED_DISPATCH_TARGETS:
        yield root / source, root / destination
    canonical = root / "skills" / "gsd-path"
    for skill, resources in PHASE_RESOURCES.items():
        for relative in resources:
            yield canonical / relative, root / "skills" / skill / relative
    for source, destination in SCRIPT_TARGETS:
        yield root / source, root / destination
    for source, destination in PHASE_CONTRACT_TARGETS:
        yield root / source, root / destination


def package_metadata(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in (".git", "node_modules")]
        for name in names + files:
            if name == ".DS_Store":
                yield Path(directory) / name


def mismatches(root: Path) -> Sequence[str]:
    problems = []
    if SKILL_NAMES != ("gsd-path", *sorted(PHASE_RESOURCES)):
        problems.append("manifest skills must be root gsd-path plus every phase resource key")
    package_path = root / "package.json"
    try:
        package_files = tuple(json.loads(package_path.read_text(encoding="utf-8"))["files"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        package_files = ()
    if package_files != PACKAGE_FILES:
        problems.append("package.json files do not match manifest package_files")
    for source, destination in resource_pairs(root):
        if not source.is_file():
            problems.append(f"missing canonical resource: {source.relative_to(root)}")
        elif not destination.is_file():
            problems.append(f"missing generated resource: {destination.relative_to(root)}")
        elif source.read_bytes() != destination.read_bytes():
            problems.append(f"stale generated resource: {destination.relative_to(root)}")
    for path in package_metadata(root):
        problems.append(f"unexpected package metadata: {path.relative_to(root)}")
    return problems


def synchronize(root: Path) -> int:
    copied = 0
    for source, destination in resource_pairs(root):
        if not source.is_file():
            print(f"missing canonical resource: {source}", file=sys.stderr)
            return 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied += 1
    removed_metadata = 0
    for path in package_metadata(root):
        if not path.is_file() and not path.is_symlink():
            print(f"unexpected non-file package metadata: {path}", file=sys.stderr)
            return 1
        path.unlink()
        removed_metadata += 1
    package_path = root / "package.json"
    package = json.loads(package_path.read_text(encoding="utf-8"))
    package["files"] = list(PACKAGE_FILES)
    package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"removed_metadata": removed_metadata, "resources": copied}, sort_keys=True))
    return 0


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root",
    )
    argument_parser.add_argument("--check", action="store_true")
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = parser().parse_args(argv)
    root = arguments.root.resolve()
    if arguments.check:
        problems = mismatches(root)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        print(json.dumps({"resources": sum(1 for _ in resource_pairs(root))}, sort_keys=True))
        return 0
    return synchronize(root)


if __name__ == "__main__":
    raise SystemExit(main())
