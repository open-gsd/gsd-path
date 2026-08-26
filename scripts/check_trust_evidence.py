#!/usr/bin/env python3
"""Validate release evidence for every supported GSD Path host."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Sequence, Tuple


SCHEMA = "gsd-path/live-evidence/v1"
STEP_SCHEMA = "gsd-path/live-step-evidence/v1"
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
METADATA_DETAILS = (
    "Host and CLI version",
    "Operator",
    "Date",
    "Fixture repository",
    "Child-agent API used",
)
ARTIFACT_STEPS = {
    "Install command and result": "install",
    "Router invocation and state artifact": "router",
    "Child spawn output": "child-spawn",
    "Task branch, worktree, and landing commit": "task-landing",
    "Task Verify command and result": "task-verify",
    "Wave and final review artifacts": "reviews",
    "Archive validation output": "archive",
    "Integration merge and milestone tag": "integration",
    "Remaining `git worktree list` output": "worktrees",
    "Native guard and Git-hook results": "guards",
}
ARTIFACT_DETAILS = tuple(ARTIFACT_STEPS)
REQUIRED_DETAILS = METADATA_DETAILS + ARTIFACT_DETAILS
EMPTY_DETAIL_VALUES = frozenset({"pass", "pending", "yes", "none", "n/a"})
SUMMARY_PATHS = frozenset(
    {
        "docs/trust-validation/HOST-MATRIX.md",
        "docs/trust-validation/TRUST-EVIDENCE.md",
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


def _validate_step_artifact(path: Path, host: str, label: str) -> None:
    evidence = _read_json(path)
    if not isinstance(evidence, dict):
        raise EvidenceError(f"{path}: step evidence must be a JSON object")
    expected = {
        "schema": STEP_SCHEMA,
        "host": host,
        "step": ARTIFACT_STEPS[label],
        "result": "pass",
    }
    for key, value in expected.items():
        if evidence.get(key) != value:
            raise EvidenceError(
                f"{path}: {key} must be {value!r}, found {evidence.get(key)!r}"
            )
    for key in ("command", "output"):
        value = evidence.get(key)
        if not isinstance(value, str) or not value.strip():
            raise EvidenceError(f"{path}: step evidence requires non-empty {key}")
        if value.strip().casefold() in EMPTY_DETAIL_VALUES:
            raise EvidenceError(f"{path}: step evidence requires meaningful {key}")


def _validate_evidence_details(path: Path, host: str) -> Tuple[Path, ...]:
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
    artifacts: List[Path] = []
    for label in REQUIRED_DETAILS:
        value = details.get(label, "")
        if not value or value.casefold() in EMPTY_DETAIL_VALUES:
            raise EvidenceError(f"{path}: missing reproducible evidence detail: {label}")
        if label not in ARTIFACT_DETAILS:
            continue
        relative_artifact = Path(value)
        if relative_artifact.is_absolute():
            raise EvidenceError(f"{path}: evidence artifact must be relative: {label}")
        artifact_directory = path.with_suffix("")
        if artifact_directory.is_symlink() or not artifact_directory.is_dir():
            raise EvidenceError(f"{path}: invalid evidence artifact for {label}: {value}")
        try:
            artifact = path.parent / relative_artifact
            resolved = artifact.resolve(strict=True)
            resolved.relative_to(artifact_directory.resolve())
        except (OSError, RuntimeError, ValueError):
            raise EvidenceError(f"{path}: invalid evidence artifact for {label}: {value}")
        if artifact.is_symlink() or not resolved.is_file() or resolved.stat().st_size == 0:
            raise EvidenceError(f"{path}: invalid evidence artifact for {label}: {value}")
        if resolved in artifacts:
            raise EvidenceError(f"{path}: each evidence step requires its own artifact")
        _validate_step_artifact(resolved, host, label)
        artifacts.append(resolved)
    return tuple(artifacts)


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
    path: Path,
    host: str,
    package_version: str,
    guard_tier: str,
    candidate: str = "",
) -> Tuple[str, Tuple[Path, ...]]:
    if path.is_symlink():
        raise EvidenceError(f"evidence receipt must not be a symlink: {path}")
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
    if guard_tier not in GUARD_TIERS:
        raise EvidenceError(
            f"host manifest guard_tier must be one of {sorted(GUARD_TIERS)}: {host}"
        )
    if fields.get("guard_tier") != guard_tier:
        raise EvidenceError(
            f"{path}: guard_tier must be {guard_tier!r}, "
            f"found {fields.get('guard_tier')!r}"
        )
    return receipt_candidate, _validate_evidence_details(path, host)


def _require_current_tracked_evidence(
    repo: Path, path: Path, changed: FrozenSet[str]
) -> None:
    try:
        relative = path.relative_to(repo).as_posix()
    except ValueError:
        raise EvidenceError(f"evidence resolves outside the repository: {path}")
    try:
        _git(repo, "ls-files", "--error-unmatch", "--", relative)
    except EvidenceError:
        raise EvidenceError(f"evidence is not tracked: {relative}") from None
    if relative not in changed:
        raise EvidenceError(
            f"evidence was not added or updated after candidate: {relative}"
        )


def validate_repository(repo: Path) -> Mapping:
    repo = repo.resolve()
    if _git(repo, "status", "--porcelain", "--untracked-files=all"):
        raise EvidenceError("release evidence requires a clean worktree")
    manifest = _read_json(repo / "scripts" / "skill-resources.json")
    package = _read_json(repo / "package.json")
    host_contracts = manifest.get("hosts", {})
    if not isinstance(host_contracts, dict):
        raise EvidenceError("host manifest must contain a hosts object")
    hosts = list(host_contracts)
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
    evidence_paths: List[Path] = []
    for host in hosts:
        contract = host_contracts[host]
        if not isinstance(contract, dict):
            raise EvidenceError(f"host manifest entry must be an object: {host}")
        receipt = evidence_root / f"{host}.md"
        candidate, artifacts = _validate_receipt(
            receipt,
            host,
            version,
            contract.get("guard_tier", ""),
            candidate,
        )
        evidence_paths.extend((receipt, *artifacts))
    _git(repo, "merge-base", "--is-ancestor", candidate, "HEAD")
    changed = frozenset(
        _git(repo, "diff", "--name-only", f"{candidate}..HEAD").splitlines()
    )
    for path in evidence_paths:
        _require_current_tracked_evidence(repo, path, changed)
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
