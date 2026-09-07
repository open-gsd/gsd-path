"""Antigravity host module tests.

The samples mirror the live ``agy`` 1.1.27 stream recorded on 2026-09-07 (see
``tests/hosts/antigravity.py``): a parent conversation that launches one
``invoke_subagent`` child, lists it with ``manage_subagents``, and ends with a
nested ``result`` envelope.
"""

import json
import tempfile
import unittest
from pathlib import Path

from tests.hosts import antigravity

INIT = {"event": "init", "conversation_id": "conv-parent", "init": {"cwd": "/w", "tools": ["invoke_subagent"]}}
RESULT = {"event": "result", "result": {"conversation_id": "conv-parent", "status": "SUCCESS", "response": "shipped",
          "usage": {"input_tokens": 10, "output_tokens": 5, "thinking_tokens": 1, "cache_read_tokens": 0, "total_tokens": 16}}}


def step(index, **fields):
    return {"event": "step_update", "step_update": {"conversation_id": "conv-parent", "step_index": index, **fields}}


def spawn(role, state="DONE", cid="conv-child", log_uri=None):
    sub = {"type_name": "self", "role": role, "initial_prompt": "secret brief", "conversation_id": cid}
    if log_uri:
        sub["log_uri"] = log_uri
    return step(2, state=state, step_type="subagent", tool_name="invoke_subagent", subagent_info={"subagents": [sub]})


def listing(cid="conv-child", state="idle"):
    entries = json.dumps([{"conversationId": cid, "state": state}])
    return step(6, state="DONE", step_type="tool", tool_name="manage_subagents",
                tool_info={"name": "manage_subagents", "parameters": {"Action": "list"}, "output": f"You have 1 active subagent(s):\n{entries}"})


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

    def transcript(self, last_status="DONE"):
        path = self.run_root / "child-transcript.jsonl"
        path.write_text(json.dumps({"step_index": 0, "type": "USER_INPUT", "status": "DONE", "content": "brief"}) + "\n"
                        + json.dumps({"step_index": 1, "type": "PLANNER_RESPONSE", "status": last_status, "content": "done"}) + "\n")
        return f"file://{path}"

    def test_spec_matches_manifest_facts(self):
        spec = antigravity.SPEC
        self.assertEqual((spec.name, spec.install_flag, spec.skill_root, spec.invocation, spec.child_api, spec.guard_tier),
                         ("antigravity", "--antigravity", ".agents/skills", "/gsd-path", "invoke_subagent", "git-only"))
        self.assertTrue(spec.verified_live)
        self.assertFalse(spec.prompt_on_stdin)
        self.assertIn("Verified live", spec.notes)

    def test_command_places_prompt_in_argv_and_resumes_by_conversation(self):
        prompt = self.run_root / "prompt.txt"
        prompt.write_text("/gsd-path\n\nrun quick")
        args = antigravity.command(prompt)
        self.assertEqual(args[:3], ["agy", "-p", "/gsd-path\n\nrun quick"])
        self.assertIn("stream-json", args)
        self.assertNotIn("--conversation", args)
        resumed = antigravity.command(prompt, "conv-parent")
        self.assertEqual(resumed[-2:], ["--conversation", "conv-parent"])

    def test_parse_events_reads_nested_result_envelope(self):
        lines = [json.dumps(INIT), "not json", json.dumps(step(1, state="ACTIVE", step_type="agent_response", text_delta="hi")), json.dumps(RESULT)]
        parsed = antigravity.parse_events(lines)
        self.assertEqual(parsed, {"session_id": "conv-parent", "final_message": "shipped", "usage": RESULT["result"]["usage"]})

    def test_parse_events_never_invents_values(self):
        self.assertEqual(antigravity.parse_events([]), {"session_id": None, "final_message": None, "usage": None})
        only_steps = antigravity.parse_events([json.dumps(step(1, state="ACTIVE", step_type="agent_response"))])
        self.assertEqual(only_steps, {"session_id": "conv-parent", "final_message": None, "usage": None})

    def test_bind_child_binds_spawn_to_listing(self):
        self.record([INIT, spawn("build_T001"), listing(), RESULT])
        bound = antigravity.bind_child(self.run_root, "build_T001")
        self.assertEqual((bound["child_id"], bound["status"], bound["child_api"], bound["child_conversation_id"]),
                         ("build_T001", "completed", "invoke_subagent", "conv-child"))
        self.assertEqual(bound["spawn"]["subagent"], {"type_name": "self", "role": "build_T001", "conversation_id": "conv-child"})
        self.assertEqual(bound["spawn"]["run"], "run-1")
        self.assertEqual(bound["listing"]["entry"]["state"], "idle")
        self.assertIsNone(bound["transcript"])

    def test_bind_child_accepts_child_transcript_as_completion(self):
        self.record([INIT, spawn("build_T001", log_uri=self.transcript()), RESULT])
        bound = antigravity.bind_child(self.run_root, "build_T001")
        self.assertEqual(bound["transcript"]["final_content"], "done")
        self.assertIsNone(bound["listing"])

    def test_bind_child_raises_without_spawn_for_role(self):
        self.record([INIT, spawn("build_T002"), listing(), RESULT])
        with self.assertRaisesRegex(LookupError, "build_T001"):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_when_spawn_step_is_not_done(self):
        self.record([INIT, spawn("build_T001", state="ACTIVE"), listing(), RESULT])
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_without_completion_evidence(self):
        self.record([INIT, spawn("build_T001", log_uri=self.transcript("ACTIVE")), listing(state="running"), RESULT])
        with self.assertRaisesRegex(LookupError, "wait for the child"):
            antigravity.bind_child(self.run_root, "build_T001")
        self.record([INIT, spawn("build_T001"), listing(cid="conv-other"), RESULT], run="run-2")
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")

    def test_missing_child_ids_cannot_produce_receipt(self):
        for index, cid in enumerate((None, "", "   ")):
            with self.subTest(cid=cid):
                self.record([spawn("build_T001", cid=cid)], run=f"run-{index}")
                with self.assertRaises(LookupError):
                    antigravity.bind_child(self.run_root, "build_T001")

    def test_bind_child_raises_on_empty_run_root(self):
        with self.assertRaises(LookupError):
            antigravity.bind_child(self.run_root, "build_T001")


if __name__ == "__main__":
    unittest.main()
