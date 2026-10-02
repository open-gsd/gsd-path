"""Superseded wave review cycles are history, not re-checked against current PLAN."""

import tempfile
import unittest
from pathlib import Path
from typing import Optional

from scripts import discussion_validate
from scripts.archive_milestone import ArchiveError


class ValidateWaveReviewSupersededTest(unittest.TestCase):
    TASKS = [("T001", "Deactivate installed systems")]
    CRITERIA = [("SC1", "A dispatcher can deactivate a system.")]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "wave-1.cycle1.md"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, text: str) -> None:
        self.path.write_text(text, encoding="utf-8")

    def review(
        self,
        *,
        wave_verdict: str,
        task_verdict: str,
        coverage_heading: str,
        marker: str,
    ) -> str:
        return "\n".join(
            [
                "# Review — wave 1, cycle 1",
                "",
                f"Wave verdict: {wave_verdict}",
                "Cycle: 1",
                "Depth: full",
                "Tasks reviewed: 1",
                "",
                f"## T001 — Deactivate installed systems: {task_verdict}",
                "",
                f"- {marker} Relation manager deactivate action checked at app/Example.php:12 with the recorded Verify output.",
                "",
                "## Intent coverage",
                "",
                coverage_heading,
                f"- {marker} Evidence recorded in tests/Feature/ExampleTest.php:40 from the recorded Verify run.",
                "",
            ]
        )

    def test_superseded_blocked_cycle_skips_criterion_text_match(self) -> None:
        self.write(
            self.review(
                wave_verdict="blocked",
                task_verdict="fail",
                coverage_heading="### SC1 — deactivate (paraphrased): fail",
                marker="❌",
            )
        )
        self.assertEqual(
            list(
                discussion_validate.validate_wave_review(
                    self.path,
                    self.TASKS,
                    self.CRITERIA,
                    "full",
                    is_last_cycle=False,
                )
            ),
            ["fail"],
        )

    def test_last_cycle_still_requires_exact_criterion_text(self) -> None:
        self.write(
            self.review(
                wave_verdict="blocked",
                task_verdict="fail",
                coverage_heading="### SC1 — deactivate (paraphrased): fail",
                marker="❌",
            )
        )
        with self.assertRaises(ArchiveError):
            discussion_validate.validate_wave_review(
                self.path, self.TASKS, self.CRITERIA, "full"
            )

    def test_superseded_cycle_still_checks_task_headings(self) -> None:
        self.write(
            self.review(
                wave_verdict="blocked",
                task_verdict="fail",
                coverage_heading="### SC1 — x: fail",
                marker="❌",
            ).replace("## T001 — Deactivate installed systems", "## T009 — Something else")
        )
        with self.assertRaises(ArchiveError):
            discussion_validate.validate_wave_review(
                self.path,
                self.TASKS,
                self.CRITERIA,
                "full",
                is_last_cycle=False,
            )


