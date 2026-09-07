"""Offline checks for the Cursor host module.

Sample lines follow Cursor's stream-json schema as confirmed by a live run on 2026-09-07
(system/init, tool_call started|completed, result); the tool_call body carries the
``toolCallId``/``startedAtMs``/``completedAtMs`` envelope keys beside ``taskToolCall``.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.hosts.cursor import SPEC, bind_child, command, parse_events

SESSION = "0f1e2d3c-4b5a-6978-8a9b-0c1d2e3f4a5b"

INIT = json.dumps({"type": "system", "subtype": "init", "apiKeySource": "login", "cwd": "/tmp/repo",
                   "session_id": SESSION, "model": "composer-2.5", "permissionMode": "default"})
TASK_STARTED = json.dumps({"type": "tool_call", "subtype": "started", "call_id": "call_7",
                           "tool_call": {"taskToolCall": {"args": {"description": "build_T001", "subagent_type": "gsd-path",
                                                                   "prompt": "Read /abs/role.md then implement T001."}},
                                         "toolCallId": "call_7", "startedAtMs": "1"},
                           "session_id": SESSION})
TASK_COMPLETED = json.dumps({"type": "tool_call", "subtype": "completed", "call_id": "call_7",
                             "tool_call": {"taskToolCall": {"args": {"description": "build_T001", "subagent_type": "gsd-path",
                                                                     "prompt": "Read /abs/role.md then implement T001."},
                                                            "result": {"success": {"content": "T001 landed at 1a2b3c4"}}},
                                           "toolCallId": "call_7", "startedAtMs": "1", "completedAtMs": "2"},
                             "session_id": SESSION})
TASK_FAILED = json.dumps({"type": "tool_call", "subtype": "completed", "call_id": "call_7",
                          "tool_call": {"taskToolCall": {"args": {"description": "build_T001", "subagent_type": "gsd-path",
                                                                  "prompt": "Read /abs/role.md then implement T001."},
                                                         "result": {"error": "subagent gsd-path not found"}}},
                          "session_id": SESSION})
READ_COMPLETED = json.dumps({"type": "tool_call", "subtype": "completed", "call_id": "call_2",
                             "tool_call": {"readToolCall": {"args": {"path": "README.md"},
                                                            "result": {"success": {"content": "# x", "totalLines": 1}}}},
                             "session_id": SESSION})
RESULT = json.dumps({"type": "result", "subtype": "success", "duration_ms": 1234, "duration_api_ms": 1200,
                     "is_error": False, "result": "ok", "session_id": SESSION})


class ParseEventsTests(unittest.TestCase):
    def test_reads_session_and_final_message(self):
        parsed = parse_events([INIT, READ_COMPLETED, RESULT])
        self.assertEqual(parsed, {"session_id": SESSION, "final_message": "ok", "usage": None})

    def test_skips_non_json_lines_and_reports_missing_result(self):
        parsed = parse_events(["Starting agent...", INIT, "not json"])
        self.assertEqual(parsed, {"session_id": SESSION, "final_message": None, "usage": None})


class BindChildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run_root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, lines, run="run-20260906T000000000000Z"):
        events = self.run_root / "quick" / run / "events.jsonl"
        events.parent.mkdir(parents=True)
        events.write_text("".join(json.dumps({"elapsed_seconds": i, "raw": line}) + "\n" for i, line in enumerate(lines)))

    def test_binds_completed_task_child(self):
        self.record([INIT, READ_COMPLETED, TASK_STARTED, TASK_COMPLETED, RESULT])
        bound = bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["status"], "completed")
        self.assertEqual(bound["child_api"], "Task")
        self.assertEqual(bound["child_id"], "build_T001")
        self.assertEqual(bound["session_id"], SESSION)
        self.assertEqual(bound["run"], "run-20260906T000000000000Z")
        self.assertEqual(bound["tool_use"]["id"], "call_7")
        self.assertEqual(bound["tool_use"]["input"], {"description": "build_T001", "subagent_type": "gsd-path"})
        self.assertEqual(len(bound["tool_use"]["prompt_sha256"]), 64)
        self.assertFalse(bound["tool_result"]["is_error"])
        self.assertIn("T001 landed", bound["tool_result"]["content"])

    def test_started_without_completion_is_lookup_error(self):
        self.record([INIT, TASK_STARTED, RESULT])
        with self.assertRaises(LookupError):
            bind_child(self.run_root, "build_T001")

    def test_failed_task_is_lookup_error(self):
        self.record([INIT, TASK_STARTED, TASK_FAILED, RESULT])
        with self.assertRaises(LookupError):
            bind_child(self.run_root, "build_T001")

    def test_other_description_is_lookup_error(self):
        self.record([INIT, TASK_STARTED, TASK_COMPLETED, RESULT])
        with self.assertRaises(LookupError) as raised:
            bind_child(self.run_root, "build_T002")
        self.assertIn("build_T002", str(raised.exception))


class CommandAndSpecTests(unittest.TestCase):
    def test_command_places_prompt_in_argv(self):
        with tempfile.TemporaryDirectory() as d:
            prompt = Path(d) / "prompt.txt"
            prompt.write_text("Reply with exactly: ok")
            self.assertEqual(command(prompt), ["cursor-agent", "-p", "--output-format", "stream-json", "--force", "--trust",
                                               "Reply with exactly: ok"])
            self.assertEqual(command(prompt, SESSION)[6:8], ["--resume", SESSION])

    def test_spec_facts(self):
        self.assertEqual((SPEC.name, SPEC.install_flag, SPEC.skill_root), ("cursor", "--cursor", ".cursor/skills"))
        self.assertEqual((SPEC.child_api, SPEC.guard_tier), ("Task", "native-fail-closed"))
        self.assertFalse(SPEC.prompt_on_stdin)
        self.assertTrue(SPEC.verified_live)
        self.assertIn("UNVERIFIED", SPEC.extra["native_guard_probe"])


if __name__ == "__main__":
    unittest.main()
