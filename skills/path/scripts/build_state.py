#!/usr/bin/env python3
"""Build task readiness, landing reconciliation, and the verify ledger."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from check_task_briefs import _frontmatter, _sections
    from isolation import (
        VERIFY_LEDGER_PATH,
        IsolationError,
        recover as recover_isolation,
        verify_landed_task_files,
    )
    from pipeline_git import task_commit_subject
    from pipeline_state import PipelineStateError, load_state
    import _common
except ImportError:  # pragma: no cover - package imports used by tests
    from scripts.check_task_briefs import _frontmatter, _sections
    from scripts.isolation import (
        VERIFY_LEDGER_PATH,
        IsolationError,
        recover as recover_isolation,
        verify_landed_task_files,
    )
    from scripts.pipeline_git import task_commit_subject
    from scripts.pipeline_state import PipelineStateError, load_state
    from scripts import _common


DEFAULT_PROJECT_DIR = ".project"
TASK_ID_RE = re.compile(r"^T\d{3}$")
TASK_FILE_RE = re.compile(r"^(?P<id>T\d{3})-[a-z0-9][a-z0-9-]*\.md$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# recover verdicts that count as landed, mapped to their evidence classification.
LANDED_VERDICTS = {"recovered": "proven-landed", "attested": "attested"}
WAVE_HEADING_RE = re.compile(r"(?m)^## Wave (?P<wave>\d+)\b.*$")
VERIFY_HEAVY_RE = re.compile(r"(?m)^Heavy:\s*(?P<value>yes|no)\s*(?:<!--.*-->)?\s*$")
VALID_TASK_STATUSES = {"pending", "in-progress", "done", "failed", "blocked"}
VERIFY_RESULTS = _common.VERIFY_RESULTS


class BuildStateError(RuntimeError):
    """A typed, user-actionable build state error."""

    def __init__(
        self, code: str, message: str, details: Optional[Mapping[str, object]] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class Task:
    task_id: str
    title: str
    wave: int
    deps: Tuple[str, ...]
    files: Tuple[str, ...]
    status: str
    agent: Optional[str]
    base: Optional[str]
    worktree: Optional[str]
    task_branch: Optional[str]
    task_file: str
    verify_heavy: bool


@dataclass(frozen=True)
class Project:
    repo: Path
    branch: str
    head: str
    tasks: Tuple[Task, ...]
    tasks_dir: Path


_run_git = _common.run_git


def _git_output(repo: Path, *arguments: str) -> str:
    result = _run_git(repo, *arguments)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip() or "git command failed"
        raise BuildStateError("git-error", detail)
    return result.stdout.strip()


def _repo_root(value: str) -> Path:
    candidate = Path(value).resolve()
    if not candidate.is_dir():
        raise BuildStateError("invalid-repo", f"repository is not a directory: {candidate}")
    result = _run_git(candidate, "rev-parse", "--show-toplevel")
    if result.returncode != 0:
        raise BuildStateError("invalid-repo", f"not a Git repository: {candidate}")
    root = Path(result.stdout.strip()).resolve()
    if root != candidate:
        raise BuildStateError("invalid-repo", f"--repo must be the Git root: {root}")
    return root


def _project_path(repo: Path, value: str) -> Tuple[str, Path]:
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise BuildStateError(
            "invalid-project-dir", "--project-dir must be a repo-relative path"
        )
    normalized = str(relative)
    path = repo.joinpath(*relative.parts)
    if not path.is_dir() or path.is_symlink():
        raise BuildStateError(
            "invalid-project-dir", f"project directory is missing or unsafe: {normalized}"
        )
    return normalized, path


def _read_file(path: Path, label: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise BuildStateError("missing-input", f"{label} is missing or unsafe: {path}")
    return path.read_text(encoding="utf-8")


def _parse_frontmatter(text: str, label: str) -> Dict[str, object]:
    fields, error = _frontmatter(text)
    if fields is None:
        raise BuildStateError("invalid-frontmatter", f"{label}: {error}")
    return fields


def _verify_heavy(text: str, label: str) -> bool:
    """Read the optional `Heavy: yes|no` line of the task's ## Verify section."""

    matches = VERIFY_HEAVY_RE.findall(_sections(text).get("Verify", ""))
    if len(matches) > 1:
        raise BuildStateError("invalid-task-file", f"{label} repeats Verify Heavy")
    return bool(matches) and matches[0] == "yes"


