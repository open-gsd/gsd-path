# gsd-path project runtime
"""Guard return to Define or Plan using a committed recovery base."""

from __future__ import annotations

import sys

# Runtime helpers must not modify their immutable installation.
sys.dont_write_bytecode = True

import json
import re
from pathlib import Path


EVENTS = {
    "define": "build intent corrections requested",
    "plan": "build plan repair requested",
}
PLAN_INTENT_EVENT = "plan intent corrections requested"
MARKER = "build recovery: "
RECOVERY_KEYS = frozenset({"base", "branch", "kind", "source"})


def runtime():
    if __package__:
        from scripts import pipeline_state
    else:
        import pipeline_state
    return pipeline_state


def checkpoint_runtime():
    if __package__:
        from scripts import state_checkpoint
    else:
        import state_checkpoint
    return state_checkpoint


def _parse_recovery_record(value: object) -> dict:
    if (
        not isinstance(value, dict)
        or not {"base", "branch", "kind"}.issubset(value)
        or not set(value).issubset(RECOVERY_KEYS)
        or not isinstance(value["base"], str)
        or not re.fullmatch(r"[0-9a-f]{40}", value["base"])
    ):
        raise runtime().PipelineStateError("invalid build recovery record")
    source = value.get("source", "build")
    if source not in {"build", "plan"}:
        raise runtime().PipelineStateError("invalid build recovery record")
    if source == "plan":
        if value["kind"] != "define":
            raise runtime().PipelineStateError("invalid build recovery record")
    elif value["kind"] not in EVENTS:
        raise runtime().PipelineStateError("invalid build recovery record")
    return {**value, "source": source}


def _recovery_base_proves_milestone(before, current, source: str) -> bool:
    if before.branch != current.branch or before.milestone != current.milestone:
        return False
    if source == "plan":
        return (before.phase, before.status) in {("plan", "active"), ("plan", "blocked")}
    return (before.phase, before.status) == ("build", "blocked")


def context(repo: Path, text: str | None = None) -> dict | None:
    state = runtime()
    try:
        current, loaded, _ = state.load_state(repo)
    except state.PipelineStateError as error:
        if "STATE.md must be a real file" not in str(error):
            raise
        return None
    text = loaded if text is None else text
    recovery = None
    for line in text.splitlines():
        if " — " not in line:
            continue
        event = line.split(" — ", 2)[-1]
        if event.startswith(MARKER):
            try:
                value = _parse_recovery_record(json.loads(event[len(MARKER):]))
            except ValueError as error:
                raise state.PipelineStateError("invalid build recovery record") from error
            recovery = {**value, "active": True} if value["branch"] == current.branch else None
        elif recovery and recovery.get("active"):
            source = recovery.get("source", "build")
            if source == "build" and event == "build started":
                recovery["active"] = False
            elif source == "plan" and event == "plan approved":
                recovery["active"] = False
    if recovery:
        if not state._is_ancestor(repo, recovery["base"], "HEAD"):
            raise state.PipelineStateError("build recovery base is not an ancestor of HEAD")
        base_text = checkpoint_runtime()._git_text_at(repo, recovery["base"], ".project/STATE.md")
        if base_text is None:
            raise state.PipelineStateError("build recovery base has no STATE.md")
        before = state._state_from_text(base_text)
        if not _recovery_base_proves_milestone(before, current, recovery.get("source", "build")):
            raise state.PipelineStateError("build recovery base does not prove this blocked milestone")
    return recovery


def task_fields(text: str, label: str) -> dict:
    if __package__:
        from scripts.isolation import task_frontmatter
    else:
        from isolation import task_frontmatter
    fields, error = task_frontmatter(text)
    if fields is None:
        raise runtime().PipelineStateError(f"{label}: {error}")
    return fields


def settled_tasks(repo: Path) -> dict[str, tuple[str, dict]]:
    """Read task ownership without requiring the graph that Plan must repair."""
    state = runtime()
    directory = repo / ".project/tasks"
    if directory.is_symlink() or not directory.is_dir():
        raise state.PipelineStateError("build recovery requires real task artifacts")
    tasks = {}
    for path in sorted(directory.iterdir()):
        if state._common.is_ignored_junk(path):
            continue
        if not re.fullmatch(r"T[0-9]{3}-[a-z0-9][a-z0-9-]*\.md", path.name):
            raise state.PipelineStateError(f"invalid recovery task path: {path.name}")
        text = state._read_real_file(path, path.name)
        fields = task_fields(text, path.name)
        if fields.get("status") not in {"pending", "done"}:
            raise state.PipelineStateError(f"settle task ownership before recovery: {path.name}")
        if fields["status"] == "pending" and any(
            fields.get(key) != "null" for key in ("agent", "base", "worktree", "task_branch")
        ):
            raise state.PipelineStateError(f"pending task retains dispatch metadata: {path.name}")
        tasks[path.name] = (text, fields)
    if not tasks:
        raise state.PipelineStateError("build recovery requires task artifacts")
    return tasks


