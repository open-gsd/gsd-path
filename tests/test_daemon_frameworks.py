import http.client
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.config import Config
from gsd_daemon.frameworks import Frameworks
from gsd_daemon.serve import serve
from gsd_daemon.watcher import Watcher
from tests._platform import posix_only, requires_symlink


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class FrameworksTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name).resolve()
        self.bin = self.home / "node" / "bin"
        self.calls = []
        self.answers = {}

    def install(self, name: str, command: str, version: str) -> None:
        """A global npm install: <prefix>/lib/node_modules/<package> and a command linked into <prefix>/bin."""
        package = self.home / "node" / "lib" / "node_modules" / "@opengsd" / name
        write(package / "package.json", json.dumps({"name": f"@opengsd/{name}", "version": version}))
        target = write(package / "dist" / "cli.js", "#!/usr/bin/env node\n")
        target.chmod(0o755)  # npm marks a package's commands executable
        self.bin.mkdir(parents=True, exist_ok=True)
        (self.bin / command).symlink_to(target)

    def frameworks(self, env=None, fetch=None) -> Frameworks:
        def runner(argv, env):
            self.calls.append((list(argv), env["PATH"]))
            return self.answers.get(Path(argv[0]).name, (0, "done\n", ""))
        for tool in ("npm", "npx"):
            write(self.bin / tool, "#!/bin/sh\n").chmod(0o755)
        return Frameworks(home=self.home, runner=runner, fetch=fetch or self.fetch,
                          env={"PATH": str(self.bin), **(env or {})}, extra_dirs=[])

    def fetch(self, url: str) -> bytes:
        latest = {"@opengsd%2Fgsd-pi": "1.22.0", "@opengsd%2Fgsd-core": "1.17.0"}
        return json.dumps({"version": next(v for k, v in latest.items() if k in url)}).encode()

    @posix_only
    @requires_symlink
    def test_installed_versions_come_from_the_package_and_each_host(self) -> None:
        self.install("gsd-pi", "gsd", "1.21.1")
        self.install("gsd-core", "gsd-core", "1.11.0")
        write(self.home / ".claude" / "gsd-core" / "VERSION", "1.13.0\n")
        write(self.home / ".config" / "agents" / "gsd-core" / "VERSION", "1.6.0\n")  # kimi: first probe found
        codex = write(self.home / "elsewhere" / "gsd-core" / "VERSION", "1.3.1\n").parent.parent
        write(self.home / ".codex" / "gsd-core" / "VERSION", "0.1.0\n")  # ignored: CODEX_HOME wins
        write(self.home / ".cursor" / "get-shit-done" / "VERSION", "1.0.0\n")  # the old package: not gsd-core
        status = self.frameworks(env={"CODEX_HOME": str(codex)}).status()
        self.assertEqual(status["gsd-pi"]["installed"], "1.21.1")
        self.assertEqual(status["gsd-core"]["installed"], "1.11.0")
        self.assertEqual([(h["host"], h["version"]) for h in status["gsd-core"]["hosts"]],
                         [("claude", "1.13.0"), ("codex", "1.3.1"), ("kimi", "1.6.0")])
        # Latest is unknown until the user checks: no update is claimed.
        self.assertEqual((status["gsd-pi"]["latest"], status["gsd-pi"]["update_available"]), (None, False))

    @posix_only
    @requires_symlink
    def test_a_command_from_another_package_is_not_the_framework(self) -> None:
        package = self.home / "node" / "lib" / "node_modules" / "gsd"
        write(package / "package.json", json.dumps({"name": "gsd", "version": "9.0.0"}))
        self.bin.mkdir(parents=True)
        impostor = write(package / "bin.js", "#!/usr/bin/env node\n")
        impostor.chmod(0o755)
        (self.bin / "gsd").symlink_to(impostor)
        self.assertEqual(self.frameworks().status()["gsd-pi"], {
            "installed": None, "hosts": [], "latest": None, "checked": None, "update_available": False, "detected": False})

    @posix_only
    @requires_symlink
    def test_check_reads_the_registry_and_keeps_the_last_version_on_failure(self) -> None:
        self.install("gsd-pi", "gsd", "1.22.0")
        write(self.home / ".claude" / "gsd-core" / "VERSION", "1.13.0\n")
        frameworks = self.frameworks()
        self.assertEqual(frameworks.check(), {"gsd-pi": None, "gsd-core": None})
        status = frameworks.status()
        self.assertEqual((status["gsd-pi"]["latest"], status["gsd-pi"]["update_available"]), ("1.22.0", False))
        self.assertEqual((status["gsd-core"]["latest"], status["gsd-core"]["update_available"]), ("1.17.0", True))

        def offline(url):
            raise OSError("offline")
        errors = self.frameworks(fetch=offline).check()
        self.assertEqual(errors["gsd-core"], "offline")
        self.assertEqual(self.frameworks(fetch=offline).status()["gsd-core"]["latest"], "1.17.0")

    @posix_only
    @requires_symlink
    def test_update_runs_each_framework_own_update(self) -> None:
        self.install("gsd-pi", "gsd", "1.21.1")
        self.install("gsd-core", "gsd-core", "1.11.0")
        write(self.home / ".claude" / "gsd-core" / "VERSION", "1.13.0\n")
        write(self.home / ".cursor" / "gsd-core" / "VERSION", "1.6.0\n")
        notice = write(self.home / ".cache" / "gsd" / "gsd-update-check-opengsd-gsd-core.json", "{}")
        frameworks = self.frameworks()
        preview = frameworks.update("gsd-core", dry_run=True)
        self.assertEqual(self.calls, [])  # a preview runs nothing
        self.assertEqual([argv[1:] for argv in preview["commands"]], [
            ["install", "-g", "@opengsd/gsd-core@latest"],
            ["-y", "--package=@opengsd/gsd-core@latest", "--", "gsd-core", "--claude", "--global",
             "--config-dir", str(self.home / ".claude")],
            ["-y", "--package=@opengsd/gsd-core@latest", "--", "gsd-core", "--cursor", "--global",
             "--config-dir", str(self.home / ".cursor")]])
        result = frameworks.update("gsd-core")
        self.assertTrue(result["ok"], result)
        self.assertEqual([argv for argv, _ in self.calls], preview["commands"])
        self.assertTrue(all(path.split(os.pathsep)[0] == str(self.bin) for _, path in self.calls))
        self.assertFalse(notice.exists())  # gsd-core's own notice would announce the old update
        self.assertEqual(len((self.home / ".gsd-path" / "frameworks.log").read_text().splitlines()), 3)

        self.calls.clear()
        self.assertTrue(frameworks.update("gsd-pi")["ok"])
        self.assertEqual([argv for argv, _ in self.calls], [[str(self.bin / "gsd"), "update"]])

    @posix_only
    @requires_symlink
    def test_a_failed_command_stops_the_update(self) -> None:
        self.install("gsd-core", "gsd-core", "1.11.0")
        write(self.home / ".claude" / "gsd-core" / "VERSION", "1.13.0\n")
        notice = write(self.home / ".cache" / "gsd" / "gsd-update-check-opengsd-gsd-core.json", "{}")
        self.answers["npm"] = (1, "", "EACCES: permission denied\n")
        result = self.frameworks().update("gsd-core")
        self.assertEqual((result["ok"], result["error"]), (False, "EACCES: permission denied"))
        self.assertEqual(len(self.calls), 1)  # the host install did not run
        self.assertTrue(notice.exists())

    @posix_only
    @requires_symlink
    def test_gsd_core_updates_with_the_npm_of_its_own_prefix(self) -> None:
        self.install("gsd-core", "gsd-core", "1.11.0")
        write(self.home / ".claude" / "gsd-core" / "VERSION", "1.13.0\n")
        brew = self.home / "brew" / "bin"
        for tool in ("npm", "npx"):
            write(brew / tool, "#!/bin/sh\n").chmod(0o755)
        frameworks = self.frameworks(env={"PATH": os.pathsep.join([str(brew), str(self.bin)])})
        commands = frameworks.update("gsd-core", dry_run=True)["commands"]
        self.assertEqual([argv[0] for argv in commands], [str(self.bin / "npm"), str(self.bin / "npx")])

        (self.bin / "npm").unlink()  # no npm next to the command: the search path decides
        self.assertEqual(frameworks.update("gsd-core", dry_run=True)["commands"][0][0], str(brew / "npm"))

    def test_nothing_to_update_is_refused(self) -> None:
        frameworks = self.frameworks()
        for name, reason in (("gsd-pi", "not installed"), ("gsd-core", "not installed"), ("other", "gsd-pi or gsd-core")):
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, reason):
                frameworks.update(name, dry_run=True)