def _required_string(fields: Mapping[str, object], field: str, label: str) -> str:
    value = fields.get(field)
    if not isinstance(value, str) or not value.strip():
        raise BuildStateError("invalid-frontmatter", f"{label} has invalid {field}")
    return value.strip()


def _nullable_string(fields: Mapping[str, object], field: str, label: str) -> Optional[str]:
    value = fields.get(field)
    if not isinstance(value, str):
        raise BuildStateError("invalid-frontmatter", f"{label} has invalid {field}")
    cleaned = value.strip()
    return None if cleaned in {"", "null"} else cleaned


def _normalize_list(
    value: object, label: str, *, task_ids: bool = False, paths: bool = False
) -> Tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildStateError("invalid-frontmatter", f"{label} must be a list")
    normalized: List[str] = []
    for raw in value:
        item = raw.strip()
        if task_ids and not TASK_ID_RE.fullmatch(item):
            raise BuildStateError("invalid-frontmatter", f"{label} has invalid task id: {item}")
        if paths:
            candidate = PurePosixPath(item)
            if candidate.is_absolute() or not candidate.parts or ".." in candidate.parts:
                raise BuildStateError("invalid-frontmatter", f"{label} has invalid path: {item}")
            item = str(candidate)
        if not item:
            raise BuildStateError("invalid-frontmatter", f"{label} has an empty value")
        normalized.append(item)
    if len(normalized) != len(set(normalized)):
        raise BuildStateError("invalid-frontmatter", f"{label} repeats a value")
    return tuple(normalized)


def _parse_plan(text: str) -> Tuple[int, ...]:
    headings = list(WAVE_HEADING_RE.finditer(text))
    if not headings:
        raise BuildStateError("invalid-plan", "PLAN.md has no waves")
    wave_numbers = tuple(int(match.group("wave")) for match in headings)
    if wave_numbers != tuple(range(1, len(wave_numbers) + 1)):
        raise BuildStateError(
            "invalid-plan", "PLAN.md wave numbers must be unique, ordered, and contiguous"
        )
    return wave_numbers


def _parse_task(path: Path, relative_path: str, task_file: Optional[str] = None) -> Task:
    label = relative_path
    text = _read_file(path, label)
    fields = _parse_frontmatter(text, label)
    task_id = _required_string(fields, "id", label)
    title = _required_string(fields, "title", label)
    wave_text = _required_string(fields, "wave", label)
    try:
        wave = int(wave_text)
    except ValueError as error:
        raise BuildStateError("invalid-frontmatter", f"{label} has invalid wave") from error
    deps = _normalize_list(fields.get("deps"), f"{label} deps", task_ids=True)
    files = _normalize_list(fields.get("files"), f"{label} files", paths=True)
    status = _required_string(fields, "status", label)
    if status not in VALID_TASK_STATUSES:
        raise BuildStateError("invalid-frontmatter", f"{label} has invalid status: {status}")

    return Task(
        task_id=task_id,
        title=title,
        wave=wave,
        deps=deps,
        files=files,
        status=status,
        agent=_nullable_string(fields, "agent", label),
        base=_nullable_string(fields, "base", label),
        worktree=_nullable_string(fields, "worktree", label),
        task_branch=_nullable_string(fields, "task_branch", label),
        task_file=task_file or relative_path,
        verify_heavy=_verify_heavy(text, label),
    )


