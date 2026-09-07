"""Zed host module tests on documentation-derived samples.

UNVERIFIED AGAINST A LIVE HOST: Zed is not installed on the authoring machine. The
samples below follow the shapes read from the Zed sources cited in tests/hosts/zed.py
(eval-cli result/stderr lines, spawn_agent input/output, DbThread tool uses/results);
they are not recordings.
"""

import json
import tempfile
import unittest
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


def sample_thread(label="build_T001", is_error=False, content=None):
    if content is None:
        content = json.dumps({"session_id": "sess-child-1", "output": "done"})
    return {
        "title": "sample",
        "messages": [
            {"User": {"content": [{"Text": "/gsd-path"}]}},
            {"Agent": {
                "content": [{"ToolUse": {"id": "tu-1", "name": "spawn_agent",
                                         "input": {"label": label, "message": "brief text"}}}],
                "tool_results": {"tu-1": {"tool_use_id": "tu-1", "tool_name": "spawn_agent",
                                          "is_error": is_error, "content": content}},
            }},
        ],
    }


class ZedSpecTests(unittest.TestCase):
    def test_spec_matches_manifest_facts(self):
        s = zed.SPEC
        self.assertEqual((s.name, s.install_flag, s.skill_root, s.invocation, s.child_api, s.guard_tier),
                         ("zed", "--zed", ".agents/skills", "/gsd-path", "spawn_agent", "git-only"))
        self.assertFalse(s.verified_live)
        self.assertIn("not installed", s.notes)

    def test_command_raises_with_reason_and_alternative(self):
        with self.assertRaises(NotImplementedError) as ctx:
            zed.SPEC.command(Path("/tmp/prompt.txt"), None)
        self.assertIn("eval-cli", str(ctx.exception))
        self.assertIn("ACP client", str(ctx.exception))
        with self.assertRaises(NotImplementedError) as ctx:
            zed.SPEC.command(Path("/tmp/prompt.txt"), "sess-1")
        self.assertIn("cannot resume", str(ctx.exception))


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
        self.write_thread(sample_thread(is_error=True, content=json.dumps({"error": "boom"})))
        with self.assertRaises(LookupError):
            zed.bind_child(self.root, "build_T001")

    def test_error_payload_without_is_error_flag_raises(self):
        self.write_thread(sample_thread(content=json.dumps({"session_id": "s", "error": "boom"})))
        with self.assertRaises(LookupError):
            zed.bind_child(self.root, "build_T001")


if __name__ == "__main__":
    unittest.main()
