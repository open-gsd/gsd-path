#!/usr/bin/env python3
# gsd-path project runtime
"""Build task readiness, landing reconciliation, and the verify ledger."""

from __future__ import annotations

import argparse
import json
import re
import sys
sys.dont_write_bytecode = True
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Dict, List, Mapping, Optional, Sequence, Tuple

if __package__:
    from .check_task_briefs import _frontmatter, _sections
    from .isolation import (
        VERIFY_LEDGER_PATH,
        IsolationError,
        recover as recover_isolation,
        verify_landed_task_files,
    )
    from .pipeline_git import task_commit_subject
    from .pipeline_state import PipelineStateError, load_state
    from . import _common, check_handoffs
else:
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
        import check_handoffs
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
        from scripts import _common, check_handoffs


DEFAULT_PROJECT_DIR = ".project"
TASK_ID_RE = re.compile(r"^T\d{3}$")
TASK_FILE_RE = re.compile(r"^(?P<id>T\d{3})-[a-z0-9][a-z0-9-]*\.md$")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# recover verdicts that count as landed, mapped to their evidence classification.
LANDED_VERDICTS = {"recovered": "proven-landed", "attested": "attested"}
WAVE_HEADING_RE = re.compile(r"(?m)^## Wave (?P<wave>\d+)\b.*$")
REVIEW_VERDICT_RE = re.compile(
    r"(?m)^Wave verdict:\s*(?P<verdict>pass|blocked)\s*(?:<!--.*?-->)?\s*$"
)
REVIEW_FINDINGS_HEADING = "Review findings"
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
    repo: str = ""
    review_findings: bool = False
    verify: str = ""
    supersedes: Tuple[str, ...] = ()


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
        repo=str(fields.get("repo") or ""),
        review_findings=REVIEW_FINDINGS_HEADING in _sections(text),
        verify=_common.task_verify_command(text),
        supersedes=_normalize_list(fields.get("supersedes", []), f"{label} supersedes", task_ids=True),
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
        if _common.is_ignored_junk(path):
            continue
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


def _validate_ready_metadata(project: Project) -> Dict[str, Mapping[str, object]]:
    """Validate every task against its recovery report; return the reports by task id."""
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
    return recovery


def _overlap(left: Task, right: Task) -> List[str]:
    if left.repo != right.repo:
        return []
    return _common.overlapping_paths(left.files, right.files)


def _superseded(tasks: Sequence[Task], task: Task) -> Dict[str, str]:
    """Earlier task id -> the task that replaces its behavior: this task, or a `done` task."""

    return {
        earlier: other.task_id
        for other in tasks
        if other.status == "done" or other.task_id == task.task_id
        for earlier in other.supersedes
    }


def _held(by_id: Mapping[str, Task], task: Task) -> List[Task]:
    """The tasks whose protective role this task inherits: each task it supersedes, through a chain."""

    held: Dict[str, Task] = {}
    pending = list(task.supersedes)
    while pending:
        other = by_id.get(pending.pop())
        if other is not None and other.task_id not in held:  # a cycle ends here
            held[other.task_id] = other
            pending.extend(other.supersedes)
    return [by_id[name] for name in sorted(held)]


def _live_verify(
    by_id: Mapping[str, Task], superseded: Mapping[str, str], source: Task
) -> Tuple[str, Optional[str], List[Tuple[str, str]]]:
    """The Verify of a source that still runs, or the task that retired all of it, and the drops.

    The Verify of a fix task is exactly the composition that fix-tasks generates from the
    Verify of each task in its deps, so it carries a copy of each: only the copies that are
    not retired stay in the command. Any other Verify is one command. Each drop is
    (superseded task, superseding task); a copy whose command a live dependency still runs
    is not a drop.
    """

    if source.task_id in superseded:
        return "", superseded[source.task_id], [(source.task_id, superseded[source.task_id])]
    deps = [by_id[dependency] for dependency in source.deps if dependency in by_id]
    if not deps or source.verify != _common.fix_verify(dep.verify for dep in deps):
        return source.verify, None, []
    parts = [_live_verify(by_id, superseded, dep) for dep in deps]
    live = [command for command, retired_by, _ in parts if not retired_by]
    dropped = list(dict.fromkeys(drop for _, _, drops in parts for drop in drops
                                 if by_id[drop[0]].verify not in live))
    if not live:
        return "", parts[0][1], dropped
    return _common.fix_verify(live), None, dropped


