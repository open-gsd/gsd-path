import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

DAEMON = Path(__file__).resolve().parents[1] / "daemon"
sys.path.insert(0, str(DAEMON))

from gsd_daemon import __version__
from gsd_daemon import launch as launch_module
from gsd_daemon.config import Config
from gsd_daemon.installer import Installer
from gsd_daemon.launch import RETIRED_MARKER, ensure_venv, launch, probe_port
from gsd_daemon.serve import serve
from gsd_daemon.watcher import Watcher

UNIX_ONLY = unittest.skipIf(sys.platform == "win32", "uses ps, lsof, and POSIX signals")
NEEDS_UID = unittest.skipUnless(hasattr(os, "getuid"), "launchctl domains need a POSIX uid")

# A process that answers /status like a GSD Path daemon but is not one.
IMPOSTOR = r"""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"schema": "gsd-path-daemon/status/v1",
                           "daemon": {"version": "0.0.1", "pid": os.getpid()}}).encode()
        self.send_response(200); self.end_headers(); self.wfile.write(body)
    def log_message(self, *args): pass
HTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
"""


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class ScriptRunner:
    """Answers commands from a script; runs `real` commands for real."""

    def __init__(self, respond=None, which=None, real=()):
        self.calls = []
        self.respond = respond or (lambda cmd: (0, ""))
        self.which_map = which if which is not None else {"git": "/usr/bin/git"}
        self.real = set(real)

    def run(self, cmd, check=True):
        cmd = [str(part) for part in cmd]
        self.calls.append(cmd)
        if Path(cmd[0]).name in self.real:
            return subprocess.run(cmd, check=check, capture_output=True, text=True)
        returncode, stdout = self.respond(cmd)
        if check and returncode:
            raise subprocess.CalledProcessError(returncode, cmd, stdout, "pip: network is down")
        return subprocess.CompletedProcess(cmd, returncode, stdout, "")

    def which(self, name):
        if name in self.real:
            return name
        return self.which_map.get(name)

    def ran(self, word):
        return [cmd for cmd in self.calls if any(word in part for part in cmd)]

    def pip_runs(self):
        """Commands that run pip. Not `ran("pip")`: a random temp folder name can hold "pip"."""
        return [cmd for cmd in self.calls
                if Path(cmd[0]).name.startswith("pip") or cmd[1:3] == ["-m", "pip"]]


def installed(version):
    """Respond as a venv whose installed daemon is `version`."""
    def respond(cmd):
        if "importlib.metadata" in " ".join(cmd):
            return (0, version + "\n") if version else (1, "")
        return 0, ""
    return respond


class LaunchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()

    def installer(self, runner, platform=None, retired=True, fake_venv=True):
        installer = Installer(
            home=self.home,
            launch_agents_dir=self.home / "LaunchAgents",
            startup_dir=self.home / "startup",
            systemd_user_dir=self.home / "systemd",
            runner=runner,
            platform=platform or sys.platform,
            repo_root=DAEMON.parent,
            out=lambda _line: None,
        )
        if retired:
            marker = installer.gsd_home / RETIRED_MARKER
            marker.parent.mkdir(parents=True)
            marker.write_text("done\n")
        if fake_venv:
            installer.venv_python.parent.mkdir(parents=True)
            installer.venv_python.write_text("")
            installer.venv_pip.write_text("")
        return installer

    def spawn(self, argv, port):
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                   PYTHONPATH=str(DAEMON))
        process = subprocess.Popen(argv + [str(port)], env=env,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(lambda: (process.poll() is None and process.kill(), process.wait()))
        deadline = time.monotonic() + 30
        while probe_port(port)["state"] == "free":
            self.assertLess(time.monotonic(), deadline, "server did not start")
            self.assertIsNone(process.poll(), "server exited early")
            time.sleep(0.1)
        return process

    def serve_in_thread(self, handler=None):
        if handler is None:
            server = serve(Watcher(Config(parents=[self.tmp.name], history=False)), port=0)
            self.addCleanup(server.watcher_stop.set)
        else:
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server.server_address[1]


class ProbeTests(LaunchCase):
    def test_program_name_is_the_base_name_also_for_a_path_with_a_space(self):
        answers = {"darwin": "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome\n",
                   "linux": "node\n", "win32": "node\r\n"}
        names = {platform: launch_module.process_name(
                     7, self.installer(ScriptRunner(lambda cmd, out=out: (0, out)), platform=platform, retired=False, fake_venv=False))
                 for platform, out in answers.items()}
        self.assertEqual(names, {"darwin": "Google Chrome", "linux": "node", "win32": "node"})

    def test_free_port(self):
        self.assertEqual(probe_port(free_port()), {"state": "free"})

    def test_gsd_daemon_reports_version_and_pid(self):
        port = self.serve_in_thread()
        self.assertEqual(probe_port(port),
                         {"state": "daemon", "version": __version__, "pid": os.getpid()})

    def test_other_http_service(self):
        port = self.serve_in_thread(SimpleHTTPRequestHandler)
        self.assertEqual(probe_port(port), {"state": "other"})


class RunningDaemonTests(LaunchCase):
    def test_same_version_daemon_is_reused(self):
        runner = ScriptRunner(installed(__version__))
        port = self.serve_in_thread()
        result = launch(port, self.installer(runner))
        self.assertEqual(result["action"], "reuse")
        self.assertEqual(result["problems"], [])
        self.assertEqual(runner.pip_runs(), [])

    def test_newer_running_daemon_is_reused_over_older_bundle(self):
        runner = ScriptRunner(installed("0.0.9"))
        port = self.serve_in_thread()
        with mock.patch.object(launch_module, "__version__", "0.0.9"):
            result = launch(port, self.installer(runner))
        self.assertEqual((result["action"], result["version"]), ("reuse", __version__))

    @UNIX_ONLY
    def test_older_daemon_process_is_stopped_then_started(self):
        port = free_port()
        old = self.spawn([sys.executable, "-m", "gsd_daemon", "serve", "--port"], port)
        runner = ScriptRunner(installed("9.0.0"), real=("ps", "lsof", "ss"))
        with mock.patch.object(launch_module, "__version__", "9.0.0"):
            result = launch(port, self.installer(runner))
        self.assertEqual(result["action"], "start", result["problems"])
        self.assertEqual(result["serve_argv"][-3:], ["--port", str(port), "--require-token"])
        self.assertEqual(result["replaced"], __version__)
        self.assertIsNotNone(old.wait(timeout=5))
        self.assertEqual(probe_port(port), {"state": "free"})

    @UNIX_ONLY
    def test_impostor_with_daemon_schema_is_never_stopped(self):
        port = free_port()
        impostor = self.spawn([sys.executable, "-c", IMPOSTOR], port)
        runner = ScriptRunner(installed(__version__), real=("ps", "lsof", "ss"))
        result = launch(port, self.installer(runner))
        self.assertEqual(result["action"], "setup")
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("port", True)])
        detail = result["problems"][0]["detail"]
        self.assertEqual(detail["owner"], "daemon")  # it answers as a daemon, so the app shows its fix text
        self.assertEqual(detail["pid"], impostor.pid)
        self.assertNotIn("/", detail["name"])  # the program's name, not its path or arguments
        self.assertIn("python", detail["name"].lower())
        self.assertNotIn("command", detail)  # a command line can hold secrets; the app gets only the name
        self.assertIsNone(impostor.poll())

    def test_other_service_on_port_blocks_without_install(self):
        runner = ScriptRunner(installed(None))
        port = self.serve_in_thread(SimpleHTTPRequestHandler)
        result = launch(port, self.installer(runner, fake_venv=False))
        self.assertEqual(result["action"], "setup")
        self.assertEqual([p["kind"] for p in result["problems"]], ["port"])
        self.assertEqual(result["problems"][0]["detail"]["owner"], "other")
        self.assertEqual([cmd for cmd in runner.calls if cmd[1:3] == ["-m", "venv"]], [])

    def test_free_port_starts_daemon(self):
        runner = ScriptRunner(installed(__version__))
        installer = self.installer(runner)
        port = free_port()
        result = launch(port, installer)
        self.assertEqual(result["action"], "start")
        self.assertEqual(result["serve_argv"],
                         [str(installer.venv_python), "-m", "gsd_daemon", "serve", "--port", str(port),
                          "--require-token"])
        self.assertIsNone(result["replaced"])
        self.assertEqual(result["legacy"], [])


