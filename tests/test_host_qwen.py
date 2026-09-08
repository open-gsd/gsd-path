"""Tests for the Qwen Code host module.

The samples follow the Qwen Code docs cited in ``tests/hosts/qwen.py``; a live run on
2026-09-07 confirmed the tool_use/tool_result shapes they use.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.hosts import qwen

STREAM_JSON_SAMPLE = [
    '{"type":"system","subtype":"session_start","uuid":"u1","session_id":"123e4567-e89b-12d3-a456-426614174000","model":"qwen3-coder-plus"}',
    'not json',
    '{"type":"assistant","uuid":"u2","session_id":"123e4567-e89b-12d3-a456-426614174000","message":{"role":"assistant","content":[{"type":"text","text":"Paris."}]},"parent_tool_use_id":null}',
    '{"type":"result","subtype":"success","uuid":"u3","session_id":"123e4567-e89b-12d3-a456-426614174000","is_error":false,"duration_ms":1234,"result":"Paris.","usage":{"input_tokens":5}}',
]


def _launch(tool_id, description, **extra):
    return {"type": "assistant", "parent_tool_use_id": None, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "agent",
         "input": {"description": description, "prompt": "Read the brief.", "subagent_type": "general-purpose", **extra}}]}}


def _result(tool_id, content, is_error=False):
    return {"type": "user", "message": {"role": "user", "content": [
        {"type": "tool_result", "tool_use_id": tool_id, "content": content, "is_error": is_error}]}}


def _list_agents(tool_id, rows):
    call = {"type": "assistant", "parent_tool_use_id": None, "message": {"role": "assistant", "content": [
        {"type": "tool_use", "id": tool_id, "name": "list_agents", "input": {}}]}}
    return [call, _result(tool_id, json.dumps({"agents": rows}))]


class QwenHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run_root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def record(self, events, run="run-1"):
        path = self.run_root / "quick" / run / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps({"elapsed_seconds": i, "raw": json.dumps(ev)}) + "\n" for i, ev in enumerate(events)))

    def test_spec_matches_manifest_and_is_marked_unverified(self):
        self.assertEqual(qwen.SPEC.name, "qwen")
        self.assertEqual(qwen.SPEC.install_flag, "--qwen")
        self.assertEqual(qwen.SPEC.skill_root, ".qwen/skills")
        self.assertEqual(qwen.SPEC.child_api, "agent")
        self.assertEqual(qwen.SPEC.guard_tier, "git-only")
        self.assertTrue(qwen.SPEC.verified_live)
        self.assertIn("Verified live", qwen.SPEC.notes)

    def test_command_places_prompt_in_argv_and_resumes_by_session_id(self):
        prompt = self.run_root / "prompt.txt"
        prompt.write_text("line one\nline two\n")
        self.assertFalse(qwen.SPEC.prompt_on_stdin)
        fresh = qwen.command(prompt)
        self.assertEqual(fresh[:4], ["qwen", "--yolo", "--output-format", "stream-json"])
        self.assertEqual(fresh[-2:], ["-p", "line one\nline two\n"])
        self.assertNotIn("--resume", fresh)
        resumed = qwen.command(prompt, "123e4567-e89b-12d3-a456-426614174000")
        self.assertEqual(resumed[4:6], ["--resume", "123e4567-e89b-12d3-a456-426614174000"])
        self.assertEqual(resumed[-2:], fresh[-2:])

    def test_parse_events_reads_session_final_message_and_usage(self):
        parsed = qwen.parse_events(STREAM_JSON_SAMPLE)
        self.assertEqual(parsed, {"session_id": "123e4567-e89b-12d3-a456-426614174000",
                                  "final_message": "Paris.", "usage": {"input_tokens": 5}})

    def test_parse_events_leaves_missing_values_none(self):
        self.assertEqual(qwen.parse_events(["garbage", '{"type":"assistant"}']),
                         {"session_id": None, "final_message": None, "usage": None})

    def test_bind_child_foreground_inline_result(self):
        self.record([_launch("t1", "build_T001", run_in_background=False), _result("t1", "Task done: wrote src/app.py")])
        bound = qwen.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["status"], "completed")
        self.assertEqual(bound["child_api"], "agent")
        self.assertEqual(bound["run"], "run-1")
        self.assertEqual(bound["tool_use"]["input"]["subagent_type"], "general-purpose")
        self.assertNotIn("prompt", bound["tool_use"]["input"])
        self.assertEqual(len(bound["tool_use"]["prompt_sha256"]), 64)
        self.assertFalse(bound["tool_result"]["is_error"])

    def test_bind_child_foreground_error_result_is_not_completion(self):
        self.record([_launch("t1", "build_T001", run_in_background=False), _result("t1", "agent failed", is_error=True)])
        with self.assertRaisesRegex(LookupError, "no inline result"):
            qwen.bind_child(self.run_root, "build_T001")

    def test_bind_child_background_completed_via_list_agents(self):
        rows = [{"task_id": "task-9", "description": "build_T001", "status": "completed", "can_receive_message": True},
                {"task_id": "task-8", "description": "inspect_docs", "status": "running", "can_receive_message": True}]
        self.record([_launch("t1", "build_T001"), _result("t1", "Launched background agent task_id=task-9"),
                     *_list_agents("t2", rows)])
        bound = qwen.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["status"], "completed")
        self.assertEqual(bound["task_id"], "task-9")
        self.assertEqual(bound["list_agents_states"], rows[:1])

    def test_bind_child_background_matches_by_task_id_when_description_absent(self):
        rows = [{"task_id": "task-9", "status": "completed"}]
        self.record([_launch("t1", "build_T001"), _result("t1", 'launched {"task_id": "task-9"}'), *_list_agents("t2", rows)])
        self.assertEqual(qwen.bind_child(self.run_root, "build_T001")["list_agents_states"], rows)

    def test_retry_uses_known_task_id_exclusively(self):
        rows = [{"task_id": "task-1", "description": "build_T001", "status": "completed"},
                {"task_id": "task-2", "description": "build_T001", "status": "running"}]
        self.record([_launch("first", "build_T001"), _result("first", "task_id=task-1"),
                     _launch("retry", "build_T001"), _result("retry", "task_id=task-2"),
                     *_list_agents("list", rows)])
        bound = qwen.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["tool_use"]["id"], "first")
        self.assertEqual(bound["task_id"], "task-1")
        self.assertEqual(bound["list_agents_states"], rows[:1])

    def test_failed_retry_cannot_replace_completed_attempt(self):
        rows = [{"task_id": "task-1", "description": "build_T001", "status": "completed"}]
        self.record([_launch("first", "build_T001"), _result("first", "task_id=task-1"),
                     _launch("retry", "build_T001"), _result("retry", "launch failed", is_error=True),
                     *_list_agents("list", rows)])
        bound = qwen.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["tool_use"]["id"], "first")
        self.assertEqual(bound["task_id"], "task-1")
        self.assertFalse(bound["tool_result"]["is_error"])

    def test_failed_launch_with_task_id_cannot_bind_completed_listing(self):
        rows = [{"task_id": "task-1", "status": "completed"}]
        self.record([_launch("failed", "build_T001"), _result("failed", "task_id=task-1", is_error=True),
                     *_list_agents("list", rows)])
        with self.assertRaises(LookupError):
            qwen.bind_child(self.run_root, "build_T001")

    def test_earlier_listing_cannot_complete_later_launch(self):
        rows = [{"description": "build_T001", "status": "completed"}]
        self.record(_list_agents("list", rows), run="run-1")
        self.record([_launch("retry", "build_T001")], run="run-2")
        with self.assertRaises(LookupError):
            qwen.bind_child(self.run_root, "build_T001")

    def test_description_fallback_is_recorded_without_task_id(self):
        rows = [{"description": "build_T001", "status": "completed"}]
        self.record([_launch("first", "build_T001"), *_list_agents("list", rows)])
        bound = qwen.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["completion_match"], "description")
        self.assertEqual(bound["list_agents_states"], rows)

    def test_later_task_id_disables_description_fallback(self):
        rows = [{"task_id": "old", "description": "build_T001", "status": "completed"}]
        self.record([_launch("retry", "build_T001"), *_list_agents("list", rows),
                     _result("retry", "task_id=new")])
        with self.assertRaises(LookupError):
            qwen.bind_child(self.run_root, "build_T001")

    def test_bind_child_background_without_completed_listing_raises(self):
        self.record([_launch("t1", "build_T001"), _result("t1", "Launched background agent task_id=task-9"),
                     *_list_agents("t2", [{"task_id": "task-9", "description": "build_T001", "status": "running"}])])
        with self.assertRaisesRegex(LookupError, "list_agents"):
            qwen.bind_child(self.run_root, "build_T001")

    def test_bind_child_ignores_nested_launches_and_other_descriptions(self):
        nested = _launch("t3", "build_T001", run_in_background=False); nested["parent_tool_use_id"] = "t0"
        self.record([nested, _result("t3", "done"), _launch("t1", "build_T002", run_in_background=False), _result("t1", "done")])
        with self.assertRaisesRegex(LookupError, "no agent child with description 'build_T001'"):
            qwen.bind_child(self.run_root, "build_T001")

    def test_bind_child_absent_child_raises_lookup_error(self):
        self.record([])
        with self.assertRaises(LookupError):
            qwen.bind_child(self.run_root, "build_T001")


if __name__ == "__main__":
    unittest.main()
