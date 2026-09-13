import json
import os
import sys
from datetime import datetime, timezone
import tempfile
import unittest
from unittest import mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))
from gsd_daemon import sessions


def codex_rollout(cwd: str, model: str = "gpt-6-astra", prompt: str = "$gsd-path-build T006 please") -> str:
    turn = "turn-1"
    lines = [
        {"timestamp": "2026-09-10T10:00:00.000Z", "type": "session_meta", "payload": {"cwd": cwd, "originator": "codex_exec"}},
        {"timestamp": "2026-09-10T10:00:01.000Z", "type": "event_msg", "payload": {"type": "task_started", "turn_id": turn, "started_at": datetime(2026, 9, 10, 10, 0, 1, tzinfo=timezone.utc).timestamp()}},
        {"timestamp": "2026-09-10T10:00:02.000Z", "type": "turn_context", "payload": {"turn_id": turn, "cwd": cwd, "model": model}},
        {"timestamp": "2026-09-10T10:00:03.000Z", "type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}]}},
        {"timestamp": "2026-09-10T10:00:31.000Z", "type": "token_usage_record", "payload": {"turn_id": turn, "usage": {"input_tokens": 1000, "cached_input_tokens": 400, "output_tokens": 50}}},
        {"timestamp": "2026-09-10T10:01:01.000Z", "type": "token_usage_record", "payload": {"turn_id": turn, "usage": {"input_tokens": 2000, "cached_input_tokens": 1500, "output_tokens": 100}}},
        "not json",
    ]
    return "\n".join(json.dumps(line) if not isinstance(line, str) else line for line in lines) + "\n"


def claude_transcript(cwd: str) -> str:
    lines = [
        {"type": "user", "cwd": cwd, "timestamp": "2026-09-01T09:00:00.000Z", "uuid": "u1", "message": {"role": "user", "content": "$gsd-path-plan the thing"}},
        {"type": "assistant", "cwd": cwd, "timestamp": "2026-09-01T09:00:05.000Z", "uuid": "a1", "parentUuid": "u1", "isSidechain": False,
         "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 10, "cache_creation_input_tokens": 90, "cache_read_input_tokens": 300, "output_tokens": 20}}},
        {"type": "assistant", "cwd": cwd, "timestamp": "2026-09-01T09:00:09.000Z", "uuid": "a2", "parentUuid": "u1", "isSidechain": True,
         "message": {"model": "claude-sonnet-5", "usage": {"input_tokens": 5, "cache_read_input_tokens": 0, "output_tokens": 7}}},
    ]
    return "\n".join(json.dumps(line) for line in lines) + "\n"


class SessionParseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = str(self.base / "proj")
        (self.base / "proj").mkdir()

    def test_codex_records_model_agent_tokens_and_duration(self) -> None:
        path = self.base / "rollout.jsonl"
        path.write_text(codex_rollout(self.root), encoding="utf-8")
        cwd, records = sessions.parse_session(path)
        self.assertEqual(cwd, self.root)
        self.assertEqual(len(records), 2)
        first, second = records
        self.assertEqual(first["model"], "gpt-6-astra")
        self.assertEqual(first["agent"], "$gsd-path-build · T006")
        self.assertEqual((first["tokens_in"], first["tokens_cached"], first["tokens_out"]), (600, 400, 50))
        self.assertEqual(first["duration_s"], 30.0)   # task_started -> first record
        self.assertEqual(second["duration_s"], 30.0)  # previous record -> this one
        self.assertEqual(first["host"], "codex")

    def test_claude_records_cache_creation_as_input_and_marks_subagents(self) -> None:
        path = self.base / "transcript.jsonl"
        path.write_text(claude_transcript(self.root + "/sub"), encoding="utf-8")
        cwd, records = sessions.parse_session(path)
        self.assertEqual(cwd, self.root + "/sub")
        self.assertEqual([r["tokens_in"] for r in records], [100, 5])
        self.assertEqual(records[0]["tokens_cached"], 300)
        self.assertEqual(records[0]["agent"], "$gsd-path-plan")
        self.assertEqual(records[1]["agent"], "$gsd-path-plan · subagent")
        self.assertEqual(records[0]["host"], "claude")
        self.assertIsNone(records[0]["duration_s"])

    def test_cost_uses_price_table_per_million(self) -> None:
        prices = {"gpt-6-astra": {"input": 1.0, "cached": 0.1, "output": 10.0}}
        self.assertAlmostEqual(sessions.cost_for(prices, "gpt-6-astra", 1_000_000, 1_000_000, 100_000), 2.1)
        self.assertIsNone(sessions.cost_for(prices, "unknown-model", 1, 1, 1))
        self.assertIsNone(sessions.cost_for({}, "gpt-6-astra", 1, 1, 1))


class SessionIndexTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = str(self.base / "proj")
        (self.base / "proj").mkdir()
        self.codex = self.base / "codex" / "2026" / "09" / "10"
        self.codex.mkdir(parents=True)
        (self.codex / "a.jsonl").write_text(codex_rollout(self.root), encoding="utf-8")
        (self.codex / "other.jsonl").write_text(codex_rollout(str(self.base / "elsewhere")), encoding="utf-8")
        self.claude = self.base / "claude" / "-proj"
        self.claude.mkdir(parents=True)
        (self.claude / "t.jsonl").write_text(claude_transcript(self.root + "/worktree"), encoding="utf-8")
        self.index = sessions.SessionIndex([str(self.base / "codex"), str(self.base / "claude")],
                                           prices={"gpt-6-astra": {"input": 1.0, "cached": 0.1, "output": 10.0}})

    def test_scan_parses_only_matching_roots_and_caches(self) -> None:
        self.index.scan([self.root])
        parsed = set(Path(p).name for p in self.index._parsed)
        self.assertEqual(parsed, {"a.jsonl", "t.jsonl"})
        self.assertEqual(len(self.index.records_for(self.root)), 4)
        stamp_before = self.index._parsed[str(self.codex / "a.jsonl")][0]
        self.index.scan([self.root])
        self.assertEqual(self.index._parsed[str(self.codex / "a.jsonl")][0], stamp_before)
        # A grown file is re-parsed.
        with (self.codex / "a.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"timestamp": "2026-09-10T10:02:00.000Z", "type": "token_usage_record",
                                     "payload": {"turn_id": "turn-1", "usage": {"input_tokens": 10, "cached_input_tokens": 0, "output_tokens": 1}}}) + "\n")
        self.index.scan([self.root])
        self.assertEqual(len(self.index.records_for(self.root)), 5)

    def test_spend_totals_models_agents_and_milestones(self) -> None:
        self.index.scan([self.root])
        milestones = [{"number": "M001", "manifest": {"shipped": "2026-09-05"}}, {"number": "M002", "manifest": None}]
        spend = self.index.spend_for(self.root, milestones, current="M002")
        self.assertEqual(spend["turns"], 4)
        self.assertEqual(spend["prompts"], 2)
        self.assertEqual((spend["tokens_in"], spend["tokens_cached"], spend["tokens_out"]), (600 + 500 + 100 + 5, 400 + 1500 + 300, 50 + 100 + 20 + 7))
        # Only the Codex model is priced: (600*1 + 400*.1 + 50*10)/1e6 + (500*1 + 1500*.1 + 100*10)/1e6
        self.assertAlmostEqual(spend["cost"], round((600 + 40 + 500 + 500 + 150 + 1000) / 1e6, 2))
        self.assertEqual(spend["unpriced"], ["claude-sonnet-5"])
        self.assertEqual([m["model"] for m in spend["models"]], ["gpt-6-astra", "claude-sonnet-5"])
        self.assertEqual(spend["models"][1]["host"], "claude")
        self.assertIsNone(spend["models"][1]["cost"])
        self.assertAlmostEqual(spend["models"][0]["cost"], spend["cost"])
        agents = {a["agent"]: a for a in spend["agents"]}
        self.assertEqual(agents["$gsd-path-build · T006"]["turns"], 2)
        self.assertEqual(agents["$gsd-path-plan · subagent"]["turns"], 1)
        self.assertIsNone(agents["$gsd-path-plan · subagent"]["cost"])
        # Claude turns are dated Sep 1, before M001 shipped; Codex turns are current.
        self.assertEqual(spend["milestones"]["M001"]["turns"], 2)
        self.assertEqual(spend["milestones"]["M002"]["turns"], 2)
        self.assertIsNone(spend["milestones"]["M001"]["cost"])   # only unpriced Claude turns
        self.assertAlmostEqual(spend["milestones"]["M002"]["cost"], spend["cost"])
        self.assertEqual(spend["recent"][0]["at"], "2026-09-10T10:01:01.000Z")
        self.assertEqual(spend["recent"][0]["cost"], round((500 + 150 + 1000) / 1e6, 4))

    def test_cwd_cache_persists_across_instances(self) -> None:
        cache = self.base / "state" / "sessions-index.json"
        first = sessions.SessionIndex([str(self.base / "codex"), str(self.base / "claude")], cache_path=cache)
        first.scan([self.root])
        saved = json.loads(cache.read_text(encoding="utf-8"))
        self.assertEqual(saved[str(self.codex / "other.jsonl")], str(self.base / "elsewhere"))
        # A fresh index must not re-read any file head: make head reads fail loudly.
        original = sessions._read_head_cwd
        sessions._read_head_cwd = lambda path: (_ for _ in ()).throw(AssertionError("head re-read " + str(path)))
        try:
            second = sessions.SessionIndex([str(self.base / "codex"), str(self.base / "claude")], cache_path=cache)
            second.scan([self.root])
        finally:
            sessions._read_head_cwd = original
        self.assertEqual(len(second.records_for(self.root)), 4)
        # A corrupt cache is ignored, not fatal.
        cache.write_text("{not json", encoding="utf-8")
        third = sessions.SessionIndex([str(self.base / "codex")], cache_path=cache)
        third.scan([self.root])
        self.assertEqual(len(third.records_for(self.root)), 2)

    def test_unresolved_head_retries_only_after_file_changes(self) -> None:
        for change in ("size", "mtime"):
            with self.subTest(change=change):
                path = self.codex / "a.jsonl"
                content = codex_rollout(self.root)
                path.write_text(" " * len(content) if change == "mtime" else "", encoding="utf-8")
                index = sessions.SessionIndex([str(self.codex)])
                with mock.patch.object(sessions, "_read_head_cwd", wraps=sessions._read_head_cwd) as read:
                    index.scan([self.root])
                    self.assertEqual(index.records_for(self.root), [])
                    read.reset_mock()
                    index.scan([self.root])
                    read.assert_not_called()
                    before = path.stat()
                    path.write_text(content, encoding="utf-8")
                    mtime = before.st_mtime_ns + 1_000_000_000 if change == "mtime" else before.st_mtime_ns
                    os.utime(path, ns=(before.st_atime_ns, mtime))
                    index.scan([self.root])
                    self.assertEqual(len(index.records_for(self.root)), 2)
                    read.assert_called_once_with(path)

    def test_persisted_unresolved_head_is_retried_on_restart(self) -> None:
        cache = self.base / "sessions-index.json"
        path = self.codex / "a.jsonl"
        other = self.codex / "other.jsonl"
        cache.write_text(json.dumps({str(path): None, str(other): str(self.base / "elsewhere")}), encoding="utf-8")
        index = sessions.SessionIndex([str(self.codex)], cache_path=cache)
        with mock.patch.object(sessions, "_read_head_cwd", wraps=sessions._read_head_cwd) as read:
            index.scan([self.root])
            read.assert_called_once_with(path)
        self.assertEqual(len(index.records_for(self.root)), 2)
        self.assertEqual(json.loads(cache.read_text())[str(path)], self.root)

    def test_spend_is_none_without_records(self) -> None:
        self.index.scan([str(self.base / "nothing")])
        self.assertIsNone(self.index.spend_for(str(self.base / "nothing"), [], "M001"))

    def test_expand_session_dirs_keeps_existing_only(self) -> None:
        found = sessions.expand_session_dirs([str(self.base / "codex"), str(self.base / "c*"), str(self.base / "missing")])
        self.assertEqual(found, [str(self.base / "codex"), str(self.base / "claude")])


if __name__ == "__main__":
    unittest.main()