def _validate_graph(tasks: Sequence[Task]) -> None:
    by_id = {task.task_id: task for task in tasks}
    for task in tasks:
        for dependency in task.deps:
            if dependency not in by_id:
                raise BuildStateError(
                    "missing-dependency",
                    f"{task.task_id} names missing dependency {dependency}",
                    {"task": task.task_id, "dependency": dependency},
                )
            if by_id[dependency].wave > task.wave:
                raise BuildStateError(
                    "dependency-wave-order",
                    f"{task.task_id} depends on later-wave {dependency}",
                    {"task": task.task_id, "dependency": dependency},
                )

    visiting: List[str] = []
    visited = set()

    def visit(task_id: str) -> None:
        if task_id in visiting:
            start = visiting.index(task_id)
            cycle = visiting[start:] + [task_id]
            raise BuildStateError(
                "dependency-cycle",
                "dependency cycle: " + " -> ".join(cycle),
                {"cycle": cycle},
            )
        if task_id in visited:
            return
        visiting.append(task_id)
        for dependency in by_id[task_id].deps:
            visit(dependency)
        visiting.pop()
        visited.add(task_id)

    for task in tasks:
        visit(task.task_id)


def _load_tasks(
    repo: Path,
    project_dir: str,
    project_path: Path,
    canonical_project_dir: Optional[str] = None,
) -> Tuple[Task, ...]:
    plan_path = project_path / "plan" / "PLAN.md"
    plan_waves = _parse_plan(_read_file(plan_path, f"{project_dir}/plan/PLAN.md"))
    tasks_dir = project_path / "tasks"
    if not tasks_dir.is_dir() or tasks_dir.is_symlink():
        raise BuildStateError("missing-input", f"task directory is missing or unsafe: {tasks_dir}")
    task_paths: Dict[str, Path] = {}
    for path in sorted(tasks_dir.iterdir()):
        match = TASK_FILE_RE.fullmatch(path.name)
        if match is None or not path.is_file() or path.is_symlink():
            raise BuildStateError(
                "invalid-task-file",
                f"task artifacts must be real T###-slug.md files: {path.name}",
            )
        task_id = match.group("id")
        if task_id in task_paths:
            raise BuildStateError(
                "duplicate-task-file",
                f"multiple canonical task files map to {task_id}",
                {"task": task_id, "files": [task_paths[task_id].name, path.name]},
            )
        task_paths[task_id] = path
    parsed: List[Task] = []
    for task_id, path in sorted(task_paths.items()):
        relative = path.relative_to(repo).as_posix()
        task_file = relative
        if canonical_project_dir is not None:
            task_file = str(PurePosixPath(canonical_project_dir) / "tasks" / path.name)
        task = _parse_task(path, relative, task_file)
        if task.task_id != task_id:
            raise BuildStateError(
                "invalid-task-file",
                f"{relative} frontmatter id does not match its filename",
            )
        if task.wave not in plan_waves:
            raise BuildStateError(
                "plan-task-mismatch",
                f"{task.task_id} names missing PLAN.md Wave {task.wave}",
            )
        parsed.append(task)
    missing_waves = sorted(set(plan_waves) - {task.wave for task in parsed})
    if missing_waves:
        raise BuildStateError(
            "invalid-plan",
            "PLAN.md waves without task files: "
            + ", ".join(str(wave) for wave in missing_waves),
        )
    _validate_graph(parsed)
    return tuple(parsed)


def _load_project(repo_value: str, project_value: str, statuses: Sequence[str]) -> Project:
    repo = _repo_root(repo_value)
    project_dir, project_path = _project_path(repo, project_value)
    if project_dir == ".project/next":
        raise BuildStateError(
            "invalid-project-dir",
            "build task state cannot use the lookahead .project/next track",
        )
    try:
        state, _, _ = load_state(repo, project_dir)
    except PipelineStateError as error:
        raise BuildStateError("invalid-state", str(error)) from error
    if state.phase != "build" or state.status not in statuses:
        expected = ", ".join(statuses)
        raise BuildStateError(
            "invalid-build-state", f"STATE.md must be build with status in: {expected}"
        )
    if state.branch is None:
        raise BuildStateError("invalid-build-state", "build STATE.md must name a branch")
    branch = state.branch
    current_branch = _git_output(repo, "branch", "--show-current")
    if not current_branch or current_branch != branch:
        raise BuildStateError(
            "branch-mismatch",
            f"primary branch is {current_branch or '(detached)'}, expected {branch}",
        )
    head = _git_output(repo, "rev-parse", "HEAD")
    parsed = _load_tasks(repo, project_dir, project_path)
    return Project(repo, branch, head, tuple(parsed), project_path / "tasks")


