"""Zed host module tests.

Samples follow the Zed sources cited in tests/hosts/zed.py; ``sample_thread`` uses the
typed-input / keyed-tool_results / structured-output layout of the thread.json a live
eval-cli run wrote on 2026-09-07.
"""

import json
import os
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from tests.hosts import zed

RESULT_STDERR = [
    "[tool] spawn_agent ✓",
    "[eval-cli] subagent spawned: sess-child-1",
    "[eval-cli] stopped: EndTurn",
    "[eval-cli] result: {",
    '  "status": "completed",',
    '  "duration_secs": 12.5,',
    '  "model": "anthropic/claude-sonnet-4-6",',
    '  "input_tokens": 1200,',
    '  "output_tokens": 340,',
    '  "step_count": 3',
    "}",
]


def sample_thread(label="build_T001", is_error=False, output=None):
    """The DbThread layout a live eval-cli wrote: typed tool input, tool_results keyed by call id
    with a structured output."""
    if output is None:
        output = {"session_id": "sess-child-1", "output": "done"}
    return {"messages": [
        {"User": {"content": [{"Text": "/gsd-path"}]}},
        {"Agent": {
            "content": [{"ToolUse": {"id": "tu-1", "name": "spawn_agent",
                                     "input": {"type": "json", "value": {"label": label, "message": "brief text"}}}}],
            "tool_results": {"tu-1": {"tool_use_id": "tu-1", "is_error": is_error,
                                      "content": [{"Text": json.dumps(output)}], "output": output}},
        }},
    ]}


class ZedSpecTests(unittest.TestCase):
    def test_spec_matches_manifest_facts(self):
        s = zed.SPEC
        self.assertEqual((s.name, s.install_flag, s.skill_root, s.invocation, s.child_api, s.guard_tier),
                         ("zed", "--zed", ".agents/skills", "/gsd-path", "spawn_agent", "git-only"))
        self.assertTrue(s.verified_live)
        self.assertTrue(s.prompt_on_stdin)
        self.assertIn("Verified live", s.notes)

    def test_command_writes_beside_the_prompt_and_has_no_resume_flag(self):
        env = {"ZED_EVAL_CLI": "/opt/eval-cli", "ZED_EVAL_MODEL": "openrouter/x"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            args = zed.command(Path("/runs/run-1/prompt.txt"))
        self.assertEqual(args, ["/opt/eval-cli", "--workdir", ".", "--output-dir", "/runs/run-1", "--model", "openrouter/x"])
        with unittest.mock.patch.dict(os.environ, {"ZED_EVAL_CLI": "/opt/eval-cli"}, clear=True):
            resumed = zed.command(Path("/runs/run-2/prompt.txt"), "thread-1")
        self.assertEqual(resumed, ["/opt/eval-cli", "--workdir", ".", "--output-dir", "/runs/run-2"])


class ZedParseEventsTests(unittest.TestCase):
    def test_empty_stdout_yields_no_values(self):
        parsed = zed.parse_events([])
        self.assertEqual(parsed["session_id"], None)
        self.assertEqual(parsed["final_message"], None)
        self.assertEqual(parsed["usage"], None)
        self.assertEqual(parsed["status"], None)
        self.assertEqual(parsed["subagent_sessions"], [])

    def test_result_lines_yield_usage_status_and_subagents_only(self):
        parsed = zed.parse_events(RESULT_STDERR)
        self.assertEqual(parsed["usage"], {"input_tokens": 1200, "output_tokens": 340})
        self.assertEqual(parsed["status"], "completed")
        self.assertEqual(parsed["subagent_sessions"], ["sess-child-1"])
        self.assertIsNone(parsed["session_id"])
        self.assertIsNone(parsed["final_message"])

    def test_unparseable_result_is_not_invented(self):
        parsed = zed.parse_events(["[eval-cli] result: {", '  "status": "completed"'])
        self.assertIsNone(parsed["usage"])
        self.assertIsNone(parsed["status"])


class ZedBindChildTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def write_thread(self, thread, run="run-1"):
        d = self.root / "quick" / run
        d.mkdir(parents=True)
        (d / "thread.json").write_text(json.dumps(thread))

    def test_binds_completed_child_by_label(self):
        self.write_thread(sample_thread())
        out = zed.bind_child(self.root, "build_T001")
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["child_api"], "spawn_agent")
        self.assertEqual(out["child_session_id"], "sess-child-1")
        self.assertEqual(out["tool_use"]["id"], "tu-1")
        self.assertNotIn("message", out["tool_use"]["input"])
        self.assertEqual(len(out["tool_use"]["prompt_sha256"]), 64)
        self.assertEqual(out["run"], "run-1")

    def test_missing_thread_json_raises(self):
        with self.assertRaises(LookupError) as ctx:
            zed.bind_child(self.root, "build_T001")
        self.assertIn("thread.json", str(ctx.exception))

    def test_unknown_label_raises(self):
        self.write_thread(sample_thread(label="build_T002"))
        with self.assertRaises(LookupError):
            zed.bind_child(self.root, "build_T001")

    def test_error_result_raises(self):
        self.write_thread(sample_thread(is_error=True, output={"error": "boom"}))
        with self.assertRaises(LookupError):
            zed.bind_child(self.root, "build_T001")

    def test_error_payload_without_is_error_flag_raises(self):
        self.write_thread(sample_thread(output={"session_id": "s", "error": "boom"}))
        with self.assertRaises(LookupError):
            zed.bind_child(self.root, "build_T001")


if __name__ == "__main__":
    unittest.main()