class ReviewCycleCountsSupersededTest(unittest.TestCase):
    def make_project(self, project: Path, depth: str) -> None:
        for directory in ("intent", "plan", "tasks", "review"):
            (project / directory).mkdir()
        (project / "intent" / "INTENT.md").write_text(
            "# Intent\n\n## Success criteria\n\n1. demo works\n",
            encoding="utf-8",
        )
        (project / "plan" / "PLAN.md").write_text(
            f"""# Plan

## Wave 1 — demo

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | demo | — | src/demo.py |

Review depth: {depth}

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |
""",
            encoding="utf-8",
        )
        (project / "tasks" / "T001-demo.md").write_text(
            "---\nid: T001\ntitle: demo\nwave: 1\n---\n",
            encoding="utf-8",
        )

    def write_cycle_review(
        self,
        project: Path,
        *,
        cycle: int,
        depth: str,
        wave_verdict: str,
        task_verdict: str = "pass",
        lens: Optional[str] = None,
    ) -> Path:
        suffix = f".{lens}" if lens else ""
        path = project / "review" / f"wave-1.cycle{cycle}{suffix}.md"
        marker = "✅" if task_verdict == "pass" else "❌"
        lens_field = f"Lens: {lens}\n" if lens else ""
        path.write_text(
            f"""# Review — wave 1, cycle {cycle}

Wave verdict: {wave_verdict}
Cycle: {cycle}
Depth: {depth}
{lens_field}Tasks reviewed: 1

## T001 — demo: {task_verdict}

- {marker} demo works — evidence recorded in tests/ExampleTest.py:14 from the Verify output.

## Intent coverage

### SC1 — demo works: pass

- ✅ Evidence recorded in tests/ExampleTest.py:21 from the Verify output.
""",
            encoding="utf-8",
        )
        return path

    def write_deep_cycles(
        self,
        project: Path,
        first_verdicts: tuple[str, str],
        *,
        last_verdicts: tuple[str, str] = ("pass", "pass"),
        last_task_verdicts: tuple[str, str] = ("pass", "pass"),
    ) -> tuple[Path, Path, Path, Path]:
        self.make_project(project, "deep")
        first = tuple(
            self.write_cycle_review(
                project,
                cycle=1,
                depth="deep",
                lens=lens,
                wave_verdict=verdict,
            )
            for lens, verdict in zip(("contract", "adversarial"), first_verdicts)
        )
        last = tuple(
            self.write_cycle_review(
                project,
                cycle=2,
                depth="deep",
                lens=lens,
                wave_verdict=verdict,
                task_verdict=task_verdict,
            )
            for lens, verdict, task_verdict in zip(
                ("contract", "adversarial"), last_verdicts, last_task_verdicts
            )
        )
        return (*first, *last)

    def test_deep_superseded_cycles_require_a_blocked_gate(self) -> None:
        cases = (
            (("blocked", "pass"), True),
            (("pass", "blocked"), True),
            (("blocked", "blocked"), True),
            (("pass", "pass"), False),
        )
        for verdicts, accepted in cases:
            with self.subTest(verdicts=verdicts), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.write_deep_cycles(project, verdicts)
                if accepted:
                    self.assertEqual(discussion_validate.review_cycle_counts(project), [2])
                else:
                    with self.assertRaisesRegex(ArchiveError, "superseded review cycle"):
                        discussion_validate.review_cycle_counts(project)

    def test_deep_latest_cycle_requires_every_gate_and_task_to_pass(self) -> None:
        cases = (
            (("blocked", "pass"), ("pass", "pass"), "last review cycle"),
            (("pass", "pass"), ("fail", "pass"), "failed task"),
        )
        for last_verdicts, task_verdicts, expected_error in cases:
            with self.subTest(last_verdicts=last_verdicts, task_verdicts=task_verdicts), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.write_deep_cycles(
                    project,
                    ("pass", "blocked"),
                    last_verdicts=last_verdicts,
                    last_task_verdicts=task_verdicts,
                )
                with self.assertRaisesRegex(ArchiveError, expected_error):
                    discussion_validate.review_cycle_counts(project)

    def test_superseded_passing_lens_still_checks_structure_and_evidence(self) -> None:
        cases = (
            (
                "task-heading",
                "## T001 — demo: pass",
                "## T009 — unrelated: pass",
                "tasks and titles do not match",
            ),
            (
                "evidence",
                "- ✅ demo works — evidence recorded in tests/ExampleTest.py:14 from the Verify output.",
                "- no evidence",
                "lacks non-placeholder evidence",
            ),
        )
        for name, original, replacement, expected_error in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                reviews = self.write_deep_cycles(project, ("pass", "blocked"))
                passing_lens = reviews[0]
                passing_lens.write_text(
                    passing_lens.read_text(encoding="utf-8").replace(
                        original, replacement
                    ),
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(ArchiveError, expected_error):
                    discussion_validate.review_cycle_counts(project)

    def test_singleton_full_and_verify_only_cycles_still_pass(self) -> None:
        for depth in ("full", "verify-only"):
            with self.subTest(depth=depth), tempfile.TemporaryDirectory() as directory:
                project = Path(directory)
                self.make_project(project, depth)
                self.write_cycle_review(
                    project,
                    cycle=1,
                    depth=depth,
                    wave_verdict="pass",
                )
                self.assertEqual(discussion_validate.review_cycle_counts(project), [1])

    def test_fix_task_added_after_blocked_wave_cycle_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            for directory in ("intent", "plan", "tasks", "review"):
                (project / directory).mkdir()
            (project / "intent" / "INTENT.md").write_text(
                "# Intent\n\n## Success criteria\n\n1. demo works\n",
                encoding="utf-8",
            )
            (project / "plan" / "PLAN.md").write_text(
                """# Plan

## Wave 1 — demo

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | demo | — | src/demo.py |
| T002 | fix demo | T001 | src/demo.py |

Review depth: full

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |
| SC1 | T002 | AC1 |
""",
                encoding="utf-8",
            )
            (project / "tasks" / "T001-demo.md").write_text(
                "---\nid: T001\ntitle: demo\nwave: 1\n---\n",
                encoding="utf-8",
            )
            (project / "tasks" / "T002-fix.md").write_text(
                "---\nid: T002\ntitle: fix demo\nwave: 1\n---\n",
                encoding="utf-8",
            )
            (project / "review" / "wave-1.cycle1.md").write_text(
                """# Review — wave 1, cycle 1

Wave verdict: blocked
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — a wave-level gate was blocked before the fix task existed

## Intent coverage

### SC1 — demo works: pass

- ✅ cycle one evidence
""",
                encoding="utf-8",
            )
            (project / "review" / "wave-1.cycle2.md").write_text(
                """# Review — wave 1, cycle 2

Wave verdict: pass
Cycle: 2
Depth: full
Tasks reviewed: 2

## T001 — demo: pass

- ✅ demo works — still passes after fix

## T002 — fix demo: pass

- ✅ fix closes external review finding

## Intent coverage

### SC1 — demo works: pass

- ✅ both tasks covered in cycle two
""",
                encoding="utf-8",
            )

            self.assertEqual(discussion_validate.review_cycle_counts(project), [2])

    def test_blocked_cycle_one_with_stale_sc_heading(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            project = Path(temporary_directory)
            for directory in ("intent", "plan", "tasks", "review"):
                (project / directory).mkdir()
            (project / "intent" / "INTENT.md").write_text(
                "# Intent\n\n## Success criteria\n\n1. demo works\n",
                encoding="utf-8",
            )
            (project / "plan" / "PLAN.md").write_text(
                """# Plan

## Wave 1 — demo

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | demo | — | src/demo.py |

Review depth: full

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |
""",
                encoding="utf-8",
            )
            (project / "tasks" / "T001-demo.md").write_text(
                "---\nid: T001\ntitle: demo\nwave: 1\n---\n",
                encoding="utf-8",
            )
            (project / "review" / "wave-1.cycle1.md").write_text(
                """# Review — wave 1, cycle 1

Wave verdict: blocked
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: fail

- ❌ demo works — blocked on SC wording slip

## Intent coverage

### SC1 — demo works (paraphrased): fail

- ❌ stale heading text from blocked cycle one
""",
                encoding="utf-8",
            )
            (project / "review" / "wave-1.cycle2.md").write_text(
                """# Review — wave 1, cycle 2

Wave verdict: pass
Cycle: 2
Depth: full
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — cycle two passes with exact heading

## Intent coverage

### SC1 — demo works: pass

- ✅ conforming heading in authoritative cycle
""",
                encoding="utf-8",
            )

            self.assertEqual(discussion_validate.review_cycle_counts(project), [2])


if __name__ == "__main__":
    unittest.main()
