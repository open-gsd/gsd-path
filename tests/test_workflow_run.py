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
    def test_inspection_finish_gates_before_collection_and_uses_canonical_transition(self, script=SCRIPT):
        from tests.test_check_docs_audit import AUDIT
        from tests import test_isolation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            test_isolation.IsolationTests().init_bound_repo(root)
            test_handoffs.HandoffValidationTests().write_state(root, "inspect", "active")
            for name in ("AGENTS.md", "README.md"):
                (root / name).write_text("Documentation.\n")
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "inspect fixture")
            head = run_git(root, "rev-parse", "HEAD").stdout.strip()
            prepared = json.loads(self.run_cli(root, "prepare-inspect", "--expected-head", head, script=script).stdout)["inspection"]
            assignments = {a["task_name"]: a for a in prepared["assignments"]}
            mapper = assignments["inspect_codebase"]
            mapping = Path(mapper["worktree"]) / mapper["output"]
            mapping.parent.mkdir(parents=True, exist_ok=True)
            mapping.write_text("# Codebase\n\n## Map\nPython CLI.\n\n## Findings\nNone: no surprises.\n")
            docs = assignments["inspect_docs"]
            audit = Path(docs["worktree"]) / docs["output"]
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_text(f"# Invalid audit\nAudited HEAD: {head}\n")
            args = ("finish-inspect", "--expected-head", head, "--inspection",
                    prepared.get("receipt_file", str(root.parent / "unsupported.json")), "--mapper-reviewed")
            rejected = self.run_cli(root, *args, script=script)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("check_docs_audit.py", rejected.stdout)
            self.assertFalse((root / mapper["output"]).exists())
            self.assertTrue(mapping.is_file())
            audit.write_text(AUDIT.format(verified=1).replace("CONTRIBUTING.md", "AGENTS.md")
                             .replace("Repo root: /repo", f"Repo root: {docs['worktree']}")
                             .replace("Audited HEAD: none", f"Audited HEAD: {head}"))
            accepted = self.run_cli(root, *args, script=script)
            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            self.assertIn("Python CLI", (root / mapper["output"]).read_text())
            self.assertTrue((root / docs["output"]).is_file())
            self.assertFalse(Path(mapper["worktree"]).exists())
            self.assertFalse(Path(docs["worktree"]).exists())
            state = json.loads(self.run_cli(root, "route").stdout)["steps"][0]["result"]["state"]
            self.assertEqual((state["phase"], state["status"]), ("inspect", "done"))
            self.assertEqual(head, run_git(root, "rev-parse", "HEAD").stdout.strip())

    def test_packaged_inspection_completion(self):
        self.test_inspection_finish_gates_before_collection_and_uses_canonical_transition(
            script=SCRIPT.parent.parent / "skills/gsd-path-inspect/scripts/workflow_run.py")

    def test_initial_inspection_freezes_inputs_and_isolates_both_assignments(self, script=SCRIPT):
        from tests import test_isolation
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            test_isolation.IsolationTests().init_bound_repo(root)
            test_handoffs.HandoffValidationTests().write_state(root, "inspect", "active")
            (root / "README.md").write_text("Product documentation.\n")
            (root / "AGENTS.md").write_text("Project instructions.\n")
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "inspection fixture")
            head = run_git(root, "rev-parse", "HEAD").stdout.strip()
            result = self.run_cli(root, "prepare-inspect", "--expected-head", head, script=script)
            self.assertEqual(result.returncode, 0, result.stderr)
            inspection = json.loads(result.stdout)["inspection"]
            inventory = Path(inspection["inventory_file"])
            self.assertEqual(inventory.read_text().splitlines(), ["AGENTS.md", "README.md"])
            assignments = inspection["assignments"]
            self.assertEqual({a["task_name"] for a in assignments},
                             {"inspect_codebase", "inspect_docs"})
            self.assertEqual(len({a["worktree"] for a in assignments}), 2)
            (root / "LATER.md").write_text("Appeared after freezing.\n")
            for assignment in assignments:
                sidecar = Path(assignment["worktree"])
                self.assertEqual(head, run_git(sidecar, "rev-parse", "HEAD").stdout.strip())
                self.assertFalse((sidecar / "LATER.md").exists())
                brief = Path(assignment["brief_file"]).read_text()
                self.assertIn(str(sidecar), brief)
                self.assertTrue(Path(assignment["role"]).is_file())
                self.assertTrue(Path(assignment["template"]).is_file())
            self.assertNotIn("LATER.md", inventory.read_text())
            self.assertFalse((root / ".project/research").exists())

    def test_packaged_inspection_runs_outside_the_source_checkout(self):
        self.test_initial_inspection_freezes_inputs_and_isolates_both_assignments(
            script=SCRIPT.parent.parent / "skills/gsd-path-inspect/scripts/workflow_run.py")

    def test_initial_inspection_cannot_replace_prior_evidence_or_enter_later_phases(self):
        for prior in (False, True):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp) / "repo"
                root.mkdir()
                head = self.fixture(root)
                if prior:
                    test_handoffs.HandoffValidationTests().write_state(root, "inspect", "active")
                    audit = root / ".project/research/DOCS-AUDIT.md"
                    audit.parent.mkdir(parents=True, exist_ok=True)
                    audit.write_text("Prior audit and owner rulings.\n")
                result = self.run_cli(root, "prepare-inspect", "--expected-head", head)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("prior inspection" if prior else "active inspect track",
                              json.loads(result.stdout)["reason"])
                self.assertFalse((root.parent / "repo.gsd-path").exists())
                if prior:
                    self.assertEqual(audit.read_text(), "Prior audit and owner rulings.\n")

    def test_ship_preparation_stops_at_unproven_landing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.fixture(root)
            result = self.run_cli(root, "prepare-final", "--expected-head", head)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["steps"][-1]["script"], "build_state.py")
            self.assertFalse((root / ".project/build/verify-ledger.jsonl").exists())

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
