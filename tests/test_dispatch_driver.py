import argparse
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from scripts import dispatch_driver
from tests import test_handoffs
from tests.test_pipeline_state import run_git

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "scripts/dispatch_driver.py"
ROLE_BRIEF = PROJECT_ROOT / "skills/gsd-path-build/references/coder.md"
TASK_TEMPLATE = PROJECT_ROOT / "skills/gsd-path-build/templates/task.md"

# A stand-in coder: reads the brief on stdin, edits the task's declared file
# in the named worktree, appends to the Log, and prints the terminal RESULT line.
FAKE_CODER = textwrap.dedent(
    """
    import os, re, sys, time
    from pathlib import Path
    brief = sys.stdin.read()
    worktree = Path(re.search(r"^Work only in this worktree root: (.+)$", brief, re.M).group(1))
    task_path = Path(re.search(r"^Task file: (.+)$", brief, re.M).group(1))
    task_id = re.search(r"task (T\\d+)\\.", brief).group(1)
    text = task_path.read_text()
    declared = re.search(r"^files:\\n  - (.+)$", text, re.M).group(1)
    mode = os.environ.get("FAKE_MODE", "ready")
    if mode == "slow":
        time.sleep(3)
    if mode == "question" and "Orchestrator answer:" not in text:
        task_path.write_text(text + "- 2026-09-07 — NEEDS-ORCHESTRATOR: which greeting? — readings: hi, hello\\n")
        print(f"RESULT: {task_id} blocked")
        sys.exit(0)
    if mode == "question2" and "which file?" not in text:
        task_path.write_text(text + "- 2026-09-07 — NEEDS-ORCHESTRATOR: which file? — readings: a, b\\n")
        print(f"RESULT: {task_id} blocked")
        sys.exit(0)
    target = worktree / declared
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("raise SystemExit(1)\\n" if mode == "badverify" else "print('hello')\\n")
    task_path.write_text(text + f"- 2026-09-07 — implemented {declared}; Verify pass\\n")
    if mode != "silent":
        print(f"RESULT: {task_id} ready")
    """
)


class DispatchDriverTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "repo"
        self.root.mkdir()

    def head(self, root: Path) -> str:
        return run_git(root, "rev-parse", "HEAD").stdout.strip()

    def fixture(self, root: Path, deps_t002: str = "[]", wave_t002: int = 1) -> str:
        run_git(root, "init", "-b", "gsd-path/M001")
        run_git(root, "config", "user.name", "Test")
        run_git(root, "config", "user.email", "test@example.test")
        handoffs = test_handoffs.HandoffValidationTests()
        handoffs.write_plan_handoff(root)
        handoffs.write_coverage_task(root, "T002", "- SC2", acceptance="1. The demo test suite is green.",
                                     deps=deps_t002, wave=wave_t002)
        if wave_t002 != 1:
            plan = root / ".project/plan/PLAN.md"
            text = plan.read_text().replace(
                "| T002 | Demo task T002 | — | tests/test_app.py |\n", "")
            text = text.replace(
                "\n## Intent coverage",
                f"\n## Wave {wave_t002} — demo tests\n\nGoal: Prove the demo tests.\n"
                "Review depth: full\n\n| Task | Title | Deps | Files |\n|------|-------|------|-------|\n"
                "| T002 | Demo task T002 | — | tests/test_app.py |\n\n## Intent coverage", 1)
            plan.write_text(text)
        handoffs.write_state(root, "build", "active")
        (root / "fake_coder.py").write_text(FAKE_CODER)
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "fixture")
        return self.head(root)

    def driver(self, root: Path, *args: str, mode: str = "ready") -> dict:
        env = dict(os.environ, FAKE_MODE=mode)
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *args, "--repo", str(root)],
            capture_output=True, text=True, env=env,
        )
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def round(self, root: Path, *extra: str, mode: str = "ready", wave: int = 1) -> dict:
        return self.driver(
            root, "round", "--wave", str(wave), "--child-command", f"{sys.executable} {root / 'fake_coder.py'}",
            "--role-brief", str(ROLE_BRIEF), "--task-template", str(TASK_TEMPLATE), *extra, mode=mode,
        )

    def subjects(self, root: Path) -> list:
        return run_git(root, "log", "--format=%s").stdout.strip().splitlines()

    def branches(self, root: Path) -> list:
        return run_git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout.split()

    def test_parallel_round_lands_both_tasks_and_retires_isolates(self) -> None:
        root = self.root
        self.fixture(root)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(sorted(item["task"] for item in receipt["landed"]), ["T001", "T002"])
        self.assertTrue(all(item["mode"] == "parallel" for item in receipt["landed"]))
        subjects = self.subjects(root)
        self.assertIn("T001: Demo task T001", subjects)
        self.assertIn("T002: Demo task T002", subjects)
        self.assertEqual(subjects[0], "build: record dispatch bookkeeping")
        self.assertEqual(self.branches(root), ["gsd-path/M001"])
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        # Only a landing whose parent is the recorded base proves the verified tree.
        ledger = (root / ".project/build/verify-ledger.jsonl").read_text().splitlines()
        self.assertEqual(len(ledger), 1)
        self.assertEqual([item["ledger"] for item in receipt["landed"]], [True, False])
        for task in ("T001", "T002"):
            text = (root / f".project/tasks/{task}-demo.md").read_text()
            self.assertIn("status: done", text)
            self.assertIn("orchestrator Verify (isolate gsd-path-task/", text)
        dispatches = self.driver(root, "status")["dispatches"]
        self.assertEqual([d["outcome"] for d in dispatches], ["landed", "landed"])

    def test_serial_rounds_reproduce_in_the_sidecar_and_unlock_dependents(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001", "T002"])
        self.assertTrue(all(item["mode"] == "serial" for item in receipt["landed"]))
        self.assertEqual(self.branches(root), ["gsd-path/M001"])
        text = (root / ".project/tasks/T001-demo.md").read_text()
        self.assertIn("orchestrator Verify (sidecar gsd-path-verify/task-t001-verify): pass", text)
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")

    def test_question_blocks_until_answered_then_redispatches_the_same_isolate(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", mode="question")
        self.assertEqual(receipt["status"], "question", receipt)
        self.assertIn("which greeting?", receipt["questions"][0]["question"])
        self.assertEqual(self.head(root), head)
        again = self.round(root, mode="question")
        self.assertEqual(again["status"], "question", again)
        self.assertEqual(self.head(root), head)
        self.assertIn("no open question", json.dumps(
            self.driver(root, "answer", "--task-id", "T002", "--answer", "hello")))
        refused = self.driver(root, "finish", "--task-id", "T001")
        self.assertEqual(refused["status"], "blocked")
        self.assertIn("record is question", refused["reason"])
        answered = self.driver(root, "answer", "--task-id", "T001", "--answer", "hello — INTENT SC1")
        self.assertEqual(answered["status"], "answered")
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001", "T002"])
        text = (root / ".project/tasks/T001-demo.md").read_text()
        self.assertIn("NEEDS-ORCHESTRATOR: which greeting?", text)
        self.assertIn("Orchestrator answer: hello — INTENT SC1", text)
        self.assertIn("status: done", text)
        dispatches = self.driver(root, "status")["dispatches"]
        self.assertEqual(dispatches[0]["attempt"], 2)

    def test_interrupted_redispatch_preserves_the_answer_for_retry(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        current = dispatch_driver.Round(root, argparse.Namespace(project_dir=".project", wave=1, wait=None))
        with mock.patch.object(dispatch_driver, "spawn", side_effect=dispatch_driver.DriverStop("interrupted")):
            receipt = current.run()
        self.assertEqual(receipt["status"], "blocked", receipt)
        state = self.driver(root, "status")["dispatches"][0]
        self.assertEqual(state["outcome"], "question")
        self.assertTrue(state["answered"])
        self.assertEqual(self.head(root), head)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001", "T002"])

    def test_orphaned_active_task_blocks_bookkeeping_and_completion(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        record = root / ".git/gsd-path/dispatch/T001/attempt-1/state.json"
        state = json.loads(record.read_text())
        state["outcome"] = "redispatched"
        record.write_text(json.dumps(state))
        task = root / ".project/tasks/T001-demo.md"
        before = task.read_bytes()
        receipt = self.round(root)
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["tasks"], ["T001"])
        self.assertEqual(self.head(root), head)
        self.assertEqual(task.read_bytes(), before)

    def test_child_exit_receipt_preserves_parent_state_and_is_loaded_by_status(self) -> None:
        root = self.root
        self.fixture(root)
        attempt = root / ".git/gsd-path/dispatch/T001/attempt-1"
        attempt.mkdir(parents=True)
        record = attempt / "state.json"
        state = {"task_id": "T001", "worktree": str(root), "pid": 123,
                 "command": [sys.executable, "-c", "raise SystemExit(7)"]}
        record.write_text(json.dumps(state))
        before = record.read_bytes()
        (attempt / "brief.md").write_text("brief")
        subprocess.run([sys.executable, "-B", str(SCRIPT), "_child", "--state", str(record)],
                       check=True, capture_output=True)
        self.assertEqual(record.read_bytes(), before)
        completion = json.loads((attempt / "exit.json").read_text())
        self.assertEqual(completion["exit_code"], 7)
        self.assertFalse(completion["timed_out"])
        self.assertTrue(completion["finished_at"])
        loaded = self.driver(root, "status")["dispatches"][0]
        self.assertEqual(loaded["pid"], 123)
        self.assertEqual(loaded["exit_code"], 7)
        self.assertEqual(loaded["finished_at"], completion["finished_at"])

    def test_failed_verify_lands_nothing_and_reports_the_output(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", mode="badverify")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("Verify failed", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["blocked"][0]["execution"]["exit_code"], 1)
        self.assertEqual(self.head(root), head)
        self.assertNotIn("gsd-path-verify/task-t001-verify", self.branches(root))
        text = (root / ".project/tasks/T001-demo.md").read_text()
        self.assertIn("orchestrator Verify (sidecar gsd-path-verify/task-t001-verify): fail", text)
        again = self.round(root, mode="badverify")
        self.assertEqual(again["status"], "blocked", again)
        self.assertTrue(again["blocked"][0]["reported"])
        self.assertEqual(self.head(root), head)

    def test_child_without_result_line_is_blocked_not_landed(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", mode="silent")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("no RESULT line", receipt["blocked"][0]["reason"])
        self.assertEqual(self.head(root), head)

    def test_later_wave_blocks_while_an_earlier_wave_is_unfinished(self) -> None:
        root = self.root
        head = self.fixture(root, wave_t002=2)
        note = root / ".project/review-note.md"
        note.write_text("Pending bookkeeping\n")
        receipt = self.round(root, wave=2)
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"],
                         "wave 1 is still unfinished; run round --wave 1 first")
        self.assertEqual(receipt["landed"], [])
        self.assertEqual(receipt["dispatched"], [])
        self.assertEqual(self.head(root), head)
        self.assertEqual(run_git(root, "status", "--porcelain").stdout,
                         "?? .project/review-note.md\n")

    def test_round_stops_at_the_wave_boundary(self) -> None:
        root = self.root
        self.fixture(root, wave_t002=2)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(receipt["wave"], 1)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001"])
        self.assertIn("status: pending", (root / ".project/tasks/T002-demo.md").read_text())
        repeated = self.round(root, "--wait", "60")
        self.assertEqual(repeated["status"], "done", repeated)
        self.assertEqual(repeated["wave"], 1)
        self.assertEqual(repeated["dispatched"], [])
        receipt = self.round(root, "--wait", "60", wave=2)
        self.assertEqual(receipt["wave"], 2)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T002"])

    def test_round_without_wait_returns_in_flight_and_settles_later(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, mode="slow")
        self.assertEqual(receipt["status"], "in-flight", receipt)
        self.assertEqual([item["task_id"] for item in receipt["in_flight"]], ["T001"])
        receipt = self.round(root, "--wait", "60", mode="slow")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001", "T002"])

    def test_finish_lands_a_task_dispatched_by_hand_from_its_frontmatter(self) -> None:
        root = self.root
        head = self.fixture(root, deps_t002="[T001]")
        # The orchestrator isolated and activated the task itself, then a coder edited the primary.
        subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "scripts/workflow_run.py"),
                        "prepare-task", "--repo", str(root), "--expected-head", head,
                        "--task-id", "T001", "--round-size", "1"], check=True, capture_output=True)
        subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "scripts/isolation.py"),
                        "activate-task", "--repo", str(root), "--base", head, "--task-id", "T001",
                        "--agent", "build_t001", "--task-file", ".project/tasks/T001-demo.md"],
                       check=True, capture_output=True)
        (root / "src").mkdir()
        (root / "src/app.py").write_text("print('hello')\n")
        receipt = self.driver(root, "finish", "--task-id", "T001")
        self.assertEqual(receipt["status"], "landed", receipt)
        self.assertEqual(receipt["landed"][0]["mode"], "serial")
        self.assertTrue(Path(receipt["landed"][0]["verify"]["evidence"]).is_file())
        self.assertEqual(self.subjects(root)[0], "T001: Demo task T001")
        self.assertEqual(self.branches(root), ["gsd-path/M001"])
        self.assertIn("status: done", (root / ".project/tasks/T001-demo.md").read_text())

    def test_resume_after_in_flight_does_not_cross_the_wave_boundary(self) -> None:
        root = self.root
        self.fixture(root, wave_t002=2)
        receipt = self.round(root, mode="slow")
        self.assertEqual(receipt["status"], "in-flight", receipt)
        receipt = self.round(root, "--wait", "60", mode="slow")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(receipt["wave"], 1)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001"])
        self.assertEqual(receipt["dispatched"], [])
        self.assertIn("status: pending", (root / ".project/tasks/T002-demo.md").read_text())

    def test_second_question_after_an_answer_is_still_a_question(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        # The fake coder asks again only while no answer is recorded, so pre-seed a second question.
        task = root / ".project/tasks/T001-demo.md"
        receipt = self.round(root, "--wait", "60", mode="question2")
        self.assertEqual(receipt["status"], "question", receipt)
        self.assertIn("which file?", receipt["questions"][0]["question"])
        self.assertEqual(self.driver(root, "status")["dispatches"][0]["attempt"], 2)
        self.assertIn("Orchestrator answer: hello", task.read_text())

    def test_finish_refuses_a_running_child_and_a_recovered_landing_is_recorded(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, mode="slow")
        self.assertEqual(receipt["status"], "in-flight", receipt)
        refused = self.driver(root, "finish", "--task-id", "T001")
        self.assertEqual(refused["status"], "blocked")
        self.assertIn("running child", refused["reason"])
        receipt = self.round(root, "--wait", "60", mode="slow")
        self.assertEqual(receipt["status"], "done", receipt)
        # Simulate an interruption after land but before the record was updated.
        records = list((root / ".git/gsd-path/dispatch/T001").glob("attempt-*/state.json"))
        state = json.loads(records[0].read_text())
        state["outcome"] = None
        records[0].write_text(json.dumps(state))
        receipt = self.round(root, "--wait", "60", mode="slow")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(json.loads(records[0].read_text())["outcome"], "landed")


if __name__ == "__main__":
    unittest.main()
