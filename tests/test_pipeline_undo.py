import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import archive_milestone, isolation, pipeline_state, pipeline_undo


def run_git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def state_text(
    *,
    milestone: str = "first",
    phase: str = "plan",
    status: str = "active",
    branch: str = "gsd-path/M001",
    archive: str = "null",
) -> str:
    return (
        "---\n"
        "pipeline: gsd-path/v2\n"
        "project: demo\n"
        f"milestone: {milestone}\n"
        f"phase: {phase}\n"
        f"status: {status}\n"
        f"branch: {branch}\n"
        f"archive: {archive}\n"
        "---\n\n"
        "# Project State\n\n"
        "## Log\n\n"
        "- 2026-08-28 — fixture\n"
    )


def init_repo(root: Path, branch: str = "gsd-path/M001") -> Path:
    repo = root / "repo"
    run_git(Path(root), "init", "-b", branch, str(repo))
    run_git(repo, "config", "user.name", "GSD Path Test")
    run_git(repo, "config", "user.email", "test@example.com")
    return repo


def task_text() -> str:
    return (
        "---\n"
        "id: T001\n"
        "title: Change app\n"
        "wave: 1\n"
        "deps: []\n"
        "status: pending\n"
        "agent: null\n"
        "commit: null\n"
        "base: null\n"
        "worktree: null\n"
        "task_branch: null\n"
        "files:\n"
        "  - app.py\n"
        "---\n\n"
        "# T001 — Change app\n"
    )


def discussion_text(follow_up: str = "required") -> tuple[str, str]:
    next_owner = "ship" if follow_up == "required" else "none"
    target = ".project/plan/PLAN.md" if follow_up == "required" else "none"
    dialogue = archive_milestone.EMPTY_DISCUSSION_FILES["DIALOGUE.md"] + (
        "\n### D001 — 2026-08-28 — ship/active — Review\n\n"
        "- **Thread**: T001\n- **Reply to**: none\n- **User (verbatim)**:\n\n"
        "  > question\n\n- **Assistant**:\n\n  answer\n\n"
        "- **Evidence checked**: tests/test_pipeline_undo.py\n"
        "- **Research**: not needed — local behavior\n- **Thread status**: final\n"
    )
    answers = archive_milestone.EMPTY_DISCUSSION_FILES["ANSWERS.md"] + (
        "\n## Answer A001 — 2026-08-28 — Review\n\n"
        "- **Thread**: T001\n- **Turn**: D001\n- **Supersedes**: none\n"
        "- **Question**: question\n- **Status**: final\n"
        "- **Phase/status**: ship/active\n- **Conclusion**: answer\n"
        "- **Reasoning / pushback**: evidence supports the answer\n"
        "- **Evidence**: tests/test_pipeline_undo.py\n"
        "- **Research**: not needed — local behavior\n- **Confidence**: high\n"
        f"- **Unresolved**: none\n- **Next owner**: {next_owner}\n"
        f"- **Target artifact**: {target}\n"
        f"- **Follow-up**: {follow_up}\n"
    )
    return dialogue, answers


