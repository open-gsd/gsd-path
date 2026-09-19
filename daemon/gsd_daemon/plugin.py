"""Daemon-managed gsd-path plugin lifecycle.

Installs, updates, and uninstalls the gsd-path skill plugin — globally into
per-host skill roots and per-project — by driving the plugin's own
``scripts/install.py`` from a daemon-owned git clone at ``~/.gsd-path/src``.
Every external command goes through an injectable runner; every filesystem
removal goes through injectable hooks, so tests can observe without deleting.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .config import resolve_config_path

DEFAULT_REPO = "https://github.com/open-gsd/gsd-path.git"
ENV_HOME = "GSD_DAEMON_HOME"

HOSTS = (
    "codex", "claude", "grok", "opencode", "copilot", "qwen",
    "antigravity", "cursor", "zed", "kiro", "kimi",
)

LOCAL_ROOTS = {
    "codex": ".agents/skills",
    "claude": ".claude/skills",
    "grok": ".grok/skills",
    "opencode": ".opencode/skills",
    "copilot": ".github/skills",
    "qwen": ".qwen/skills",
    "antigravity": ".agents/skills",
    "cursor": ".cursor/skills",
    "zed": ".agents/skills",
    "kiro": ".kiro/skills",
    "kimi": ".kimi-code/skills",
}

BACKUP_PREFIX = "disabled-gsd-skills"
HOOKS_DIRECTORY = ".gsd-path"
GUARD_SCRIPTS = ("guard_hook.py", "git_guard.py")
GUARD_MARKER = "gsd-path guard"
PROJECT_RUNTIME_MARKER = "gsd-path project runtime"
PROJECT_STATUS_MARKER = "gsd-path project status launcher"
PROJECT_STATUS_LAUNCHER = "status_runtime.py"
CLAUDE_BRIDGE = "@../AGENTS.md\n@../WORKFLOW.md\n"
GIT_HOOK_NAMES = ("pre-commit", "commit-msg", "pre-push")
SETTINGS_FILES = (".claude/settings.json", ".codex/hooks.json", ".cursor/hooks.json")
CONTRACT_FILES = ("AGENTS.md", "WORKFLOW.md")
NEVER_TOUCH_DIRECTORY = ".project"

CACHE_NAME = "update-check.json"
LOG_NAME = "plugin.log"
STDOUT_TAIL_LINES = 40

Runner = Callable[..., Tuple[int, str, str]]


def _default_runner(argv: Sequence[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
    try:
        proc = subprocess.run(
            [str(part) for part in argv],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return 127, "", str(error)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _tail(text: str, lines: int = STDOUT_TAIL_LINES) -> str:
    split = (text or "").rstrip("\n").splitlines()
    return "\n".join(split[-lines:])


def _parse_version(value: Optional[str]) -> Optional[Tuple[int, ...]]:
    if not value:
        return None
    try:
        return tuple(int(part) for part in value.strip().split("."))
    except (ValueError, AttributeError):
        return None


def _is_newer(latest: Optional[str], installed: Optional[str]) -> bool:
    latest_parts = _parse_version(latest)
    installed_parts = _parse_version(installed)
    return (
        latest_parts is not None
        and installed_parts is not None
        and latest_parts > installed_parts
    )


def _is_managed_name(name: str) -> bool:
    normalized = name.casefold()
    return normalized in ("gsd-path", "path") or normalized.startswith("gsd-path-")


def _is_backup_name(name: str) -> bool:
    return name.casefold().startswith(BACKUP_PREFIX)


def _is_guard_command(command: str) -> bool:
    """Mirror of install.py's guard-command recognition for settings entries."""
    normalized = command.replace("\\", "/")
    match = re.fullmatch(
        r"(?:python3|python)\s+(?:\"([^\"\r\n]+)\"|'([^'\r\n]+)'|(\S+))",
        normalized,
    )
    if match is None:
        return False
    script = next(value for value in match.groups() if value is not None)
    managed_script = f"{HOOKS_DIRECTORY}/guard_hook.py"
    return script == managed_script or script.endswith(f"/{managed_script}")


