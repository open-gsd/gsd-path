from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, List, Optional

from .serve import DEFAULT_PORT

LAUNCH_AGENT_LABEL = "org.gsd-path.daemon"
TRAY_APP_NAME = "GSDPathTray"
TRAY_APP_BUNDLE = TRAY_APP_NAME + ".app"
WINDOWS_SHORTCUT_NAME = "gsd-path-daemon.lnk"
LINUX_SERVICE_NAME = "gsd-path-daemon.service"
ENV_PLATFORM = "GSD_DAEMON_PLATFORM"


class Runner:
    """Subprocess executor. Every external command goes through here so
    dry-run can intercept and tests can inject a fake."""

    def run(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, check=check, capture_output=True, text=True)

    def which(self, name: str) -> Optional[str]:
        return shutil.which(name)


class Installer:
    def __init__(
        self,
        home: Optional[Path] = None,
        launch_agents_dir: Optional[Path] = None,
        startup_dir: Optional[Path] = None,
        systemd_user_dir: Optional[Path] = None,
        runner: Optional[Runner] = None,
        platform: Optional[str] = None,
        repo_root: Optional[Path] = None,
        port: int = DEFAULT_PORT,
        dry_run: bool = False,
        out: Callable[[str], None] = print,
    ) -> None:
        self.home = Path(home) if home is not None else Path.home()
        self.gsd_home = self.home / ".gsd-path"
        self.venv_dir = self.gsd_home / "venv"
        self.logs_dir = self.gsd_home / "logs"
        self.launch_agents_dir = (
            Path(launch_agents_dir)
            if launch_agents_dir is not None
            else self.home / "Library" / "LaunchAgents"
        )
        if startup_dir is not None:
            self.startup_dir = Path(startup_dir)
        else:
            appdata = os.environ.get("APPDATA", str(self.home / "AppData" / "Roaming"))
            self.startup_dir = (
                Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
            )
        self.systemd_user_dir = (
            Path(systemd_user_dir)
            if systemd_user_dir is not None
            else self.home / ".config" / "systemd" / "user"
        )
        self.runner = runner or Runner()
        self.platform = platform or os.environ.get(ENV_PLATFORM) or sys.platform
        self.repo_root = (
            Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[2]
        )
        self.port = port
        self.dry_run = dry_run
        self.out = out
        self._step_no = 0
        self._step_total = 0

    # -- derived paths ------------------------------------------------------

    @property
    def venv_python(self) -> Path:
        if self.platform == "win32":
            return self.venv_dir / "Scripts" / "python.exe"
        return self.venv_dir / "bin" / "python3"

    @property
    def venv_pythonw(self) -> Path:
        return self.venv_dir / "Scripts" / "pythonw.exe"

    @property
    def venv_pip(self) -> Path:
        if self.platform == "win32":
            return self.venv_dir / "Scripts" / "pip.exe"
        return self.venv_dir / "bin" / "pip"

    @property
    def package_dir(self) -> Path:
        return self.repo_root / "daemon"

    @property
    def plist_path(self) -> Path:
        return self.launch_agents_dir / (LAUNCH_AGENT_LABEL + ".plist")

    @property
    def shortcut_path(self) -> Path:
        return self.startup_dir / WINDOWS_SHORTCUT_NAME

    @property
    def unit_path(self) -> Path:
        return self.systemd_user_dir / LINUX_SERVICE_NAME

    @property
    def app_source(self) -> Path:
        return self.repo_root / "daemon" / "macos" / "build" / TRAY_APP_BUNDLE

    @property
    def app_dest(self) -> Path:
        return self.home / "Applications" / TRAY_APP_BUNDLE

    # -- output + execution helpers -----------------------------------------

    def _step(self, title: str) -> None:
        self._step_no += 1
        self.out(f"[{self._step_no}/{self._step_total}] {title}")

    def _exec(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        rendered = " ".join(str(part) for part in cmd)
        if self.dry_run:
            self.out(f"  would run: {rendered}")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        self.out(f"  $ {rendered}")
        return self.runner.run([str(part) for part in cmd], check=check)

    def _write_text(self, path: Path, content: str) -> None:
        if self.dry_run:
            self.out(f"  would write: {path}")
            for line in content.rstrip("\n").splitlines():
                self.out(f"    | {line}")
            return
        self.out(f"  write {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def _write_plist(self, path: Path, payload: dict) -> None:
        self._write_text(path, plistlib.dumps(payload).decode("utf-8"))

    def _mkdir(self, path: Path) -> None:
        if self.dry_run:
            self.out(f"  would mkdir: {path}")
            return
        path.mkdir(parents=True, exist_ok=True)

    def _remove_file(self, path: Path) -> None:
        if self.dry_run:
            self.out(f"  would remove: {path}")
            return
        if path.exists() or path.is_symlink():
            self.out(f"  remove {path}")
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path)
            else:
                path.unlink()
        else:
            self.out(f"  already absent: {path}")

    def _warn(self, message: str) -> None:
        self.out(f"  warning: {message}")

    # -- artifact contents ----------------------------------------------------

    def daemon_plist(self) -> dict:
        return {
            "Label": LAUNCH_AGENT_LABEL,
            "ProgramArguments": [
                str(self.venv_python),
                "-m",
                "gsd_daemon",
                "serve",
                "--port",
                str(self.port),
            ],
            "RunAtLoad": True,
            "KeepAlive": True,
            # The daemon answers the dashboard and tray interactively; without
            # this launchd runs it at background QoS and a 3 s session scan
            # takes minutes.
            "ProcessType": "Interactive",
            "StandardOutPath": str(self.logs_dir / "stdout.log"),
            "StandardErrorPath": str(self.logs_dir / "stderr.log"),
        }

    def linux_unit(self) -> str:
        return (
            "[Unit]\n"
            "Description=GSD Path progress daemon\n"
            "\n"
            "[Service]\n"
            "Type=simple\n"
            f"ExecStart={self.venv_python} -m gsd_daemon serve --port {self.port}\n"
            "Restart=always\n"
            "\n"
            "[Install]\n"
            "WantedBy=default.target\n"
        )

    def windows_shortcut_script(self) -> str:
        return (
            f"$s = (New-Object -COM WScript.Shell).CreateShortcut('{self.shortcut_path}'); "
            f"$s.TargetPath = '{self.venv_pythonw}'; "
            f"$s.Arguments = '-m gsd_daemon tray --serve'; "
            f"$s.WorkingDirectory = '{self.venv_dir / 'Scripts'}'; "
            "$s.Save()"
        )

    # -- install --------------------------------------------------------------

    def install(self, no_tray: bool = False, no_autostart: bool = False) -> int:
        if self.platform not in ("darwin", "win32") and not self.platform.startswith("linux"):
            self.out(f"error: unsupported platform {self.platform!r} "
                     "(expected darwin, win32, or linux)")
            return 2
        if not self.dry_run and not (self.package_dir / "pyproject.toml").exists():
            self.out(f"error: daemon package not found at {self.package_dir}; "
                     "run install from a gsd-path repository checkout")
            return 2

        steps = ["venv", "package"]
        if not no_tray:
            steps.append("tray-extra")
        if not no_autostart:
            steps.append("autostart")
            if self.platform == "darwin" and not no_tray:
                steps.append("tray-app")
        self._step_total = len(steps)
        self._step_no = 0
        mode = " (dry-run)" if self.dry_run else ""
        self.out(f"installing gsd-path-daemon{mode} — platform {self.platform}, "
                 f"home {self.home}")

        self._step("Create isolated virtualenv")
        self._exec([sys.executable, "-m", "venv", str(self.venv_dir)])

        self._step("Install gsd-path-daemon into the virtualenv")
        self._exec([self.venv_pip, "install", "--upgrade", str(self.package_dir)])

        if not no_tray:
            self._step("Install the tray extra (pystray + Pillow)")
            try:
                self._exec([self.venv_pip, "install", "--upgrade",
                            str(self.package_dir) + "[tray]"])
            except subprocess.CalledProcessError:
                self._warn("tray extra failed to install (no network or no pystray "
                           "wheel); continuing — the CLI, watcher, and dashboard work "
                           "without it")

        if no_autostart:
            self.out("autostart skipped (--no-autostart)")
        else:
            self._autostart_install()

        if not no_tray and not no_autostart and self.platform == "darwin":
            self._install_darwin_tray_app()
        elif self.platform == "darwin" and (no_tray or no_autostart):
            self.out(f"tray app skipped ({'--no-tray' if no_tray else '--no-autostart'})")

        self.out("install complete")
        return 0

    def _autostart_install(self) -> None:
        if self.platform == "darwin":
            self._step("Register the LaunchAgent (autostart)")
            self._write_plist(self.plist_path, self.daemon_plist())
            uid = os.getuid()
            domain = f"gui/{uid}"
            self._exec(["launchctl", "bootout", f"{domain}/{LAUNCH_AGENT_LABEL}"],
                       check=False)
            try:
                self._exec(["launchctl", "bootstrap", domain, str(self.plist_path)])
            except subprocess.CalledProcessError:
                self._warn("launchctl bootstrap failed; falling back to launchctl load")
                self._exec(["launchctl", "load", "-w", str(self.plist_path)])
        elif self.platform == "win32":
            self._step("Create the Startup-folder shortcut (autostart)")
            self._mkdir(self.startup_dir)
            self._exec(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
                        "-Command", self.windows_shortcut_script()])
        else:
            self._step("Install the systemd user service (autostart, best-effort)")
            self._write_text(self.unit_path, self.linux_unit())
            try:
                self._exec(["systemctl", "--user", "daemon-reload"])
                self._exec(["systemctl", "--user", "enable", "--now", LINUX_SERVICE_NAME])
            except subprocess.CalledProcessError:
                self._warn("systemctl --user failed; enable the service manually with "
                           f"'systemctl --user enable --now {LINUX_SERVICE_NAME}'")

    def _install_darwin_tray_app(self) -> None:
        self._step("Build and register the native tray app")
        if self.runner.which("swiftc") is None:
            self._warn("swiftc not found (install Xcode Command Line Tools with "
                       "'xcode-select --install'); skipping the native tray app — "
                       "the dashboard and the pystray tray still work")
            return
        self._exec(["bash", str(self.repo_root / "daemon" / "macos" / "build.sh")])
        self._mkdir(self.app_dest.parent)
        self._exec(["ditto", "-rsrc", str(self.app_source), str(self.app_dest)])
        self._exec([
            "osascript", "-e",
            f'tell application "System Events" to delete login item "{TRAY_APP_NAME}"',
        ], check=False)
        self._exec([
            "osascript", "-e",
            'tell application "System Events" to make login item at end with '
            f'properties {{path:"{self.app_dest}", hidden:false}}',
        ])

    # -- uninstall ------------------------------------------------------------

    def uninstall(self) -> int:
        if self.platform not in ("darwin", "win32") and not self.platform.startswith("linux"):
            self.out(f"error: unsupported platform {self.platform!r} "
                     "(expected darwin, win32, or linux)")
            return 2
        steps = ["autostart"]
        if self.platform == "darwin":
            steps += ["login-item", "app"]
        self._step_total = len(steps)
        self._step_no = 0
        mode = " (dry-run)" if self.dry_run else ""
        self.out(f"uninstalling gsd-path-daemon{mode} — platform {self.platform}, "
                 f"home {self.home}")

        if self.platform == "darwin":
            self._step("Unload and remove the LaunchAgent")
            uid = os.getuid()
            result = self._exec(["launchctl", "bootout",
                                 f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], check=False)
            if result.returncode != 0 and self.plist_path.exists():
                self._exec(["launchctl", "unload", str(self.plist_path)], check=False)
            self._remove_file(self.plist_path)

            self._step("Remove the tray-app login item")
            self._exec([
                "osascript", "-e",
                f'tell application "System Events" to delete login item "{TRAY_APP_NAME}"',
            ], check=False)

            self._step("Remove the copied tray app")
            self._remove_file(self.app_dest)
        elif self.platform == "win32":
            self._step("Remove the Startup-folder shortcut")
            self._remove_file(self.shortcut_path)
        else:
            self._step("Disable and remove the systemd user service")
            self._exec(["systemctl", "--user", "disable", "--now", LINUX_SERVICE_NAME],
                       check=False)
            self._remove_file(self.unit_path)
            self._exec(["systemctl", "--user", "daemon-reload"], check=False)

        self.out(f"note: the virtualenv at {self.venv_dir} was kept; "
                 "delete it manually to remove the daemon completely")
        self.out("uninstall complete")
        return 0
