#!/usr/bin/env python3
"""Validate release evidence for every supported GSD Path host."""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path, PurePosixPath
from typing import Dict, FrozenSet, List, Mapping, Sequence, Tuple

try:
    from archive_milestone import (
        ArchiveError,
        require_generated_integration_commit,
        require_published_integration,
    )
    from pipeline_git import bound_branch_name, milestone_number, ship_subject
except ImportError:
    from scripts.archive_milestone import (
        ArchiveError,
        require_generated_integration_commit,
        require_published_integration,
    )
    from scripts.pipeline_git import bound_branch_name, milestone_number, ship_subject


SCHEMA = "gsd-path/live-evidence/v1"
STEP_SCHEMA = "gsd-path/live-step-evidence/v1"
RUN_MANIFEST_SCHEMA = "gsd-path/live-run-manifest/v1"
GUARD_EVIDENCE_SCHEMA = "gsd-path/live-guard-evidence/v1"
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
STEP_STRING_FIELDS = {
    "install": ("host_version", "install_root", "candidate", "package_version"),
    "router": ("state_artifact",),
    "child-spawn": ("child_id",),
    "task-landing": (
        "fixture_bundle",
        "run_manifest",
        "fixture_base_commit",
        "task_branch",
        "task_worktree",
        "landing_commit",
    ),
    "task-verify": ("verify_artifact",),
    "reviews": ("wave_review_artifact", "final_review_artifact"),
    "archive": ("archive_path",),
    "integration": (
        "fixture_bundle",
        "run_manifest",
        "ship_commit",
        "bound_branch",
        "default_branch",
        "integration_commit",
        "milestone_tag",
    ),
    "worktrees": ("primary_worktree",),
    "guards": ("guard_artifact",),
}
STEP_EXACT_FIELDS = {
    "install": {"exit_code": 0},
    "router": {"state_phase": "shipped"},
    "child-spawn": {"child_status": "completed"},
    "task-verify": {"verify_exit_code": 0},
    "archive": {"validation_exit_code": 0},
}
SUMMARY_PATHS = frozenset(
    {
        "docs/trust-validation/HOST-MATRIX.md",
        "docs/trust-validation/TRUST-EVIDENCE.md",
    }
)
WORKTREE_RECORD_KEYS = frozenset(
    {"worktree", "HEAD", "branch", "bare", "detached", "locked", "prunable"}
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


def _required_string(evidence: Mapping, key: str, path: Path) -> str:
    value = evidence.get(key)
    if (
        not isinstance(value, str)
        or not value.strip()
        or value.strip().casefold() in EMPTY_DETAIL_VALUES
    ):
        raise EvidenceError(f"{path}: step evidence requires meaningful {key}")
    return value.strip()


def _validate_step_artifact(
    path: Path, host: str, label: str, guard_tier: str
) -> Mapping:
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
    step = ARTIFACT_STEPS[label]
    for key in ("run_id", "command", "output", *STEP_STRING_FIELDS.get(step, ())):
        _required_string(evidence, key, path)
    for key, value in STEP_EXACT_FIELDS.get(step, {}).items():
        if evidence.get(key) != value:
            raise EvidenceError(f"{path}: {key} must be {value!r}")
    if step == "guards":
        expected_native = "not-applicable" if guard_tier == "git-only" else "pass"
        expected_guards = {
            "declared_tier": guard_tier,
            "native_guard": expected_native,
            "git_hooks": "pass",
        }
        for key, value in expected_guards.items():
            if evidence.get(key) != value:
                raise EvidenceError(f"{path}: {key} must be {value!r}")
    return evidence


def _normalized_worktree_path(value: str, path: Path) -> str:
    normalized = value.replace("\\", "/").rstrip("/") or "/"
    parts = PurePosixPath(normalized).parts
    if (
        ".." in parts
        or not (
            normalized.startswith("/")
            or re.match(r"^[A-Za-z]:/", normalized)
        )
    ):
        raise EvidenceError(f"{path}: worktree path must be absolute: {value}")
    return normalized


def _worktree_records(output: str, path: Path) -> Tuple[Mapping[str, str], ...]:
    records: List[Mapping[str, str]] = []
    record: Dict[str, str] = {}
    for line in (*output.splitlines(), ""):
        if not line:
            if not record:
                continue
            missing = {"worktree", "HEAD"} - set(record)
            states = {"branch", "bare", "detached"} & set(record)
            if missing or len(states) != 1:
                raise EvidenceError(f"{path}: invalid git worktree porcelain record")
            if not re.fullmatch(r"[0-9a-f]{40}", record["HEAD"]):
                raise EvidenceError(f"{path}: worktree HEAD must be a full Git SHA")
            record["worktree"] = _normalized_worktree_path(record["worktree"], path)
            records.append(record)
            record = {}
            continue
        key, separator, value = line.partition(" ")
        if key not in WORKTREE_RECORD_KEYS or key in record:
            raise EvidenceError(f"{path}: invalid git worktree porcelain line: {line}")
        record[key] = value if separator else ""
    if not records:
        raise EvidenceError(f"{path}: git worktree porcelain output is empty")
    return tuple(records)


def _resolved_artifact(
    path: Path, artifact_directory: Path, value: str, label: str
) -> Path:
    relative_artifact = Path(value)
    if relative_artifact.is_absolute():
        raise EvidenceError(f"{path}: evidence artifact must be relative: {label}")
    try:
        artifact = path.parent / relative_artifact
        resolved = artifact.resolve(strict=True)
        resolved.relative_to(artifact_directory.resolve())
    except (OSError, RuntimeError, ValueError):
        raise EvidenceError(f"{path}: invalid evidence artifact for {label}: {value}")
    if artifact.is_symlink() or not resolved.is_file() or resolved.stat().st_size == 0:
        raise EvidenceError(f"{path}: invalid evidence artifact for {label}: {value}")
    return resolved


def _full_sha(evidence: Mapping, key: str, path: Path) -> str:
    value = evidence.get(key)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{40}", value):
        raise EvidenceError(f"{path}: {key} must be a full lowercase Git SHA")
    return value


def _bundle_path(value: str, label: str, bundle: Path) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or "\\" in value
        or ":" in value
        or path.is_absolute()
        or ".." in path.parts
        or not path.parts
        or path.parts[0] != ".project"
    ):
        raise EvidenceError(f"{bundle}: {label} must be a safe .project path")
    return path.as_posix()


