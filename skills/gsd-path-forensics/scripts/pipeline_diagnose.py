#!/usr/bin/env python3
"""Read-only diagnosis of a stuck GSD Path pipeline.

Runs existing helpers and git probes. Never mutates the worktree, state, or
refs. Findings name the exact helper command to retry; they never invent git.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Optional, Sequence

def _load_diagnose_modules():
    try:
        import detect_project
        import isolation
        import pipeline_state
        return detect_project, isolation, pipeline_state
    except ImportError:
        pass
    try:
        from scripts import detect_project, isolation, pipeline_state
        return detect_project, isolation, pipeline_state
    except ImportError:
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        sys.path.insert(0, str(shared))
        import detect_project
        import isolation
        import pipeline_state
        return detect_project, isolation, pipeline_state


detect_project, isolation, pipeline_state = _load_diagnose_modules()
DetectError = detect_project.DetectError
classify = detect_project.classify
IsolationError = isolation.IsolationError
_registered_worktrees = isolation._registered_worktrees
PipelineStateError = pipeline_state.PipelineStateError
status_state = pipeline_state.status_state
validate_state = pipeline_state.validate_state

try:
    from pipeline_undo import UndoError, preview as undo_preview
except ImportError:
    try:
        from scripts.pipeline_undo import UndoError, preview as undo_preview
    except ImportError:
        shared = Path(__file__).resolve().parents[2] / "gsd-path" / "scripts"
        if str(shared) not in sys.path:
            sys.path.insert(0, str(shared))
        from pipeline_undo import UndoError, preview as undo_preview


DIAGNOSE_SCHEMA = "gsd-path/diagnose/v1"
PIPELINE_WORKTREE_PREFIXES = (
    "refs/heads/gsd-path-task/",
    "refs/heads/gsd-path-verify/",
    "refs/heads/gsd-path-integrate/",
)


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


def _leftover_worktrees(repo: Path) -> list[dict[str, str]]:
    leftovers: list[dict[str, str]] = []
    records = _registered_worktrees(repo)
    primary = repo.resolve()
    for path, branch in records.items():
        if path == primary:
            continue
        ref = branch or ""
        if any(ref.startswith(prefix) for prefix in PIPELINE_WORKTREE_PREFIXES):
            leftovers.append({"worktree": str(path), "branch": ref})
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
                    "python3 <bundled detect_project.py> classify --repo <absolute-root>",
                )
            )
    else:
        findings.append(
            _finding(
                "classify",
                "stuck",
                classified["error"] or "classify failed",
                "python3 <bundled detect_project.py> classify --repo <absolute-root>",
            )
        )

    status_probe = by_name["status"]
    if not status_probe["ok"]:
        findings.append(
            _finding(
                "status",
                "stuck",
                status_probe["error"] or "status failed",
                "python3 <bundled pipeline_state.py> status --repo <absolute-root>",
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
        if git.get("branch") and status.get("state", {}).get("branch") not in {
            None,
            git.get("branch"),
        }:
            findings.append(
                _finding(
                    "branch-mismatch",
                    "stuck",
                    str(route.get("reason") or "current branch does not match STATE.branch"),
                    "python3 <bundled pipeline_state.py> route --repo <absolute-root>",
                )
            )
        for name, path in sorted(journals.items()):
            retries = {
                "checkpoint": "python3 <bundled pipeline_state.py> resume-checkpoint --repo <absolute-root>",
                "shipment": "python3 <bundled pipeline_state.py> record-shipment --repo <absolute-root> --archive <STATE.archive> --event <journal.event>",
                "promotion": "python3 <bundled pipeline_state.py> promote-next --repo <absolute-root> --milestone <journal.milestone> --branch <journal.branch> --integrate <journal.integrate>",
                "bind_next": "python3 <bundled pipeline_git.py> bind-next with the journal's typed fields",
                "abandon": "python3 <bundled archive_milestone.py> abandon --repo <absolute-root> (via $gsd-path-build)",
                "collect_artifact": "python3 <bundled isolation.py> collect-artifact using the journal request",
            }
            findings.append(
                _finding(
                    f"journal-{name}",
                    "stuck",
                    f"{name} journal present: {path}",
                    retries.get(name, "invoke $gsd-path and follow route.action"),
                )
            )
        if route.get("action") == "block":
            findings.append(
                _finding(
                    "route-block",
                    "stuck",
                    str(route.get("reason") or "route returned block"),
                    "python3 <bundled pipeline_state.py> route --repo <absolute-root>",
                )
            )
        pending = status.get("pending_answers") or []
        if pending:
            findings.append(
                _finding(
                    "pending-answers",
                    "info",
                    f"{len(pending)} required discussion follow-up(s) without disposition",
                    "python3 <bundled discussion_records.py> pending --repo <absolute-root>",
                )
            )
        if status.get("pending_error"):
            findings.append(
                _finding(
                    "pending-error",
                    "stuck",
                    str(status["pending_error"]),
                    "python3 <bundled discussion_records.py> pending --repo <absolute-root>",
                )
            )
        dirty = git.get("dirty") or []
        if dirty:
            findings.append(
                _finding(
                    "dirty-worktree",
                    "info",
                    "uncommitted paths: " + ", ".join(dirty),
                    "python3 <bundled pipeline_state.py> status --repo <absolute-root>",
                )
            )

        state = status.get("state") or {}
        archive = state.get("archive")
        if archive and state.get("phase") in {"ship", "shipped"}:
            try:
                try:
                    from archive_milestone import ArchiveError, validate, validate_integrated
                except ImportError:  # pragma: no cover
                    from scripts.archive_milestone import (
                        ArchiveError,
                        validate,
                        validate_integrated,
                    )
            except ImportError:
                findings.append(
                    _finding(
                        "archive-helper",
                        "info",
                        "archive_milestone helper is unavailable in this skill copy",
                        "python3 <bundled archive_milestone.py> validate --repo <absolute-root>",
                    )
                )
            else:
                try:
                    validate(resolved)
                except ArchiveError as error:
                    findings.append(
                        _finding(
                            "archive-validate",
                            "stuck",
                            str(error),
                            "python3 <bundled archive_milestone.py> validate --repo <absolute-root>",
                        )
                    )
                else:
                    if state.get("phase") == "shipped" and state.get("milestone"):
                        try:
                            validate_integrated(resolved, str(state["milestone"]))
                        except ArchiveError as error:
                            findings.append(
                                _finding(
                                    "integration",
                                    "stuck",
                                    str(error),
                                    "python3 <bundled archive_milestone.py> validate-integrated --repo <absolute-root> --slug <STATE.milestone>",
                                )
                            )

    worktrees = by_name["worktrees"]
    if worktrees["ok"]:
        leftovers = worktrees["result"] or []
        if leftovers:
            listed = ", ".join(
                f"{item['branch']} @ {item['worktree']}" for item in leftovers
            )
            findings.append(
                _finding(
                    "leftover-worktrees",
                    "info",
                    listed,
                    "python3 <bundled isolation.py> retire --repo <absolute-root> --worktree <path> --branch <branch>",
                )
            )
    else:
        findings.append(
            _finding(
                "worktrees",
                "info",
                worktrees["error"] or "could not list worktrees",
                "git worktree list --porcelain",
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
                    "python3 <bundled pipeline_undo.py> preview --repo <absolute-root>",
                )
            )
    else:
        findings.append(
            _finding(
                "undo-preview",
                "info",
                undo_probe["error"] or "undo preview failed",
                "python3 <bundled pipeline_undo.py> preview --repo <absolute-root>",
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
