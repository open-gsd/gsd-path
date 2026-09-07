"""Offline tests for Codex rollout receipt binding."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.hosts import codex


def spawn(call, name, compact=False):
    args = {"task_name": "build_T001", "message": "brief"}
    return [
        {"type": "function_call", "name": "spawn_agent", "call_id": call,
         "arguments": json.dumps(args, separators=(",", ":") if compact else None)},
        {"type": "function_call_output", "call_id": call, "output": json.dumps({"task_name": name})},
    ]


def listing(name, status="completed"):
    return [
        {"type": "function_call", "name": "list_agents", "call_id": "list"},
        {"type": "function_call_output", "call_id": "list", "output": json.dumps({"agents": [
            {"agent_name": name, "agent_status": status}]})},
    ]


class CodexBindChildTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        events = self.root / "quick" / "run-1" / "events.jsonl"
        events.parent.mkdir(parents=True)
        events.write_text(json.dumps({"raw": json.dumps({"type": "thread.started", "thread_id": "thread"})}))
        self.transcript = self.root / "rollout-thread.jsonl"
        patcher = mock.patch.object(codex, "SESSION_ROOTS", (self.root,))
        patcher.start()
        self.addCleanup(patcher.stop)

    def bind(self, records):
        self.transcript.write_text("".join(json.dumps({"payload": p}) + "\n" for p in records))
        return codex.bind_child(self.root, "build_T001")

    def test_arguments_allow_json_whitespace(self):
        name = "/root/build_T001"
        bound = self.bind(spawn("first", name) + listing(name))
        self.assertEqual(bound["spawn_call"]["call_id"], "first")
        self.assertNotIn("message", bound["spawn_call"]["arguments"])
        self.assertEqual(bound["agent_name"], name)

    def test_retry_does_not_inherit_completed_attempt(self):
        first, second = "/root/first/build_T001", "/root/second/build_T001"
        records = spawn("first", first, compact=True) + listing(first)
        records += spawn("second", second, compact=True) + listing(second, "running")
        bound = self.bind(records)
        self.assertEqual(bound["spawn_call"]["call_id"], "first")
        self.assertEqual(json.loads(bound["spawn_output"])["task_name"], first)
        self.assertEqual([s["agent_name"] for s in bound["list_agents_states"]], [first])

    def test_completion_for_same_suffix_does_not_bind_other_child(self):
        with self.assertRaises(LookupError):
            self.bind(spawn("second", "/root/second/build_T001", compact=True)
                      + listing("/root/first/build_T001"))

    def test_completed_retry_is_selected(self):
        first, second = "/root/first/build_T001", "/root/second/build_T001"
        bound = self.bind(spawn("first", first) + listing(first, "running")
                          + spawn("second", second) + listing(second, {"completed": "ok"}))
        self.assertEqual(bound["spawn_call"]["call_id"], "second")
        self.assertEqual(json.loads(bound["spawn_output"])["task_name"], second)

    def test_missing_child_identity_cannot_bind(self):
        records = spawn("first", None) + listing("/root/build_T001")
        with self.assertRaises(LookupError):
            self.bind(records)
