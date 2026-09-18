#!/usr/bin/env python3
# gsd-path project runtime
"""Read-only diagnosis of a stuck GSD Path pipeline.

Runs existing helpers and git probes. Never mutates the worktree, state, or
refs. Findings name the exact helper command to retry; they never invent git.
"""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence


def _load_diagnose_modules():
    try:
        import archive_milestone
        import detect_project
        import discussion_records
        import integration
        import isolation
        import pipeline_git
        import pipeline_state
        return (
            archive_milestone,
            detect_project,
            discussion_records,
            integration,
            isolation,
            pipeline_git,
            pipeline_state,
        )
    except ModuleNotFoundError as error:
        if error.name not in {
            "archive_milestone",
            "detect_project",
            "discussion_records",
            "integration",
            "isolation",
            "pipeline_git",
            "pipeline_state",
        }:
            raise
    try:
        from scripts import (
            archive_milestone,
            detect_project,
            discussion_records,
            integration,
            isolation,
            pipeline_git,
            pipeline_state,
        )
        return (
            archive_milestone,
            detect_project,
            discussion_records,
            integration,
            isolation,
            pipeline_git,
            pipeline_state,
        )
    except ModuleNotFoundError as error:
        if error.name not in {
            "scripts",
            "scripts.archive_milestone",
            "scripts.detect_project",
            "scripts.discussion_records",
            "scripts.integration",
            "scripts.isolation",
            "scripts.pipeline_git",
            "scripts.pipeline_state",
        }:
            raise
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        sys.path.insert(0, str(shared))
        import archive_milestone
        import detect_project
        import discussion_records
        import integration
        import isolation
        import pipeline_git
        import pipeline_state
        return (
            archive_milestone,
            detect_project,
            discussion_records,
            integration,
            isolation,
            pipeline_git,
            pipeline_state,
        )


(
    archive_milestone,
    detect_project,
    discussion_records,
    integration,
    isolation,
    pipeline_git,
    pipeline_state,
) = _load_diagnose_modules()
DetectError = detect_project.DetectError
classify = detect_project.classify
IsolationError = isolation.IsolationError
_registered_worktrees = isolation._registered_worktrees
_worktree_report = isolation._worktree_report
PipelineStateError = pipeline_state.PipelineStateError
status_state = pipeline_state.status_state
validate_state = pipeline_state.validate_state

try:
    import pipeline_undo
except ModuleNotFoundError as error:
    if error.name != "pipeline_undo":
        raise
    try:
        from scripts import pipeline_undo
    except ModuleNotFoundError as error:
        if error.name not in {"scripts", "scripts.pipeline_undo"}:
            raise
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        if str(shared) not in sys.path:
            sys.path.insert(0, str(shared))
        import pipeline_undo

UndoError = pipeline_undo.UndoError
undo_preview = pipeline_undo.preview


DIAGNOSE_SCHEMA = "gsd-path/diagnose/v1"
ISOLATION_WORKTREE_PREFIXES = ("gsd-path-task/", "gsd-path-verify/")
INTEGRATION_WORKTREE_PREFIX = "gsd-path-integrate/"


class DiagnoseError(RuntimeError):
    """Raised only when the repository path itself cannot be diagnosed."""


def _probe(
    name: str,
    runner: Callable[[], object],
) -> dict[str, object]:
    try:
        value = runner()
    except (
        DetectError,
        PipelineStateError,
        UndoError,
        IsolationError,
        OSError,
        ValueError,
    ) as error:
        return {"name": name, "ok": False, "error": str(error), "result": None}
    return {"name": name, "ok": True, "error": None, "result": value}


def _finding(
    identifier: str,
    severity: str,
    evidence: str,
    retry: str,
) -> dict[str, str]:
    return {
        "id": identifier,
        "severity": severity,
        "evidence": evidence,
        "retry": retry,
    }


def _needs_user(action: str) -> str:
    return f"NEEDS-USER: {action}"


def _state_template() -> Path:
    here = Path(__file__).resolve()
    for candidate in (
        here.parents[2] / "gsd-path" / "templates" / "state.md",  # skills/<skill>/scripts
        here.parents[1] / "skills" / "gsd-path" / "templates" / "state.md",  # scripts/
    ):
        if candidate.is_file():
            return candidate
    return Path("<path-to-gsd-path-state-template>")


def _command(module: object, *arguments: object) -> str:
    script = Path(str(getattr(module, "__file__"))).resolve()
    return shlex.join([sys.executable, str(script), *map(str, arguments)])