class PipelineUndoTests(unittest.TestCase):
    def test_preview_and_apply_plan_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            expected_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text("# Plan — first\n", encoding="utf-8")
            pipeline_state.checkpoint_approval(repo, "plan", expected_head)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            self.assertNotEqual(approved, expected_head)

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "checkpoint")
            self.assertEqual(previewed["target"]["head"], approved)

            applied = pipeline_undo.apply_undo(repo, "checkpoint", approved)
            self.assertEqual(applied["status"], "applied")
            self.assertEqual(
                run_git(repo, "rev-parse", "HEAD").stdout.strip(),
                expected_head,
            )
            state = pipeline_state.load_state(repo)[0]
            self.assertEqual((state.phase, state.status), ("plan", "active"))

    def test_checkpoint_undo_preserves_committed_discussion_extension(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            discussion = project / "discuss"
            discussion.mkdir(parents=True)
            for name, content in archive_milestone.EMPTY_DISCUSSION_FILES.items():
                (discussion / name).write_text(content, encoding="utf-8")
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: approval base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            dialogue, answers = discussion_text("none")
            (discussion / "DIALOGUE.md").write_text(dialogue, encoding="utf-8")
            (discussion / "ANSWERS.md").write_text(answers, encoding="utf-8")
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text("# Plan — first\n", encoding="utf-8")
            pipeline_state.checkpoint_approval(repo, "plan", parent)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()

            pipeline_undo.apply_undo(repo, "checkpoint", approved)

            self.assertEqual(
                (discussion / "ANSWERS.md").read_text(encoding="utf-8"), answers
            )
            self.assertIsNone(pipeline_undo.pending_transaction(repo))

    def test_apply_refuses_published_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = init_repo(root)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            expected_head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text("# Plan — first\n", encoding="utf-8")
            pipeline_state.checkpoint_approval(repo, "plan", expected_head)
            origin = root / "origin.git"
            subprocess.run(
                ["git", "init", "-q", "--bare", str(origin)],
                check=True,
            )
            run_git(repo, "remote", "add", "origin", str(origin))
            run_git(repo, "push", "-u", "origin", "gsd-path/M001")

            previewed = pipeline_undo.preview(repo)
            self.assertIsNone(previewed["target"]["kind"])
            self.assertTrue(
                any("force-pushes" in reason for reason in previewed["target"]["blocked"])
            )

    def test_apply_drops_unpublished_task_landing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"),
                encoding="utf-8",
            )
            (repo / "app.py").write_text("base = True\n", encoding="utf-8")
            task = project / "tasks" / "T001.md"
            task.parent.mkdir()
            task.write_text(task_text(), encoding="utf-8")
            run_git(repo, "add", ".")
            run_git(repo, "commit", "-m", "fixture: build base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (repo / "app.py").write_text("base = False\n", encoding="utf-8")
            task.write_text(
                task_text()
                .replace("status: pending", "status: in-progress")
                .replace("agent: null", "agent: coder")
                .replace("base: null", f"base: {parent}")
                .replace("worktree: null", f"worktree: {repo}"),
                encoding="utf-8",
            )
            head = isolation.land(
                repo,
                repo,
                parent,
                "T001",
                "Change app",
                ".project/tasks/T001.md",
                ["app.py"],
            )["commit"]

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "task")
            pipeline_undo.apply_undo(repo, "task", head)
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), parent)
            self.assertEqual((repo / "app.py").read_text(encoding="utf-8"), "base = True\n")

    def test_preview_rejects_spoofed_task_landing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: build base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (repo / "app.py").write_text("spoofed\n", encoding="utf-8")
            run_git(repo, "add", "app.py")
            run_git(
                repo,
                "commit",
                "-m",
                "T001: Change app",
                "-m",
                f"Task: .project/tasks/T001.md\nBase: {parent}\nFiles:\n- app.py",
            )

            previewed = pipeline_undo.preview(repo)
            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("unproven", previewed["target"]["blocked"][0])

    def test_uncommitted_archive_restores_tracked_project_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"),
                encoding="utf-8",
            )
            (intent / "INTENT.md").write_text("# Intent — first\n", encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            (project / "STATE.md").write_text(
                state_text(
                    phase="ship",
                    status="active",
                    archive=f"{archive}/",
                ),
                encoding="utf-8",
            )
            archived_intent = repo / archive / "intent"
            archived_intent.mkdir(parents=True)
            (intent / "INTENT.md").replace(archived_intent / "INTENT.md")
            intent.rmdir()

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "uncommitted-archive")
            head = previewed["target"]["head"]
            pipeline_undo.apply_undo(repo, "uncommitted-archive", head)
            self.assertTrue((intent / "INTENT.md").is_file())
            self.assertFalse((repo / archive).exists())
            state = pipeline_state.load_state(repo)[0]
            self.assertIsNone(state.archive)

    def test_uncommitted_archive_preserves_appended_discussion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            discussion = project / "discuss"
            discussion.mkdir(parents=True)
            dialogue = archive_milestone.EMPTY_DISCUSSION_FILES["DIALOGUE.md"]
            answers = archive_milestone.EMPTY_DISCUSSION_FILES["ANSWERS.md"]
            (discussion / "DIALOGUE.md").write_text(dialogue, encoding="utf-8")
            (discussion / "ANSWERS.md").write_text(answers, encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            archived = repo / archive / "discuss"
            archived.parent.mkdir(parents=True)
            discussion.replace(archived)
            discussion.mkdir()
            dialogue, answers = discussion_text()
            (discussion / "DIALOGUE.md").write_text(dialogue, encoding="utf-8")
            (discussion / "ANSWERS.md").write_text(answers, encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()

            pipeline_undo.apply_undo(repo, "uncommitted-archive", head)

            self.assertEqual(
                (discussion / "ANSWERS.md").read_text(encoding="utf-8"),
                answers,
            )
            self.assertFalse((repo / archive).exists())

    def test_archive_undo_resumes_from_durable_discussion_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            discussion = project / "discuss"
            discussion.mkdir(parents=True)
            for name, content in archive_milestone.EMPTY_DISCUSSION_FILES.items():
                (discussion / name).write_text(content, encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            archived = repo / archive / "discuss"
            archived.parent.mkdir(parents=True)
            discussion.replace(archived)
            discussion.mkdir()
            dialogue, answers = discussion_text()
            (discussion / "DIALOGUE.md").write_text(dialogue, encoding="utf-8")
            (discussion / "ANSWERS.md").write_text(answers, encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()

            with mock.patch.object(
                pipeline_undo,
                "_restore_discussion",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "uncommitted-archive", head)
            self.assertIsNotNone(pipeline_undo.pending_transaction(repo))

            pipeline_undo.apply_undo(repo, "uncommitted-archive", head)

            self.assertEqual(
                (discussion / "ANSWERS.md").read_text(encoding="utf-8"), answers
            )
            self.assertFalse((repo / archive).exists())
            self.assertIsNone(pipeline_undo.pending_transaction(repo))

    def test_build_archive_is_not_a_ship_archive_undo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            archive = ".project/archive/001-first"
            (project / "STATE.md").write_text(
                state_text(
                    phase="build",
                    status="active",
                    archive=f"{archive}/",
                ),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: abandon recovery")
            (repo / archive).mkdir(parents=True)
            (repo / archive / "partial.md").write_text("keep\n", encoding="utf-8")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertTrue((repo / archive / "partial.md").is_file())

    def test_lookahead_discard_removes_untracked_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: build")
            next_state = project / "next"
            next_state.mkdir()
            (next_state / "STATE.md").write_text(
                state_text(phase="inspect", status="active", branch="null"),
                encoding="utf-8",
            )

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "lookahead")
            pipeline_undo.apply_undo(
                repo, "lookahead", previewed["target"]["head"]
            )
            self.assertFalse(next_state.exists())

    def test_lookahead_discard_unlinks_target_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            (intent / "INTENT.md").write_text("keep\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: build")
            (project / "next").symlink_to(intent, target_is_directory=True)

            previewed = pipeline_undo.preview(repo)
            pipeline_undo.apply_undo(repo, "lookahead", previewed["target"]["head"])

            self.assertFalse((project / "next").exists())
            self.assertEqual((intent / "INTENT.md").read_text(encoding="utf-8"), "keep\n")

    def test_cli_preview_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: build")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "scripts" / "pipeline_undo.py"),
                    "preview",
                    "--repo",
                    str(repo),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["schema"], pipeline_undo.UNDO_SCHEMA)
            self.assertEqual(payload["status"], "preview")


if __name__ == "__main__":
    unittest.main()