def _regression_sources(
    tasks: Sequence[Task], task: Task
) -> List[Tuple[Task, List[str], Optional[str], str, List[Tuple[str, str]]]]:
    """Each `done` task whose Verify protects a file of this task:
    (source, replaced, retired_by, command, dropped).

    A source is a task of an earlier wave that shares a declared file with this task. A task
    that supersedes others inherits their role: it is also a source, in any wave, for a task
    that shares a file with a task it holds, and `replaced` names those tasks.
    `retired_by` names the task that supersedes the source: this task, or a `done` task. A
    retired Verify does not run, also not as a copy in the Verify of a fix task: `command`
    is the Verify that runs and `dropped` names each retired copy (`_live_verify`). The source still counts for the one-at-a-time
    rule, so the superseding task never runs beside a task that shares a file of the
    superseded task.
    """

    by_id = {other.task_id: other for other in tasks}
    superseded = _superseded(tasks, task)
    sources = []
    for other in tasks:
        if other.status != "done" or other.task_id == task.task_id:
            continue
        replaced = [held.task_id for held in _held(by_id, other) if _overlap(task, held)]
        if replaced or (other.wave < task.wave and _overlap(task, other)):
            command, retired_by, dropped = _live_verify(by_id, superseded, other)
            sources.append((other, replaced, retired_by, command, dropped))
    return sources


def _landing_tasks(repo: Path, task_id: str, project_dir: str) -> Tuple[List[Task], Task]:
    tasks = [
        _parse_task(path, path.relative_to(repo).as_posix())
        for path in sorted((repo / project_dir / "tasks").glob("*.md"))
    ]
    task = next((item for item in tasks if item.task_id == task_id), None)
    if task is None:
        raise BuildStateError("unknown-task", f"task file is missing: {task_id}")
    return tasks, task


def retired_verifies(
    repo: Path, task_id: str, project_dir: str = DEFAULT_PROJECT_DIR
) -> List[Dict[str, str]]:
    """Return the earlier-wave tasks whose Verify a landing of this task does not run again.

    A task's plan-approved `supersedes` names them. The Verify is retired for that task, and
    for every task that lands after that task is `done`: the Verify of the superseding task
    then runs in its place (`regression_verifies`, key `supersedes`). A fix task whose
    generated Verify holds only retired copies is here too. A fix task whose generated Verify
    loses some of its copies has one entry for each, with the superseded task under `part`.
    """

    tasks, task = _landing_tasks(repo, task_id, project_dir)
    retired: List[Dict[str, str]] = []
    for other, _, retired_by, _, dropped in _regression_sources(tasks, task):
        if retired_by:
            if other.verify:
                retired.append({"task": other.task_id, "superseded_by": retired_by})
        else:
            retired.extend({"task": other.task_id, "part": part, "superseded_by": by}
                           for part, by in dropped)
    return retired


def regression_verifies(
    repo: Path, task_id: str, own: str, project_dir: str = DEFAULT_PROJECT_DIR
) -> List[Dict[str, object]]:
    """Return the Verify commands of landed tasks that a landing of this task must also pass.

    One entry per distinct command, with every source task that has it, and under
    `supersedes` the tasks whose retired Verify it replaces for this landing. A command
    that the task's own Verify already runs is left out: an identical command, or
    a dependency's command when the own Verify is exactly the fix-task Verify of
    the task's dependencies. Text that only contains a command proves nothing.
    A retired Verify is not here, also not as a copy in the Verify of a fix task: see
    `retired_verifies`.
    """

    tasks, task = _landing_tasks(repo, task_id, project_dir)
    by_id = {item.task_id: item for item in tasks}
    composed = [by_id[dependency].verify for dependency in task.deps if dependency in by_id]
    covered = {own, *(composed if own == _common.fix_verify(composed) else ())}
    sources: Dict[str, Dict[str, object]] = {}
    for other, replaced, _, command, _ in _regression_sources(tasks, task):
        if command and command not in covered:
            entry = sources.setdefault(command, {"tasks": [], "command": command})
            entry["tasks"].append(other.task_id)
            if replaced:  # this Verify runs in the place of the Verify of each task it replaced
                entry["supersedes"] = sorted({*entry.get("supersedes", ()), *replaced})
    return list(sources.values())


