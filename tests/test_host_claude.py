"""Offline Claude Code tests using synthetic stream-json protocol samples."""

import json
import tempfile
import unittest
from pathlib import Path

from tests.hosts import claude


def launch(**options):
    return {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "id": "agent-1", "name": "Agent", "input": {
            "description": "build_T001", "prompt": "Read the brief.", **options}}]}}


def result(text="Done", is_error=False):
    return {"type": "user", "message": {"content": [
        {"type": "tool_result", "tool_use_id": "agent-1", "content": text, "is_error": is_error}]}}


def started(background):
    return {"type": "system", "subtype": "task_started", "tool_use_id": "agent-1",
            "task_id": "task-1", "is_backgrounded": background}


def notification(status="completed", tool_id="agent-1"):
    return {"type": "system", "subtype": "task_notification", "tool_use_id": tool_id,
            "task_id": "task-1", "status": status, "summary": "Finished"}


class ClaudeBindChildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def bind(self, events):
        path = self.root / "quick" / "run-1" / "events.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(json.dumps({"raw": json.dumps(event)}) + "\n" for event in events))
        return claude.bind_child(self.root, "build_T001")

    def test_foreground_result_with_launched_prose_binds(self):
        text = "Launched the verification command; all checks passed"
        for records in ([launch()], [launch(run_in_background=False), started(False)]):
            with self.subTest(records=records):
                bound = self.bind(records + [result(text)])
                self.assertEqual(bound["status"], "completed")
                self.assertEqual(bound["tool_use"]["id"], "agent-1")
                self.assertEqual(bound["tool_result"]["content"], text)
                self.assertNotIn("task_notification", bound)

    def test_foreground_error_result_does_not_bind(self):
        with self.assertRaises(LookupError):
            self.bind([launch(run_in_background=False), started(False), result(is_error=True)])

    def test_background_mode_from_either_flag_requires_notification(self):
        for records in ([launch(run_in_background=True)], [launch(), started(True)]):
            with self.subTest(records=records):
                with self.assertRaises(LookupError):
                    self.bind(records + [result("Child accepted")])

    def test_background_mode_from_either_flag_binds_completed_notification(self):
        for records in ([launch(run_in_background=True)], [launch(), started(True)]):
            with self.subTest(records=records):
                bound = self.bind(records + [result("Child accepted"), notification()])
                self.assertEqual(bound["status"], "completed")
                self.assertEqual(bound["tool_use"]["id"], "agent-1")
                self.assertEqual(bound["task_notification"]["status"], "completed")

    def test_background_rejects_failed_or_unrelated_notification(self):
        for event in (notification("failed"), notification(tool_id="other-agent")):
            with self.subTest(event=event), self.assertRaises(LookupError):
                self.bind([launch(), started(True), result("Child accepted"), event])


if __name__ == "__main__":
    unittest.main()
