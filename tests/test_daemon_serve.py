import http.client
import io
from email.message import Message
from html.parser import HTMLParser
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.config import Config
from gsd_daemon.serve import _Handler, serve
from gsd_daemon.watcher import Watcher

STATE = """---
pipeline: gsd-path/v2
project: demo
milestone: demo-ms
phase: build
status: active
branch: gsd-path/M001
archive: null
---

# Project State

## Log
- 2026-09-01 — build — started
"""

TASK = """---
id: {task_id}
title: Task {task_id}
wave: 1
deps: []
status: {status}
files:
  - src/{task_id}.py
---

# {task_id}
"""

WAVE_REVIEW = """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full

3/3 tasks pass
"""


def make_project(root: Path) -> Path:
    project_dir = root / ".project"
    (project_dir / "tasks").mkdir(parents=True)
    (project_dir / "STATE.md").write_bytes(STATE.encode("utf-8"))
    (project_dir / "tasks" / "T001-one.md").write_bytes(
        TASK.format(task_id="T001", status="done").encode("utf-8"))
    (project_dir / "tasks" / "T002-two.md").write_bytes(
        TASK.format(task_id="T002", status="pending").encode("utf-8"))
    review_dir = project_dir / "review"
    review_dir.mkdir()
    (review_dir / "wave-1.cycle1.md").write_bytes(WAVE_REVIEW.encode("utf-8"))
    build_dir = project_dir / "build"
    build_dir.mkdir()
    (build_dir / "verify-ledger.jsonl").write_bytes(
        (json.dumps({"command": "make test", "commit": "abc1234", "result": "pass",
                    "recorded_at": "2026-09-11T12:00:00+00:00"}) + "\n").encode("utf-8"),
    )
    (build_dir / "usage.jsonl").write_bytes(
        (json.dumps({"task": "T001", "model": "kimi-k2", "family": "kimi",
                    "tokens_in": 100, "tokens_out": 50, "cost": 0.01,
                    "phase": "build"}) + "\n").encode("utf-8"),
    )
    return root


class ServeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        parent = Path(cls.tmp.name) / "work"
        parent.mkdir()
        make_project(parent / "demo")
        cls.history = Path(cls.tmp.name) / "history.jsonl"
        cls.history.write_bytes(
            (json.dumps({"type": "phase-changed", "root": str(parent / "demo"),
                        "detail": "plan -> build", "at": "2026-09-11T10:00:00+00:00"}) + "\n" +
             json.dumps({"type": "phase-changed", "root": str(parent / "other"),
                         "detail": "build -> ship", "at": "2026-09-11T10:01:00+00:00"}) + "\n").encode("utf-8"),
        )
        cls._env = mock.patch.dict("os.environ", {"GSD_DAEMON_HISTORY": str(cls.history)})
        cls._env.start()
        cls.addClassCleanup(cls._env.stop)
        watcher = Watcher(Config(parents=[str(parent)], history=False))
        cls.server = serve(watcher, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.watcher_stop.set)
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def get(self, path: str) -> tuple:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response.status, response.getheader("Content-Type"), body

    def test_health(self) -> None:
        status, content_type, body = self.get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"ok": True})

    def test_responses_are_not_cacheable(self) -> None:
        for path in ("/", "/status", "/health"):
            connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
            connection.request("GET", path)
            response = connection.getresponse()
            response.read()
            self.assertEqual(response.getheader("Cache-Control"), "no-store")
            connection.close()

    def test_status_contains_new_fields(self) -> None:
        status, content_type, body = self.get("/status")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["schema"], "gsd-path-daemon/status/v1")
        self.assertIn("generated_at", payload)
        # The app identifies and compares a running daemon by these two fields.
        from gsd_daemon import __version__
        self.assertEqual(payload["daemon"]["version"], __version__)
        self.assertEqual(payload["daemon"]["pid"], os.getpid())
        self.assertEqual(len(payload["projects"]), 1)
        project = payload["projects"][0]
        for key in ("project", "milestone", "phase", "status", "branch", "git",
                    "tasks_done", "tasks_total", "current_wave", "waves",
                    "pending_answers", "next_skill", "time_in_phase_s", "usage",
                    "reviews", "answers"):
            self.assertIn(key, project)
        self.assertEqual(project["project"], "demo")
        self.assertEqual(project["reviews"][0]["file"], "wave-1.cycle1.md")
        self.assertEqual(project["reviews"][0]["verdict"], "pass")
        self.assertEqual(project["ledger"][0]["command"], "make test")
        self.assertEqual(project["usage"]["tokens_in"], 100)
        self.assertEqual(project["answers"], [])
        self.assertIsNotNone(project["time_in_phase_s"])

    def test_activity(self) -> None:
        status, content_type, body = self.get("/activity")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        events = [event for event in payload["events"]
                  if event.get("type") == "phase-changed"
                  and event.get("root") == str(Path(self.tmp.name) / "work" / "demo")]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["detail"], "plan -> build")

    def test_dashboard_html(self) -> None:
        status, content_type, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        class PageTitle(HTMLParser):
            def __init__(self):
                super().__init__()
                self.in_title = False
                self.title = ""

            def handle_starttag(self, tag, attrs):
                if tag == "title":
                    self.in_title = True

            def handle_endtag(self, tag):
                if tag == "title":
                    self.in_title = False

            def handle_data(self, data):
                if self.in_title:
                    self.title += data

        page = PageTitle()
        page.feed(body.decode("utf-8"))
        self.assertEqual(page.title, "OpenGSD Path")

    def test_dashboard_inline_js_parses(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        status, _content_type, body = self.get("/")
        self.assertEqual(status, 200)
        scripts = re.findall(r"<script>([\s\S]*?)</script>", body.decode("utf-8"))
        self.assertEqual(len(scripts), 1)
        with tempfile.NamedTemporaryFile("wb", suffix=".js", delete=False) as handle:
            handle.write(scripts[0].encode("utf-8"))
            path = handle.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        result = subprocess.run([node, "--check", path], capture_output=True, encoding="utf-8", errors="replace")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_dashboard_sorts_idle_project_with_shipped(self) -> None:
        node = shutil.which("node")
        if not node:
            self.skipTest("node not available")
        status, _content_type, body = self.get("/")
        self.assertEqual(status, 200)
        scripts = re.findall(r"<script>([\s\S]*?)</script>", body.decode("utf-8"))
        self.assertEqual(len(scripts), 1)
        projects = [
            {"root": "/w/m-idle", "repository": "m-idle", "workflow": {"state": "idle", "label": "Not started"}},
            {"root": "/w/alpha-shipped", "repository": "alpha-shipped", "workflow": {"state": "shipped", "label": "Shipped"}},
            {"root": "/w/zeta-blocked", "repository": "zeta-blocked", "workflow": {"state": "blocked", "label": "Blocked"}},
        ]
        prelude = """
const element = () => ({dataset: {}, style: {}, innerHTML: "", open: false, addEventListener() {},
  querySelector() { return null; }, querySelectorAll() { return []; }, appendChild() {}, focus() {}});
const stage = element();
globalThis.document = Object.assign(element(), {getElementById: () => stage, documentElement: element(), body: element(), activeElement: null});
globalThis.window = Object.assign(globalThis, {scrollX: 0, scrollY: 0, scrollTo() {}, addEventListener() {}});
globalThis.location = {hash: ""};
globalThis.history = {replaceState() {}, pushState() {}};
globalThis.fetch = () => new Promise(() => {});
globalThis.setInterval = () => 0;
"""
        probe = (
            "\ndelete stage.dataset.readingKey;\nDATA = {schema: 1, generated_at: null, projects: %s};\nrender();\n"
            "const html = stage.innerHTML;\n"
            "console.log(JSON.stringify(DATA.projects.map(p => p.repository).sort((a, b) => html.indexOf(a) - html.indexOf(b))));\n"
        ) % json.dumps(projects)
        with tempfile.NamedTemporaryFile("wb", suffix=".js", delete=False) as handle:
            handle.write((prelude + scripts[0] + probe).encode("utf-8"))
            path = handle.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        result = subprocess.run([node, path], capture_output=True, encoding="utf-8", errors="replace", timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), ["zeta-blocked", "alpha-shipped", "m-idle"])

    def test_not_found(self) -> None:
        status, content_type, body = self.get("/nope")
        self.assertEqual(status, 404)