def _begin_common(repo: Path, before, event: str) -> str:
    state = runtime()
    if before.archive is not None or before.branch != state._current_branch(repo):
        raise state.PipelineStateError("build recovery requires the active bound branch")
    if state._worktree_changes(repo):
        raise state.PipelineStateError("checkpoint the blocked build before recovery")
    if any(state.transaction_journals(repo).values()):
        raise state.PipelineStateError("finish pending transactions before build recovery")
    state._read_real_file(repo / ".project/intent/INTENT.md", "INTENT.md")
    return state._run_git(repo, "rev-parse", "HEAD").stdout.strip()


def _settle_build_dispatch(repo: Path) -> None:
    state = runtime()
    records = records_root(repo)
    for directory in {path.parent.parent for path in records.rglob("attempt-*/state.json")}:
        latest = max(directory.glob("attempt-*/state.json"), key=lambda path: int(path.parent.name.split("-")[1]))
        record = state._read_json(latest)
        if (record.get("cleanup_pending")
                or (record.get("worktree") and record.get("branch") and not record.get("cleanup_complete"))
                or record.get("outcome") not in {"landed", "collected", "blocked", "resolved", "redispatched"}):
            raise state.PipelineStateError(f"settle dispatch records before recovery: {latest}")


def _verify_done_tasks(repo: Path, tasks: dict[str, tuple[str, dict]], base: str) -> None:
    state = runtime()
    done = [repo / ".project/tasks" / name for name, (_, fields) in tasks.items()
            if fields["status"] == "done"]
    if not done:
        return
    if __package__:
        from scripts.isolation import verify_landed_task_files
    else:
        from isolation import verify_landed_task_files
    verify_landed_task_files(repo, done, ".project/tasks", base)


def begin(repo: Path, before, after, event: str) -> dict:
    state = runtime()
    if (before.phase, before.status) == ("build", "blocked") and after.phase in EVENTS:
        if event != EVENTS[after.phase]:
            raise state.PipelineStateError(f"state transition requires event: {EVENTS[after.phase]}")
        _settle_build_dispatch(repo)
        tasks = settled_tasks(repo)
        state._read_real_file(repo / ".project/plan/PLAN.md", "PLAN.md")
        base = _begin_common(repo, before, event)
        _verify_done_tasks(repo, tasks, base)
        return {"kind": after.phase, "base": base, "branch": before.branch, "source": "build"}
    if (
        before.phase == "plan"
        and before.status in {"active", "blocked"}
        and (after.phase, after.status) == ("define", "active")
    ):
        if event != PLAN_INTENT_EVENT:
            raise state.PipelineStateError(f"state transition requires event: {PLAN_INTENT_EVENT}")
        state._read_real_file(repo / ".project/plan/PLAN.md", "PLAN.md")
        tasks_dir = repo / ".project/tasks"
        tasks = settled_tasks(repo) if tasks_dir.is_dir() and any(
            path.is_file() and not state._common.is_ignored_junk(path)
            for path in tasks_dir.iterdir()
        ) else {}
        base = _begin_common(repo, before, event)
        _verify_done_tasks(repo, tasks, base)
        return {"kind": "define", "base": base, "branch": before.branch, "source": "plan"}
    raise state.PipelineStateError("build recovery requires build/blocked")


def records_root(repo: Path) -> Path:
    if __package__:
        from scripts import isolation
    else:
        import isolation
    root = isolation.common_git_dir(repo) / "gsd-path/dispatch" / isolation.require_bound(repo).replace("/", "-")
    recovery = context(repo)
    return root / recovery["base"] if recovery else root


def review_backup(repo: Path, recovery: dict) -> Path:
    return repo / ".project/plan" / f"build-recovery-{recovery['base']}" / "review"


def validate_review_backup(repo: Path, recovery: dict, directory: Path) -> None:
    state = runtime()
    if directory.exists():
        checkpoint_runtime()._tree_digest(directory)  # Reject symlinks and special files before reading.
    expected = {}
    for path in state._run_git(repo, "ls-tree", "-r", "--name-only", "-z",
                               recovery["base"], "--", ".project/review").stdout.split("\0"):
        if path:
            expected[str(Path(path).relative_to(".project/review"))] = checkpoint_runtime()._git_text_at(repo, recovery["base"], path)
    actual = {str(path.relative_to(directory)): path.read_text(encoding="utf-8")
              for path in directory.rglob("*")
              if path.is_file() and not state._common.is_ignored_junk(path)} if directory.exists() else {}
    if actual != expected:
        raise state.PipelineStateError("review backup differs from the recovery base")


