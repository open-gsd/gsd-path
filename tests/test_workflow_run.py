import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests import test_handoffs
from tests.test_pipeline_state import run_git

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/workflow_run.py"


GRANT = '- 2026-09-27 — define — pre-approval: {"kinds": ["intent", "plan"]}\n'
APPROVED = "- 2026-09-27 — define — milestone intent approved\n"


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
                (root / name).write_bytes("Documentation.\n".encode("utf-8"))
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "inspect fixture")
            head = run_git(root, "rev-parse", "HEAD").stdout.strip()
            prepared = json.loads(self.run_cli(root, "prepare-inspect", "--expected-head", head, script=script).stdout)["inspection"]
            assignments = {a["task_name"]: a for a in prepared["assignments"]}
            mapper = assignments["inspect_codebase"]
            mapping = Path(mapper["worktree"]) / mapper["output"]
            mapping.parent.mkdir(parents=True, exist_ok=True)
            mapping.write_bytes("# Codebase\n\n## Map\nPython CLI.\n\n## Findings\nNone: no surprises.\n".encode("utf-8"))
            docs = assignments["inspect_docs"]
            audit = Path(docs["worktree"]) / docs["output"]
            audit.parent.mkdir(parents=True, exist_ok=True)
            audit.write_bytes(f"# Invalid audit\nAudited HEAD: {head}\n".encode("utf-8"))
            args = ("finish-inspect", "--expected-head", head, "--inspection",
                    prepared.get("receipt_file", str(root.parent / "unsupported.json")), "--mapper-reviewed")
            rejected = self.run_cli(root, *args, script=script)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("check_docs_audit.py", rejected.stdout)
            self.assertFalse((root / mapper["output"]).exists())
            self.assertTrue(mapping.is_file())
            valid = (AUDIT.format(verified=1).replace("CONTRIBUTING.md", "AGENTS.md")
                     .replace("Audited HEAD: none", f"Audited HEAD: {head}"))
            audit.write_bytes(valid.replace("Repo root: /repo", f"Repo root: {docs['worktree']}").encode("utf-8"))
            sidecar_root = self.run_cli(root, *args, script=script)
            self.assertNotEqual(sidecar_root.returncode, 0)
            self.assertIn("Repo root does not match", sidecar_root.stderr)
            audit.write_bytes(valid.replace("Repo root: /repo", f"Repo root: {root.resolve()}").encode("utf-8"))
            accepted = self.run_cli(root, *args, script=script)
            self.assertEqual(accepted.returncode, 0, accepted.stderr + accepted.stdout)
            self.assertIn("Python CLI", (root / mapper["output"]).read_text(encoding="utf-8"))
            self.assertIn(f"Repo root: {root.resolve()}\n", (root / docs["output"]).read_text(encoding="utf-8"))
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
            (root / "README.md").write_bytes("Product documentation.\n".encode("utf-8"))
            (root / "AGENTS.md").write_bytes("Project instructions.\n".encode("utf-8"))
            run_git(root, "add", ".")
            run_git(root, "commit", "-m", "inspection fixture")
            head = run_git(root, "rev-parse", "HEAD").stdout.strip()
            result = self.run_cli(root, "prepare-inspect", "--expected-head", head, script=script)
            self.assertEqual(result.returncode, 0, result.stderr)
            inspection = json.loads(result.stdout)["inspection"]
            inventory = Path(inspection["inventory_file"])
            self.assertEqual(inventory.read_text(encoding="utf-8").splitlines(), ["AGENTS.md", "README.md"])
            assignments = inspection["assignments"]
            self.assertEqual({a["task_name"] for a in assignments},
                             {"inspect_codebase", "inspect_docs"})
            self.assertEqual(len({a["worktree"] for a in assignments}), 2)
            (root / "LATER.md").write_bytes("Appeared after freezing.\n".encode("utf-8"))
            for assignment in assignments:
                sidecar = Path(assignment["worktree"])
                self.assertEqual(head, run_git(sidecar, "rev-parse", "HEAD").stdout.strip())
                self.assertFalse((sidecar / "LATER.md").exists())
                brief = Path(assignment["brief_file"]).read_text(encoding="utf-8")
                self.assertIn(str(sidecar), brief)
                self.assertIn(f"Write header Repo root: {root.resolve()}\n", brief)
                self.assertTrue(Path(assignment["role"]).is_file())
                self.assertTrue(Path(assignment["template"]).is_file())
            self.assertNotIn("LATER.md", inventory.read_text(encoding="utf-8"))
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
                    audit.write_bytes("Prior audit and owner rulings.\n".encode("utf-8"))
                result = self.run_cli(root, "prepare-inspect", "--expected-head", head)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("prior inspection" if prior else "active inspect track",
                              json.loads(result.stdout)["reason"])
                self.assertFalse((root.parent / "repo.gsd-path").exists())
                if prior:
                    self.assertEqual(audit.read_text(encoding="utf-8"), "Prior audit and owner rulings.\n")

    def test_ship_preparation_stops_at_unproven_landing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.fixture(root)
            result = self.run_cli(root, "prepare-final", "--expected-head", head)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["steps"][-1]["script"], "build_state.py")
            self.assertFalse((root / ".project/build/verify-ledger.jsonl").exists())

    def test_prepare_final_rerun_flag_reaches_the_verification_step(self):
        from unittest import mock
        from types import SimpleNamespace
        from scripts import workflow_run
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.fixture(root)
            commands = []

            def fake_run(command, **kwargs):
                commands.append(command)
                stdout = '{"pending": []}' if command[2].endswith("discussion_records.py") else "{}"
                return SimpleNamespace(returncode=0, stdout=stdout, stderr="")

            for rerun, expected in ((True, self.assertIn), (False, self.assertNotIn)):
                with self.subTest(rerun=rerun):
                    commands.clear()
                    with mock.patch.object(workflow_run.subprocess, "run", side_effect=fake_run):
                        workflow_run.run_workflow(
                            root, "prepare-final", ".project", head, rerun=rerun
                        )
                    lean = [
                        command for command in commands
                        if command[2].endswith("lean_verification.py")
                    ]
                    self.assertEqual(len(lean), 1)
                    expected("--rerun", lean[0])

    def fixture(self, root):
        run_git(root, "init", "-b", "gsd-path/M001")
        run_git(root, "config", "user.name", "Test")
        run_git(root, "config", "user.email", "test@example.test")
        test_handoffs.HandoffValidationTests().write_plan_handoff(root)
        state = root / ".project/STATE.md"
        state.write_bytes(state.read_text(encoding="utf-8").replace("branch: null", "branch: gsd-path/M001").encode("utf-8"))
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "fixture")
        return run_git(root, "rev-parse", "HEAD").stdout.strip()

    def run_cli(self, root, *args, script=SCRIPT):
        return subprocess.run([sys.executable, "-B", str(script), *args, "--repo", str(root)],
                              capture_output=True, encoding="utf-8", errors="replace")

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
            (root / ".project/plan/PLAN.md").write_bytes("invalid plan".encode("utf-8"))
            before = (root / ".project/STATE.md").read_bytes()
            result = self.run_cli(root, "approve-plan", "--expected-head", head)
            self.assertNotEqual(result.returncode, 0)
            receipt = json.loads(result.stdout)
            self.assertEqual(receipt["status"], "blocked")
            self.assertEqual(receipt["steps"][-1]["script"], "check_handoffs.py")
            self.assertIn(receipt["steps"][-1]["stderr"], result.stderr)
            self.assertEqual(before, (root / ".project/STATE.md").read_bytes())
            self.assertEqual(head, run_git(root, "rev-parse", "HEAD").stdout.strip())

    def quick_fixture(self, root, log=GRANT + APPROVED, lane="quick", questions="- none\n"):
        self.fixture(root)
        intent = root / ".project/intent/INTENT.md"
        intent.write_bytes((f"Lane: {lane}   <!-- quick -->\n" + intent.read_text(encoding="utf-8")
                          + f"\n## Open questions\n\n{questions}").encode("utf-8"))
        state = root / ".project/STATE.md"
        state.write_bytes((state.read_text(encoding="utf-8") + log).encode("utf-8"))
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "quick fixture")
        return run_git(root, "rev-parse", "HEAD").stdout.strip()

    def preauthorize(self, root, kind="plan"):
        result = self.run_cli(root, "preauthorize", "--kind", kind)
        return result.returncode, json.loads(result.stdout)

    def test_preauthorize_records_use_and_the_canonical_approval_consumes_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            head = self.quick_fixture(root)
            code, receipt = self.preauthorize(root)
            self.assertEqual((code, receipt["status"]), (0, "complete"), receipt)
            state = (root / ".project/STATE.md").read_text(encoding="utf-8")
            self.assertTrue(state.endswith("— plan — pre-authorized approval: plan\n"))
            # A failed approval leaves the grant usable: only the approval event consumes it.
            self.assertEqual(self.preauthorize(root)[0], 0)
            approved = self.run_cli(root, "approve-plan", "--expected-head", head)
            self.assertEqual(approved.returncode, 0, approved.stderr)
            code, receipt = self.preauthorize(root)
            self.assertEqual(code, 1)
            self.assertEqual(receipt["next"], "ask the owner at this gate")

    def test_preauthorize_intent_before_milestone_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.quick_fixture(root, log=GRANT)
            state = root / ".project/STATE.md"
            state.write_bytes(state.read_text(encoding="utf-8").replace("milestone: demo", "milestone: null")
                             .replace("phase: plan", "phase: define").encode("utf-8"))
            code, receipt = self.preauthorize(root, "intent")
            self.assertEqual((code, receipt["status"]), (0, "complete"), receipt)
            self.assertTrue(state.read_text(encoding="utf-8").endswith("— define — pre-authorized approval: intent\n"))
            # Intent pre-approval checks only the intent draft, never the plan gate.
            gates = [step["command"][3] for step in receipt["steps"] if step["script"] == "check_handoffs.py"]
            self.assertEqual(gates, ["intent"])

    def test_preauthorize_intent_blocks_an_incomplete_edge_probe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.quick_fixture(root, log=GRANT)
            state = root / ".project/STATE.md"
            state.write_bytes(state.read_text(encoding="utf-8").replace("milestone: demo", "milestone: null")
                             .replace("phase: plan", "phase: define").encode("utf-8"))
            intent = root / ".project/intent/INTENT.md"
            # The edge the probe raised was never ruled on: a placeholder disposition.
            intent.write_bytes((intent.read_text(encoding="utf-8") + "\n## Edge coverage\n\n"
                                "| Edge | Criterion | Category | Disposition | Detail |\n"
                                "|------|-----------|----------|-------------|--------|\n"
                                "| E1 | SC1 | boundary | <disposition> | <ruling> |\n").encode("utf-8"))
            code, receipt = self.preauthorize(root, "intent")
            self.assertEqual(code, 1, receipt)
            self.assertEqual(receipt["next"], "ask the owner at this gate")
            self.assertEqual((receipt["steps"][-1]["script"], receipt["steps"][-1]["exit_code"]),
                             ("check_handoffs.py", 1))
            self.assertIn("E1 disposition", receipt["steps"][-1]["stderr"])
            self.assertFalse(state.read_text(encoding="utf-8").endswith("pre-authorized approval: intent\n"))

    def test_preauthorize_blocks_outside_its_grant(self):
        cases = {
            "no pre-approval grant": dict(log=APPROVED),
            "does not grant plan": dict(log=GRANT.replace('"intent", "plan"', '"intent"') + APPROVED),
            "used or out of scope": dict(log=GRANT + APPROVED + APPROVED),
            "only the quick lane": dict(lane="standard"),
            "open RESEARCH or NEEDS-USER": dict(questions="- [NEEDS-USER] Which port?\n"),
        }
        for reason, fixture in cases.items():
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.quick_fixture(root, **fixture)
                before = (root / ".project/STATE.md").read_bytes()
                code, receipt = self.preauthorize(root)
                self.assertEqual(code, 1)
                self.assertIn(reason, receipt["reason"] + receipt["steps"][-1].get("stderr", ""))
                self.assertEqual(before, (root / ".project/STATE.md").read_bytes())

    def test_preauthorize_enforces_quick_plan_limits_and_scope(self):
        def audit_ruling(root, ruling=""):
            audit = root / ".project/research/DOCS-AUDIT.md"
            audit.parent.mkdir()
            audit.write_bytes(
                ("## Remediation queue\n\n| # | Doc | Claim | Verdict | Class | Action |\n|---|---|---|---|---|---|\n"
                "| 1 | README.md | runs | stale | NEEDS-USER | ask |\n\n## User rulings\n\n"
                "| Queue # | Ruling | User's words | Planned |\n|---|---|---|---|\n" + ruling).encode("utf-8"))

        edits = {
            "finding_skeptics off": lambda root: self.edit(
                root, "plan/PLAN.md", "- review_panel: off", "- review_panel: off\n- finding_skeptics: on"),
            "finding_skeptics": lambda root: self.edit(
                root, "plan/PLAN.md", "## Config", "- finding_skeptics: off\n\n## Config\n\n- finding_skeptics: on"),
            "review_panel off": lambda root: self.edit(
                root, "plan/PLAN.md", "- review_panel: off", "- review_panel: claude,gpt"),
            "quick lane": lambda root: self.edit(
                root, "intent/INTENT.md", "Lane: quick   <!-- quick -->",
                "Lane: standard   <!-- quick -->\nLane: quick"),
            "one wave and at most two tasks": self.third_task,
            "user ruling": lambda root: audit_ruling(root),
            "placeholder user ruling": lambda root: audit_ruling(
                root, '| 1 | fix-doc | "<verbatim>" | no |\n'),
            "build recovery or patch planning": lambda root: (root / ".project/review").mkdir() or (
                root / ".project/review/PATCH-FINDINGS.md").write_text("findings\n", encoding="utf-8"),
        }
        for reason, edit in edits.items():
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                self.quick_fixture(root)
                edit(root)
                before = (root / ".project/STATE.md").read_bytes()
                code, receipt = self.preauthorize(root)
                self.assertEqual(code, 1, receipt)
                self.assertIn("user ruling" if reason == "placeholder user ruling" else reason,
                              receipt["reason"] + receipt["steps"][-1].get("stderr", ""))
                self.assertEqual(before, (root / ".project/STATE.md").read_bytes())

    def edit(self, root, relative, old, new):
        path = root / ".project" / relative
        self.assertIn(old, path.read_text(encoding="utf-8"))
        path.write_bytes(path.read_text(encoding="utf-8").replace(old, new).encode("utf-8"))

    def third_task(self, root):
        handoffs = test_handoffs.HandoffValidationTests()
        handoffs.write_coverage_task(root, "T003", "- SC2", files="src/extra.py")
        self.edit(root, "plan/PLAN.md", "| T002 | Demo task T002 | — | tests/test_app.py |",
                  "| T002 | Demo task T002 | — | tests/test_app.py |\n| T003 | Demo task T003 | — | src/extra.py |")
        self.edit(root, "plan/PLAN.md", "| SC2 | T002 | AC1 |", "| SC2 | T002 | AC1 |\n| SC2 | T003 | AC1 |")
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "third task")

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
            (root / "new.py").write_bytes("print('new')".encode("utf-8"))
            self.assertFalse((sidecar / "new.py").exists())
            self.assertEqual(head, run_git(sidecar, "rev-parse", "HEAD").stdout.strip())
            self.assertTrue(run_git(sidecar, "branch", "--show-current").stdout.strip())

    def test_serial_prepare_returns_a_blocked_receipt_when_the_sidecar_path_is_unavailable(self):
        from unittest import mock
        from scripts import workflow_run
        from tests import test_isolation
        with tempfile.TemporaryDirectory() as tmp:
            root = (Path(tmp) / "repo").resolve()
            root.mkdir()
            head = test_isolation.IsolationTests().init_bound_repo(root)
            with mock.patch.object(workflow_run.isolation.worktree_paths, "worktree_path",
                                   side_effect=OSError("workspace pin is unreadable")):
                result = workflow_run.run_workflow(root, "prepare-task", ".project", head, "T001", 1)
            self.assertEqual((result["status"], result["reason"]), ("blocked", "workspace pin is unreadable"))
            self.assertEqual([step["script"] for step in result["steps"]], ["isolation.py"])

    def test_packaged_runner_uses_its_bundled_dependencies(self):
        for skill in ("gsd-path", "gsd-path-plan", "gsd-path-build"):
            with self.subTest(skill=skill), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                head = self.fixture(root)
                script = SCRIPT.parent.parent / "skills" / skill / "scripts/workflow_run.py"
                result = self.run_cli(root, "approve-plan", "--expected-head", head, script=script)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["steps"][-1]["result"]["status"], "approved")