def _blocked_wave_reviews(project: Project) -> Dict[int, int]:
    """Return waves whose highest canonical review cycle has a blocked lens."""

    review_dir = project.tasks_dir.parent / "review"
    if review_dir.is_symlink() or not review_dir.is_dir():
        return {}

    latest: Dict[int, int] = {}
    verdicts: Dict[Tuple[int, int], List[str]] = {}
    for path in sorted(review_dir.iterdir()):
        named = check_handoffs.WAVE_REVIEW_NAME.fullmatch(path.name)
        if named is None or path.is_symlink() or not path.is_file():
            continue
        wave, cycle = int(named.group("wave")), int(named.group("cycle"))
        latest[wave] = max(latest.get(wave, 0), cycle)
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        verdict = REVIEW_VERDICT_RE.search(text)
        if verdict is not None:
            verdicts.setdefault((wave, cycle), []).append(verdict.group("verdict"))

    return {
        wave: cycle
        for wave, cycle in latest.items()
        if "blocked" in verdicts.get((wave, cycle), [])
    }


def _unreviewed_waves(project: Project, waves: Sequence[int]) -> List[int]:
    """Return the given waves that still need a canonical review file of their own.

    A repair wave is left out: the next review cycle of its source wave judges it.
    """

    review_dir = project.tasks_dir.parent / "review"
    reviewed = {
        wave for wave in waves
        if all(task.review_findings for task in project.tasks if task.wave == wave)
    }
    if review_dir.is_dir() and not review_dir.is_symlink():
        for path in review_dir.iterdir():
            named = check_handoffs.WAVE_REVIEW_NAME.fullmatch(path.name)
            if named is not None and path.is_file() and not path.is_symlink():
                reviewed.add(int(named.group("wave")))
    return [wave for wave in waves if wave not in reviewed]


