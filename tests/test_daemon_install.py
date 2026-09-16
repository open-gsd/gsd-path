import http.client
import json
import os
import plistlib
import subprocess
import sys
import tempfile
import types
import unittest
import threading
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import serve as serve_module
from gsd_daemon import tray as tray_module
from gsd_daemon.config import Config
from gsd_daemon.installer import (
    ENV_PLATFORM,
    LAUNCH_AGENT_LABEL,
    LINUX_SERVICE_NAME,
    TRAY_APP_NAME,
    WINDOWS_SHORTCUT_NAME,
    Installer,
)
from gsd_daemon.watcher import Watcher


class FakeRunner:
    """Records every command; never touches the real system."""

    def __init__(self, which_map=None, fail_if=None):
        self.calls = []  # list of (cmd_list, check_bool)
        self.which_map = which_map if which_map is not None else {"swiftc": "/usr/bin/swiftc"}
        self.fail_if = fail_if  # optional callable(cmd_list) -> bool

    def run(self, cmd, check=True):
        cmd = [str(part) for part in cmd]
        self.calls.append((cmd, check))
        failed = bool(self.fail_if and self.fail_if(cmd))
        returncode = 1 if failed else 0
        if check and failed:
            raise subprocess.CalledProcessError(returncode, cmd)
        return subprocess.CompletedProcess(cmd, returncode, "", "")

    def which(self, name):
        return self.which_map.get(name)

    def commands(self):
        return [cmd for cmd, _check in self.calls]


def make_installer(tmp, platform="darwin", runner=None, dry_run=False, **kwargs):
    home = Path(tmp) / "home"
    home.mkdir(exist_ok=True)
    return Installer(
        home=home,
        launch_agents_dir=home / "Library" / "LaunchAgents",
        startup_dir=home / "startup",
        systemd_user_dir=home / "systemd",
        runner=runner or FakeRunner(),
        platform=platform,
        repo_root=Path(tmp) / "repo",
        dry_run=dry_run,
        **kwargs,
    )


def make_repo(tmp):
    repo = Path(tmp) / "repo"
    (repo / "daemon").mkdir(parents=True)
    (repo / "daemon" / "pyproject.toml").write_text("[project]\nname = 'x'\n", encoding="utf-8")
    return repo


def run_captured(installer, method, **kwargs):
    lines = []
    installer.out = lines.append
    result = getattr(installer, method)(**kwargs)
    return "\n".join(lines), result


