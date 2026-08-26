#!/usr/bin/env python3
"""Validate release evidence for every supported GSD Path host."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Sequence


SCHEMA = "gsd-path/live-evidence/v1"
PIPELINE = "gsd-path/v2"
PASS_FIELDS = (
    "verdict",
    "child_spawn",
    "state",
    "task_verify",
    "wave_review",
    "final_review",
    "archive",
    "integration",
)
GUARD_TIERS = frozenset({"native-fail-closed", "native-limited", "git-only"})
REQUIRED_DETAILS = (
    "Host and CLI version",
    "Operator",
    "Date",
    "Fixture repository",
    "Child-agent API used",
    "Install command and result",
    "Router invocation and state artifact",
    "Child spawn output",
    "Task branch, worktree, and landing commit",
    "Task Verify command and result",
    "Wave and final review artifacts",
    "Archive validation output",
    "Integration merge and milestone tag",
    "Remaining `git worktree list` output",
    "Native guard and Git-hook results",
)
EMPTY_DETAIL_VALUES = frozenset({"pass", "pending", "yes", "none", "n/a"})
SUMMARY_PATHS = frozenset(
    {
        "docs/trust-validation/HOST-MATRIX.md",
        "docs/trust-validation/TRUST-EVIDENCE.md",
        "docs/trust-validation/TRUST-VALIDATION-SPEC.md",
    }
)


class EvidenceError(RuntimeError):
    pass


def _read_json(path: Path) -> Mapping:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceError(f"cannot read JSON contract {path}: {error}") from error


def _frontmatter(path: Path) -> Dict[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceError(f"cannot read evidence {path}: {error}") from error
    if not lines or lines[0] != "---":
        raise EvidenceError(f"evidence is missing frontmatter: {path}")
    fields: Dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return fields
        if ":" not in line:
            raise EvidenceError(f"invalid evidence frontmatter line in {path}: {line}")
        key, value = line.split(":", 1)
        key, value = key.strip(), value.strip()
        if not key or not value or key in fields:
            raise EvidenceError(f"invalid evidence field in {path}: {key or line}")
        fields[key] = value
    raise EvidenceError(f"evidence frontmatter is not closed: {path}")


def _validate_evidence_details(path: Path) -> None:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceError(f"cannot read evidence {path}: {error}") from error
    details: Dict[str, str] = {}
    for line in lines:
        if not line.startswith("- ") or ":" not in line:
            continue
        label, value = line[2:].split(":", 1)
        if label in REQUIRED_DETAILS:
            if label in details:
                raise EvidenceError(f"{path}: duplicate evidence detail: {label}")
            details[label] = value.strip()
    for label in REQUIRED_DETAILS:
        value = details.get(label, "")
        if not value or value.casefold() in EMPTY_DETAIL_VALUES:
            raise EvidenceError(f"{path}: missing reproducible evidence detail: {label}")


def _git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise EvidenceError(
            f"git {' '.join(arguments)} failed: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _validate_receipt(
    path: Path, host: str, package_version: str, candidate: str = ""
) -> str:
    fields = _frontmatter(path)
    expected = {
        "schema": SCHEMA,
        "host": host,
        "package": package_version,
        "pipeline": PIPELINE,
    }
    for key, value in expected.items():
        if fields.get(key) != value:
            raise EvidenceError(
                f"{path}: {key} must be {value!r}, found {fields.get(key)!r}"
            )
    receipt_candidate = fields.get("candidate", "")
    if not re.fullmatch(r"[0-9a-f]{40}", receipt_candidate):
        raise EvidenceError(f"{path}: candidate must be a full lowercase Git SHA")
    if candidate and receipt_candidate != candidate:
        raise EvidenceError(
            f"{path}: candidate {receipt_candidate} does not match {candidate}"
        )
    for field in PASS_FIELDS:
        if fields.get(field) != "pass":
            raise EvidenceError(
                f"{path}: {field} must be 'pass', found {fields.get(field)!r}"
            )
    if fields.get("guard_tier") not in GUARD_TIERS:
        raise EvidenceError(
            f"{path}: guard_tier must be one of {sorted(GUARD_TIERS)}"
        )
    _validate_evidence_details(path)
    return receipt_candidate


def validate_repository(repo: Path) -> Mapping:
    repo = repo.resolve()
    manifest = _read_json(repo / "scripts" / "skill-resources.json")
    package = _read_json(repo / "package.json")
    hosts = list(manifest.get("hosts", {}))
    version = package.get("version")
    if not hosts:
        raise EvidenceError("host manifest is empty")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9A-Za-z.+-]+", version):
        raise EvidenceError("package version is missing or invalid")
    evidence_root = (
        repo / "docs" / "trust-validation" / "evidence" / "releases" / version
    )
    missing = [host for host in hosts if not (evidence_root / f"{host}.md").is_file()]
    if missing:
        raise EvidenceError(f"missing host evidence: {', '.join(missing)}")
    extra = sorted(path.stem for path in evidence_root.glob("*.md") if path.stem not in hosts)
    if extra:
        raise EvidenceError(f"unexpected host evidence: {', '.join(extra)}")

    candidate = ""
    for host in hosts:
        candidate = _validate_receipt(
            evidence_root / f"{host}.md", host, version, candidate
        )
    _git(repo, "merge-base", "--is-ancestor", candidate, "HEAD")
    changed = _git(repo, "diff", "--name-only", f"{candidate}..HEAD").splitlines()
    evidence_prefix = f"docs/trust-validation/evidence/releases/{version}/"
    disallowed = [
        path
        for path in changed
        if not path.startswith(evidence_prefix) and path not in SUMMARY_PATHS
    ]
    if disallowed:
        raise EvidenceError(
            "non-evidence changes follow the tested candidate: " + ", ".join(disallowed)
        )
    return {"candidate": candidate, "hosts": hosts, "version": version}


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    argument_parser.add_argument("--repo", type=Path, default=Path.cwd())
    return argument_parser


def main(argv: Sequence[str] = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        result = validate_repository(arguments.repo)
    except EvidenceError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
