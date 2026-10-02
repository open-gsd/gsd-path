from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from scripts import build_state


def task(
    task_id: str,
    wave: int,
    *,
    deps: tuple[str, ...] = (),
    status: str = "pending",
    review_findings: bool = False,
) -> build_state.Task:
    return build_state.Task(
        task_id=task_id,
        title=f"Task {task_id}",
        wave=wave,
        deps=deps,
        files=(f"src/{task_id.lower()}.py",),
        status=status,
        agent=None,
        base=None,
        worktree=None,
        task_branch=None,
        task_file=f".project/tasks/{task_id}-task.md",
        verify_heavy=False,
        review_findings=review_findings,
    )


class BlockedWaveRepairReadyTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.tasks_dir = self.repo / ".project" / "tasks"
        self.tasks_dir.mkdir(parents=True)
        self.review_dir = self.repo / ".project" / "review"
        self.review_dir.mkdir()

    def review(self, wave: int, cycle: int, lens: Optional[str], verdict: str) -> None:
        suffix = f".{lens}" if lens else ""
        path = self.review_dir / f"wave-{wave}.cycle{cycle}{suffix}.md"
        path.write_text(
            f"# Review — wave {wave}, cycle {cycle}\n\nWave verdict: {verdict}\n",
            encoding="utf-8",
        )

    def ready(self, *tasks: build_state.Task) -> dict:
        project = build_state.Project(
            repo=self.repo,
            branch="gsd-path/M001",
            head="a" * 40,
            tasks=tasks,
            tasks_dir=self.tasks_dir,
        )
        with mock.patch.object(build_state, "_load_project", return_value=project):
            with mock.patch.object(build_state, "_validate_ready_metadata"):
                return build_state.ready(str(self.repo))

    def source_and_ordinary(self) -> tuple[build_state.Task, build_state.Task]:
        return (
            task("T001", 1, status="done"),
            task("T002", 2, deps=("T001",)),
        )

    def test_blocked_latest_lens_cycle_selects_repair_wave(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, "contract", "blocked")
        self.review(1, 1, "adversarial", "pass")
        repair = task("T003", 4, deps=("T001",), review_findings=True)

        payload = self.ready(source, ordinary, repair)

        self.assertEqual(payload["current_wave"], 4)
        self.assertEqual(payload["repair_for_wave"], 1)
        self.assertEqual([item["id"] for item in payload["ready"]], ["T003"])

    def test_in_progress_repair_remains_the_selected_wave(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, "adversarial", "blocked")
        repair = task(
            "T003", 4, deps=("T001",), status="in-progress", review_findings=True
        )

        payload = self.ready(source, ordinary, repair)

        self.assertEqual(payload["current_wave"], 4)
        self.assertEqual(payload["repair_for_wave"], 1)
        self.assertEqual(payload["ready"], [])

    def test_failed_or_blocked_repair_uses_existing_recovery_route(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, None, "blocked")
        for status in ("failed", "blocked"):
            with self.subTest(status=status):
                repair = task(
                    "T003", 4, deps=("T001",), status=status, review_findings=True
                )
                with self.assertRaises(build_state.BuildStateError) as raised:
                    self.ready(source, ordinary, repair)
                self.assertEqual(raised.exception.code, "task-recovery-required")
                self.assertEqual(raised.exception.details["wave"], 4)

    def test_completed_repair_waits_for_a_passing_source_review(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, None, "blocked")
        repair = task(
            "T003", 4, deps=("T001",), status="done", review_findings=True
        )

        payload = self.ready(source, ordinary, repair)

        self.assertEqual(payload["current_wave"], 1)
        self.assertEqual(payload["ready"], [])
        self.assertEqual(
            payload["blocked_review"],
            {"wave": 1, "cycle": 1, "waiting_waves": [2]},
        )

    def test_blocked_review_remains_visible_when_every_task_is_done(self) -> None:
        source = task("T001", 1, status="done")
        self.review(1, 1, None, "blocked")

        payload = self.ready(source)

        self.assertEqual(payload["current_wave"], 1)
        self.assertEqual(payload["ready"], [])
        self.assertEqual(
            payload["blocked_review"],
            {"wave": 1, "cycle": 1, "waiting_waves": []},
        )

    def test_highest_cycle_pass_releases_wave_and_ignores_lower_blocked_cycle(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, "contract", "blocked")
        self.review(1, 2, "contract", "pass")
        self.review(1, 2, "adversarial", "pass")

        payload = self.ready(source, ordinary)

        self.assertEqual(payload["current_wave"], 2)
        self.assertEqual([item["id"] for item in payload["ready"]], ["T002"])
        self.assertNotIn("blocked_review", payload)

    def test_any_blocked_lens_in_the_highest_cycle_keeps_wave_blocked(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, None, "blocked")
        self.review(1, 2, "contract", "pass")
        self.review(1, 2, "adversarial", "blocked")
        repair = task("T003", 4, deps=("T001",), review_findings=True)

        payload = self.ready(source, ordinary, repair)

        self.assertEqual(payload["repair_for_wave"], 1)
        self.assertEqual([item["id"] for item in payload["ready"]], ["T003"])

    def test_panel_skeptic_and_repair_files_do_not_count_as_review_cycles(self) -> None:
        source, ordinary = self.source_and_ordinary()
        for name in (
            "wave-1.cycle99.panel.md",
            "wave-1.cycle100.skeptic-t001_ac1.md",
            "wave-1.cycle101.repair-T001.json",
            "wave-1.cycle102.panel.skipped.json",
        ):
            (self.review_dir / name).write_text(
                "Wave verdict: blocked\n", encoding="utf-8"
            )

        payload = self.ready(source, ordinary)

        self.assertEqual(payload["current_wave"], 2)
        self.assertEqual([item["id"] for item in payload["ready"]], ["T002"])
        self.assertNotIn("repair_for_wave", payload)

    def test_later_dependency_without_review_findings_does_not_qualify(self) -> None:
        source, ordinary = self.source_and_ordinary()
        self.review(1, 1, None, "blocked")
        later = task("T003", 4, deps=("T001",))

        payload = self.ready(source, ordinary, later)

        self.assertEqual(payload["current_wave"], 1)
        self.assertEqual(payload["ready"], [])
        self.assertEqual(payload["blocked_review"]["waiting_waves"], [2, 4])

    def test_repair_marker_uses_an_exact_review_findings_section_heading(self) -> None:
        path = self.tasks_dir / "T003-fix.md"
        frontmatter = """---
id: T003
title: Fix review finding
wave: 4
deps: [T001]
status: pending
agent: null
base: null
worktree: null
task_branch: null
files: [src/t003.py]
---
"""
        path.write_text(
            frontmatter + "\n## Review findings\n\nFix this.\n", encoding="utf-8"
        )
        parsed = build_state._parse_task(path, str(path), str(path))
        self.assertTrue(parsed.review_findings)

        path.write_text(
            frontmatter + "\n## Review findings and notes\n\nFix this.\n",
            encoding="utf-8",
        )
        parsed = build_state._parse_task(path, str(path), str(path))
        self.assertFalse(parsed.review_findings)


if __name__ == "__main__":
    unittest.main()
