"""Superseded wave review cycles are history, not re-checked against current PLAN."""

import tempfile
import unittest
from pathlib import Path

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
    def test_fix_task_added_after_passing_cycle_one(self) -> None:
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

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — cycle one passed before fix task existed

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
