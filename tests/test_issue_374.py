"""Regression tests for issue #374: two archive-ship blockers."""

import unittest
from types import SimpleNamespace

from scripts import build_recovery, check_handoffs


class TaskReviewObservationUnparseableNumberingTest(unittest.TestCase):
    """A frozen landed task may repeat a criterion number (#374, bug 1)."""

    TASK = (
        "## Context\n"
        "\n"
        "The task implements the demo.\n"
        "\n"
        "## Acceptance criteria\n"
        "\n"
        "1. The demo command prints hello.\n"
        "2. The demo test suite is green.\n"
        "2. The demo covers the repeated number.\n"
        "\n"
        "## Verify\n"
        "\n"
        "```bash\n"
        "true\n"
        "```\n"
    )
    WELL_FORMED = (
        "## Acceptance criteria\n"
        "\n"
        "1. The demo command prints hello.\n"
        "2. The demo test suite is green.\n"
        "\n"
        "## Verify\n"
    )

    def test_repeated_number_does_not_raise_and_keeps_the_evidence_line(self) -> None:
        item = "2. The demo covers the repeated number. \u2014 Observed in the log."
        self.assertEqual(
            check_handoffs.task_review_observation(item, self.TASK),
            item,
        )

    def test_exact_criterion_still_collapses_on_a_well_formed_task(self) -> None:
        self.assertEqual(
            check_handoffs.task_review_observation(
                "The demo command prints hello.", self.WELL_FORMED
            ),
            "",
        )

    def test_observed_criterion_still_strips_the_quoted_prefix(self) -> None:
        self.assertEqual(
            check_handoffs.task_review_observation(
                "The demo test suite is green. \u2014 Ran the suite: 12 pass.",
                self.WELL_FORMED,
            ),
            "Ran the suite: 12 pass.",
        )


class RecoveryBaseMilestoneProofTest(unittest.TestCase):
    """A recovery base with milestone null still proves identity (#374, bug 2)."""

    @staticmethod
    def state(
        milestone,
        *,
        branch: str = "gsd-path/M001",
        phase: str = "build",
        status: str = "blocked",
    ):
        return SimpleNamespace(
            branch=branch, milestone=milestone, phase=phase, status=status
        )

    def test_unset_base_milestone_proves_on_a_matching_branch(self) -> None:
        before = self.state(None)
        current = self.state("terra-dome", phase="ship", status="active")
        self.assertTrue(
            build_recovery._recovery_base_proves_milestone(before, current, "build")
        )

    def test_matching_named_milestones_still_prove(self) -> None:
        before = self.state("terra-dome")
        current = self.state("terra-dome")
        self.assertTrue(
            build_recovery._recovery_base_proves_milestone(before, current, "build")
        )

    def test_a_base_named_milestone_must_still_match(self) -> None:
        before = self.state("older-name")
        current = self.state("terra-dome")
        self.assertFalse(
            build_recovery._recovery_base_proves_milestone(before, current, "build")
        )

    def test_a_branch_mismatch_never_proves_even_with_an_unset_base(self) -> None:
        before = self.state(None, branch="gsd-path/M002")
        current = self.state("terra-dome")
        self.assertFalse(
            build_recovery._recovery_base_proves_milestone(before, current, "build")
        )


if __name__ == "__main__":
    unittest.main()
