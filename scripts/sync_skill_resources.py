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
SKILL_ALIASES = dict(RESOURCE_MANIFEST["skill_aliases"])
ROUTER_ALIASES = dict(RESOURCE_MANIFEST["router_aliases"])
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
    for legacy, canonical_skill in SKILL_ALIASES.items():
        canonical_directory = root / "skills" / canonical_skill
        legacy_directory = root / "skills" / legacy
        yield canonical_directory / "SKILL.md", legacy_directory / "CANONICAL.md"
        for relative in PHASE_RESOURCES.get(canonical_skill, ()):
            yield canonical / relative, legacy_directory / relative
        canonical_prefix = f"skills/{canonical_skill}/"
        for source, destination in SCRIPT_TARGETS:
            if destination.startswith(canonical_prefix):
                relative = destination.removeprefix(canonical_prefix)
                yield root / source, legacy_directory / relative
    for alias, canonical_skill in ROUTER_ALIASES.items():
        canonical_directory = root / "skills" / canonical_skill
        alias_directory = root / "skills" / alias
        for source in _skill_files(canonical_directory):
            yield source, alias_directory / source.relative_to(canonical_directory)


def _skill_files(skill_root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(skill_root):
        names[:] = [name for name in names if name not in (".git", "node_modules")]
        for name in files:
            if name == ".DS_Store":
                continue
            yield Path(directory) / name


def rewrite_router_alias_skill(text: str, alias: str, canonical: str) -> str:
    """Keep the router contract; change only the slash/catalog name."""
    if not text.startswith("---\n"):
        raise ValueError("SKILL.md is missing YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise ValueError("SKILL.md has unterminated YAML frontmatter")
    header = text[4:end]
    rest = text[end:]
    expected = f"name: {canonical}"
    replacement = f"name: {alias}"
    lines = header.split("\n")
    if expected not in lines:
        raise ValueError(f"router alias {alias} is missing {expected}")
    rewritten = [replacement if line == expected else line for line in lines]
    if rewritten.count(replacement) != 1:
        raise ValueError(f"router alias {alias} name rewrite was not unique")
    invoke = f"invokes ${canonical}."
    invoke_with_alias = f"invokes ${alias} or ${canonical}."
    header = "\n".join(rewritten)
    if invoke not in header:
        raise ValueError(f"router alias {alias} is missing {invoke}")
    header = header.replace(invoke, invoke_with_alias, 1)
    return "---\n" + header + rest


def materialized_resource_bytes(source: Path, destination: Path) -> bytes:
    data = source.read_bytes()
    if destination.name != "SKILL.md":
        return data
    alias = destination.parent.name
    canonical = ROUTER_ALIASES.get(alias)
    if canonical is None:
        return data
    return rewrite_router_alias_skill(
        data.decode("utf-8"), alias, canonical
    ).encode("utf-8")


def package_metadata(root: Path) -> Iterable[Path]:
    for directory, names, files in os.walk(root):
        names[:] = [name for name in names if name not in (".git", "node_modules")]
        for name in names + files:
            if name == ".DS_Store":
                yield Path(directory) / name


def divergence_warning(source: Path, destination: Path, root: Path) -> Optional[str]:
    """Flag the wrong-direction-edit signature: a generated copy that differs
    from canonical and is NEWER than it (sync preserves canonical mtimes via
    copy2, so a just-edited copy is the only newer-and-different case)."""
    if not destination.is_file():
        return None
    if destination.read_bytes() == materialized_resource_bytes(source, destination):
        return None
    if destination.stat().st_mtime > source.stat().st_mtime:
        return (
            f"generated resource diverges from canonical and is newer "
            f"(possible wrong-direction edit; edit {source.relative_to(root)} "
            f"instead): {destination.relative_to(root)}"
        )
    return None


def mismatches(root: Path) -> Sequence[str]:
    problems = []
    expected_skills = (
        "gsd-path",
        *sorted((*PHASE_RESOURCES, *SKILL_ALIASES, *ROUTER_ALIASES)),
    )
    if SKILL_NAMES != expected_skills:
        problems.append(
            "manifest skills must be root gsd-path plus every canonical skill and alias"
        )
    if set(SKILL_ALIASES) & set(PHASE_RESOURCES):
        problems.append("skill aliases cannot also own phase resources")
    if set(ROUTER_ALIASES) & set(PHASE_RESOURCES):
        problems.append("router aliases cannot also own phase resources")
    if set(ROUTER_ALIASES) & set(SKILL_ALIASES):
        problems.append("router aliases cannot also be skill aliases")
    for legacy, canonical in SKILL_ALIASES.items():
        if canonical not in PHASE_RESOURCES:
            problems.append(f"skill alias target is not canonical: {legacy} -> {canonical}")
    for alias, canonical in ROUTER_ALIASES.items():
        if canonical != "gsd-path":
            problems.append(f"router alias target is not the router: {alias} -> {canonical}")
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
        else:
            try:
                expected = materialized_resource_bytes(source, destination)
            except ValueError as error:
                problems.append(str(error))
                continue
            if expected != destination.read_bytes():
                warning = divergence_warning(source, destination, root)
                if warning:
                    problems.append(warning)
                else:
                    problems.append(
                        f"stale generated resource: {destination.relative_to(root)}"
                    )
    for path in package_metadata(root):
        problems.append(f"unexpected package metadata: {path.relative_to(root)}")
    return problems


def synchronize(root: Path) -> int:
    copied = 0
    warnings = 0
    for source, destination in resource_pairs(root):
        if not source.is_file():
            print(f"missing canonical resource: {source}", file=sys.stderr)
            return 1
        warning = divergence_warning(source, destination, root)
        if warning:
            print(f"warning: {warning}", file=sys.stderr)
            warnings += 1
        destination.parent.mkdir(parents=True, exist_ok=True)
        expected = materialized_resource_bytes(source, destination)
        if expected != source.read_bytes():
            destination.write_bytes(expected)
        else:
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
    print(
        json.dumps(
            {
                "removed_metadata": removed_metadata,
                "resources": copied,
                "warnings": warnings,
            },
            sort_keys=True,
        )
    )
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