class FrameworkRouteTests(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        env = mock.patch.dict(os.environ, {"GSD_DAEMON_CONFIG": str(Path(tmp.name) / "daemon.json")})
        env.start()
        self.addCleanup(env.stop)
        self.frameworks = mock.Mock()
        self.frameworks.status.return_value = {"gsd-pi": {"installed": "1.21.1"}}
        self.frameworks.check.return_value = {"gsd-pi": None, "gsd-core": None}
        self.frameworks.update.return_value = {"ok": True, "commands": [["gsd", "update"]]}
        plugin = mock.Mock()
        plugin.refresh_source.return_value = {"refreshed": True, "error": None}
        plugin.check_update.return_value = {"latest": "1.4.0"}
        plugin.detect_global.return_value = {}
        plugin.releases.return_value = {}
        plugin._read_cache.return_value = {}
        watcher = Watcher(Config(parents=[], history=False, session_dirs=[]))
        with mock.patch("threading.Thread.start"):
            self.server = serve(watcher, port=0, plugin=plugin, frameworks=self.frameworks)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(method, path, body=json.dumps(body) if body is not None else None,
                     headers={"Content-Type": "application/json"} if body is not None else {})
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        return response.status, payload

    def test_status_check_and_update_routes(self) -> None:
        self.assertEqual(self.request("GET", "/api/plugin/status")[1]["frameworks"], {"gsd-pi": {"installed": "1.21.1"}})
        code, payload = self.request("POST", "/api/plugin/check", {})
        self.assertEqual((code, payload["framework_errors"]), (200, {"gsd-pi": None, "gsd-core": None}))
        code, payload = self.request("POST", "/api/frameworks/update", {"name": "gsd-pi", "dry_run": True})
        self.assertEqual((code, payload["commands"]), (200, [["gsd", "update"]]))
        self.frameworks.update.assert_called_with("gsd-pi", dry_run=True)
        self.frameworks.update.side_effect = ValueError("name must be gsd-pi or gsd-core")
        code, payload = self.request("POST", "/api/frameworks/update", {"name": "other"})
        self.assertEqual((code, payload["error"]), (400, "name must be gsd-pi or gsd-core"))


if __name__ == "__main__":
    unittest.main()