def prepare(repo: Path) -> dict:
    """Move old reviews once; the durable STATE record owns interruption recovery."""
    state = runtime()
    repo = state._repo_root(repo)
    with state._state_lock(repo / ".project"):
        recovery = context(repo)
        if not recovery or not recovery["active"]:
            raise state.PipelineStateError("no active build recovery")
        target = review_backup(repo, recovery)
        if (repo / ".project/plan").is_symlink() or target.parent.is_symlink() or target.is_symlink():
            raise state.PipelineStateError("unsafe recovery review backup")
        source = repo / ".project/review"
        if source.is_symlink():
            raise state.PipelineStateError("unsafe recovery review directory")
        if not target.exists():
            validate_review_backup(repo, recovery, source)
            target.parent.mkdir(exist_ok=True)
            if source.exists():
                source.rename(target)
            else:
                target.mkdir()
        validate_review_backup(repo, recovery, target)
        source.mkdir(exist_ok=True)
    return {"status": "prepared", "recovery": recovery, "path": str(target)}


def validate_plan(repo: Path) -> None:
    state = runtime()
    recovery = context(repo)
    if not recovery or not recovery["active"]:
        return
    if not review_backup(repo, recovery).is_dir():
        raise state.PipelineStateError("run prepare-build-recovery before planning")
    validate_review_backup(repo, recovery, review_backup(repo, recovery))
    source = checkpoint_runtime()._task_contracts_at(repo, recovery["base"], ".project/tasks")
    current = settled_tasks(repo)
    done = set()
    for _, (path, text) in source.items():
        fields = task_fields(text, path)
        if fields.get("status") == "done":
            name = Path(path).name
            done.add(name)
            if name not in current or current[name][0] != text:
                raise state.PipelineStateError(f"build recovery must preserve landed task: {name}")
    if any(fields["status"] == "done" and name not in done
           for name, (_, fields) in current.items()):
        raise state.PipelineStateError("build recovery cannot manufacture landed tasks")
    if recovery["kind"] == "plan":
        intent = checkpoint_runtime()._git_text_at(repo, recovery["base"], ".project/intent/INTENT.md")
        if state._read_real_file(repo / ".project/intent/INTENT.md", "INTENT.md") != intent:
            raise state.PipelineStateError("plan repair cannot change approved intent")
    unchanged = unchanged_waves(repo, recovery)
    for path in (repo / ".project/review").iterdir():
        match = re.match(r"wave-([1-9]\d*)[.]", path.name)
        if match and int(match[1]) not in unchanged:
            raise state.PipelineStateError("changed wave must be reviewed after build resumes")


def unchanged_waves(repo: Path, recovery: dict) -> set[int]:
    """Reuse evidence only when its intent, wave contract, and task bytes match."""
    state = runtime()
    project = repo / ".project"
    old_intent = checkpoint_runtime()._git_text_at(repo, recovery["base"], ".project/intent/INTENT.md")
    if state._read_real_file(project / "intent/INTENT.md", "INTENT.md") != old_intent:
        return set()
    old_plan = checkpoint_runtime()._git_text_at(repo, recovery["base"], ".project/plan/PLAN.md") or ""
    new_plan = state._read_real_file(project / "plan/PLAN.md", "PLAN.md")

    def sections(text):
        return {match[1]: match[2] for match in re.finditer(
            r"(?ms)^## ([^\n]+)\n(.*?)(?=^## |\Z)", text,
        )}

    old_sections, new_sections = sections(old_plan), sections(new_plan)
    # Non-wave settings govern every wave, including coverage and surfaces.
    if ({k: v for k, v in old_sections.items() if not k.startswith("Wave ")}
            != {k: v for k, v in new_sections.items() if not k.startswith("Wave ")}):
        return set()
    old_tasks = checkpoint_runtime()._task_contracts_at(repo, recovery["base"], ".project/tasks")
    current = settled_tasks(repo)
    unchanged = set()
    for title, body in new_sections.items():
        match = re.match(r"Wave ([1-9]\d*)\b", title)
        if not match or old_sections.get(title) != body:
            continue
        wave = match[1]
        before = {Path(path).name: text for path, text in old_tasks.values()
                  if task_fields(text, path).get("wave") == wave}
        after = {name: text for name, (text, fields) in current.items() if fields.get("wave") == wave}
        if before and before == after:
            unchanged.add(int(wave))
    return unchanged


def restore_unchanged_reviews(repo: Path) -> None:
    recovery = context(repo)
    if not recovery or not recovery["active"]:
        return
    unchanged = unchanged_waves(repo, recovery)
    for path in review_backup(repo, recovery).iterdir():
        match = re.match(r"wave-([1-9]\d*)[.]", path.name)
        if match and int(match[1]) in unchanged:
            destination = repo / ".project/review" / path.name
            content = path.read_text(encoding="utf-8")
            if not destination.exists() or runtime()._read_real_file(destination, destination.name) != content:
                runtime()._atomic_write(destination, content)


def inventory_checkpoint(repo: Path, head: str) -> bool:
    state = runtime()
    if state._run_git(repo, "show", "-s", "--format=%s", head).stdout.strip() != state.PLAN_APPROVAL_SUBJECT:
        return False
    text = checkpoint_runtime()._git_text_at(repo, head, ".project/STATE.md")
    if text is None:
        return False
    approved = state._state_from_text(text)
    if (approved.phase, approved.status) != ("plan", "done"):
        return False
    recovery = context(repo, text)
    return bool(recovery and recovery["active"])
