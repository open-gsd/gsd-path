"""Behavioral proof for returning a blocked build to its contract owner."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_pipeline_state import state_text
from tests.test_task_briefs import PLAN_WAVE, TASK_TEMPLATE, git


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "pipeline_state.py"


class BuildReentryTests(unittest.TestCase):
    def test_router_bundle_complete_recovery(self):
        bundled = SCRIPT.parent.parent / "skills/gsd-path/scripts/pipeline_state.py"
        with mock.patch(__name__ + ".SCRIPT", bundled):
            self.test_plan_repair_reapproves_and_returns_to_build()

    def exercise_project_runtime(self, names):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            for name in names:
                shutil.copyfile(SCRIPT.parent / name, runtime / name)
            with mock.patch(__name__ + ".SCRIPT", runtime / "pipeline_state.py"):
                self.test_plan_repair_reapproves_and_returns_to_build()

    def test_python_project_runtime_complete_recovery(self):
        from scripts import install
        self.exercise_project_runtime(install.PROJECT_RUNTIME_SCRIPTS)

    def test_node_project_runtime_complete_recovery(self):
        result = subprocess.run([
            "node", "--input-type=module", "-e",
            "const m = await import(process.argv[1]); console.log(JSON.stringify(m.PROJECT_RUNTIME_SCRIPTS));",
            (SCRIPT.parent / "install.mjs").as_uri(),
        ], capture_output=True, text=True, check=True)
        self.exercise_project_runtime(json.loads(result.stdout))

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        git(self.repo, "init", "-b", "gsd-path/M001")
        git(self.repo, "config", "user.email", "test@example.test")
        git(self.repo, "config", "user.name", "Test")
        self.project = self.repo / ".project"
        for directory in ("plan", "tasks", "intent", "review"):
            (self.project / directory).mkdir(parents=True)
        (self.project / "STATE.md").write_text(state_text(
            phase="build", status="blocked", milestone="demo", branch="gsd-path/M001",
        ))
        (self.project / "intent/INTENT.md").write_text(
            "# Intent\n\nLane: quick\n\n## Success criteria\n\n- SC1: The demo behavior holds.\n"
        )
        (self.project / "plan/PLAN.md").write_text(PLAN_WAVE.format(title="demo"))
        self.task = self.project / "tasks/T001-demo.md"
        self.task.write_text(TASK_TEMPLATE.format(
            task_id="T001", files_block="  - app.py", context="Repair the demo.",
            approach="Keep the public interface.", contract="- None", verify="python3 app.py",
        ))
        (self.repo / "app.py").write_text("print('demo')\n")
        (self.project / "review/PLAN-PANEL.md").write_text("Old plan approval evidence\n")
        self.base = self.commit()

    def commit(self):
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-m", "build: checkpoint blocked build")
        return git(self.repo, "rev-parse", "HEAD")

    def cli(self, *args, success=True):
        result = subprocess.run([
            sys.executable, "-B", str(SCRIPT), *args, "--repo", str(self.repo),
        ], capture_output=True, text=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        self.assertNotEqual(result.returncode, 0)
        return result.stderr

    def move(self, phase, status, event, success=True):
        current = self.cli("validate")["state"]
        return self.cli(
            "transition", "--expect-phase", current["phase"], "--expect-status", current["status"],
            "--expect-branch", current["branch"], "--expect-archive", "null",
            "--set-phase", phase, "--set-status", status, "--event", event, success=success,
        )

    def reopen(self, phase):
        event = "build intent corrections requested" if phase == "define" else "build plan repair requested"
        return self.move(phase, "active", event)

    def test_plan_repair_reapproves_and_returns_to_build(self):
        from scripts import build_state, dispatch_driver
        old_records = dispatch_driver.records_root(self.repo)
        old_attempt = old_records / "review_wave_1_cycle_1/attempt-1/state.json"
        old_attempt.parent.mkdir(parents=True)
        old_attempt.write_text(json.dumps({"outcome": "collected"}))
        self.reopen("plan")
        prepared = self.cli("prepare-build-recovery")
        backup = Path(prepared["path"])
        self.assertEqual((backup / "PLAN-PANEL.md").read_text(), "Old plan approval evidence\n")
        self.assertFalse((self.project / "review/PLAN-PANEL.md").exists())
        self.cli("prepare-build-recovery")
        self.assertEqual(self.cli("route")["route"]["mode"], "build-repair")
        self.assertNotEqual(dispatch_driver.records_root(self.repo), old_records)
        replacement = self.project / "tasks/T001-repaired.md"
        replacement.write_text(self.task.read_text())
        self.task.unlink()
        approved = self.cli("approve", "--kind", "plan", "--expected-head", self.base)
        self.assertEqual(approved["state"]["status"], "done")
        self.assertEqual(self.cli("route")["route"]["phase"], "build")
        self.move("build", "active", "build started")
        self.assertNotEqual(dispatch_driver.records_root(self.repo), old_records)
        self.assertFalse(list(dispatch_driver.records_root(self.repo).rglob("state.json")))
        ready = build_state.ready(str(self.repo))
        self.assertEqual([task["id"] for task in ready["ready"]], ["T001"])
        self.assertFalse(self.task.exists())

    def test_intent_correction_reapproves_before_build(self):
        self.reopen("define")
        self.cli("prepare-build-recovery")
        self.assertEqual(self.cli("route")["route"]["mode"], "corrections")
        intent = self.project / "intent/INTENT.md"
        intent.write_text(intent.read_text() + "\n## Corrections\n\nUser: change the demo output.\n")
        self.move("define", "done", "milestone intent approved")
        self.assertEqual(self.cli("route")["route"]["mode"], "build-repair")
        self.move("plan", "active", "planning started")
        failure = self.move("build", "active", "build started", success=False)
        self.assertIn("illegal state transition", failure)
        self.cli("approve", "--kind", "plan", "--expected-head", self.base)
        self.move("build", "active", "build started")
        self.assertIn("User: change the demo output.", intent.read_text())

    def test_recovery_keeps_integration_locked(self):
        self.reopen("define")
        failure = self.cli("configure-integration", "--scope", "milestone", "--mode", "pull-request", success=False)
        self.assertIn("integration mode is locked", failure)

    def test_active_task_blocks_recovery_without_changes(self):
        self.task.write_text(self.task.read_text().replace("status: pending", "status: in-progress"))
        self.commit()
        original = (self.project / "STATE.md").read_bytes()
        failure = self.move("plan", "active", "build plan repair requested", success=False)
        self.assertIn("settle task ownership", failure)
        self.assertEqual((self.project / "STATE.md").read_bytes(), original)

    def test_plan_only_repair_cannot_change_intent_or_defer_approval(self):
        self.reopen("plan")
        self.cli("prepare-build-recovery")
        failure = self.cli("approve", "--kind", "plan", "--patch", success=False)
        self.assertIn("recovery requires a plan checkpoint", failure)
        intent = self.project / "intent/INTENT.md"
        intent.write_text(intent.read_text() + "Changed requirements\n")
        failure = self.cli("approve", "--kind", "plan", "--expected-head", self.base, success=False)
        self.assertIn("cannot change approved intent", failure)
        self.assertEqual(self.cli("validate")["state"]["status"], "active")

    def test_reapproval_reuses_only_reviews_of_unchanged_contracts(self):
        review = self.project / "review/wave-1.cycle1.md"
        review.write_text("Previously recorded wave evidence\n")
        self.base = self.commit()
        self.reopen("plan")
        self.cli("prepare-build-recovery")
        self.assertFalse(review.exists())
        self.cli("approve", "--kind", "plan", "--expected-head", self.base)
        self.assertEqual(review.read_text(), "Previously recorded wave evidence\n")

    def test_reapproval_restores_a_partial_copy_of_unchanged_evidence(self):
        review = self.project / "review/wave-1.cycle1.md"
        review.write_text("Previously recorded wave evidence\n")
        self.base = self.commit()
        self.reopen("plan")
        self.cli("prepare-build-recovery")
        review.write_text("Previously")
        self.cli("approve", "--kind", "plan", "--expected-head", self.base)
        self.assertEqual(review.read_text(), "Previously recorded wave evidence\n")

    def test_changed_contract_cannot_reuse_a_previous_review(self):
        review = self.project / "review/wave-1.cycle1.md"
        review.write_text("Previously recorded wave evidence\n")
        self.base = self.commit()
        self.reopen("plan")
        self.cli("prepare-build-recovery")
        self.task.write_text(self.task.read_text().replace("demo behavior holds", "new behavior holds"))
        review.write_text("Previously recorded wave evidence\n")
        failure = self.cli("approve", "--kind", "plan", "--expected-head", self.base, success=False)
        self.assertIn("changed wave must be reviewed after build resumes", failure)

    def test_plan_repair_preserves_real_landed_task_and_proof(self):
        from scripts import isolation, build_state
        self.move("build", "active", "build resumed")
        base = self.commit()
        self.task.write_text(self.task.read_text()
            .replace("status: pending", "status: in-progress")
            .replace("agent: null", "agent: builder")
            .replace("base: null", f"base: {base}")
            .replace("worktree: null", f"worktree: {self.repo}"))
        (self.repo / "app.py").write_text("print('implemented')\n")
        landed = isolation.land(self.repo, self.repo, base, "T001", "Demo task T001",
                                ".project/tasks/T001-demo.md", ["app.py"])
        self.move("build", "blocked", "plan defect requires repair")
        self.base = self.commit()
        original = self.task.read_text()
        self.reopen("plan")
        self.cli("prepare-build-recovery")
        self.task.write_text(original.replace("demo behavior holds", "changed behavior holds"))
        failure = self.cli("approve", "--kind", "plan", "--expected-head", self.base, success=False)
        self.assertIn("preserve landed task", failure)
        self.task.write_text(original)
        self.cli("approve", "--kind", "plan", "--expected-head", self.base)
        self.move("build", "active", "build started")
        proof = build_state.reconcile(str(self.repo), task_id="T001")
        self.assertEqual(proof["classification"], "proven-landed")
        self.assertEqual(proof["history"]["candidates"][0]["commit"], landed["commit"])

    def test_recovery_rejects_a_changed_review_backup(self):
        self.reopen("plan")
        prepared = self.cli("prepare-build-recovery")
        (Path(prepared["path"]) / "PLAN-PANEL.md").write_text("Changed old evidence\n")
        failure = self.cli("prepare-build-recovery", success=False)
        self.assertIn("review backup differs from the recovery base", failure)

    def test_recovery_cannot_change_milestone_identity(self):
        self.reopen("define")
        failure = self.cli(
            "transition", "--expect-phase", "define", "--expect-status", "active",
            "--expect-branch", "gsd-path/M001", "--expect-archive", "null",
            "--expect-milestone", "demo", "--set-status", "done", "--set-milestone", "different",
            "--event", "milestone intent approved", success=False,
        )
        self.assertIn("recovery must preserve milestone identity", failure)

    def test_unsettled_reviewer_blocks_recovery(self):
        from scripts import dispatch_driver
        record = dispatch_driver.records_root(self.repo) / "reviews/wave-1/attempt-1/state.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"outcome": None, "task_id": "review_wave_1"}))
        failure = self.move("plan", "active", "build plan repair requested", success=False)
        self.assertIn("settle dispatch records before recovery", failure)

    def test_pending_reviewer_cleanup_blocks_recovery_until_settled(self):
        from scripts import dispatch_driver
        records = dispatch_driver.records_root(self.repo)
        record = records / "reviews/wave-1/attempt-1/state.json"
        record.parent.mkdir(parents=True)
        record.write_text(json.dumps({"outcome": "collected", "cleanup_pending": True}))
        original = (self.project / "STATE.md").read_bytes()
        for phase, event in (
            ("define", "build intent corrections requested"),
            ("plan", "build plan repair requested"),
        ):
            with self.subTest(phase=phase):
                failure = self.move(phase, "active", event, success=False)
                self.assertIn("settle dispatch records before recovery", failure)
                self.assertEqual((self.project / "STATE.md").read_bytes(), original)
                self.assertEqual(dispatch_driver.records_root(self.repo), records)
            (self.project / "STATE.md").write_bytes(original)
        record.write_text(json.dumps({
            "outcome": "collected", "cleanup_pending": False, "cleanup_complete": True,
        }))
        self.assertEqual(self.reopen("plan")["state"]["phase"], "plan")
        self.assertNotEqual(dispatch_driver.records_root(self.repo), records)

    def test_blocked_build_returns_to_requested_contract_owner(self):
        for phase, event in (
            ("define", "build intent corrections requested"),
            ("plan", "build plan repair requested"),
        ):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as tmp:
                repo = Path(tmp)
                git(repo, "init", "-b", "gsd-path/M001")
                git(repo, "config", "user.email", "test@example.test")
                git(repo, "config", "user.name", "Test")
                project = repo / ".project"
                for directory in ("plan", "tasks", "intent"):
                    (project / directory).mkdir(parents=True)
                (project / "STATE.md").write_text(state_text(
                    phase="build", status="blocked", milestone="demo",
                    branch="gsd-path/M001",
                ))
                (project / "intent/INTENT.md").write_text(
                    "# Intent\n\nLane: quick\n\n## Success criteria\n\n"
                    "- SC1: The demo behavior holds.\n"
                )
                (project / "plan/PLAN.md").write_text(PLAN_WAVE.format(title="demo"))
                (project / "tasks/T001-demo.md").write_text(TASK_TEMPLATE.format(
                    task_id="T001", files_block="  - app.py",
                    context="Repair the demo.", approach="Keep the public interface.",
                    contract="- None", verify="python3 app.py",
                ))
                (repo / "app.py").write_text("print('demo')\n")
                git(repo, "add", ".")
                git(repo, "commit", "-m", "build: checkpoint blocked build")
                original_task = (project / "tasks/T001-demo.md").read_bytes()
                result = subprocess.run([
                    sys.executable, "-B", str(SCRIPT), "transition", "--repo", str(repo),
                    "--expect-phase", "build", "--expect-status", "blocked",
                    "--expect-branch", "gsd-path/M001", "--expect-archive", "null",
                    "--set-phase", phase, "--set-status", "active", "--event", event,
                ], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["state"]["phase"], phase)
                routed = subprocess.run([
                    sys.executable, "-B", str(SCRIPT), "route", "--repo", str(repo),
                ], capture_output=True, text=True, check=True)
                self.assertEqual(json.loads(routed.stdout)["route"]["phase"], phase)
                self.assertEqual((project / "tasks/T001-demo.md").read_bytes(), original_task)


if __name__ == "__main__":
    unittest.main()
