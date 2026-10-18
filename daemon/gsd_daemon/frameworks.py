"""Installed and latest versions of gsd-pi and gsd-core, and their update.

Installed versions are read from files: the npm package behind each command,
and gsd-core's VERSION file in each agent host. The latest versions come from
the npm registry only when the user checks for updates (cached in between),
the same rule as the GSD Path skills. An update runs each framework's own
update path: `gsd update` for gsd-pi, and for gsd-core the installer once per
installed host, as gsd-core's /gsd-update does.
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from . import subprocess_platform
from .plugin import _is_newer, _tail

PACKAGES = {"gsd-pi": "@opengsd/gsd-pi", "gsd-core": "@opengsd/gsd-core"}
COMMANDS = {"gsd-pi": "gsd", "gsd-core": "gsd-core"}
REGISTRY = "https://registry.npmjs.org/{name}/latest"
FETCH_TIMEOUT_S = 30  # the same bound as the GSD Path release check (release_source.py)

# gsd-core's agent hosts and their default config folders, from each host's
# capabilities/<host>/capability.json "configHome" (env override first).
CORE_HOSTS: Tuple[Tuple[str, Tuple[str, ...], Tuple[str, ...]], ...] = (
    # (install flag, env overrides, default folders below the home folder, first found wins)
    ("claude", ("CLAUDE_CONFIG_DIR",), (".claude",)),
    ("opencode", ("OPENCODE_CONFIG_DIR",), (".config/opencode",)),
    ("kilo", ("KILO_CONFIG_DIR",), (".config/kilo",)),
    ("codex", ("CODEX_HOME",), (".codex",)),
    ("kimi", ("KIMI_CONFIG_DIR",), (".config/agents", ".agents")),
    ("kimi-code", ("KIMI_CODE_HOME",), (".kimi-code",)),
    ("copilot", ("COPILOT_CONFIG_DIR", "COPILOT_HOME"), (".copilot",)),
    ("antigravity", ("ANTIGRAVITY_CONFIG_DIR",),
     (".gemini/antigravity", ".gemini/antigravity-ide", ".gemini/antigravity-cli")),
    ("cursor", ("CURSOR_CONFIG_DIR",), (".cursor",)),
    ("windsurf", ("WINDSURF_CONFIG_DIR",), (".codeium/windsurf",)),
    ("augment", ("AUGMENT_CONFIG_DIR",), (".augment",)),
    ("trae", ("TRAE_CONFIG_DIR",), (".trae",)),
    ("qwen", ("QWEN_CONFIG_DIR",), (".qwen",)),
    ("hermes", ("HERMES_HOME",), (".hermes",)),
    ("cline", ("CLINE_CONFIG_DIR",), (".cline",)),
    ("codebuddy", ("CODEBUDDY_CONFIG_DIR",), (".codebuddy",)),
    ("zcode", ("ZCODE_CONFIG_DIR",), (".zcode",)),
    ("pi", ("PI_CODING_AGENT_DIR",), (".pi/agent",)),
)

Runner = Callable[[Sequence[str], Dict[str, str]], Tuple[int, str, str]]


def _run(argv: Sequence[str], env: Dict[str, str]) -> Tuple[int, str, str]:
    try:
        # No input: an installer that would ask a question gets none instead of hanging.
        proc = subprocess_platform.run([str(part) for part in argv], env=env, stdin=subprocess.DEVNULL,
                                       capture_output=True, text=True, check=False)
    except OSError as error:
        return 127, "", str(error)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url), timeout=FETCH_TIMEOUT_S) as response:
        return response.read()


class Frameworks:
    def __init__(self, home: Optional[Path] = None, runner: Runner = _run,
                 fetch: Callable[[str], bytes] = _fetch, env: Optional[Dict[str, str]] = None,
                 extra_dirs: Optional[List[Path]] = None):
        self.home = Path(home) if home else Path.home()
        self.extra_dirs = extra_dirs
        self.runner = runner
        self.fetch = fetch
        self.env = dict(os.environ if env is None else env)

    @property
    def cache_path(self) -> Path:
        return self.home / ".gsd-path" / "frameworks.json"

    @property
    def log_path(self) -> Path:
        return self.home / ".gsd-path" / "frameworks.log"

    # -- installed ---------------------------------------------------------------

    def search_path(self) -> str:
        """PATH plus the usual Node install folders: the app's daemon starts with a short PATH."""
        extra = self.extra_dirs
        if extra is None:
            extra = [self.home / ".npm-global" / "bin", self.home / ".bun" / "bin", self.home / ".volta" / "bin",
                     self.home / "Library" / "pnpm", self.home / ".local" / "share" / "pnpm",
                     Path("/opt/homebrew/bin"), Path("/usr/local/bin")]
            extra += [Path(p) for p in sorted(glob.glob(str(self.home / ".nvm" / "versions" / "node" / "*" / "bin")))]
        parts = [p for p in self.env.get("PATH", "").split(os.pathsep) if p]
        return os.pathsep.join(parts + [str(p) for p in extra if str(p) not in parts])

    def package(self, name: str) -> Optional[dict]:
        """The npm package behind the framework's command: {version, dir, bin_dir}."""
        command = shutil.which(COMMANDS[name], path=self.search_path())
        if not command:
            return None
        current = Path(os.path.realpath(command)).parent
        for folder in [current, *current.parents]:
            try:
                data = json.loads((folder / "package.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict) and data.get("name") == PACKAGES[name]:
                version = data.get("version")
                return {"version": version if isinstance(version, str) else None, "dir": str(folder),
                        "bin_dir": str(Path(command).parent)}
        return None

    def core_hosts(self) -> List[dict]:
        """Agent hosts with a gsd-core install: {host, dir, version}."""
        found = []
        for host, env_names, defaults in CORE_HOSTS:
            override = next((self.env[e] for e in env_names if self.env.get(e)), None)
            folders = [Path(os.path.expanduser(override))] if override else [self.home / d for d in defaults]
            for folder in folders:
                stamp = folder / "gsd-core" / "VERSION"
                try:
                    version = stamp.read_text(encoding="utf-8").strip()
                except OSError:
                    continue
                found.append({"host": host, "dir": str(folder), "version": version or None})
                break
        return found

    # -- latest ------------------------------------------------------------------

    def _cache(self) -> dict:
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return data if isinstance(data, dict) else {}

    def check(self) -> Dict[str, Optional[str]]:
        """Read the latest versions from the npm registry; return an error per framework that failed."""
        cache, errors = self._cache(), {}
        for name, package in PACKAGES.items():
            try:
                version = json.loads(self.fetch(REGISTRY.format(name=package.replace("/", "%2F")))).get("version")
                if not isinstance(version, str) or not version:
                    raise ValueError("the registry answer has no version")
                cache[name] = {"latest": version, "checked": datetime.now(timezone.utc).isoformat()}
                errors[name] = None
            except Exception as error:  # a failed check keeps the last known version
                errors[name] = str(error)
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass
        return errors

    # -- status ------------------------------------------------------------------

    def status(self) -> dict:
        cache = self._cache()
        result = {}
        for name in PACKAGES:
            latest = (cache.get(name) or {}).get("latest")
            package = self.package(name)
            hosts = self.core_hosts() if name == "gsd-core" else []
            versions = [p["version"] for p in [package] if p] + [h["version"] for h in hosts]
            result[name] = {
                "installed": package["version"] if package else None,
                "hosts": hosts,
                "latest": latest,
                "checked": (cache.get(name) or {}).get("checked"),
                "update_available": bool(latest) and any(_is_newer(latest, v) for v in versions if v),
                "detected": bool(package or hosts),
            }
        return result

    # -- update ------------------------------------------------------------------

    def plan(self, name: str) -> List[List[str]]:
        """The commands an update runs, in order."""
        if name not in PACKAGES:
            raise ValueError("name must be gsd-pi or gsd-core")
        package = self.package(name)
        if name == "gsd-pi":
            if not package:
                raise ValueError("gsd-pi is not installed: no `gsd` command was found")
            # gsd-pi's own update: installs @opengsd/gsd-pi@latest with the manager that owns it, then checks it.
            return [[str(Path(package["bin_dir"]) / "gsd"), "update"]]
        hosts = self.core_hosts()
        if not package and not hosts:
            raise ValueError("gsd-core is not installed: no `gsd-core` command and no agent host install")
        commands = []
        if package:
            commands.append([self._tool("npm"), "install", "-g", f"{PACKAGES[name]}@latest"])
        # The same per-host command as gsd-core's /gsd-update, with the folder spelled out.
        commands += [[self._tool("npx"), "-y", f"--package={PACKAGES[name]}@latest", "--", "gsd-core",
                      f"--{h['host']}", "--global", "--config-dir", h["dir"]] for h in hosts]
        return commands

    def _tool(self, command: str) -> str:
        found = shutil.which(command, path=self.search_path())
        if not found:
            raise ValueError(f"`{command}` was not found; install Node.js to update gsd-core")
        return found

    def update(self, name: str, dry_run: bool = False) -> dict:
        commands = self.plan(name)
        if dry_run:
            return {"ok": True, "commands": commands, "stdout_tail": "", "error": None}
        env = {**self.env, "PATH": self.search_path()}
        output: List[str] = []
        for argv in commands:
            rc, stdout, stderr = self.runner(argv, env)
            self._log(name, argv, rc, stdout, stderr)
            output.append(f"$ {' '.join(argv)}\n{_tail(stdout)}")
            if rc != 0:
                return {"ok": False, "commands": commands, "stdout_tail": "\n".join(output),
                        "error": _tail(stderr) or _tail(stdout) or f"exit {rc}"}
        self._forget_update_notices(name)
        return {"ok": True, "commands": commands, "stdout_tail": "\n".join(output), "error": None,
                "status": self.status()[name]}

    def _forget_update_notices(self, name: str) -> None:
        """Remove the framework's own cached update notice, as its updater does, so it does not
        keep announcing the version just installed."""
        notices = {"gsd-pi": [self.home / ".gsd" / ".update-check"],
                   "gsd-core": [self.home / ".cache" / "gsd" / "gsd-update-check-opengsd-gsd-core.json",
                                self.home / ".cache" / "gsd" / "gsd-update-check.json"]}
        for path in notices[name]:
            try:
                path.unlink()
            except OSError:
                pass

    def _log(self, name: str, argv: Sequence[str], rc: int, stdout: str, stderr: str) -> None:
        record = {"at": datetime.now(timezone.utc).isoformat(), "framework": name, "argv": list(argv),
                  "rc": rc, "stdout_tail": _tail(stdout), "stderr_tail": _tail(stderr)}
        try:
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record) + "\n")
        except OSError:
            pass
