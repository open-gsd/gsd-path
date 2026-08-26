#!/usr/bin/env python3
"""Install GSD Path skills for supported coding agents."""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple

try:
    from . import sync_skill_resources
except ImportError:  # Direct execution from scripts/.
    import sync_skill_resources  # type: ignore


def skill_names_for_manifest(manifest: Mapping) -> Tuple[str, ...]:
    return tuple(manifest["skills"])


def targets_for_manifest(manifest: Mapping) -> Tuple[str, ...]:
    return tuple(manifest["hosts"])


def local_roots_for_manifest(manifest: Mapping) -> Mapping[str, str]:
    return {
        target: config["local_root"]
        for target, config in manifest["hosts"].items()
    }


TARGETS = targets_for_manifest(sync_skill_resources.RESOURCE_MANIFEST)
LOCAL_ROOTS = local_roots_for_manifest(sync_skill_resources.RESOURCE_MANIFEST)
SKILL_NAMES = skill_names_for_manifest(sync_skill_resources.RESOURCE_MANIFEST)
SKILL_ALIASES = dict(sync_skill_resources.RESOURCE_MANIFEST["skill_aliases"])
CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n"
HOOKS_DIRECTORY = ".gsd-path"
GUARD_SCRIPTS = ("guard_hook.py", "git_guard.py")
GUARD_MARKER = "gsd-path guard"
INSTALL_LOCK_NAME = ".gsd-path-install-lock"
CLAUDE_MATCHER = (
    "Edit|Write|MultiEdit|NotebookEdit|Delete|StrReplace|ApplyPatch|Create|Shell|Bash"
)
def _claude_guard_entry(interpreter: str) -> dict:
    """The managed PreToolUse guard entry, as an object."""
    return {
        "matcher": CLAUDE_MATCHER,
        "hooks": [
            {
                "type": "command",
                "command": (
                    f"{interpreter} \"$CLAUDE_PROJECT_DIR/"
                    f"{HOOKS_DIRECTORY}/guard_hook.py\""
                ),
            }
        ],
    }


def claude_hooks_settings(interpreter: str) -> str:
    return (
        json.dumps(
            {"hooks": {"PreToolUse": [_claude_guard_entry(interpreter)]}},
            indent=2,
        )
        + "\n"
    )


def _codex_guard_command(interpreter: str) -> str:
    return (
        f'{interpreter} "$(git rev-parse --show-toplevel)/'
        f'{HOOKS_DIRECTORY}/guard_hook.py"'
    )


def _codex_guard_command_windows(interpreter: str) -> str:
    return (
        'powershell.exe -NoProfile -NonInteractive -Command '
        '"$root = git rev-parse --show-toplevel; '
        f"& {interpreter} (Join-Path $root '{HOOKS_DIRECTORY}\\guard_hook.py')\""
    )


def codex_hooks_settings(interpreter: str) -> str:
    return json.dumps(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "matcher": ".*",
                        "hooks": [
                            {
                                "type": "command",
                                "command": _codex_guard_command(interpreter),
                                "commandWindows": _codex_guard_command_windows(
                                    interpreter
                                ),
                            }
                        ],
                    }
                ]
            }
        },
        indent=2,
    ) + "\n"


def cursor_hooks_settings(interpreter: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "hooks": {
                "preToolUse": [
                    {
                        "command": f'{interpreter} "{HOOKS_DIRECTORY}/guard_hook.py"',
                        "matcher": ".*",
                        "failClosed": True,
                    }
                ]
            },
        },
        indent=2,
    ) + "\n"


def pre_commit_hook(interpreter: str) -> str:
    return (
        "#!/bin/sh\n"
        "# gsd-path guard: archive immutability before commit.\n"
        f"exec {interpreter} \"$(git rev-parse --show-toplevel)/"
        f"{HOOKS_DIRECTORY}/git_guard.py\" pre-commit\n"
    )


def commit_msg_hook(interpreter: str) -> str:
    return (
        "#!/bin/sh\n"
        "# gsd-path guard: archive immutability and ship-commit purity.\n"
        f"exec {interpreter} \"$(git rev-parse --show-toplevel)/"
        f"{HOOKS_DIRECTORY}/git_guard.py\" commit-msg \"$1\"\n"
    )


def _detect_python_interpreter() -> Optional[str]:
    """Probe for a runnable interpreter (python3, then python).

    Emitted hooks must never hard-code an interpreter that does not exist on
    this machine (python3 is typically absent on Windows).
    """
    for candidate in ("python3", "python"):
        try:
            result = subprocess.run(
                [candidate, "--version"], capture_output=True, check=False
            )
        except OSError:
            continue
        if result.returncode == 0:
            return candidate
    return None


def _effective_interpreter() -> Optional[str]:
    """Single owner of the interpreter probe and its policy.

    Returns the probed interpreter, or None when no interpreter works —
    callers must then skip writing hook content instead of pinning a
    nonexistent python3.
    """
    return _detect_python_interpreter()


