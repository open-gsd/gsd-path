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

from scripts import dispatch_driver, pipeline_state
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

# A stand-in skeptic: restates the briefed observations and records one verdict for all of them.
FAKE_SKEPTIC = textwrap.dedent(
    """
    import os, re, sys
    from pathlib import Path
    brief = sys.stdin.read()
    staged = Path(re.search(r"^Write exactly this output file: (.+)$", brief, re.M).group(1))
    locator = re.search(r"^Criterion locator: (\\S+)$", brief, re.M).group(1)
    observations = re.findall(r"^- \\[(\\w+)\\] (.+)$", brief, re.M)
    verdict = os.environ.get("FAKE_SKEPTIC", "stands")
    lines = [f"- Criterion locator: {locator}", "", "## Observations", ""]
    for n, (lens, text) in enumerate(observations, 1):
        lines += [f"### Observation {n} — {lens}", "", text, ""]
    lines += ["## Observation verdicts", ""]
    for n in range(1, len(observations) + 1):
        lines += [f"### Observation {n}: {verdict}", "", "checked", ""]
    lines += ["## Verdict", "", verdict, "", "## Evidence", "", "Re-ran Verify in the sidecar.", ""]
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text("\\n".join(lines))
    print(f"Verdict: {verdict}")
    """
)

