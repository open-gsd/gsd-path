import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_handoffs
from tests.test_pipeline_state import run_git

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/workflow_run.py"


class WorkflowRunTests(unittest.TestCase):
    def fixture(self, root):
        run_git(root, "init", "-b", "gsd-path/M001")
        run_git(root, "config", "user.name", "Test")
        run_git(root, "config", "user.email", "test@example.test")
        test_handoffs.HandoffValidationTests().write_plan_handoff(root)
        state = root / ".project/STATE.md"
        state.write_text(state.read_text().replace("branch: null", "branch: gsd-path/M001"))
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "fixture")
        return run_git(root, "rev-parse", "HEAD").stdout.strip()

    def run_cli(self, root, *args, script=SCRIPT):
        return subprocess.run([sys.executable, "-B", str(script), *args, "--repo", str(root)],
                              capture_output=True, text=True)

    def test_plan_gate_and_approval_use_canonical_helpers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.fixture(root)
            result = self.run_cli(root, "approve-plan", "--expected-head", head)
            self.assertEqual(result.returncode, 0, result.stderr)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["steps"][-1]["result"]["status"], "approved")
            self.assertNotEqual(head, run_git(root, "rev-parse", "HEAD").stdout.strip())
            self.assertFalse((root / "src").exists())

    def test_failed_gate_stops_before_approval_and_preserves_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.fixture(root)
            (root / ".project/plan/PLAN.md").write_text("invalid plan")
            before = (root / ".project/STATE.md").read_bytes()
            result = self.run_cli(root, "approve-plan", "--expected-head", head)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "blocked")
            self.assertEqual(receipt["steps"][-1]["script"], "check_handoffs.py")
            self.assertIn(receipt["steps"][-1]["stderr"], result.stderr)
            self.assertEqual(before, (root / ".project/STATE.md").read_bytes())
            self.assertEqual(head, run_git(root, "rev-parse", "HEAD").stdout.strip())

    def test_serial_prepare_creates_verification_before_product_changes(self):
        from tests import test_isolation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            head = test_isolation.IsolationTests().init_bound_repo(root)
            result = self.run_cli(root, "prepare-task", "--expected-head", head,
                                  "--task-id", "T001", "--round-size", "1")
            self.assertEqual(result.returncode, 0, result.stderr)
            steps = json.loads(result.stdout)["steps"]
            task, verification = [step["result"] for step in steps]
            self.assertEqual(Path(task["worktree"]), root.resolve())
            sidecar = Path(verification["worktree"])
            self.assertNotEqual(sidecar, root.resolve())
            (root / "new.py").write_text("print('new')")
            self.assertFalse((sidecar / "new.py").exists())
            self.assertEqual(head, run_git(sidecar, "rev-parse", "HEAD").stdout.strip())
            self.assertTrue(run_git(sidecar, "branch", "--show-current").stdout.strip())

    def test_packaged_runner_uses_its_bundled_dependencies(self):
        for skill in ("gsd-path", "gsd-path-plan", "gsd-path-build"):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                head = self.fixture(root)
                script = SCRIPT.parent.parent / "skills" / skill / "scripts/workflow_run.py"
                result = self.run_cli(root, "approve-plan", "--expected-head", head, script=script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["steps"][-1]["result"]["status"], "approved")
