import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import state_checkpoint
from scripts import archive_milestone, isolation, pipeline_state, pipeline_undo
from tests.test_task_briefs import PLAN_WAVE, TASK_TEMPLATE


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


def write_plan_tasks(repo: Path) -> None:
    tasks = repo / '.project/tasks'
    tasks.mkdir()
    (tasks / 'T001-change-app.md').write_text(TASK_TEMPLATE.format(
        task_id='T001', files_block='  - app.py', context='Create the demo app.',
        approach='Implement the demo behavior.', contract='- None', verify='python3 app.py'),
        encoding='utf-8')


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
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", expected_head)
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
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", parent)
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
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", expected_head)
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

    def test_checkpoint_recovery_rechecks_publication_before_reset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = init_repo(root)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", parent)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()

            with mock.patch.object(
                pipeline_undo,
                "_reset_to",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "checkpoint", approved)

            origin = root / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
            run_git(repo, "remote", "add", "origin", str(origin))
            run_git(repo, "push", "-u", "origin", "gsd-path/M001")

            with self.assertRaisesRegex(pipeline_undo.UndoError, "published"):
                pipeline_undo.apply_undo(repo, "checkpoint", approved)
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), approved)

    def test_checkpoint_recovery_rejects_a_different_branch_at_the_same_head(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", parent)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            with mock.patch.object(
                pipeline_undo,
                "_reset_to",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "checkpoint", approved)
            run_git(repo, "switch", "-c", "other")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("expected gsd-path/M001", previewed["target"]["blocked"][0])
            with self.assertRaisesRegex(
                pipeline_undo.UndoError, "expected gsd-path/M001"
            ):
                pipeline_undo.apply_undo(repo, "checkpoint", approved)
            self.assertEqual(run_git(repo, "rev-parse", "HEAD").stdout.strip(), approved)

    def test_checkpoint_recovery_preserves_new_worktree_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            project.mkdir()
            state = project / "STATE.md"
            state.write_text(state_text(), encoding="utf-8")
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: approval base")
            parent = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            (project / "plan").mkdir()
            (project / "plan" / "PLAN.md").write_text(
                PLAN_WAVE.format(title="first"), encoding="utf-8"
            )
            write_plan_tasks(repo)
            state_checkpoint.checkpoint_approval(repo, "plan", parent)
            approved = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            with mock.patch.object(
                pipeline_undo,
                "_reset_to",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "checkpoint", approved)
            state.write_text(
                state.read_text(encoding="utf-8") + "user edit\n",
                encoding="utf-8",
            )

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("unowned worktree changes", previewed["target"]["blocked"][0])
            with self.assertRaisesRegex(
                pipeline_undo.UndoError, "unowned worktree changes"
            ):
                pipeline_undo.apply_undo(repo, "checkpoint", approved)
            self.assertTrue(state.read_text(encoding="utf-8").endswith("user edit\n"))

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

    def test_uncommitted_archive_accepts_uncommitted_final_review_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"),
                encoding="utf-8",
            )
            (intent / "INTENT.md").write_text(
                "# Intent — first\n\n## Success criteria\n\n1. demo works\n",
                encoding="utf-8",
            )
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            archive = ".project/archive/001-first"
            archive_root = repo / archive
            archived_intent = archive_root / "intent"
            archived_intent.parent.mkdir(parents=True)
            intent.replace(archived_intent)
            review = archive_root / "review"
            review.mkdir()
            (review / "FINAL.md").write_text(
                f"""# Final Review — first

Reviewed HEAD: {head}
Overall verdict: pass

## Success criteria

### SC1 — demo works

- **Verdict**: met
- **Check**: `python -m unittest`
- **Observed**: focused tests passed
- **Reference**: tests
- **Finding**: none
- **Fix direction**: none
""",
                encoding="utf-8",
            )
            (review / "final-gap-1.md").write_text(
                f"""# Gap Review — 1: project Verify command

Reviewed HEAD: {head}
Gap verdict: pass
Risk: project Verify command
Waves checked: 1

## Checked evidence

- **Check**: `python -m unittest`
- **Observed**: focused project verification passed.
- **Reference**: `tests/test_pipeline_undo.py`

## Finding

- **Found**: The project Verify command passed at the reviewed HEAD.
- **Fix direction**: none
""",
                encoding="utf-8",
            )
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "uncommitted-archive")
            pipeline_undo.apply_undo(repo, "uncommitted-archive", head)

            self.assertTrue((intent / "INTENT.md").is_file())
            self.assertFalse(archive_root.exists())

    def test_uncommitted_archive_blocks_unowned_project_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            notes = project / "notes.md"
            notes.write_text("original\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"),
                encoding="utf-8",
            )
            (intent / "INTENT.md").write_text("# Intent — first\n", encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            archived_intent = repo / archive / "intent"
            archived_intent.mkdir(parents=True)
            (intent / "INTENT.md").replace(archived_intent / "INTENT.md")
            intent.rmdir()
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )
            notes.write_text("user edit\n", encoding="utf-8")
            unexpected = project / "plan" / "unexpected.md"
            unexpected.parent.mkdir()
            unexpected.write_text("user edit\n", encoding="utf-8")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("unowned", previewed["target"]["blocked"][0])
            self.assertEqual(notes.read_text(encoding="utf-8"), "user edit\n")
            self.assertEqual(unexpected.read_text(encoding="utf-8"), "user edit\n")

    def test_uncommitted_archive_blocks_unknown_archive_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"), encoding="utf-8"
            )
            (intent / "INTENT.md").write_text("# Intent — first\n", encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            archived_intent = repo / archive / "intent"
            archived_intent.mkdir(parents=True)
            (intent / "INTENT.md").replace(archived_intent / "INTENT.md")
            intent.rmdir()
            personal = repo / archive / "personal.md"
            personal.write_text("keep\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("inventory differs", previewed["target"]["blocked"][0])
            self.assertEqual(personal.read_text(encoding="utf-8"), "keep\n")

    def test_archive_recovery_rejects_new_archive_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            intent = project / "intent"
            intent.mkdir(parents=True)
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active"), encoding="utf-8"
            )
            (intent / "INTENT.md").write_text("# Intent — first\n", encoding="utf-8")
            run_git(repo, "add", ".project")
            run_git(repo, "commit", "-m", "fixture: ship active")
            archive = ".project/archive/001-first"
            archived_intent = repo / archive / "intent"
            archived_intent.mkdir(parents=True)
            (intent / "INTENT.md").replace(archived_intent / "INTENT.md")
            intent.rmdir()
            (project / "STATE.md").write_text(
                state_text(phase="ship", status="active", archive=f"{archive}/"),
                encoding="utf-8",
            )
            head = run_git(repo, "rev-parse", "HEAD").stdout.strip()
            with mock.patch.object(
                pipeline_undo,
                "_reset_to",
                side_effect=pipeline_undo.UndoError("interrupted"),
            ):
                with self.assertRaisesRegex(pipeline_undo.UndoError, "interrupted"):
                    pipeline_undo.apply_undo(repo, "uncommitted-archive", head)
            personal = repo / archive / "personal.md"
            personal.write_text("keep\n", encoding="utf-8")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("archive inventory drifted", previewed["target"]["blocked"][0])
            with self.assertRaisesRegex(
                pipeline_undo.UndoError, "archive inventory drifted"
            ):
                pipeline_undo.apply_undo(repo, "uncommitted-archive", head)
            self.assertEqual(personal.read_text(encoding="utf-8"), "keep\n")

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
            routed = pipeline_state.route_state(repo)
            self.assertEqual(routed["route"]["action"], "resume-undo")
            self.assertEqual(routed["route"]["kind"], "uncommitted-archive")
            self.assertEqual(routed["route"]["expected_head"], head)

            previewed = pipeline_undo.preview(repo)
            self.assertEqual(previewed["target"]["kind"], "uncommitted-archive")
            self.assertEqual(previewed["apply"]["expected_head"], head)

            pipeline_undo.apply_undo(
                repo,
                previewed["apply"]["kind"],
                previewed["apply"]["expected_head"],
            )

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

    def test_lookahead_discard_rejects_target_symlink(self) -> None:
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

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("real .project/next", previewed["target"]["blocked"][0])
            self.assertTrue((project / "next").is_symlink())
            self.assertEqual((intent / "INTENT.md").read_text(encoding="utf-8"), "keep\n")

    def test_lookahead_discard_rejects_arbitrary_notes_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            next_dir = project / "next"
            next_dir.mkdir(parents=True)
            notes = next_dir / "notes.md"
            notes.write_text("keep\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"), encoding="utf-8"
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: build")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("ownership is unproven", previewed["target"]["blocked"][0])
            self.assertEqual(notes.read_text(encoding="utf-8"), "keep\n")

    def test_lookahead_discard_rejects_unowned_track_descendants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = init_repo(Path(tmp))
            project = repo / ".project"
            next_dir = project / "next"
            plan = next_dir / "plan"
            plan.mkdir(parents=True)
            (next_dir / "STATE.md").write_text(
                state_text(phase="plan", status="active", branch="null"),
                encoding="utf-8",
            )
            (plan / "PLAN.md").write_text("# Plan — next\n", encoding="utf-8")
            personal = plan / "personal.md"
            personal.write_text("keep\n", encoding="utf-8")
            (project / "STATE.md").write_text(
                state_text(phase="build", status="active"),
                encoding="utf-8",
            )
            run_git(repo, "add", ".project/STATE.md")
            run_git(repo, "commit", "-m", "fixture: build")

            previewed = pipeline_undo.preview(repo)

            self.assertIsNone(previewed["target"]["kind"])
            self.assertIn("not owned by plan", previewed["target"]["blocked"][0])
            self.assertEqual(personal.read_text(encoding="utf-8"), "keep\n")

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
