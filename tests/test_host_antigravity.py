"""Antigravity host module tests.

Every sample below is documentation-derived (see ``tests/hosts/antigravity.py``) and is
UNVERIFIED against a live ``agy`` CLI: the tests prove the parser's observable behaviour on
the documented event shapes, not that a real CLI produces them.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.hosts import antigravity

INIT = {"event": "init", "conversation_id": "conv-parent", "init": {"cwd": "/w", "tools": ["invoke_subagent"], "permission_mode": "skip"}}
RESULT = {"event": "result", "conversation_id": "conv-parent", "status": "SUCCESS", "response": "shipped",
          "usage": {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 1, "cache_read_tokens": 0, "total_tokens": 16}}


def step(index, **fields):
    return {"event": "step_update", "step_update": {"conversation_id": "conv-parent", "step_index": index, **fields}}


def spawn(role, state="DONE", output='{"conversation_id": "conv-child"}'):
    return step(3, state=state, step_type="tool", tool_name="invoke_subagent",
                tool_info={"name": "invoke_subagent", "parameters": {"TypeName": "self", "Workspace": "/w", "Role": role, "prompt": "secret brief"}, "output": output})


def done(cid="conv-child", status="done"):
    return step(9, state="DONE", step_type="checkpoint", subagent_info={"conversation_id": cid, "status": status})


class AntigravityHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.run_root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, events, run="run-1"):
        path = self.run_root / "quick" / run / "events.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text("".join(json.dumps({"elapsed_seconds": 0.0, "raw": json.dumps(ev)}) + "\n" for ev in events))

    def test_spec_matches_manifest_facts(self):
        spec = antigravity.SPEC
        self.assertEqual((spec.name, spec.install_flag, spec.skill_root, spec.invocation, spec.child_api, spec.guard_tier),
                         ("antigravity", "--antigravity", ".agents/skills", "/gsd-path", "invoke_subagent", "git-only"))
        self.assertFalse(spec.verified_live)
        self.assertFalse(spec.prompt_on_stdin)
        self.assertIn("Documentation-derived", spec.notes)

    def test_command_places_prompt_in_argv_and_resumes_by_conversation(self):
        prompt = self.run_root / "prompt.txt"
        prompt.write_text("/gsd-path\n\nrun quick")
        args = antigravity.command(prompt)
        self.assertEqual(args[:3], ["agy", "-p", "/gsd-path\n\nrun quick"])
        self.assertIn("stream-json", args)
        self.assertNotIn("--conversation", args)
        resumed = antigravity.command(prompt, "conv-parent")
        self.assertEqual(resumed[-2:], ["--conversation", "conv-parent"])

    def test_parse_events_reads_conversation_response_and_usage(self):
        lines = [json.dumps(INIT), "not json", json.dumps(step(1, state="ACTIVE", step_type="agent_response", text_delta="hi")), json.dumps(RESULT)]
        parsed = antigravity.parse_events(lines)
        self.assertEqual(parsed, {"session_id": "conv-parent", "final_message": "shipped", "usage": RESULT["usage"]})

    def test_parse_events_never_invents_values(self):
        self.assertEqual(antigravity.parse_events([]), {"session_id": None, "final_message": None, "usage": None})
        only_steps = antigravity.parse_events([json.dumps(step(1, state="ACTIVE", step_type="agent_response"))])
        self.assertEqual(only_steps, {"session_id": "conv-parent", "final_message": None, "usage": None})

    def test_bind_child_binds_spawn_to_done_subagent_info(self):
        self.record([INIT, spawn("build_T001"), done(), RESULT])
        bound = antigravity.bind_child(self.run_root, "build_T001")
        self.assertEqual((bound["child_id"], bound["status"], bound["child_api"], bound["child_conversation_id"]),
                         ("build_T001", "completed", "invoke_subagent", "conv-child"))
        self.assertEqual(bound["spawn"]["parameters"], {"TypeName": "self", "Workspace": "/w", "Role": "build_T001"})
        self.assertEqual(bound["spawn"]["run"], "run-1")
        self.assertEqual(bound["completion"]["subagent_info"]["status"], "done")

    def test_bind_child_accepts_documented_idle_state_and_plain_string_output(self):
        self.record([INIT, spawn("build_T001", output="conv-child"), done(status="Idle"), RESULT])
        self.assertEqual(antigravity.bind_child(self.run_root, "build_T001")["child_conversation_id"], "conv-child")

    def test_bind_child_raises_without_spawn_for_role(self):
        self.record([INIT, spawn("build_T002"), done(), RESULT])
        with self.assertRaisesRegex(LookupError, "build_T001"):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_when_spawn_step_is_not_done(self):
        self.record([INIT, spawn("build_T001", state="ACTIVE"), done(), RESULT])
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_without_completion_evidence(self):
        self.record([INIT, spawn("build_T001"), done(status="running"), RESULT])
        with self.assertRaisesRegex(LookupError, "undocumented"):
            antigravity.bind_child(self.run_root, "build_T001")
        self.record([INIT, spawn("build_T001"), done(cid="conv-other"), RESULT], run="run-2")
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_missing_child_ids_cannot_produce_receipt(self):
        for index, output in enumerate((None, {}, "", "   ", {"conversation_id": ""})):
            with self.subTest(output=output):
                self.record([spawn("build_T001", output=output), done(cid=None)], run=f"run-{index}")
                with self.assertRaises(LookupError):
                    antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_on_empty_run_root(self):
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")


if __name__ == "__main__":
    unittest.main()
