import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hosts import kiro

PARENT = "c0457f16-361c-42d1-a5f0-2480a4b68c58"
CHILD = "6a80049c-0a44-4e1f-a06c-3720fc6d9202"
CALL = "tooluse_igCUAjIWPbAYHzNB0maO63"

# Recorded 2026-09-06 with kiro-cli 2.21.1 (child probe), trimmed.
CHILD_RUN = [
    '{"type":"runStarted","data":{"payloadSchema":"acp","acpProtocolVersion":1,"engine":"v2"}}',
    '{"type":"metadata","data":{"sessionId":"%s","contextUsagePercentage":38.35}}' % PARENT,
    '{"type":"sessionUpdate","data":{"sessionId":"%s","update":{"sessionUpdate":"tool_call","toolCallId":"%s","title":"Spawning agent crew",'
    '"rawInput":{"__tool_use_purpose":"Launch a single subagent named build_probe with the specified prompt","task":"build_probe",'
    '"stages":[{"name":"build_probe","role":"kiro_default","prompt_template":"Reply with exactly: done"}],"mode":"blocking"},'
    '"_meta":{"kiro":{"toolName":"subagent"}}}}}' % (PARENT, CALL),
    '{"type":"sessionUpdate","data":{"sessionId":"%s","update":{"sessionUpdate":"tool_call_update","toolCallId":"%s","content":[{"type":"content","content":{"type":"text","text":"Running crew pipeline (1 stages)..."}}]}}}' % (PARENT, CALL),
    '{"type":"sessionUpdate","data":{"sessionId":"%s","update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"done"}}}}' % CHILD,
    '{"type":"metadata","data":{"sessionId":"%s","contextUsagePercentage":9.12,"meteringUsage":[{"value":0.29,"unit":"credit","unitPlural":"credits"}],"turnDurationMs":4738}}' % CHILD,
    '{"type":"sessionUpdate","data":{"sessionId":"%s","update":{"sessionUpdate":"tool_call_update","toolCallId":"%s","kind":"other","status":"completed","title":"Spawning agent crew",'
    '"rawInput":{"task":"build_probe","stages":[{"name":"build_probe","role":"kiro_default","prompt_template":"Reply with exactly: done"}],"mode":"blocking"},'
    '"rawOutput":{"items":[{"Text":"Pipeline completed: 1 stages finished.\\n\\n## build_probe\\n\\ndone"}]}}}}' % (PARENT, CALL),
    '{"type":"sessionUpdate","data":{"sessionId":"%s","update":{"sessionUpdate":"agent_message_chunk","content":{"type":"text","text":"done"}}}}' % PARENT,
    '{"type":"metadata","data":{"sessionId":"%s","contextUsagePercentage":9.23,"meteringUsage":[{"value":0.30,"unit":"credit","unitPlural":"credits"},{"value":0.15,"unit":"credit","unitPlural":"credits"}],"turnDurationMs":11144}}' % PARENT,
    '{"type":"runFinished","data":{"sessionId":"%s","status":"success","stopReason":"end_turn","finalText":"donedone","finalTextTruncated":false}}' % PARENT,
]

# Recorded 2026-09-06: the v1 engine rejects stream-json.
V1_ERROR = ['{"type":"runError","data":{"sessionId":null,"stage":"engine","message":"--output-format stream-json is not supported on the v1 engine. Pass --agent-engine v2 (or v3)."}}']

# Recorded 2026-09-06: parent transcript ToolResults row and child session metadata, trimmed.
PARENT_TRANSCRIPT = ('{"version":"v1","kind":"ToolResults","data":{"message_id":"2c155d16","content":[{"kind":"toolResult","data":{"toolUseId":"%s",'
                     '"content":[{"kind":"text","data":"Pipeline completed: 1 stages finished.\\n\\n## build_probe\\n\\ndone"}],"status":"success"}}]}}\n' % CALL)
CHILD_META = {"session_id": CHILD, "cwd": "/x", "created_at": "2026-09-07T03:08:04Z", "updated_at": "2026-09-07T03:08:09Z",
              "parent_session_id": PARENT, "session_created_reason": "subagent"}


def write_run(root, lines, name="run-1"):
    run = Path(root) / "quick" / name
    run.mkdir(parents=True)
    (run / "events.jsonl").write_text("".join(json.dumps({"elapsed_seconds": i, "raw": l}) + "\n" for i, l in enumerate(lines)))
    return run


class KiroHostTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.no_store = mock.patch.object(kiro, "SESSION_ROOT", self.root / "absent")
        self.no_store.start()
        self.addCleanup(self.no_store.stop)

    def test_command_reads_prompt_on_stdin_and_resumes_by_session_id(self):
        self.assertTrue(kiro.SPEC.prompt_on_stdin)
        args = kiro.command(Path("/p"), None)
        self.assertEqual(args[:2], ["kiro-cli", "chat"])
        self.assertIn("--agent-engine", args)
        self.assertEqual(args[args.index("--agent-engine") + 1], "v2")
        self.assertIn("--no-interactive", args)
        self.assertEqual(args[args.index("--output-format") + 1], "stream-json")
        self.assertNotIn("--resume-id", args)
        self.assertEqual(kiro.command(Path("/p"), PARENT)[-2:], ["--resume-id", PARENT])

    def test_parse_events_keys_session_and_usage_on_the_parent_run(self):
        parsed = kiro.parse_events(CHILD_RUN)
        self.assertEqual(parsed["session_id"], PARENT)
        self.assertEqual(parsed["final_message"], "donedone")
        self.assertEqual(parsed["usage"]["turnDurationMs"], 11144)
        self.assertEqual(len(parsed["usage"]["meteringUsage"]), 2)

    def test_parse_events_reports_nothing_for_v1_engine_error(self):
        self.assertEqual(kiro.parse_events(V1_ERROR), {"session_id": None, "final_message": None, "usage": None})

    def test_bind_child_returns_completed_crew_evidence(self):
        write_run(self.root, CHILD_RUN)
        out = kiro.bind_child(self.root, "build_probe")
        self.assertEqual(out["status"], "completed")
        self.assertEqual(out["child_id"], "build_probe")
        self.assertEqual(out["child_api"], "subagent")
        self.assertEqual(out["session_id"], PARENT)
        self.assertEqual(out["run"], "run-1")
        self.assertEqual(out["tool_call"]["id"], CALL)
        self.assertEqual(out["tool_call"]["input"]["task"], "build_probe")
        self.assertEqual(out["tool_call"]["input"]["stages"], [{"name": "build_probe", "role": "kiro_default"}])
        self.assertNotIn("prompt_template", json.dumps(out["tool_call"]))
        self.assertEqual(len(out["tool_call"]["input"]["prompt_sha256"]), 64)
        self.assertEqual(out["tool_call_update"]["status"], "completed")
        self.assertIn("Pipeline completed: 1 stages finished.", out["tool_call_update"]["output"])
        self.assertNotIn("child_sessions", out)
        self.assertNotIn("transcript", out)

    def test_bind_child_adds_session_store_evidence_when_present(self):
        write_run(self.root, CHILD_RUN)
        store = self.root / "sessions"; store.mkdir()
        (store / f"{CHILD}.json").write_text(json.dumps(CHILD_META))
        (store / f"{PARENT}.json").write_text(json.dumps({"session_id": PARENT, "session_created_reason": "subagent"}))
        (store / f"{PARENT}.jsonl").write_text(PARENT_TRANSCRIPT)
        with mock.patch.object(kiro, "SESSION_ROOT", store):
            out = kiro.bind_child(self.root, "build_probe")
        self.assertEqual([c["session_id"] for c in out["child_sessions"]], [CHILD])
        self.assertEqual(out["child_sessions"][0]["session_created_reason"], "subagent")
        self.assertEqual(out["transcript"]["status"], "success")
        self.assertEqual(out["transcript"]["file"], f"{PARENT}.jsonl")
        self.assertIn("## build_probe", out["transcript"]["content"])

    def test_bind_child_unknown_name_raises(self):
        write_run(self.root, CHILD_RUN)
        with self.assertRaises(LookupError) as cm:
            kiro.bind_child(self.root, "build_T001")
        self.assertIn("build_T001", str(cm.exception))

    def test_bind_child_without_completed_update_raises(self):
        write_run(self.root, [l for l in CHILD_RUN if '"status":"completed"' not in l])
        with self.assertRaises(LookupError):
            kiro.bind_child(self.root, "build_probe")

    def test_spec_matches_manifest_facts(self):
        self.assertEqual((kiro.SPEC.name, kiro.SPEC.install_flag, kiro.SPEC.skill_root, kiro.SPEC.child_api, kiro.SPEC.guard_tier),
                         ("kiro", "--kiro", ".kiro/skills", "invoke_sub_agent", "git-only"))


if __name__ == "__main__":
    unittest.main()
