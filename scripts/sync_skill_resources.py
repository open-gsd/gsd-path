#!/usr/bin/env python3
"""Synchronize canonical GSD Path resources into standalone phase skills."""

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Iterable, Optional, Sequence, Tuple


PHASE_RESOURCES = {
    "gsd-path-build": (
        "references/coder.md",
        "references/dispatch.md",
        "references/reviewer.md",
        "templates/board.md",
        "templates/task.md",
        "templates/wave-review.md",
    ),
    "gsd-path-docs-audit": (
        "references/dispatch.md",
        "references/docs-auditor.md",
        "templates/docs-audit.md",
    ),
    "gsd-path-grill": (
        "templates/intent.md",
        "templates/state.md",
    ),
    "gsd-path-onboard": (
        "references/codebase-mapper.md",
        "references/dispatch.md",
        "references/docs-auditor.md",
        "templates/codebase.md",
        "templates/docs-audit.md",
        "templates/state.md",
    ),
    "gsd-path-plan": (
        "references/dispatch.md",
        "references/planner.md",
        "templates/plan.md",
        "templates/task.md",
    ),
    "gsd-path-research": (
        "references/dispatch.md",
        "references/researcher.md",
        "templates/evidence.md",
    ),
    "gsd-path-review": (
        "references/dispatch.md",
        "references/reviewer.md",
        "templates/archive-manifest.md",
        "templates/final-review.md",
        "templates/gap-review.md",
        "templates/wave-review.md",
    ),
    "gsd-path-synthesize": (
        "references/dispatch.md",
        "references/synthesizer.md",
        "templates/synthesis.md",
    ),
}

SCRIPT_TARGETS = (
    ("scripts/archive_milestone.py", "skills/gsd-path/scripts/archive_milestone.py"),
    ("scripts/archive_milestone.py", "skills/gsd-path-review/scripts/archive_milestone.py"),
)

PHASE_CONTRACT_TARGETS = (
    ("skills/gsd-path-build/SKILL.md", "skills/gsd-path/BUILD.md"),
    ("skills/gsd-path-docs-audit/SKILL.md", "skills/gsd-path/DOCS-AUDIT.md"),
    ("skills/gsd-path-grill/SKILL.md", "skills/gsd-path/GRILL.md"),
    ("skills/gsd-path-onboard/SKILL.md", "skills/gsd-path/ONBOARD.md"),
    ("skills/gsd-path-plan/SKILL.md", "skills/gsd-path/PLAN.md"),
    ("skills/gsd-path-research/SKILL.md", "skills/gsd-path/RESEARCH.md"),
    ("skills/gsd-path-review/SKILL.md", "skills/gsd-path/REVIEW.md"),
    ("skills/gsd-path-synthesize/SKILL.md", "skills/gsd-path/SYNTHESIZE.md"),
)

SHARED_DISPATCH_TARGETS = (
    ("platforms/shared-agents/dispatch.md", "skills/gsd-path/references/dispatch.md"),
)


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
    yield from root.rglob(".DS_Store")


def mismatches(root: Path) -> Sequence[str]:
    problems = []
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
