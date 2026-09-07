import argparse
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import time
import unittest
from contextlib import redirect_stdout
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
    if mode in ("question", "questionjson") and "Orchestrator answer:" not in text:
        task_path.write_text(text + "- 2026-09-07 — NEEDS-ORCHESTRATOR: which greeting? — readings: hi, hello\\n")
        if mode == "questionjson":
            import json
            print(json.dumps({"result": f"RESULT: {task_id} blocked", "usage": {"output_tokens": 3}}))
        else:
            print(f"RESULT: {task_id} blocked")
        sys.exit(0)
    if mode == "question2" and "which file?" not in text:
        task_path.write_text(text + "- 2026-09-07 — NEEDS-ORCHESTRATOR: which file? — readings: a, b\\n")
        print(f"RESULT: {task_id} blocked")
        sys.exit(0)
    if mode == "questioncrash":
        task_path.write_text(text + "- 2026-09-07 — NEEDS-ORCHESTRATOR: which file? — readings: a, b\\n")
        sys.exit(2)
    target = worktree / declared
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("raise SystemExit(1)\\n" if mode == "badverify" else "print('hello')\\n")
    task_path.write_text(text + f"- 2026-09-07 — implemented {declared}; Verify pass\\n")
    if mode == "claudejson":
        import json
        print(json.dumps({"result": f"RESULT: {task_id} ready", "usage": {"output_tokens": 3}}))
    elif mode != "silent":
        print(f"RESULT: {task_id} ready")
    """
)

# A stand-in reviewer: reads the brief, stages a wave review naming only the wave's tasks.
FAKE_REVIEWER = textwrap.dedent(
    """
    import os, re, sys
    from pathlib import Path
    brief = sys.stdin.read()
    staged = Path(re.search(r"^Write exactly this output file: (.+)$", brief, re.M).group(1))
    name = re.search(r"logical task name (\\S+)\\.", brief).group(1)
    wave, cycle = re.search(r"wave (\\d+), cycle (\\d+)", brief).groups()
    lens = re.search(r"; lens: (\\w+)\\.", brief)
    tasks = re.findall(r"^- (T\\d+): ", brief, re.M)
    verdict = os.environ.get("FAKE_REVIEW", "pass")
    criteria = {"T001": ("The demo command prints hello.", "SC1"),
                "T002": ("The demo test suite is green.", "SC2")}
    lines = [f"# Review — wave {wave}, cycle {cycle}", "", f"Wave verdict: {verdict}", f"Cycle: {cycle}",
             "Depth: " + ("deep" if lens else "full")]
    if lens:
        lines.append(f"Lens: {lens.group(1)}")
    lines.append(f"Tasks reviewed: {len(tasks)}")
    for task in tasks:
        criterion, _ = criteria[task]
        failed = verdict == "blocked" and task == tasks[0]
        lines += ["", f"## {task} — Demo task {task}: " + ("fail" if failed else "pass"), ""]
        lines.append(f"- ❌ {criterion} — found: wrong output, src/app.py:1\\n  fix: print hello"
                     if failed else f"- ✅ {criterion} — recorded Verify pass")
    lines += ["", "## Intent coverage", ""]
    for task in tasks:
        criterion, sc = criteria[task]
        failed = verdict == "blocked" and task == tasks[0]
        lines += [f"### {sc} — {criterion}: " + ("fail" if failed else "pass"),
                  ("- ❌ " if failed else "- ✅ ") + criterion + (" — found: wrong output, src/app.py:1\\n  fix: print hello" if failed else " — recorded Verify")]
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("\\n".join(lines) + "\\n")
    print(f"RESULT: {name} {verdict}")
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
        (root / "fake_reviewer.py").write_text(FAKE_REVIEWER)
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

    def review(self, root: Path, *extra: str, verdict: str = "pass", wave: int = 1, cycle: int = 1) -> dict:
        env = dict(os.environ, FAKE_REVIEW=verdict)
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "review", "--wave", str(wave), "--cycle", str(cycle),
             "--child-command", f"{sys.executable} {root / 'fake_reviewer.py'}",
             "--role-brief", str(PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md"),
             "--template", str(PROJECT_ROOT / "skills/gsd-path-build/templates/wave-review.md"),
             *extra, "--repo", str(root)], capture_output=True, text=True, env=env)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def subjects(self, root: Path) -> list:
        return run_git(root, "log", "--format=%s").stdout.strip().splitlines()

    def branches(self, root: Path) -> list:
        return run_git(root, "for-each-ref", "--format=%(refname:short)", "refs/heads/").stdout.split()

    def test_mutating_commands_refuse_a_held_repository_lock(self) -> None:
        root = self.root
        head = self.fixture(root)
        with dispatch_driver.acquire_lock(root):
            receipts = [self.round(root),
                        self.driver(root, "finish", "--task-id", "T001"),
                        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")]
            for receipt in receipts:
                self.assertEqual(receipt["status"], "blocked", receipt)
                self.assertEqual(receipt["reason"],
                                 "another dispatch_driver invocation holds the lock")
            self.assertEqual(self.driver(root, "status")["dispatches"], [])
            self.assertEqual(self.head(root), head)
            self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)

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
        record = root / ".git/gsd-path/dispatch/gsd-path-M001/T001/attempt-1/state.json"
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
        attempt = root / ".git/gsd-path/dispatch/gsd-path-M001/T001/attempt-1"
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
        self.fixture(root, deps_t002="[T001]")
        (root / ".gitignore").write_text("*.env\n")
        (root / "config.env").write_text("GREETING=hello\n")
        run_git(root, "add", ".gitignore")
        run_git(root, "add", "-f", "config.env")
        run_git(root, "commit", "-m", "track ignored configuration")
        head = self.head(root)
        subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "scripts/workflow_run.py"),
                        "prepare-task", "--repo", str(root), "--expected-head", head,
                        "--task-id", "T001", "--round-size", "1"], check=True, capture_output=True)
        subprocess.run([sys.executable, "-B", str(PROJECT_ROOT / "scripts/isolation.py"),
                        "activate-task", "--repo", str(root), "--base", head, "--task-id", "T001",
                        "--agent", "build_t001", "--task-file", ".project/tasks/T001-demo.md"],
                       check=True, capture_output=True)
        (root / "src").mkdir()
        (root / "src/app.py").write_text("print('hello')\n")
        expected_paths = run_git(root, "ls-files").stdout.splitlines() + ["src/app.py"]
        expected = {path: (root / path).read_bytes() for path in expected_paths}
        verify = dispatch_driver.run_verify

        def check_sidecar(command: str, sidecar: Path) -> dict:
            self.assertNotEqual(sidecar, root)
            paths = run_git(sidecar, "ls-files").stdout.splitlines()
            self.assertEqual({path: (sidecar / path).read_bytes() for path in paths}, expected)
            return verify(command, sidecar)

        output = io.StringIO()
        with mock.patch.object(dispatch_driver, "run_verify", side_effect=check_sidecar), redirect_stdout(output):
            code = dispatch_driver.main(["finish", "--repo", str(root), "--task-id", "T001"])
        self.assertEqual(code, 0, output.getvalue())
        receipt = json.loads(output.getvalue())
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

    def test_finish_recovers_a_retired_parallel_landing_without_repeating_verify(self) -> None:
        root = self.root
        self.fixture(root)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        landing = next(item for item in receipt["landed"] if item["task"] == "T001")
        self.assertEqual(landing["mode"], "parallel")
        record = root / ".git/gsd-path/dispatch/gsd-path-M001/T001/attempt-1/state.json"
        state = json.loads(record.read_text())
        self.assertFalse(Path(state["worktree"]).exists())
        state["outcome"] = None
        record.write_text(json.dumps(state))
        task = root / ".project/tasks/T001-demo.md"
        before = task.read_bytes()
        head = self.head(root)
        receipt = self.driver(root, "finish", "--task-id", "T001")
        self.assertEqual(receipt["status"], "landed", receipt)
        self.assertEqual(receipt["landed"],
                         [{"task": "T001", "commit": landing["commit"], "recovered": True}])
        persisted = json.loads(record.read_text())
        self.assertEqual(persisted["outcome"], "landed")
        self.assertEqual(persisted["commit"], landing["commit"])
        self.assertEqual(task.read_bytes(), before)
        self.assertEqual(self.head(root), head)

    def test_classify_blocks_when_the_isolate_task_file_is_missing(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        current = dispatch_driver.Round(root, argparse.Namespace(project_dir=".project", wave=1))
        state = dispatch_driver.latest_states(current.root)[0]
        task = Path(state["worktree"]) / state["task_file"]
        task.unlink()
        self.assertFalse(current.classify(state))
        self.assertEqual(current.receipt["blocked"][0]["task_id"], "T001")
        self.assertIn(str(task), current.receipt["blocked"][0]["reason"])
        self.assertEqual(dispatch_driver.latest_states(current.root)[0]["outcome"], "blocked")

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
        records = list((root / ".git/gsd-path/dispatch/gsd-path-M001/T001").glob("attempt-*/state.json"))
        state = json.loads(records[0].read_text())
        state["outcome"] = None
        records[0].write_text(json.dumps(state))
        receipt = self.round(root, "--wait", "60", mode="slow")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(json.loads(records[0].read_text())["outcome"], "landed")

    def reset_after_failed_serial_attempt(self, root: Path) -> None:
        """Stand in for the parent's documented retry: discard the rejected patch, task back to pending."""
        run_git(root, "checkout", "--", ".")
        run_git(root, "clean", "-fdq", "--", "src")

    def test_attempt_limit_per_milestone_stops_for_a_person(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        self.assertEqual(self.round(root, "--wait", "60", mode="badverify")["status"], "blocked")
        self.reset_after_failed_serial_attempt(root)
        receipt = self.round(root, "--wait", "60", mode="badverify")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["dispatched"][0]["attempt"], 2)
        self.reset_after_failed_serial_attempt(root)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("reached the attempt limit (2)", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["dispatched"], [])
        receipt = self.round(root, "--wait", "60", "--max-attempts", "3")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001", "T002"])

    def test_child_that_asks_then_crashes_is_a_failure_not_a_question(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", mode="questioncrash")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["questions"], [])
        self.assertIn("child exited 2", receipt["blocked"][0]["reason"])

    def test_budget_ledger_is_per_milestone_and_blocks_admission(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        budget = ("--task-limit", "3", "--session-limit", "3", "--budget-authority", "test policy")
        receipt = self.round(root, "--wait", "60", *budget, mode="claudejson")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("token budget admit", receipt["blocked"][0]["reason"])
        self.assertEqual([item["task"] for item in receipt["landed"]], ["T001"])
        ledger = json.loads((root / ".git/gsd-path/budget/gsd-path-M001.json").read_text())
        self.assertEqual([row["output_tokens"] for row in ledger["observations"].values()], [3])
        # A wider session limit on the same ledger is refused: the policy is fixed per milestone.
        receipt = self.round(root, "--wait", "60", "--task-limit", "3", "--session-limit", "30",
                             "--budget-authority", "test policy", mode="claudejson")
        self.assertIn("token budget configure", receipt["blocked"][0]["reason"])

    def test_budget_rejection_leaves_dependent_pending_without_isolation(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        task_path = root / ".project/tasks/T002-demo.md"
        before = task_path.read_bytes()
        budget = ("--task-limit", "3", "--session-limit", "3", "--budget-authority", "test policy")
        receipt = self.round(root, "--wait", "60", *budget, mode="claudejson")
        for retry in (False, True):
            if retry:
                receipt = self.round(root, "--wait", "60", mode="claudejson")
            self.assertEqual(receipt["status"], "blocked", receipt)
            self.assertIn("token budget admit", receipt["blocked"][0]["reason"])
            fields, _ = dispatch_driver.isolation.task_frontmatter(task_path.read_text())
            self.assertEqual(fields["status"], "pending")
            self.assertEqual(task_path.read_bytes(), before)
            self.assertFalse((dispatch_driver.records_root(root) / "T002").exists())
            self.assertEqual(self.branches(root), ["gsd-path/M001"])
            worktrees = run_git(root, "worktree", "list", "--porcelain").stdout.splitlines()
            self.assertEqual([line for line in worktrees if line.startswith("worktree ")],
                             [f"worktree {root.resolve()}"])

    def test_budget_stops_when_child_output_cannot_prove_usage(self) -> None:
        root = self.root.parent / "plain"
        root.mkdir()
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", "--task-limit", "50", "--session-limit", "50",
                             "--budget-authority", "test policy")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("token budget record", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["landed"], [])
        self.assertEqual(self.driver(root, "status")["dispatches"][0]["outcome"], None)


    def test_answered_question_requires_budget_admission_without_flags(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        budget = ("--task-limit", "3", "--session-limit", "3", "--budget-authority", "test policy")
        receipt = self.round(root, "--wait", "60", *budget, mode="questionjson")
        self.assertEqual(receipt["status"], "question", receipt)
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        receipt = self.round(root, "--wait", "60", mode="claudejson")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("token budget admit", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["dispatched"], [])
        state = dispatch_driver.latest_states(dispatch_driver.records_root(root))[0]
        self.assertEqual(state["attempt"], 1)
        self.assertEqual(state["outcome"], "question")
        self.assertTrue(state["answered"])

    def test_question_redispatch_must_prove_its_own_usage(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        budget = ("--task-limit", "50", "--session-limit", "50", "--budget-authority", "test policy")
        receipt = self.round(root, "--wait", "60", *budget, mode="questionjson")
        self.assertEqual(receipt["status"], "question", receipt)
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        receipt = self.round(root, "--wait", "60", *budget)
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("token budget record", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["landed"], [])
        state = dispatch_driver.latest_states(dispatch_driver.records_root(root))[0]
        self.assertEqual(state["attempt"], 2)
        self.assertFalse(state.get("usage_recorded"))

    def test_finish_records_usage_from_persisted_policy(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        budget = ("--task-limit", "50", "--session-limit", "50", "--budget-authority", "test policy")
        receipt = self.round(root, *budget, mode="claudejson")
        self.assertEqual(receipt["status"], "in-flight", receipt)
        deadline = time.monotonic() + 60
        while not dispatch_driver.latest_states(dispatch_driver.records_root(root))[0].get("finished_at"):
            self.assertLess(time.monotonic(), deadline, "child did not finish")
            time.sleep(0.1)
        receipt = self.driver(root, "finish", "--task-id", "T001")
        self.assertEqual(receipt["status"], "landed", receipt)
        ledger = json.loads(dispatch_driver.budget_ledger(root).read_text())
        self.assertEqual(list(ledger["observations"].values()),
                         [{"task": "T001", "output_tokens": 3}])

    def test_answer_does_not_erase_original_dispatch_from_attempt_limit(self) -> None:
        root = self.root
        self.fixture(root, deps_t002="[T001]")
        receipt = self.round(root, "--wait", "60", mode="question")
        self.assertEqual(receipt["status"], "question", receipt)
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        receipt = self.round(root, "--wait", "60", mode="badverify")
        self.assertEqual(receipt["status"], "blocked", receipt)
        records = dispatch_driver.records_root(root)
        origins = [json.loads(path.read_text())["origin"]
                   for path in sorted((records / "T001").glob("attempt-*/state.json"))]
        self.assertEqual(origins, ["dispatch", "question"])
        self.assertEqual(dispatch_driver.attempts_used(records, "T001"), 1)
        self.reset_after_failed_serial_attempt(root)
        receipt = self.round(root, "--wait", "60", mode="badverify")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["dispatched"][0]["attempt"], 3)
        self.reset_after_failed_serial_attempt(root)
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("reached the attempt limit (2)", receipt["blocked"][0]["reason"])
        self.assertEqual(receipt["dispatched"], [])

    def test_build_evidence_receipt_lands_at_its_canonical_path(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        head = self.head(root)
        completed = subprocess.run(
            [sys.executable, "-B", str(PROJECT_ROOT / "scripts/workflow_run.py"), "build-evidence",
             "--repo", str(root), "--expected-head", head], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        receipt = json.loads(completed.stdout)
        evidence = root / ".project/build/evidence.json"
        self.assertEqual(Path(receipt["steps"][-1]["evidence"]).resolve(), evidence.resolve())
        proof = json.loads(evidence.read_text())
        self.assertEqual(proof, receipt["steps"][0]["result"])
        self.assertEqual(sorted(entry["task"]["id"] for entry in proof["tasks"]), ["T001", "T002"])

    def test_review_full_collects_validates_and_checkpoints_a_pass(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        head = self.head(root)
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertEqual(receipt["depth"], "full")
        self.assertEqual(receipt["base"], head)
        self.assertEqual(receipt["lenses"]["canonical"]["verdict"], "pass")
        self.assertFalse(receipt["panel_required"])
        review = root / ".project/review/wave-1.cycle1.md"
        self.assertIn("Wave verdict: pass", review.read_text())
        self.assertEqual(self.subjects(root)[0], "build: record wave 1 cycle 1 review")
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        self.assertEqual(self.branches(root), ["gsd-path/M001"])
        again = self.review(root, "--wait", "60")
        self.assertEqual(again["status"], "pass", again)
        self.assertIsNone(again["checkpoint"])

    def test_review_blocked_groups_findings_and_leaves_the_file_for_the_fix_checkpoint(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        head = self.head(root)
        receipt = self.review(root, "--wait", "60", verdict="blocked")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["lenses"]["canonical"]["verdict"], "blocked")
        findings = receipt["findings"]
        self.assertEqual(findings.get("status", "ok"), "ok", findings)
        self.assertTrue(findings["fix_batches"], findings)
        self.assertEqual(self.head(root), head)
        self.assertIn(".project/review/wave-1.cycle1.md", run_git(root, "status", "--porcelain", "-uall").stdout)
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_review_deep_runs_both_lenses(self) -> None:
        root = self.root
        self.fixture(root)
        plan = root / ".project/plan/PLAN.md"
        plan.write_text(plan.read_text().replace("Review depth: full", "Review depth: deep", 1))
        run_git(root, "commit", "-qam", "plan: deep review")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertEqual(sorted(receipt["lenses"]), ["adversarial", "contract"])
        for lens in ("contract", "adversarial"):
            self.assertIn(f"Lens: {lens}", (root / f".project/review/wave-1.cycle1.{lens}.md").read_text())
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_review_resumes_only_missing_deep_lens(self) -> None:
        root = self.root
        self.fixture(root)
        plan = root / ".project/plan/PLAN.md"
        plan.write_text(plan.read_text().replace("Review depth: full", "Review depth: deep", 1))
        run_git(root, "commit", "-qam", "plan: deep review")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        options = argparse.Namespace(project_dir=".project", wave=1, cycle=1, wait=None,
                                     repair_evidence=None,
                                     role_brief=PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md",
                                     template=PROJECT_ROOT / "skills/gsd-path-build/templates/wave-review.md",
                                     child_command=f"{sys.executable} {root / 'fake_reviewer.py'}",
                                     child_timeout=None)
        review = dispatch_driver.Review(root, options)
        with mock.patch.object(review, "settle"):
            self.assertEqual(review.run()["status"], "in-flight")
        states = review.current_states(["contract", "adversarial"])
        for state in states.values():
            while not Path(state["_path"]).with_name("exit.json").is_file():
                time.sleep(dispatch_driver.POLL_SECONDS)
        adversarial = states["adversarial"]
        sidecar = Path(adversarial["worktree"])
        dispatch_driver.isolation.clean_verify(root, sidecar, adversarial["base"], adversarial["branch"])
        dispatch_driver.isolation.retire(root, sidecar, adversarial["branch"], False)
        shutil.rmtree(Path(adversarial["_path"]).parent.parent)
        contract_path = Path(states["contract"]["_path"])
        contract_pid = states["contract"]["pid"]
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertEqual(sorted(receipt["lenses"]), ["adversarial", "contract"])
        self.assertEqual(json.loads(contract_path.read_text())["pid"], contract_pid)
        self.assertEqual(len(list(contract_path.parent.parent.glob("attempt-*"))), 1)
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_review_recovers_validated_collection_after_interruption(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        states = dispatch_driver.latest_states(dispatch_driver.records_root(root) / "reviews")
        state = states[0]
        dispatch_driver.update_state(state, outcome=None, cleanup_complete=False)
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertFalse(receipt["blocked"])
        self.assertIsNone(receipt["checkpoint"])
        canonical = root / state["relative"]
        canonical.write_text(canonical.read_text() + "changed after validation\n")
        dispatch_driver.update_state(state, outcome=None, cleanup_complete=False)
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"], "reviewer wrote no review file")

    def test_review_rejects_changed_or_missing_collected_artifact(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        head = self.head(root)
        canonical = root / ".project/review/wave-1.cycle1.md"
        for mutation in ("edit", "delete"):
            with self.subTest(mutation=mutation):
                if mutation == "edit":
                    canonical.write_text(canonical.read_text() + "Changed after collection.\n")
                else:
                    canonical.unlink()
                receipt = self.review(root, "--wait", "60")
                self.assertEqual(receipt["status"], "blocked", receipt)
                self.assertEqual(receipt["blocked"][0]["reason"],
                                 "canonical review artifact changed after collection")
                self.assertEqual(receipt["blocked"][0]["helper"], "isolation.py collect-artifact")
                self.assertTrue(any(item["kind"] == "helper-failure"
                                    for item in receipt["findings"]["structural_blockers"]))
                self.assertFalse(receipt.get("checkpoint"))
                self.assertEqual(self.head(root), head)

    def test_review_cleanup_failures_report_findings_and_resume(self) -> None:
        for helper in ("clean_verify", "retire"):
            with self.subTest(helper=helper):
                root = (self.root / helper).resolve()
                root.mkdir()
                self.fixture(root)
                plan = root / ".project/plan/PLAN.md"
                plan.write_text(plan.read_text().replace("Review depth: full", "Review depth: deep", 1))
                run_git(root, "commit", "-qam", "plan: deep review")
                self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
                head = self.head(root)
                options = argparse.Namespace(project_dir=".project", wave=1, cycle=1, wait=60,
                                             repair_evidence=None,
                                             role_brief=PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md",
                                             template=PROJECT_ROOT / "skills/gsd-path-build/templates/wave-review.md",
                                             child_command=f"{sys.executable} {root / 'fake_reviewer.py'}",
                                             child_timeout=None)
                with mock.patch.object(dispatch_driver.isolation, helper,
                                       side_effect=dispatch_driver.isolation.IsolationError("cleanup failed")):
                    receipt = dispatch_driver.Review(root, options).run()
                self.assertEqual(receipt["status"], "blocked", receipt)
                self.assertEqual(sorted(receipt["lenses"]), ["adversarial", "contract"])
                self.assertEqual(len(receipt["blocked"]), 2)
                self.assertTrue(all(item["helper"] == "isolation.py retire" for item in receipt["blocked"]))
                self.assertTrue(any(item["kind"] == "helper-failure" and
                                    item["detail"] == "isolation.py retire: cleanup failed"
                                    for item in receipt["findings"]["structural_blockers"]))
                self.assertEqual(self.head(root), head)
                records = dispatch_driver.records_root(root) / "reviews"
                for state in dispatch_driver.latest_states(records):
                    self.assertEqual(state["outcome"], "collected")
                    self.assertTrue(state["cleanup_pending"])
                    self.assertEqual(state["cleanup_error"], "cleanup failed")
                    self.assertTrue(Path(state["worktree"]).is_dir())
                receipt = self.review(root, "--wait", "60")
                self.assertEqual(receipt["status"], "pass", receipt)
                self.assertFalse(receipt["blocked"])
                for state in dispatch_driver.latest_states(records):
                    self.assertTrue(state["cleanup_complete"])
                    self.assertFalse(state["cleanup_pending"])
                    self.assertIsNone(state["cleanup_error"])
                    self.assertFalse(Path(state["worktree"]).exists())
                self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_review_requires_previous_cycle_evidence(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.review(root, "--wait", "60", cycle=2)
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"],
                         f"previous cycle review is missing: {root.resolve() / '.project/review/wave-1.cycle1.md'}")
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_review_refuses_verify_only_and_unlanded_waves(self) -> None:
        root = self.root
        self.fixture(root, wave_t002=2)
        plan = root / ".project/plan/PLAN.md"
        text = plan.read_text()
        head_block = text.index("## Wave 2")
        plan.write_text(text[:head_block] + text[head_block:].replace("Review depth: full", "Review depth: verify-only", 1))
        run_git(root, "commit", "-qam", "plan: verify-only wave 2")
        receipt = self.review(root, wave=2)
        self.assertEqual(receipt["status"], "not-applicable")
        self.assertIn("verify-only", receipt["reason"])
        receipt = self.review(root, wave=1)
        self.assertEqual(receipt["status"], "blocked")
        self.assertIn("no proven landing", receipt["blocked"][0]["reason"])

    def test_review_without_wait_returns_in_flight_then_settles(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.review(root)
        self.assertIn(receipt["status"], ("in-flight", "pass"), receipt)
        if receipt["status"] == "in-flight":
            self.assertEqual([item["task_id"] for item in receipt["in_flight"]], ["review_wave_1_cycle_1"])
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)

    def test_review_invalid_artifact_blocks_before_collection_and_keeps_the_sidecar(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.review(root, "--wait", "60", verdict="garbage")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["helper"], "check_handoffs.py wave")
        self.assertFalse((root / ".project/review/wave-1.cycle1.md").exists())
        self.assertIn("gsd-path-verify/wave-1-cycle-1", self.branches(root))
        self.assertTrue(receipt["findings"]["structural_blockers"], receipt["findings"])


if __name__ == "__main__":
    unittest.main()
