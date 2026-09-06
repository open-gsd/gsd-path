import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("release_receipt", ROOT / "release_receipt.py")
release_receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_receipt)


class ClaudeChildReceiptTests(unittest.TestCase):
    def collect(self, events, landed_tool_use_id=None):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            stream = Path(temporary) / "quick/run-001/events.jsonl"
            stream.parent.mkdir(parents=True)
            stream.write_text("".join(json.dumps({"raw": json.dumps(event)}) + "\n" for event in events))
            if landed_tool_use_id is None:
                return release_receipt.claude_child(temporary, "build_T001")
            return release_receipt.claude_child(temporary, "build_T001", landed_tool_use_id)

    def use(self, identifier, background=False):
        return {"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Agent", "id": identifier,
            "input": {"description": "build_T001", "prompt": "task prompt", "run_in_background": background},
        }]}}

    def result(self, identifier, content="done", error=False):
        return {"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": identifier, "content": content, "is_error": error,
        }]}}

    def notification(self, identifier, status="completed"):
        return {"type": "system", "subtype": "task_notification", "tool_use_id": identifier,
                "task_id": "task-" + identifier, "status": status, "summary": "Verified task"}

    def test_background_requires_bound_completed_notification(self):
        for background, content in ((True, "launched"), (False, "Async agent launched successfully.")):
            for extra in ([], [self.notification("other")], [self.notification("a", "failed")],
                          [{"type": "system", "subtype": "task_updated", "tool_use_id": "a",
                            "patch": {"status": "completed"}}]):
                with self.subTest(background=background, extra=extra):
                    with self.assertRaisesRegex(SystemExit, "no completed Agent"):
                        self.collect([self.use("a", background), self.result("a", content)] + extra)

    def test_background_records_completion_and_launch(self):
        started = {"type": "system", "subtype": "task_started", "tool_use_id": "a",
                   "task_id": "task-a", "prompt": "task prompt"}
        receipt = self.collect([self.use("a", True), started, self.result("a", "Async agent launched"),
                                self.notification("a")])
        self.assertEqual("task-a", receipt["task_id"])
        self.assertEqual("a", receipt["task_started"]["tool_use_id"])
        self.assertNotIn("prompt", receipt["task_started"])
        self.assertEqual("Verified task", receipt["task_notification"]["summary"])
        self.assertEqual("completed", receipt["task_notification"]["status"])
        self.assertEqual("Async agent launched", receipt["tool_result"]["content"])
        self.assertNotIn("prompt", receipt["tool_use"]["input"])
        self.assertEqual(hashlib.sha256(b"task prompt").hexdigest(), receipt["tool_use"]["prompt_sha256"])

    def test_incomplete_retry_cannot_replace_completed_attempt(self):
        receipt = self.collect([self.use("a"), self.result("a"), self.use("b")])
        self.assertEqual("a", receipt["tool_use"]["id"])
        self.assertEqual("a", receipt["tool_result"]["tool_use_id"])

    def test_foreground_errors_do_not_complete(self):
        with self.assertRaisesRegex(SystemExit, "no completed Agent"):
            self.collect([self.use("a"), self.result("a", error=True)])

    def test_selects_last_completion_or_proven_landing(self):
        events = [self.use("a"), self.use("b"), self.result("b"), self.result("a")]
        self.assertEqual("a", self.collect(events)["tool_use"]["id"])
        self.assertEqual("b", self.collect(events, "b")["tool_use"]["id"])
        with self.assertRaisesRegex(SystemExit, "has no completion evidence"):
            self.collect(events, "missing")
