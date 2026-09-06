import hashlib
import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RECEIPT = ROOT / "docs/trust-validation/evidence/releases/1.0.0/codex/release_receipt.py"
spec = importlib.util.spec_from_file_location("release_receipt", RECEIPT)
release_receipt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release_receipt)


class ReleaseReceiptHookTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.reference = self.root / "reference"
        self.reference.mkdir()
        self.archive = ".project/archive/001-test"
        self.guard = ".gsd-path/git_guard.py"
        self.hook = ".git/hooks/pre-commit"
        git = release_receipt.git
        git(self.reference, "init", "-q", "-b", "main")
        git(self.reference, "config", "user.name", "Receipt Test")
        git(self.reference, "config", "user.email", "receipt@example.invalid")
        git(self.reference, "config", "commit.gpgsign", "false")
        archive = self.reference / self.archive
        archive.mkdir(parents=True)
        (archive / "record.txt").write_text("archived\n")
        guard = self.reference / self.guard
        guard.parent.mkdir()
        guard.write_text(
            "import subprocess, sys\n"
            "changed = subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True)\n"
            "if any(p.startswith('.project/archive/') for p in changed.splitlines()):\n"
            "    sys.stderr.write('archive is read-only\\n')\n"
            "    sys.exit(1)\n"
        )
        git(self.reference, "add", ".")
        git(self.reference, "commit", "-qm", "fixture")
        hook = self.reference / self.hook
        hook.write_text("#!/bin/sh\nexec python3 .gsd-path/git_guard.py\n")
        hook.chmod(0o755)
        self.fixture = self.root / "fixture"
        for relative in (self.guard, self.hook):
            target = self.fixture / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.reference / relative, target)

    def check_hooks(self, fixture, reference=None):
        result = release_receipt.git_hook_check(fixture, self.archive, reference)
        self.assertTrue(result["steps"][0]["blocked"])
        self.assertEqual(0, result["steps"][1]["exit_code"])
        for key, relative in (("guard_sha256", self.guard), ("pre_commit_hook_sha256", self.hook)):
            self.assertEqual({
                "fixture": hashlib.sha256((fixture / relative).read_bytes()).hexdigest(),
                "checked_repository": hashlib.sha256(((reference or fixture) / relative).read_bytes()).hexdigest(),
            }, result[key])
        return result

    def test_matching_reference_passes(self):
        result = self.check_hooks(self.fixture, self.reference)
        self.assertEqual("pass", result["git_hooks"])
        self.assertEqual([], result["hash_mismatches"])
        self.assertEqual({"pre-commit": True}, result["fixture_hook_executable"])

    def test_same_repository_passes(self):
        result = self.check_hooks(self.reference)
        self.assertEqual("pass", result["git_hooks"])

    def test_nonexecutable_fixture_pre_commit_fails(self):
        (self.fixture / self.hook).chmod(0o644)
        result = self.check_hooks(self.fixture, self.reference)
        self.assertEqual("fail", result["git_hooks"])
        self.assertEqual([], result["hash_mismatches"])
        self.assertEqual({"pre-commit": False}, result["fixture_hook_executable"])

    def test_optional_fixture_commit_msg_requires_executability(self):
        hook = self.fixture / ".git/hooks/commit-msg"
        hook.write_text("#!/bin/sh\nexit 0\n")
        for mode, executable, verdict in ((0o644, False, "fail"), (0o755, True, "pass")):
            with self.subTest(mode=mode):
                hook.chmod(mode)
                result = self.check_hooks(self.fixture, self.reference)
                self.assertEqual(verdict, result["git_hooks"])
                self.assertEqual({"pre-commit": True, "commit-msg": executable},
                                 result["fixture_hook_executable"])

    def test_nonexecutable_reference_pre_commit_stays_inert(self):
        (self.reference / self.hook).chmod(0o644)
        result = release_receipt.git_hook_check(self.fixture, self.archive, self.reference)
        self.assertEqual("fail", result["git_hooks"])
        self.assertFalse(result["steps"][0]["blocked"])
        self.assertEqual(0, result["steps"][0]["exit_code"])
        self.assertEqual(0, result["steps"][1]["exit_code"])

    def test_nonexecutable_commit_msg_stays_inert(self):
        hook = self.reference / ".git/hooks/commit-msg"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o644)
        result = self.check_hooks(self.reference)
        self.assertEqual("fail", result["git_hooks"])
        self.assertEqual({"pre-commit": True, "commit-msg": False},
                         result["fixture_hook_executable"])

    def test_mismatched_files_fail(self):
        replacements = {self.guard: "raise SystemExit(0)\n", self.hook: "#!/bin/sh\nexit 0\n"}
        cases = [([self.hook], ["pre_commit_hook_sha256"]),
                 ([self.guard], ["guard_sha256"]),
                 ([self.guard, self.hook], ["guard_sha256", "pre_commit_hook_sha256"])]
        for changed, mismatches in cases:
            with self.subTest(changed=changed):
                for relative, replacement in replacements.items():
                    original = (self.reference / relative).read_text()
                    (self.fixture / relative).write_text(replacement if relative in changed else original)
                result = self.check_hooks(self.fixture, self.reference)
                self.assertEqual("fail", result["git_hooks"])
                self.assertEqual(mismatches, result["hash_mismatches"])


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