def _route_retry(
    repo: Path,
    route: dict[str, object],
    undo_result: Optional[dict[str, object]],
) -> Optional[str]:
    action = route.get("action")
    if action == "resume-checkpoint":
        return _command(pipeline_state, "resume-checkpoint", "--repo", repo)
    if action == "resume-shipment":
        return _command(
            pipeline_state,
            "record-shipment",
            "--repo",
            repo,
            "--archive",
            route["archive"],
            "--event",
            route["event"],
        )
    if action == "resume-promotion":
        return _command(
            pipeline_state,
            "promote-next",
            "--repo",
            repo,
            "--milestone",
            route["milestone"],
            "--branch",
            route["branch"],
            "--base",
            route["base"],
            "--landing",
            route["landing"],
        )
    if action == "resume-next-handoff":
        arguments: list[object] = [
            "bind-next",
            "--repo",
            repo,
            "--branch",
            route["branch"],
            "--previous-branch",
            route["previous_branch"],
            "--ship",
            route["ship"],
            "--remote-default",
            route["remote_default"],
            "--base",
            route["base"],
            "--landing",
            route["landing"],
        ]
        if route.get("allow_remote_absent") is True:
            arguments.append("--allow-missing-previous")
        return _command(pipeline_git, *arguments)
    if action == "resume-undo":
        apply = (undo_result or {}).get("apply") or {}
        if (
            apply.get("kind") != route.get("kind")
            or apply.get("expected_head") != route.get("expected_head")
        ):
            blocked = (
                ((undo_result or {}).get("target") or {}).get("blocked") or []
            )
            reason = "; ".join(map(str, blocked)) or "undo recovery is not resumable"
            return _needs_user(reason)
        return _command(
            pipeline_undo,
            "apply",
            "--repo",
            repo,
            "--kind",
            route["kind"],
            "--expected-head",
            route["expected_head"],
        )
    return None


def _leftover_worktrees(repo: Path) -> list[dict[str, object]]:
    leftovers: list[dict[str, object]] = []
    records = _registered_worktrees(repo)
    primary = repo.resolve()
    for path, branch in records.items():
        if path == primary:
            continue
        ref = branch or ""
        short = ref.removeprefix("refs/heads/")
        if short.startswith(ISOLATION_WORKTREE_PREFIXES):
            report, error = _worktree_report(repo, path, short)
            if error or report is None:
                recovery = "needs-user"
                reason = error or "sidecar ownership could not be proven"
            elif report["clean"]:
                recovery = "retire"
                reason = None
            else:
                recovery = "needs-user"
                reason = "dirty sidecar requires its owning retry-retirement workflow"
            leftovers.append(
                {
                    "worktree": str(path),
                    "branch": short,
                    "recovery": recovery,
                    "reason": reason,
                }
            )
        elif short.startswith(INTEGRATION_WORKTREE_PREFIX):
            leftovers.append(
                {"worktree": str(path), "branch": short, "recovery": "integrate"}
            )
    return leftovers