def _resolve_git_hooks_path(project: "Path") -> Optional["Path"]:
    """Effective hooks dir via `git rev-parse --git-path hooks`.

    Honors core.hooksPath and linked worktrees. Returns None when git cannot
    resolve it for this project.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel", "--git-path", "hooks"],
            cwd=os.fspath(project),
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return None
    if result.returncode != 0:
        return None
    lines = [line for line in result.stdout.splitlines() if line]
    if len(lines) != 2:
        return None
    toplevel, hooks_path = lines
    if not _same_path(Path(toplevel), project):
        return None
    return Path(os.path.abspath(os.path.join(os.fspath(project), hooks_path)))


def _git_hooks_directory(project: "Path") -> Optional["Path"]:
    dot_git = project / ".git"
    if not _lexists(dot_git):
        return None
    resolved = _resolve_git_hooks_path(project)
    if resolved is not None:
        return resolved
    # Fallback when git is not runnable: only a plain .git directory is safe.
    return dot_git / "hooks" if dot_git.is_dir() else None
OPENCODE_NOTE = (
    "note: OpenCode stable discovers the skills but has no documented hard "
    'explicit-only switch; OpenCode v2 honors opencode/autoinvoke="false" '
    "and /gsd-path."
)
ANTIGRAVITY_NOTE = (
    "note: Antigravity discovers /gsd-path but has no documented hard "
    "explicit-only skill switch; invoke the skill explicitly."
)
KIRO_NOTE = (
    "note: Kiro discovers /gsd-path but has no documented hard explicit-only "
    "skill switch; invoke the skill explicitly."
)
HOST_NOTES = {
    "opencode": OPENCODE_NOTE,
    "antigravity": ANTIGRAVITY_NOTE,
    "kiro": KIRO_NOTE,
}
EXPLICIT_ONLY_TARGETS = frozenset(
    {"claude", "grok", "copilot", "qwen", "cursor", "zed", "kimi", "shared-agents"}
)
SHARED_AGENT_TARGETS = frozenset({"codex", "antigravity", "zed"})
SHARED_AGENT_PROFILE = "shared-agents"
CURSOR_AGENT_FILENAME = "gsd-path.md"
CURSOR_AGENT_BACKUP_NAME = "cursor-agent-gsd-path.md"


class InstallerError(RuntimeError):
    """A safe, user-facing installation failure."""


@dataclass(frozen=True)
class TargetPlan:
    name: str
    root: Path


@dataclass(frozen=True)
class DeploymentPlan:
    profile: str
    root: Path
    targets: Tuple[str, ...]


@dataclass
class TargetTransaction:
    root: Path
    created_directories: List[Path] = field(default_factory=list)
    backup: Optional[Path] = None
    moved: List[Tuple[Path, Path]] = field(default_factory=list)
    installed: List[Path] = field(default_factory=list)


@dataclass
class ProjectTransaction:
    created_directories: List[Path] = field(default_factory=list)
    copied: List[Path] = field(default_factory=list)


def absolute_path(path: Path) -> Path:
    return Path(os.path.abspath(os.fspath(path.expanduser())))


def local_root(target: str, project_dir: Path) -> Path:
    try:
        relative = LOCAL_ROOTS[target]
    except KeyError as error:
        raise ValueError(f"unsupported target: {target}") from error
    return absolute_path(project_dir) / relative


def default_root(target: str, environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    if target == "codex":
        return absolute_path(Path("~/.agents/skills"))
    if target == "claude":
        return absolute_path(Path(env.get("CLAUDE_CONFIG_DIR") or "~/.claude") / "skills")
    if target == "grok":
        return absolute_path(Path(env.get("GROK_HOME") or "~/.grok") / "skills")
    if target == "opencode":
        config_dir = env.get("OPENCODE_CONFIG_DIR")
        if config_dir:
            base = Path(config_dir)
        else:
            config_file = env.get("OPENCODE_CONFIG")
            if config_file:
                base = absolute_path(Path(config_file)).parent
            else:
                base = Path(env.get("XDG_CONFIG_HOME") or "~/.config") / "opencode"
        return absolute_path(base / "skills")
    if target == "copilot":
        return absolute_path(Path(env.get("COPILOT_HOME") or "~/.copilot") / "skills")
    if target == "qwen":
        return absolute_path(Path(env.get("QWEN_HOME") or "~/.qwen") / "skills")
    if target == "antigravity":
        return absolute_path(Path("~/.gemini/antigravity-cli/skills"))
    if target == "cursor":
        return absolute_path(Path("~/.cursor/skills"))
    if target == "zed":
        return absolute_path(Path("~/.agents/skills"))
    if target == "kiro":
        return absolute_path(Path(env.get("KIRO_HOME") or "~/.kiro") / "skills")
    if target == "kimi":
        return absolute_path(
            Path(env.get("KIMI_CODE_HOME") or "~/.kimi-code") / "skills"
        )
    raise ValueError(f"unsupported target: {target}")


def legacy_codex_root(environ: Optional[Mapping[str, str]] = None) -> Path:
    env = os.environ if environ is None else environ
    return absolute_path(Path(env.get("CODEX_HOME") or "~/.codex") / "skills")


def _is_managed_name(name: str) -> bool:
    normalized = name.casefold()
    return normalized in ("ogsd", "gsd-path") or normalized.startswith(
        ("ogsd-", "gsd-path-")
    )


def _lexists(path: Path) -> bool:
    return os.path.lexists(os.fspath(path))


def _validate_directory_destination(path: Path, label: str) -> None:
    if _lexists(path):
        if path.is_symlink():
            raise InstallerError(f"{label} is a symlink: {path}")
        if not path.is_dir():
            raise InstallerError(f"{label} is not a directory: {path}")
        return
    parent = path.parent
    while not _lexists(parent):
        parent = parent.parent
    if parent.is_symlink() or not parent.is_dir():
        raise InstallerError(f"{label} has an unsafe parent: {parent}")


def _reject_source_symlinks(path: Path) -> None:
    for directory, names, files in os.walk(path, followlinks=False):
        base = Path(directory)
        for name in names + files:
            candidate = base / name
            if candidate.is_symlink():
                raise InstallerError(f"source contains a symlink: {candidate}")


def validate_source(source_root: Path, profiles: Sequence[str]) -> Tuple[str, ...]:
    problems = sync_skill_resources.mismatches(source_root)
    if problems:
        raise InstallerError("source resources are stale: " + "; ".join(problems))

    skills_root = source_root / "skills"
    if not skills_root.is_dir() or skills_root.is_symlink():
        raise InstallerError(f"missing safe skills directory: {skills_root}")
    found = {
        entry.name
        for entry in skills_root.iterdir()
        if _is_managed_name(entry.name) and entry.name.startswith("gsd-path")
    }
    if found != set(SKILL_NAMES):
        raise InstallerError(
            f"expected exactly {len(SKILL_NAMES)} GSD Path skills; found "
            + ", ".join(sorted(found))
        )
    for name in SKILL_NAMES:
        skill = skills_root / name
        if skill.is_symlink() or not skill.is_dir() or not (skill / "SKILL.md").is_file():
            raise InstallerError(f"invalid skill directory: {skill}")
        _reject_source_symlinks(skill)

    for profile in profiles:
        adapter = source_root / "platforms" / profile / "dispatch.md"
        if adapter.is_symlink() or not adapter.is_file():
            raise InstallerError(f"missing dispatch adapter: {adapter}")
        if profile == "cursor":
            agent = source_root / "platforms" / "cursor" / "agent.md"
            if agent.is_symlink() or not agent.is_file():
                raise InstallerError(f"missing Cursor subagent: {agent}")
    return SKILL_NAMES


def _augment_frontmatter(text: str, target: str) -> str:
    lines = text.splitlines()
    if not lines or lines[0] != "---":
        raise InstallerError("SKILL.md is missing YAML frontmatter")
    try:
        end = lines.index("---", 1)
    except ValueError as error:
        raise InstallerError("SKILL.md has unterminated YAML frontmatter") from error
    header = lines[1:end]

    if target in EXPLICIT_ONLY_TARGETS:
        key = "disable-model-invocation:"
        replacement = "disable-model-invocation: true"
        for index, line in enumerate(header):
            if line.startswith(key):
                header[index] = replacement
                break
        else:
            header.append(replacement)
    if target in {"opencode", SHARED_AGENT_PROFILE}:
        try:
            metadata = header.index("metadata:")
        except ValueError:
            header.extend(
                [
                    "metadata:",
                    '  opencode/autoinvoke: "false"',
                    '  opencode/slash: "true"',
                ]
            )
        else:
            section_end = metadata + 1
            while section_end < len(header) and (
                not header[section_end] or header[section_end][0].isspace()
            ):
                section_end += 1
            values = {
                "opencode/autoinvoke:": '  opencode/autoinvoke: "false"',
                "opencode/slash:": '  opencode/slash: "true"',
            }
            for key, replacement in values.items():
                for index in range(metadata + 1, section_end):
                    if header[index].strip().startswith(key):
                        header[index] = replacement
                        break
                else:
                    header.insert(section_end, replacement)
                    section_end += 1

    transformed = ["---", *header, "---", *lines[end + 1 :]]
    return "\n".join(transformed) + ("\n" if text.endswith(("\n", "\r")) else "")


def stage_target(source_root: Path, target: str, staged_root: Path) -> None:
    skills_root = source_root / "skills"
    for name in SKILL_NAMES:
        shutil.copytree(skills_root / name, staged_root / name)

    manifest = source_root / "package.json"
    if manifest.is_file():
        try:
            version = json.loads(manifest.read_text(encoding="utf-8")).get("version")
        except (json.JSONDecodeError, AttributeError):
            version = None
        if version:
            (staged_root / "gsd-path" / "VERSION").write_text(
                f"{version}\n", encoding="utf-8"
            )

    adapter = (source_root / "platforms" / target / "dispatch.md").read_text(
        encoding="utf-8"
    )
    for dispatch in sorted(staged_root.glob("*/references/dispatch.md")):
        dispatch.write_text(adapter, encoding="utf-8")
    if target == "cursor":
        shutil.copy2(
            source_root / "platforms" / "cursor" / "agent.md",
            staged_root / CURSOR_AGENT_FILENAME,
        )

    if target != "codex":
        if target != SHARED_AGENT_PROFILE:
            for name in SKILL_NAMES:
                metadata = staged_root / name / "agents"
                if metadata.is_dir():
                    shutil.rmtree(metadata)
        invocation = (
            "gsd-path"
            if target in {"opencode", SHARED_AGENT_PROFILE}
            else "/gsd-path"
        )
        for name in SKILL_NAMES:
            entrypoint = staged_root / name / "SKILL.md"
            entrypoint.write_text(
                _augment_frontmatter(entrypoint.read_text(encoding="utf-8"), target),
                encoding="utf-8",
            )
        for markdown in sorted(staged_root.rglob("*.md")):
            content = markdown.read_text(encoding="utf-8")
            markdown.write_text(
                content.replace("$gsd-path", invocation), encoding="utf-8"
            )


def _missing_directories(path: Path) -> List[Path]:
    missing = []
    cursor = path
    while not _lexists(cursor):
        missing.append(cursor)
        cursor = cursor.parent
    return list(reversed(missing))


def _create_directory(path: Path, created: List[Path]) -> None:
    missing = _missing_directories(path)
    created.extend(missing)
    path.mkdir(parents=True, exist_ok=True)


def _release_install_locks(locks: Sequence[Path], created: Sequence[Path]) -> None:
    for lock in reversed(locks):
        lock.rmdir()
    _remove_empty_directories(created)


def _acquire_install_locks(roots: Iterable[Path]) -> Tuple[List[Path], List[Path]]:
    locks: List[Path] = []
    for root in roots:
        candidate = root.parent / INSTALL_LOCK_NAME
        if not any(_same_path(candidate, existing) for existing in locks):
            locks.append(candidate)
    locks.sort(key=lambda candidate: os.path.normcase(os.fspath(candidate)))
    acquired: List[Path] = []
    created: List[Path] = []
    try:
        for lock in locks:
            _create_directory(lock.parent, created)
            try:
                lock.mkdir()
            except FileExistsError as error:
                raise InstallerError(
                    f"installation already in progress for {lock.parent}"
                ) from error
            acquired.append(lock)
    except BaseException:
        _release_install_locks(acquired, created)
        raise
    return acquired, created


def _backup_path(root: Path, reserved: Sequence[Path] = ()) -> Path:
    candidate = root.parent / "disabled-gsd-skills"
    number = 1
    while _lexists(candidate) or any(
        _same_path(candidate, path) for path in reserved
    ):
        candidate = root.parent / f"disabled-gsd-skills-{number}"
        number += 1
    return candidate


def _backup_existing(
    transaction: TargetTransaction,
    extras: Sequence[Tuple[Path, str]] = (),
) -> None:
    existing = sorted(
        (
            (entry, entry.name)
            for entry in transaction.root.iterdir()
            if _is_managed_name(entry.name)
        ),
        key=lambda item: item[0].name,
    )
    existing.extend((path, backup_name) for path, backup_name in extras if _lexists(path))
    if existing:
        transaction.backup = _backup_path(transaction.root)
        transaction.backup.mkdir()
        for entry, backup_name in existing:
            stored = transaction.backup / backup_name
            transaction.moved.append((entry, stored))
            os.replace(entry, stored)


def _reserve_directory(path: Path) -> None:
    path.mkdir()


def _reserve_file(path: Path) -> None:
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        os.close(descriptor)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _apply_target(
    plan: DeploymentPlan, staged_root: Path, transaction: TargetTransaction
) -> None:
    _create_directory(plan.root, transaction.created_directories)
    extras = []
    cursor_agent = None
    if plan.profile == "cursor":
        cursor_agent = plan.root.parent / "agents" / CURSOR_AGENT_FILENAME
        _create_directory(cursor_agent.parent, transaction.created_directories)
        extras.append((cursor_agent, CURSOR_AGENT_BACKUP_NAME))
    _backup_existing(transaction, extras)
    for name in SKILL_NAMES:
        destination = plan.root / name
        _reserve_directory(destination)
        transaction.installed.append(destination)
        shutil.copytree(staged_root / name, destination, dirs_exist_ok=True)
    if cursor_agent is not None:
        _reserve_file(cursor_agent)
        transaction.installed.append(cursor_agent)
        shutil.copy2(staged_root / CURSOR_AGENT_FILENAME, cursor_agent)


def _remove_path(path: Path) -> None:
    if not _lexists(path):
        return
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def _remove_empty_directories(paths: Iterable[Path]) -> None:
    for path in reversed(list(paths)):
        try:
            path.rmdir()
        except OSError:
            pass


def _rollback_target(transaction: TargetTransaction) -> None:
    for destination in reversed(transaction.installed):
        _remove_path(destination)
    for original, stored in reversed(transaction.moved):
        if _lexists(stored):
            os.replace(stored, original)
    if transaction.backup is not None:
        try:
            transaction.backup.rmdir()
        except OSError:
            pass
    _remove_empty_directories(transaction.created_directories)


def _project_destinations(
    project: Path,
    selected: Sequence[str],
    hooks: bool,
    interpreter: str,
    hooks_dir: Optional[Path],
) -> List[Tuple[Path, Optional[str], Optional[str], bool]]:
    """(destination, source name, literal content, executable) per file.

    hooks_dir is the pre-resolved git hooks directory (or None); resolving
    it once per run avoids repeated `git rev-parse` spawns.
    """
    destinations: List[Tuple[Path, Optional[str], Optional[str], bool]] = [
        (project / "AGENTS.md", "AGENTS.md", None, False),
        (project / "WORKFLOW.md", "WORKFLOW.md", None, False),
    ]
    if "claude" in selected:
        destinations.append(
            (project / ".claude" / "CLAUDE.md", None, CLAUDE_BRIDGE, False)
        )
    if hooks:
        for name in GUARD_SCRIPTS:
            destinations.append(
                (project / HOOKS_DIRECTORY / name, f"scripts/{name}", None, False)
            )
        if "claude" in selected:
            destinations.append(
                (
                    project / ".claude" / "settings.json",
                    None,
                    claude_hooks_settings(interpreter),
                    False,
                )
            )
        if "codex" in selected:
            destinations.append(
                (
                    project / ".codex" / "hooks.json",
                    None,
                    codex_hooks_settings(interpreter),
                    False,
                )
            )
        if "cursor" in selected:
            destinations.append(
                (
                    project / ".cursor" / "hooks.json",
                    None,
                    cursor_hooks_settings(interpreter),
                    False,
                )
            )
        if hooks_dir is not None:
            destinations.append(
                (hooks_dir / "pre-commit", None, pre_commit_hook(interpreter), True)
            )
            destinations.append(
                (hooks_dir / "commit-msg", None, commit_msg_hook(interpreter), True)
            )
    return destinations


def _describe_project_path(project: Path, destination: Path) -> str:
    try:
        return destination.relative_to(project).as_posix()
    except ValueError:
        return destination.as_posix()


def _project_files(
    project: Path,
    selected: Sequence[str],
    hooks: bool,
    interpreter: str,
    hooks_dir: Optional[Path],
) -> str:
    return ", ".join(
        _describe_project_path(project, destination)
        for destination, _, _, _ in _project_destinations(
            project, selected, hooks, interpreter, hooks_dir
        )
    )


def _existing_contract_error(destination: Path) -> "InstallerError":
    return InstallerError(
        f"project contract already exists: {destination} — the installer never "
        "overwrites project files; merge template changes manually "
        "(see UPDATE.md)."
    )


def _validate_project(
    source_root: Path,
    project: Path,
    selected: Sequence[str],
    hooks: bool,
    reserved_roots: Sequence[Tuple[str, Path]],
    interpreter: str,
    hooks_dir: Optional[Path],
) -> None:
    _validate_directory_destination(project, "project path")
    sources = ["AGENTS.md", "WORKFLOW.md"]
    if hooks:
        sources.extend(f"scripts/{name}" for name in GUARD_SCRIPTS)
    for source_name in sources:
        source = source_root / source_name
        if source.is_symlink() or not source.is_file():
            raise InstallerError(f"missing project contract: {source}")
    for destination, _, _, _ in _project_destinations(
        project, selected, hooks, interpreter, hooks_dir
    ):
        if _lexists(destination):
            raise _existing_contract_error(destination)
        for label, root in reserved_roots:
            if _paths_overlap(destination, root):
                raise InstallerError(
                    f"project contract overlaps {label}: {destination}, {root}"
                )
    project_directories = []
    if "claude" in selected:
        project_directories.append(("Claude", project / ".claude"))
    if hooks and "codex" in selected:
        project_directories.append(("Codex", project / ".codex"))
    if hooks and "cursor" in selected:
        project_directories.append(("Cursor", project / ".cursor"))
    for label, directory in project_directories:
        if _lexists(directory) and (
            directory.is_symlink() or not directory.is_dir()
        ):
            raise InstallerError(f"unsafe {label} project directory: {directory}")


def _apply_project(
    source_root: Path,
    project: Path,
    selected: Sequence[str],
    hooks: bool,
    transaction: ProjectTransaction,
    interpreter: str,
    hooks_dir: Optional[Path],
) -> None:
    _create_directory(project, transaction.created_directories)
    for destination, source_name, content, executable in _project_destinations(
        project, selected, hooks, interpreter, hooks_dir
    ):
        _create_directory(destination.parent, transaction.created_directories)
        created = False
        try:
            if source_name:
                with (source_root / source_name).open("rb") as source:
                    with destination.open("xb") as output:
                        created = True
                        shutil.copyfileobj(source, output)
            else:
                with destination.open("x", encoding="utf-8") as output:
                    created = True
                    output.write(content)
            if executable:
                destination.chmod(0o755)
            transaction.copied.append(destination)
        except FileExistsError as error:
            raise _existing_contract_error(destination) from error
        except (Exception, KeyboardInterrupt):
            if created:
                _remove_path(destination)
            raise


def _rollback_project(transaction: ProjectTransaction) -> None:
    for destination in reversed(transaction.copied):
        _remove_path(destination)
    _remove_empty_directories(transaction.created_directories)


def _is_managed_guard_script(destination: Path) -> bool:
    if not destination.is_file():
        return False
    return GUARD_MARKER in destination.read_text(encoding="utf-8", errors="replace")


def _is_managed_git_hook(destination: Path) -> bool:
    if not destination.is_file():
        return False
    text = destination.read_text(encoding="utf-8", errors="replace")
    return GUARD_MARKER in text and "git_guard.py" in text


def _is_managed_hook_settings(destination: Path) -> bool:
    if not destination.is_file():
        return False
    try:
        parsed = _parsed_managed_settings(destination)
    except InstallerError:
        return False
    return _has_managed_hook_settings(parsed)


def _atomic_temporary(destination: Path) -> Tuple[int, Path]:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.gsd-path-tmp-", dir=destination.parent
    )
    return descriptor, Path(name)


def _atomic_write(
    destination: Path, content: str, mode: Optional[int] = None
) -> None:
    descriptor, temporary = _atomic_temporary(destination)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(content)
        if mode is not None:
            temporary.chmod(mode)
        elif destination.is_file() and not destination.is_symlink():
            temporary.chmod(destination.stat().st_mode & 0o777)
        os.replace(temporary, destination)
    except BaseException:
        _remove_path(temporary)
        raise


def _atomic_copy(source: Path, destination: Path) -> None:
    descriptor, temporary = _atomic_temporary(destination)
    try:
        with source.open("rb") as input_file:
            with os.fdopen(descriptor, "wb") as output:
                shutil.copyfileobj(input_file, output)
        os.replace(temporary, destination)
    except BaseException:
        _remove_path(temporary)
        raise


def _is_managed_hook_entry(entry) -> bool:
    """A PreToolUse entry is ours when one of its commands runs the guard."""
    if not isinstance(entry, dict):
        return False
    hooks_list = entry.get("hooks")
    if not isinstance(hooks_list, list):
        return False
    return any(
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and _is_guard_command(hook["command"])
        for hook in hooks_list
    )


def _is_guard_command(command: str) -> bool:
    return f"{HOOKS_DIRECTORY}/guard_hook.py" in command.replace("\\", "/")


def _is_managed_direct_hook_entry(entry) -> bool:
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("command"), str)
        and _is_guard_command(entry["command"])
    )


def _has_managed_hook_settings(parsed: dict) -> bool:
    hooks = parsed.get("hooks")
    if not isinstance(hooks, dict):
        return False
    nested = hooks.get("PreToolUse")
    direct = hooks.get("preToolUse")
    return (
        isinstance(nested, list)
        and any(_is_managed_hook_entry(entry) for entry in nested)
    ) or (
        isinstance(direct, list)
        and any(_is_managed_direct_hook_entry(entry) for entry in direct)
    )


def _parsed_managed_settings(settings: Path) -> dict:
    try:
        parsed = json.loads(settings.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as error:
        raise InstallerError(
            f"managed hook settings file is not valid JSON: {settings}"
        ) from error
    if not isinstance(parsed, dict):
        raise InstallerError(
            f"managed hook settings file is not a JSON object: {settings}"
        )
    return parsed


def _merged_hook_settings(
    settings: Path, event_name: str, managed_entry: dict, is_managed_entry
) -> str:
    parsed = _parsed_managed_settings(settings)
    hooks_object = parsed.get("hooks")
    if not isinstance(hooks_object, dict):
        hooks_object = {}
    existing = hooks_object.get(event_name)
    if not isinstance(existing, list):
        existing = []
    merged = []
    replaced = False
    for entry in existing:
        if is_managed_entry(entry):
            if not replaced:
                merged.append(managed_entry)
                replaced = True
        else:
            merged.append(entry)
    if not replaced:
        merged.append(managed_entry)
    hooks_object[event_name] = merged
    parsed["hooks"] = hooks_object
    return json.dumps(parsed, indent=2) + "\n"


def _merged_claude_settings(settings: Path, interpreter: str) -> str:
    return _merged_hook_settings(
        settings, "PreToolUse", _claude_guard_entry(interpreter), _is_managed_hook_entry
    )


def _merged_codex_settings(settings: Path, interpreter: str) -> str:
    managed = codex_hooks_settings(interpreter)
    managed_entry = json.loads(managed)["hooks"]["PreToolUse"][0]
    return _merged_hook_settings(
        settings, "PreToolUse", managed_entry, _is_managed_hook_entry
    )


def _merged_cursor_settings(settings: Path, interpreter: str) -> str:
    managed = cursor_hooks_settings(interpreter)
    managed_entry = json.loads(managed)["hooks"]["preToolUse"][0]
    return _merged_hook_settings(
        settings, "preToolUse", managed_entry, _is_managed_direct_hook_entry
    )


def _validate_hooks_refresh(
    source_root: Path,
    project: Path,
    full: bool,
    hooks_dir: Optional[Path],
    selected: Sequence[str],
) -> None:
    _validate_directory_destination(project, "project path")
    for name in GUARD_SCRIPTS:
        destination = project / HOOKS_DIRECTORY / name
        if destination.is_symlink():
            raise InstallerError(f"refusing to refresh a symlink: {destination}")
        if not _is_managed_guard_script(destination):
            raise InstallerError(f"not a managed GSD Path guard script: {destination}")
        source = source_root / "scripts" / name
        if source.is_symlink() or not source.is_file():
            raise InstallerError(f"missing guard script source: {source}")
    if full:
        for target, label, settings in (
            ("claude", "Claude", project / ".claude" / "settings.json"),
            ("codex", "Codex", project / ".codex" / "hooks.json"),
            ("cursor", "Cursor", project / ".cursor" / "hooks.json"),
        ):
            exists = _lexists(settings)
            if not exists and target not in selected:
                continue
            _validate_directory_destination(
                settings.parent, f"unsafe {label} project directory"
            )
            if settings.is_symlink():
                raise InstallerError(f"refusing to refresh a symlink: {settings}")
            if exists:
                parsed = _parsed_managed_settings(settings)
                if target not in selected and not _has_managed_hook_settings(parsed):
                    raise InstallerError(
                        f"not a managed GSD Path hook settings file: {settings}"
                    )
        if hooks_dir is not None:
            for hook_name in ("pre-commit", "commit-msg"):
                hook_path = hooks_dir / hook_name
                if hook_path.is_symlink():
                    raise InstallerError(
                        f"refusing to refresh a symlink: {hook_path}"
                    )
                if _lexists(hook_path) and not _is_managed_git_hook(hook_path):
                    raise InstallerError(
                        f"not a managed GSD Path git hook: {hook_path}"
                    )


def refresh_hooks(
    source_root: Path,
    project: Path,
    full: bool,
    dry_run: bool = False,
    selected: Sequence[str] = (),
) -> List[str]:
    """Refreshed project-relative paths; "note:"-prefixed entries are
    user-facing notes rather than refreshed files."""
    hooks_dir = _git_hooks_directory(project) if full else None
    _validate_hooks_refresh(source_root, project, full, hooks_dir, selected)
    refreshed: List[str] = []
    for name in GUARD_SCRIPTS:
        destination = project / HOOKS_DIRECTORY / name
        source = source_root / "scripts" / name
        if not dry_run:
            _atomic_copy(source, destination)
        refreshed.append(_describe_project_path(project, destination))
    if full:
        # Dry-run only lists paths, so it never needs the interpreter probe.
        interpreter = None if dry_run else _effective_interpreter()
        if not dry_run and interpreter is None:
            refreshed.append(
                "note: hooks: no working python3 or python interpreter found "
                "on PATH; skipped native settings and git hook refresh"
            )
            return refreshed
        for target, settings, merge, generated in (
            (
                "claude",
                project / ".claude" / "settings.json",
                _merged_claude_settings,
                claude_hooks_settings,
            ),
            (
                "codex",
                project / ".codex" / "hooks.json",
                _merged_codex_settings,
                codex_hooks_settings,
            ),
            (
                "cursor",
                project / ".cursor" / "hooks.json",
                _merged_cursor_settings,
                cursor_hooks_settings,
            ),
        ):
            exists = _lexists(settings)
            if exists or target in selected:
                if not dry_run:
                    settings.parent.mkdir(parents=True, exist_ok=True)
                    content = (
                        merge(settings, interpreter)
                        if exists
                        else generated(interpreter)
                    )
                    _atomic_write(settings, content)
                refreshed.append(_describe_project_path(project, settings))
        if hooks_dir is not None:
            for hook_name in ("pre-commit", "commit-msg"):
                hook_path = hooks_dir / hook_name
                if not dry_run:
                    content = (
                        pre_commit_hook(interpreter)
                        if hook_name == "pre-commit"
                        else commit_msg_hook(interpreter)
                    )
                    hook_path.parent.mkdir(parents=True, exist_ok=True)
                    _atomic_write(hook_path, content, mode=0o755)
                refreshed.append(_describe_project_path(project, hook_path))
    return refreshed


def _comparison_path(path: Path) -> Path:
    value = os.path.normcase(os.fspath(path.resolve(strict=False)))
    if sys.platform == "darwin":
        value = value.casefold()
    return Path(value)


def _paths_overlap(left: Path, right: Path) -> bool:
    left = _comparison_path(left)
    right = _comparison_path(right)
    return left == right or left in right.parents or right in left.parents


def _same_path(left: Path, right: Path) -> bool:
    return _comparison_path(left) == _comparison_path(right)


def _deployment_plans(plans: Sequence[TargetPlan]) -> List[DeploymentPlan]:
    if len({plan.name for plan in plans}) != len(plans):
        raise InstallerError("each target may be selected only once")
    unsupported = sorted({plan.name for plan in plans} - set(TARGETS))
    if unsupported:
        raise InstallerError("unsupported target: " + ", ".join(unsupported))

    groups: List[List[TargetPlan]] = []
    for plan in plans:
        for group in groups:
            if _same_path(group[0].root, plan.root):
                group.append(plan)
                break
        else:
            groups.append([plan])

    deployments = []
    for group in groups:
        targets = tuple(plan.name for plan in group)
        target_set = set(targets)
        if len(group) > 1:
            if not target_set <= SHARED_AGENT_TARGETS:
                labels = ", ".join(targets)
                raise InstallerError(
                    "only Codex, Antigravity, and Zed may share a skills root: "
                    f"{labels}"
                )
            profile = SHARED_AGENT_PROFILE
        elif group[0].name in SHARED_AGENT_TARGETS:
            profile = SHARED_AGENT_PROFILE
        elif _same_path(group[0].root, default_root("codex")):
            raise InstallerError(
                f"{group[0].name} cannot install a host-specific bundle to the "
                "shared ~/.agents/skills root"
            )
        else:
            profile = group[0].name
        deployments.append(DeploymentPlan(profile, group[0].root, targets))
    return deployments


def _validate_distinct_roots(plans: Sequence[DeploymentPlan]) -> None:
    for index, left in enumerate(plans):
        for right in plans[index + 1 :]:
            if _paths_overlap(left.root, right.root):
                raise InstallerError(
                    "target roots overlap: "
                    f"{'+'.join(left.targets)}={left.root}, "
                    f"{'+'.join(right.targets)}={right.root}"
                )

    cursor_plans = [plan for plan in plans if plan.profile == "cursor"]
    for cursor_plan in cursor_plans:
        agent_root = cursor_plan.root.parent / "agents"
        if _paths_overlap(agent_root, cursor_plan.root):
            raise InstallerError(
                "Cursor skills and agent roots overlap: "
                f"skills={cursor_plan.root}, agents={agent_root}"
            )
        for plan in plans:
            if plan is cursor_plan:
                continue
            if _paths_overlap(agent_root, plan.root):
                raise InstallerError(
                    "Cursor agent root overlaps a target root: "
                    f"cursor={agent_root}, {'+'.join(plan.targets)}={plan.root}"
                )


def _append_host_notes(results: List[str], selected: Sequence[str]) -> None:
    for target in TARGETS:
        if target in selected and target in HOST_NOTES:
            results.append(HOST_NOTES[target])


def _install_result(
    plan: DeploymentPlan, dry_run: bool = False, update: bool = False
) -> str:
    verb = "update" if update else "install"
    action = f"would {verb}" if dry_run else ("updated" if update else "installed")
    label = "+".join(plan.targets)
    skill_count = len(SKILL_NAMES)
    if plan.profile == "cursor":
        agent = plan.root.parent / "agents" / CURSOR_AGENT_FILENAME
        return (
            f"{label}: {action} {skill_count} skills to {plan.root} "
            f"and custom subagent to {agent}"
        )
    shared = " shared" if plan.profile == SHARED_AGENT_PROFILE else ""
    return f"{label}: {action} {skill_count}{shared} skills to {plan.root}"


def _managed_entry_count(plan: DeploymentPlan) -> int:
    count = 0
    if plan.root.is_dir():
        count = sum(
            1 for entry in plan.root.iterdir() if _is_managed_name(entry.name)
        )
    if plan.profile == "cursor" and _lexists(
        plan.root.parent / "agents" / CURSOR_AGENT_FILENAME
    ):
        count += 1
    return count


def _has_managed_install(root: Path) -> bool:
    return root.is_dir() and any(_is_managed_name(entry.name) for entry in root.iterdir())


def detect_installs(
    targets: Sequence[str], roots: Mapping[str, Path]
) -> List[TargetPlan]:
    return [
        TargetPlan(target, roots[target])
        for target in targets
        if _has_managed_install(roots[target])
    ]


def _planned_backup_roots(
    legacy_root: Optional[Path], deployments: Sequence[DeploymentPlan]
) -> List[Tuple[str, Path]]:
    transactions = []
    if legacy_root is not None and legacy_root.is_dir() and any(
        _is_managed_name(entry.name) for entry in legacy_root.iterdir()
    ):
        transactions.append(("Codex legacy backup", legacy_root))
    transactions.extend(
        (f"{'+'.join(plan.targets)} backup", plan.root)
        for plan in deployments
        if _managed_entry_count(plan)
    )

    planned = []
    reserved = []
    for label, root in transactions:
        backup = _backup_path(root, reserved)
        reserved.append(backup)
        planned.append((label, backup))
    return planned


def install(
    source_root: Path,
    plans: Sequence[TargetPlan],
    project: Optional[Path] = None,
    dry_run: bool = False,
    hooks: bool = False,
    migrate_legacy: bool = True,
    update: bool = False,
) -> List[str]:
    if hooks and project is None:
        raise InstallerError("--hooks requires --project")
    # Resolve per-run environment facts (interpreter, git hooks directory)
    # once here and thread them down.
    effective_hooks = hooks
    interpreter = "python3"
    hooks_dir: Optional[Path] = None
    hook_notes: List[str] = []
    if hooks:
        probed = _effective_interpreter()
        if probed is None:
            effective_hooks = False
            hook_notes.append(
                "note: hooks: no working python3 or python interpreter found "
                "on PATH; skipped guard hook install"
            )
        else:
            interpreter = probed
    if effective_hooks:
        hooks_dir = _git_hooks_directory(project)
        if hooks_dir is None and _lexists(project / ".git"):
            hook_notes.append(
                "note: hooks: found .git but could not resolve the git hooks "
                "directory (is git runnable?); git hooks were not installed"
            )
    selected = [plan.name for plan in plans]
    deployments = _deployment_plans(plans)
    adapters = list(dict.fromkeys(deployment.profile for deployment in deployments))
    validate_source(source_root, adapters)
    _validate_distinct_roots(deployments)
    for plan in plans:
        _validate_directory_destination(plan.root, f"{plan.name} skills root")
        if _paths_overlap(plan.root, source_root):
            raise InstallerError(
                f"{plan.name} skills root overlaps source repository: {plan.root}"
            )
    for deployment in deployments:
        if deployment.profile != "cursor":
            continue
        cursor_agent_root = deployment.root.parent / "agents"
        _validate_directory_destination(cursor_agent_root, "Cursor agent root")
        if _paths_overlap(cursor_agent_root, source_root):
            raise InstallerError(
                f"Cursor agent root overlaps source repository: {cursor_agent_root}"
            )
    legacy_root = (
        legacy_codex_root() if migrate_legacy and "codex" in selected else None
    )
    reserved_roots = [
        (f"{'+'.join(plan.targets)} skills root", plan.root) for plan in deployments
    ]
    reserved_roots.extend(
        ("Cursor agent root", plan.root.parent / "agents")
        for plan in deployments
        if plan.profile == "cursor"
    )
    if legacy_root is not None:
        codex_roots = [
            plan.root for plan in deployments if "codex" in plan.targets
        ]
        if any(_same_path(legacy_root, root) for root in codex_roots):
            legacy_root = None
        elif _paths_overlap(legacy_root, source_root):
            raise InstallerError(
                f"Codex legacy root overlaps source repository: {legacy_root}"
            )
        else:
            for label, root in reserved_roots:
                if _paths_overlap(legacy_root, root):
                    raise InstallerError(
                        f"Codex legacy root overlaps {label}: {legacy_root}, {root}"
                    )
    if legacy_root is not None:
        _validate_directory_destination(legacy_root, "Codex legacy skills root")

    planned_backups = _planned_backup_roots(legacy_root, deployments)
    mutation_roots = list(reserved_roots)
    if legacy_root is not None:
        mutation_roots.append(("Codex legacy skills root", legacy_root))
    for backup_label, backup in planned_backups:
        for root_label, root in mutation_roots:
            if _paths_overlap(backup, root):
                raise InstallerError(
                    f"{backup_label} overlaps {root_label}: {backup}, {root}"
                )

    if project is not None:
        _validate_project(
            source_root,
            project,
            selected,
            effective_hooks,
            [*mutation_roots, *planned_backups],
            interpreter,
            hooks_dir,
        )

    results = []
    with tempfile.TemporaryDirectory(prefix="gsd-path-install-") as temporary:
        staging = Path(temporary)
        staged = []
        for index, plan in enumerate(deployments):
            staged_root = staging / f"{index}-{plan.profile}"
            staged.append(staged_root)
            staged_root.mkdir()
            stage_target(source_root, plan.profile, staged_root)

        if dry_run:
            if legacy_root is not None and legacy_root.is_dir():
                legacy_count = sum(
                    1 for entry in legacy_root.iterdir() if _is_managed_name(entry.name)
                )
                if legacy_count:
                    results.append(
                        f"codex-legacy: would back up {legacy_count} entries from {legacy_root}"
                    )
            for plan in deployments:
                count = _managed_entry_count(plan)
                suffix = f"; would back up {count} entries" if count else ""
                results.append(
                    _install_result(plan, dry_run=True, update=update) + suffix
                )
            if project is not None:
                files = _project_files(
                    project, selected, effective_hooks, interpreter, hooks_dir
                )
                results.append(f"project: would copy {files} to {project}")
            results.extend(hook_notes)
            _append_host_notes(results, selected)
            return results

        lock_roots = [plan.root for plan in deployments]
        if legacy_root is not None and legacy_root.is_dir():
            lock_roots.append(legacy_root)
        install_locks, lock_directories = _acquire_install_locks(lock_roots)
        target_transactions: List[TargetTransaction] = []
        project_transaction = ProjectTransaction()
        try:
            if legacy_root is not None and legacy_root.is_dir():
                legacy_transaction = TargetTransaction(legacy_root)
                target_transactions.append(legacy_transaction)
                _backup_existing(legacy_transaction)
                if legacy_transaction.backup is not None:
                    results.append(
                        "codex-legacy: backed up "
                        f"{len(legacy_transaction.moved)} entries to "
                        f"{legacy_transaction.backup}"
                    )
            for index, plan in enumerate(deployments):
                transaction = TargetTransaction(plan.root)
                target_transactions.append(transaction)
                _apply_target(plan, staged[index], transaction)
                results.append(_install_result(plan, update=update))
                if transaction.backup is not None:
                    results.append(
                        f"{'+'.join(plan.targets)}: backed up "
                        f"{len(transaction.moved)} entries "
                        f"to {transaction.backup}"
                    )
            if project is not None:
                _apply_project(
                    source_root,
                    project,
                    selected,
                    effective_hooks,
                    project_transaction,
                    interpreter,
                    hooks_dir,
                )
                files = _project_files(
                    project, selected, effective_hooks, interpreter, hooks_dir
                )
                results.append(f"project: copied {files} to {project}")
            results.extend(hook_notes)
        except (Exception, KeyboardInterrupt) as error:
            rollback_errors = []
            try:
                _rollback_project(project_transaction)
            except (Exception, KeyboardInterrupt) as rollback_error:
                rollback_errors.append(str(rollback_error))
            for transaction in reversed(target_transactions):
                try:
                    _rollback_target(transaction)
                except (Exception, KeyboardInterrupt) as rollback_error:
                    rollback_errors.append(str(rollback_error))
            detail = ""
            if rollback_errors:
                detail = f"; rollback incomplete: {'; '.join(rollback_errors)}"
            reason = "interrupted" if isinstance(error, KeyboardInterrupt) else str(error)
            raise InstallerError(
                f"installation failed and was rolled back: {reason}{detail}"
            ) from error
        finally:
            _release_install_locks(install_locks, lock_directories)
    _append_host_notes(results, selected)
    return results


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(description=__doc__)
    for target in TARGETS:
        argument_parser.add_argument(f"--{target}", action="store_true")
        argument_parser.add_argument(f"--{target}-root", type=Path)
    argument_parser.add_argument("--all", action="store_true", dest="all_targets")
    argument_parser.add_argument("--update", action="store_true")
    argument_parser.add_argument("--local", action="store_true")
    argument_parser.add_argument("--dry-run", action="store_true")
    argument_parser.add_argument("--project", type=Path)
    argument_parser.add_argument("--hooks", action="store_true")
    argument_parser.add_argument("--hooks-refresh", action="store_true")
    argument_parser.add_argument("--hooks-refresh-full", action="store_true")
    argument_parser.add_argument(
        "--source-root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    return argument_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    argument_parser = parser()
    arguments = argument_parser.parse_args(argv)
    source_root = absolute_path(arguments.source_root)
    project = (
        absolute_path(arguments.project) if arguments.project is not None else None
    )
    if arguments.hooks_refresh or arguments.hooks_refresh_full:
        if project is None:
            print("error: --hooks-refresh requires --project", file=sys.stderr)
            return 2
        try:
            selected = [
                target
                for target in TARGETS
                if arguments.all_targets or getattr(arguments, target)
            ]
            refreshed = refresh_hooks(
                source_root,
                project,
                arguments.hooks_refresh_full,
                arguments.dry_run,
                selected,
            )
            notes = [line for line in refreshed if line.startswith("note:")]
            files = [line for line in refreshed if not line.startswith("note:")]
            prefix = "would refresh" if arguments.dry_run else "refreshed"
            print(f"hooks: {prefix} {', '.join(files)}")
            for note in notes:
                print(note)
        except InstallerError as error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        return 0
    selected = [
        target
        for target in TARGETS
        if arguments.all_targets or getattr(arguments, target)
    ]
    if not selected:
        if arguments.update:
            selected = list(TARGETS)
        else:
            argument_parser.error("select at least one target or --all")

    roots = {}
    for target in selected:
        override = getattr(arguments, f"{target}_root")
        roots[target] = (
            absolute_path(override)
            if override is not None
            else (
                local_root(target, Path.cwd())
                if arguments.local
                else default_root(target)
            )
        )
    plans = (
        detect_installs(selected, roots)
        if arguments.update
        else [TargetPlan(target, roots[target]) for target in selected]
    )
    if arguments.update and not plans:
        scope = "this project" if arguments.local else "global roots"
        print(
            "error: no existing GSD Path skills found to update "
            f"({scope}); run an install first, e.g. --all"
            + (" --local" if arguments.local else ""),
            file=sys.stderr,
        )
        return 1
    try:
        for result in install(
            source_root,
            plans,
            project,
            arguments.dry_run,
            arguments.hooks,
            migrate_legacy=not arguments.local,
            update=arguments.update,
        ):
            print(result)
    except InstallerError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
