import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import pipeline_git, pipeline_state


ROOT = Path(__file__).resolve().parents[1]
PIPELINE_GIT = ROOT / "scripts" / "pipeline_git.py"


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def make_remote_repo(tmp: str) -> tuple[Path, Path, str]:
    origin = Path(tmp) / "origin.git"
    repo = Path(tmp) / "repo"
    run_git(Path(tmp), "init", "--bare", "-b", "main", str(origin))
    run_git(Path(tmp), "init", "-b", "main", str(repo))
    run_git(repo, "config", "user.name", "GSD Path Test")
    run_git(repo, "config", "user.email", "test@example.com")
    (repo / "product.txt").write_text("base\n", encoding="utf-8")
    run_git(repo, "add", "product.txt")
    run_git(repo, "commit", "-m", "base")
    run_git(repo, "remote", "add", "origin", str(origin))
    run_git(repo, "push", "-u", "origin", "main")
    return origin, repo, run_git(repo, "rev-parse", "HEAD").stdout.strip()


def make_integrated_milestone(tmp: str) -> tuple[Path, Path, str, str]:
    origin, repo, base = make_remote_repo(tmp)
    run_git(repo, "switch", "-c", "gsd-path/M001", base)
    project = repo / ".project"
    project.mkdir()
    (project / "STATE.md").write_text(
        "---\n"
        "pipeline: gsd-path/v2\n"
        "project: demo\n"
        "milestone: first\n"
        "phase: shipped\n"
        "status: done\n"
        "branch: gsd-path/M001\n"
        "archive: .project/archive/001-first/\n"
        "---\n\n"
        "# Project State\n\n"
        "## Log\n",
        encoding="utf-8",
    )
    (repo / "milestone.txt").write_text("shipped\n", encoding="utf-8")
    run_git(repo, "add", ".project/STATE.md", "milestone.txt")
    run_git(repo, "commit", "-m", "ship: M001 — first")
    ship = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    run_git(repo, "push", "origin", "gsd-path/M001")
    run_git(repo, "switch", "main")
    run_git(
        repo,
        "merge",
        "--no-ff",
        "gsd-path/M001",
        "-m",
        "integrate: M001 — merge gsd-path/M001 into main",
    )
    integrate = run_git(repo, "rev-parse", "HEAD").stdout.strip()
    run_git(repo, "push", "origin", "main")
    run_git(repo, "switch", "gsd-path/M001")
    return origin, repo, ship, integrate


