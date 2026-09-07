import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_state, isolation, lean_verification


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ISOLATION_SCRIPT = PROJECT_ROOT / "scripts" / "isolation.py"
RECEIPT = ".project/build/rebase-adoption.json"
RULING = "Adopt this rebase; preserve original evidence."


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


def task_text(task_id: str, title: str, path: str, status: str = "pending") -> str:
    return (
        f"---\nid: {task_id}\ntitle: {title}\nwave: 1\ndeps: []\nstatus: {status}\n"
        f"agent: null\nbase: null\nworktree: null\ntask_branch: null\nfiles:\n  - {path}\n"
        "---\n\n# Task\n\n## Acceptance criteria\n\n1. Value is two.\n\n## Log\n\n"
    )


class RebaseRecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name)
        git(self.repo, "init", "-b", "gsd-path/M001")
        git(self.repo, "config", "user.name", "Test")
        git(self.repo, "config", "user.email", "test@example.test")
        git(self.repo, "config", "core.hooksPath", str(self.repo / "no-hooks"))
        self.path = ".project/tasks/T001-change.md"
        task = self.repo / self.path
        task.parent.mkdir(parents=True)
        task.write_text(task_text("T001", "Change value", "value.txt"))
        (self.repo / "value.txt").write_text("one\n")
        plan = self.repo / ".project/plan/PLAN.md"
        plan.parent.mkdir()
        plan.write_text("# Plan\n\n## Wave 1 — change\n\nReview depth: full\n")
        self.commit("plan")
        self.base = git(self.repo, "rev-parse", "HEAD")
        done = task_text("T001", "Change value", "value.txt", "done").replace(
            "agent: null", "agent: worker").replace("base: null", "base: " + self.base)
        task.write_text(done + "- Verify passed.\n")
        (self.repo / "value.txt").write_text("two\n")
        body = isolation.task_commit_body(self.path, [self.path, "value.txt"], self.base)
        self.commit("T001: Change value", body)
        self.original = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "branch", "keep/original")
        git(self.repo, "checkout", "-B", "gsd-path/M001", self.base)
        (self.repo / "unrelated.txt").write_text("upstream\n")
        self.commit("upstream")
        # Rebase the plan as well so the original Base is absent from ancestry.
        git(self.repo, "checkout", "--orphan", "rebased")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "plan")
        git(self.repo, "cherry-pick", self.original)
        git(self.repo, "branch", "-M", "gsd-path/M001")
        self.head = git(self.repo, "rev-parse", "HEAD")

    def commit(self, subject: str, body: str = "") -> None:
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", subject, *(["-m", body] if body else []))
        self.head = git(self.repo, "rev-parse", "HEAD")

    def adopt(self, success: bool = True) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            (sys.executable, str(ISOLATION_SCRIPT), "adopt-rebase", "--repo", str(self.repo),
             "--original-head", self.original, "--head", self.head, "--ruling", RULING),
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        return result

    def verify(self):
        return isolation.verify_landed_task_files(
            self.repo, [self.repo / self.path], ".project/tasks", self.head
        )

    def recover_task(self, task_id: str = "T001"):
        report = isolation.recover(self.repo, Path(".project/tasks"))
        return next(task for task in report["tasks"] if task["task_id"] == task_id)

    def test_explicit_adoption_restores_landing_gate(self) -> None:
        with self.assertRaises(isolation.IsolationError):
            self.verify()
        result = self.adopt()
        self.assertEqual(json.loads(result.stdout)["verdict"], "adopted")
        self.assertEqual(self.verify()["tasks"][0]["verdict"], "attested")
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.head)
        self.assertEqual(git(self.repo, "rev-parse", "keep/original"), self.original)

    def test_receipt_matches_library_output(self) -> None:
        self.adopt()
        receipt = (self.repo / RECEIPT).read_text()
        expected = isolation.adopt_rebase(self.repo, self.original, self.head, RULING)
        self.assertEqual(receipt, json.dumps(expected, indent=2) + "\n")
        self.assertEqual(expected["schema"], "gsd-path/rebase-adoption/v1")

    def test_changed_rebased_product_rejected(self) -> None:
        (self.repo / "value.txt").write_text("wrong\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "--amend", "--no-edit")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.adopt(False)

    def test_changed_task_contract_rejected(self) -> None:
        task = self.repo / self.path
        task.write_text(task.read_text().replace("Value is two.", "Anything passes."))
        self.commit("change contract")
        self.adopt(False)

    def test_tampered_receipt_rejected(self) -> None:
        self.adopt()
        path = self.repo / RECEIPT
        receipt = json.loads(path.read_text())
        receipt["tasks"][0]["original_landing"] = self.base
        path.write_text(json.dumps(receipt))
        with self.assertRaises(isolation.IsolationError):
            self.verify()

    def test_changed_current_task_rejected(self) -> None:
        self.adopt()
        task = self.repo / self.path
        task.write_text(task.read_text() + "- fabricated verification\n")
        with self.assertRaises(isolation.IsolationError):
            self.verify()

    def test_missing_task_receipt_rejected(self) -> None:
        self.adopt()
        path = self.repo / RECEIPT
        receipt = json.loads(path.read_text())
        receipt["tasks"] = []
        path.write_text(json.dumps(receipt))
        with self.assertRaises(isolation.IsolationError):
            self.verify()

    def test_product_change_after_adoption_rejected(self) -> None:
        self.adopt()
        (self.repo / "value.txt").write_text("three\n")
        self.commit("product changed")
        with self.assertRaises(isolation.IsolationError):
            self.verify()

    def test_owner_adoption_preserves_both_log_versions(self) -> None:
        task = self.repo / self.path
        task.write_text(task.read_text().replace(
            "Verify passed.", "Verify passed; corrected approval reference."))
        self.commit("correct approval reference")
        self.adopt()
        self.assertEqual(self.verify()["tasks"][0]["verdict"], "attested")
        receipt = json.loads((self.repo / RECEIPT).read_text())
        self.assertIn("- Verify passed.\n", receipt["tasks"][0]["original_task"])
        self.assertIn("corrected approval reference", receipt["tasks"][0]["adopted_task"])

    def test_ship_inputs_accept_only_valid_adoption_receipt(self) -> None:
        self.adopt()
        (self.repo / ".project/STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: fixture\nmilestone: adoption\n"
            "phase: ship\nstatus: active\nbranch: gsd-path/M001\narchive: null\n"
            "integration_default: direct\nintegration: direct\nintegration_source: default\n"
            "---\n\n## Log\n")
        lean_verification._require_ship_inputs(self.repo, self.head)
        (self.repo / RECEIPT).write_text("{}")
        with self.assertRaises((isolation.IsolationError, build_state.BuildStateError)):
            lean_verification._require_ship_inputs(self.repo, self.head)

    def test_recover_reports_adopted_task_attested(self) -> None:
        self.assertEqual(self.recover_task()["verdict"], "block")
        self.adopt()
        report = isolation.recover(self.repo, Path(".project/tasks"))
        self.assertEqual(report["verdict"], "ok")
        task = report["tasks"][0]
        self.assertEqual(task["verdict"], "attested")
        self.assertEqual(task["provenance"], "owner-authorized-rebase")
        self.assertEqual(task["commit"], self.head)
        self.assertEqual(task["base"], self.base)

    def test_recover_blocks_tampered_receipt_without_raising(self) -> None:
        self.adopt()
        path = self.repo / RECEIPT
        receipt = json.loads(path.read_text())
        receipt["tasks"][0]["original_base"] = self.head
        path.write_text(json.dumps(receipt))
        task = self.recover_task()
        self.assertEqual(task["verdict"], "block")
        self.assertTrue(task["reason"].startswith("rebase adoption receipt is invalid: "), task)
        path.write_text("not json")
        self.assertTrue(self.recover_task()["reason"].startswith("rebase adoption receipt is invalid: "))

    def test_landing_commit_after_adoption_keeps_attested(self) -> None:
        self.adopt()
        second = ".project/tasks/T002-second.md"
        (self.repo / second).write_text(task_text("T002", "Second value", "value2.txt", "done"))
        (self.repo / "value2.txt").write_text("two\n")
        self.commit("T002: Second value",
                    isolation.task_commit_body(second, [second, "value2.txt"], self.head))
        self.assertEqual(self.recover_task()["verdict"], "attested")
        self.assertEqual(self.verify()["tasks"][0]["verdict"], "attested")

    def test_bare_product_commit_after_adoption_blocks(self) -> None:
        self.adopt()
        (self.repo / "value.txt").write_text("three\n")
        self.commit("product changed")
        task = self.recover_task()
        self.assertEqual(task["verdict"], "block")
        self.assertIn("product changed outside a landing after the adopted revision", task["reason"])

    def test_adopt_skips_pending_and_refuses_in_progress(self) -> None:
        second = self.repo / ".project/tasks/T002-second.md"
        second.write_text(task_text("T002", "Second value", "value2.txt"))
        self.commit("add pending task")
        self.adopt()
        receipt = json.loads((self.repo / RECEIPT).read_text())
        self.assertEqual([row["path"] for row in receipt["tasks"]], [self.path])
        (self.repo / RECEIPT).unlink()
        second.write_text(task_text("T002", "Second value", "value2.txt", "in-progress"))
        self.commit("start second task")
        result = self.adopt(False)
        self.assertIn("rebasing a in-progress task is unsupported", result.stderr)

    def test_adopt_rejects_same_heads_and_empty_ruling(self) -> None:
        with self.assertRaises(isolation.IsolationError):
            isolation.adopt_rebase(self.repo, self.head, self.head, RULING)
        with self.assertRaises(isolation.IsolationError):
            isolation.adopt_rebase(self.repo, self.original, self.head, "  ")
        with self.assertRaises(isolation.IsolationError):
            isolation.adopt_rebase(self.repo, self.original[:7], self.head, RULING)

    def test_empty_subject_in_history_is_tolerated(self) -> None:
        git(self.repo, "commit", "-q", "--allow-empty", "--allow-empty-message", "-m", "")
        self.head = git(self.repo, "rev-parse", "HEAD")
        self.adopt()
        self.assertEqual(self.recover_task()["verdict"], "attested")


if __name__ == "__main__":
    unittest.main()
