import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("release_receipt", ROOT / "release_receipt.py")
release_receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_receipt)


class ClaudeChildReceiptTests(unittest.TestCase):
    def collect(self, events, landed_tool_use_id=None):
        with tempfile.TemporaryDirectory(dir=ROOT) as temporary:
            stream = Path(temporary) / "quick/run-001/events.jsonl"
            stream.parent.mkdir(parents=True)
            stream.write_text("".join(json.dumps({"raw": json.dumps(event)}) + "\n" for event in events))
            if landed_tool_use_id is None:
                return release_receipt.claude_child(temporary, "build_T001")
            return release_receipt.claude_child(temporary, "build_T001", landed_tool_use_id)

    def use(self, identifier, background=False):
        return {"type": "assistant", "message": {"content": [{
            "type": "tool_use", "name": "Agent", "id": identifier,
            "input": {"description": "build_T001", "prompt": "task prompt", "run_in_background": background},
        }]}}

    def result(self, identifier, content="done", error=False):
        return {"type": "user", "message": {"content": [{
            "type": "tool_result", "tool_use_id": identifier, "content": content, "is_error": error,
        }]}}

    def notification(self, identifier, status="completed"):
        return {"type": "system", "subtype": "task_notification", "tool_use_id": identifier,
                "task_id": "task-" + identifier, "status": status, "summary": "Verified task"}

    def test_background_requires_bound_completed_notification(self):
        for background, content in ((True, "launched"), (False, "Async agent launched successfully.")):
            for extra in ([], [self.notification("other")], [self.notification("a", "failed")],
                          [{"type": "system", "subtype": "task_updated", "tool_use_id": "a",
                            "patch": {"status": "completed"}}]):
                with self.subTest(background=background, extra=extra):
                    with self.assertRaisesRegex(SystemExit, "no completed Agent"):
                        self.collect([self.use("a", background), self.result("a", content)] + extra)

    def test_background_records_completion_and_launch(self):
        started = {"type": "system", "subtype": "task_started", "tool_use_id": "a",
                   "task_id": "task-a", "prompt": "task prompt"}
        receipt = self.collect([self.use("a", True), started, self.result("a", "Async agent launched"),
                                self.notification("a")])
        self.assertEqual("task-a", receipt["task_id"])
        self.assertEqual("a", receipt["task_started"]["tool_use_id"])
        self.assertNotIn("prompt", receipt["task_started"])
        self.assertEqual("Verified task", receipt["task_notification"]["summary"])
        self.assertEqual("completed", receipt["task_notification"]["status"])
        self.assertEqual("Async agent launched", receipt["tool_result"]["content"])
        self.assertNotIn("prompt", receipt["tool_use"]["input"])
        self.assertEqual(hashlib.sha256(b"task prompt").hexdigest(), receipt["tool_use"]["prompt_sha256"])

    def test_incomplete_retry_cannot_replace_completed_attempt(self):
        receipt = self.collect([self.use("a"), self.result("a"), self.use("b")])
        self.assertEqual("a", receipt["tool_use"]["id"])
        self.assertEqual("a", receipt["tool_result"]["tool_use_id"])

    def test_foreground_errors_do_not_complete(self):
        with self.assertRaisesRegex(SystemExit, "no completed Agent"):
            self.collect([self.use("a"), self.result("a", error=True)])

    def test_selects_last_completion_or_proven_landing(self):
        events = [self.use("a"), self.use("b"), self.result("b"), self.result("a")]
        self.assertEqual("a", self.collect(events)["tool_use"]["id"])
        self.assertEqual("b", self.collect(events, "b")["tool_use"]["id"])
        with self.assertRaisesRegex(SystemExit, "has no completion evidence"):
            self.collect(events, "missing")


