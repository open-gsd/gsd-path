import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.config import Config
from gsd_daemon.watcher import Watcher

STATE = """---
pipeline: gsd-path/v2
project: demo
milestone: demo-ms
phase: {phase}
status: {status}
branch: gsd-path/M001
archive: null
---
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
"""


def make_project(root: Path, phase: str = "build", status: str = "active") -> Path:
    project_dir = root / ".project"
    (project_dir / "tasks").mkdir(parents=True, exist_ok=True)
    (project_dir / "STATE.md").write_text(STATE.format(phase=phase, status=status), encoding="utf-8")
    (project_dir / "tasks" / "T001-one.md").write_text(TASK.format(task_id="T001", status="done"),
                                                        encoding="utf-8")
    (project_dir / "tasks" / "T002-two.md").write_text(TASK.format(task_id="T002", status="pending"),
                                                       encoding="utf-8")
    return root


def touch(root: Path) -> None:
    # mtime granularity guard: ensure the next mutation lands on a newer mtime
    time.sleep(0.02)


class WatcherTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name) / "work"
        self.parent.mkdir()
        self.project = self.parent / "demo"
        self.config = Config(parents=[str(self.parent)])

    def watcher(self, probe_hook=None) -> Watcher:
        return Watcher(self.config, probe_hook=probe_hook)

    def events_of(self, events, event_type) -> list:
        return [event for event in events if event["type"] == event_type]

    def test_project_added(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        events = watcher.poll_once()
        added = self.events_of(events, "project-added")
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["root"], str(self.project))
        self.assertIn(str(self.project), watcher.projects)

    def test_no_events_when_stable(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        watcher.poll_once()
        self.assertEqual(watcher.poll_once(), [])

    def test_phase_changed(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        watcher.poll_once()
        touch(self.project)
        (self.project / ".project" / "STATE.md").write_text(
            STATE.format(phase="ship", status="active"), encoding="utf-8")
        events = watcher.poll_once()
        changed = self.events_of(events, "phase-changed")
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["detail"], "build -> ship")

    def test_blocked(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        watcher.poll_once()
        touch(self.project)
        (self.project / ".project" / "STATE.md").write_text(
            STATE.format(phase="build", status="blocked"), encoding="utf-8")
        events = watcher.poll_once()
        self.assertEqual(len(self.events_of(events, "blocked")), 1)
        status_changed = self.events_of(events, "status-changed")
        self.assertEqual(status_changed[0]["detail"], "active -> blocked")

    def test_tasks_changed(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        watcher.poll_once()
        touch(self.project)
        (self.project / ".project" / "tasks" / "T002-two.md").write_text(
            TASK.format(task_id="T002", status="done"), encoding="utf-8")
        events = watcher.poll_once()
        changed = self.events_of(events, "tasks-changed")
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["detail"], "2/2 done (was 1/2)")

    def test_project_removed(self) -> None:
        make_project(self.project)
        watcher = self.watcher()
        watcher.poll_once()
        for path in sorted((self.project / ".project").rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            else:
                path.rmdir()
        (self.project / ".project").rmdir()
        self.project.rmdir()
        events = watcher.poll_once()
        removed = self.events_of(events, "project-removed")
        self.assertEqual(len(removed), 1)
        self.assertEqual(removed[0]["root"], str(self.project))
        self.assertEqual(watcher.projects, {})

    def test_mtime_prefilter_skips_probe(self) -> None:
        make_project(self.project)
        calls = []
        watcher = self.watcher(probe_hook=calls.append)
        watcher.poll_once()
        watcher.poll_once()
        watcher.poll_once()
        self.assertEqual(calls, [str(self.project)])

    def test_prefilter_reprobes_after_mutation(self) -> None:
        make_project(self.project)
        calls = []
        watcher = self.watcher(probe_hook=calls.append)
        watcher.poll_once()
        touch(self.project)
        (self.project / ".project" / "STATE.md").write_text(
            STATE.format(phase="ship", status="active"), encoding="utf-8")
        watcher.poll_once()
        self.assertEqual(calls, [str(self.project), str(self.project)])


if __name__ == "__main__":
    unittest.main()


class SpendAttachmentTests(unittest.TestCase):
    def test_first_poll_can_skip_the_session_scan(self) -> None:
        from unittest import mock
        from gsd_daemon.config import Config
        from gsd_daemon.watcher import Watcher
        watcher = Watcher(Config(parents=[]))
        with mock.patch.object(watcher.sessions, "scan", side_effect=AssertionError("scanned")) as scan:
            watcher.poll_once(scan_sessions=False)
            self.assertEqual(scan.call_count, 0)
        with mock.patch.object(watcher.sessions, "scan") as scan:
            watcher.poll_once()
            self.assertEqual(scan.call_count, 1)