class VenvTests(LaunchCase):
    def test_newer_installed_daemon_is_never_downgraded(self):
        runner = ScriptRunner(installed("99.0.0"))
        self.assertEqual(ensure_venv(self.installer(runner)), "99.0.0")
        self.assertEqual(runner.pip_runs(), [])
        self.assertEqual([cmd for cmd in runner.calls if cmd[1:3] == ["-m", "venv"]], [])

    def test_older_installed_daemon_is_upgraded_from_a_copy_of_the_bundle(self):
        seen = []

        def respond(cmd):
            if "pip" in Path(cmd[0]).name and cmd[1:3] == ["install", "--upgrade"]:
                target = Path(cmd[-1])
                seen.append((target, sorted(p.name for p in target.iterdir()),
                             (target / "gsd_daemon" / "launch.py").is_file()))
            return installed("0.0.1")(cmd)
        installer = self.installer(ScriptRunner(respond))
        self.assertEqual(ensure_venv(installer), __version__)
        self.assertEqual(len(seen), 1)
        target, names, has_code = seen[0]
        # pip builds in place, so it must get a copy, never the (read-only) app bundle.
        self.assertNotEqual(target.resolve(), DAEMON.resolve())
        self.assertEqual(names, ["README.md", "gsd_daemon", "pyproject.toml"])
        self.assertTrue(has_code)
        self.assertFalse(target.exists(), "the build copy was not removed")
        self.assertEqual(installer.package_dir, DAEMON)

    def test_build_copy_of_a_bundle_without_write_bits_is_writable(self):
        bundle = Path(self.tmp.name) / "bundle"
        shutil.copytree(DAEMON, bundle / "daemon", ignore=shutil.ignore_patterns("__pycache__"))
        paths = [bundle / "daemon", *(bundle / "daemon").rglob("*")]
        for path in paths:
            path.chmod(path.stat().st_mode & ~0o222)
        self.addCleanup(lambda: [path.chmod(0o755) for path in paths])
        locked = []

        def respond(cmd):
            if "pip" in Path(cmd[0]).name and cmd[1:3] == ["install", "--upgrade"]:
                target = Path(cmd[-1])
                # pip must be able to delete its own copy of this tree.
                locked.extend(p for p in [target, *target.rglob("*")]
                              if not p.stat().st_mode & stat.S_IWUSR)
                locked.append(None)
            return installed(None)(cmd)
        installer = self.installer(ScriptRunner(respond))
        installer.repo_root = bundle
        self.assertEqual(ensure_venv(installer), __version__)
        self.assertEqual(locked, [None])

    @unittest.skipIf(sys.platform == "win32", "Windows venvs copy their launcher on every run")
    def test_venv_made_by_another_python_is_rebuilt_for_this_python(self):
        # Field case: a venv made by Xcode 3.9, upgraded by a launch that found python.org 3.14.
        other = Path(self.tmp.name) / "other" / "python3"
        other.parent.mkdir()
        other.write_text("")
        installer = self.installer(ScriptRunner(), fake_venv=False)
        bin_dir = installer.venv_python.parent
        bin_dir.mkdir(parents=True)
        (bin_dir / "python3").symlink_to(other)
        (bin_dir / "python").symlink_to("python3")

        def respond(cmd):
            if cmd[1:3] == ["-m", "venv"]:
                subprocess.run(cmd + ["--without-pip"], check=True, capture_output=True)
                return 0, ""
            return installed("0.0.1")(cmd)
        installer.runner = ScriptRunner(respond)
        self.assertEqual(ensure_venv(installer), __version__)
        minor = bin_dir / f"python3.{sys.version_info[1]}"
        self.assertEqual({os.path.realpath(bin_dir / name) for name in ("python", "python3", minor)},
                         {os.path.realpath(minor)})
        self.assertNotEqual(os.path.realpath(installer.venv_python), os.path.realpath(other))
        # A venv this Python made is upgraded in place, not rebuilt.
        installer.runner = runner = ScriptRunner()
        self.assertEqual(installer.install(no_tray=True, no_autostart=True), 0)
        self.assertEqual(runner.calls[0], [sys.executable, "-m", "venv", str(installer.venv_dir)])

    def test_install_failure_is_a_blocking_problem(self):
        def respond(cmd):
            return (1, "") if cmd[1:3] == ["install", "--upgrade"] else installed(None)(cmd)
        result = launch(free_port(), self.installer(ScriptRunner(respond)))
        self.assertEqual(result["action"], "setup")
        self.assertEqual([p["kind"] for p in result["problems"]], ["install"])
        self.assertIn("network is down", result["problems"][0]["fix"])

    def test_install_that_returns_an_error_code_is_a_blocking_problem(self):
        runner = ScriptRunner(installed(None))
        result = launch(free_port(), self.installer(runner, platform="freebsd"))
        self.assertEqual((result["action"], result["serve_argv"]), ("setup", None))
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("install", True)])