def ready(repo: str, project_dir: str = DEFAULT_PROJECT_DIR, *,
          allow_done: bool = False) -> Dict[str, object]:
    """Return task readiness, optionally accepting build/done for completion checks."""

    project = _load_project(repo, project_dir, ("active", "done") if allow_done else ("active",))
    reports = _validate_ready_metadata(project)
    by_id = {task.task_id: task for task in project.tasks}
    unfinished_waves = sorted({task.wave for task in project.tasks if task.status != "done"})
    current_wave = unfinished_waves[0] if unfinished_waves else None
    blocked_reviews = _blocked_wave_reviews(project)
    blocked_wave = min(
        (
            wave
            for wave in blocked_reviews
            if (current_wave is None or wave < current_wave)
            and any(task.wave == wave for task in project.tasks)
            and all(task.status == "done" for task in project.tasks if task.wave == wave)
        ),
        default=None,
    )
    repair_for_wave: Optional[int] = None
    blocked_review: Optional[Dict[str, object]] = None
    if blocked_wave is not None:
        source_ids = {task.task_id for task in project.tasks if task.wave == blocked_wave}
        repairs = [
            task
            for task in project.tasks
            if task.status != "done"
            and task.wave > blocked_wave
            and task.review_findings
            and source_ids.intersection(task.deps)
        ]
        if repairs:
            repair_for_wave = blocked_wave
            current_wave = min(task.wave for task in repairs)
        else:
            current_wave = blocked_wave
            blocked_review = {
                "wave": blocked_wave,
                "cycle": blocked_reviews[blocked_wave],
                "waiting_waves": unfinished_waves,
            }
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
    if current_wave is not None and blocked_review is None and not selectable and not wave_active:
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

    # Tasks that share a regression source land one at a time, each from the landing of the one
    # before, so the source's Verify runs on their combined edits. A parallel round leaves the
    # primary task file pending: a retained isolate shows that the task is already dispatched.
    # A retired source still counts: its superseding task holds its role.
    sources = {task.task_id: {other.task_id for other, _, _, _, _ in _regression_sources(project.tasks, task)}
               for task in concurrent}
    started = [task for task in selectable if reports[task.task_id].get("verdict") != "none"]
    claimed = {source for task in active + started for source in sources[task.task_id]}
    dispatchable = []
    for task in selectable:
        if task in started or not sources[task.task_id] & claimed:
            dispatchable.append(task)
            claimed |= sources[task.task_id]

    typed: Dict[str, object] = {}
    if repair_for_wave is not None:
        typed["repair_for_wave"] = repair_for_wave
    if blocked_review is not None:
        typed["blocked_review"] = blocked_review
    # Informational: every wave below the lowest unfinished wave is all done.
    unreviewed = _unreviewed_waves(project, sorted(
        {task.wave for task in project.tasks if unfinished_waves and task.wave < unfinished_waves[0]}
    ))
    if unreviewed:
        typed["unreviewed_waves"] = unreviewed
    return {
        "command": "ready",
        "branch": project.branch,
        "head": project.head,
        "current_wave": current_wave,
        **typed,
        "ready": [
            {
                "id": task.task_id,
                "title": task.title,
                "wave": task.wave,
                "status": task.status,
                "deps": list(task.deps),
                "files": list(task.files),
                "task_file": task.task_file,
                # The landing also runs each regression Verify, so a heavy one makes the task heavy.
                "verify_heavy": task.verify_heavy
                or any(other.verify_heavy and not retired_by
                       for other, _, retired_by, _, _ in _regression_sources(project.tasks, task)),
                **({"repo": task.repo} if task.repo else {}),
            }
            for task in dispatchable
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


def _member_checkout(repo: Path, member: Optional[str]) -> Path:
    if member is None:
        return repo
    try:
        import members
    except ImportError:  # pragma: no cover - package import used by tests
        from scripts import members
    try:
        listed = {item["name"]: Path(item["checkout"]) for item in members.read_members(repo)}
    except members.MembersError as error:
        raise BuildStateError("invalid-member", str(error)) from error
    if member not in listed:
        raise BuildStateError("invalid-member", f"{member} is not in MEMBERS.md")
    return listed[member]


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
                  execution: Optional[Dict[str, object]] = None,
                  member: Optional[str] = None,
                  rerun: bool = False) -> Dict[str, object]:
    """Append one verify run (command, commit, result, timestamp) to the ledger.

    A member run names its member and a commit in that member's repository.
    ``rerun`` marks an owner-requested re-execution at the same command and
    commit, so the ledger shows the earlier entry was superseded, not erased.
    """

    repository = _repo_root(repo)
    if result not in VERIFY_RESULTS:
        raise BuildStateError("invalid-result", "--result must be pass or fail")
    normalized, commit = _ledger_key(_member_checkout(repository, member), command, commit)
    ignore_error = _common.project_ignore_error(repository)
    if ignore_error:
        raise BuildStateError("ignored-ledger", ignore_error)
    path = _ledger_path(repository)
    _ledger_entries(path)
    entry = {
        "schema": _common.VERIFY_LEDGER_SCHEMA,
        "command": normalized,
        "commit": commit,
        "result": result,
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **({"repo": member} if member else {}),
        **({"rerun": True} if rerun else {}),
    }
    if execution is not None:
        if (not isinstance(execution.get("stdout"), str)
                or not isinstance(execution.get("stderr"), str)
                or type(execution.get("exit_code")) is not int
                or (execution["exit_code"] == 0) != (result == "pass")):
            raise BuildStateError("invalid-execution", "verification output and result disagree")
        if "cwd" in execution and not isinstance(execution["cwd"], str):
            raise BuildStateError("invalid-execution", "execution cwd must be a path string")
        if "base" in execution and not re.fullmatch(r"[0-9a-f]{40}", str(execution["base"])):
            raise BuildStateError("invalid-execution", "execution base must be a commit sha")
        location = execution.get("location")
        if isinstance(location, str) and "cwd" in execution and "worktree" in execution:
            if location.startswith("sidecar") and execution["cwd"] == execution["worktree"]:
                raise BuildStateError("invalid-execution",
                                      "a sidecar Verify cannot name the task checkout as its directory")
            if location.startswith("isolate") and execution["cwd"] != execution["worktree"]:
                raise BuildStateError("invalid-execution",
                                      "an isolate Verify must name its task worktree as its directory")
        entry["execution"] = execution
    path.parent.mkdir(parents=True, exist_ok=True)
    previous = path.read_text(encoding="utf-8") if path.exists() else ""
    _common.atomic_write(path, previous + json.dumps(entry, sort_keys=True) + "\n")
    return {"command": "verify-record", "ledger": VERIFY_LEDGER_PATH, "entry": entry}


def verify_lookup(repo: str, command: str, commit: str, member: Optional[str] = None) -> Dict[str, object]:
    """Return the latest recorded run of this command at this commit, or a miss."""

    repository = _repo_root(repo)
    normalized, commit = _ledger_key(_member_checkout(repository, member), command, commit)
    entry = _common.latest_verify_entry(_ledger_entries(_ledger_path(repository)), normalized, commit, member)
    return {
        "command": "verify-lookup",
        "ledger": VERIFY_LEDGER_PATH,
        "hit": entry is not None,
        "reuse": entry is not None and entry["result"] == "pass",
        "entry": entry,
    }


VERIFY_LOG_RE = re.compile(r"orchestrator Verify \((?:isolate|sidecar) [^)]+\): (pass|fail), exit \d+")
MEMBER_RECORD_RE = re.compile(r"^Member: (\S+) ([0-9a-f]{40}) ([0-9a-f]{40})$", re.MULTILINE)
GAP_MEMBER_RE = re.compile(r"^Member reviewed HEAD: (\S+) ([0-9a-f]{40})$", re.MULTILINE)
GAP_HEAD_RE = re.compile(r"^Reviewed HEAD: ([0-9a-f]{40})$", re.MULTILINE)
GAP_VERDICT_RE = re.compile(r"^Gap verdict: (pass|blocked)$", re.MULTILINE)


def _proven_landings(
    repository: Path,
    done_paths: Dict[str, Path],
    canonical_tasks_dir: str,
    head: str,
) -> Tuple[Dict[str, str], Dict[str, str]]:
    """Map each provably landed task id to its landing commit and record proof failures."""

    def collect(payload: Mapping[str, object]) -> Dict[str, str]:
        proven: Dict[str, str] = {}
        for item in payload["tasks"]:  # type: ignore[index]
            if not isinstance(item, Mapping):
                continue
            if str(item.get("verdict")) in LANDED_VERDICTS and item.get("commit"):
                proven[str(item.get("task_id"))] = str(item["commit"])
        return proven

    try:
        batch = verify_landed_task_files(repository, list(done_paths.values()), canonical_tasks_dir, head)
        return collect(batch), {}
    except IsolationError:
        pass
    proven: Dict[str, str] = {}
    errors: Dict[str, str] = {}
    for task_id, path in sorted(done_paths.items()):
        try:
            single = verify_landed_task_files(repository, [path], canonical_tasks_dir, head)
        except IsolationError as error:
            errors[task_id] = str(error)
            continue
        found = collect(single)
        if task_id in found:
            proven[task_id] = found[task_id]
    return proven, errors


def _ledger_absence_reason(
    repository: Path,
    task: Task,
    landing: str,
    member_landing: Optional[str],
    member_base: Optional[str],
) -> str:
    """Explain why a passing task has no reusable ledger row."""

    if task.repo:
        if not member_landing or not member_base:
            return "member record does not name the member landing"
        try:
            checkout = _member_checkout(repository, task.repo)
            parent = _git_output(checkout, "rev-parse", f"{member_landing}^")
        except BuildStateError:
            return "member checkout unavailable — the record condition cannot be re-derived"
        return ("ledger row absent although the member landing meets the record condition"
                if parent == member_base else
                "member landing parent differs from the member base — row deliberately not written")
    parent = _git_output(repository, "rev-parse", f"{landing}^")
    return ("ledger row absent although the landing meets the record condition"
            if parent == task.base else
            "landing parent differs from the recorded base — row deliberately not written")


def evidence_manifest(
    repo: str,
    project_dir: str,
    head: str,
    canonical_project_dir: str = DEFAULT_PROJECT_DIR,
) -> Dict[str, object]:
    """Join every task to its authoritative accepted evidence and classify the result.

    States: `ledger` (a reusable verify-ledger row matches the task's Verify command
    at its proven landing — for member tasks, at the member landing recorded in the
    coordinator record body), `log-only` (the retained task Log records the isolated
    Verify pass and the landing is proven, but no reusable row exists), `rejected`
    (the Log records a failed Verify, or a ledger row at the landing failed), and
    `superseded` / `missing` (a plan-approved supersedes retired the Verify, or no
    durable evidence exists at this head). A pass is never inferred from a Log label
    alone: done tasks require a proven first-parent landing, and member rows must
    match the recorded member landing. The project section reports the member
    milestone project Verify only when a final-gap artifact records a passing verdict
    at exactly this head (`gap-embedded`), or a reusable ledger row matches PLAN's
    project Verify command at this head (`ledger`); a blocked gap verdict or a
    different reviewed HEAD is listed but never accepted. Limits: failed-attempt
    executions kept only in uncommitted dispatch records are not consulted, and a
    noncanonical task artifact aborts with `invalid-task-file` naming the file — the
    same strictness as every other build_state command; fix or flag the file first.
    """

    repository = _repo_root(repo)
    artifact_dir, artifact_path = _project_path(repository, project_dir)
    canonical_dir, _ = _project_path(repository, canonical_project_dir)
    if not FULL_SHA_RE.fullmatch(head) or not _commit_resolves(repository, head):
        raise BuildStateError("invalid-head", "--head must be a full, existing commit SHA")
    if _git_output(repository, "rev-parse", f"{head}^{{commit}}") != head:
        raise BuildStateError("invalid-head", "--head must resolve to itself")
    tasks = _load_tasks(
        repository, artifact_dir, artifact_path, canonical_project_dir=canonical_dir
    )
    superseded_by: Dict[str, str] = {}
    for task in tasks:
        for earlier in task.supersedes:
            superseded_by.setdefault(earlier, task.task_id)
    done_paths = {
        task.task_id: artifact_path / "tasks" / Path(task.task_file).name
        for task in tasks if task.status == "done"
    }
    canonical_tasks_dir = str(PurePosixPath(canonical_dir) / "tasks")
    proven, proof_errors = (
        _proven_landings(repository, done_paths, canonical_tasks_dir, head) if done_paths else ({}, {})
    )
    ledger_path = _ledger_path(repository)
    entries = _ledger_entries(ledger_path) if ledger_path.exists() else []
    manifest: List[Dict[str, object]] = []
    for task in tasks:
        text = _read_file(
            artifact_path / "tasks" / Path(task.task_file).name,
            f"{artifact_dir}/tasks/{Path(task.task_file).name}",
        )
        results = VERIFY_LOG_RE.findall(text)
        entry: Dict[str, object] = {
            "task": task.task_id,
            "title": task.title,
            "status": task.status,
            "repo": task.repo or None,
            "verify_command": _common.task_verify_command(text),
            "superseded_by": superseded_by.get(task.task_id),
        }
        manifest.append(entry)
        if task.status != "done":
            entry["state"] = "rejected" if "fail" in results else "missing"
            entry["reason"] = "verify failed" if "fail" in results else "task never landed"
            if "fail" in results:
                entry["receipt"] = {"source": "task-log", "path": task.task_file}
            continue
        landing = proven.get(task.task_id)
        if landing is None:
            entry["state"] = "missing"
            entry["reason"] = ("landing proof failed: " + proof_errors[task.task_id]
                               if task.task_id in proof_errors
                               else "done task without a provable first-parent landing at this head")
            continue
        entry["landing"] = landing
        member_landing: Optional[str] = None
        member_base: Optional[str] = None
        if task.repo:
            body = _git_output(repository, "log", "-1", "--format=%b", landing)
            record = MEMBER_RECORD_RE.search(body)
            if record is None or record.group(1) != task.repo:
                entry["state"] = "missing"
                entry["reason"] = "member record commit does not name this member's landing"
                continue
            member_landing, member_base = record.group(2), record.group(3)
        lookup_commit = member_landing or landing
        if not entry["verify_command"]:
            entry["state"] = "missing"
            entry["reason"] = "landed task without a Verify command"
            continue
        try:
            lookup = verify_lookup(str(repository), str(entry["verify_command"]), lookup_commit,
                                   task.repo or None)
        except BuildStateError:
            lookup = None
        if lookup is not None and lookup["hit"]:
            entry["state"] = "ledger" if lookup["reuse"] else "rejected"
            entry["receipt"] = {"source": "verify-ledger", "commit": lookup_commit}
        elif "pass" in results:
            entry["state"] = "log-only"
            entry["receipt"] = {"source": "task-log", "path": task.task_file}
            entry["reason"] = _ledger_absence_reason(
                repository, task, landing, member_landing, member_base)
        elif entry["superseded_by"]:
            entry["state"] = "superseded"
            entry["reason"] = (f"verify retired by {entry['superseded_by']}; "
                               "the superseding task carries the evidence")
        else:
            entry["state"] = "missing"
            entry["reason"] = "proven landing without a recorded Verify result"
    gap_members: List[Dict[str, object]] = []
    gap_accepted = False
    gap_reasons: List[str] = []
    review_dir = repository.joinpath(*PurePosixPath(canonical_dir).parts) / "review"
    if review_dir.is_dir() and not review_dir.is_symlink():
        for path in sorted(review_dir.iterdir()):
            if _common.is_ignored_junk(path) or not path.is_file():
                continue
            if not re.fullmatch(r"final-gap-\d+\.md", path.name):
                continue
            text = path.read_text(encoding="utf-8")
            verdict = GAP_VERDICT_RE.findall(text)
            reviewed = GAP_HEAD_RE.findall(text)
            for name, sha in GAP_MEMBER_RE.findall(text):
                gap_members.append({
                    "member": name,
                    "head": sha,
                    "verdict": verdict[-1] if verdict else None,
                    "source": f"{canonical_dir}/review/{path.name}",
                })
            if not any(name for name, _ in GAP_MEMBER_RE.findall(text)):
                continue
            if verdict and verdict[-1] == "pass" and reviewed and reviewed[-1] == head:
                gap_accepted = True
            else:
                gap_reasons.append(
                    f"{path.name}: verdict {verdict[-1] if verdict else 'unreadable'}"
                    f" at reviewed HEAD {reviewed[-1] if reviewed else 'unreadable'}")
    plan = _read_file(artifact_path / "plan" / "PLAN.md", f"{artifact_dir}/plan/PLAN.md")
    try:
        project_command = check_handoffs._line_value(plan, "Project verify:")
    except check_handoffs.HandoffError:
        project_command = ""
    project_state = "missing"
    project_reason: Optional[str] = None
    if gap_accepted:
        project_state = "gap-embedded"
    elif gap_reasons:
        project_reason = "; ".join(gap_reasons)
    elif project_command:
        project_lookup = verify_lookup(str(repository), project_command, head)
        if project_lookup["reuse"]:
            project_state = "ledger"
        elif project_lookup["hit"]:
            project_reason = "the recorded project Verify row at this head failed"
    elif gap_members:
        project_reason = "final-gap member results exist but none prove this head"
    return {
        "command": "evidence-manifest",
        "project_dir": artifact_dir,
        "canonical_project_dir": canonical_dir,
        "head": head,
        "tasks": manifest,
        "project": {
            "members": gap_members or None,
            "state": project_state,
            **({"reason": project_reason} if project_reason else {}),
        },
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
    manifest_parser = subcommands.add_parser(
        "evidence-manifest", help="join every task to its authoritative accepted evidence"
    )
    manifest_parser.add_argument("--repo", required=True)
    manifest_parser.add_argument("--project-dir", default=DEFAULT_PROJECT_DIR)
    manifest_parser.add_argument("--head", required=True)
    manifest_parser.add_argument("--canonical-project-dir", default=DEFAULT_PROJECT_DIR)
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
        elif arguments.command == "evidence-manifest":
            result = evidence_manifest(
                arguments.repo,
                arguments.project_dir,
                arguments.head,
                arguments.canonical_project_dir,
            )
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
