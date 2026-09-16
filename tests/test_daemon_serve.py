import http.client
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
from gsd_daemon.serve import serve
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
    (project_dir / "STATE.md").write_text(STATE, encoding="utf-8")
    (project_dir / "tasks" / "T001-one.md").write_text(
        TASK.format(task_id="T001", status="done"), encoding="utf-8")
    (project_dir / "tasks" / "T002-two.md").write_text(
        TASK.format(task_id="T002", status="pending"), encoding="utf-8")
    review_dir = project_dir / "review"
    review_dir.mkdir()
    (review_dir / "wave-1.cycle1.md").write_text(WAVE_REVIEW, encoding="utf-8")
    build_dir = project_dir / "build"
    build_dir.mkdir()
    (build_dir / "verify-ledger.jsonl").write_text(
        json.dumps({"command": "make test", "commit": "abc1234", "result": "pass",
                    "recorded_at": "2026-09-11T12:00:00+00:00"}) + "\n",
        encoding="utf-8",
    )
    (build_dir / "usage.jsonl").write_text(
        json.dumps({"task": "T001", "model": "kimi-k2", "family": "kimi",
                    "tokens_in": 100, "tokens_out": 50, "cost": 0.01,
                    "phase": "build"}) + "\n",
        encoding="utf-8",
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
        cls.history.write_text(
            json.dumps({"type": "phase-changed", "root": str(parent / "demo"),
                        "detail": "plan -> build", "at": "2026-09-11T10:00:00+00:00"}) + "\n",
            encoding="utf-8",
        )
        cls._env = mock.patch.dict("os.environ", {"GSD_DAEMON_HISTORY": str(cls.history)})
        cls._env.start()
        cls.addClassCleanup(cls._env.stop)
        watcher = Watcher(Config(parents=[str(parent)]))
        cls.server = serve(watcher, port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
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
        self.assertEqual(len(payload["events"]), 1)
        self.assertEqual(payload["events"][0]["type"], "phase-changed")

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
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as handle:
            handle.write(scripts[0])
            path = handle.name
        self.addCleanup(lambda: os.path.exists(path) and os.unlink(path))
        result = subprocess.run([node, "--check", path], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

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
        staged = state.with_name("STATE.md.tmp")
        staged.write_text(state.read_text(encoding="utf-8").replace("phase: build", "phase: ship"), encoding="utf-8")
        os.utime(staged, (time.time() + 5, time.time() + 5))
        os.replace(staged, state)
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
                    conn.request(method, path, json.dumps(body) if body else None)
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
        cls.config_path.write_text('{"parents": []}', encoding="utf-8")
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


class BrowseEndpointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        root = Path(cls.tmp.name) / "root"
        (root / "alpha").mkdir(parents=True)
        (root / "beta").mkdir()
        (root / ".hidden").mkdir()
        (root / "afile.txt").write_text("x", encoding="utf-8")
        (root / "proj" / ".project").mkdir(parents=True)
        (root / "proj" / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: p\n", encoding="utf-8")
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