class PrerequisiteTests(LaunchCase):
    def test_missing_git_blocks(self):
        runner = ScriptRunner(installed(__version__), which={})
        result = launch(free_port(), self.installer(runner))
        self.assertEqual(result["action"], "setup")
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("git", True)])
        self.assertEqual(runner.pip_runs(), [])


class RequirementTests(LaunchCase):
    """`requirements` in the launch result feeds the app's Requirements step."""

    def rows(self, runner, platform="darwin"):
        if not hasattr(self, "shared"):
            self.shared = self.installer(runner)
        self.shared.runner, self.shared.platform = runner, platform
        result = launch(free_port(), self.shared)
        self.assertNotIn("gho_secret", json.dumps(result))
        return {row["id"]: row for row in result["requirements"]}

    def respond(self, gh_auth=0, venv=0, git=0):
        def respond(cmd):
            line = " ".join(cmd)
            if cmd[1:] == ["--version"] and Path(cmd[0]).name == "git":
                return git, "git version 2.39.5 (Apple Git-154)\n"
            if cmd[1:3] == ["auth", "token"]:
                return gh_auth, "gho_secret\n"
            if "ensurepip" in line:
                return venv, ""
            return installed(__version__)(cmd)
        return respond

    def test_python_and_git_report_their_versions(self):
        rows = self.rows(ScriptRunner(self.respond()))
        self.assertEqual(rows["python"], {
            "id": "python", "required": True, "state": "ready",
            "detail": ".".join(str(part) for part in sys.version_info[:3])})
        self.assertEqual(rows["git"]["state"], "ready")
        self.assertEqual(rows["git"]["detail"], "2.39.5 (Apple Git-154)")

    def test_missing_git_is_a_missing_required_row(self):
        rows = self.rows(ScriptRunner(self.respond(), which={}))
        self.assertEqual((rows["git"]["state"], rows["git"]["required"]), ("missing", True))

    def test_git_that_cannot_run_is_missing_and_blocks(self):
        # macOS without the Command Line Tools: /usr/bin/git exists but exits non-zero.
        result = launch(free_port(), self.installer(ScriptRunner(self.respond(git=1)), platform="darwin"))
        git = [row for row in result["requirements"] if row["id"] == "git"]
        self.assertEqual(git, [{"id": "git", "required": True, "state": "missing", "detail": None}])
        self.assertEqual(result["action"], "setup")
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("git", True)])
        self.assertIn("xcode-select --install", result["problems"][0]["fix"])

    def test_github_cli_states(self):
        which = {"git": "/usr/bin/git", "gh": "/usr/bin/gh"}
        rows = self.rows(ScriptRunner(self.respond(), which=which))
        self.assertEqual(rows["gh"], {"id": "gh", "required": False, "state": "ready", "detail": None})
        rows = self.rows(ScriptRunner(self.respond(gh_auth=1), which=which))
        self.assertEqual((rows["gh"]["state"], rows["gh"]["required"]), ("signed-out", False))
        rows = self.rows(ScriptRunner(self.respond()))
        self.assertEqual((rows["gh"]["state"], rows["gh"]["detail"]), ("missing", None))

    def test_missing_venv_module_blocks_before_the_install(self):
        runner = ScriptRunner(self.respond(venv=1))
        result = launch(free_port(), self.installer(runner, platform="linux", fake_venv=False))
        rows = {row["id"]: row for row in result["requirements"]}
        self.assertEqual((rows["python-venv"]["state"], rows["python-venv"]["required"]), ("missing", True))
        self.assertEqual(result["action"], "setup")
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("python-venv", True)])
        self.assertIn("sudo apt install python3-venv", result["problems"][0]["fix"])
        self.assertEqual([cmd for cmd in runner.calls if cmd[1:3] == ["-m", "venv"]], [])

    def test_venv_left_without_pip_still_gets_the_venv_module_check(self):
        # A failed `python -m venv` leaves the interpreter but no pip.
        installer = self.installer(ScriptRunner(self.respond(venv=1)), platform="linux")
        installer.venv_pip.unlink()
        result = launch(free_port(), installer)
        self.assertEqual(result["action"], "setup")
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("python-venv", True)])

    def test_existing_venv_skips_the_venv_module_check(self):
        runner = ScriptRunner(self.respond(venv=1))
        result = launch(free_port(), self.installer(runner, platform="linux"))
        rows = {row["id"]: row for row in result["requirements"]}
        self.assertEqual(rows["python-venv"]["state"], "ready")
        self.assertEqual(result["action"], "start")
        self.assertEqual(result["problems"], [])
        self.assertEqual(runner.ran("ensurepip"), [])

    def test_venv_module_row_is_linux_only(self):
        self.assertNotIn("python-venv", self.rows(ScriptRunner(self.respond())))
        rows = self.rows(ScriptRunner(self.respond()), platform="linux")
        self.assertEqual((rows["python-venv"]["state"], rows["python-venv"]["required"]), ("ready", True))