class PipelineGitTests(unittest.TestCase):
    def test_bound_branch_name_uses_m00n(self) -> None:
        self.assertEqual(pipeline_git.bound_branch_name(1), "gsd-path/M001")
        self.assertEqual(pipeline_git.bound_branch_name(12), "gsd-path/M012")
        self.assertTrue(pipeline_git.is_bound_branch("gsd-path/M001"))
        self.assertFalse(pipeline_git.is_bound_branch("gsd-path/M000"))
        self.assertFalse(pipeline_git.is_bound_branch("gsd-path/demo"))
        self.assertFalse(pipeline_git.is_bound_branch("main"))
        for token in ("M000", "gsd-path/M000", "000-demo"):
            with self.subTest(token=token), self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                ">= 1",
            ):
                pipeline_git.milestone_number(token)

    def test_active_roadmap_rejects_m000(self) -> None:
        roadmap = "### M000 — invalid\n\nStatus: active\n"

        with self.assertRaisesRegex(pipeline_git.PipelineGitError, ">= 1"):
            pipeline_git.active_roadmap_milestone_id(roadmap)

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
            base="a" * 40,
        )
        self.assertEqual(
            body,
            "Task: .project/tasks/T009.md\n"
            "Base: " + "a" * 40 + "\n"
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

    def test_bind_initial_uses_exact_remote_default_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, base = make_remote_repo(tmp)
            command = [
                sys.executable,
                str(PIPELINE_GIT),
                "bind-initial",
                "--repo",
                str(repo),
                "--branch",
                "gsd-path/M001",
                "--remote-default",
                "origin/main",
                "--base",
                base,
            ]

            result = subprocess.run(command, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], "gsd-path/bind-initial/v1")
            self.assertEqual(payload["status"], "bound")
            self.assertEqual(
                run_git(repo, "branch", "--show-current").stdout.strip(),
                "gsd-path/M001",
            )
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), base)

            retry = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)["status"], "already-bound")

    def test_bind_initial_rejects_dirty_or_stale_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, base = make_remote_repo(tmp)
            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "full commit SHA",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base[:12],
                )
            (repo / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "not clean",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base,
                )
            (repo / "untracked.txt").unlink()
            (repo / "second.txt").write_text("ahead\n", encoding="utf-8")
            run_git(repo, "add", "second.txt")
            run_git(repo, "commit", "-m", "ahead")
            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "not at origin/main",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base,
                )

    def test_bind_initial_rejects_branch_owned_by_another_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, base = make_remote_repo(tmp)
            other = Path(tmp) / "other"
            run_git(
                repo,
                "worktree",
                "add",
                "-b",
                "gsd-path/M001",
                str(other),
                base,
            )

            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "another worktree",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base,
                )

    def test_bind_initial_rejects_stale_fetched_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin, repo, base = make_remote_repo(tmp)
            other = Path(tmp) / "other-clone"
            run_git(Path(tmp), "clone", str(origin), str(other))
            run_git(other, "config", "user.name", "GSD Path Test")
            run_git(other, "config", "user.email", "test@example.com")
            (other / "remote.txt").write_text("new remote head\n", encoding="utf-8")
            run_git(other, "add", "remote.txt")
            run_git(other, "commit", "-m", "advance remote")
            run_git(other, "push", "origin", "main")

            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "stale relative to origin",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base,
                )

    def test_bind_initial_rejects_remote_branch_collision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, base = make_remote_repo(tmp)
            run_git(repo, "branch", "gsd-path/M001", base)
            run_git(repo, "push", "origin", "gsd-path/M001")

            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "on origin",
            ):
                pipeline_git.bind_initial_milestone_branch(
                    repo,
                    "gsd-path/M001",
                    "origin/main",
                    base,
                )

    def test_retire_previous_branch_leases_remote_before_local_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, ship = make_remote_repo(tmp)
            run_git(repo, "branch", "gsd-path/M001", ship)
            run_git(repo, "push", "origin", "gsd-path/M001")
            run_git(repo, "switch", "-c", "gsd-path/M002", ship)
            calls: list[tuple[str, ...]] = []
            original = pipeline_git._run_git

            def recording_run_git(
                target: Path,
                *arguments: str,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                calls.append(arguments)
                return original(target, *arguments, check=check)

            with mock.patch.object(pipeline_git, "_run_git", side_effect=recording_run_git):
                pipeline_git.retire_previous_branch(
                    repo,
                    "gsd-path/M001",
                    ship,
                )

            remote_delete = next(
                index
                for index, arguments in enumerate(calls)
                if arguments[:2] == ("push", f"--force-with-lease=refs/heads/gsd-path/M001:{ship}")
            )
            local_delete = next(
                index
                for index, arguments in enumerate(calls)
                if arguments[:2] == ("branch", "-d")
            )
            self.assertLess(remote_delete, local_delete)

    def test_bind_next_rejects_unjournaled_target_branch_adoption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, ship, integrate = make_integrated_milestone(tmp)
            run_git(repo, "switch", "-c", "gsd-path/M002", integrate)

            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "no matching bind-next journal",
            ):
                pipeline_git.bind_next_milestone_branch(
                    repo,
                    "gsd-path/M002",
                    "gsd-path/M001",
                    ship,
                    "origin/main",
                    integrate,
                )

    def test_bind_next_resumes_after_switch_from_matching_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, ship, integrate = make_integrated_milestone(tmp)
            with mock.patch.object(
                pipeline_git,
                "retire_previous_branch",
                side_effect=pipeline_git.PipelineGitError("simulated interruption"),
            ):
                with self.assertRaisesRegex(
                    pipeline_git.PipelineGitError,
                    "simulated interruption",
                ):
                    pipeline_git.bind_next_milestone_branch(
                        repo,
                        "gsd-path/M002",
                        "gsd-path/M001",
                        ship,
                        "origin/main",
                        integrate,
                    )

            self.assertEqual(
                run_git(repo, "branch", "--show-current").stdout.strip(),
                "gsd-path/M002",
            )
            journal = pipeline_git.bind_next_journal_path(repo, "gsd-path/M002")
            self.assertEqual(
                json.loads(journal.read_text(encoding="utf-8"))["stage"],
                "switched",
            )

            result = pipeline_git.bind_next_milestone_branch(
                repo,
                "gsd-path/M002",
                "gsd-path/M001",
                ship,
                "origin/main",
                integrate,
            )

            self.assertEqual(result["status"], "already-bound")
            self.assertEqual(
                json.loads(journal.read_text(encoding="utf-8"))["stage"],
                "retired",
            )

    def test_bind_next_persists_ownership_before_switch_and_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, ship, integrate = make_integrated_milestone(tmp)
            original = pipeline_git._run_git

            def interrupt_switch(
                target: Path,
                *arguments: str,
                check: bool = True,
            ) -> subprocess.CompletedProcess[str]:
                if arguments[:3] == ("switch", "--no-track", "-c"):
                    raise pipeline_git.PipelineGitError("simulated switch interruption")
                return original(target, *arguments, check=check)

            with mock.patch.object(
                pipeline_git,
                "_run_git",
                side_effect=interrupt_switch,
            ):
                with self.assertRaisesRegex(
                    pipeline_git.PipelineGitError,
                    "simulated switch interruption",
                ):
                    pipeline_git.bind_next_milestone_branch(
                        repo,
                        "gsd-path/M002",
                        "gsd-path/M001",
                        ship,
                        "origin/main",
                        integrate,
                    )

            journal_path = pipeline_git.bind_next_journal_path(
                repo,
                "gsd-path/M002",
            )
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
            self.assertEqual(journal["stage"], "prepared")
            self.assertEqual(
                run_git(repo, "branch", "--show-current").stdout.strip(),
                "gsd-path/M001",
            )

            recovery = pipeline_state.route_state(repo)["route"]
            self.assertEqual(recovery["action"], "resume-next-handoff")
            self.assertEqual(recovery["previous_branch"], "gsd-path/M001")

            result = pipeline_git.bind_next_milestone_branch(
                repo,
                str(recovery["branch"]),
                str(recovery["previous_branch"]),
                str(recovery["ship"]),
                str(recovery["remote_default"]),
                str(recovery["base"]),
            )

            self.assertEqual(result["status"], "bound")
            self.assertEqual(
                json.loads(journal_path.read_text(encoding="utf-8"))["stage"],
                "retired",
            )

    def test_bind_next_requires_pull_request_tag_after_branch_auto_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin.git"
            default_checkout = Path(tmp) / "repo"
            primary = Path(tmp) / "repo-gsd-path"
            run_git(Path(tmp), "init", "--bare", "-b", "main", str(origin))
            run_git(Path(tmp), "init", "-b", "main", str(default_checkout))
            run_git(default_checkout, "config", "user.name", "GSD Path Test")
            run_git(default_checkout, "config", "user.email", "test@example.com")
            (default_checkout / "product.txt").write_text("base\n", encoding="utf-8")
            run_git(default_checkout, "add", "product.txt")
            run_git(default_checkout, "commit", "-m", "base")
            run_git(default_checkout, "remote", "add", "origin", str(origin))
            run_git(default_checkout, "push", "-u", "origin", "main")
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
            run_git(primary, "push", "origin", "gsd-path/M001")

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
            run_git(default_checkout, "push", "origin", "main")
            run_git(default_checkout, "push", "origin", "--delete", "gsd-path/M001")

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
                "--allow-missing-previous",
            ]
            nested = primary / "nested"
            nested.mkdir()
            with self.assertRaisesRegex(
                pipeline_git.PipelineGitError,
                "worktree root",
            ):
                pipeline_git.bind_next_milestone_branch(
                    nested,
                    "gsd-path/M002",
                    "gsd-path/M001",
                    m001_ship,
                    "origin/main",
                    integrated_main,
                    allow_remote_absent=True,
                )
            nested.rmdir()

            rejected = subprocess.run(
                bind_next,
                capture_output=True,
                text=True,
            )
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("pull-request integration proof", rejected.stderr)

            tag_message = (
                "milestone 001-first\n\n"
                "Mode: pull-request\n"
                "Pull-Request: https://github.com/open-gsd/demo/pull/7\n"
                f"Ship: {m001_ship}\n"
                f"Landing: {integrated_main}"
            )
            run_git(
                default_checkout,
                "tag",
                "-a",
                "-m",
                tag_message,
                "milestone/001-first",
                integrated_main,
            )
            run_git(default_checkout, "push", "origin", "milestone/001-first")

            result = subprocess.run(
                bind_next,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["status"], "bound")
            self.assertEqual(
                run_git(primary, "branch", "--show-current").stdout.strip(),
                "gsd-path/M002",
            )
            self.assertEqual(
                run_git(primary, "rev-parse", "HEAD").stdout.strip(),
                integrated_main,
            )
            retired_local = subprocess.run(
                ["git", "-C", str(primary), "show-ref", "--verify", "--quiet",
                 "refs/heads/gsd-path/M001"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(retired_local.returncode, 1, "gsd-path/M001 not retired")
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
            self.assertEqual(json.loads(retry.stdout)["status"], "already-bound")

            run_git(origin, "update-ref", "refs/heads/main", m001_ship)
            stale_retry = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(stale_retry.returncode, 1)
            self.assertIn("stale relative to origin", stale_retry.stderr)
            run_git(origin, "update-ref", "refs/heads/main", integrated_main)

            run_git(primary, "push", "origin", "gsd-path/M002")
            run_git(
                primary,
                "update-ref",
                "-d",
                "refs/remotes/origin/gsd-path/M002",
            )
            collision_retry = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(collision_retry.returncode, 1)
            self.assertIn("refs/heads/gsd-path/M002 on origin", collision_retry.stderr)
            run_git(primary, "push", "origin", "--delete", "gsd-path/M002")

            (primary / "untracked.txt").write_text("dirty\n", encoding="utf-8")
            dirty_retry = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(dirty_retry.returncode, 1)
            self.assertIn("primary worktree is not clean", dirty_retry.stderr)

    def test_bind_next_retires_previous_branch_on_origin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            origin = Path(tmp) / "origin.git"
            default_checkout = Path(tmp) / "repo"
            primary = Path(tmp) / "repo-gsd-path"
            run_git(Path(tmp), "init", "--bare", "-b", "main", str(origin))
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
            run_git(default_checkout, "remote", "add", "origin", str(origin))
            run_git(default_checkout, "push", "origin", "main")
            run_git(primary, "push", "origin", "gsd-path/M001")

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
            run_git(
                origin,
                "update-ref",
                "refs/heads/gsd-path/M001",
                integrated_main,
            )
            moved = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(moved.returncode, 1)
            self.assertIn("origin/gsd-path/M001 moved after ship", moved.stderr)
            self.assertEqual(
                run_git(primary, "branch", "--show-current").stdout.strip(),
                "gsd-path/M001",
            )
            run_git(
                origin,
                "update-ref",
                "refs/heads/gsd-path/M001",
                m001_ship,
            )
            result = subprocess.run(bind_next, capture_output=True, text=True)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                run_git(primary, "branch", "--show-current").stdout.strip(),
                "gsd-path/M002",
            )
            for ref in (
                f"refs/heads/gsd-path/M001",
                f"refs/remotes/origin/gsd-path/M001",
            ):
                gone = subprocess.run(
                    ["git", "-C", str(primary), "show-ref", "--verify", "--quiet", ref],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(gone.returncode, 1, f"{ref} not retired")
            remote_gone = subprocess.run(
                ["git", "-C", str(origin), "show-ref", "--verify", "--quiet",
                 "refs/heads/gsd-path/M001"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(remote_gone.returncode, 1, "origin branch not retired")
            self.assertEqual(
                run_git(origin, "rev-parse", "refs/heads/main").stdout.strip(),
                integrated_main,
            )

            retry = subprocess.run(bind_next, capture_output=True, text=True)
            self.assertEqual(retry.returncode, 0, retry.stderr)


if __name__ == "__main__":
    unittest.main()
