import unittest

from scripts import pipeline_git


class PipelineGitTests(unittest.TestCase):
    def test_bound_branch_name_uses_m00n(self) -> None:
        self.assertEqual(pipeline_git.bound_branch_name(1), "gsd-path/M001")
        self.assertEqual(pipeline_git.bound_branch_name(12), "gsd-path/M012")
        self.assertTrue(pipeline_git.is_bound_branch("gsd-path/M001"))
        self.assertFalse(pipeline_git.is_bound_branch("gsd-path/demo"))
        self.assertFalse(pipeline_git.is_bound_branch("main"))

    def test_ship_and_integrate_subjects(self) -> None:
        self.assertEqual(
            pipeline_git.ship_subject("001-phase-0-1"),
            "ship: M001 — phase-0-1",
        )
        self.assertEqual(
            pipeline_git.integrate_subject("001-phase-0-1", "main"),
            "integrate: M001 — merge gsd-path/M001 into main",
        )
        self.assertTrue(
            pipeline_git.is_ship_subject("ship: M001 — phase-0-1", "001-phase-0-1")
        )
        self.assertTrue(
            pipeline_git.is_ship_subject("ship: 001-phase-0-1", "001-phase-0-1")
        )
        self.assertTrue(
            pipeline_git.is_integrate_subject(
                "integrate: 001-phase-0-1", "001-phase-0-1", "main"
            )
        )
        self.assertFalse(
            pipeline_git.is_integrate_subject(
                "integrate: M001 — merge gsd-path/M001 into main",
                "001-phase-0-1",
                "master",
            )
        )

    def test_task_commit_message(self) -> None:
        self.assertEqual(
            pipeline_git.task_commit_subject("T009", " Verify snapshot "),
            "T009: Verify snapshot",
        )
        body = pipeline_git.task_commit_body(
            ".project/tasks/T009.md",
            [".project/tasks/T009.md", "app/cron.ts"],
        )
        self.assertEqual(
            body,
            "Task: .project/tasks/T009.md\n"
            "Files:\n"
            "- .project/tasks/T009.md\n"
            "- app/cron.ts\n",
        )

    def test_next_milestone_number(self) -> None:
        self.assertEqual(pipeline_git.next_milestone_number([]), 1)
        self.assertEqual(pipeline_git.next_milestone_number(["001-demo"]), 2)
        self.assertEqual(
            pipeline_git.next_milestone_number(["001-demo"], active_roadmap_id="M003"),
            3,
        )

    def test_active_roadmap_milestone_id(self) -> None:
        roadmap = (
            "### M001 — first\nStatus: shipped\n\n"
            "### M002 — second\nStatus: active\n\n"
            "### M003 — third\nStatus: pending\n"
        )
        self.assertEqual(pipeline_git.active_roadmap_milestone_id(roadmap), "M002")
        self.assertIsNone(pipeline_git.active_roadmap_milestone_id("### M001 — only\n"))


if __name__ == "__main__":
    unittest.main()