class LegacyAutostartTests(LaunchCase):
    def darwin(self, still_loaded, login_items="Finder"):
        state = {"uninstalled": False}

        def respond(cmd):
            if cmd[:2] == ["launchctl", "bootout"]:
                state["uninstalled"] = True
            if cmd[:2] == ["launchctl", "print"]:
                return (0, "") if (still_loaded or not state["uninstalled"]) else (113, "")
            if cmd[0] == "osascript" and "get the name" in cmd[-1]:
                return 0, login_items
            return installed(__version__)(cmd)
        return ScriptRunner(respond)

    @NEEDS_UID
    def test_uninstall_is_rechecked_and_remaining_entry_is_reported(self):
        runner = self.darwin(still_loaded=True)
        installer = self.installer(runner, platform="darwin", retired=False)
        installer.plist_path.parent.mkdir(parents=True)
        installer.plist_path.write_text("<plist/>")
        result = launch(free_port(), installer)
        self.assertTrue(runner.ran("bootout"), "uninstall did not run")
        self.assertFalse(installer.plist_path.exists())
        self.assertEqual(result["action"], "start")
        self.assertFalse(result["autostart_ok"])
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]],
                         [("autostart", False)])
        self.assertEqual(result["legacy"], [
            {"name": "launch-agent", "removed": False, "fix": result["problems"][0]["fix"]}])
        self.assertFalse((installer.gsd_home / RETIRED_MARKER).exists())

    @NEEDS_UID
    def test_verified_cleanup_writes_marker_and_later_launch_skips_checks(self):
        runner = self.darwin(still_loaded=False, login_items="Finder, GSDPathTray")
        installer = self.installer(runner, platform="darwin", retired=False)
        first = launch(free_port(), installer)
        self.assertTrue(runner.ran("delete login item"), "login item was not removed")
        # The fake still lists the login item after removal, so it remains.
        self.assertEqual([p["kind"] for p in first["problems"]], ["autostart"])

        clean = self.darwin(still_loaded=False)
        installer.runner = clean
        second = launch(free_port(), installer)
        self.assertTrue(second["autostart_ok"])
        self.assertTrue((installer.gsd_home / RETIRED_MARKER).exists())

        skipped = self.darwin(still_loaded=True)
        installer.runner = skipped
        third = launch(free_port(), installer)
        self.assertTrue(third["autostart_ok"])
        self.assertEqual(skipped.ran("launchctl"), [])

    @NEEDS_UID
    def test_login_item_is_not_checked_without_a_previous_install(self):
        runner = self.darwin(still_loaded=False)
        installer = self.installer(runner, platform="darwin", retired=False, fake_venv=False)
        launch_module.retire_legacy(installer)
        self.assertTrue(runner.ran("bootout"), "uninstall did not run")
        self.assertEqual(runner.ran("get the name"), [])

    def test_failed_uninstall_on_linux_without_systemctl_does_not_block(self):
        def respond(cmd):
            if cmd[0] == "systemctl":
                raise FileNotFoundError(2, "No such file or directory", "systemctl")
            return installed(__version__)(cmd)
        installer = self.installer(ScriptRunner(respond), platform="linux", retired=False)
        installer.unit_path.parent.mkdir(parents=True)
        installer.unit_path.write_text("[Unit]\n")
        result = launch(free_port(), installer)
        self.assertEqual(result["action"], "start")
        self.assertFalse(result["autostart_ok"])
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("autostart", False)])
        self.assertIn(str(installer.unit_path), result["problems"][0]["fix"])
        self.assertFalse((installer.gsd_home / RETIRED_MARKER).exists())

    def test_error_with_no_registration_to_name_is_a_blocking_launch_problem(self):
        installer = self.installer(ScriptRunner(installed(__version__)), platform="win32", retired=False)
        # The marker directory cannot be made: a file is in its place.
        (installer.gsd_home / RETIRED_MARKER).parent.write_text("")
        result = launch(free_port(), installer)
        self.assertEqual((result["action"], result["serve_argv"]), ("setup", None))
        self.assertEqual([(p["kind"], p["blocking"]) for p in result["problems"]], [("launch", True)])

    def test_windows_startup_shortcut_is_removed(self):
        runner = ScriptRunner(installed(__version__))
        installer = self.installer(runner, platform="win32", retired=False)
        installer.shortcut_path.parent.mkdir(parents=True)
        installer.shortcut_path.write_text("lnk")
        result = launch(free_port(), installer)
        self.assertFalse(installer.shortcut_path.exists())
        self.assertEqual([(row["name"], row["removed"]) for row in result["legacy"]], [("startup-shortcut", True)])
        self.assertTrue(result["autostart_ok"])
        # The next launch has nothing to report.
        self.assertEqual(launch(free_port(), installer)["legacy"], [])


class CliTests(LaunchCase):
    def test_launch_command_prints_json(self):
        marker = self.home / ".gsd-path" / RETIRED_MARKER
        marker.parent.mkdir(parents=True)
        marker.write_text("done\n")
        port = self.serve_in_thread(SimpleHTTPRequestHandler)
        env = dict(os.environ, HOME=str(self.home), USERPROFILE=str(self.home),
                   PYTHONPATH=str(DAEMON))
        output = subprocess.run([sys.executable, "-m", "gsd_daemon", "launch", "--port", str(port)],
                                env=env, capture_output=True, text=True, check=True).stdout
        result = json.loads(output)
        self.assertEqual((result["action"], result["port"]), ("setup", port))
        self.assertEqual([p["kind"] for p in result["problems"]], ["port"])


if __name__ == "__main__":
    unittest.main()