def _commit_resolves(repo: Path, value: str) -> bool:
    result = _run_git(repo, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}")
    return result.returncode == 0


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return _run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _invalid_state(task: Task, message: str) -> None:
    raise BuildStateError(
        "invalid-task-state", f"{task.task_id}: {message}", {"task": task.task_id}
    )


def _recovery_reports(project: Project) -> Dict[str, Mapping[str, object]]:
    try:
        recovery = recover_isolation(project.repo, project.tasks_dir)
    except IsolationError as error:
        raise BuildStateError("invalid-task-state", str(error)) from error
    if recovery.get("verdict") == "block" and not recovery.get("tasks"):
        raise BuildStateError(
            "invalid-task-state",
            str(recovery.get("reason", "task recovery failed")),
        )
    reports: Dict[str, Mapping[str, object]] = {}
    for report in recovery.get("tasks", []):
        if not isinstance(report, Mapping):
            raise BuildStateError("invalid-task-state", "task recovery returned invalid evidence")
        task_id = report.get("task_id")
        if not isinstance(task_id, str) or task_id in reports:
            raise BuildStateError("invalid-task-state", "task recovery returned invalid ownership")
        reports[task_id] = report
    expected = {task.task_id for task in project.tasks}
    if set(reports) != expected:
        raise BuildStateError("invalid-task-state", "task recovery inventory is incomplete")
    return reports


def _validate_ready_metadata(project: Project) -> None:
    by_id = {task.task_id: task for task in project.tasks}
    recovery = _recovery_reports(project)
    seen_worktrees: Dict[str, str] = {}
    seen_branches: Dict[str, str] = {}
    for task in project.tasks:
        if task.status == "pending":
            if any(
                value is not None
                for value in (
                    task.agent,
                    task.base,
                    task.worktree,
                    task.task_branch,
                )
            ):
                _invalid_state(task, "pending task retains dispatch metadata")
            continue
        if task.status in {"in-progress", "failed", "blocked"}:
            if task.agent is None or task.base is None or task.worktree is None:
                _invalid_state(
                    task,
                    f"{task.status} task is missing agent, base, or worktree",
                )
            if not FULL_SHA_RE.fullmatch(task.base) or not _commit_resolves(
                project.repo, task.base
            ):
                _invalid_state(
                    task,
                    f"{task.status} task base is not a full, existing commit",
                )
            if not _is_ancestor(project.repo, task.base, project.head):
                _invalid_state(
                    task,
                    f"{task.status} task base is not an ancestor of HEAD",
                )
            if any(by_id[dependency].status != "done" for dependency in task.deps):
                _invalid_state(task, f"{task.status} task has an incomplete dependency")
            if task.task_branch is None:
                if Path(task.worktree).resolve() != project.repo:
                    _invalid_state(task, "serial task does not name the primary worktree")
            else:
                expected = f"gsd-path-task/{task.task_id}"
                if task.task_branch != expected or Path(task.worktree).resolve() == project.repo:
                    _invalid_state(task, "parallel task has invalid branch or worktree metadata")
                previous = seen_branches.setdefault(task.task_branch, task.task_id)
                if previous != task.task_id:
                    _invalid_state(task, f"task branch is also owned by {previous}")
            worktree_key = str(Path(task.worktree).resolve())
            previous = seen_worktrees.setdefault(worktree_key, task.task_id)
            if previous != task.task_id:
                _invalid_state(task, f"worktree is also owned by {previous}")
            continue
        if task.status == "done":
            if any(by_id[dependency].status != "done" for dependency in task.deps):
                _invalid_state(task, "done task has an incomplete dependency")
            if task.agent is None or task.base is None:
                _invalid_state(task, "done task is missing agent or base")
            if task.worktree is not None or task.task_branch is not None:
                _invalid_state(task, "done task retains active isolation metadata")
            report = recovery[task.task_id]
            if report.get("verdict") not in LANDED_VERDICTS:
                reason = report.get("reason", "landing commit is not proven")
                _invalid_state(task, str(reason))


def _overlap(left: Task, right: Task) -> List[str]:
    return sorted(set(left.files) & set(right.files))


