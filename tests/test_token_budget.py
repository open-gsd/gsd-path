import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/token_budget.py"


class TokenBudgetTests(unittest.TestCase):
    def run_cli(self, root, *args):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), *args,
                               "--ledger", str(root / "budget.json")],
                              capture_output=True, text=True)

    def test_usage_survives_resume_and_duplicate_observation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            configured = self.run_cli(root, "configure", "--task-limit", "4000", "--session-limit", "30000",
                                      "--authority", "owner policy")
            self.assertEqual(configured.returncode, 0, configured.stderr)
            for index, usage in enumerate((3000, 1100)):
                event = root / f"run-{index}.jsonl"
                event.write_text(json.dumps({"type": "turn.completed", "usage": {"output_tokens": usage,
                    "input_tokens": 10000, "reasoning_output_tokens": 100}}) + "\n")
                for _ in range(2):
                    record = self.run_cli(root, "record", "--task", "plan", "--events", str(event))
                    self.assertEqual(record.returncode, 0, record.stderr)
            admission = self.run_cli(root, "admit", "--task", "plan")
            self.assertNotEqual(admission.returncode, 0)
            report = json.loads(admission.stdout)
            self.assertEqual(report["task_output_tokens"], 4100)
            self.assertEqual(report["session_output_tokens"], 4100)
            self.assertFalse(report["hard_cap_supported"])
            self.assertEqual(report["decision"], "blocked")

    def test_strict_cap_is_not_claimed_for_codex_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_cli(root, "configure", "--task-limit", "4000", "--session-limit", "30000",
                         "--authority", "owner policy")
            result = self.run_cli(root, "admit", "--task", "build_t001", "--require-hard-cap")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unsupported", json.loads(result.stdout)["reason"])

    def test_cumulative_resume_records_only_new_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_cli(root, 'configure', '--task-limit', '4000', '--session-limit', '30000',
                         '--authority', 'owner policy')
            first, second = root / 'first.jsonl', root / 'second.jsonl'
            for path, total in ((first, 3000), (second, 4100)):
                path.write_text('\n'.join(json.dumps(event) for event in [
                    {'type': 'thread.started', 'thread_id': 'same-thread'},
                    {'type': 'turn.completed', 'usage': {'output_tokens': total}}]))
            self.assertEqual(self.run_cli(root, 'record', '--task', 'inspect', '--events', str(first)).returncode, 0)
            for _ in range(2):
                result = self.run_cli(root, 'record', '--task', 'define', '--events', str(second),
                                      '--previous-events', str(first))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            admission = json.loads(self.run_cli(root, 'admit', '--task', 'define').stdout)
            self.assertEqual(admission['session_output_tokens'], 4100)
            self.assertEqual(admission['task_output_tokens'], 1100)
            self.assertEqual(admission['decision'], 'admit')
            saved = (root / 'budget.json').read_bytes()
            first.write_text(first.read_text().replace('3000', '3500'))
            result = self.run_cli(root, 'record', '--task', 'inspect', '--events', str(first))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'budget.json').read_bytes(), saved)
            first.write_text(first.read_text().replace('3500', '3000'))
            second.write_text(second.read_text().replace('same-thread', 'other-thread'))
            result = self.run_cli(root, 'record', '--task', 'define', '--events', str(second),
                                  '--previous-events', str(first))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((root / 'budget.json').read_bytes(), saved)

    def test_session_exhaustion_blocks_a_new_task(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_cli(root, "configure", "--task-limit", "4000", "--session-limit", "30000",
                         "--authority", "owner policy")
            event = root / "events.jsonl"
            event.write_text(json.dumps({"type": "turn.completed", "usage": {"output_tokens": 30000}}) + "\n")
            self.run_cli(root, "record", "--task", "orchestrator", "--events", str(event))
            result = self.run_cli(root, "admit", "--task", "new_task")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)["session_remaining"], 0)

    def test_incomplete_usage_blocks_recording_without_changing_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.run_cli(root, "configure", "--task-limit", "4000", "--session-limit", "30000",
                         "--authority", "owner policy")
            before = (root / "budget.json").read_bytes()
            event = root / "incomplete.jsonl"
            event.write_text(json.dumps({"type": "thread.started", "thread_id": "x"}) + "\n")
            result = self.run_cli(root, "record", "--task", "plan", "--events", str(event))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, (root / "budget.json").read_bytes())

    def test_native_child_and_evaluator_wrapped_events(self):
        from scripts import token_budget
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            child = root / "child.jsonl"
            events = [
                {"type": "session_meta", "payload": {"source": {"subagent": {"thread_spawn": {}}}}},
                {"type": "event_msg", "payload": {"type": "task_started"}},
                {"type": "event_msg", "payload": {"type": "token_count", "info": {
                    "total_token_usage": {"output_tokens": 3000, "reasoning_output_tokens": 100}}}},
                {"type": "event_msg", "payload": {"type": "task_complete"}},
            ]
            child.write_text("\n".join(json.dumps(event) for event in events))
            self.assertEqual(token_budget.output_usage(child), 3000)
            wrapped = root / "wrapped.jsonl"
            wrapped.write_text(json.dumps({"raw": json.dumps({"type": "turn.completed", "usage": {
                "output_tokens": 4100, "reasoning_output_tokens": 100}})}))
            self.assertEqual(token_budget.output_usage(wrapped), 4100)
            child.write_text("\n".join(json.dumps(event) for event in events[:-1]))
            with self.assertRaisesRegex(ValueError, "unavailable"):
                token_budget.output_usage(child)