class ManifestBindingTests(unittest.TestCase):
    def test_manifest_binds_completed_child_and_final_review(self):
        from contextlib import redirect_stdout
        from io import StringIO
        from types import SimpleNamespace
        from unittest.mock import patch

        for host in ("codex", "claude"):
            for agent, source in (("build_t001", None), ("build_T001", None),
                                  ("build_T001", ".project/review/wave-1.cycle6.md")):
                with self.subTest(host=host, agent=agent, source=source), tempfile.TemporaryDirectory(dir=ROOT) as tmp:
                    root = Path(tmp)
                    repo = root / "quick/fixture"
                    archive = ".project/archive/001-test"
                    archived = repo / archive
                    (archived / "tasks").mkdir(parents=True)
                    (archived / "tasks/T001.md").write_text(f"id: T001\nagent: {agent}\nbase: base\n")
                    (repo / ".project/STATE.md").write_text(f"archive: {archive}\nbranch: gsd-path/M001\n")
                    (archived / "build").mkdir()
                    (archived / "build/verify-ledger.jsonl").write_text("")
                    (archived / "review").mkdir()
                    wave = "wave-1.cycle6.md" if source else "wave-1.cycle1.md"
                    (archived / "review" / wave).write_text("Wave verdict: pass\n")
                    (archived / "review/FINAL.md").write_text(f"Source review: {source}\n" if source else "Overall verdict: pass\n")
                    native = root / "native.json"
                    native.write_text('{"native_guard": "pass"}')
                    if host == "codex":
                        transcript = root / "session.jsonl"
                        payloads = [
                            {"type": "function_call", "name": "spawn_agent", "call_id": "a", "arguments": '{"task_name":"build_T001"}'},
                            {"type": "function_call_output", "call_id": "a", "output": "spawned"},
                            {"type": "function_call_output", "call_id": "b", "output": json.dumps({"agents": [{"agent_name": "/root/build_T001", "agent_status": "completed"}]})},
                        ]
                        transcript.write_text("".join(json.dumps({"payload": p}) + "\n" for p in payloads))
                    else:
                        stream = root / "quick/run-001/events.jsonl"
                        stream.parent.mkdir()
                        helper = ClaudeChildReceiptTests()
                        stream.write_text("".join(json.dumps({"raw": json.dumps(e)}) + "\n" for e in (helper.use("a"), helper.result("a"))))
                        transcript = None
                    args = SimpleNamespace(repo=str(ROOT), fixture=str(repo), transcript=str(transcript) if transcript else None,
                                           committed_archive_repo=None, committed_archive=None, native_guard_evidence=str(native),
                                           run_id="test", host_version="test", candidate="candidate", package_version="1.0.0", task_branch="task")
                    with patch.multiple(release_receipt, HOST=host, GUARD_TIER="git-only", CHILD_API="test"), \
                         patch.object(release_receipt, "git_hook_check", return_value={"git_hooks": "pass"}), \
                         patch.object(release_receipt, "git", side_effect=lambda repo, *args: "landing" if args[0] == "log" else "remote refs/heads/main"), \
                         redirect_stdout(StringIO()):
                        if agent == "build_t001":
                            with self.assertRaisesRegex(SystemExit, "no completed child"):
                                release_receipt.phase_manifest(args)
                            self.assertFalse((archived / "trust-run-manifest.json").exists())
                        else:
                            self.assertEqual(0, release_receipt.phase_manifest(args))
                            manifest = json.loads((archived / "trust-run-manifest.json").read_text())
                            self.assertEqual(f"{archive}/review/{wave}", manifest["artifacts"]["wave_review"])
                            self.assertEqual(agent, manifest["child_id"])

    def test_remote_default_never_uses_stale_tracking_ref(self):
        from types import SimpleNamespace
        from unittest.mock import patch

        def command(args, **kwargs):
            output = remote if args[1] == "ls-remote" else "stale\n"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")

        with patch.object(release_receipt.subprocess, "run", side_effect=command):
            remote = "fresh\trefs/heads/main\n"
            self.assertEqual("fresh", release_receipt.remote_default_commit(ROOT))
            remote = ""
            with self.assertRaisesRegex(SystemExit, "refs/heads/main"):
                release_receipt.remote_default_commit(ROOT)
