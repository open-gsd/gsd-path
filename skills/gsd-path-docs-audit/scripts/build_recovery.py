# gsd-path project runtime
"""Guard a blocked build's return to Define or Plan using its committed base."""

from __future__ import annotations

import json
import re
from pathlib import Path


EVENTS = {
    "define": "build intent corrections requested",
    "plan": "build plan repair requested",
}
MARKER = "build recovery: "


def runtime():
    if __package__:
        from scripts import pipeline_state
    else:
        import pipeline_state
    return pipeline_state


def context(repo: Path, text: str | None = None) -> dict | None:
    state = runtime()
    current, loaded, _ = state.load_state(repo)
    text = loaded if text is None else text
    recovery = None
    for line in text.splitlines():
        if " — " not in line:
            continue
        event = line.split(" — ", 2)[-1]
        if event.startswith(MARKER):
            try:
                value = json.loads(event[len(MARKER):])
            except ValueError as error:
                raise state.PipelineStateError("invalid build recovery record") from error
            if (not isinstance(value, dict) or set(value) != {"base", "branch", "kind"}
                    or value["kind"] not in EVENTS
                    or not isinstance(value["base"], str)
                    or not re.fullmatch(r"[0-9a-f]{40}", value["base"])):
                raise state.PipelineStateError("invalid build recovery record")
            recovery = {**value, "active": True} if value["branch"] == current.branch else None
        elif event == "build started" and recovery:
            recovery["active"] = False
    if recovery:
        if not state._is_ancestor(repo, recovery["base"], "HEAD"):
            raise state.PipelineStateError("build recovery base is not an ancestor of HEAD")
        source = state._git_text_at(repo, recovery["base"], ".project/STATE.md")
        if source is None:
            raise state.PipelineStateError("build recovery base has no STATE.md")
        before = state._state_from_text(source)
        if ((before.phase, before.status) != ("build", "blocked")
                or before.branch != current.branch or before.milestone != current.milestone):
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


def begin(repo: Path, before, after, event: str) -> dict:
    state = runtime()
    if (before.phase, before.status) != ("build", "blocked") or after.phase not in EVENTS:
        raise state.PipelineStateError("build recovery requires build/blocked")
    if event != EVENTS[after.phase]:
        raise state.PipelineStateError(f"state transition requires event: {EVENTS[after.phase]}")
    if before.archive is not None or before.branch != state._current_branch(repo):
        raise state.PipelineStateError("build recovery requires the active bound branch")
    if state._worktree_changes(repo):
        raise state.PipelineStateError("checkpoint the blocked build before recovery")
    if any(state.transaction_journals(repo).values()):
        raise state.PipelineStateError("finish pending transactions before build recovery")
    records = records_root(repo)
    for directory in {path.parent.parent for path in records.rglob("attempt-*/state.json")}:
        latest = max(directory.glob("attempt-*/state.json"), key=lambda path: int(path.parent.name.split("-")[1]))
        record = state._read_json(latest)
        if record.get("outcome") not in {"landed", "collected", "blocked", "resolved", "redispatched"}:
            raise state.PipelineStateError(f"settle dispatch records before recovery: {latest}")
    tasks = settled_tasks(repo)
    state._read_real_file(repo / ".project/plan/PLAN.md", "PLAN.md")
    state._read_real_file(repo / ".project/intent/INTENT.md", "INTENT.md")
    base = state._run_git(repo, "rev-parse", "HEAD").stdout.strip()
    done = [repo / ".project/tasks" / name for name, (_, fields) in tasks.items()
            if fields["status"] == "done"]
    if done:
        if __package__:
            from scripts.isolation import verify_landed_task_files
        else:
            from isolation import verify_landed_task_files
        verify_landed_task_files(repo, done, ".project/tasks", base)
    return {"kind": after.phase, "base": base, "branch": before.branch}


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
        state._tree_digest(directory)  # Reject symlinks and special files before reading.
    expected = {}
    for path in state._run_git(repo, "ls-tree", "-r", "--name-only", "-z",
                               recovery["base"], "--", ".project/review").stdout.split("\0"):
        if path:
            expected[str(Path(path).relative_to(".project/review"))] = state._git_text_at(repo, recovery["base"], path)
    actual = {str(path.relative_to(directory)): path.read_text(encoding="utf-8")
              for path in directory.rglob("*") if path.is_file()} if directory.exists() else {}
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
    source = state._task_contracts_at(repo, recovery["base"], ".project/tasks")
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
        intent = state._git_text_at(repo, recovery["base"], ".project/intent/INTENT.md")
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
    old_intent = state._git_text_at(repo, recovery["base"], ".project/intent/INTENT.md")
    if state._read_real_file(project / "intent/INTENT.md", "INTENT.md") != old_intent:
        return set()
    old_plan = state._git_text_at(repo, recovery["base"], ".project/plan/PLAN.md") or ""
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
    old_tasks = state._task_contracts_at(repo, recovery["base"], ".project/tasks")
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
    text = state._git_text_at(repo, head, ".project/STATE.md")
    if text is None:
        return False
    approved = state._state_from_text(text)
    if (approved.phase, approved.status) != ("plan", "done"):
        return False
    recovery = context(repo, text)
    return bool(recovery and recovery["active"])
