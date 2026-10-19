"""Skills come from the verified npm release tarball, not from a clone of main."""
import base64
import hashlib
import http.client
import io
import json
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import frameworks, release_source
from gsd_daemon.config import Config
from gsd_daemon.plugin import PluginManager
from gsd_daemon.serve import serve_in_thread
from gsd_daemon.watcher import Watcher
from gsd_daemon.release_source import ReleaseError


def tarball(version, extra=None, links=()):
    """A package tarball the way npm packs one: every path under package/."""
    files = {"package/package.json": json.dumps({"version": version}),
             "package/scripts/install.py": f"print('installer {version}')\n",
             "package/AGENTS.md": "# agents template\n"}
    files.update(extra or {})
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        for name, text in files.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        for name, target in links:
            info = tarfile.TarInfo(name)
            info.type = tarfile.SYMTYPE
            info.linkname = target
            archive.addfile(info)
    return buffer.getvalue()


def integrity(data):
    return "sha512-" + base64.b64encode(hashlib.sha512(data).digest()).decode("ascii")


@unittest.skipUnless(shutil.which("openssl"), "needs the openssl CLI to make a test certificate")
class TlsTests(unittest.TestCase):
    """A python.org macOS build without "Install Certificates" has no CA file or path."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        # A throwaway self-signed certificate for 127.0.0.1, made per run so no
        # key lives in the repo. It plays both the registry's certificate and
        # the only root in a stand-in macOS system bundle.
        self.bundle = root / "cert.pem"
        subprocess.run(
            ["openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1",
             "-nodes", "-days", "1", "-subj", "/CN=gsd-path test registry",
             "-addext", "subjectAltName=IP:127.0.0.1",
             "-keyout", str(root / "key.pem"), "-out", str(self.bundle)],
            check=True, capture_output=True)

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok": true}')

            def log_message(self, *args):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.bundle, root / "key.pem")
        server.socket = context.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f"https://127.0.0.1:{server.server_address[1]}/"

    def paths(self, cafile):
        return ssl.DefaultVerifyPaths(cafile, None, "SSL_CERT_FILE", "", "SSL_CERT_DIR", "")

    def test_no_ca_certificates_falls_back_to_the_system_bundle(self):
        with mock.patch.object(release_source, "SYSTEM_CA_FILE", str(self.bundle)), \
                mock.patch("ssl.get_default_verify_paths", return_value=self.paths(None)):
            self.assertEqual(release_source.default_fetch(self.url), b'{"ok": true}')
            # The framework version check reads the same registry.
            self.assertEqual(frameworks._fetch(self.url), b'{"ok": true}')

    def test_python_with_its_own_ca_file_does_not_trust_the_system_bundle(self):
        # Verification stays on: a cert only the fallback bundle trusts is refused.
        with mock.patch.object(release_source, "SYSTEM_CA_FILE", str(self.bundle)), \
                mock.patch("ssl.get_default_verify_paths", return_value=self.paths("/elsewhere.pem")), \
                self.assertRaises(OSError) as raised:
            release_source.default_fetch(self.url)
        self.assertIn("CERTIFICATE_VERIFY_FAILED", str(raised.exception))


class Registry:
    """Serves an index and tarballs; records every URL asked for."""

    def __init__(self, versions, latest, corrupt=()):
        self.calls = []
        self.down = False
        self.tarballs = {v: tarball(v) for v in versions}
        self.index = {"dist-tags": {"latest": latest}, "versions": {
            v: {"dist": {"tarball": f"https://registry.npmjs.org/@opengsd/gsd-path/-/gsd-path-{v}.tgz",
                         "integrity": integrity(data)}}
            for v, data in self.tarballs.items()}}
        for version in corrupt:
            self.tarballs[version] = tarball(version, {"package/evil.py": "print('swapped')\n"})

    def __call__(self, url):
        self.calls.append(url)
        if self.down:
            raise OSError("network is down")
        if url == release_source.REGISTRY_URL:
            return json.dumps(self.index).encode("utf-8")
        return self.tarballs[url.rsplit("-", 1)[1][:-len(".tgz")]]


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "user").mkdir()
        self.runs = []

    def manager(self, registry, clock=lambda: 1_000_000.0):
        def runner(argv, cwd=None):
            self.runs.append([str(part) for part in argv])
            return 0, "ok", ""
        return PluginManager(home=self.root / "home", user_home=self.root / "user", runner=runner,
                             environ={}, out=lambda line: None, clock=clock, fetch=registry)


class UnpackTests(Case):
    def test_wrong_hash_is_refused_and_nothing_is_written(self):
        data = tarball("1.4.0")
        with self.assertRaises(ReleaseError):
            release_source.install_release(self.root / "releases", "1.4.0",
                                           {"tarball": "https://x/y-1.4.0.tgz", "integrity": integrity(b"other")},
                                           lambda url: data)
        self.assertFalse((self.root / "releases" / "1.4.0").exists())

    def test_only_sha512_integrity_is_accepted(self):
        data = tarball("1.4.0")
        weak = "sha1-" + base64.b64encode(hashlib.sha1(data).digest()).decode("ascii")
        for value in (weak, "", None):
            with self.subTest(integrity=value), self.assertRaises(ReleaseError):
                release_source.install_release(self.root / "releases", "1.4.0",
                                               {"tarball": "https://x/y-1.4.0.tgz", "integrity": value},
                                               lambda url: data)

    def test_paths_outside_the_package_and_links_are_refused(self):
        for bad in (tarball("1.4.0", {"package/../../escape.py": "x"}),
                    tarball("1.4.0", {"other/file.py": "x"}),
                    tarball("1.4.0", links=[("package/link", "/etc/passwd")])):
            with self.subTest(), self.assertRaises(ReleaseError):
                release_source.install_release(self.root / "releases", "1.4.0",
                                               {"tarball": "https://x/y-1.4.0.tgz", "integrity": integrity(bad)},
                                               lambda url, bad=bad: bad)
            self.assertFalse((self.root / "releases" / "1.4.0").exists())
            self.assertFalse((self.root / "escape.py").exists())

    def test_plain_http_tarball_is_refused_before_any_download(self):
        calls = []
        with self.assertRaises(ReleaseError):
            release_source.install_release(self.root / "releases", "1.4.0",
                                           {"tarball": "http://x/y-1.4.0.tgz", "integrity": integrity(b"")},
                                           lambda url: calls.append(url) or b"")
        self.assertEqual(calls, [])

    def test_a_release_unpacked_by_another_process_meanwhile_is_used(self):
        data = tarball("1.4.0")
        dest = self.root / "releases" / "1.4.0"

        def fetch(url):  # the other process finishes while this one downloads
            (dest / "scripts").mkdir(parents=True)
            (dest / "scripts" / "install.py").write_text("print('other')\n", encoding="utf-8")
            return data

        entry = {"tarball": "https://x/y-1.4.0.tgz", "integrity": integrity(data)}
        self.assertEqual(release_source.install_release(self.root / "releases", "1.4.0", entry, fetch), dest)
        self.assertEqual([path.name for path in (self.root / "releases").iterdir()], ["1.4.0"])


class ManagerTests(Case):
    def test_install_runs_the_installer_of_the_latest_verified_release(self):
        registry = Registry(["1.3.2", "1.4.0"], latest="1.4.0")
        manager = self.manager(registry)
        result = manager.install_global(["claude"])
        self.assertTrue(result["ok"], result)
        installer = self.root / "home" / "releases" / "1.4.0" / "scripts" / "install.py"
        self.assertEqual(self.runs, [[sys.executable, str(installer), "--claude"]])
        self.assertEqual(installer.read_text(encoding="utf-8"), "print('installer 1.4.0')\n")
        self.assertEqual(manager.src_version(), "1.4.0")
        self.assertFalse((self.root / "home" / "src").exists())  # no clone of main

    def test_swapped_tarball_fails_the_install_and_runs_nothing(self):
        manager = self.manager(Registry(["1.4.0"], latest="1.4.0", corrupt=["1.4.0"]))
        result = manager.install_global(["claude"])
        self.assertFalse(result["ok"])
        self.assertIn("sha512", result["error"])
        self.assertEqual(self.runs, [])
        self.assertFalse((self.root / "home" / "releases" / "1.4.0").exists())

    def test_refresh_reports_latest_and_the_release_list_newest_first(self):
        manager = self.manager(Registry(["1.3.2", "1.10.0", "1.4.0", "2.0.0-beta.1"], latest="1.10.0"))
        self.assertEqual(manager.refresh_source(ttl_hours=0),
                         {"refreshed": True, "latest": "1.10.0", "error": None})
        self.assertEqual(manager.releases(), {"source": "npm", "latest": "1.10.0", "selected": None,
                                              "versions": ["1.10.0", "1.4.0", "1.3.2"]})

    def test_offline_refresh_keeps_the_cached_state(self):
        registry = Registry(["1.4.0"], latest="1.4.0")
        manager = self.manager(registry)
        manager.refresh_source(ttl_hours=0)
        registry.down = True
        result = manager.refresh_source(ttl_hours=0)
        self.assertEqual((result["refreshed"], result["latest"]), (False, "1.4.0"))
        self.assertIn("network is down", result["error"])
        self.assertTrue(manager.install_global(["claude"])["ok"])  # the unpacked release still works

    def test_refresh_within_the_ttl_does_not_ask_the_registry(self):
        registry = Registry(["1.4.0"], latest="1.4.0")
        manager = self.manager(registry)
        manager.refresh_source()
        asked = len(registry.calls)
        manager.refresh_source()
        self.assertEqual(len(registry.calls), asked)

    def test_a_chosen_release_is_used_until_it_is_cleared(self):
        registry = Registry(["1.3.2", "1.4.0"], latest="1.4.0")
        manager = self.manager(registry)
        manager.select_release("1.3.2")
        manager.install_global(["claude"])
        self.assertIn(str(Path("releases") / "1.3.2"), self.runs[-1][1])
        self.assertEqual(manager.releases()["selected"], "1.3.2")
        manager.refresh_source(ttl_hours=0)  # a refresh does not undo the choice
        self.assertEqual(manager.src_version(), "1.3.2")
        manager.select_release(None)
        manager.install_global(["claude"])
        self.assertIn(str(Path("releases") / "1.4.0"), self.runs[-1][1])

    def test_an_unpublished_release_cannot_be_chosen(self):
        manager = self.manager(Registry(["1.4.0"], latest="1.4.0"))
        with self.assertRaises(ValueError):
            manager.select_release("9.9.9")
        self.assertIsNone(manager.releases()["selected"])

    def test_a_prerelease_cannot_be_chosen(self):
        manager = self.manager(Registry(["1.4.0", "2.0.0-beta.1"], latest="1.4.0"))
        with self.assertRaises(ValueError):
            manager.select_release("2.0.0-beta.1")
        self.assertIsNone(manager.releases()["selected"])
        self.assertFalse((self.root / "home" / "releases" / "2.0.0-beta.1").exists())

    def test_a_chosen_release_that_was_unpublished_fails_and_stays_chosen(self):
        registry = Registry(["1.3.2", "1.4.0"], latest="1.4.0")
        manager = self.manager(registry)
        manager.select_release("1.3.2")
        del registry.index["versions"]["1.3.2"]
        result = manager.refresh_source(ttl_hours=0)
        self.assertFalse(result["refreshed"])
        self.assertIn("1.3.2", result["error"])
        self.assertIn("follow the latest release", result["error"])
        self.assertEqual(manager.releases()["selected"], "1.3.2")
        self.assertFalse((self.root / "home" / "releases" / "1.4.0").exists())
        shutil.rmtree(self.root / "home" / "releases" / "1.3.2")
        result = manager.install_global(["claude"])
        self.assertFalse(result["ok"])
        self.assertIn("1.3.2", result["error"])
        self.assertEqual(self.runs, [])

    def test_plugin_repo_keeps_the_git_clone_source(self):
        registry = Registry(["1.4.0"], latest="1.4.0")
        git = []
        manager = PluginManager(home=self.root / "home", user_home=self.root / "user",
                                runner=lambda argv, cwd=None: (0, "", ""),
                                git_runner=lambda argv, cwd=None: git.append(list(argv)) or (0, "", ""),
                                environ={}, out=lambda line: None, fetch=registry,
                                repo="https://example.invalid/fork.git")
        manager.install_global(["claude"])
        self.assertEqual(git[0][:3], ["git", "clone", "https://example.invalid/fork.git"])
        self.assertEqual(registry.calls, [])
        with self.assertRaises(ValueError):
            manager.select_release("1.4.0")
        self.assertEqual(registry.calls, [])
        self.assertFalse((self.root / "home" / "releases").exists())
        self.assertEqual(manager.releases(), {"source": "git", "latest": None, "selected": None, "versions": []})

    def test_update_available_compares_with_the_release_in_use(self):
        manager = self.manager(Registry(["1.3.2", "1.4.0"], latest="1.4.0"))
        skill = self.root / "user" / ".claude" / "skills" / "gsd-path"
        skill.mkdir(parents=True)
        (skill / "VERSION").write_text("1.3.2\n", encoding="utf-8")
        manager.refresh_source(ttl_hours=0)
        self.assertTrue(manager.check_update()["update_available"])
        manager.select_release("1.3.2")
        result = manager.check_update()
        self.assertEqual((result["latest"], result["installed"], result["update_available"]),
                         ("1.4.0", {"claude": "1.3.2"}, False))


class RouteTests(Case):
    """The Skills page reads the release list and changes the release through the daemon."""

    def setUp(self):
        super().setUp()
        self.registry = Registry(["1.3.2", "1.4.0"], latest="1.4.0")
        self.plugin = self.manager(self.registry)
        server, _ = serve_in_thread(Watcher(Config(parents=[], history=False, session_dirs=[])),
                                    port=0, plugin=self.plugin,
                                    frameworks=mock.Mock(**{"status.return_value": {}, "check.return_value": {}}))
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(server.watcher_stop.set)
        self.port = server.server_address[1]

    def request(self, method, path, body=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request(method, path, body=None if body is None else json.dumps(body),
                           headers={"Content-Type": "application/json"} if body is not None else {})
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_check_reads_the_registry_and_status_lists_the_releases(self):
        status, payload = self.request("POST", "/api/plugin/check", {})
        self.assertEqual((status, payload["ok"], payload["latest"]), (200, True, "1.4.0"))
        self.assertIn(release_source.REGISTRY_URL, self.registry.calls)
        status, payload = self.request("GET", "/api/plugin/status")
        self.assertEqual(payload["releases"], {"source": "npm", "latest": "1.4.0", "selected": None,
                                               "versions": ["1.4.0", "1.3.2"]})

    def test_check_reports_a_registry_failure(self):
        self.registry.down = True
        status, payload = self.request("POST", "/api/plugin/check", {})
        self.assertEqual((status, payload["ok"]), (200, False))
        self.assertIn("network is down", payload["error"])

    def test_release_is_chosen_and_cleared(self):
        status, payload = self.request("POST", "/api/plugin/release", {"version": "1.3.2"})
        self.assertEqual((status, payload["selected"]), (200, "1.3.2"))
        self.assertEqual(self.plugin.src_version(), "1.3.2")
        status, payload = self.request("POST", "/api/plugin/release", {"version": None})
        self.assertEqual((status, payload["selected"]), (200, None))
        self.assertEqual(self.plugin.src_version(), "1.4.0")

    def test_unpublished_or_malformed_release_is_a_bad_request(self):
        for body in ({"version": "9.9.9"}, {"version": 7}, {}):
            with self.subTest(body=body):
                status, payload = self.request("POST", "/api/plugin/release", body)
                self.assertEqual(status, 400, payload)
        self.assertIsNone(self.plugin.releases()["selected"])

    def test_release_route_refuses_the_git_source(self):
        self.plugin.git_source = True
        asked = len(self.registry.calls)
        status, payload = self.request("POST", "/api/plugin/release", {"version": "1.3.2"})
        self.assertEqual(status, 400, payload)
        self.assertEqual(len(self.registry.calls), asked)
        self.assertEqual(self.plugin.releases()["source"], "git")


if __name__ == "__main__":
    unittest.main()