# A stand-in panelist: writes a wave-panel file with no findings.
FAKE_PANELIST = textwrap.dedent(
    """
    import re, sys
    from pathlib import Path
    brief = sys.stdin.read()
    staged = Path(re.search(r"^Write exactly this output file: (.+)$", brief, re.M).group(1))
    family = re.search(r"Family: (\\w+)\\.", brief).group(1)
    model = re.search(r"Model: (\\S+)\\.", brief).group(1)
    depth = re.search(r"Depth for this brief: (\\w+)\\.", brief).group(1)
    wave, cycle = re.search(r"wave (\\d+), cycle (\\d+)", brief).groups()
    staged.parent.mkdir(parents=True, exist_ok=True)
    staged.write_text(f"# Panel — wave {wave}, cycle {cycle}\\n\\n- Family: {family}\\n- Model: {model}\\n"
                      f"- Depth: {depth}\\n\\n## Findings\\n\\n- none\\n\\n## Summary\\n\\nNo findings.\\n")
    print("0 findings")
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

    def fixture(self, root: Path, deps_t002: str = "[]", wave_t002: int = 1,
                state: tuple = ("build", "active")) -> str:
        run_git(root, "init", "-b", "gsd-path/M001")
        # Finish automatic housekeeping before TemporaryDirectory removes Git objects.
        run_git(root, "config", "gc.autoDetach", "false")
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
        handoffs.write_state(root, *state)
        (root / "fake_coder.py").write_text(FAKE_CODER)
        (root / "fake_reviewer.py").write_text(FAKE_REVIEWER)
        (root / "fake_panelist.py").write_text(FAKE_PANELIST)
        (root / "fake_skeptic.py").write_text(FAKE_SKEPTIC)
        run_git(root, "add", ".")
        run_git(root, "commit", "-m", "fixture")
        return self.head(root)

    def driver(self, root: Path, *args: str, mode: str = "ready", **fake: str) -> dict:
        env = dict(os.environ, FAKE_MODE=mode, **fake)
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

    def panel(self, root: Path, *extra: str, advertised: str = "gpt-6-astra,claude-opus") -> dict:
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "panel", "--wave", "1", "--cycle", "1",
             "--child-command", f"{sys.executable} {root / 'fake_panelist.py'} {{model}}",
             "--advertised", advertised, "--parent-slug", "claude-opus",
             "--role-brief", str(PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md"),
             "--template", str(PROJECT_ROOT / "skills/gsd-path-build/templates/wave-panel.md"),
             *extra, "--repo", str(root)], capture_output=True, text=True)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def skeptics(self, root: Path, *extra: str, verdict: str = "stands") -> dict:
        return self.driver(
            root, "skeptics", "--wave", "1", "--cycle", "1",
            "--child-command", f"{sys.executable} {root / 'fake_skeptic.py'}",
            "--role-brief", str(PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md"),
            "--template", str(PROJECT_ROOT / "skills/gsd-path-build/templates/skeptic.md"),
            *extra, FAKE_SKEPTIC=verdict)

    def set_deep_review_with_skeptics(self, root: Path) -> None:
        plan = root / ".project/plan/PLAN.md"
        text = plan.read_text().replace("Review depth: full", "Review depth: deep", 1)
        plan.write_text(text.replace("- review_panel: off", "- review_panel: off\n- finding_skeptics: on", 1))
        run_git(root, "commit", "-qam", "plan: deep review with skeptics")

    def set_panel(self, root: Path, value: str) -> None:
        plan = root / ".project/plan/PLAN.md"
        plan.write_text(plan.read_text().replace("- review_panel: off", f"- review_panel: {value}", 1))
        run_git(root, "commit", "-qam", f"plan: review panel {value}")

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
        task = root / ".project/tasks/T001-demo.md"
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        record = root / ".git/gsd-path/dispatch/gsd-path-M001/T001/attempt-1/state.json"
        state = json.loads(record.read_text())
        state["outcome"] = "redispatched"
        record.write_text(json.dumps(state))
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
        task = root / ".project/tasks/T001-demo.md"
        self.assertEqual(self.round(root, "--wait", "60", mode="question")["status"], "question")
        self.driver(root, "answer", "--task-id", "T001", "--answer", "hello")
        # The fake coder asks again only while no answer is recorded, so pre-seed a second question.
        receipt = self.round(root, "--wait", "60", mode="question2")
        self.assertEqual(receipt["status"], "question", receipt)
        self.assertIn("which file?", receipt["questions"][0]["question"])
        self.assertEqual(self.driver(root, "status")["dispatches"][0]["attempt"], 2)
        self.assertIn("Orchestrator answer: hello", task.read_text())

    def test_finish_recovers_a_retired_parallel_landing_without_repeating_verify(self) -> None:
        root = self.root
        self.fixture(root)
        task = root / ".project/tasks/T001-demo.md"
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        landing = next(item for item in receipt["landed"] if item["task"] == "T001")
        self.assertEqual(landing["mode"], "parallel")
        record = root / ".git/gsd-path/dispatch/gsd-path-M001/T001/attempt-1/state.json"
        state = json.loads(record.read_text())
        self.assertFalse(Path(state["worktree"]).exists())
        state["outcome"] = None
        record.write_text(json.dumps(state))
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

    def test_review_rejects_changed_inputs_after_pass(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        intent = root / ".project/intent/INTENT.md"
        intent.write_text(intent.read_text() + "Additional acceptance criterion.\n")
        for committed in (False, True):
            with self.subTest(committed=committed):
                if committed:
                    run_git(root, "commit", "-qam", "intent: add criterion")
                head = self.head(root)
                receipt = self.review(root, "--wait", "60")
                self.assertEqual(receipt["status"], "blocked", receipt)
                self.assertEqual(receipt["blocked"][0]["reason"],
                                 "inputs changed after the review base; run a new cycle")
                self.assertEqual(receipt["blocked"][0]["helper"], "dispatch_driver.py review")
                self.assertTrue(any(item["kind"] == "helper-failure" for
                                    item in receipt["findings"]["structural_blockers"]))
                self.assertFalse(receipt.get("checkpoint"))
                self.assertEqual(self.head(root), head)

    def test_review_rechecks_inputs_before_checkpoint(self) -> None:
        root = self.root.resolve()
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        head = self.head(root)
        options = argparse.Namespace(project_dir=".project", wave=1, cycle=1, wait=None)
        review = dispatch_driver.Review(root, options)
        conclude = review.conclude

        def change_inputs_and_conclude():
            intent = root / ".project/intent/INTENT.md"
            intent.write_text(intent.read_text() + "Additional acceptance criterion.\n")
            conclude()

        with mock.patch.object(review, "conclude", side_effect=change_inputs_and_conclude):
            receipt = review.run()
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["reason"], "inputs changed after the review base; run a new cycle")
        self.assertTrue(any(item["kind"] == "helper-failure" for
                            item in receipt["findings"]["structural_blockers"]))
        self.assertEqual(self.head(root), head)

    def test_review_rejects_unrelated_commit_after_pass(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        run_git(root, "commit", "--allow-empty", "-m", "unrelated checkpoint")
        head = self.head(root)
        receipt = self.review(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"],
                         "inputs changed after the review base; run a new cycle")
        self.assertEqual(self.head(root), head)

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

    def test_advance_rereads_a_result_recorded_after_the_child_died(self) -> None:
        path = self.root / "state.json"
        state = {"task_id": "x", "pid": 999999, "finished_at": None, "outcome": None, "_path": str(path)}
        dispatch_driver.save_state(path, {"task_id": "x", "pid": 999999})
        dispatch_driver.save_state(path.with_name("exit.json"), {"finished_at": "now", "exit_code": 0})
        collected = []
        with mock.patch.object(dispatch_driver, "process_alive", return_value=True):
            self.assertFalse(dispatch_driver.advance(state, collected.append))
        with mock.patch.object(dispatch_driver, "process_alive", return_value=False):
            self.assertTrue(dispatch_driver.advance(state, collected.append))
        self.assertEqual(collected, [state])
        self.assertEqual(state["exit_code"], 0)

    def test_advance_blocks_an_orphaned_child(self) -> None:
        path = self.root / "state.json"
        state = {"task_id": "x", "pid": 999999, "finished_at": None, "outcome": None, "_path": str(path)}
        dispatch_driver.save_state(path, {"task_id": "x", "pid": 999999})
        with mock.patch.object(dispatch_driver, "process_alive", return_value=False):
            self.assertTrue(dispatch_driver.advance(state, self.fail))
        self.assertEqual(state["outcome"], "blocked")
        self.assertEqual(dispatch_driver.load_state(path)["reason"], dispatch_driver.ORPHANED)

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

    def test_fix_tasks_writes_one_task_per_batch_and_the_next_round_lands_it(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60", verdict="blocked")["status"], "blocked")
        receipt = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
        self.assertEqual(receipt["status"], "created", receipt)
        self.assertEqual([item["task"] for item in receipt["created"]], ["T003"])
        self.assertEqual(receipt["created"][0]["deps"], ["T001"])
        self.assertEqual(receipt["created"][0]["files"], ["src/app.py"])
        text = (root / receipt["created"][0]["path"]).read_text()
        self.assertIn("Criterion: The demo command prints hello.", text)
        self.assertIn("— found: wrong output, src/app.py:1", text)
        self.assertEqual(text.count("1. The demo command prints hello."), 1)
        self.assertNotIn("2. The demo command prints hello.", text)
        self.assertEqual(dispatch_driver._common.task_verify_command(text), "set -e\n(\npython3 src/app.py\n)")
        self.assertEqual(receipt["plan_wave"], 2)
        self.assertIn("## Wave 2 — fix wave 1 cycle 1 review findings", (root / ".project/plan/PLAN.md").read_text())
        self.assertEqual(self.subjects(root)[0], "build: record wave 1 cycle 1 review and fix tasks")
        head = self.head(root)
        plan = (root / ".project/plan/PLAN.md").read_bytes()
        repeated = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
        self.assertEqual(repeated["status"], "exists", repeated)
        self.assertEqual(repeated["existing"][0]["task"], "T003")
        self.assertEqual(repeated["existing"][0]["locators"], receipt["created"][0]["locators"])
        self.assertEqual(self.head(root), head)
        self.assertEqual((root / ".project/plan/PLAN.md").read_bytes(), plan)
        plan_path = root / ".project/plan/PLAN.md"
        original = plan.decode()
        start = original.index("## Wave 2")
        end = original.index("## Intent coverage", start)
        for damaged in (original[:start] + original[end:],
                        "\n".join(line for line in original.split("\n") if not line.startswith("| T003 |"))):
            plan_path.write_text(damaged)
            repair = root / receipt["created"][0]["path"]
            repair.write_text(repair.read_text() + "- 2026-09-07 — repair inventory interrupted\n")
            repaired = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
            self.assertEqual(repaired["status"], "created", repaired)
            self.assertEqual(repaired["created"], [])
            self.assertEqual([item["task"] for item in repaired["existing"]], ["T003"])
            self.assertEqual(plan_path.read_text(), original)
            self.assertEqual([step["exit_code"] for step in repaired["steps"]
                              if step["script"] == "check_task_briefs.py"], [0])
            self.assertIsNotNone(repaired["checkpoint"])
            self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")  # wave 1 has nothing left
        again = self.round(root, "--wait", "60", wave=2)
        self.assertEqual(again["status"], "done", again)
        self.assertEqual([item["task"] for item in again["landed"]], ["T003"])
        self.assertIn("status: done", (root / receipt["created"][0]["path"]).read_text())

    def test_fix_tasks_resumes_after_only_first_batch_was_written(self) -> None:
        root = self.root
        self.fixture(root)
        reviewer = root / "fake_reviewer.py"
        reviewer.write_text(reviewer.read_text().replace(' and task == tasks[0]', ''))
        run_git(root, "commit", "-qam", "fixture: block both tasks")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60", verdict="blocked")["status"], "blocked")
        write = dispatch_driver._common.atomic_write

        def interrupt(path, text):
            if path.name == "T004-fix-wave-1-cycle-1.md":
                raise dispatch_driver.DriverStop("interrupted second batch")
            return write(path, text)

        options = argparse.Namespace(project_dir=".project", wave=1, cycle=1)
        with mock.patch.object(dispatch_driver._common, "atomic_write", side_effect=interrupt):
            stopped = dispatch_driver.fix_tasks(root, options)
        self.assertEqual(stopped["status"], "blocked", stopped)
        first = root / ".project/tasks/T003-fix-wave-1-cycle-1.md"
        first_bytes = first.read_bytes()
        receipt = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
        self.assertEqual(receipt["status"], "created", receipt)
        self.assertEqual([item["task"] for item in receipt["created"]], ["T004"])
        self.assertEqual([item["task"] for item in receipt["existing"]], ["T003"])
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertIsNotNone(receipt["checkpoint"])
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        self.assertEqual(self.round(root, "--wait", "60", wave=2)["status"], "done")

    def test_child_collection_recovers_after_source_removal(self) -> None:
        self.fixture(self.root)
        base = self.head(self.root)
        sidecar = dispatch_driver.isolation.isolate_verify(self.root, base, "collection-recovery")
        relative = ".project/review/wave-1.cycle1.skeptic-t001_ac1.md"
        staged = Path(sidecar["worktree"]) / relative
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_text("validated skeptic output")
        record = self.root / ".project/collection-state.json"
        state = {**sidecar, "relative": relative, "exit_code": 0, "_path": str(record)}
        dispatch_driver.save_state(record, state)
        receipt = {"steps": []}
        collect = dispatch_driver.isolation.collect_artifact

        def interrupted(*args):
            collect(*args)
            raise RuntimeError("interrupted after collection")

        with mock.patch.object(dispatch_driver.isolation, "collect_artifact", side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, "interrupted after collection"):
                dispatch_driver.collect_file(self.root, receipt, state, lambda path: {"verdict": "refuted"})
        self.assertFalse(staged.exists())
        state = dispatch_driver.load_state(record)
        dispatch_driver.collect_file(self.root, receipt, state,
                                     lambda path: self.fail("resume must use persisted validation"))
        self.assertEqual(state["outcome"], "collected")
        self.assertEqual(state["verdict"], "refuted")
        self.assertEqual((self.root / relative).read_text(), "validated skeptic output")
        self.assertFalse(Path(sidecar["worktree"]).exists())
        self.assertEqual(receipt["steps"][0]["script"], "isolation.py collect-artifact")

    def test_skeptics_run_once_per_locator_and_fix_tasks_batches_what_stands(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_deep_review_with_skeptics(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        review = self.review(root, "--wait", "60", verdict="blocked")
        self.assertEqual(review["status"], "blocked", review)
        locators = review["findings"]["skeptic_groups"]
        self.assertTrue(locators, review["findings"])
        self.assertEqual(self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")["escalation"],
                         ["skeptic_groups"])
        receipt = self.skeptics(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual({key: item["verdict"] for key, item in receipt["skeptics"].items()},
                         {locator: "stands" for locator in locators})
        for locator in locators:
            text = (root / f".project/review/wave-1.cycle1.skeptic-{locator}.md").read_text()
            self.assertIn(f"- Criterion locator: {locator}", text)
        self.assertEqual(receipt["findings"]["skeptic_groups"], [])
        self.assertEqual(sorted(receipt["findings"]["fix_groups"]), sorted(locators))
        self.assertEqual(self.branches(root), ["gsd-path/M001"])
        again = self.skeptics(root, "--wait", "60")
        self.assertEqual(again["status"], "done", again)
        self.assertFalse([step for step in again["steps"] if step["script"] == "isolation.py isolate-verify"])
        fixes = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
        self.assertEqual(fixes["status"], "created", fixes)
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")

    def test_skeptics_that_refute_everything_leave_the_ruling_to_the_user(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_deep_review_with_skeptics(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60", verdict="blocked")["status"], "blocked")
        receipt = self.skeptics(root, "--wait", "60", verdict="refuted")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertTrue(receipt["findings"]["all_refuted"], receipt["findings"])
        self.assertEqual(self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")["escalation"],
                         ["all_refuted"])

    def test_skeptics_report_none_for_a_passing_cycle_and_escalate_structural_blockers(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_deep_review_with_skeptics(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.skeptics(root, "--wait", "60")
        self.assertEqual(receipt["status"], "escalate", receipt)
        self.assertEqual(receipt["escalation"], ["structural_blockers"])
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        self.assertEqual(self.skeptics(root, "--wait", "60")["status"], "none")

    def state(self, root: Path) -> str:
        state, _, _ = pipeline_state.load_state(root)
        return f"{state.phase}/{state.status}"

    def test_round_enters_build_from_plan_done_and_checkpoints_the_transition(self) -> None:
        root = self.root
        self.fixture(root, state=("plan", "done"))
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(self.state(root), "build/active")
        self.assertIn("build: start milestone", self.subjects(root))
        self.assertIn("build started", (root / ".project/STATE.md").read_text())

    def test_round_records_build_blocked_when_recovery_blocks(self) -> None:
        root = self.root
        head = self.fixture(root)
        task = next((root / ".project/tasks").glob("T001*.md"))  # done by hand, no landing commit
        task.write_text(task.read_text().replace("status: pending", "status: done", 1)
                        .replace("agent: null", "agent: fake", 1).replace("base: null", f"base: {head}", 1))
        run_git(root, "commit", "-qam", "task: T001 marked done outside land")
        receipt = self.round(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"], "recovery blocked")
        self.assertEqual(self.state(root), "build/blocked")
        self.assertEqual(self.subjects(root)[0], "build: record blocked recovery")
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        again = self.round(root, "--wait", "60")  # recovery re-enters build/active, then blocks again
        self.assertEqual(again["status"], "blocked", again)
        self.assertEqual(self.state(root), "build/blocked")
        self.assertEqual(self.subjects(root)[:3], ["build: record blocked recovery", "build: start milestone",
                                                   "build: record blocked recovery"])

    def test_complete_proves_every_wave_then_enters_ship(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        early = self.driver(root, "complete")
        self.assertEqual(early["status"], "blocked", early)
        self.assertEqual(early["blocked"][0]["reason"], "review cycle waves do not match PLAN.md")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        receipt = self.driver(root, "complete")
        self.assertEqual(receipt["status"], "done", receipt)
        self.assertEqual(receipt["review_cycles"], [1])
        self.assertEqual(self.state(root), "ship/active")
        self.assertEqual(self.subjects(root)[0], "build: complete milestone")
        self.assertTrue((root / ".project/build/evidence.json").is_file())
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")

    def test_fix_tasks_escalates_structural_blockers(self) -> None:
        root = self.root
        self.fixture(root)
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        receipt = self.driver(root, "fix-tasks", "--wave", "1", "--cycle", "1")
        self.assertEqual(receipt["status"], "escalate", receipt)
        self.assertEqual(receipt["escalation"], ["structural_blockers"])

    def panel_options(self) -> argparse.Namespace:
        return argparse.Namespace(project_dir=".project", wave=1, cycle=1, wait=60,
                                  advertised="gpt-6-astra,claude-opus", parent_slug="gemini-pro",
                                  child_command=f"{sys.executable} {self.root / 'fake_panelist.py'} {{model}}",
                                  role_brief=PROJECT_ROOT / "skills/gsd-path-build/references/reviewer.md",
                                  template=PROJECT_ROOT / "skills/gsd-path-build/templates/wave-panel.md",
                                  child_timeout=None)

    def test_panel_resumes_missing_family_and_pending_cleanup(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "gpt,claude")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        options = self.panel_options()
        with mock.patch.object(dispatch_driver.isolation, "retire",
                               side_effect=dispatch_driver.isolation.IsolationError("cleanup failed")):
            panel = dispatch_driver.Panel(root, options)
            receipt = panel.run()
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual({item["helper"] for item in receipt["blocked"]}, {"isolation.py retire"})
        self.assertNotIn("merge", receipt)
        roster = dispatch_driver.load_state(panel.root / "wave-1-cycle-1/roster.json")
        self.assertEqual(set(roster["families"]), {"gpt", "claude"})
        state = panel.states()["gpt"]
        dispatch_driver.isolation.retire(root, Path(state["worktree"]), state["branch"], False)
        shutil.rmtree(panel.root / state["task_id"])
        (root / state["relative"]).unlink()
        receipt = self.panel(root, "--wait", "60", advertised="claude-opus")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertEqual(set(receipt["families"]), {"gpt", "claude"})
        self.assertFalse(any(item.get("cleanup_pending") for item in panel.states().values()))
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_blocked_review_panel_does_not_checkpoint(self) -> None:
        for mode, advertised in (("gpt", "gpt-6-astra,claude-opus"), ("detected", "claude-opus")):
            with self.subTest(mode=mode):
                root = self.root / mode
                root.mkdir()
                self.fixture(root)
                self.set_panel(root, mode)
                self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
                self.assertEqual(self.review(root, "--wait", "60", verdict="blocked")["status"], "blocked")
                head = self.head(root)
                receipt = self.panel(root, "--wait", "60", advertised=advertised)
                self.assertEqual(receipt["review_verdict"], "blocked", receipt)
                self.assertIsNone(receipt["checkpoint"])
                self.assertEqual(self.head(root), head)

    def test_fix_tasks_preserves_verify_lines_and_skips_carried_batches(self) -> None:
        root = self.root
        self.fixture(root)
        task = next((root / ".project/tasks").glob("T001-*.md"))
        task.write_text(task.read_text().replace("python3 src/app.py", "python3 src/app.py # check A"))
        run_git(root, "commit", "-qam", "fixture: trailing verify comment")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60", verdict="blocked")["status"], "blocked")
        findings = dispatch_driver.review_findings.compute(root, ".project", 1, 1)
        for group in findings["groups"]:
            group["tasks"] = ["T001", "T002"]
        findings["fix_batches"][0]["files"] = ["src/app.py", "tests/test_app.py"]
        options = argparse.Namespace(project_dir=".project", wave=1, cycle=1)
        with mock.patch.object(dispatch_driver.review_findings, "compute", return_value=findings):
            receipt = dispatch_driver.fix_tasks(root, options)
        self.assertEqual(receipt["status"], "created", receipt)
        command = dispatch_driver._common.task_verify_command((root / receipt["created"][0]["path"]).read_text())
        texts = dispatch_driver.contracts._task_texts(root, ".project")
        self.assertEqual(command.splitlines(), ["set -e", *[line for source in ("T001", "T002") for line in
            ("(", dispatch_driver._common.task_verify_command(texts[source]), ")")]])
        # A source Verify ending in `exit 0` ends only its own subshell; the next one still runs.
        probe = subprocess.run(["bash", "-c", "set -e\n(\ntrue; exit 0\n)\n(\nexit 7\n)"], capture_output=True)
        self.assertEqual(probe.returncode, 7)
        (root / "tests/test_app.py").write_text("raise SystemExit(7)\n")
        result = subprocess.run(["bash", "-c", command], cwd=root, capture_output=True, text=True)
        self.assertEqual(result.returncode, 7, result)
        options.cycle = 2
        plan = (root / ".project/plan/PLAN.md").read_bytes()
        with mock.patch.object(dispatch_driver.review_findings, "compute", return_value=findings):
            carried = dispatch_driver.fix_tasks(root, options)
        self.assertEqual(carried["status"], "none", carried)
        self.assertEqual(carried["carried"], findings["fix_batches"])
        self.assertEqual(carried["created"], [])
        self.assertEqual((root / ".project/plan/PLAN.md").read_bytes(), plan)

    def test_panel_named_family_runs_merges_and_checkpoints_with_the_review(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "gpt")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        review = self.review(root, "--wait", "60")
        self.assertEqual(review["status"], "pass", review)
        self.assertTrue(review["panel_required"])
        self.assertIsNone(review.get("checkpoint"))
        receipt = self.panel(root, "--wait", "60")
        self.assertEqual(receipt["status"], "pass", receipt)
        self.assertEqual(receipt["families"]["gpt"]["slug"], "gpt-6-astra")
        self.assertTrue((root / ".project/review/wave-1.cycle1.panel.gpt.md").is_file())
        self.assertTrue((root / receipt["panel"]).is_file())
        self.assertEqual(self.subjects(root)[0], "build: record wave 1 cycle 1 review")
        self.assertEqual(run_git(root, "status", "--porcelain").stdout, "")
        self.assertEqual(self.branches(root), ["gsd-path/M001"])

    def test_panel_detected_without_cross_model_families_writes_the_skipped_receipt(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "detected")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        receipt = self.panel(root, "--wait", "60", advertised="claude-opus")
        self.assertEqual(receipt["status"], "skipped", receipt)
        skipped = root / ".project/review/wave-1.cycle1.panel.skipped.json"
        self.assertEqual(json.loads(skipped.read_text())["status"], "skipped")
        self.assertEqual(self.subjects(root)[0], "build: record wave 1 cycle 1 review")

    def test_panel_blocks_when_inputs_changed_after_the_review_base(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "gpt")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        head = self.head(root)
        with (root / ".project/intent/INTENT.md").open("a") as handle:
            handle.write("\n7. An unreviewed criterion.\n")
        receipt = self.panel(root, "--wait", "60")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertIn("inputs changed after the review base", receipt["blocked"][0]["reason"])
        self.assertEqual(self.head(root), head)
        self.assertIsNone(receipt.get("checkpoint"))
        self.assertFalse((root / ".project/review/wave-1.cycle1.panel.md").exists())

    def test_panel_skipped_retry_blocks_after_a_post_review_intent_commit(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "detected")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        skipped = root / ".project/review/wave-1.cycle1.panel.skipped.json"
        saved = json.dumps({"status": "skipped", "mode": "detected", "selected": []})
        skipped.write_text(saved)
        with (root / ".project/intent/INTENT.md").open("a") as handle:
            handle.write("\n7. An unreviewed criterion.\n")
        run_git(root, "add", ".project/intent/INTENT.md")
        run_git(root, "commit", "-m", "intent: add criterion after review")
        head = self.head(root)
        receipt = self.panel(root, "--wait", "60", advertised="claude-opus")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"],
                         "inputs changed after the review base; run a new cycle")
        self.assertIsNone(receipt.get("checkpoint"))
        self.assertEqual(self.head(root), head)
        self.assertEqual(skipped.read_text(), saved)

    def test_panel_rejects_a_null_skipped_receipt(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "detected")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        head = self.head(root)
        skipped = root / ".project/review/wave-1.cycle1.panel.skipped.json"
        skipped.write_text("null")
        receipt = self.panel(root, "--wait", "60", advertised="claude-opus")
        self.assertEqual(receipt["status"], "blocked", receipt)
        self.assertEqual(receipt["blocked"][0]["reason"],
                         "panel skipped receipt exists but is not a skipped receipt")
        self.assertIsNone(receipt.get("checkpoint"))
        self.assertEqual(self.head(root), head)
        self.assertEqual(skipped.read_text(), "null")

    def test_panel_reuses_a_valid_skipped_receipt_after_an_interrupted_checkpoint(self) -> None:
        root = self.root
        self.fixture(root)
        self.set_panel(root, "detected")
        self.assertEqual(self.round(root, "--wait", "60")["status"], "done")
        self.assertEqual(self.review(root, "--wait", "60")["status"], "pass")
        skipped = root / ".project/review/wave-1.cycle1.panel.skipped.json"
        skipped.write_text(json.dumps({"status": "skipped", "mode": "detected", "selected": []}))
        receipt = self.panel(root, "--wait", "60", advertised="claude-opus")
        self.assertEqual(receipt["status"], "skipped", receipt)
        self.assertEqual(self.subjects(root)[0], "build: record wave 1 cycle 1 review")


if __name__ == "__main__":
    unittest.main()