def ready(repo: str, project_dir: str = DEFAULT_PROJECT_DIR, *,
          allow_done: bool = False) -> Dict[str, object]:
    """Return task readiness, optionally accepting build/done for completion checks."""

    project = _load_project(repo, project_dir, ("active", "done") if allow_done else ("active",))
    _validate_ready_metadata(project)
    by_id = {task.task_id: task for task in project.tasks}
    unfinished_waves = sorted({task.wave for task in project.tasks if task.status != "done"})
    current_wave = unfinished_waves[0] if unfinished_waves else None
    active = [task for task in project.tasks if task.status == "in-progress"]
    if current_wave is not None and any(task.wave != current_wave for task in active):
        task = next(task for task in active if task.wave != current_wave)
        _invalid_state(task, f"active outside current Wave {current_wave}")

    recovery = [
        task
        for task in project.tasks
        if task.wave == current_wave and task.status in {"failed", "blocked"}
    ]
    if recovery:
        raise BuildStateError(
            "task-recovery-required",
            f"Wave {current_wave} has failed or blocked tasks requiring recovery",
            {
                "wave": current_wave,
                "tasks": [
                    {"id": task.task_id, "status": task.status}
                    for task in recovery
                ],
            },
        )

    selectable = [
        task
        for task in project.tasks
        if task.wave == current_wave
        and task.status == "pending"
        and all(by_id[dependency].status == "done" for dependency in task.deps)
    ]
    concurrent = selectable + active
    for index, left in enumerate(concurrent):
        for right in concurrent[index + 1 :]:
            paths = _overlap(left, right)
            if paths:
                raise BuildStateError(
                    "ready-file-overlap",
                    f"concurrent tasks {left.task_id} and {right.task_id} overlap",
                    {"tasks": [left.task_id, right.task_id], "files": paths},
                )

    wave_active = any(task.wave == current_wave for task in active)
    if current_wave is not None and not selectable and not wave_active:
        stalled = [
            {
                "id": task.task_id,
                "status": task.status,
                "waiting_on": [
                    dependency
                    for dependency in task.deps
                    if by_id[dependency].status != "done"
                ],
            }
            for task in project.tasks
            if task.wave == current_wave and task.status != "done"
        ]
        raise BuildStateError(
            "dependency-deadlock",
            f"Wave {current_wave} has unfinished tasks but no ready or in-progress task",
            {"wave": current_wave, "tasks": stalled},
        )

    return {
        "command": "ready",
        "branch": project.branch,
        "head": project.head,
        "current_wave": current_wave,
        "ready": [
            {
                "id": task.task_id,
                "title": task.title,
                "wave": task.wave,
                "status": task.status,
                "deps": list(task.deps),
                "files": list(task.files),
                "task_file": task.task_file,
                "verify_heavy": task.verify_heavy,
            }
            for task in selectable
        ],
    }


def _reconcile_result(
    project: Project,
    task: Task,
    classification: str,
    candidates: Sequence[Mapping[str, object]],
    reasons: Sequence[str],
    landed_commit: Optional[str] = None,
) -> Dict[str, object]:
    return {
        "command": "reconcile",
        "classification": classification,
        "task": {
            "id": task.task_id,
            "status": task.status,
            "task_file": task.task_file,
            "base": task.base,
        },
        "history": {
            "branch": project.branch,
            "head": project.head,
            "subject": task_commit_subject(task.task_id, task.title),
            "candidates": list(candidates),
        },
        "landed_commit": landed_commit,
        "reasons": list(reasons),
    }


def _reconcile_task(project: Project, task: Task) -> Dict[str, object]:
    report = _recovery_reports(project)[task.task_id]
    verdict = str(report.get("verdict", "block"))
    rejected = report.get("rejected")
    candidates: List[Mapping[str, object]] = []
    if isinstance(rejected, list):
        candidates.extend(item for item in rejected if isinstance(item, Mapping))
    commit = report.get("commit")
    if isinstance(commit, str):
        candidates.append(
            {
                "commit": commit,
                "base": report.get("base"),
                "valid": verdict in LANDED_VERDICTS,
            }
        )
    if verdict in LANDED_VERDICTS:
        return _reconcile_result(
            project,
            task,
            LANDED_VERDICTS[verdict],
            candidates,
            (),
            landed_commit=commit if isinstance(commit, str) else None,
        )
    reason = str(report.get("reason", verdict))
    classification = {
        "none": "resumable",
        "resume": "resumable",
        "reconcile": "reconcile",
        "block": "blocked",
    }.get(verdict, "blocked")
    return _reconcile_result(project, task, classification, candidates, (reason,))


