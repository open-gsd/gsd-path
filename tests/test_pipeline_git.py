import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_git


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_GIT = ROOT / "scripts" / "pipeline_git.py"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


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

    def test_bind_next_starts_m002_from_integrated_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            default_checkout = Path(tmp) / "repo"
            primary = Path(tmp) / "repo-gsd-path"
            run_git(Path(tmp), "init", "-b", "main", str(default_checkout))
            run_git(default_checkout, "config", "user.name", "GSD Path Test")
            run_git(default_checkout, "config", "user.email", "test@example.com")
            (default_checkout / "product.txt").write_text("base\n", encoding="utf-8")
            run_git(default_checkout, "add", "product.txt")
            run_git(default_checkout, "commit", "-m", "base")
            run_git(
                default_checkout,
                "worktree",
                "add",
                "-b",
                "gsd-path/M001",
                str(primary),
                "main",
            )

            project = primary / ".project"
            project.mkdir()
            (project / "STATE.md").write_text("status: shipped\n", encoding="utf-8")
            run_git(primary, "add", ".project/STATE.md")
            run_git(
                primary,
                "commit",
                "-m",
                "ship: M001 — first",
                "-m",
                "Archive: .project/archive/001-first/\nReviewed-HEAD: base",
            )
            m001_ship = run_git(primary, "rev-parse", "HEAD").stdout.strip()

            run_git(
                default_checkout,
                "merge",
                "--no-ff",
                "gsd-path/M001",
                "-m",
                "integrate: M001 — merge gsd-path/M001 into main",
                "-m",
                f"Ship: {m001_ship}\nDefault: main\nBranch: gsd-path/M001",
            )
            integrated_main = run_git(
                default_checkout,
                "rev-parse",
                "HEAD",
            ).stdout.strip()
            run_git(
                default_checkout,
                "update-ref",
                "refs/remotes/origin/main",
                integrated_main,
            )

            bind_next = [
                sys.executable,
                str(PIPELINE_GIT),
                "bind-next",
                "--repo",
                str(primary),
                "--branch",
                "gsd-path/M002",
                "--previous-branch",
                "gsd-path/M001",
                "--ship",
                m001_ship,
                "--remote-default",
                "origin/main",
                "--base",
                integrated_main,
            ]
            result = subprocess.run(
                bind_next,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                run_git(primary, "branch", "--show-current").stdout.strip(),
                "gsd-path/M002",
            )
            self.assertEqual(
                run_git(primary, "rev-parse", "HEAD").stdout.strip(),
                integrated_main,
            )
            self.assertEqual(
                run_git(primary, "rev-parse", "gsd-path/M001").stdout.strip(),
                m001_ship,
            )
            self.assertEqual(
                run_git(default_checkout, "branch", "--show-current").stdout.strip(),
                "main",
            )
            self.assertEqual(
                run_git(default_checkout, "rev-parse", "HEAD").stdout.strip(),
                integrated_main,
            )

            retry = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(retry.returncode, 0, retry.stderr)


if __name__ == "__main__":
    unittest.main()