class PlistTests(unittest.TestCase):
    def test_daemon_plist_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = make_installer(tmp)
            payload = installer.daemon_plist()
            loaded = plistlib.loads(plistlib.dumps(payload))
            self.assertEqual(loaded["Label"], "org.gsd-path.daemon")
            venv_python = str(installer.home / ".gsd-path" / "venv" / "bin" / "python3")
            self.assertEqual(
                loaded["ProgramArguments"],
                [venv_python, "-m", "gsd_daemon", "serve", "--port", "8765"],
            )
            self.assertIs(loaded["RunAtLoad"], True)
            self.assertIs(loaded["KeepAlive"], True)
            self.assertEqual(loaded["ProcessType"], "Interactive")
            logs = installer.home / ".gsd-path" / "logs"
            self.assertEqual(loaded["StandardOutPath"], str(logs / "stdout.log"))
            self.assertEqual(loaded["StandardErrorPath"], str(logs / "stderr.log"))

    def test_install_writes_parseable_plist(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            installer = make_installer(tmp)
            installer.install()
            self.assertTrue(installer.plist_path.exists())
            with installer.plist_path.open("rb") as handle:
                loaded = plistlib.load(handle)
            self.assertEqual(loaded["Label"], LAUNCH_AGENT_LABEL)
            self.assertEqual(loaded["ProgramArguments"][1:], ["-m", "gsd_daemon",
                                                              "serve", "--port", "8765"])


class DryRunTests(unittest.TestCase):
    def test_dry_run_darwin(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, platform="darwin", runner=runner, dry_run=True)
            output, _rc = run_captured(installer, "install")
            self.assertEqual(runner.calls, [])
            self.assertFalse(installer.plist_path.exists())
            self.assertIn("would run:", output)
            self.assertIn("-m venv", output)
            self.assertIn("pip install --upgrade", output + " ")
            self.assertIn("launchctl bootstrap gui/", output)
            self.assertIn("org.gsd-path.daemon.plist", output)
            self.assertIn("build.sh", output)
            self.assertIn("ditto -rsrc", output)
            self.assertIn("make login item", output)
            self.assertIn("RunAtLoad", output)

    def test_dry_run_win32(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, platform="win32", runner=runner, dry_run=True)
            output, _rc = run_captured(installer, "install")
            self.assertEqual(runner.calls, [])
            self.assertIn("powershell", output)
            self.assertIn("CreateShortcut", output)
            self.assertIn(WINDOWS_SHORTCUT_NAME, output)
            self.assertIn("tray --serve", output)
            self.assertNotIn("launchctl", output)

    def test_dry_run_linux(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, platform="linux", runner=runner, dry_run=True)
            output, _rc = run_captured(installer, "install")
            self.assertEqual(runner.calls, [])
            self.assertIn("systemctl --user enable --now", output)
            self.assertIn(LINUX_SERVICE_NAME, output)
            self.assertIn("Restart=always", output)
            self.assertNotIn("launchctl", output)

    def test_dry_run_uninstall_executes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            runner = FakeRunner()
            installer = make_installer(tmp, runner=runner, dry_run=True)
            output, _rc = run_captured(installer, "uninstall")
            self.assertEqual(runner.calls, [])
            self.assertIn("launchctl bootout", output)
            self.assertIn("delete login item", output)


class DarwinInstallTests(unittest.TestCase):
    def test_command_sequence_and_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, runner=runner)
            self.assertEqual(installer.install(), 0)
            commands = runner.commands()

            venv = installer.home / ".gsd-path" / "venv"
            pip = str(venv / "bin" / "pip")
            self.assertEqual(commands[0], [sys.executable, "-m", "venv", str(venv)])
            self.assertEqual(commands[1], [pip, "install", "--upgrade",
                                           str(installer.package_dir)])
            self.assertEqual(commands[2], [pip, "install", "--upgrade",
                                           str(installer.package_dir) + "[tray]"])
            uid = os.getuid()
            self.assertEqual(commands[3], ["launchctl", "bootout",
                                           f"gui/{uid}/{LAUNCH_AGENT_LABEL}"])
            self.assertEqual(commands[4], ["launchctl", "bootstrap", f"gui/{uid}",
                                           str(installer.plist_path)])
            joined = [" ".join(cmd) for cmd in commands]
            self.assertTrue(any("build.sh" in line for line in joined))
            self.assertTrue(any(line.startswith("ditto -rsrc") for line in joined))
            delete_calls = [line for line in joined
                            if "osascript" in line and "delete login item" in line]
            make_calls = [line for line in joined
                          if "osascript" in line and "make login item" in line]
            self.assertEqual(len(delete_calls), 1)
            self.assertEqual(len(make_calls), 1)
            self.assertIn(str(installer.app_dest), make_calls[0])

            # Idempotent: a second install runs the same full sequence cleanly.
            runner.calls.clear()
            self.assertEqual(installer.install(), 0)
            self.assertEqual(len(runner.commands()), len(commands))

    def test_bootstrap_falls_back_to_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner(fail_if=lambda cmd: cmd[:2] == ["launchctl", "bootstrap"])
            installer = make_installer(tmp, runner=runner)
            self.assertEqual(installer.install(), 0)
            joined = [" ".join(cmd) for cmd in runner.commands()]
            self.assertTrue(any(line.startswith("launchctl load -w") for line in joined))

    def test_tray_extra_failure_warns_and_continues(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner(fail_if=lambda cmd: cmd[-1].endswith("[tray]"))
            installer = make_installer(tmp, runner=runner)
            output, _rc = run_captured(installer, "install")
            self.assertIn("tray extra failed", output)
            # autostart still registered after the warning
            joined = [" ".join(cmd) for cmd in runner.commands()]
            self.assertTrue(any("launchctl bootstrap" in line for line in joined))

    def test_missing_swiftc_skips_tray_app(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner(which_map={})
            installer = make_installer(tmp, runner=runner)
            output, _rc = run_captured(installer, "install")
            self.assertIn("swiftc not found", output)
            joined = [" ".join(cmd) for cmd in runner.commands()]
            self.assertFalse(any("build.sh" in line for line in joined))
            self.assertFalse(any("make login item" in line for line in joined))
            self.assertTrue(any("launchctl bootstrap" in line for line in joined))

    def test_no_tray_no_autostart_flags(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, runner=runner)
            installer.install(no_tray=True, no_autostart=True)
            commands = runner.commands()
            self.assertEqual(len(commands), 2)  # venv + core package only
            self.assertFalse(installer.plist_path.exists())

    def test_uninstall_reverses_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, runner=runner)
            installer.install()
            self.assertTrue(installer.plist_path.exists())
            runner.calls.clear()
            self.assertEqual(installer.uninstall(), 0)
            uid = os.getuid()
            commands = runner.commands()
            self.assertEqual(commands[0], ["launchctl", "bootout",
                                           f"gui/{uid}/{LAUNCH_AGENT_LABEL}"])
            joined = [" ".join(cmd) for cmd in commands]
            self.assertTrue(any("delete login item" in line and TRAY_APP_NAME in line
                                for line in joined))
            self.assertFalse(installer.plist_path.exists())
            # bootout before plist removal: plist was still present during bootout
            self.assertIn("already absent", run_captured(installer, "uninstall")[0])


class WindowsInstallTests(unittest.TestCase):
    def test_shortcut_script_and_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, platform="win32", runner=runner)
            self.assertEqual(installer.install(), 0)
            commands = runner.commands()
            ps = [cmd for cmd in commands if cmd[0] == "powershell"]
            self.assertEqual(len(ps), 1)
            script = ps[0][-1]
            self.assertIn("WScript.Shell", script)
            self.assertIn("CreateShortcut", script)
            self.assertIn(WINDOWS_SHORTCUT_NAME, script)
            self.assertIn(str(installer.home / ".gsd-path" / "venv" / "Scripts"
                              / "pythonw.exe"), script)
            self.assertIn("$s.Arguments = '-m gsd_daemon tray --serve'", script)
            # venv and pip use Scripts/ on win32
            self.assertIn(str(Path("Scripts") / "pip.exe"), " ".join(commands[1]))

            # uninstall deletes the shortcut; tolerant when it is already gone
            self.assertEqual(installer.uninstall(), 0)
            shortcut = installer.shortcut_path
            shortcut.parent.mkdir(parents=True, exist_ok=True)
            shortcut.write_text("lnk", encoding="utf-8")
            self.assertEqual(installer.uninstall(), 0)
            self.assertFalse(shortcut.exists())