def reconcile(
    repo: str, task_id: str, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Classify recorded task state against canonical first-parent commits."""

    if not TASK_ID_RE.fullmatch(task_id):
        raise BuildStateError("invalid-task-id", f"invalid task id: {task_id}")
    project = _load_project(repo, project_dir, ("active", "blocked", "done"))
    task = next((item for item in project.tasks if item.task_id == task_id), None)
    if task is None:
        raise BuildStateError("unknown-task", f"task file is missing: {task_id}")
    return _reconcile_task(project, task)


def verify_landed_tasks(
    repo: str,
    project_dir: str,
    head: str,
    canonical_project_dir: str = DEFAULT_PROJECT_DIR,
) -> Dict[str, object]:
    """Verify archived task records against canonical first-parent landings."""

    repository = _repo_root(repo)
    artifact_dir, artifact_path = _project_path(repository, project_dir)
    canonical_dir, _ = _project_path(repository, canonical_project_dir)
    if not FULL_SHA_RE.fullmatch(head) or not _commit_resolves(repository, head):
        raise BuildStateError(
            "invalid-head", "--head must be a full, existing commit SHA"
        )
    if _git_output(repository, "rev-parse", f"{head}^{{commit}}") != head:
        raise BuildStateError("invalid-head", "--head must resolve to itself")

    tasks = _load_tasks(
        repository,
        artifact_dir,
        artifact_path,
        canonical_project_dir=canonical_dir,
    )
    for task in tasks:
        if task.status != "done":
            _invalid_state(task, "task must have status: done before shipping")
    try:
        proven = verify_landed_task_files(
            repository,
            [artifact_path / "tasks" / Path(task.task_file).name for task in tasks],
            str(PurePosixPath(canonical_dir) / "tasks"),
            head,
        )
    except IsolationError as error:
        raise BuildStateError("invalid-task-state", str(error)) from error

    reports = {
        str(report["task_id"]): report
        for report in proven["tasks"]
        if isinstance(report, Mapping) and isinstance(report.get("task_id"), str)
    }
    evidence = []
    for task in tasks:
        report = reports.get(task.task_id)
        if report is None or report.get("verdict") not in LANDED_VERDICTS:
            _invalid_state(task, "task landing is not canonical")
        commit = report.get("commit")
        evidence.append(
            {
                "command": "reconcile",
                "classification": LANDED_VERDICTS[str(report["verdict"])],
                "task": {
                    "id": task.task_id,
                    "status": task.status,
                    "task_file": task.task_file,
                    "base": task.base,
                },
                "history": {
                    "branch": proven["bound_branch"],
                    "head": head,
                    "subject": task_commit_subject(task.task_id, task.title),
                    "candidates": [
                        {
                            "commit": commit,
                            "base": report.get("base"),
                            "valid": True,
                        }
                    ],
                },
                "landed_commit": commit,
                "reasons": [],
            }
        )
    return {
        "command": "verify-landed",
        "project_dir": artifact_dir,
        "canonical_project_dir": canonical_dir,
        "head": head,
        "tasks": evidence,
    }


def _ledger_path(repo: Path) -> Path:
    path = repo.joinpath(*PurePosixPath(VERIFY_LEDGER_PATH).parts)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise BuildStateError("invalid-ledger", f"verify ledger is not a regular file: {path}")
    return path


def _ledger_key(repo: Path, command: str, commit: str) -> Tuple[str, str]:
    if not command.strip():
        raise BuildStateError("invalid-command", "--command must not be empty")
    if not FULL_SHA_RE.fullmatch(commit) or not _commit_resolves(repo, commit):
        raise BuildStateError("invalid-commit", "--commit must be a full, existing commit SHA")
    return command, commit


def _ledger_entries(path: Path) -> List[Dict[str, object]]:
    try:
        return _common.verify_ledger_entries(path)
    except ValueError as error:
        raise BuildStateError("invalid-ledger", str(error)) from error


def verify_record(repo: str, command: str, commit: str, result: str,
                  execution: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    """Append one verify run (command, commit, result, timestamp) to the ledger."""

    repository = _repo_root(repo)
    if result not in VERIFY_RESULTS:
        raise BuildStateError("invalid-result", "--result must be pass or fail")
    normalized, commit = _ledger_key(repository, command, commit)
    path = _ledger_path(repository)
    _ledger_entries(path)
    entry = {
        "schema": _common.VERIFY_LEDGER_SCHEMA,
        "command": normalized,
        "commit": commit,
        "result": result,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    if execution is not None:
        if (not isinstance(execution.get("stdout"), str)
                or not isinstance(execution.get("stderr"), str)
                or type(execution.get("exit_code")) is not int
                or (execution["exit_code"] == 0) != (result == "pass")):
            raise BuildStateError("invalid-execution", "verification output and result disagree")
        entry["execution"] = execution
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    _common.atomic_write(path, previous + json.dumps(entry, sort_keys=True) + "\n")
    return {"command": "verify-record", "ledger": VERIFY_LEDGER_PATH, "entry": entry}


def verify_lookup(repo: str, command: str, commit: str) -> Dict[str, object]:
    """Return the latest recorded run of this command at this commit, or a miss."""

    repository = _repo_root(repo)
    normalized, commit = _ledger_key(repository, command, commit)
    entry = _common.latest_verify_entry(_ledger_entries(_ledger_path(repository)), normalized, commit)
    return {
        "command": "verify-lookup",
        "ledger": VERIFY_LEDGER_PATH,
        "hit": entry is not None,
        "reuse": entry is not None and entry["result"] == "pass",
        "entry": entry,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    ready_parser = subcommands.add_parser("ready", help="list dependency-ready tasks")
    ready_parser.add_argument("--repo", required=True)
    ready_parser.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR)
    reconcile_parser = subcommands.add_parser(
        "reconcile", help="classify one task against first-parent landing evidence"
    )
    reconcile_parser.add_argument("--repo", required=True)
    reconcile_parser.add_argument("--task-id", required=True)
    reconcile_parser.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR)
    verify_parser = subcommands.add_parser(
        "verify-landed", help="verify archived tasks against canonical landings"
    )
    verify_parser.add_argument("--repo", required=True)
    verify_parser.add_argument("--project-dir", required=True)
    verify_parser.add_argument("--head", required=True)
    verify_parser.add_argument("--canonical-project-dir", default=DEFAULT_PROJECT_DIR)
    record_parser = subcommands.add_parser(
        "verify-record", help="append one verify run to the ledger"
    )
    record_parser.add_argument("--repo", required=True)
    record_parser.add_argument("--command", required=True, dest="verify_command")
    record_parser.add_argument("--commit", required=True)
    record_parser.add_argument("--result", required=True, choices=VERIFY_RESULTS)
    lookup_parser = subcommands.add_parser(
        "verify-lookup", help="find the recorded run of a command at a commit"
    )
    lookup_parser.add_argument("--repo", required=True)
    lookup_parser.add_argument("--command", required=True, dest="verify_command")
    lookup_parser.add_argument("--commit", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "ready":
            result = ready(arguments.repo, arguments.project_dir)
        elif arguments.command == "reconcile":
            result = reconcile(arguments.repo, arguments.task_id, arguments.project_dir)
        elif arguments.command == "verify-record":
            result = verify_record(
                arguments.repo, arguments.verify_command, arguments.commit, arguments.result
            )
        elif arguments.command == "verify-lookup":
            result = verify_lookup(arguments.repo, arguments.verify_command, arguments.commit)
        else:
            result = verify_landed_tasks(
                arguments.repo,
                arguments.project_dir,
                arguments.head,
                arguments.canonical_project_dir,
            )
    except BuildStateError as error:
        result = {
            "command": arguments.command,
            "error": {"code": error.code, "message": str(error), "details": error.details},
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
