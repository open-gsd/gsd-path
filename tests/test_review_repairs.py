"""Repair evidence must follow real task landings, not a shared branch tip."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import _common, build_state, isolation
from tests.test_build_state import run_git
from tests.test_review_findings import PLAN, TASK


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/review_findings.py"


class RepairEvidenceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.name", "Test")
        run_git(self.repo, "config", "user.email", "test@example.com")
        run_git(self.repo, "switch", "-q", "-c", "gsd-path/M001")
        self.project = self.repo / ".project"
        for directory in ("tasks", "plan", "review"):
            (self.project / directory).mkdir(parents=True, exist_ok=True)
        (self.project / "plan/PLAN.md").write_text(
            PLAN.format(cycles=3, skeptics="off", depth="full")
            + "\n## Wave 2 — repair\nGoal: repair the observed failure\nReview depth: full\n"
        )
        (self.repo / "count.py").write_text("print('initial')\n")
        self.original_file = self.task("T001", "Original", 1, "", "")
        self.commit("fixture")
        self.original = self.land("T001", "Original", self.original_file, "bad")
        self.review = self.project / "review/wave-1.cycle1.md"
        self.review.write_text("""# Review — wave 1, cycle 1
Wave verdict: blocked
Cycle: 1
Depth: full
Tasks reviewed: 1
## T001 — Original: fail
- ❌ Prints good — found: prints bad, count.py:1
  fix: print good
""")
        self.findings = """## Review findings

### t001_ac1
Criterion: Prints good
Observation 1 — canonical:
Prints good — found: prints bad, count.py:1 fix: print good

"""
        self.repair_file = self.task("T002", "Repair", 2, "T001", self.findings)

    def task(self, task_id, title, wave, deps, findings):
        path = self.project / "tasks" / f"{task_id}-task.md"
        text = TASK.format(id=task_id, title=title, files="  - count.py",
                           interface="None", owned="None", ac1="Prints good",
                           ac2="Exits successfully")
        text = text.replace("wave: 1", f"wave: {wave}").replace("deps: []", f"deps: [{deps}]")
        text = text.replace("status: done", "status: pending")
        text = text.replace("python3 -m unittest tests.test_demo", "python3 -B count.py")
        path.write_text(text.replace("## Log", findings + "## Log"))
        return path.relative_to(self.repo).as_posix()

    def commit(self, message):
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-qm", message)
        return run_git(self.repo, "rev-parse", "HEAD")

    def land(self, task_id, title, task_file, output):
        base = run_git(self.repo, "rev-parse", "HEAD")
        isolation.activate_task(self.repo, base, task_id, "coder", task_file, None)
        (self.repo / "count.py").write_text(f"print({output!r})\n")
        result = subprocess.run([sys.executable, "-B", "count.py"], cwd=self.repo,
                                capture_output=True, text=True, check=True)
        commit = isolation.land(self.repo, self.repo, base, task_id, title,
                                task_file, ["count.py"])["commit"]
        build_state.verify_record(str(self.repo), "python3 -B count.py", commit, "pass",
                                  {"stdout": result.stdout, "stderr": result.stderr,
                                   "exit_code": result.returncode})
        return commit

    def finish_repair(self):
        self.commit("plan repair")
        return self.land("T002", "Repair", self.repair_file, "good")

    def cli(self):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "repair-evidence", "--repo", str(self.repo),
             "--wave", "1", "--cycle", "1", "--task", "T002"],
            capture_output=True, text=True,
        )
        return result, json.loads(result.stdout) if result.stdout else {}

    def test_proven_repair_resolves_to_its_isolated_product_without_reverification(self):
        repair = self.finish_repair()
        before = run_git(self.repo, "status", "--porcelain")
        ledger = (self.repo / _common.VERIFY_LEDGER_PATH).read_bytes()
        result, evidence = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr or evidence)
        self.assertEqual(evidence["repair"]["commit"], repair)
        self.assertEqual(evidence["originals"][0]["commit"], self.original)
        self.assertEqual(evidence["groups"][0]["locator"], "t001_ac1")
        self.assertEqual(evidence["verification"]["entry"]["execution"]["stdout"], "good\n")
        self.assertEqual(run_git(self.repo, "status", "--porcelain"), before)
        self.assertEqual((self.repo / _common.VERIFY_LEDGER_PATH).read_bytes(), ledger)

    def test_rejects_unlanded_repair(self):
        self.commit("pending repair")
        result, evidence = self.cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("done", evidence["error"])

    def test_rejects_unrelated_missing_or_changed_evidence(self):
        expected_errors = {
            "dependency": "dependencies/files",
            "finding": "eligible source finding batch",
            "intervening": "unlinked changes",
            "ledger": "passing Verify",
            "report": "exact criterion and observations",
            "task": "task",
            "later-product": "product changed after",
        }
        for fault, error in expected_errors.items():
            with self.subTest(fault=fault):
                # Each case needs its own real history; setUp's fixture is replaced.
                self.setUp()
                path = self.repo / self.repair_file
                if fault == "dependency":
                    path.write_text(path.read_text().replace("deps: [T001]", "deps: []"))
                elif fault == "finding":
                    path.write_text(path.read_text().replace("### t001_ac1", "### t001_ac9"))
                elif fault == "intervening":
                    (self.repo / "count.py").write_text("print('unrelated')\n")
                self.finish_repair()
                if fault == "ledger":
                    (self.repo / _common.VERIFY_LEDGER_PATH).unlink()
                elif fault == "report":
                    self.review.write_text(self.review.read_text().replace("prints bad", "prints worse"))
                elif fault == "task":
                    path.write_text(path.read_text().replace("Prints good", "Anything passes"))
                elif fault == "later-product":
                    (self.repo / "count.py").write_text("print('later unrelated change')\n")
                result, evidence = self.cli()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(evidence.get("status"), "error", result.stderr or evidence)
                self.assertIn(error, evidence["error"])