class LinuxInstallTests(unittest.TestCase):
    def test_unit_content_and_enable(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner()
            installer = make_installer(tmp, platform="linux", runner=runner)
            self.assertEqual(installer.install(), 0)
            unit = installer.unit_path.read_text(encoding="utf-8")
            venv_python = installer.home / ".gsd-path" / "venv" / "bin" / "python3"
            self.assertIn("Type=simple", unit)
            self.assertIn(f"ExecStart={venv_python} -m gsd_daemon serve --port 8765",
                          unit)
            self.assertIn("Restart=always", unit)
            self.assertIn("WantedBy=default.target", unit)
            commands = runner.commands()
            self.assertEqual(commands[3], ["systemctl", "--user", "daemon-reload"])
            self.assertEqual(commands[4], ["systemctl", "--user", "enable", "--now",
                                           LINUX_SERVICE_NAME])

            runner.calls.clear()
            self.assertEqual(installer.uninstall(), 0)
            commands = runner.commands()
            self.assertEqual(commands[0], ["systemctl", "--user", "disable", "--now",
                                           LINUX_SERVICE_NAME])
            self.assertEqual(commands[-1], ["systemctl", "--user", "daemon-reload"])
            self.assertFalse(installer.unit_path.exists())

    def test_systemctl_failure_is_best_effort(self):
        with tempfile.TemporaryDirectory() as tmp:
            make_repo(tmp)
            runner = FakeRunner(fail_if=lambda cmd: cmd[0] == "systemctl")
            installer = make_installer(tmp, platform="linux", runner=runner)
            output, _rc = run_captured(installer, "install")
            self.assertIn("systemctl --user failed", output)
            self.assertTrue(installer.unit_path.exists())


class UnsupportedPlatformTests(unittest.TestCase):
    def test_unsupported_platform_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            installer = make_installer(tmp, platform="sunos5")
            output, _rc = run_captured(installer, "install")
            self.assertIn("unsupported platform", output)
            self.assertEqual(installer.install(), 2)

    def test_env_platform_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {ENV_PLATFORM: "linux"}):
                installer = make_installer(tmp, platform=None)
                self.assertEqual(installer.platform, "linux")


