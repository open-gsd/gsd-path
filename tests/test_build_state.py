from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import isolation


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_state.py"
BRANCH = "gsd-path/M001"


def run_git(repo: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(repo), *arguments),
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr or result.stdout)
    return result.stdout.strip()


def task_text(
    task_id: str,
    title: str,
    wave: int,
    deps: tuple[str, ...],
    files: tuple[str, ...],
    *,
    status: str = "pending",
    agent: str | None = None,
    base: str | None = None,
    worktree: str | None = None,
    task_branch: str | None = None,
    log: tuple[str, ...] = ("created",),
) -> str:
    scalar = lambda value: value if value is not None else "null"
    deps_value = ", ".join(deps)
    files_value = ", ".join(files)
    log_lines = "\n".join(f"- {item}" for item in log)
    return f"""---
id: {task_id}
title: {title}
wave: {wave}
deps: [{deps_value}]
status: {status}
agent: {scalar(agent)}
base: {scalar(base)}
worktree: {scalar(worktree)}
task_branch: {scalar(task_branch)}
files: [{files_value}]
---

# {task_id} — {title}

## Log

{log_lines}
"""


def plan_text(
    rows_by_wave: tuple[
        tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...], ...
    ],
) -> str:
    blocks = ["# Plan — test"]
    for wave, rows in enumerate(rows_by_wave, start=1):
        blocks.extend(
            (
                f"## Wave {wave} — test",
                "",
                f"Goal: exercise {len(rows)} canonical task files",
            )
        )
        blocks.append("")
    return "\n".join(blocks)


class BuildStateTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        run_git(self.repo, "init", "-q")
        run_git(self.repo, "config", "user.email", "test@example.com")
        run_git(self.repo, "config", "user.name", "Test User")
        run_git(self.repo, "switch", "-q", "-c", BRANCH)
        (self.repo / ".project" / "plan").mkdir(parents=True)
        (self.repo / ".project" / "tasks").mkdir()
        (self.repo / ".project" / "STATE.md").write_text(
            f"""---
pipeline: gsd-path/v2
project: test
milestone: test
phase: build
status: active
branch: {BRANCH}
archive: null
---
""",
            encoding="utf-8",
        )

    def write_plan(
        self,
        rows_by_wave: tuple[
            tuple[tuple[str, str, tuple[str, ...], tuple[str, ...]], ...], ...
        ],
    ) -> None:
        (self.repo / ".project" / "plan" / "PLAN.md").write_text(
            plan_text(rows_by_wave), encoding="utf-8"
        )

    def write_task(self, task_id: str, content: str, slug: str = "task") -> None:
        (self.repo / ".project" / "tasks" / f"{task_id}-{slug}.md").write_text(
            content, encoding="utf-8"
        )

    def commit_all(self, subject: str) -> str:
        run_git(self.repo, "add", "-A")
        run_git(self.repo, "commit", "-q", "-m", subject)
        return run_git(self.repo, "rev-parse", "HEAD")

    def cli(self, *arguments: str) -> tuple[subprocess.CompletedProcess[str], dict]:
        result = subprocess.run(
            (sys.executable, str(SCRIPT), *arguments, "--repo", str(self.repo)),
            text=True,
            capture_output=True,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
        except json.JSONDecodeError as error:
            self.fail(
                f"CLI did not return JSON: {result.stdout!r}; "
                f"stderr={result.stderr!r}; {error}"
            )
        return result, payload

    def test_ready_reads_canonical_task_files_without_plan_rows(self) -> None:
        self.write_plan(
            (
                (("T001", "First", (), ("one.py",)),),
                (("T002", "Later", (), ("two.py",)),),
            )
        )
        self.write_task("T001", task_text("T001", "First", 1, (), ("one.py",)))
        self.write_task("T002", task_text("T002", "Later", 2, (), ("two.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["current_wave"], 1)
        self.assertEqual([task["id"] for task in payload["ready"]], ["T001"])

    def test_ready_rejects_a_lookahead_project_directory(self) -> None:
        self.write_plan(((("T001", "Next", (), ("next.py",)),),))
        self.write_task("T001", task_text("T001", "Next", 1, (), ("next.py",)))
        next_root = self.repo / ".project" / "next"
        next_root.mkdir()
        (self.repo / ".project" / "STATE.md").rename(next_root / "STATE.md")
        (self.repo / ".project" / "plan").rename(next_root / "plan")
        (self.repo / ".project" / "tasks").rename(next_root / "tasks")
        self.commit_all("lookahead plan")

        result, payload = self.cli("ready", "--project-dir", ".project/next")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-project-dir")
        self.assertIn("lookahead", payload["error"]["message"])

    def test_ready_uses_complete_pipeline_state_validation(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, (), ("one.py",)))
        state_path = self.repo / ".project" / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace("archive: null\n", ""),
            encoding="utf-8",
        )
        self.commit_all("invalid state")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-state")
        self.assertIn("missing fields: archive", payload["error"]["message"])

    def test_ready_honors_same_wave_dependency_order(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")

        _, before = self.cli("ready")
        self.assertEqual([task["id"] for task in before["ready"]], ["T001"])

        task_path = self.repo / ".project" / "tasks" / "T001-task.md"
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Foundation",
                1,
                (),
                ("one.py",),
                status="in-progress",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        task_path.write_text(
            task_path.read_text(encoding="utf-8") + "- implementation complete\n",
            encoding="utf-8",
        )
        (self.repo / "one.py").write_text("done = True\n", encoding="utf-8")
        isolation.land(
            self.repo,
            self.repo,
            base,
            "T001",
            "Foundation",
            ".project/tasks/T001-task.md",
            ["one.py"],
        )
        result, after = self.cli("ready")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual([task["id"] for task in after["ready"]], ["T002"])

    def test_ready_rejects_done_task_without_a_proven_landing(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Foundation",
                1,
                (),
                ("one.py",),
                status="done",
                agent="builder",
                base=base,
            ),
        )

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("retry land", payload["error"]["message"])

    def test_ready_blocks_the_wave_until_failed_or_blocked_tasks_recover(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "Blocked", (), ("one.py",)),
                    ("T002", "Independent", (), ("two.py",)),
                ),
            )
        )
        self.write_task(
            "T001", task_text("T001", "Blocked", 1, (), ("one.py",))
        )
        self.write_task(
            "T002", task_text("T002", "Independent", 1, (), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Blocked",
                1,
                (),
                ("one.py",),
                status="blocked",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "task-recovery-required")
        self.assertEqual(payload["error"]["details"]["wave"], 1)
        self.assertEqual(
            payload["error"]["details"]["tasks"],
            [{"id": "T001", "status": "blocked"}],
        )

    def test_ready_validates_failed_or_blocked_task_ownership(self) -> None:
        self.write_plan(((('T001', 'Failed', (), ('one.py',)),),))
        self.write_task(
            "T001",
            task_text("T001", "Failed", 1, (), ("one.py",), status="failed"),
        )
        self.commit_all("invalid failed task")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("missing agent, base, or worktree", payload["error"]["message"])

    def test_ready_rejects_done_task_with_incomplete_dependency(self) -> None:
        rows = (
            (
                ("T001", "Foundation", (), ("one.py",)),
                ("T002", "Consumer", ("T001",), ("two.py",)),
            ),
        )
        self.write_plan(rows)
        self.write_task("T001", task_text("T001", "Foundation", 1, (), ("one.py",)))
        self.write_task(
            "T002", task_text("T002", "Consumer", 1, ("T001",), ("two.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T002",
            task_text(
                "T002",
                "Consumer",
                1,
                ("T001",),
                ("two.py",),
                status="done",
                agent="builder",
                base=base,
            ),
        )

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")
        self.assertIn("done task has an incomplete dependency", payload["error"]["message"])

    def test_ready_reports_dependency_cycle(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "One", ("T002",), ("one.py",)),
                    ("T002", "Two", ("T001",), ("two.py",)),
                ),
            )
        )
        self.write_task("T001", task_text("T001", "One", 1, ("T002",), ("one.py",)))
        self.write_task("T002", task_text("T002", "Two", 1, ("T001",), ("two.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "dependency-cycle")
        self.assertEqual(payload["error"]["details"]["cycle"], ["T001", "T002", "T001"])

    def test_ready_reports_a_missing_dependency(self) -> None:
        self.write_plan(((("T001", "One", ("T999",), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, ("T999",), ("one.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "missing-dependency")
        self.assertEqual(payload["error"]["details"]["dependency"], "T999")

    def test_ready_rejects_incomplete_active_metadata(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task(
            "T001", task_text("T001", "One", 1, (), ("one.py",), status="in-progress")
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-state")

    def test_ready_rejects_overlapping_candidates(self) -> None:
        self.write_plan(
            (
                (
                    ("T001", "One", (), ("shared.py",)),
                    ("T002", "Two", (), ("shared.py",)),
                ),
            )
        )
        self.write_task("T001", task_text("T001", "One", 1, (), ("shared.py",)))
        self.write_task("T002", task_text("T002", "Two", 1, (), ("shared.py",)))
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "ready-file-overlap")
        self.assertEqual(payload["error"]["details"]["tasks"], ["T001", "T002"])

    def test_ready_rejects_a_noncanonical_task_filename(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        (self.repo / ".project" / "tasks" / "T001.md").write_text(
            task_text("T001", "One", 1, (), ("one.py",)), encoding="utf-8"
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-file")

    def test_ready_rejects_a_stray_entry_beside_a_canonical_task(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task("T001", task_text("T001", "One", 1, (), ("one.py",)))
        (self.repo / ".project" / "tasks" / "notes.md").write_text(
            "post-review notes\n", encoding="utf-8"
        )
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "invalid-task-file")
        self.assertIn("notes.md", payload["error"]["message"])

    def test_ready_rejects_duplicate_task_ids(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        content = task_text("T001", "One", 1, (), ("one.py",))
        self.write_task("T001", content, "first")
        self.write_task("T001", content, "second")
        self.commit_all("plan")

        result, payload = self.cli("ready")

        self.assertEqual(result.returncode, 1)
        self.assertEqual(payload["error"]["code"], "duplicate-task-file")

    def prepare_in_progress_task(self) -> tuple[str, str]:
        self.write_plan(((("T001", "Implement feature", (), ("app.py",)),),))
        (self.repo / "app.py").write_text("value = 0\n", encoding="utf-8")
        self.write_task(
            "T001", task_text("T001", "Implement feature", 1, (), ("app.py",))
        )
        base = self.commit_all("plan")
        self.write_task(
            "T001",
            task_text(
                "T001",
                "Implement feature",
                1,
                (),
                ("app.py",),
                status="in-progress",
                agent="builder",
                base=base,
                worktree=str(self.repo),
            ),
        )
        return base, ".project/tasks/T001-task.md"

    def land_task(self, task_file: str, sequence: int) -> str:
        (self.repo / "app.py").write_text(f"value = {sequence}\n", encoding="utf-8")
        current = (self.repo / task_file).read_text(encoding="utf-8")
        (self.repo / task_file).write_text(
            current + f"- implementation {sequence}\n", encoding="utf-8"
        )
        fields = dict(
            line.split(": ", 1)
            for line in current.split("---", 2)[1].strip().splitlines()
            if ": " in line
        )
        base = fields["base"]
        result = isolation.land(
            self.repo,
            self.repo,
            base,
            "T001",
            "Implement feature",
            task_file,
            ["app.py"],
        )
        return str(result["commit"])

    def test_reconcile_proves_one_canonical_landed_commit(self) -> None:
        base, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        before = run_git(self.repo, "status", "--porcelain=v1", "--untracked-files=all")

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            run_git(self.repo, "status", "--porcelain=v1", "--untracked-files=all"), before
        )
        self.assertEqual(payload["classification"], "proven-landed")
        self.assertEqual(payload["landed_commit"], landed)
        self.assertEqual(len(payload["history"]["candidates"]), 1)
        self.assertTrue(payload["history"]["candidates"][0]["valid"])

    def test_reconcile_proves_done_commit_from_isolation_history(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "proven-landed")
        self.assertEqual(payload["landed_commit"], landed)

    def test_reconcile_rejects_rewritten_ancestral_dispatch_base(self) -> None:
        (self.repo / "seed.txt").write_text("seed\n", encoding="utf-8")
        earlier = self.commit_all("seed")
        base, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        path = self.repo / task_file
        path.write_text(
            path.read_text(encoding="utf-8")
            .replace(f"base: {base}", f"base: {earlier}"),
            encoding="utf-8",
        )

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "blocked")
        self.assertIn("no landing commit", payload["reasons"][0])

    def test_verify_landed_uses_canonical_paths_for_archived_tasks(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        landed = self.land_task(task_file, 1)
        archive = self.repo / ".project" / "archive" / "001-test"
        archive.mkdir(parents=True)
        (self.repo / ".project" / "plan").rename(archive / "plan")
        (self.repo / ".project" / "tasks").rename(archive / "tasks")

        result, payload = self.cli(
            "verify-landed",
            "--project-dir",
            ".project/archive/001-test",
            "--head",
            landed,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["head"], landed)
        self.assertEqual(len(payload["tasks"]), 1)
        self.assertEqual(payload["tasks"][0]["classification"], "proven-landed")
        self.assertEqual(
            payload["tasks"][0]["task"]["task_file"],
            ".project/tasks/T001-task.md",
        )

    def test_reconcile_marks_unlanded_owned_work_resumable(self) -> None:
        self.prepare_in_progress_task()

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "resumable")
        self.assertEqual(payload["history"]["candidates"], [])

    def test_reconcile_blocks_in_progress_without_a_recorded_base(self) -> None:
        self.write_plan(((("T001", "One", (), ("one.py",)),),))
        self.write_task(
            "T001",
            task_text(
                "T001",
                "One",
                1,
                (),
                ("one.py",),
                status="in-progress",
                agent="builder",
                worktree=str(self.repo),
            ),
        )
        self.commit_all("invalid dispatch")

        result, payload = self.cli("reconcile", "--task-id", "T001")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(payload["classification"], "blocked")
        self.assertIn("invalid base", payload["reasons"][0])

    def test_isolation_rejects_a_second_landing_for_done_task(self) -> None:
        _, task_file = self.prepare_in_progress_task()
        self.land_task(task_file, 1)

        with self.assertRaises(isolation.IsolationError):
            self.land_task(task_file, 2)


if __name__ == "__main__":
    unittest.main()
