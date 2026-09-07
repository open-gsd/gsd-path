"""Grok host runner tests on trimmed lines recorded from grok 1.0.13 (2026-09-06)."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hosts import grok

SESSION = "01a079d4-e4b4-7be3-859d-0a212d1feb80"
SUBAGENT = "01a079d5-18bc-7fd3-8217-ba124901c14e"
CWD = "/private/tmp/grok-probe/two"
SPAWN_CALL = "call-39d7c3b6-e532-42e6-9b56-24aa22564c60-0"
WAIT_CALL = "call-ad5ac1ce-901f-459b-9dfc-1abb39da817a-1"

SPAWN_OUTPUT = ("Subagent started in background.\nsubagent_id: " + SUBAGENT + "\ntype: general-purpose\n"
                "description: build_probe\n\nWhen you need its result, use get_command_or_subagent_output with "
                'task_ids=["' + SUBAGENT + '"] and a positive timeout_ms.')

HEAD = [
    {"type": "available_commands", "tools": ["spawn_subagent", "get_command_or_subagent_output"], "commands": ["gsd-path"]},
    {"type": "thought", "data": "Spawn"},
    {"type": "text", "data": "Spawning"}, {"type": "text", "data": " the subagent."},
    {"type": "usage", "usage": {"input_tokens": 30879, "output_tokens": 638}, "signature": "cZ5X"},
    {"type": "tool_call", "toolCallId": SPAWN_CALL, "title": "spawn_subagent", "kind": "task", "status": "pending",
     "toolName": "spawn_subagent", "rawInput": {"prompt": "Reply with exactly: ok", "description": "build_probe",
                                                "subagent_type": "general-purpose", "background": True, "isolation": "none", "cwd": CWD},
     "content": [], "locations": []},
    {"type": "tool_call_update", "toolCallId": SPAWN_CALL, "status": None, "content": [], "rawOutput": None, "locations": []},
    {"type": "tool_call_update", "toolCallId": SPAWN_CALL, "status": "completed",
     "content": [{"type": "content", "content": {"type": "text", "text": SPAWN_OUTPUT}}],
     "rawOutput": {"type": "Text", "text": SPAWN_OUTPUT}, "locations": []},
    {"type": "text", "data": "Waiting"}, {"type": "text", "data": "ok"}, {"type": "text", "data": " for the subagent."},
    {"type": "tool_call", "toolCallId": WAIT_CALL, "title": "get_command_or_subagent_output", "kind": "background_task_action",
     "status": "pending", "toolName": "get_command_or_subagent_output", "rawInput": {"task_ids": [SUBAGENT], "timeout_ms": 60000},
     "content": [], "locations": []},
]
COMPLETION = {"type": "tool_call_update", "toolCallId": WAIT_CALL, "status": "completed", "content": [], "rawOutput": {
    "type": "TaskOutput", "Result": {"task_id": SUBAGENT, "command": "[subagent:general-purpose] build_probe", "status": "completed",
                                     "exit_code": 0, "started": "2026-09-07T03:06:43Z", "ended": "2026-09-07T03:06:45Z", "duration_secs": 1.618,
                                     "output": "ok\n\n<subagent_meta>id=" + SUBAGENT + ", type=general-purpose, tool_calls=0, turns=1</subagent_meta>",
                                     "truncated": False}}, "locations": []}
TAIL = [
    {"type": "text", "data": "ok"},
    {"type": "usage", "usage": {"input_tokens": 311, "output_tokens": 29}, "signature": "9Kl0"},
    {"type": "end", "stopReason": "end_turn", "sessionId": SESSION, "requestId": "b63c50e8-c52f-40e4-8166-abbdd16ccae4",
     "usage": {"input_tokens": 42370, "cache_read_input_tokens": 80640, "output_tokens": 796, "reasoning_tokens": 603, "total_tokens": 123806},
     "num_turns": 3, "total_cost_usd": 0.02207212, "modelUsage": {"grok-4.6-build": {"modelCalls": 4}}},
]


def lines(events):
    return [json.dumps(e) for e in events]


class ParseEventsTests(unittest.TestCase):
    def test_reads_session_usage_and_final_text_after_last_tool_event(self):
        parsed = grok.parse_events(lines(HEAD + [COMPLETION] + TAIL))
        self.assertEqual(parsed["session_id"], SESSION)
        self.assertEqual(parsed["final_message"], "ok")
        self.assertEqual(parsed["usage"]["total_tokens"], 123806)

    def test_single_turn_without_tools_joins_text_deltas(self):
        recorded = ['{"type":"text","data":"ok"}', '{"type":"text","data":"2"}', "not json",
                    '{"type":"end","stopReason":"end_turn","sessionId":"' + SESSION + '","usage":{"total_tokens":36610}}']
        self.assertEqual(grok.parse_events(recorded), {"session_id": SESSION, "final_message": "ok2", "usage": {"total_tokens": 36610}})

    def test_interrupted_stream_has_no_session(self):
        parsed = grok.parse_events(lines(HEAD))
        self.assertIsNone(parsed["session_id"])
        self.assertIsNone(parsed["usage"])


class BindChildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.run_root = Path(self.temporary.name)
        self.sessions = self.run_root / "sessions"
        patcher = mock.patch.object(grok, "SESSION_ROOT", self.sessions)
        patcher.start(); self.addCleanup(patcher.stop)

    def record(self, events, run="run-20260907T030630000000Z"):
        run_dir = self.run_root / "quick" / run; run_dir.mkdir(parents=True)
        (run_dir / "events.jsonl").write_text("".join(json.dumps({"elapsed_seconds": i, "raw": raw}) + "\n" for i, raw in enumerate(lines(events))))

    def test_binds_completed_background_child_by_description(self):
        self.record(HEAD + [COMPLETION] + TAIL)
        bound = grok.bind_child(self.run_root, "build_probe")
        self.assertEqual(bound["status"], "completed")
        self.assertEqual(bound["child_api"], "spawn_subagent")
        self.assertEqual(bound["session_id"], SESSION)
        self.assertEqual(bound["subagent_id"], SUBAGENT)
        self.assertEqual(bound["spawn_input"]["cwd"], CWD)
        self.assertNotIn("prompt", bound["spawn_input"])
        self.assertEqual(bound["completion"]["task_id"], SUBAGENT)
        self.assertEqual(bound["completion"]["command"], "[subagent:general-purpose] build_probe")
        self.assertEqual(bound["completion"]["exit_code"], 0)
        self.assertIsNone(bound["transcript"])

    def test_child_that_never_completed_raises(self):
        self.record(HEAD + TAIL)
        with self.assertRaises(LookupError) as raised:
            grok.bind_child(self.run_root, "build_probe")
        self.assertIn("never reported completed", str(raised.exception))

    def test_unknown_description_raises(self):
        self.record(HEAD + [COMPLETION] + TAIL)
        with self.assertRaises(LookupError):
            grok.bind_child(self.run_root, "build_T001")

    def test_completion_of_another_task_id_does_not_bind(self):
        other = json.loads(json.dumps(COMPLETION)); other["rawOutput"]["Result"]["task_id"] = "01a079d5-0000-7fd3-8217-000000000000"
        self.record(HEAD + [other] + TAIL)
        with self.assertRaises(LookupError):
            grok.bind_child(self.run_root, "build_probe")

    def test_transcript_evidence_when_session_dir_exists(self):
        self.record(HEAD + [COMPLETION] + TAIL)
        parent = grok.session_dir(CWD, SESSION); parent.mkdir(parents=True); (parent.parent / SUBAGENT).mkdir()
        (parent / "resources_state.json").write_text(json.dumps({"state": {"grok_build.ReportedTaskCompletions": {"reported": [SUBAGENT]}}}))
        transcript = grok.bind_child(self.run_root, "build_probe")["transcript"]
        self.assertEqual(transcript["session_dir"], str(parent))
        self.assertEqual(transcript["child_session_dir"], str(parent.parent / SUBAGENT))
        self.assertEqual(transcript["reported_completions"], [SUBAGENT])


class CommandTests(unittest.TestCase):
    def test_headless_and_resume_argv(self):
        fresh = grok.command(Path("/tmp/p.txt"), None)
        self.assertIn("--prompt-file", fresh); self.assertIn("/tmp/p.txt", fresh)
        self.assertIn("streaming-json", fresh); self.assertNotIn("--resume", fresh)
        resumed = grok.command(Path("/tmp/p.txt"), SESSION)
        self.assertEqual(resumed[-2:], ["--resume", SESSION])
        self.assertFalse(grok.SPEC.prompt_on_stdin)


if __name__ == "__main__":
    unittest.main()