class ServeInThreadTests(unittest.TestCase):
    def test_health_endpoint(self):
        watcher = Watcher(Config())
        server, thread = serve_module.serve_in_thread(watcher, port=0)
        try:
            port = server.server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/health")
            response = connection.getresponse()
            body = json.loads(response.read())
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertEqual(body, {"ok": True})
            self.assertTrue(thread.is_alive())
        finally:
            server.shutdown()
            server.server_close()


def _fake_tray_modules(health_results, servers):
    pil = types.ModuleType("PIL")
    pil_image = types.ModuleType("PIL.Image")
    pil_image.new = lambda *args, **kwargs: object()
    pil_draw = types.ModuleType("PIL.ImageDraw")

    class _Draw:
        def __init__(self, image):
            pass

        def ellipse(self, *args, **kwargs):
            pass

        def line(self, *args, **kwargs):
            pass

        def rounded_rectangle(self, *args, **kwargs):
            pass

    pil_draw.Draw = _Draw
    pil.Image = pil_image
    pil.ImageDraw = pil_draw

    pystray = types.ModuleType("pystray")

    class MenuItem:
        def __init__(self, label, action=None, enabled=True, checked=None):
            self.label = label

    class Menu:
        SEPARATOR = object()

        def __init__(self, *items):
            self.items = items

    class Icon:
        def __init__(self, name, image, title, menu):
            self.icon = image
            self.title = title
            self.menu = menu

        def update_menu(self):
            pass

        def run(self):
            # While the tray loop runs, the --serve dashboard must be live.
            if not servers:
                return
            port = servers[0].server_address[1]
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            connection.request("GET", "/health")
            response = connection.getresponse()
            health_results.append((response.status, json.loads(response.read())))
            connection.close()

        def stop(self):
            pass

    pystray.MenuItem = MenuItem
    pystray.Menu = Menu
    pystray.Icon = Icon
    return {"pystray": pystray, "PIL": pil,
            "PIL.Image": pil_image, "PIL.ImageDraw": pil_draw}


class TrayServeFlagTests(unittest.TestCase):
    def test_tray_serve_starts_dashboard_thread(self):
        health_results = []
        servers = []
        real_serve_in_thread = serve_module.serve_in_thread
        scans = []
        bound = []
        scanned = threading.Event()
        real_server = serve_module.ThreadingHTTPServer

        def bind(*args, **kwargs):
            server = real_server(*args, **kwargs)
            bound.append(server.server_address)
            return server

        def attach_spend(watcher, current):
            scans.append(bool(bound))
            scanned.set()

        def spy(watcher, port):
            server, thread = real_serve_in_thread(watcher, port)
            servers.append(server)
            return server, thread

        modules = _fake_tray_modules(health_results, servers)
        with mock.patch.dict(sys.modules, modules):
            with mock.patch.object(tray_module, "serve_in_thread", spy), mock.patch.object(
                tray_module.Watcher, "_attach_spend", attach_spend
            ), mock.patch.object(serve_module, "ThreadingHTTPServer", bind):
                tray_module.run(Config(session_dirs=[]), serve_port=0)
                self.assertTrue(scanned.wait(5))

        self.assertTrue(scans)
        self.assertTrue(all(scans), "session scan ran before the dashboard server started")
        self.assertEqual(len(servers), 1)
        self.assertNotEqual(servers[0].server_address[1], 0)
        self.assertEqual(health_results, [(200, {"ok": True})])
        # server shut down after the tray loop exited
        self.assertEqual(servers[0].socket.fileno(), -1)

    def test_tray_without_serve_starts_no_server(self):
        servers = []

        def spy(watcher, port):
            servers.append(port)
            raise AssertionError("serve_in_thread must not be called")

        modules = _fake_tray_modules([], [])
        with mock.patch.dict(sys.modules, modules):
            with mock.patch.object(tray_module, "serve_in_thread", spy):
                tray_module.run(Config())
        self.assertEqual(servers, [])


if __name__ == "__main__":
    unittest.main()