def _is_managed_command_hook(hook) -> bool:
    return (
        isinstance(hook, dict)
        and isinstance(hook.get("command"), str)
        and _is_guard_command(hook["command"])
    )


def _is_managed_hook_entry(entry) -> bool:
    if not isinstance(entry, dict):
        return False
    hooks_list = entry.get("hooks")
    if not isinstance(hooks_list, list):
        return False
    return any(_is_managed_command_hook(hook) for hook in hooks_list)


def _unmerged_settings(parsed: dict) -> Optional[dict]:
    """Settings object with gsd-path guard entries surgically removed.

    Returns None when the file contains no managed entries. Empty hook
    lists/objects are pruned; a result of {} means the file should be deleted.
    """
    hooks = parsed.get("hooks")
    if not isinstance(hooks, dict):
        return None
    changed = False
    new_hooks = {}
    for event, entries in hooks.items():
        if event == "PreToolUse" and isinstance(entries, list):
            kept = []
            for entry in entries:
                if _is_managed_hook_entry(entry):
                    changed = True
                    unrelated = [
                        hook for hook in entry["hooks"]
                        if not _is_managed_command_hook(hook)
                    ]
                    if unrelated:
                        kept.append({**entry, "hooks": unrelated})
                else:
                    kept.append(entry)
            if kept:
                new_hooks[event] = kept
            elif not changed:
                new_hooks[event] = kept
        elif event == "preToolUse" and isinstance(entries, list):
            kept = []
            for entry in entries:
                if _is_managed_command_hook(entry):
                    changed = True
                else:
                    kept.append(entry)
            if kept:
                new_hooks[event] = kept
        else:
            new_hooks[event] = entries
    if not changed:
        return None
    result = dict(parsed)
    if new_hooks:
        result["hooks"] = new_hooks
    else:
        result.pop("hooks", None)
    # A file reduced to nothing but the cursor "version" marker is empty.
    if set(result.keys()) <= {"version"}:
        return {}
    return result


