"""Tests for the GitHub Copilot CLI host module.

The samples follow the SDK streaming-events envelope that a live ``copilot`` 1.0.83
run (2026-09-07) confirmed: ``{type, data, id, timestamp, parentId}`` lines, ``task``
and ``subagent.*`` events keyed by ``toolCallId`` (``agentId`` on the envelope), and a
terminal ``result`` line carrying ``sessionId`` and ``usage``.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hosts import copilot

SESSION = "0b1c2d3e-4f50-4617-8a9b-0c1d2e3f4a5b"
CALL = "toolu_task_build_t001"


def env(kind, data, **envelope):
    return {"id": "evt", "timestamp": "2026-09-06T00:00:00Z", "parentId": None, "type": kind, "data": data, **envelope}


def task_start(child, call_id=CALL, key="description"):
    return env("tool.execution_start", {"toolCallId": call_id, "toolName": "task",
                                        "arguments": {"agent_type": "general-purpose", key: child, "prompt": "Read /abs/brief.md then build."}})


def task_complete(call_id=CALL, success=True):
    return env("tool.execution_complete", {"toolCallId": call_id, "success": success, "result": {"content": "T001 landed"}})


def subagent(kind, call_id=CALL, **extra):
    return env(f"subagent.{kind}", {"toolCallId": call_id, "agentName": "general-purpose", **extra}, agentId="general-purpose-0")


STDOUT_SAMPLE = [
    json.dumps(env("session.start", {"sessionId": SESSION, "model": "gpt-5.4"})),
    "not json at all",
    json.dumps(env("assistant.message", {"messageId": "m1", "content": "First reply"})),
    json.dumps(env("assistant.usage", {"model": "gpt-5.4", "inputTokens": 10, "outputTokens": 5})),
    json.dumps(env("assistant.message", {"messageId": "m2", "content": "Archive prepared at .planning/archive/M001"})),
    json.dumps({"type": "result", "usage": {"premiumRequests": 3, "totalApiDurationMs": 1200, "sessionDurationMs": 5000, "codeChanges": {"linesAdded": 4}}}),
]


class CommandTests(unittest.TestCase):
    def test_headless_argv_carries_prompt_text_and_json_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("/gsd-path quick\nline two")
            args = copilot.command(prompt)
        self.assertEqual(args[:3], ["copilot", "-p", "/gsd-path quick\nline two"])
        self.assertIn("--allow-all", args)
        self.assertIn("--no-ask-user", args)
        self.assertEqual(args[args.index("--output-format") + 1], "json")
        self.assertFalse(any(a.startswith("--resume") for a in args))
        self.assertFalse(copilot.SPEC.prompt_on_stdin)

    def test_resume_appends_documented_resume_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("continue")
            args = copilot.command(prompt, resume=SESSION)
        self.assertEqual(args[-1], f"--resume={SESSION}")


class ParseEventsTests(unittest.TestCase):
    def test_extracts_session_final_message_and_terminal_usage(self):
        parsed = copilot.parse_events(STDOUT_SAMPLE)
        self.assertEqual(parsed["session_id"], SESSION)
        self.assertEqual(parsed["final_message"], "Archive prepared at .planning/archive/M001")
        self.assertEqual(parsed["usage"]["premiumRequests"], 3)

    def test_assistant_usage_is_kept_when_no_result_event(self):
        parsed = copilot.parse_events(STDOUT_SAMPLE[:4])
        self.assertEqual(parsed["usage"], {"model": "gpt-5.4", "inputTokens": 10, "outputTokens": 5})
        self.assertEqual(parsed["final_message"], "First reply")

    def test_top_level_session_id_key_is_accepted(self):
        parsed = copilot.parse_events([json.dumps({"type": "result", "session_id": SESSION, "usage": {}})])
        self.assertEqual(parsed["session_id"], SESSION)

    def test_nothing_is_invented(self):
        self.assertEqual(copilot.parse_events(["garbage", json.dumps({"type": "assistant.turn_start", "data": {}})]),
                         {"session_id": None, "final_message": None, "usage": None})


class BindChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_root = Path(self.tmp.name) / "eval"
        self.home = Path(self.tmp.name) / "copilot-home"
        patcher = mock.patch.dict(os.environ, {"COPILOT_HOME": str(self.home)})
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_run(self, stream_events, session_id=SESSION, name="run-20260906T000000000000Z"):
        run_dir = self.run_root / "quick" / name
        run_dir.mkdir(parents=True)
        (run_dir / "events.jsonl").write_text("".join(json.dumps({"elapsed_seconds": i, "raw": json.dumps(ev)}) + "\n"
                                                      for i, ev in enumerate(stream_events)))
        (run_dir / "run.json").write_text(json.dumps({"host": "copilot", "session_id": session_id}))

    def write_transcript(self, events, session_id=SESSION):
        path = self.home / "session-state" / session_id / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps(ev) + "\n" for ev in events))

    def test_binds_task_call_to_completion_in_session_transcript(self):
        self.write_run([{"type": "result", "usage": {}}])
        self.write_transcript([env("user.message", {"content": "/gsd-path"}), task_start("build_T001"), subagent("started", model="gpt-5.4"),
                               env("tool.execution_start", {"toolCallId": "inner", "toolName": "bash", "arguments": {"cmd": "git commit"}}, agentId="general-purpose-0"),
                               subagent("completed", durationMs=9000, totalToolCalls=7), task_complete()])
        bound = copilot.bind_child(self.run_root, "build_T001")
        self.assertEqual((bound["child_id"], bound["status"], bound["child_api"]), ("build_T001", "completed", "task"))
        self.assertEqual(bound["agent_id"], "general-purpose-0")
        self.assertEqual(bound["source"], f"session-state/{SESSION}")
        self.assertEqual(bound["matched_argument"], "description")
        self.assertEqual(bound["tool_call"]["toolCallId"], CALL)
        self.assertNotIn("prompt", bound["tool_call"]["arguments"])
        self.assertEqual(len(bound["tool_call"]["prompt_sha256"]), 64)
        self.assertEqual(bound["tool_result"], {"success": True, "content": "T001 landed"})
        self.assertEqual(bound["completed"], {"agentName": "general-purpose", "durationMs": 9000, "totalToolCalls": 7})
        self.assertEqual(bound["started"]["model"], "gpt-5.4")

    def test_binds_from_recorded_stdout_stream_without_transcript(self):
        self.write_run([task_start("review_final", key="name"), task_complete()], session_id=None)
        bound = copilot.bind_child(self.run_root, "review_final")
        self.assertEqual(bound["matched_argument"], "name")
        self.assertEqual(bound["source"], "run-20260906T000000000000Z")

    def test_subagent_completed_alone_counts_as_completion(self):
        self.write_run([task_start("plan"), subagent("completed")], session_id=None)
        self.assertEqual(copilot.bind_child(self.run_root, "plan")["status"], "completed")

    def test_later_retry_wins(self):
        self.write_run([task_start("build_T001", call_id="first"), task_complete("first", success=False),
                        task_start("build_T001", call_id="second"), task_complete("second")], session_id=None)
        self.assertEqual(copilot.bind_child(self.run_root, "build_T001")["tool_call"]["toolCallId"], "second")

    def test_missing_task_call_raises(self):
        self.write_run([{"type": "result", "usage": {}}])
        self.write_transcript([task_start("build_T002")])
        with self.assertRaises(LookupError) as ctx:
            copilot.bind_child(self.run_root, "build_T001")
        self.assertIn("build_T001", str(ctx.exception))

    def test_started_but_never_completed_raises(self):
        self.write_run([task_start("build_T001"), subagent("started")], session_id=None)
        with self.assertRaises(LookupError) as ctx:
            copilot.bind_child(self.run_root, "build_T001")
        self.assertIn("never completed", str(ctx.exception))

    def test_failed_subagent_is_not_completion_even_with_tool_result(self):
        self.write_run([task_start("build_T001"), subagent("failed", error="boom"), task_complete()], session_id=None)
        with self.assertRaises(LookupError):
            copilot.bind_child(self.run_root, "build_T001")

    def test_missing_transcript_and_empty_stream_raises(self):
        self.write_run([{"type": "result", "usage": {}}])  # session id recorded, but no session-state directory
        with self.assertRaises(LookupError):
            copilot.bind_child(self.run_root, "build_T001")


class SpecTests(unittest.TestCase):
    def test_spec_matches_manifest_and_declares_verified(self):
        spec = copilot.SPEC
        self.assertEqual((spec.name, spec.install_flag, spec.skill_root), ("copilot", "--copilot", ".github/skills"))
        self.assertEqual((spec.child_api, spec.guard_tier), ("task", "git-only"))
        self.assertTrue(spec.verified_live)
        self.assertIn("Verified live", spec.notes)


if __name__ == "__main__":
    unittest.main()