class ServeHistoryTests(unittest.TestCase):
    def test_poll_loop_records_changes_but_not_the_startup_scan(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        parent = Path(tmp.name) / "work"
        parent.mkdir()
        project = make_project(parent / "demo")
        history = Path(tmp.name) / "history.jsonl"
        env = mock.patch.dict("os.environ", {"GSD_DAEMON_HISTORY": str(history)})
        env.start()
        self.addCleanup(env.stop)
        watcher = Watcher(Config(parents=[str(parent)], poll_seconds=1, session_dirs=[]))
        server = serve(watcher, port=0)
        self.addCleanup(server.server_close)
        self.addCleanup(server.watcher_stop.set)
        deadline = time.time() + 10
        while not watcher.projects and time.time() < deadline:
            time.sleep(0.05)
        self.assertTrue(watcher.projects)
        state = project / ".project" / "STATE.md"
        # Replace atomically: a poll must never see a half-written STATE.md.
        staged = Path(tmp.name) / "STATE.md.tmp"
        staged.write_bytes(state.read_text(encoding="utf-8").replace("phase: build", "phase: ship").encode("utf-8"))
        os.utime(staged, (time.time() + 5, time.time() + 5))
        while True:
            try:
                os.replace(staged, state)
                break
            except PermissionError:
                if time.time() >= deadline:
                    raise
                time.sleep(0.05)
        while "phase-changed" not in (history.read_text(encoding="utf-8") if history.exists() else "") and time.time() < deadline:
            time.sleep(0.05)
        # Other test classes leave poll threads running that share the patched history path.
        events = [e for e in map(json.loads, history.read_text(encoding="utf-8").splitlines()) if e["root"] == str(project)]
        self.assertEqual([e["type"] for e in events], ["phase-changed"])
        self.assertEqual(events[0]["detail"], "build -> ship")


class ParentsEndpointTests(unittest.TestCase):
    def test_folder_changes_and_manual_refresh_scan_immediately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            watcher = Watcher(Config(parents=[], history=False, session_dirs=[]))
            # No periodic scan: only the HTTP actions can discover these projects.
            with mock.patch("threading.Thread.start"):
                server = serve(watcher, port=0)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            self.addCleanup(server.server_close)
            self.addCleanup(server.shutdown)
            with mock.patch.dict(os.environ, {"GSD_DAEMON_CONFIG": str(root / "config.json")}):
                def request(method, path, body=None):
                    conn = http.client.HTTPConnection(*server.server_address)
                    conn.request(method, path, json.dumps(body) if body else None,
                                 {"Content-Type": "application/json"} if body else {})
                    response = conn.getresponse()
                    data = response.read()
                    conn.close()
                    self.assertEqual(response.status, 200, data)
                    return json.loads(data)
                first = make_project(root / "first")
                request("POST", "/api/config/parents", {"action": "add", "path": str(root)})
                status = request("GET", "/status")
                self.assertEqual([p["root"] for p in status["projects"]], [str(first)])
                self.assertEqual(status["daemon"]["parents"], [str(root)])
                second = make_project(root / "second")
                request("POST", "/api/refresh")
                self.assertEqual({p["root"] for p in request("GET", "/status")["projects"]}, {str(first), str(second)})
                request("POST", "/api/config/parents", {"action": "remove", "path": str(root)})
                self.assertEqual(request("GET", "/status")["projects"], [])

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.config_path = Path(cls.tmp.name) / "daemon.json"
        cls.config_path.write_bytes('{"parents": []}'.encode("utf-8"))
        cls._env = mock.patch.dict("os.environ", {"GSD_DAEMON_CONFIG": str(cls.config_path)})
        cls._env.start()
        cls.addClassCleanup(cls._env.stop)
        watcher = Watcher(Config(parents=[], session_dirs=[]))
        cls.server = serve(watcher, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def post(self, body: dict) -> tuple:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("POST", "/api/config/parents", json.dumps(body),
                           {"Content-Type": "application/json"})
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_add_then_remove(self) -> None:
        folder = Path(self.tmp.name) / "watchme"
        folder.mkdir()
        status, payload = self.post({"action": "add", "path": str(folder)})
        self.assertEqual(status, 200)
        self.assertEqual(payload["parents"], [str(folder)])
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["parents"], [str(folder)])
        status, payload = self.post({"action": "remove", "path": str(folder)})
        self.assertEqual(status, 200)
        self.assertEqual(payload["parents"], [])
        saved = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertEqual(saved["parents"], [])

    def test_add_not_a_directory(self) -> None:
        status, payload = self.post({"action": "add", "path": str(self.tmp.name + "/nope")})
        self.assertEqual(status, 400)
        self.assertIn("not a directory", payload["error"])

    def test_invalid_body(self) -> None:
        status, payload = self.post({"action": "ad", "path": "/tmp"})
        self.assertEqual(status, 400)
        status, payload = self.post({"action": "add"})
        self.assertEqual(status, 400)


class PostBodyTests(unittest.TestCase):
    def test_refusal_consumes_socket_body_before_reply(self):
        body = b'{"confirm": true}'
        for headers, expected in (({"Origin": "https://evil.example"}, 403),
                                  ({"Content-Type": "text/plain"}, 415)):
            with self.subTest(headers=headers):
                handler = object.__new__(_Handler)
                handler.path = "/api/plugin/update"
                handler.server = mock.Mock(server_address=("127.0.0.1", 8080))
                handler.headers = Message()
                for key, value in {"Host": "127.0.0.1:8080", "Content-Length": str(len(body)),
                                   "Content-Type": "application/json", **headers}.items():
                    handler.headers[key] = value
                socket_body = handler.rfile = io.BytesIO(body)
                replies = []

                def reply(code, content_type, payload):
                    self.assertEqual(socket_body.tell(), len(body))
                    replies.append((code, json.loads(payload)))

                handler._respond = reply
                handler.do_POST()
                self.assertEqual(replies[0][0], expected)
                self.assertIn("error", replies[0][1])


class PostOriginTests(unittest.TestCase):
    """Every POST route refuses cross-site pages, DNS rebinding, and non-JSON bodies."""

    ROUTES = ("/api/plugin/install", "/api/plugin/update", "/api/plugin/uninstall",
              "/api/plugin/check", "/api/plugin/release", "/api/frameworks/update",
              "/api/config/parents", "/api/config", "/api/path-config", "/api/refresh")

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        env = mock.patch.dict(os.environ, {"GSD_DAEMON_CONFIG": str(self.root / "daemon.json")})
        env.start()
        self.addCleanup(env.stop)
        self.plugin = mock.Mock()
        self.plugin.plan_uninstall_project.return_value = {"plan": []}
        self.plugin.apply_plan.return_value = {"ok": True}
        self.scans = []
        self.watcher = Watcher(Config(parents=[], history=False, session_dirs=[]))
        with mock.patch("threading.Thread.start"):  # no background poll: scans come only from requests
            self.frameworks = mock.Mock()
            self.server = serve(self.watcher, port=0, plugin=self.plugin, frameworks=self.frameworks)
        self.server.RequestHandlerClass.scan = staticmethod(lambda scan_sessions=True: self.scans.append(1))
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.port = self.server.server_address[1]
        self.body = json.dumps({"scope": "project", "root": str(self.root), "confirm": True, "name": "gsd-pi",
                                "action": "add", "path": str(self.root)})

    def post(self, path, headers, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.putrequest("POST", path, skip_host="Host" in headers)
        data = (self.body if body is None else body).encode()
        for key, value in {**headers, "Content-Length": str(len(data))}.items():
            conn.putheader(key, value)
        conn.endheaders(data)
        response = conn.getresponse()
        payload = json.loads(response.read())
        conn.close()
        return response.status, payload

    def assert_refused(self, headers, code):
        for path in self.ROUTES:
            with self.subTest(path=path, headers=headers):
                status, payload = self.post(path, headers)
                self.assertEqual(status, code, payload)
        self.assertEqual(self.plugin.method_calls, [])
        self.assertEqual(self.frameworks.method_calls, [])  # no update ran
        self.assertEqual(self.scans, [])
        self.assertEqual(self.watcher.config.parents, [])
        self.assertFalse((self.root / "daemon.json").exists())

    def test_cross_site_origin_refused(self):
        self.assert_refused({"Content-Type": "application/json", "Origin": "https://evil.example"}, 403)

    def test_opaque_origin_refused(self):
        self.assert_refused({"Content-Type": "application/json", "Origin": "null"}, 403)

    def test_foreign_host_refused(self):
        self.assert_refused({"Content-Type": "application/json", "Host": f"evil.example:{self.port}"}, 403)

    def test_cross_site_fetch_metadata_refused(self):
        self.assert_refused({"Content-Type": "application/json", "Sec-Fetch-Site": "cross-site"}, 403)

    def test_text_plain_body_refused(self):
        for path in self.ROUTES[:-1]:  # /api/refresh takes no body
            with self.subTest(path=path):
                status, payload = self.post(path, {"Content-Type": "text/plain"})
                self.assertEqual(status, 415, payload)
        self.assertEqual(self.plugin.method_calls, [])
        self.assertEqual(self.watcher.config.parents, [])

    def test_same_origin_json_requests_still_work(self):
        origin = {"Origin": f"http://localhost:{self.port}", "Host": f"localhost:{self.port}",
                  "Sec-Fetch-Site": "same-origin"}
        status, payload = self.post("/api/plugin/uninstall", {**origin, "Content-Type": "application/json"})
        self.assertEqual((status, payload["ok"]), (200, True), payload)
        self.plugin.plan_uninstall_project.assert_called_once_with(str(self.root))
        self.plugin.apply_plan.assert_called_once_with({"plan": []}, confirm=True)
        status, payload = self.post("/api/refresh", origin, body="")  # dashboard sends no body or type
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.scans, [1])


class PostTokenTests(PostOriginTests):
    """With a token set, every POST also needs the X-GSD-Path-Token header."""

    def setUp(self) -> None:
        super().setUp()
        self.server.RequestHandlerClass.token = "s3cret"
        self.json = {"Content-Type": "application/json"}

    def test_missing_token_refused(self):
        self.assert_refused(self.json, 403)

    def test_wrong_token_refused(self):
        self.assert_refused({**self.json, "X-GSD-Path-Token": "s3cre"}, 403)

    def test_refusal_names_the_app(self):
        _, payload = self.post("/api/refresh", self.json)
        self.assertIn("OpenGSD Path app", payload["error"])

    def test_same_origin_json_requests_still_work(self):
        token = {**self.json, "X-GSD-Path-Token": "s3cret"}
        status, payload = self.post("/api/plugin/uninstall", token)
        self.assertEqual((status, payload["ok"]), (200, True), payload)
        self.plugin.apply_plan.assert_called_once_with({"plan": []}, confirm=True)
        status, payload = self.post("/api/refresh", token)
        self.assertEqual(status, 200, payload)
        self.assertEqual(self.scans, [1])

    def test_reads_need_no_token(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", "/status")
        self.assertEqual(conn.getresponse().status, 200)
        conn.close()


class RequireTokenCliTests(unittest.TestCase):
    """`serve --require-token` creates the token file and enforces its content."""

    def test_token_file_gates_posts_and_is_reused(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name).resolve()
        env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home),
               "GSD_DAEMON_CONFIG": str(home / "daemon.json"),
               "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "daemon"),
               "PYTHONUNBUFFERED": "1"}
        token_file = home / ".gsd-path" / "app" / "api-token"

        def start():
            proc = subprocess.Popen(
                [sys.executable, "-m", "gsd_daemon", "serve", "--port", "0", "--require-token"],
                env=env, stdout=subprocess.PIPE, text=True)
            self.addCleanup(proc.wait)
            self.addCleanup(proc.kill)
            self.addCleanup(proc.stdout.close)
            return proc, int(proc.stdout.readline().strip().rsplit(":", 1)[1])

        def refresh(port, headers):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/api/refresh", headers=headers)
            status = conn.getresponse().status
            conn.close()
            return status

        proc, port = start()
        token = token_file.read_text(encoding="utf-8")
        self.assertGreaterEqual(len(token), 32)
        if os.name != "nt":
            self.assertEqual(token_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual(refresh(port, {}), 403)
        self.assertEqual(refresh(port, {"X-GSD-Path-Token": token}), 200)
        proc.kill()
        proc.wait()
        _, port = start()
        self.assertEqual(token_file.read_text(encoding="utf-8"), token)
        self.assertEqual(refresh(port, {"X-GSD-Path-Token": token}), 200)


class BrowseEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name) / "root"
        (root / "alpha").mkdir(parents=True)
        (root / "beta").mkdir()
        (root / ".hidden").mkdir()
        (root / "afile.txt").write_bytes("x".encode("utf-8"))
        (root / "proj" / ".project").mkdir(parents=True)
        (root / "proj" / ".project" / "STATE.md").write_bytes(
            "---\npipeline: gsd-path/v2\nproject: p\n".encode("utf-8"))
        cls.root = root
        watcher = Watcher(Config(parents=[]))
        cls.server = serve(watcher, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.addClassCleanup(cls.server.server_close)
        cls.addClassCleanup(cls.server.shutdown)

    def browse(self, path: str) -> tuple:
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/api/fs/browse?path=" + urllib.parse.quote(path))
        response = connection.getresponse()
        payload = json.loads(response.read())
        connection.close()
        return response.status, payload

    def test_lists_dirs_only_sorted(self) -> None:
        status, payload = self.browse(str(self.root))
        self.assertEqual(status, 200)
        names = [d["name"] for d in payload["dirs"]]
        self.assertEqual(names, ["alpha", "beta", "proj"])  # no files, no hidden
        self.assertEqual(payload["path"], str(self.root))
        self.assertTrue(payload["parent"])
        marked = {d["name"]: d["project"] for d in payload["dirs"]}
        self.assertEqual(marked, {"alpha": False, "beta": False, "proj": True})

    def test_root_has_no_parent(self) -> None:
        status, payload = self.browse(os.path.abspath(os.sep))
        self.assertEqual(status, 200)
        self.assertIsNone(payload["parent"])

    def test_not_a_directory(self) -> None:
        status, payload = self.browse(str(self.root / "afile.txt"))
        self.assertEqual(status, 400)
        self.assertIn("not a directory", payload["error"])


if __name__ == "__main__":
    unittest.main()
