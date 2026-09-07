import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hosts import kimi

SESSION = "session_ba7b8575-ebed-451e-b757-60fd944aea1b"
PROMPT = "create the file /probe/probe.txt containing the single line hello, then report done"
CALL = {"role": "assistant", "tool_calls": [{"type": "function", "id": "tool_9siOSTCz6uwyDBoVV3SYclXR", "function": {
    "name": "Agent", "arguments": json.dumps({"subagent_type": "coder", "description": "build_probe", "prompt": PROMPT})}}]}
RESULT_TEXT = ("agent_id: agent-0\nactual_subagent_type: coder\nstatus: completed\nstop_reason: completed\n\n"
               "[summary]\nDone. Created `probe.txt` containing the single line `hello`.\n\n"
               "resume_hint: Continue with Agent(resume=\"agent-0\", prompt=\"...\").")
RESULT = {"role": "tool", "tool_call_id": "tool_9siOSTCz6uwyDBoVV3SYclXR", "content": RESULT_TEXT}
HINT = {"role": "meta", "type": "session.resume_hint", "session_id": SESSION, "command": f"kimi -r {SESSION}",
        "content": f"To resume this session: kimi -r {SESSION}"}
LINES = [
    json.dumps({"role": "meta", "type": "system.version", "version": "0.41.0"}),
    json.dumps(CALL), json.dumps(RESULT), json.dumps({"role": "assistant", "content": "child done"}), json.dumps(HINT),
]


def write_run(root, lines, name="run-20260906T000000000000Z"):
    run = Path(root) / "quick" / name
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text("".join(json.dumps({"elapsed_seconds": i, "raw": line}) + "\n" for i, line in enumerate(lines)))
    return run


class KimiSpecTests(unittest.TestCase):
    def test_spec_matches_manifest_facts(self):
        self.assertEqual((kimi.SPEC.name, kimi.SPEC.install_flag, kimi.SPEC.skill_root), ("kimi", "--kimi", ".kimi-code/skills"))
        self.assertEqual((kimi.SPEC.child_api, kimi.SPEC.guard_tier, kimi.SPEC.invocation), ("Agent", "git-only", "/gsd-path"))
        self.assertFalse(kimi.SPEC.prompt_on_stdin)

    def test_command_puts_prompt_text_on_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("Reply with exactly: ok\n")
            args = kimi.command(prompt)
            self.assertEqual(args[1:], ["-p", "Reply with exactly: ok\n", "--output-format", "stream-json"])
            resumed = kimi.command(prompt, SESSION)
            self.assertEqual(resumed[1:3], ["-S", SESSION])
            self.assertEqual(resumed[3:], args[1:])


class ParseEventsTests(unittest.TestCase):
    def test_reads_session_id_and_final_reply(self):
        self.assertEqual(kimi.parse_events(LINES), {"session_id": SESSION, "final_message": "child done", "usage": None})

    def test_skips_non_json_and_reports_nothing_invented(self):
        self.assertEqual(kimi.parse_events(["kimi version 0.41.0", "", "not json"]),
                         {"session_id": None, "final_message": None, "usage": None})


class BindChildTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)

    def test_binds_completed_agent_child_by_description(self):
        write_run(self.root, LINES)
        with mock.patch.object(kimi, "SESSION_ROOT", self.root / "no-store"):
            bound = kimi.bind_child(self.root, "build_probe")
        self.assertEqual((bound["child_id"], bound["status"], bound["child_api"]), ("build_probe", "completed", "Agent"))
        self.assertEqual(bound["session_id"], SESSION)
        self.assertEqual(bound["run"], "run-20260906T000000000000Z")
        self.assertEqual(bound["tool_call"]["input"], {"subagent_type": "coder", "description": "build_probe"})
        self.assertEqual(bound["tool_call"]["prompt_sha256"], hashlib.sha256(PROMPT.encode()).hexdigest())
        self.assertEqual({k: bound["tool_result"][k] for k in ("agent_id", "actual_subagent_type", "status", "stop_reason")},
                         {"agent_id": "agent-0", "actual_subagent_type": "coder", "status": "completed", "stop_reason": "completed"})
        self.assertIsNone(bound["session_store"])

    def test_includes_session_store_evidence_when_recorded(self):
        write_run(self.root, LINES)
        store = self.root / "store"
        session_dir = store / "wd_child_3ef6642a9053" / SESSION
        (session_dir / "agents" / "agent-0").mkdir(parents=True)
        (session_dir / "state.json").write_text(json.dumps({"id": SESSION, "agents": {
            "main": {"type": "main"},
            "agent-0": {"type": "sub", "parentAgentId": "main", "labels": {"parentAgentId": "main", "profileName": "coder"}}}}))
        (session_dir / "agents" / "agent-0" / "wire.jsonl").write_text(
            json.dumps({"type": "metadata", "protocol_version": "1.5"}) + "\n"
            + json.dumps({"type": "turn.ended", "agentId": "agent-0", "turnId": 0, "reason": "completed", "durationMs": 9070}) + "\n")
        with mock.patch.object(kimi, "SESSION_ROOT", store):
            bound = kimi.bind_child(self.root, "build_probe")
        self.assertEqual(bound["session_store"], {"state": SESSION, "type": "sub", "turn_ended_reasons": ["completed"],
                                                  "labels": {"parentAgentId": "main", "profileName": "coder"}})

    def test_unknown_description_raises_lookup_error(self):
        write_run(self.root, LINES)
        with self.assertRaises(LookupError) as raised:
            kimi.bind_child(self.root, "build_T001")
        self.assertIn("build_T001", str(raised.exception))

    def test_child_that_did_not_complete_raises_lookup_error(self):
        failed = dict(RESULT, content=RESULT_TEXT.replace("status: completed", "status: failed"))
        write_run(self.root, [json.dumps(CALL), json.dumps(failed), json.dumps(HINT)])
        with self.assertRaises(LookupError):
            kimi.bind_child(self.root, "build_probe")

    def test_call_without_result_raises_lookup_error(self):
        write_run(self.root, [json.dumps(CALL), json.dumps(HINT)])
        with self.assertRaises(LookupError):
            kimi.bind_child(self.root, "build_probe")


if __name__ == "__main__":
    unittest.main()
