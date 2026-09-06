import tempfile
import json
import shlex
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from scripts import check_handoffs, lean_verification, isolation
from tests import test_handoffs
from tests.test_handoffs import git, git_output


class LeanVerificationTests(unittest.TestCase):
    def test_package_behavior_is_stable_with_cli_helpers_on_sys_path(self):
        root = Path(__file__).resolve().parents[1]
        program = """import sys, unittest
sys.path.insert(0, 'scripts')
suite = unittest.defaultTestLoader.loadTestsFromNames([
    'tests.test_lean_verification.LeanVerificationTests.test_uncommitted_contract_is_not_verified_at_committed_head',
    'tests.test_lean_verification.LeanVerificationTests.test_interrupted_collection_reuses_failed_execution_and_retires_sidecar',
])
raise SystemExit(not unittest.TextTestRunner().run(suite).wasSuccessful())
"""
        result = subprocess.run([sys.executable, '-B', '-c', program], cwd=root,
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_ship_bundle_returns_final_gate_without_review_dispatch(self):
        script = Path(__file__).resolve().parents[1] / "skills/gsd-path-ship/scripts/lean_verification.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, _ = self.fixture(root)
            command = [sys.executable, "-B", str(script), "--repo", str(root), "--expected-head", head]
            for reused in (False, True):
                result = subprocess.run(command, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                receipt = json.loads(result.stdout)
                self.assertIn("Ran 1 test", receipt["verification"]["execution"]["stderr"])
                self.assertEqual(receipt["next"], "final-gate", receipt)
                self.assertEqual(receipt["verification"]["reused"], reused)
                self.assertTrue(receipt["final"]["reused"])
            self.assertEqual(check_handoffs.validate_final(root)["verdict"], "pass")

    def test_cleanup_refuses_primary_and_changed_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, _ = self.fixture(root)
            (root / "precious.txt").write_text("keep")
            with self.assertRaises(isolation.IsolationError):
                isolation.clean_verify(root, root, head, "gsd-path/verify/example")
            self.assertEqual((root / "precious.txt").read_text(), "keep")
            (root / "precious.txt").unlink()
            sidecar = isolation.isolate_verify(root, head, "changed")
            worktree = Path(sidecar["worktree"])
            git(worktree, "commit", "--allow-empty", "-qm", "unexpected commit")
            (worktree / "precious.txt").write_text("keep")
            with self.assertRaisesRegex(isolation.IsolationError, "HEAD changed"):
                isolation.clean_verify(root, worktree, head, sidecar["branch"])
            self.assertEqual((worktree / "precious.txt").read_text(), "keep")

    def test_uncommitted_contract_is_not_verified_at_committed_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, _ = self.fixture(root)
            plan = root / ".project/plan/PLAN.md"
            plan.write_text(plan.read_text().replace("python3 -m unittest discover", "false"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "uncommitted"):
                lean_verification.verify_project(root, head)
            self.assertFalse((root / ".project/build/verify-ledger.jsonl").exists())

    def test_interrupted_collection_reuses_failed_execution_and_retires_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            plan = root / ".project/plan/PLAN.md"
            plan.write_text(plan.read_text().replace("python3 -m unittest discover", "echo broken >&2; exit 7"))
            git(root, "add", ".")
            git(root, "commit", "-qm", "failing verify")
            head = git_output(root, "rev-parse", "HEAD")
            with patch.object(isolation, "clean_verify", side_effect=OSError("interrupted")):
                with self.assertRaisesRegex(OSError, "interrupted"):
                    lean_verification.verify_project(root, head)
            self.assertEqual(git_output(root, "worktree", "list", "--porcelain").count("worktree "), 2)
            ledger = root / ".project/build/verify-ledger.jsonl"
            before = ledger.read_bytes()
            result = lean_verification.verify_project(root, head)
            self.assertFalse(result["passed"])
            self.assertTrue(result["reused"])
            self.assertEqual(result["execution"]["stderr"], "broken\n")
            self.assertEqual(ledger.read_bytes(), before)
            self.assertEqual(git_output(root, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_prepared_collection_recovers_before_retirement(self):
        for stage in ("prepared", "collected"):
            with self.subTest(stage=stage):
                with tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    head, _ = self.fixture(root)
                    write = isolation._write_collect_journal
                    def interrupt(path, payload):
                        write(path, payload)
                        if payload["stage"] == stage:
                            raise OSError("interrupted after prepare")
                    with patch.object(isolation, "_write_collect_journal", side_effect=interrupt):
                        with self.assertRaisesRegex(OSError, "interrupted after prepare"):
                            lean_verification.verify_project(root, head)
                    self.assertEqual(len(isolation.collect_artifact_recoveries(root)), 1)
                    ledger = root / ".project/build/verify-ledger.jsonl"
                    before = ledger.read_bytes()
                    run = subprocess.run
                    def no_replay(command, *args, **kwargs):
                        if command[:2] == ["bash", "-c"]:
                            self.fail("project command replayed")
                        return run(command, *args, **kwargs)
                    with patch.object(subprocess, "run", side_effect=no_replay):
                        result = lean_verification.verify_project(root, head)
                    self.assertTrue(result["reused"])
                    self.assertEqual(isolation.collect_artifact_recoveries(root), [])
                    self.assertEqual(ledger.read_bytes(), before)
                    self.assertFalse(Path(result["execution"]["worktree"]).exists())

    def test_project_verification_executes_once_and_rebuilds_evidence_from_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            self.fixture(root)
            counter = Path(tmp) / "executions.txt"
            program = root / "verify.py"
            program.write_text(
                "from pathlib import Path\n"
                f"with Path({str(counter)!r}).open('a') as f: f.write('run\\n')\n"
                "Path('hello.py').write_text('generated change')\n"
                "Path('generated.txt').write_text('output')\n"
                "print('verified in ' + str(Path.cwd()))\n"
            )
            plan = root / ".project/plan/PLAN.md"
            command = f"{shlex.quote(sys.executable)} -B verify.py"
            plan.write_text(plan.read_text().replace("python3 -m unittest discover", command))
            git(root, "add", ".")
            git(root, "commit", "-qm", "verification command")
            head = git_output(root, "rev-parse", "HEAD")
            result = lean_verification.verify_project(root, head)
            self.assertTrue(result["passed"])
            self.assertFalse(result["reused"])
            self.assertEqual(counter.read_text(), "run\n")
            gap = root / ".project/review/final-gap-1.md"
            self.assertIn(".project/build/verify-ledger.jsonl", gap.read_text())
            self.assertNotIn("verified in", gap.read_text())
            self.assertEqual((root / "hello.py").read_text(), "print('hello')\n")
            self.assertFalse((root / "generated.txt").exists())
            self.assertEqual(git_output(root, "worktree", "list", "--porcelain").count("worktree "), 1)
            ledger = root / ".project/build/verify-ledger.jsonl"
            before = ledger.read_bytes()
            gap.unlink()
            result = lean_verification.verify_project(root, head)
            self.assertTrue(result["reused"])
            self.assertTrue(result["passed"])
            self.assertIn(".project/build/verify-ledger.jsonl", gap.read_text())
            self.assertEqual(counter.read_text(), "run\n")
            self.assertEqual(ledger.read_bytes(), before)
            self.assertEqual(json.loads(before)["execution"]["exit_code"], 0)
            self.assertIn("verified in", json.loads(before)["execution"]["stdout"])

    def fixture(self, root, surface=False, lane_line="Lane: quick"):
        helper = test_handoffs.HandoffValidationTests()
        helper.write_plan_handoff(root)
        if surface:
            helper.write_intent_criteria(root, surfaces="CLI")
            helper.write_plan_coverage(root, surface_contract="""## Surface contract

### CLI — T001
Criteria: SC1
Entry: python3 hello.py
States: prints hello
Walkthrough:
1. Run python3 hello.py and observe hello.
""")
        intent = root / ".project/intent/INTENT.md"
        intent.write_text(intent.read_text().replace("# Intent — demo", f"# Intent — demo\n\n{lane_line}"))
        (root / "hello.py").write_text("print('hello')\n")
        (root / "test_hello.py").write_text(
            "import subprocess\n"
            "import sys\n"
            "import unittest\n\n"
            "class HelloTests(unittest.TestCase):\n"
            "    def test_output(self):\n"
            "        output = subprocess.check_output([sys.executable, 'hello.py'], text=True)\n"
            "        self.assertEqual(output, 'hello\\n')\n"
        )
        git(root, "init", "-q", "-b", "gsd-path/M001")
        git(root, "config", "user.email", "test@example.test")
        git(root, "config", "user.name", "Test")
        git(root, "add", ".")
        git(root, "commit", "-qm", "reviewed product and contracts")
        reviewed = git_output(root, "rev-parse", "HEAD")
        relative = helper.write_wave_review(root)
        wave = root / relative
        text = wave.read_text().replace("Wave verdict: pass", f"Reviewed HEAD: {reviewed}\nReview scope: final\nWave verdict: pass")
        if surface:
            text = text.replace("- ✅ hello.py output", """- ✅ hello.py output
- **Surface**: CLI
- **Check**: `python3 hello.py`
- **Observed**: hello followed by newline""")
        wave.write_text(text)
        git(root, "add", ".project")
        git(root, "commit", "-qm", "record full wave review")
        helper.write_state(root, "ship", "active")
        git(root, "add", ".project/STATE.md")
        git(root, "commit", "-qm", "build complete")
        helper.write_final_review(root)
        (root / ".project/review/FINAL.md").unlink()
        return git_output(root, "rev-parse", "HEAD"), wave

    def test_template_style_lane_comment_still_reuses_the_wave(self):
        # The bundled intent template writes `Lane: quick   <!-- ... -->`; the trailing
        # comment must not turn a quick lane into a refused reuse (seen live 2026-09-06).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, _ = self.fixture(root, lane_line="Lane: quick   <!-- one deliverable-sized task in one wave -->")
            result = lean_verification.reuse_final(root, head)
            self.assertTrue(result["reused"], result)
            self.assertEqual(check_handoffs.validate_final(root)["verdict"], "pass")

    def test_complete_full_wave_becomes_final_without_a_second_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, wave = self.fixture(root)
            before = wave.read_bytes()
            result = lean_verification.reuse_final(root, head)
            self.assertTrue(result["reused"], result)
            self.assertEqual(check_handoffs.validate_final(root)["verdict"], "pass")
            self.assertEqual(before, wave.read_bytes())
            self.assertEqual(lean_verification.reuse_final(root, head), result)

    def test_walked_surface_is_reused_with_observed_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head, _ = self.fixture(root, surface=True)
            result = lean_verification.reuse_final(root, head)
            self.assertTrue(result["reused"], result)
            final = root / ".project/review/FINAL.md"
            self.assertIn("hello followed by newline", final.read_text())
            self.assertEqual(check_handoffs.validate_final(root)["verdict"], "pass")

    def test_changed_product_or_contract_requires_fresh_review(self):
        for name in ("hello.py", ".project/intent/INTENT.md", ".project/plan/PLAN.md",
                     ".project/tasks/T001-demo.md"):
            with self.subTest(path=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                _, _wave = self.fixture(root)
                path = root / name
                path.write_text(path.read_text() + "\nchanged\n")
                git(root, "add", name)
                git(root, "commit", "-qm", "change review input")
                test_handoffs.HandoffValidationTests().write_final_review(root)
                (root / ".project/review/FINAL.md").unlink()
                result = lean_verification.reuse_final(root, git_output(root, "rev-parse", "HEAD"))
                self.assertFalse(result["reused"], result)
                self.assertIn("product or approved contracts changed", result["reason"])
                self.assertFalse((root / ".project/review/FINAL.md").exists())

    def test_missing_walkthrough_or_final_scope_requires_fresh_review(self):
        for removed in ("Review scope: final\n", "- **Observed**: hello followed by newline\n"):
            with self.subTest(removed=removed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                head, wave = self.fixture(root, surface=True)
                wave.write_text(wave.read_text().replace(removed, ""))
                git(root, "add", str(wave.relative_to(root)))
                git(root, "commit", "-qm", "record incomplete review")
                head = git_output(root, "rev-parse", "HEAD")
                test_handoffs.HandoffValidationTests().write_final_review(root)
                (root / ".project/review/FINAL.md").unlink()
                self.assertFalse(lean_verification.reuse_final(root, head)["reused"])
                self.assertFalse((root / ".project/review/FINAL.md").exists())