def diagnose(repo: Path) -> dict[str, object]:
    resolved = repo.resolve()
    if not resolved.is_dir():
        raise DiagnoseError(f"repo is not a directory: {resolved}")

    probes = [
        _probe("classify", lambda: classify(resolved)),
        _probe("validate", lambda: validate_state(resolved)),
        _probe("status", lambda: status_state(resolved)),
        _probe("undo-preview", lambda: undo_preview(resolved)),
        _probe("undo-transaction", lambda: pipeline_undo.pending_transaction(resolved)),
        _probe("collect-artifacts", lambda: isolation.collect_artifact_recoveries(resolved)),
        _probe("worktrees", lambda: _leftover_worktrees(resolved)),
    ]
    by_name = {probe["name"]: probe for probe in probes}
    findings: list[dict[str, str]] = []

    classified = by_name["classify"]
    if classified["ok"]:
        verdict = (classified["result"] or {}).get("verdict")
        if verdict == "orphan":
            paths = (classified["result"] or {}).get("orphan_paths") or []
            findings.append(
                _finding(
                    "orphan",
                    "stuck",
                    "detect_project classify returned orphan: " + ", ".join(map(str, paths)),
                    _needs_user("choose orphan recovery, migration, or a new location"),
                )
            )
    else:
        findings.append(
            _finding(
                "classify",
                "stuck",
                classified["error"] or "classify failed",
                _needs_user("repair or relocate the unowned project metadata"),
            )
        )

    status_probe = by_name["status"]
    no_project = (
        classified["ok"]
        and (classified["result"] or {}).get("verdict") in {"brownfield", "greenfield"}
        and not (resolved / ".project" / "STATE.md").exists()
    )
    if no_project:
        findings.append(
            _finding(
                "no-project",
                "stuck",
                "no owned pipeline: .project/STATE.md is missing",
                _command(
                    detect_project,
                    "initialize",
                    "--repo",
                    resolved,
                    "--template",
                    _state_template(),
                ),
            )
        )
    elif not status_probe["ok"]:
        findings.append(
            _finding(
                "status",
                "stuck",
                status_probe["error"] or "status failed",
                _needs_user("repair the invalid pipeline state or helper journal"),
            )
        )
    else:
        status = status_probe["result"] or {}
        route = status.get("route") or {}
        git = status.get("git") or {}
        journals = {
            key: path
            for key, path in (status.get("journals") or {}).items()
            if path
        }
        undo_probe = by_name["undo-preview"]
        undo_result = undo_probe["result"] if undo_probe["ok"] else None
        route_retry = _route_retry(resolved, route, undo_result)
        recorded_branch = status.get("state", {}).get("branch")
        if (
            not route_retry
            and git.get("branch")
            and recorded_branch not in {None, git.get("branch")}
        ):
            findings.append(
                _finding(
                    "branch-mismatch",
                    "stuck",
                    str(route.get("reason") or "current branch does not match STATE.branch"),
                    _needs_user("restore the worktree to the branch recorded in STATE.md"),
                )
            )
        if route_retry:
            active = [f"{name}: {path}" for name, path in sorted(journals.items())]
            findings.append(
                _finding(
                    f"journal-{route.get('action')}",
                    "stuck",
                    "; ".join(active),
                    route_retry,
                )
            )
        if route.get("action") == "block":
            undo_result = by_name["undo-preview"]
            undo_target = (
                (undo_result["result"] or {}).get("target") or {}
                if undo_result["ok"]
                else {}
            )
            retry = (
                "$gsd-path-undo"
                if undo_target.get("kind")
                else _needs_user(str(route.get("reason") or "resolve the route block"))
            )
            findings.append(
                _finding(
                    "route-block",
                    "stuck",
                    str(route.get("reason") or "route returned block"),
                    retry,
                )
            )
        pending = status.get("pending_answers") or []
        if pending:
            paths = ", ".join(
                f"{item.get('answer')} -> {item.get('owner')} -> {item.get('target')}"
                for item in pending
            )
            findings.append(
                _finding(
                    "pending-answers",
                    "stuck",
                    f"{len(pending)} required discussion disposition(s): {paths}",
                    _needs_user("resolve and dispose the pending discussion answers"),
                )
            )
        if status.get("pending_error"):
            findings.append(
                _finding(
                    "pending-error",
                    "stuck",
                    str(status["pending_error"]),
                    _needs_user("repair the discussion records before routing"),
                )
            )
        dirty = git.get("dirty") or []
        if dirty:
            findings.append(
                _finding(
                    "dirty-worktree",
                    "info",
                    "uncommitted paths: " + ", ".join(dirty),
                    _command(pipeline_state, "status", "--repo", resolved),
                )
            )

        state = status.get("state") or {}
        archive = state.get("archive")
        if archive and state.get("phase") in {"ship", "shipped"}:
            try:
                archive_milestone.validate(resolved)
            except archive_milestone.ArchiveError as error:
                findings.append(
                    _finding(
                        "archive-validate",
                        "stuck",
                        str(error),
                        "$gsd-path-ship",
                    )
                )
            else:
                if state.get("phase") == "shipped" and state.get("milestone"):
                    try:
                        integration.validate_integrated(
                            resolved, str(state["milestone"]), refresh=False
                        )
                    except archive_milestone.ArchiveError as error:
                        findings.append(
                            _finding(
                                "integration",
                                "stuck",
                                str(error),
                                "$gsd-path-ship",
                            )
                        )

    undo_transaction = by_name["undo-transaction"]
    route_action = (
        ((status_probe["result"] or {}).get("route") or {}).get("action")
        if status_probe["ok"]
        else None
    )
    if (
        undo_transaction["ok"]
        and undo_transaction["result"]
        and route_action != "resume-undo"
    ):
        transaction = undo_transaction["result"]
        findings.append(
            _finding(
                "undo-transaction",
                "stuck",
                f"{transaction['kind']} undo transaction is incomplete",
                _command(
                    pipeline_undo,
                    "apply",
                    "--repo",
                    resolved,
                    "--kind",
                    transaction["kind"],
                    "--expected-head",
                    transaction["expected_head"],
                ),
            )
        )
    elif not undo_transaction["ok"]:
        findings.append(
            _finding(
                "undo-transaction",
                "stuck",
                undo_transaction["error"] or "undo transaction is unreadable",
                "$gsd-path-undo",
            )
        )

    collect_probe = by_name["collect-artifacts"]
    if collect_probe["ok"]:
        for transaction in collect_probe["result"] or []:
            arguments: list[object] = [
                "collect-artifact",
                "--repo",
                transaction["primary_worktree"],
                "--source",
                transaction["source_worktree"],
                "--base",
                transaction["base"],
                "--branch",
                transaction["branch"],
                "--source-path",
                transaction["source"],
                "--destination-path",
                transaction["destination"],
            ]
            if transaction["expected_destination"] is not None:
                arguments.extend(
                    ["--expected-destination", transaction["expected_destination"]]
                )
            findings.append(
                _finding(
                    "collect-artifact",
                    "stuck",
                    f"{transaction['stage']} journal: {transaction['journal']}",
                    _command(isolation, *arguments),
                )
            )
    else:
        findings.append(
            _finding(
                "collect-artifact",
                "stuck",
                collect_probe["error"] or "artifact collection journal is unreadable",
                _needs_user("repair the artifact collection journal"),
            )
        )

    worktrees = by_name["worktrees"]
    if worktrees["ok"]:
        leftovers = worktrees["result"] or []
        for item in leftovers:
            if item["recovery"] == "integrate":
                state = (
                    (status_probe["result"] or {}).get("state") or {}
                    if status_probe["ok"]
                    else {}
                )
                slug = state.get("milestone")
                archive = str(state.get("archive") or "").rstrip("/")
                expected_branch = None
                expected_worktree = None
                if archive:
                    expected_branch, expected_worktree = (
                        integration.integration_names(
                            resolved,
                            Path(archive).name,
                        )
                    )
                retry = (
                    _command(
                        archive_milestone,
                        "integrate",
                        "--repo",
                        resolved,
                        "--slug",
                        slug,
                    )
                    if (
                        isinstance(slug, str)
                        and slug
                        and state.get("phase") == "shipped"
                        and state.get("status") == "done"
                        and item["branch"] == expected_branch
                        and expected_worktree is not None
                        and Path(str(item["worktree"])).resolve()
                        == expected_worktree.resolve()
                    )
                    else _needs_user(
                        "reconcile the integration worktree with the shipped milestone "
                        "and canonical helper path"
                    )
                )
            elif item["recovery"] == "retire":
                retry = _command(
                    isolation,
                    "retire",
                    "--repo",
                    resolved,
                    "--worktree",
                    item["worktree"],
                    "--branch",
                    item["branch"],
                )
            else:
                retry = _needs_user(str(item["reason"]))
            findings.append(
                _finding(
                    "leftover-worktrees",
                    "info",
                    f"{item['branch']} @ {item['worktree']}",
                    retry,
                )
            )
    else:
        findings.append(
            _finding(
                "worktrees",
                "info",
                worktrees["error"] or "could not list worktrees",
                _needs_user("repair the worktree registry"),
            )
        )

    undo_probe = by_name["undo-preview"]
    if undo_probe["ok"]:
        target = (undo_probe["result"] or {}).get("target") or {}
        if target.get("kind"):
            findings.append(
                _finding(
                    "undo-available",
                    "info",
                    f"preview kind {target['kind']} at {target.get('head')}",
                    _command(pipeline_undo, "preview", "--repo", resolved),
                )
            )
    else:
        findings.append(
            _finding(
                "undo-preview",
                "info",
                undo_probe["error"] or "undo preview failed",
                _command(pipeline_undo, "preview", "--repo", resolved),
            )
        )

    stuck = [item for item in findings if item["severity"] == "stuck"]
    if any(item["id"] == "orphan" for item in stuck):
        verdict = "unowned"
    elif stuck:
        verdict = "stuck"
    else:
        verdict = "ok"

    return {
        "schema": DIAGNOSE_SCHEMA,
        "status": verdict,
        "repo": str(resolved),
        "probes": [
            {
                "name": probe["name"],
                "ok": probe["ok"],
                "error": probe["error"],
            }
            for probe in probes
        ],
        "findings": findings,
        "undo": None if not undo_probe["ok"] else undo_probe["result"],
        "status_snapshot": None if not status_probe["ok"] else status_probe["result"],
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("diagnose",))
    parser.add_argument("--repo", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        result = diagnose(args.repo)
    except DiagnoseError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