def _bundle_object_type(fixture: Path, commit: str, path: str, bundle: Path) -> str:
    try:
        return _git(fixture, "cat-file", "-t", f"{commit}:{path}")
    except EvidenceError:
        raise EvidenceError(f"{bundle}: bundled artifact is missing: {path}") from None


def _bundle_blob(fixture: Path, commit: str, path: str, bundle: Path) -> str:
    if _bundle_object_type(fixture, commit, path, bundle) != "blob":
        raise EvidenceError(f"{bundle}: bundled artifact must be a file: {path}")
    content = _git(fixture, "show", f"{commit}:{path}")
    if not content:
        raise EvidenceError(f"{bundle}: bundled artifact is empty: {path}")
    return content


def _validate_shipped_state(
    content: str, path: str, archive: str, bundle: Path
) -> None:
    if path != ".project/STATE.md":
        raise EvidenceError(f"{bundle}: bundled state must be .project/STATE.md")
    with tempfile.TemporaryDirectory(prefix="gsd-path-state-evidence-") as temporary:
        root = Path(temporary)
        state_path = root / path
        state_path.parent.mkdir(parents=True)
        state_path.write_text(content, encoding="utf-8")
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().with_name("pipeline_state.py")),
                "validate",
                "--repo",
                str(root),
            ],
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise EvidenceError(f"{bundle}: bundled state is invalid: {detail}")
    try:
        state = json.loads(result.stdout)["state"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise EvidenceError(
            f"{bundle}: bundled state validator returned invalid JSON"
        ) from error
    if state.get("phase") != "shipped" or state.get("status") != "done":
        raise EvidenceError(f"{bundle}: bundled state must be shipped and done")
    if str(state.get("archive", "")).rstrip("/") != archive.rstrip("/"):
        raise EvidenceError(f"{bundle}: bundled state archive does not match evidence")


def _validate_run_artifacts(
    fixture: Path,
    bundle: Path,
    host: str,
    guard_tier: str,
    integration_commit: str,
    steps: Mapping[str, Mapping],
    candidate: str,
    package_version: str,
) -> None:
    landing = steps["task-landing"]
    integration = steps["integration"]
    run_id = _required_string(landing, "run_id", bundle)
    manifest_path = _bundle_path(
        _required_string(landing, "run_manifest", bundle), "run_manifest", bundle
    )
    if _required_string(integration, "run_manifest", bundle) != manifest_path:
        raise EvidenceError(f"{bundle}: landing and integration must use one run manifest")
    try:
        manifest = json.loads(
            _bundle_blob(fixture, integration_commit, manifest_path, bundle)
        )
    except json.JSONDecodeError as error:
        raise EvidenceError(f"{bundle}: run manifest is not valid JSON") from error
    if not isinstance(manifest, dict):
        raise EvidenceError(f"{bundle}: run manifest must be a JSON object")
    expected_artifacts = {
        "state": _required_string(steps["router"], "state_artifact", bundle),
        "verify": _required_string(steps["task-verify"], "verify_artifact", bundle),
        "wave_review": _required_string(
            steps["reviews"], "wave_review_artifact", bundle
        ),
        "final_review": _required_string(
            steps["reviews"], "final_review_artifact", bundle
        ),
        "archive": _required_string(steps["archive"], "archive_path", bundle),
        "guards": _required_string(steps["guards"], "guard_artifact", bundle),
    }
    expected_manifest = {
        "schema": RUN_MANIFEST_SCHEMA,
        "host": host,
        "run_id": run_id,
        "host_version": _required_string(steps["install"], "host_version", bundle),
        "candidate": candidate,
        "package_version": package_version,
        "child_id": _required_string(steps["child-spawn"], "child_id", bundle),
        "guard_tier": guard_tier,
        "fixture_base_commit": _full_sha(landing, "fixture_base_commit", bundle),
        "landing_commit": _full_sha(landing, "landing_commit", bundle),
        "task_branch": _required_string(landing, "task_branch", bundle),
        "bound_branch": _required_string(integration, "bound_branch", bundle),
        "default_branch": _required_string(integration, "default_branch", bundle),
        "milestone_tag": _required_string(integration, "milestone_tag", bundle),
        "artifacts": expected_artifacts,
    }
    for key, value in expected_manifest.items():
        if manifest.get(key) != value:
            raise EvidenceError(f"{bundle}: run manifest {key} does not match evidence")
    paths = {
        label: _bundle_path(value, f"{label} artifact", bundle)
        for label, value in expected_artifacts.items()
    }
    archive = paths["archive"]
    for label in ("verify", "wave_review", "final_review", "guards"):
        if not paths[label].startswith(f"{archive}/"):
            raise EvidenceError(f"{bundle}: {label} artifact must be inside archive")
    if _bundle_object_type(fixture, integration_commit, archive, bundle) != "tree":
        raise EvidenceError(f"{bundle}: archive artifact must be a directory")
    if not _git(
        fixture, "ls-tree", "-r", "--name-only", integration_commit, "--", archive
    ):
        raise EvidenceError(f"{bundle}: archive artifact is empty")
    state = _bundle_blob(fixture, integration_commit, paths["state"], bundle)
    _validate_shipped_state(state, paths["state"], archive, bundle)
    for label in ("verify", "wave_review", "final_review"):
        _bundle_blob(fixture, integration_commit, paths[label], bundle)
    try:
        guard_evidence = json.loads(
            _bundle_blob(fixture, integration_commit, paths["guards"], bundle)
        )
    except json.JSONDecodeError as error:
        raise EvidenceError(f"{bundle}: bundled guard evidence is not valid JSON") from error
    if not isinstance(guard_evidence, dict):
        raise EvidenceError(f"{bundle}: bundled guard evidence must be a JSON object")
    expected_guard = {
        "schema": GUARD_EVIDENCE_SCHEMA,
        "host": host,
        "run_id": run_id,
        "declared_tier": guard_tier,
        "native_guard": steps["guards"].get("native_guard"),
        "git_hooks": steps["guards"].get("git_hooks"),
    }
    for key, value in expected_guard.items():
        if guard_evidence.get(key) != value:
            raise EvidenceError(f"{bundle}: bundled guard {key} does not match evidence")


def _validate_git_bundle(
    bundle: Path,
    host: str,
    guard_tier: str,
    steps: Mapping[str, Mapping],
    candidate: str,
    package_version: str,
) -> None:
    landing = steps["task-landing"]
    integration = steps["integration"]
    base = _full_sha(landing, "fixture_base_commit", bundle)
    landing_commit = _full_sha(landing, "landing_commit", bundle)
    ship_commit = _full_sha(integration, "ship_commit", bundle)
    integration_commit = _full_sha(integration, "integration_commit", bundle)
    bound_branch = _required_string(integration, "bound_branch", bundle)
    default_branch = _required_string(integration, "default_branch", bundle)
    milestone_tag = _required_string(integration, "milestone_tag", bundle)
    if not re.fullmatch(r"milestone/[0-9]{3}-[A-Za-z0-9._-]+", milestone_tag):
        raise EvidenceError(f"{bundle}: milestone_tag has an invalid name")
    with tempfile.TemporaryDirectory(prefix=f"gsd-path-{host}-evidence-") as temporary:
        fixture = Path(temporary) / "fixture.git"
        _git(
            bundle.parent,
            "clone",
            "--mirror",
            "--quiet",
            "--",
            str(bundle),
            str(fixture),
        )
        for name, commit in (
            ("fixture_base_commit", base),
            ("landing_commit", landing_commit),
            ("ship_commit", ship_commit),
            ("integration_commit", integration_commit),
        ):
            try:
                _git(fixture, "cat-file", "-e", f"{commit}^{{commit}}")
            except EvidenceError:
                raise EvidenceError(
                    f"{bundle}: {name} is not present in the bundle"
                ) from None
        for ancestor, descendant, relationship in (
            (base, landing_commit, "fixture base must precede landing commit"),
            (landing_commit, ship_commit, "landing commit must precede ship commit"),
        ):
            try:
                _git(fixture, "merge-base", "--is-ancestor", ancestor, descendant)
            except EvidenceError:
                raise EvidenceError(f"{bundle}: {relationship}") from None
        archive_path = _bundle_path(
            _required_string(steps["archive"], "archive_path", bundle),
            "archive_path",
            bundle,
        )
        archive_name = PurePosixPath(archive_path).name
        try:
            expected_branch = bound_branch_name(milestone_number(archive_name))
            expected_ship_subject = ship_subject(archive_name)
        except ValueError as error:
            raise EvidenceError(f"{bundle}: archive name is invalid") from error
        if bound_branch != expected_branch:
            raise EvidenceError(f"{bundle}: bound_branch does not match archive")
        if default_branch != "main":
            raise EvidenceError(f"{bundle}: default_branch must be main")
        if milestone_tag != f"milestone/{archive_name}":
            raise EvidenceError(f"{bundle}: milestone_tag does not match archive")
        if _git(fixture, "show", "-s", "--format=%s", ship_commit) != expected_ship_subject:
            raise EvidenceError(f"{bundle}: ship commit subject is not canonical")
        try:
            require_generated_integration_commit(
                fixture,
                integration_commit,
                archive_path,
                archive_name,
                ship_commit,
                default_branch,
                bound_branch,
                first_parent=base,
            )
            remote_default = _git(
                fixture, "rev-parse", f"refs/remotes/origin/{default_branch}"
            )
            if remote_default != integration_commit:
                raise EvidenceError(
                    f"{bundle}: published default branch is not at integration_commit"
                )
            require_published_integration(
                fixture,
                bound_branch,
                ship_commit,
                milestone_tag,
                integration_commit,
            )
        except ArchiveError as error:
            raise EvidenceError(f"{bundle}: {error}") from error
        tag_ref = f"refs/tags/{milestone_tag}"
        try:
            tag_type = _git(fixture, "cat-file", "-t", tag_ref)
            tagged_commit = _git(fixture, "rev-parse", f"{tag_ref}^{{commit}}")
        except EvidenceError:
            raise EvidenceError(f"{bundle}: milestone tag is not present") from None
        if tag_type != "tag" or tagged_commit != integration_commit:
            raise EvidenceError(
                f"{bundle}: milestone tag must be annotated at integration_commit"
            )
        task_branch = _required_string(landing, "task_branch", bundle)
        try:
            _git(fixture, "check-ref-format", "--branch", task_branch)
        except EvidenceError:
            raise EvidenceError(f"{bundle}: task_branch has an invalid name") from None
        if _git_ref_exists(fixture, f"refs/heads/{task_branch}"):
            raise EvidenceError(f"{bundle}: task branch was not retired")
        _validate_run_artifacts(
            fixture,
            bundle,
            host,
            guard_tier,
            integration_commit,
            steps,
            candidate,
            package_version,
        )


def _validate_evidence_details(
    path: Path,
    host: str,
    guard_tier: str,
    candidate: str,
    package_version: str,
) -> Tuple[Path, ...]:
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
    artifact_directory = path.with_suffix("")
    if artifact_directory.is_symlink() or not artifact_directory.is_dir():
        raise EvidenceError(f"{path}: evidence artifact directory is missing")
    artifacts: List[Path] = []
    steps: Dict[str, Mapping] = {}
    for label in ARTIFACT_DETAILS:
        value = details[label]
        resolved = _resolved_artifact(path, artifact_directory, value, label)
        if resolved in artifacts:
            raise EvidenceError(f"{path}: each evidence step requires its own artifact")
        steps[ARTIFACT_STEPS[label]] = _validate_step_artifact(
            resolved, host, label, guard_tier
        )
        artifacts.append(resolved)
    landing = steps["task-landing"]
    integration = steps["integration"]
    install = steps["install"]
    if _full_sha(install, "candidate", path) != candidate:
        raise EvidenceError(f"{path}: install candidate does not match receipt")
    if _required_string(install, "package_version", path) != package_version:
        raise EvidenceError(f"{path}: install package_version does not match receipt")
    run_ids = {
        _required_string(evidence, "run_id", path) for evidence in steps.values()
    }
    if len(run_ids) != 1:
        raise EvidenceError(f"{path}: all evidence steps must use one run_id")
    landing_bundle = _required_string(landing, "fixture_bundle", path)
    integration_bundle = _required_string(integration, "fixture_bundle", path)
    if landing_bundle != integration_bundle:
        raise EvidenceError(f"{path}: landing and integration must use one fixture bundle")
    worktree_step = steps["worktrees"]
    records = _worktree_records(_required_string(worktree_step, "output", path), path)
    primary_worktree = _normalized_worktree_path(
        _required_string(worktree_step, "primary_worktree", path), path
    )
    task_worktree = _normalized_worktree_path(
        _required_string(landing, "task_worktree", path), path
    )
    task_ref = f"refs/heads/{_required_string(landing, 'task_branch', path)}"
    primary = next(
        (
            record
            for record in records
            if record["worktree"].casefold() == primary_worktree.casefold()
        ),
        None,
    )
    if (
        primary is None
        or not primary.get("branch", "").startswith("refs/heads/")
        or primary["HEAD"] != _full_sha(integration, "integration_commit", path)
    ):
        raise EvidenceError(
            f"{path}: primary worktree must be on a named branch at integration HEAD"
        )
    if any(
        record["worktree"].casefold() == task_worktree.casefold()
        or record.get("branch") == task_ref
        for record in records
    ):
        raise EvidenceError(f"{path}: task worktree was not retired")
    bundle = _resolved_artifact(
        path, artifact_directory, landing_bundle, "fixture Git bundle"
    )
    _validate_git_bundle(
        bundle, host, guard_tier, steps, candidate, package_version
    )
    artifacts.append(bundle)
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


def _git_ref_exists(repo: Path, ref: str) -> bool:
    result = subprocess.run(
        ["git", "show-ref", "--verify", "--quiet", ref],
        cwd=repo,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode not in {0, 1}:
        raise EvidenceError(f"git show-ref failed: {result.stderr.strip()}")
    return result.returncode == 0


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
    return receipt_candidate, _validate_evidence_details(
        path,
        host,
        guard_tier,
        receipt_candidate,
        package_version,
    )


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