class PluginManager:
    def __init__(
        self,
        home: Optional[Path] = None,
        user_home: Optional[Path] = None,
        runner: Optional[Runner] = None,
        git_runner: Optional[Runner] = None,
        environ: Optional[dict] = None,
        out: Callable[[str], None] = print,
        clock: Callable[[], float] = time.time,
        remove_dir: Optional[Callable[[str], None]] = None,
        remove_file: Optional[Callable[[str], None]] = None,
        write_file: Optional[Callable[[str, str], None]] = None,
        repo: Optional[str] = None,
    ) -> None:
        self.environ = environ if environ is not None else os.environ
        if home is not None:
            self.home = Path(home)
        elif self.environ.get(ENV_HOME):
            self.home = Path(self.environ[ENV_HOME]).expanduser()
        else:
            self.home = Path.home() / ".gsd-path"
        self.user_home = Path(user_home) if user_home is not None else Path.home()
        self.runner = runner or _default_runner
        self.git_runner = git_runner or self.runner
        self.out = out
        self.clock = clock
        self._remove_dir = remove_dir or (lambda path: shutil.rmtree(path))
        self._remove_file = remove_file or (lambda path: os.unlink(path))
        self._write_file = write_file or (
            lambda path, text: Path(path).write_text(text, encoding="utf-8")
        )
        self.repo = repo or self._config_repo() or DEFAULT_REPO

    # -- paths ---------------------------------------------------------------

    @property
    def src_dir(self) -> Path:
        return self.home / "src"

    @property
    def cache_path(self) -> Path:
        return self.home / CACHE_NAME

    @property
    def log_path(self) -> Path:
        return self.home / "logs" / LOG_NAME

    @property
    def install_py(self) -> Path:
        return self.src_dir / "scripts" / "install.py"

    def _config_repo(self) -> Optional[str]:
        try:
            data = json.loads(resolve_config_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = data.get("plugin_repo") if isinstance(data, dict) else None
        return value if isinstance(value, str) and value else None

    # -- host roots ------------------------------------------------------------

    def global_root(self, host: str) -> Path:
        env = self.environ
        home = self.user_home

        def env_home(name: str, default: str) -> Path:
            value = env.get(name)
            if value:
                candidate = Path(value).expanduser()
                return candidate if candidate.is_absolute() else home / candidate
            return home / default

        if host in ("codex", "zed"):
            return home / ".agents" / "skills"
        if host == "claude":
            return env_home("CLAUDE_CONFIG_DIR", ".claude") / "skills"
        if host == "grok":
            return env_home("GROK_HOME", ".grok") / "skills"
        if host == "opencode":
            if env.get("OPENCODE_CONFIG_DIR"):
                base = Path(env["OPENCODE_CONFIG_DIR"]).expanduser()
            elif env.get("OPENCODE_CONFIG"):
                base = Path(env["OPENCODE_CONFIG"]).expanduser().parent
            else:
                base = Path(env.get("XDG_CONFIG_HOME") or (home / ".config")).expanduser() / "opencode"
            return base / "skills"
        if host == "copilot":
            return env_home("COPILOT_HOME", ".copilot") / "skills"
        if host == "qwen":
            return env_home("QWEN_HOME", ".qwen") / "skills"
        if host == "antigravity":
            return home / ".gemini" / "antigravity-cli" / "skills"
        if host == "cursor":
            return home / ".cursor" / "skills"
        if host == "kiro":
            return env_home("KIRO_HOME", ".kiro") / "skills"
        if host == "kimi":
            return env_home("KIMI_CODE_HOME", ".kimi-code") / "skills"
        raise ValueError(f"unsupported host: {host}")

    def local_root(self, host: str, project: Path) -> Path:
        try:
            relative = LOCAL_ROOTS[host]
        except KeyError as error:
            raise ValueError(f"unsupported host: {host}") from error
        return project / relative

    # -- source clone ----------------------------------------------------------

    def _ssh_repo(self, url: str) -> Optional[str]:
        match = re.match(r"https://github\.com/(.+?)(?:\.git)?$", url)
        if not match:
            return None
        return f"git@github.com:{match.group(1)}.git"

    def ensure_source(self) -> Path:
        if (self.src_dir / ".git").exists():
            return self.src_dir
        rc, _stdout, stderr = self.git_runner(["git", "clone", self.repo, str(self.src_dir)])
        if rc == 0:
            return self.src_dir
        https_error = stderr.strip()
        ssh_repo = self._ssh_repo(self.repo)
        ssh_error = ""
        if ssh_repo:
            rc, _stdout, stderr = self.git_runner(
                ["git", "clone", ssh_repo, str(self.src_dir)]
            )
            if rc == 0:
                return self.src_dir
            ssh_error = stderr.strip()
        raise RuntimeError(
            "could not clone the gsd-path repository — it is private and this "
            "machine has no working GitHub credentials. Fix one of these, then "
            "retry:\n"
            "  1. run `gh auth login` (the GitHub CLI sets up git credentials), or\n"
            "  2. add an SSH key to your GitHub account, or\n"
            "  3. set \"plugin_repo\" in ~/.gsd-path/daemon.json to a URL that "
            "embeds a token.\n"
            f"https attempt: {https_error}\nssh attempt: {ssh_error or 'skipped'}"
        )

    def src_version(self) -> Optional[str]:
        try:
            data = json.loads((self.src_dir / "package.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        version = data.get("version") if isinstance(data, dict) else None
        return version if isinstance(version, str) and version else None

    def _read_cache(self) -> dict:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def _write_cache(self, latest: Optional[str]) -> None:
        payload = {
            "last_fetch": datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat(),
            "last_fetch_epoch": self.clock(),
            "latest": latest,
        }
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass

    def refresh_source(self, ttl_hours: float = 24) -> dict:
        """Fetch + fast-forward the source clone at most once per TTL.

        Offline or any other failure falls back to the cached state and never
        raises.
        """
        cache = self._read_cache()
        last_fetch = cache.get("last_fetch_epoch")
        if isinstance(last_fetch, (int, float)) and not isinstance(last_fetch, bool):
            if self.clock() - last_fetch < ttl_hours * 3600:
                return {"refreshed": False, "latest": cache.get("latest"), "error": None}
        latest = cache.get("latest")
        error = None
        try:
            self.ensure_source()
            rc, stdout, stderr = self.git_runner(
                ["git", "-C", str(self.src_dir), "fetch", "origin", "main"]
            )
            if rc == 0:
                rc, stdout, stderr = self.git_runner(
                    ["git", "-C", str(self.src_dir), "pull", "--ff-only"]
                )
            if rc != 0:
                error = (stderr or stdout).strip() or f"git exited {rc}"
            else:
                version = self.src_version()
                if version:
                    latest = version
        except Exception as exc:  # offline, no git, failed clone — cached state wins
            error = str(exc)
        self._write_cache(latest)
        return {"refreshed": error is None, "latest": latest, "error": error}

    # -- detection ---------------------------------------------------------------

    def _managed_dirs(self, root: Path) -> List[str]:
        try:
            return sorted(
                entry.name
                for entry in root.iterdir()
                if entry.is_dir() and _is_managed_name(entry.name)
            )
        except OSError:
            return []

    def _read_version_stamp(self, skill_dir: Path) -> Optional[str]:
        try:
            stamp = (skill_dir / "VERSION").read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError):
            return None
        return stamp or None

    def detect_global(self) -> Dict[str, dict]:
        result: Dict[str, dict] = {}
        for host in HOSTS:
            root = self.global_root(host)
            skill_dirs = self._managed_dirs(root)
            result[host] = {
                "installed": "gsd-path" in skill_dirs,
                "version": self._read_version_stamp(root / "gsd-path"),
                "root": str(root),
                "skill_dirs": skill_dirs,
            }
        return result

    def _marker_file(self, path: Path, marker: str) -> bool:
        try:
            return path.is_file() and marker in path.read_text(
                encoding="utf-8", errors="replace"
            )
        except OSError:
            return False

    def detect_project(self, root) -> dict:
        project = Path(os.path.abspath(os.path.expanduser(str(root))))
        local_skills = [
            host for host in HOSTS if self._managed_dirs(self.local_root(host, project))
        ]
        runtime_dir = project / HOOKS_DIRECTORY / "runtime"
        runtime = self._marker_file(
            project / HOOKS_DIRECTORY / PROJECT_STATUS_LAUNCHER, PROJECT_STATUS_MARKER
        ) or any(
            self._marker_file(candidate, PROJECT_RUNTIME_MARKER)
            for candidate in self._py_files(runtime_dir)
        )
        hooks = all(
            self._marker_file(project / HOOKS_DIRECTORY / name, GUARD_MARKER)
            for name in GUARD_SCRIPTS
        )
        contracts = all((project / name).is_file() for name in CONTRACT_FILES)
        runtime_version = None
        try:
            declaration = json.loads((project / HOOKS_DIRECTORY / "runtime.json").read_text())
            if declaration.get("schema") == "gsd-path/runtime/v1":
                runtime_version = declaration.get("version")
        except (OSError, ValueError, AttributeError):
            pass
        return {
            "root": str(project),
            "local_skills": local_skills,
            "runtime": runtime,
            "contracts": contracts,
            "hooks": hooks,
            "runtime_version": runtime_version,
        }

    @staticmethod
    def _py_files(directory: Path) -> List[Path]:
        try:
            return sorted(directory.glob("*.py"))
        except OSError:
            return []

    def check_update(self, fetch: bool = False) -> dict:
        if fetch:
            self.refresh_source()
        latest = self._read_cache().get("latest")
        installed = {
            host: entry["version"]
            for host, entry in self.detect_global().items()
            if entry["installed"] and entry["version"]
        }
        return {
            "installed": installed,
            "latest": latest,
            "update_available": any(
                _is_newer(latest, version) for version in installed.values()
            ),
        }

    # -- install/update wrappers --------------------------------------------------

    def _validate_hosts(self, hosts: Sequence[str]) -> List[str]:
        unknown = [host for host in hosts if host not in HOSTS]
        if unknown:
            raise ValueError(f"unsupported host(s): {', '.join(unknown)}")
        return list(hosts)

    def _run_installer(self, op: str, tail: List[str]) -> dict:
        try:
            self.ensure_source()
        except Exception as error:
            result = {"ok": False, "argv": [], "stdout_tail": "", "error": str(error)}
            self._log_op(op, [], 127, "", str(error))
            return result
        argv = [sys.executable, str(self.install_py), *tail]
        rc, stdout, stderr = self.runner(argv)
        self._log_op(op, argv, rc, stdout, stderr)
        error = None
        if rc != 0:
            detail = _tail(stderr) or _tail(stdout)
            prefix = "partial install (exit 2): " if rc == 2 else ""
            error = prefix + detail
        return {
            "ok": rc == 0,
            "argv": [str(part) for part in argv],
            "stdout_tail": _tail(stdout),
            "error": error,
        }

    def install_global(self, hosts: Optional[Sequence[str]] = None,
                       dry_run: bool = False) -> dict:
        tail = ["--all"] if not hosts else [f"--{host}" for host in self._validate_hosts(hosts)]
        if dry_run:
            tail.append("--dry-run")
        return self._run_installer("install-global", tail)

    def update_global(self, dry_run: bool = False) -> dict:
        self.refresh_source()
        tail = ["--update"]
        if dry_run:
            tail.append("--dry-run")
        return self._run_installer("update-global", tail)

    def install_project(self, root, local_hosts: Optional[Sequence[str]] = None,
                        hooks: bool = False, dry_run: bool = False) -> dict:
        project = str(Path(os.path.abspath(os.path.expanduser(str(root)))))
        tail = ["--project", project]
        if local_hosts:
            tail.append("--local")
            tail.extend(f"--{host}" for host in self._validate_hosts(local_hosts))
        else:
            # install.py requires a target selection; --all installs every
            # host's global skills plus the project contracts.
            tail.append("--all")
        if hooks:
            tail.append("--hooks")
        if dry_run:
            tail.append("--dry-run")
        return self._run_installer("install-project", tail)

    def update_project(self, root, dry_run: bool = False) -> dict:
        project = str(Path(os.path.abspath(os.path.expanduser(str(root)))))
        tail = ["--update", "--project", project]
        if dry_run:
            tail.append("--dry-run")
        return self._run_installer("update-project", tail)

    def _log_op(self, op: str, argv: Sequence[str], rc: int,
                stdout: str, stderr: str) -> None:
        record = {
            "at": datetime.fromtimestamp(self.clock(), tz=timezone.utc).isoformat(),
            "op": op,
            "argv": [str(part) for part in argv],
            "rc": rc,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
        }
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            pass

    # -- uninstall planning -----------------------------------------------------

    def _is_proven_skill_dir(self, skill_dir: Path) -> bool:
        if (skill_dir / "VERSION").is_file():
            return True
        try:
            text = (skill_dir / "SKILL.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return "gsd-path" in text

    @staticmethod
    def _plan_guard(plan: List[dict], skipped: List[dict]) -> Tuple[List[dict], List[dict]]:
        """Hard rule: nothing under a .project/ directory is ever planned."""
        safe = []
        for entry in plan:
            if NEVER_TOUCH_DIRECTORY in Path(entry["path"]).parts:
                skipped.append({
                    "path": entry["path"],
                    "reason": "inside .project/ — never touched",
                })
            else:
                safe.append(entry)
        return safe, skipped

    def _plan_skill_dirs(self, root: Path, scope_label: str,
                         plan: List[dict], skipped: List[dict]) -> None:
        if not root.is_dir():
            return
        try:
            entries = sorted(root.iterdir())
        except OSError:
            return
        for entry in entries:
            if _is_backup_name(entry.name):
                skipped.append({"path": str(entry), "reason": "backup directory — never touched"})
            elif _is_managed_name(entry.name) and entry.is_dir():
                if self._is_proven_skill_dir(entry):
                    plan.append({
                        "path": str(entry),
                        "kind": "dir",
                        "reason": f"managed gsd-path skill directory ({scope_label})",
                    })
                else:
                    skipped.append({
                        "path": str(entry),
                        "reason": "managed name but no VERSION stamp and no "
                                  "gsd-path SKILL.md — kept",
                    })

    def plan_uninstall_global(self, hosts: Optional[Sequence[str]] = None) -> dict:
        selected = self._validate_hosts(hosts) if hosts else list(HOSTS)
        plan: List[dict] = []
        skipped: List[dict] = []
        for host in selected:
            root = self.global_root(host)
            if not root.is_dir():
                skipped.append({"path": str(root), "reason": f"{host} skills root does not exist"})
                continue
            self._plan_skill_dirs(root, f"{host} global root", plan, skipped)
        if "cursor" in selected:
            agent = self.user_home / ".cursor" / "agents" / "gsd-path.md"
            if agent.is_file():
                plan.append({
                    "path": str(agent),
                    "kind": "file",
                    "reason": "cursor gsd-path subagent file",
                })
        plan, skipped = self._plan_guard(plan, skipped)
        return {"plan": plan, "skipped": skipped}

    def _template_bytes(self, name: str) -> Optional[bytes]:
        try:
            return (self.src_dir / name).read_bytes()
        except OSError:
            return None

    def _plan_contract(self, path: Path, template: Optional[bytes],
                       plan: List[dict], skipped: List[dict]) -> None:
        if not path.is_file():
            return
        if template is None:
            skipped.append({
                "path": str(path),
                "reason": "no local source clone to verify against — kept",
            })
            return
        try:
            identical = path.read_bytes() == template
        except OSError:
            identical = False
        if identical:
            plan.append({
                "path": str(path),
                "kind": "file",
                "reason": "byte-identical to the source template",
            })
        else:
            skipped.append({"path": str(path), "reason": "user-modified, kept"})

    def _git_hooks_dir(self, project: Path) -> Optional[Path]:
        rc, stdout, _stderr = self.git_runner(
            ["git", "rev-parse", "--show-toplevel", "--git-path", "hooks"],
            cwd=str(project),
        )
        if rc == 0:
            lines = [line for line in stdout.splitlines() if line]
            if len(lines) == 2:
                toplevel, hooks_path = lines
                if os.path.abspath(toplevel) == str(project):
                    return Path(os.path.abspath(os.path.join(str(project), hooks_path)))
        dot_git = project / ".git"
        return dot_git / "hooks" if dot_git.is_dir() else None

    def plan_uninstall_project(self, root) -> dict:
        project = Path(os.path.abspath(os.path.expanduser(str(root))))
        plan: List[dict] = []
        skipped: List[dict] = []

        for host in HOSTS:
            self._plan_skill_dirs(
                self.local_root(host, project), f"{host} project-local root", plan, skipped
            )

        runtime_dir = project / HOOKS_DIRECTORY / "runtime"
        for candidate in self._py_files(runtime_dir):
            if self._marker_file(candidate, PROJECT_RUNTIME_MARKER):
                plan.append({
                    "path": str(candidate),
                    "kind": "file",
                    "reason": "marker-matched project runtime script",
                })
            else:
                skipped.append({
                    "path": str(candidate),
                    "reason": "no gsd-path runtime marker — kept",
                })

        declaration = project / HOOKS_DIRECTORY / "runtime.json"
        if declaration.is_file() and not declaration.is_symlink():
            try:
                data = json.loads(declaration.read_text())
                if isinstance(data, dict) and data.get("schema") == "gsd-path/runtime/v1":
                    plan.append({"path": str(declaration), "kind": "file", "reason": "managed runtime declaration; shared runtime versions are retained"})
            except (OSError, ValueError):
                skipped.append({"path": str(declaration), "reason": "invalid runtime declaration — kept"})

        launcher = project / HOOKS_DIRECTORY / PROJECT_STATUS_LAUNCHER
        if launcher.is_file():
            if self._marker_file(launcher, PROJECT_STATUS_MARKER):
                plan.append({
                    "path": str(launcher),
                    "kind": "file",
                    "reason": "marker-matched project status launcher",
                })
            else:
                skipped.append({
                    "path": str(launcher),
                    "reason": "no gsd-path status-launcher marker — kept",
                })

        for name in GUARD_SCRIPTS:
            candidate = project / HOOKS_DIRECTORY / name
            if not candidate.is_file():
                continue
            if self._marker_file(candidate, GUARD_MARKER):
                plan.append({
                    "path": str(candidate),
                    "kind": "file",
                    "reason": "marker-matched guard script",
                })
            else:
                skipped.append({
                    "path": str(candidate),
                    "reason": "no gsd-path guard marker — kept",
                })

        for name in CONTRACT_FILES:
            self._plan_contract(project / name, self._template_bytes(name), plan, skipped)
        self._plan_contract(
            project / ".claude" / "CLAUDE.md", CLAUDE_BRIDGE.encode("utf-8"), plan, skipped
        )

        for relative in SETTINGS_FILES:
            settings = project / relative
            if not settings.is_file():
                continue
            try:
                parsed = json.loads(settings.read_text(encoding="utf-8", errors="replace"))
            except ValueError:
                skipped.append({"path": str(settings), "reason": "not valid JSON — kept"})
                continue
            if not isinstance(parsed, dict):
                skipped.append({"path": str(settings), "reason": "not a JSON object — kept"})
                continue
            unmerged = _unmerged_settings(parsed)
            if unmerged is None:
                continue
            reason = "remove gsd-path guard hook entries"
            if not unmerged:
                reason += "; file becomes empty and is deleted"
            plan.append({"path": str(settings), "kind": "settings", "reason": reason})

        hooks_dir = self._git_hooks_dir(project)
        if hooks_dir is not None:
            for name in GIT_HOOK_NAMES:
                hook = hooks_dir / name
                if not hook.is_file():
                    continue
                if self._marker_file(hook, GUARD_MARKER):
                    plan.append({
                        "path": str(hook),
                        "kind": "file",
                        "reason": "marker-matched gsd-path git hook",
                    })
                else:
                    skipped.append({"path": str(hook), "reason": "user git hook — kept"})

        plan, skipped = self._plan_guard(plan, skipped)
        return {"plan": plan, "skipped": skipped}

    # -- uninstall apply ---------------------------------------------------------

    def _apply_settings_removal(self, settings: Path) -> None:
        parsed = json.loads(settings.read_text(encoding="utf-8", errors="replace"))
        unmerged = _unmerged_settings(parsed) if isinstance(parsed, dict) else None
        if unmerged is None:
            return
        if not unmerged:
            self._remove_file(str(settings))
        else:
            self._write_file(str(settings), json.dumps(unmerged, indent=2) + "\n")

    def apply_plan(self, plan: dict, confirm: bool = False) -> dict:
        if not confirm:
            return {
                "ok": False,
                "refused": True,
                "error": "confirmation required — pass confirm=True to apply",
                "applied": [],
                "errors": [],
            }
        applied: List[str] = []
        errors: List[dict] = []
        for entry in plan.get("plan", []):
            path = entry.get("path", "")
            if NEVER_TOUCH_DIRECTORY in Path(path).parts:
                errors.append({"path": path, "error": "refused: path is inside .project/"})
                continue
            try:
                kind = entry.get("kind")
                if kind == "dir":
                    self._remove_dir(path)
                elif kind == "file":
                    self._remove_file(path)
                elif kind == "settings":
                    self._apply_settings_removal(Path(path))
                else:
                    raise ValueError(f"unknown plan entry kind: {kind}")
                applied.append(path)
            except (OSError, ValueError) as error:
                errors.append({"path": path, "error": str(error)})
        self._log_op(
            "uninstall-apply",
            [entry.get("path", "") for entry in plan.get("plan", [])],
            0 if not errors else 1,
            "\n".join(applied),
            json.dumps(errors),
        )
        return {"ok": not errors, "applied": applied, "errors": errors}
