#!/usr/bin/env python3
"""Read-only build task readiness and landing reconciliation."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

try:
    from check_task_briefs import _frontmatter
    from pipeline_git import task_commit_body, task_commit_subject
    from pipeline_state import PipelineStateError, load_state
except ImportError:  # pragma: no cover - package imports used by tests
    from scripts.check_task_briefs import _frontmatter
    from scripts.pipeline_git import task_commit_body, task_commit_subject
    from scripts.pipeline_state import PipelineStateError, load_state


DEFAULT_PROJECT_DIR = ".project"
TASK_ID_RE = re.compile(r"^T\d{3}$")
TASK_FILE_RE = re.compile(r"^(?P<id>T\d{3})-[a-z0-9][a-z0-9-]*\.md$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
WAVE_HEADING_RE = re.compile(r"(?m)^## Wave (?P<wave>\d+)\b.*$")
PLAN_ROW_RE = re.compile(
    r"^\|\s*(?P<id>T\d{3})\s*\|\s*(?P<title>[^|]+?)\s*\|"
    r"\s*(?P<deps>[^|]+?)\s*\|\s*(?P<files>[^|]+?)\s*\|\s*$"
)
VALID_TASK_STATUSES = {"pending", "in-progress", "done", "failed", "blocked"}


class BuildStateError(RuntimeError):
    """A typed, user-actionable build state error."""

    def __init__(
        self, code: str, message: str, details: Optional[Mapping[str, object]] = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})


@dataclass(frozen=True)
class PlanTask:
    task_id: str
    title: str
    wave: int
    deps: Tuple[str, ...]
    files: Tuple[str, ...]


@dataclass(frozen=True)
class Task(PlanTask):
    status: str
    agent: Optional[str]
    commit: Optional[str]
    base: Optional[str]
    worktree: Optional[str]
    task_branch: Optional[str]
    task_file: str


@dataclass(frozen=True)
class Project:
    repo: Path
    branch: str
    head: str
    tasks: Tuple[Task, ...]


def _run_git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", "-C", str(repo), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )


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


def _parse_frontmatter(path: Path, label: str) -> Dict[str, object]:
    fields, error = _frontmatter(_read_file(path, label))
    if fields is None:
        raise BuildStateError("invalid-frontmatter", f"{label}: {error}")
    return fields


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


def _plan_ids(value: str, label: str) -> Tuple[str, ...]:
    cleaned = value.strip().strip("`")
    if cleaned in {"", "—", "-", "[]"} or cleaned.casefold() == "none":
        return ()
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    ids = tuple(item.strip().strip("`\"'") for item in cleaned.split(","))
    if not ids or any(not TASK_ID_RE.fullmatch(item) for item in ids):
        raise BuildStateError("invalid-plan", f"{label} has an invalid task list")
    if len(ids) != len(set(ids)):
        raise BuildStateError("invalid-plan", f"{label} repeats a task")
    return ids


def _plan_files(value: str, label: str) -> Tuple[str, ...]:
    cleaned = value.strip().strip("`")
    values = [
        item.strip().strip("`\"'")
        for item in re.split(r"\s*(?:,|<br\s*/?>)\s*", cleaned)
        if item.strip()
    ]
    try:
        return _normalize_list(values, label, paths=True)
    except BuildStateError as error:
        raise BuildStateError("invalid-plan", str(error)) from error


def _parse_plan(text: str) -> Tuple[PlanTask, ...]:
    headings = list(WAVE_HEADING_RE.finditer(text))
    if not headings:
        raise BuildStateError("invalid-plan", "PLAN.md has no waves")
    wave_numbers = [int(match.group("wave")) for match in headings]
    if wave_numbers != list(range(1, len(wave_numbers) + 1)):
        raise BuildStateError(
            "invalid-plan", "PLAN.md wave numbers must be unique, ordered, and contiguous"
        )

    tasks: List[PlanTask] = []
    seen = set()
    for index, heading in enumerate(headings):
        wave = int(heading.group("wave"))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        wave_rows = 0
        for line in text[heading.end() : end].splitlines():
            stripped = line.strip()
            if not re.match(r"^\|\s*T\d", stripped):
                continue
            match = PLAN_ROW_RE.fullmatch(stripped)
            if match is None:
                raise BuildStateError("invalid-plan", f"PLAN.md Wave {wave} has a malformed row")
            task_id = match.group("id")
            if task_id in seen:
                raise BuildStateError("invalid-plan", f"PLAN.md repeats {task_id}")
            seen.add(task_id)
            title = match.group("title").strip()
            if not title:
                raise BuildStateError("invalid-plan", f"PLAN.md {task_id} title is empty")
            tasks.append(
                PlanTask(
                    task_id=task_id,
                    title=title,
                    wave=wave,
                    deps=_plan_ids(match.group("deps"), f"PLAN.md {task_id} Deps"),
                    files=_plan_files(match.group("files"), f"PLAN.md {task_id} Files"),
                )
            )
            wave_rows += 1
        if wave_rows == 0:
            raise BuildStateError("invalid-plan", f"PLAN.md Wave {wave} has no task rows")
    return tuple(tasks)


def _parse_task(
    path: Path, relative_path: str, plan: PlanTask, task_file: Optional[str] = None
) -> Task:
    label = relative_path
    fields = _parse_frontmatter(path, label)
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

    if task_id != plan.task_id:
        raise BuildStateError("plan-task-mismatch", f"PLAN.md {plan.task_id} maps to {label}")
    comparisons = (
        ("title", " ".join(title.split()), " ".join(plan.title.split())),
        ("wave", wave, plan.wave),
        ("deps", deps, plan.deps),
        ("files", files, plan.files),
    )
    for field, actual, expected in comparisons:
        if actual != expected:
            raise BuildStateError(
                "plan-task-mismatch", f"{task_id} {field} differs between PLAN.md and task file"
            )

    return Task(
        task_id=task_id,
        title=title,
        wave=wave,
        deps=deps,
        files=files,
        status=status,
        agent=_nullable_string(fields, "agent", label),
        commit=_nullable_string(fields, "commit", label),
        base=_nullable_string(fields, "base", label),
        worktree=_nullable_string(fields, "worktree", label),
        task_branch=_nullable_string(fields, "task_branch", label),
        task_file=task_file or relative_path,
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
    plan_rows = _parse_plan(_read_file(plan_path, f"{project_dir}/plan/PLAN.md"))
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
    plan_ids = {row.task_id for row in plan_rows}
    if plan_ids != set(task_paths):
        missing_files = sorted(plan_ids - set(task_paths))
        extra_files = sorted(set(task_paths) - plan_ids)
        details: List[str] = []
        if missing_files:
            details.append("rows without task files: " + ", ".join(missing_files))
        if extra_files:
            details.append("task files without rows: " + ", ".join(extra_files))
        raise BuildStateError("plan-task-mismatch", "; ".join(details))

    parsed: List[Task] = []
    for row in plan_rows:
        path = task_paths[row.task_id]
        relative = path.relative_to(repo).as_posix()
        task_file = relative
        if canonical_project_dir is not None:
            task_file = str(PurePosixPath(canonical_project_dir) / "tasks" / path.name)
        parsed.append(_parse_task(path, relative, row, task_file))
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
    return Project(repo, branch, head, tuple(parsed))


def _commit_resolves(repo: Path, value: str) -> bool:
    result = _run_git(repo, "rev-parse", "--verify", "--quiet", f"{value}^{{commit}}")
    return result.returncode == 0


def _is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    return _run_git(repo, "merge-base", "--is-ancestor", ancestor, descendant).returncode == 0


def _invalid_state(task: Task, message: str) -> None:
    raise BuildStateError(
        "invalid-task-state", f"{task.task_id}: {message}", {"task": task.task_id}
    )


def _validate_ready_metadata(project: Project) -> None:
    by_id = {task.task_id: task for task in project.tasks}
    first_parent = set(
        _git_output(project.repo, "rev-list", "--first-parent", project.head).splitlines()
    )
    seen_worktrees: Dict[str, str] = {}
    seen_branches: Dict[str, str] = {}
    for task in project.tasks:
        if task.status == "pending":
            if any(
                value is not None
                for value in (
                    task.agent,
                    task.commit,
                    task.base,
                    task.worktree,
                    task.task_branch,
                )
            ):
                _invalid_state(task, "pending task retains dispatch or commit metadata")
            continue
        if task.status in {"in-progress", "failed", "blocked"}:
            if task.commit is not None:
                _invalid_state(task, f"{task.status} task has a recorded commit")
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
            if task.agent is None or task.base is None or task.commit is None:
                _invalid_state(task, "done task is missing agent, base, or commit")
            if not FULL_SHA_RE.fullmatch(task.base) or not FULL_SHA_RE.fullmatch(task.commit):
                _invalid_state(task, "done task base or commit is not a full SHA")
            if not _commit_resolves(project.repo, task.base) or not _commit_resolves(
                project.repo, task.commit
            ):
                _invalid_state(task, "done task base or commit does not exist")
            if task.base not in first_parent or task.commit not in first_parent:
                _invalid_state(
                    task,
                    "done task base and commit must be on canonical first-parent history",
                )
            if not _is_ancestor(project.repo, task.base, task.commit):
                _invalid_state(task, "done task commit precedes its recorded base")
            candidate = _candidate(project, task, task.commit)
            if not candidate["valid"]:
                reasons = ", ".join(candidate["reasons"])
                _invalid_state(task, f"done task commit is not canonical: {reasons}")


def _overlap(left: Task, right: Task) -> List[str]:
    return sorted(set(left.files) & set(right.files))


def ready(repo: str, project_dir: str = DEFAULT_PROJECT_DIR) -> Dict[str, object]:
    """Return pending tasks that the orchestrator may dispatch now."""

    project = _load_project(repo, project_dir, ("active",))
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
            }
            for task in selectable
        ],
    }


def _candidate(
    project: Project,
    task: Task,
    commit: str,
    *,
    require_dispatch_parent: bool = True,
) -> Dict[str, object]:
    parents = _git_output(project.repo, "show", "-s", "--format=%P", commit).split()
    if not parents:
        raise BuildStateError("git-error", "candidate commit has no parent")
    parent = parents[0]
    paths_result = _run_git(
        project.repo,
        "-c",
        "diff.renames=false",
        "diff-tree",
        "--no-commit-id",
        "--name-only",
        "-r",
        "-z",
        parent,
        commit,
    )
    if paths_result.returncode != 0:
        raise BuildStateError("git-error", "could not inspect candidate paths")
    paths = sorted(path for path in paths_result.stdout.split("\0") if path)
    subject = _git_output(project.repo, "show", "-s", "--format=%s", commit)
    expected_subject = task_commit_subject(task.task_id, task.title)
    body = _git_output(project.repo, "show", "-s", "--format=%b", commit)
    expected_body = task_commit_body(task.task_file, paths).strip()
    allowed = set(task.files) | {task.task_file}
    unexpected = sorted(set(paths) - allowed)
    reasons: List[str] = []
    if len(parents) != 1:
        reasons.append("task commit is a merge")
    if task.task_file not in paths:
        reasons.append("task file is not changed")
    if unexpected:
        reasons.append("unexpected changed paths")
    if subject != expected_subject:
        reasons.append("commit subject does not match the canonical task subject")
    if body != expected_body:
        reasons.append("commit body does not match canonical task fields")
    parent_text = _git_file_text(project.repo, parent, task.task_file)
    if require_dispatch_parent and parent_text is None:
        reasons.append("candidate parent is missing the task file")
    elif require_dispatch_parent:
        assert parent_text is not None
        parent_fields, error = _frontmatter(parent_text)
        if parent_fields is None:
            reasons.append(f"candidate parent task frontmatter is invalid: {error}")
        else:
            expected_dispatch = {
                "base": task.base,
                "agent": task.agent,
                "worktree": task.worktree,
                "task_branch": task.task_branch,
            }
            actual_dispatch: Dict[str, Optional[str]] = {}
            for field in expected_dispatch:
                value = parent_fields.get(field)
                if not isinstance(value, str):
                    reasons.append(
                        f"candidate parent task has invalid dispatch field: {field}"
                    )
                    continue
                cleaned = value.strip()
                actual_dispatch[field] = (
                    None if cleaned in {"", "null"} else cleaned
                )
            mismatched = sorted(
                field
                for field, expected in expected_dispatch.items()
                if actual_dispatch.get(field) != expected
            )
            if mismatched:
                reasons.append(
                    "candidate parent dispatch metadata differs from recorded task: "
                    + ", ".join(mismatched)
                )
            if parent_fields.get("status") != "in-progress":
                reasons.append("candidate parent task status is not in-progress")
            if parent_fields.get("commit") != "null":
                reasons.append("candidate parent task already records a commit")
    _, log_reason = _task_log_delta(project.repo, parent, commit, task.task_file)
    if log_reason is not None:
        reasons.append(log_reason)
    return {
        "commit": commit,
        "parent": parent,
        "valid": not reasons,
        "paths": paths,
        "unexpected_paths": unexpected,
        "subject_matches": subject == expected_subject,
        "body_matches": body == expected_body,
        "is_merge": len(parents) != 1,
        "reasons": reasons,
    }


def _git_file_text(repo: Path, revision: str, path: str) -> Optional[str]:
    result = _run_git(repo, "show", f"{revision}:{path}")
    return result.stdout if result.returncode == 0 else None


def _task_log_delta(
    repo: Path,
    parent: str,
    commit: str,
    task_file: str,
) -> Tuple[Optional[str], Optional[str]]:
    before = _git_file_text(repo, parent, task_file)
    after = _git_file_text(repo, commit, task_file)
    if before is None or after is None:
        return None, "task file is missing before or after the candidate"
    if before.count("\n## Log\n") != 1:
        return None, "task file parent has no unique Log section"
    if len(after) <= len(before) or not after.startswith(before):
        return None, "task file is not a nonempty append-only Log delta"
    delta = after[len(before) :]
    if not delta.strip():
        return None, "task Log delta is empty"
    return delta, None


def _binary_patch(repo: Path, parent: str, commit: str, paths: Sequence[str]) -> bytes:
    if not paths:
        return b""
    result = subprocess.run(
        (
            "git",
            "-C",
            str(repo),
            "diff",
            "--binary",
            "--full-index",
            "--no-ext-diff",
            "--no-renames",
            parent,
            commit,
            "--",
            *sorted(paths),
        ),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise BuildStateError("git-error", "could not reconstruct candidate patch")
    return result.stdout


def _common_git_dir(repo: Path) -> Optional[Path]:
    result = _run_git(repo, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if result.returncode != 0:
        return None
    return Path(result.stdout.strip()).resolve()


def _resumable(project: Project, task: Task) -> Tuple[bool, List[str]]:
    reasons: List[str] = []
    if task.status == "pending":
        if any(
            value is not None
            for value in (task.agent, task.commit, task.base, task.worktree, task.task_branch)
        ):
            reasons.append("pending task retains dispatch or commit metadata")
        return not reasons, reasons
    if task.status != "in-progress":
        return False, [f"task status is {task.status}"]
    if task.base is None:
        reasons.append("in-progress task has no recorded base")
    if task.commit is not None:
        reasons.append("in-progress task has a recorded commit")
    if task.agent is None or task.worktree is None:
        reasons.append("in-progress task is missing agent or worktree")
        return False, reasons
    worktree = Path(task.worktree).resolve()
    if task.task_branch is None:
        if worktree != project.repo:
            reasons.append("serial task does not name the primary worktree")
    else:
        expected = f"gsd-path-task/{task.task_id}"
        if task.task_branch != expected:
            reasons.append("parallel task branch is not canonical")
        if not worktree.is_dir():
            reasons.append("recorded worktree is missing")
        else:
            root_result = _run_git(worktree, "rev-parse", "--show-toplevel")
            branch_result = _run_git(worktree, "branch", "--show-current")
            if (
                root_result.returncode != 0
                or Path(root_result.stdout.strip()).resolve() != worktree
            ):
                reasons.append("recorded worktree is not its Git root")
            if branch_result.returncode != 0 or branch_result.stdout.strip() != task.task_branch:
                reasons.append("recorded worktree is not on the recorded branch")
            if _common_git_dir(worktree) != _common_git_dir(project.repo):
                reasons.append("recorded worktree belongs to another repository")
    return not reasons, reasons


def _retained_source_reasons(
    project: Project,
    task: Task,
    landed: Mapping[str, object],
) -> List[str]:
    owned, reasons = _resumable(project, task)
    if not owned:
        return reasons
    landed_commit = str(landed["commit"])
    if task.task_branch is None:
        if project.head != landed_commit:
            return ["serial retained source HEAD does not equal the landed candidate"]
        return []

    assert task.worktree is not None
    source = Path(task.worktree).resolve()
    if _git_output(source, "status", "--porcelain", "--untracked-files=all"):
        return ["retained source worktree is not clean"]
    source_commit = _git_output(source, "rev-parse", "HEAD")
    assert task.base is not None
    source_parents = _git_output(source, "show", "-s", "--format=%P", source_commit).split()
    if source_parents != [task.base]:
        return ["retained source is not one task commit directly after its base"]
    source_candidate = _candidate(
        project,
        task,
        source_commit,
        require_dispatch_parent=False,
    )
    if not source_candidate["valid"]:
        return [
            "retained source commit is not canonical: "
            + ", ".join(str(reason) for reason in source_candidate["reasons"])
        ]
    if source_candidate["paths"] != landed["paths"]:
        return ["retained source and landed candidate changed different paths"]

    source_delta, source_error = _task_log_delta(
        project.repo,
        task.base,
        source_commit,
        task.task_file,
    )
    landed_delta, landed_error = _task_log_delta(
        project.repo,
        str(landed["parent"]),
        landed_commit,
        task.task_file,
    )
    if source_error is not None or landed_error is not None:
        return [source_error or landed_error or "task Log delta could not be compared"]
    if source_delta != landed_delta:
        return ["retained source and landed task Log deltas differ"]

    product_paths = [
        path for path in task.files if path != task.task_file
    ]
    source_patch = _binary_patch(project.repo, task.base, source_commit, product_paths)
    landed_patch = _binary_patch(
        project.repo,
        str(landed["parent"]),
        landed_commit,
        product_paths,
    )
    if source_patch != landed_patch:
        return ["retained source and landed product patches differ"]
    return []


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
            "recorded_commit": task.commit,
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
    if task.base is None:
        resumable, reasons = _resumable(project, task)
        classification = "resumable" if resumable else "blocked"
        return _reconcile_result(project, task, classification, (), reasons)
    if not FULL_SHA_RE.fullmatch(task.base) or not _commit_resolves(project.repo, task.base):
        return _reconcile_result(
            project, task, "blocked", (), ("recorded base is not a full, existing commit",)
        )
    if not _is_ancestor(project.repo, task.base, project.head):
        return _reconcile_result(
            project, task, "blocked", (), ("recorded base is not an ancestor of HEAD",)
        )

    subject = task_commit_subject(task.task_id, task.title)
    commits = _git_output(
        project.repo, "rev-list", "--first-parent", "--reverse", f"{task.base}..{project.head}"
    ).splitlines()
    matching = [
        commit
        for commit in commits
        if _git_output(project.repo, "show", "-s", "--format=%s", commit) == subject
    ]
    candidates = [_candidate(project, task, commit) for commit in matching]
    if len(candidates) > 1:
        return _reconcile_result(
            project,
            task,
            "ambiguous",
            candidates,
            ("multiple first-parent commits have the canonical task subject",),
        )
    if candidates and not candidates[0]["valid"]:
        return _reconcile_result(
            project,
            task,
            "blocked",
            candidates,
            tuple(candidates[0]["reasons"]),  # type: ignore[arg-type]
        )
    if candidates:
        candidate_commit = str(candidates[0]["commit"])
        if task.status == "done":
            if task.commit != candidate_commit:
                return _reconcile_result(
                    project,
                    task,
                    "blocked",
                    candidates,
                    ("recorded commit does not match the canonical landed commit",),
                )
        elif task.status != "in-progress" or task.commit is not None:
            return _reconcile_result(
                project,
                task,
                "blocked",
                candidates,
                (f"landed commit conflicts with task status {task.status}",),
            )
        else:
            source_reasons = _retained_source_reasons(project, task, candidates[0])
            if source_reasons:
                return _reconcile_result(
                    project,
                    task,
                    "blocked",
                    candidates,
                    source_reasons,
                )
        return _reconcile_result(
            project, task, "proven-landed", candidates, (), landed_commit=candidate_commit
        )

    if task.status == "done":
        return _reconcile_result(
            project,
            task,
            "blocked",
            (),
            ("done task has no canonical commit on first-parent history",),
        )
    resumable, reasons = _resumable(project, task)
    return _reconcile_result(
        project,
        task,
        "resumable" if resumable else "blocked",
        (),
        reasons,
    )


def reconcile(
    repo: str, task_id: str, project_dir: str = DEFAULT_PROJECT_DIR
) -> Dict[str, object]:
    """Classify recorded task state against canonical first-parent commits."""

    if not TASK_ID_RE.fullmatch(task_id):
        raise BuildStateError("invalid-task-id", f"invalid task id: {task_id}")
    project = _load_project(repo, project_dir, ("active", "blocked", "done"))
    task = next((item for item in project.tasks if item.task_id == task_id), None)
    if task is None:
        raise BuildStateError("unknown-task", f"task is not in PLAN.md: {task_id}")
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
    project = Project(repository, "", head, tasks)
    for task in tasks:
        if task.status != "done":
            _invalid_state(task, "task must have status: done before shipping")
    _validate_ready_metadata(project)

    evidence = []
    for task in tasks:
        result = _reconcile_task(project, task)
        if result["classification"] != "proven-landed":
            reasons = ", ".join(str(reason) for reason in result["reasons"])
            _invalid_state(task, reasons or "task landing is not canonical")
        evidence.append(result)
    return {
        "command": "verify-landed",
        "project_dir": artifact_dir,
        "canonical_project_dir": canonical_dir,
        "head": head,
        "tasks": evidence,
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
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "ready":
            result = ready(arguments.repo, arguments.project_dir)
        elif arguments.command == "reconcile":
            result = reconcile(arguments.repo, arguments.task_id, arguments.project_dir)
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
