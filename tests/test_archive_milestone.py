import json
import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from scripts import archive_milestone, isolation, pipeline_git, review_panel

if sys.platform != "win32":
    import fcntl


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_SCRIPT = PROJECT_ROOT / "scripts" / "archive_milestone.py"
GIT_GUARD_SCRIPT = PROJECT_ROOT / "scripts" / "git_guard.py"


class ArchiveMilestoneTests(unittest.TestCase):
    def run_command(self, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    def git(self, repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return self.run_command("git", *args, cwd=repo)

    def make_repo(self, root: Path, branch: str = "gsd-path/M001") -> None:
        self.git(root, "init", "-q", "-b", branch)
        self.git(root, "config", "user.name", "Validation")
        self.git(root, "config", "user.email", "validation@example.invalid")

        project = root / ".project"
        for directory in ("intent", "research", "plan", "tasks", "review"):
            (project / directory).mkdir(parents=True, exist_ok=True)

        (project / "STATE.md").write_text(
            f"""---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: ship
status: active
branch: {branch}
archive: null
---

# Project State

## Log
- 2026-08-01 — ship — final review passed
"""
        )
        (project / "intent" / "INTENT.md").write_text(
            "# Intent\n\n## Success criteria\n\n1. demo works\n"
        )
        for evidence in ("domain", "stack", "pitfalls", "similar"):
            (project / "research" / f"evidence-{evidence}.md").write_text("# Evidence\n")
        (project / "research" / "SYNTHESIS.md").write_text("# Synthesis\n")
        (project / "research" / "DOCS-AUDIT.md").write_text(
            """# Docs Audit

## User rulings

| Queue # | Ruling | User's words | Planned |
|---------|--------|--------------|---------|
| 1 | fix-doc | "keep this queued" | no |
"""
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
"""
        )
        (root / "src").mkdir()
        product = root / "src" / "demo.py"
        product.write_text("value = 'before'\n", encoding="utf-8")
        task = project / "tasks" / "T001-demo.md"
        task.write_text(
            """---
id: T001
title: demo
wave: 1
deps: []
status: pending
agent: null
base: null
worktree: null
task_branch: null
files: [src/demo.py]
---

# T001 — demo

## Intent coverage

- SC1

## Log

- created
""",
            encoding="utf-8",
        )
        (project / "review" / "FINAL.md").write_text("Overall verdict: pass\n")
        (project / "review" / "wave-1.cycle1.md").write_text(
            """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — focused Verify passed

## Intent coverage

### SC1 — demo works: pass

- ✅ focused Verify passed in tests
"""
        )

        self.git(root, "add", ".project", "src/demo.py")
        baseline = self.git(root, "commit", "-q", "-m", "baseline")
        self.assertEqual(baseline.returncode, 0, baseline.stderr)
        base = self.git(root, "rev-parse", "HEAD").stdout.strip()
        task.write_text(
            task.read_text(encoding="utf-8")
            .replace("status: pending", "status: in-progress")
            .replace("agent: null", "agent: builder")
            .replace("base: null", f"base: {base}")
            .replace("worktree: null", f"worktree: {root}"),
            encoding="utf-8",
        )
        task.write_text(
            isolation._landed_task_text(
                task.read_text(encoding="utf-8") + "- implementation complete\n",
                base,
            ),
            encoding="utf-8",
        )
        product.write_text("value = 'implemented'\n", encoding="utf-8")
        task_file = ".project/tasks/T001-demo.md"
        changed_paths = [task_file, "src/demo.py"]
        self.git(root, "add", *changed_paths)
        landed = self.git(
            root,
            "commit",
            "-q",
            "-m",
            pipeline_git.task_commit_subject("T001", "demo"),
            "-m",
            pipeline_git.task_commit_body(task_file, changed_paths, base),
        )
        self.assertEqual(landed.returncode, 0, landed.stderr)
        reviewed_head = self.git(root, "rev-parse", "HEAD").stdout.strip()
        (project / "review" / "FINAL.md").write_text(
            f"""# Final Review — demo

Reviewed HEAD: {reviewed_head}
Overall verdict: pass

## Success criteria

### SC1 — demo works

- **Verdict**: met
- **Check**: `python -m unittest`
- **Observed**: focused tests passed
- **Reference**: tests
- **Finding**: none
- **Fix direction**: none
"""
        )
        (project / "review" / "final-gap-1.md").write_text(
            f"""# Gap Review — 1: project Verify command

Reviewed HEAD: {reviewed_head}
Gap verdict: pass
Risk: project Verify command
Waves checked: 1

## Checked evidence

- **Check**: `python -m unittest`
- **Observed**: focused project verification passed.
- **Reference**: `tests/test_archive_milestone.py`

## Finding

- **Found**: The project Verify command passed at the reviewed HEAD.
- **Fix direction**: none
"""
        )

    def write_manifest(self, archive: Path) -> None:
        contents = sorted(
            path.relative_to(archive).as_posix()
            for path in archive.rglob("*")
            if path.is_file() and path.name != "MANIFEST.md"
        )
        listed_contents = "\n".join(f"- {path}" for path in contents)
        (archive / "MANIFEST.md").write_text(
            f"""# Archive — {archive.name}

Milestone: demo
Shipped: 2026-08-01
Final verdict: all criteria met; project verify passed
Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1
Carried forward: 1 DOCS-AUDIT ruling(s)

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| demo works | met | tests |

## Contents

{listed_contents}

## Notes

- none
"""
        )

    def write_panel_skip_receipt(self, path: Path) -> None:
        payload = review_panel.resolve_panel(
            {"mode": "detected", "families": ()},
            (),
        )
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def write_discussion(
        self, directory: Path, turn: int = 1, final: bool = True,
        phase_status: str = "ship/active",
    ) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        dialogue_turns = []
        answer_records = []
        for number in range(1, turn + 1):
            previous = f"D{number - 1:03d}" if number > 1 else "none"
            supersedes = f"A{number - 1:03d}" if number > 1 else "none"
            status = "final" if final and number == turn else "working"
            dialogue_turns.append(
                f"""### D{number:03d} — 2026-08-01 — {phase_status} — demo

- **Thread**: T001
- **Reply to**: {previous}
- **User (verbatim)**:

  > question {number}

- **Assistant**:

  answer {number}

- **Evidence checked**: tests/test_archive_milestone.py
- **Research**: not needed — local behavior
- **Thread status**: {status}
"""
            )
            answer_records.append(
                f"""## Answer A{number:03d} — 2026-08-01 — demo

- **Thread**: T001
- **Turn**: D{number:03d}
- **Supersedes**: {supersedes}
- **Question**: question {number}
- **Status**: {status}
- **Phase/status**: {phase_status}
- **Conclusion**: answer {number}
- **Reasoning / pushback**: evidence supports the answer
- **Evidence**: tests/test_archive_milestone.py
- **Research**: not needed — local behavior
- **Confidence**: high
- **Unresolved**: none
- **Next owner**: none
- **Target artifact**: none
- **Follow-up**: none
"""
            )

        (directory / "DIALOGUE.md").write_text(
            "# GSD Path Discussion — Dialogue\n\n## Turns\n\n"
            + "\n".join(dialogue_turns)
        )
        (directory / "ANSWERS.md").write_text(
            "# GSD Path Discussion — Answers\n\n" + "\n".join(answer_records)
        )

    def prepare_archive(self, repo: Path, slug: str = "demo") -> Path:
        prepare = self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "prepare",
            "--repo",
            str(repo),
            "--slug",
            slug,
            cwd=PROJECT_ROOT,
        )
        self.assertEqual(prepare.returncode, 0, prepare.stderr)
        return repo / json.loads(prepare.stdout)["archive"]

    def preflight(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "preflight",
            "--repo",
            str(repo),
            cwd=PROJECT_ROOT,
        )

    def render_manifest(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "render-manifest",
            "--repo",
            str(repo),
            cwd=PROJECT_ROOT,
        )

    def mark_shipped(self, repo: Path) -> None:
        state_path = repo / ".project" / "STATE.md"
        state = state_path.read_text().replace("phase: ship", "phase: shipped")
        state_path.write_text(state.replace("status: active", "status: done"))

    def commit_ship(
        self,
        repo: Path,
        archive: Path,
        *,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        allow_empty: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        arguments = ["commit", "-q"]
        if allow_empty:
            arguments.append("--allow-empty")
        arguments.extend(
            (
                "-m",
                subject or pipeline_git.ship_subject(archive.name),
                "-m",
                body
                or pipeline_git.ship_commit_body(
                    archive.relative_to(repo).as_posix(), reviewed_head
                ),
            )
        )
        return self.git(repo, *arguments)

    def snapshot_worktree(self, repo: Path) -> dict:
        snapshot = {}
        for path in sorted(repo.rglob("*")):
            relative = path.relative_to(repo)
            if relative.parts[0] == ".git":
                continue
            if path.is_symlink():
                snapshot[relative.as_posix()] = ("symlink", os.readlink(path))
            elif path.is_dir():
                snapshot[relative.as_posix()] = ("directory", None)
            else:
                snapshot[relative.as_posix()] = ("file", path.read_bytes())
        return snapshot

    def test_prepare_is_idempotent_and_validate_requires_ship_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            result = json.loads(prepare.stdout)
            self.assertEqual(result["archive"], ".project/archive/001-demo")
            self.assertEqual(result["carried_forward"], 1)

            archive = repo / result["archive"]
            self.assertTrue((archive / "intent" / "INTENT.md").is_file())
            self.assertTrue((archive / "research" / "DOCS-AUDIT.md").is_file())
            self.assertTrue((repo / ".project" / "research" / "DOCS-AUDIT.md").is_file())

            retry = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)["archive"], result["archive"])
            archive_directories = sorted((repo / ".project" / "archive").iterdir())
            self.assertEqual([path.name for path in archive_directories], ["001-demo"])

            state_path = repo / ".project" / "STATE.md"
            state = state_path.read_text().replace("phase: ship", "phase: shipped")
            state = state.replace("status: active", "status: done")
            state_path.write_text(state)
            self.write_manifest(archive)

            before_commit = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(before_commit.returncode, 0)

            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            after_commit = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(after_commit.returncode, 0, after_commit.stderr)
            self.assertEqual(json.loads(after_commit.stdout)["archive"], result["archive"])

    def test_prepare_rejects_branch_archive_sequence_mismatch_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            switched = self.git(repo, "switch", "-q", "-c", "gsd-path/M002")
            self.assertEqual(switched.returncode, 0, switched.stderr)
            state = repo / ".project" / "STATE.md"
            state.write_text(
                state.read_text().replace("branch: gsd-path/M001", "branch: gsd-path/M002")
            )
            before = self.snapshot_worktree(repo)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("archive sequence", prepare.stderr)
            self.assertEqual(self.snapshot_worktree(repo), before)

    def test_prepare_rejects_m000_bound_branch_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo, branch="gsd-path/M000")
            before = self.snapshot_worktree(repo)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("STATE.md is invalid", prepare.stderr)
            self.assertEqual(self.snapshot_worktree(repo), before)

    def test_prepare_rejects_existing_archive_zero_without_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            (repo / ".project" / "archive" / "000-legacy").mkdir(parents=True)
            before = self.snapshot_worktree(repo)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("archive milestone number must be >= 1", prepare.stderr)
            self.assertEqual(self.snapshot_worktree(repo), before)

    def test_render_manifest_replaces_stale_content_with_derived_values(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            final = repo / ".project" / "review" / "FINAL.md"
            final.write_text(final.read_text().replace("tests", "tests | smoke"))
            archive = self.prepare_archive(repo)
            manifest = archive / "MANIFEST.md"
            manifest.write_text("stale\n")

            rendered = self.render_manifest(repo)

            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertEqual(json.loads(rendered.stdout)["archive"], ".project/archive/001-demo")
            content = manifest.read_text()
            self.assertIn("# Archive — 001-demo", content)
            self.assertRegex(content, r"(?m)^Shipped: \d{4}-\d{2}-\d{2}$")
            self.assertIn("Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1", content)
            self.assertIn("| demo works | met | tests \\| smoke |", content)
            self.assertIn("Carried forward: 1 DOCS-AUDIT ruling(s)", content)
            self.assertFalse((archive / ".MANIFEST.md.gsd-path-tmp").exists())
            checked = self.preflight(repo)
            self.assertEqual(checked.returncode, 0, checked.stderr)

    def test_render_manifest_rejects_a_task_not_recorded_done(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            task = archive / "tasks" / "T001-demo.md"
            task.write_text(
                task.read_text(encoding="utf-8").replace(
                    "status: done", "status: in-progress"
                ),
                encoding="utf-8",
            )

            rendered = self.render_manifest(repo)

            self.assertNotEqual(rendered.returncode, 0)
            self.assertIn("status: done", rendered.stderr)
            self.assertFalse((archive / "MANIFEST.md").exists())

    def test_render_manifest_rejects_a_final_criterion_renamed_from_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            final = archive / "review" / "FINAL.md"
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "### SC1 — demo works", "### SC1 — an easier demo starts"
                ),
                encoding="utf-8",
            )

            rendered = self.render_manifest(repo)

            self.assertNotEqual(rendered.returncode, 0)
            self.assertIn("heading text differs", rendered.stderr)
            self.assertFalse((archive / "MANIFEST.md").exists())

    def test_render_manifest_ignores_an_unrelated_commit_off_first_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            landed = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            tree = self.git(repo, "rev-parse", "HEAD^{tree}").stdout.strip()
            side = self.git(
                repo,
                "commit-tree",
                tree,
                "-p",
                landed,
                "-m",
                "side task",
            ).stdout.strip()
            merge = self.git(repo, "merge", "--no-ff", "-q", "-m", "merge side", side)
            self.assertEqual(merge.returncode, 0, merge.stderr)
            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()

            for name in ("FINAL.md", "final-gap-1.md"):
                review = repo / ".project" / "review" / name
                review.write_text(
                    review.read_text(encoding="utf-8").replace(
                        landed, reviewed_head
                    ),
                    encoding="utf-8",
                )
            archive = self.prepare_archive(repo)

            rendered = self.render_manifest(repo)

            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertTrue((archive / "MANIFEST.md").exists())

    def test_preflight_rejects_a_task_commit_with_noncanonical_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            previous = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            task = repo / ".project" / "tasks" / "T001-demo.md"
            task.write_text(
                task.read_text(encoding="utf-8") + "\n- malformed landing\n",
                encoding="utf-8",
            )
            self.git(repo, "add", ".project/tasks/T001-demo.md")
            committed = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                pipeline_git.task_commit_subject("T001", "demo"),
                "-m",
                "not the canonical task body",
            )
            self.assertEqual(committed.returncode, 0, committed.stderr)
            malformed = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            for name in ("FINAL.md", "final-gap-1.md"):
                review = repo / ".project" / "review" / name
                review.write_text(
                    review.read_text(encoding="utf-8").replace(previous, malformed),
                    encoding="utf-8",
                )
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("body has no Base: field", preflight.stderr)

    def test_prepare_archives_optional_discussion_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            expected_dialogue = (discussion / "DIALOGUE.md").read_text()

            archive = self.prepare_archive(repo)

            self.assertFalse(discussion.exists())
            self.assertEqual(
                (archive / "discuss" / "DIALOGUE.md").read_text(),
                expected_dialogue,
            )
            self.assertIn("## Answer A001", (archive / "discuss" / "ANSWERS.md").read_text())
            self.write_manifest(archive)
            preflight = self.preflight(repo)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)

            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)
            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)

    def test_prepare_accepts_canonical_empty_discussion_records(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            discussion.mkdir()
            dialogue_template = (
                PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "dialogue.md"
            ).read_text()
            answers_template = (
                PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "answers.md"
            ).read_text()
            (discussion / "DIALOGUE.md").write_text(
                dialogue_template.split("\n### D001", 1)[0].rstrip() + "\n"
            )
            (discussion / "ANSWERS.md").write_text(
                answers_template.split("\n## Answer A001", 1)[0].rstrip() + "\n"
            )

            archive = self.prepare_archive(repo)

            self.assertFalse(discussion.exists())
            self.assertEqual(
                (archive / "discuss" / "DIALOGUE.md").read_text(),
                dialogue_template.split("\n### D001", 1)[0].rstrip() + "\n",
            )

    @unittest.skipIf(sys.platform == "win32", "POSIX lock contention check")
    def test_prepare_holds_discussion_lock_while_reconciling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            original = archive_milestone.reconcile_append_only_discussion

            def assert_locked(active_root, archive):
                descriptor = os.open(active_root, os.O_RDONLY)
                try:
                    with self.assertRaises(BlockingIOError):
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                finally:
                    os.close(descriptor)
                return original(active_root, archive)

            with mock.patch.object(
                archive_milestone,
                "reconcile_append_only_discussion",
                side_effect=assert_locked,
            ):
                result = archive_milestone.prepare(repo, "demo")

            self.assertEqual(result["archive"], ".project/archive/001-demo")

    def test_discussion_lock_uses_windows_locking_without_fcntl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            program = textwrap.dedent(
                f"""
                # Import the script's platform-sensitive standard library
                # modules before faking sys.platform: shutil imports _winapi
                # on "win32", which does not exist on POSIX interpreters.
                import argparse
                import filecmp
                import json
                import runpy
                import shutil
                import subprocess
                import sys
                import types
                from pathlib import Path

                calls = []
                locking = types.ModuleType("msvcrt")
                locking.LK_LOCK = 1
                locking.LK_UNLCK = 2
                locking.locking = lambda descriptor, mode, size: calls.append(mode)
                sys.modules["fcntl"] = None
                sys.modules["msvcrt"] = locking
                sys.platform = "win32"
                module = runpy.run_path({str(ARCHIVE_SCRIPT)!r}, run_name="archive_portability")
                with module["discussion_lock"](Path({str(repo / ".project")!r})):
                    calls.append("inside")
                print(json.dumps(calls))
                """
            )

            result = self.run_command(
                sys.executable,
                "-c",
                program,
                cwd=PROJECT_ROOT,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout), [1, "inside", 2])

    def test_prepare_reconciles_append_only_discussion_after_archive_started(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion, final=False)

            archive = self.prepare_archive(repo)
            self.write_discussion(discussion, turn=2)

            resumed = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertFalse(discussion.exists())
            self.assertIn("### D002", (archive / "discuss" / "DIALOGUE.md").read_text())
            self.assertIn("## Answer A002", (archive / "discuss" / "ANSWERS.md").read_text())

    def test_prepare_rejects_incomplete_discussion_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            (discussion / "ANSWERS.md").unlink()

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("discussion archive", prepare.stderr)

    def test_prepare_rejects_empty_dialogue_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            dialogue = discussion / "DIALOGUE.md"
            dialogue.write_text(
                dialogue.read_text().replace("  > question 1", "  >   "),
                encoding="utf-8",
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("verbatim user block", prepare.stderr)

    def test_prepare_accepts_markdown_headings_inside_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            dialogue = discussion / "DIALOGUE.md"
            dialogue.write_text(
                dialogue.read_text().replace(
                    "  answer 1",
                    "- **Decision:** keep it\n\n### Result\n\nanswer 1",
                ),
                encoding="utf-8",
            )

            archive = self.prepare_archive(repo)

            self.assertIn(
                "### Result", (archive / "discuss" / "DIALOGUE.md").read_text()
            )

    def test_prepare_rejects_cross_thread_reply_and_supersession(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion, turn=2)
            for name in ("DIALOGUE.md", "ANSWERS.md"):
                path = discussion / name
                content = path.read_text()
                marker = "### D002" if name == "DIALOGUE.md" else "## Answer A002"
                before, after = content.split(marker, 1)
                path.write_text(before + marker + after.replace("T001", "T002", 1))

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("same thread", prepare.stderr)

    def test_prepare_rejects_required_follow_up_without_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            answers = discussion / "ANSWERS.md"
            answers.write_text(
                answers.read_text()
                .replace("- **Next owner**: none", "- **Next owner**: gsd-path-ship")
                .replace(
                    "- **Target artifact**: none",
                    "- **Target artifact**: .project/review/FINAL.md",
                )
                .replace("- **Follow-up**: none", "- **Follow-up**: required")
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("disposition", prepare.stderr)

    def test_prepare_rejects_disposition_from_wrong_owner_or_artifact(self) -> None:
        cases = (
            ("gsd-path-ship", ".project/plan/PLAN.md", "owner"),
            ("gsd-path-plan", ".project/review/FINAL.md", "artifact"),
        )
        for owner, artifact, expected_error in cases:
            with self.subTest(expected_error=expected_error):
                with tempfile.TemporaryDirectory() as temporary_directory:
                    repo = Path(temporary_directory)
                    self.make_repo(repo)
                    discussion = repo / ".project" / "discuss"
                    self.write_discussion(discussion)
                    answers = discussion / "ANSWERS.md"
                    content = (
                        answers.read_text()
                        .replace(
                            "- **Next owner**: none",
                            "- **Next owner**: gsd-path-plan",
                        )
                        .replace(
                            "- **Target artifact**: none",
                            "- **Target artifact**: .project/plan/PLAN.md",
                        )
                        .replace(
                            "- **Follow-up**: none", "- **Follow-up**: required"
                        )
                    )
                    answers.write_text(
                        content
                        + f"""

## Disposition X001 — 2026-08-01

- **Answer**: A001
- **Status**: applied
- **Owner**: {owner}
- **Artifact**: {artifact}
- **Evidence**: unrelated review change
"""
                    )

                    prepare = self.run_command(
                        sys.executable,
                        str(ARCHIVE_SCRIPT),
                        "prepare",
                        "--repo",
                        str(repo),
                        "--slug",
                        "demo",
                        cwd=PROJECT_ROOT,
                    )

                    self.assertNotEqual(prepare.returncode, 0)
                    self.assertIn(expected_error, prepare.stderr)

    def test_prepare_rejects_unknown_discussion_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            for name in ("DIALOGUE.md", "ANSWERS.md"):
                path = discussion / name
                path.write_text(path.read_text().replace("ship/active", "bogus/active"))

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("phase", prepare.stderr.lower())

    def test_prepare_recovers_half_written_discussion_reconciliation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion, final=False)
            archive = self.prepare_archive(repo)
            self.write_discussion(discussion, turn=2)
            original_replace = archive_milestone.os.replace

            def fail_answer_replace(source, destination):
                if Path(destination).name == "ANSWERS.md":
                    raise OSError("injected second-copy failure")
                return original_replace(source, destination)

            with mock.patch.object(
                archive_milestone.os, "replace", side_effect=fail_answer_replace
            ):
                with self.assertRaises(OSError):
                    archive_milestone.reconcile_append_only_discussion(
                        repo / ".project", archive
                    )

            resumed = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertEqual(resumed.returncode, 0, resumed.stderr)
            self.assertFalse(discussion.exists())
            self.assertIn("Answer A002", (archive / "discuss" / "ANSWERS.md").read_text())

    def test_discussion_recovery_rejects_symlinked_archive_destination(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            archive = self.prepare_archive(repo)
            self.write_discussion(discussion, turn=2)
            outside = repo / "outside-discuss"
            self.write_discussion(outside)
            before = {
                name: (outside / name).read_bytes()
                for name in archive_milestone.DISCUSSION_FILES
            }
            shutil.rmtree(archive / "discuss")
            (archive / "discuss").symlink_to(outside, target_is_directory=True)
            payload = {
                "schema": "gsd-path/discussion-archive/v1",
                "archive": str(archive.resolve()),
                "files": {
                    name: (discussion / name).read_text()
                    for name in archive_milestone.DISCUSSION_FILES
                },
            }
            (repo / ".project" / archive_milestone.DISCUSSION_TRANSACTION_NAME).write_text(
                json.dumps(payload) + "\n"
            )

            with self.assertRaises(archive_milestone.ArchiveError):
                archive_milestone.finish_discussion_reconciliation(
                    repo / ".project", archive
                )

            self.assertEqual(
                {
                    name: (outside / name).read_bytes()
                    for name in archive_milestone.DISCUSSION_FILES
                },
                before,
            )

    def test_discussion_recovery_does_not_follow_temporary_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            discussion = repo / ".project" / "discuss"
            self.write_discussion(discussion)
            archive = self.prepare_archive(repo)
            self.write_discussion(discussion, turn=2)
            payload = {
                "schema": "gsd-path/discussion-archive/v1",
                "archive": str(archive.resolve()),
                "files": {
                    name: (discussion / name).read_text()
                    for name in archive_milestone.DISCUSSION_FILES
                },
            }
            (repo / ".project" / archive_milestone.DISCUSSION_TRANSACTION_NAME).write_text(
                json.dumps(payload) + "\n"
            )
            outside = repo / "outside-record.md"
            outside.write_text("outside sentinel\n")
            temporary = archive / "discuss" / ".DIALOGUE.md.gsd-path-tmp"
            temporary.symlink_to(outside)

            archive_milestone.finish_discussion_reconciliation(
                repo / ".project", archive
            )

            self.assertEqual(outside.read_text(), "outside sentinel\n")
            self.assertFalse((archive / "discuss" / "DIALOGUE.md").is_symlink())
            self.assertIn(
                "### D002", (archive / "discuss" / "DIALOGUE.md").read_text()
            )

    def test_ship_accepts_active_lessons_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            (repo / ".project" / "LESSONS.md").write_text(
                "# Lessons\n\n- 001-demo — verify commands must fail on skipped work\n"
            )
            self.mark_shipped(repo)
            self.write_manifest(archive)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            self.assertFalse((archive / "LESSONS.md").exists())

    def test_validate_rejects_duplicate_canonical_ship_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            first = self.commit_ship(repo, archive)
            self.assertEqual(first.returncode, 0, first.stderr)
            duplicate = self.commit_ship(repo, archive, allow_empty=True)
            self.assertEqual(duplicate.returncode, 0, duplicate.stderr)

            result = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("multiple commits", result.stderr)

    def test_ship_accepts_persistent_program_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            (repo / ".project" / "CHARTER.md").write_text("# Charter\n")
            (repo / ".project" / "ROADMAP.md").write_text(
                "# Roadmap\n\n### M001 — demo\n\nStatus: shipped\nArchive: .project/archive/001-demo\n"
            )
            (repo / ".project" / "SYNTHESIS.md").write_text(
                "# Synthesis\n\n## Settled\n\n- program decision\n"
            )
            self.mark_shipped(repo)
            self.write_manifest(archive)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)
            for persistent in ("CHARTER.md", "ROADMAP.md", "SYNTHESIS.md"):
                self.assertTrue((repo / ".project" / persistent).is_file())
                self.assertFalse((archive / persistent).exists())

    def test_validate_rejects_missing_unchanged_or_wrong_program_roadmap(self) -> None:
        for case in ("missing", "unchanged", "wrong"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                project = repo / ".project"
                (project / "CHARTER.md").write_text("# Charter\n")
                if case == "unchanged":
                    (project / "ROADMAP.md").write_text("# Roadmap\n\n### M001 — demo\n\nStatus: shipped\nArchive: .project/archive/001-demo\n")
                    self.git(repo, "add", ".project/CHARTER.md", ".project/ROADMAP.md")
                    self.git(repo, "commit", "-q", "-m", "program metadata")
                archive = self.prepare_archive(repo)
                if case != "missing" and not (project / "ROADMAP.md").exists():
                    pointer = ".project/archive/999-wrong" if case == "wrong" else ".project/archive/001-demo"
                    (project / "ROADMAP.md").write_text(f"# Roadmap\n\n### M001 — demo\n\nStatus: shipped\nArchive: {pointer}\n")
                self.mark_shipped(repo)
                self.write_manifest(archive)
                self.git(repo, "add", ".project")
                ship = self.commit_ship(repo, archive)
                self.assertEqual(ship.returncode, 0, ship.stderr)

                validate = self.run_command(sys.executable, str(ARCHIVE_SCRIPT), "validate", "--repo", str(repo), cwd=PROJECT_ROOT)

                self.assertNotEqual(validate.returncode, 0)
                self.assertIn("ROADMAP", validate.stderr)

    def test_preflight_accepts_persistent_repository_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            (repo / ".project" / "REPOSITORY.md").write_text(
                "# Repository Binding\n\nKind: new-github\n"
            )

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)

            self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def test_prepare_recovers_an_interrupted_carry_forward_copy(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)

            active_research = repo / ".project" / "research"
            (active_research / "DOCS-AUDIT.md").unlink()
            (active_research / ".DOCS-AUDIT.md.gsd-path-tmp").write_text("partial\n")

            retry = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertTrue((active_research / "DOCS-AUDIT.md").is_file())
            self.assertFalse((active_research / ".DOCS-AUDIT.md.gsd-path-tmp").exists())

    def test_prepare_rejects_an_incomplete_active_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            (repo / ".project" / "plan" / "PLAN.md").unlink()
            (repo / ".project" / "plan").rmdir()

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("missing both active and archived plan", prepare.stderr)

    def test_prepare_rejects_state_owned_by_another_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace("pipeline: gsd-path/v2", "pipeline: legacy/v1")
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("pipeline must be gsd-path/v2", prepare.stderr)

    def test_prepare_rejects_wrong_phase_without_moving_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(state_path.read_text().replace("phase: ship", "phase: build"))

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("phase", prepare.stderr)
            self.assertTrue((repo / ".project" / "intent" / "INTENT.md").is_file())

    def test_prepare_rejects_symlinked_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "repo"
            repo.mkdir()
            self.make_repo(repo)
            outside = root / "outside"
            outside.mkdir()
            (repo / ".project" / "archive").symlink_to(outside, target_is_directory=True)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("symlink", prepare.stderr)
            self.assertTrue((repo / ".project" / "intent" / "INTENT.md").is_file())
            self.assertFalse(list(outside.iterdir()))

    def test_validate_rejects_product_code_in_ship_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            archive = repo / json.loads(prepare.stdout)["archive"]

            state_path = repo / ".project" / "STATE.md"
            state = state_path.read_text().replace("phase: ship", "phase: shipped")
            state_path.write_text(state.replace("status: active", "status: done"))
            self.write_manifest(archive)
            (repo / "product.txt").write_text("must not ship in the archive commit\n")
            self.git(repo, "add", ".project", "product.txt")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("outside .project", validate.stderr)

    def test_validate_rejects_an_incomplete_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            archive = repo / json.loads(prepare.stdout)["archive"]

            state_path = repo / ".project" / "STATE.md"
            state = state_path.read_text().replace("phase: ship", "phase: shipped")
            state_path.write_text(state.replace("status: active", "status: done"))
            (archive / "MANIFEST.md").write_text("# Archive — 001-demo\n")
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("manifest", validate.stderr.lower())

    def test_preflight_rejects_missing_canonical_artifact_and_extra_active_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            archive = repo / json.loads(prepare.stdout)["archive"]
            (archive / "intent" / "INTENT.md").unlink()
            self.write_manifest(archive)
            (repo / ".project" / "EXTRA.md").write_text("unexpected\n")

            preflight = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "preflight",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("canonical", preflight.stderr)

            (archive / "intent" / "INTENT.md").write_text(
                "# Intent\n\n## Success criteria\n\n1. demo works\n"
            )
            self.write_manifest(archive)
            extra_only = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "preflight",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(extra_only.returncode, 0)
            self.assertIn("unexpected active", extra_only.stderr)

    def test_preflight_validates_manifest_metadata_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            archive = repo / json.loads(prepare.stdout)["archive"]
            self.write_manifest(archive)

            valid = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "preflight",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(valid.returncode, 0, valid.stderr)

            manifest = archive / "MANIFEST.md"
            manifest.write_text(manifest.read_text().replace("Milestone: demo", "Milestone: wrong"))
            invalid = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "preflight",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(invalid.returncode, 0)
            self.assertIn("milestone", invalid.stderr.lower())

    def test_validate_rejects_mutation_of_an_older_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo, branch="gsd-path/M002")
            older = repo / ".project" / "archive" / "001-older" / "locked.md"
            older.parent.mkdir(parents=True)
            older.write_text("read only\n")
            self.git(repo, "add", str(older.relative_to(repo)))
            prior = self.git(repo, "commit", "-q", "-m", "older archive")
            self.assertEqual(prior.returncode, 0, prior.stderr)

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(prepare.returncode, 0, prepare.stderr)
            archive = repo / json.loads(prepare.stdout)["archive"]
            state_path = repo / ".project" / "STATE.md"
            state = state_path.read_text().replace("phase: ship", "phase: shipped")
            state_path.write_text(state.replace("status: active", "status: done"))
            self.write_manifest(archive)
            older.write_text("mutated during ship\n")
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("older archive", validate.stderr)

    def test_validate_requires_a_single_parent_ship_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.git(repo, "commit", "-q", "-m", "stage archive transaction")
            self.assertEqual(ship.returncode, 0, ship.stderr)

            baseline = self.git(repo, "rev-parse", "HEAD^").stdout.strip()
            tree = self.git(repo, "rev-parse", f"{baseline}^{{tree}}").stdout.strip()
            side = self.git(repo, "commit-tree", tree, "-p", baseline, "-m", "side").stdout.strip()
            merge = self.git(
                repo,
                "merge",
                "--no-ff",
                "-q",
                "-m",
                pipeline_git.ship_subject(archive.name),
                "-m",
                pipeline_git.ship_commit_body(
                    archive.relative_to(repo).as_posix(), baseline
                ),
                side,
            )
            self.assertEqual(merge.returncode, 0, merge.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("exactly one parent", validate.stderr)

    def test_preflight_allows_uncommitted_shipped_state_and_prepare_rejects_committed_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)

            before_commit = self.preflight(repo)
            self.assertEqual(before_commit.returncode, 0, before_commit.stderr)

            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)
            manifest_before = (archive / "MANIFEST.md").read_bytes()
            state_temporary = repo / ".project" / ".STATE.md.gsd-path-tmp"
            state_temporary.write_text("preserve on refusal\n")

            committed_preflight = self.preflight(repo)
            self.assertNotEqual(committed_preflight.returncode, 0)
            self.assertIn("validate", committed_preflight.stderr)
            retry = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("validate", retry.stderr)
            self.assertEqual((archive / "MANIFEST.md").read_bytes(), manifest_before)
            self.assertEqual(state_temporary.read_text(), "preserve on refusal\n")

    def test_committed_target_commands_do_not_recreate_a_deleted_archive_root(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            archive_root = repo / ".project" / "archive"
            for command in ("prepare", "preflight", "validate"):
                with self.subTest(command=command):
                    if archive_root.exists():
                        shutil.rmtree(archive_root)
                    before = self.snapshot_worktree(repo)
                    arguments = [
                        sys.executable,
                        str(ARCHIVE_SCRIPT),
                        command,
                        "--repo",
                        str(repo),
                    ]
                    if command == "prepare":
                        arguments.extend(("--slug", "demo"))
                    result = self.run_command(*arguments, cwd=PROJECT_ROOT)

                    self.assertNotEqual(result.returncode, 0)
                    if command != "validate":
                        self.assertIn("validate", result.stderr)
                    self.assertEqual(self.snapshot_worktree(repo), before)

    def test_preflight_rejects_dirty_older_archives_including_ignored_files(self) -> None:
        for status_kind in ("tracked", "untracked", "ignored"):
            with self.subTest(status_kind=status_kind), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo, branch="gsd-path/M002")
                older = repo / ".project" / "archive" / "001-older" / "locked.md"
                older.parent.mkdir(parents=True)
                if status_kind == "tracked":
                    older.write_text("original\n")
                    self.git(repo, "add", str(older.relative_to(repo)))
                    commit = self.git(repo, "commit", "-q", "-m", "older archive")
                    self.assertEqual(commit.returncode, 0, commit.stderr)
                    reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
                    final = repo / ".project" / "review" / "FINAL.md"
                    final_content = final.read_text()
                    final.write_text(
                        final_content.replace(
                            final_content.split("Reviewed HEAD: ", 1)[1].splitlines()[0],
                            reviewed_head,
                        )
                    )
                    gap = repo / ".project" / "review" / "final-gap-1.md"
                    gap_content = gap.read_text()
                    gap.write_text(
                        gap_content.replace(
                            gap_content.split("Reviewed HEAD: ", 1)[1].splitlines()[0],
                            reviewed_head,
                        )
                    )

                archive = self.prepare_archive(repo)
                self.write_manifest(archive)
                if status_kind == "ignored":
                    (repo / ".git" / "info" / "exclude").write_text(
                        ".project/archive/001-older/\n"
                    )
                older.write_text(f"{status_kind} mutation\n")

                preflight = self.preflight(repo)
                self.assertNotEqual(preflight.returncode, 0)
                self.assertIn("older archive", preflight.stderr)

    def test_preflight_rejects_ignored_files_in_the_current_archive(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            relative_archive = archive.relative_to(repo).as_posix()
            (repo / ".git" / "info" / "exclude").write_text(f"{relative_archive}/review/FINAL.md\n")

            preflight = self.preflight(repo)
            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("ignored current archive", preflight.stderr)

    def test_ignored_untracked_carry_forward_fails_preflight_and_committed_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            carry_path = ".project/research/DOCS-AUDIT.md"
            untrack = self.git(repo, "rm", "--cached", "-q", carry_path)
            self.assertEqual(untrack.returncode, 0, untrack.stderr)
            commit = self.git(repo, "commit", "-q", "-m", "untrack carry queue")
            self.assertEqual(commit.returncode, 0, commit.stderr)

            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            for name in ("FINAL.md", "final-gap-1.md"):
                artifact = repo / ".project" / "review" / name
                content = artifact.read_text()
                old_head = content.split("Reviewed HEAD: ", 1)[1].splitlines()[0]
                artifact.write_text(content.replace(old_head, reviewed_head))
            (repo / ".git" / "info" / "exclude").write_text(f"/{carry_path}\n")

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)
            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("ignored active carry-forward", preflight.stderr)

            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)
            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("committed carry-forward", validate.stderr)

    def test_validate_rejects_a_committed_carry_forward_with_different_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            active_audit = repo / ".project" / "research" / "DOCS-AUDIT.md"
            archived_audit = archive / "research" / "DOCS-AUDIT.md"
            active_audit.write_text("different committed queue\n")
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            active_audit.write_bytes(archived_audit.read_bytes())
            assume_unchanged = self.git(
                repo,
                "update-index",
                "--assume-unchanged",
                ".project/research/DOCS-AUDIT.md",
            )
            self.assertEqual(assume_unchanged.returncode, 0, assume_unchanged.stderr)
            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("committed carry-forward differs", validate.stderr)

    def test_prepare_requires_normalized_milestone_slug_without_persisting_a_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace("milestone: demo", "milestone: demo-app")
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("slug", prepare.stderr)
            self.assertIn("archive: null", state_path.read_text())

    def test_prepare_normalizes_cli_slug_against_canonical_state_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace("milestone: demo", "milestone: demo-app")
            )

            archive = self.prepare_archive(repo, "Demo App")
            self.assertEqual(archive.name, "001-demo-app")

            state_path.write_text(
                state_path.read_text().replace("milestone: demo-app", "milestone: other")
            )
            retry = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "Other",
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("archive does not match milestone", retry.stderr)

    def test_prepare_rejects_symlinked_canonical_files_and_malformed_wave_names(self) -> None:
        cases = ("singleton", "task", "malformed-wave")
        for case in cases:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                project = repo / ".project"
                if case == "singleton":
                    intent = project / "intent" / "INTENT.md"
                    intent.unlink()
                    (project / "intent" / "actual.md").write_text("# Intent\n")
                    intent.symlink_to("actual.md")
                elif case == "task":
                    task = project / "tasks" / "T001-demo.md"
                    task.unlink()
                    (project / "tasks" / "actual.md").write_text("# Task\n")
                    task.symlink_to("actual.md")
                else:
                    (project / "review" / "wave-1cycle2.md").write_text("Wave verdict: pass\n")

                prepare = self.run_command(
                    sys.executable,
                    str(ARCHIVE_SCRIPT),
                    "prepare",
                    "--repo",
                    str(repo),
                    "--slug",
                    "demo",
                    cwd=PROJECT_ROOT,
                )
                self.assertNotEqual(prepare.returncode, 0)
                self.assertIn("canonical", prepare.stderr)

    def test_archive_accepts_deep_review_lens_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            plan = repo / ".project" / "plan" / "PLAN.md"
            plan.write_text(
                plan.read_text().replace("Review depth: full", "Review depth: deep")
            )
            review = repo / ".project" / "review"
            (review / "wave-1.cycle1.md").unlink()
            for lens in ("contract", "adversarial"):
                (review / f"wave-1.cycle1.{lens}.md").write_text(
                    f"""# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: deep
Lens: {lens}
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — {lens} evidence passed

## Intent coverage

### SC1 — demo works: pass

- ✅ {lens} evidence passed in focused tests
"""
                )

            archive = self.prepare_archive(repo)

            self.assertTrue((archive / "review" / "wave-1.cycle1.contract.md").is_file())
            self.assertTrue((archive / "review" / "wave-1.cycle1.adversarial.md").is_file())
            self.write_manifest(archive)
            preflight = self.preflight(repo)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def test_preflight_rejects_base_review_for_deep_plan_wave(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            plan = repo / ".project" / "plan" / "PLAN.md"
            plan.write_text(
                plan.read_text().replace("Review depth: full", "Review depth: deep")
            )

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("deep", preflight.stderr)
            self.assertIn("contract and adversarial", preflight.stderr)

    def test_preflight_accepts_verify_only_review_declared_by_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            project = repo / ".project"
            plan = project / "plan" / "PLAN.md"
            plan.write_text(
                plan.read_text().replace(
                    "Review depth: full", "Review depth: verify-only"
                )
            )
            review = project / "review" / "wave-1.cycle1.md"
            review.write_text(
                review.read_text().replace("Depth: full", "Depth: verify-only")
            )

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)

            self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def test_preflight_accepts_optional_panel_when_review_panel_is_off(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            (repo / ".project" / "review" / "wave-1.cycle1.panel.md").write_text(
                "# Panel — wave 1, cycle 1\n"
            )

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)

            self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def test_preflight_requires_panel_when_review_panel_is_on(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            plan = repo / ".project" / "plan" / "PLAN.md"
            plan.write_text(plan.read_text() + "\n## Config\n- review_panel: detected\n")

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("PLAN-PANEL.md", prepare.stderr)

    def test_prepare_fails_closed_on_duplicate_review_panel_config(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            plan = repo / ".project" / "plan" / "PLAN.md"
            plan.write_text(
                plan.read_text()
                + "\n## Config\n- review_panel: off\n- review_panel: off\n"
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("multiple review_panel values", prepare.stderr)

    def test_preflight_accepts_canonical_skipped_panel_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            project = repo / ".project"
            plan = project / "plan" / "PLAN.md"
            plan.write_text(plan.read_text() + "\n## Config\n- review_panel: detected\n")
            review = project / "review"
            self.write_panel_skip_receipt(review / "PLAN-PANEL.skipped.json")
            self.write_panel_skip_receipt(
                review / "wave-1.cycle1.panel.skipped.json"
            )

            archive = self.prepare_archive(repo)
            rendered = self.render_manifest(repo)
            preflight = self.preflight(repo)

            self.assertEqual(rendered.returncode, 0, rendered.stderr)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assertTrue(
                (archive / "review" / "PLAN-PANEL.skipped.json").is_file()
            )
            self.assertTrue(
                (
                    archive
                    / "review"
                    / "wave-1.cycle1.panel.skipped.json"
                ).is_file()
            )

    def test_prepare_rejects_a_noncanonical_skipped_panel_receipt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            project = repo / ".project"
            plan = project / "plan" / "PLAN.md"
            plan.write_text(plan.read_text() + "\n## Config\n- review_panel: detected\n")
            (project / "review" / "PLAN-PANEL.skipped.json").write_text(
                '{"status": "skipped"}\n', encoding="utf-8"
            )

            prepare = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(prepare.returncode, 0)
            self.assertIn("canonical skipped-panel receipt", prepare.stderr)

    def test_preflight_accepts_enabled_review_panel_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            plan = repo / ".project" / "plan" / "PLAN.md"
            plan.write_text(plan.read_text() + "\n## Config\n- review_panel: detected\n")
            (repo / ".project" / "review" / "PLAN-PANEL.md").write_text(
                "# Plan panel\n\nActionable: 0\n"
            )
            (repo / ".project" / "review" / "wave-1.cycle1.panel.md").write_text(
                "# Panel — wave 1, cycle 1\n"
            )

            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            preflight = self.preflight(repo)

            self.assertEqual(preflight.returncode, 0, preflight.stderr)
            self.assertTrue((archive / "review" / "PLAN-PANEL.md").is_file())
            self.assertTrue((archive / "review" / "wave-1.cycle1.panel.md").is_file())

    def test_deep_review_lens_content_is_validated(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = Path(temporary_directory)
            (archive / "plan").mkdir()
            (archive / "tasks").mkdir()
            (archive / "review").mkdir()
            (archive / "plan" / "PLAN.md").write_text(
                """# Plan

## Wave 1 — demo

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | demo | — | demo.py |

Review depth: deep
"""
            )
            (archive / "tasks" / "T001-demo.md").write_text(
                "---\nid: T001\ntitle: demo\nwave: 1\n---\n# Task\n"
            )
            (archive / "review" / "wave-1.cycle1.contract.md").write_text(
                """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Lens: contract
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — contract evidence passed
"""
            )
            (archive / "review" / "wave-1.cycle1.adversarial.md").write_text(
                """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: deep
Lens: adversarial
Tasks reviewed: 1

## T001 — demo: pass

- ✅ demo works — adversarial evidence passed
"""
            )

            with self.assertRaisesRegex(archive_milestone.ArchiveError, "review depth"):
                archive_milestone.review_cycle_counts(archive)

    def test_wave_review_cannot_substitute_another_plan_waves_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            archive = Path(temporary_directory)
            (archive / "plan").mkdir()
            (archive / "tasks").mkdir()
            (archive / "review").mkdir()
            (archive / "plan" / "PLAN.md").write_text(
                """# Plan

## Wave 1 — first

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | first task | — | first.py |

## Wave 2 — second

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T002 | second task | T001 | second.py |
"""
            )
            (archive / "tasks" / "T001-first.md").write_text(
                "---\nid: T001\ntitle: first task\nwave: 1\n---\n"
            )
            (archive / "tasks" / "T002-second.md").write_text(
                "---\nid: T002\ntitle: second task\nwave: 2\n---\n"
            )
            for wave in (1, 2):
                (archive / "review" / f"wave-{wave}.cycle1.md").write_text(
                    f"""# Review — wave {wave}, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T002 — second task: pass

- ✅ second task works — focused evidence passed
"""
                )

            with self.assertRaisesRegex(
                archive_milestone.ArchiveError,
                "tasks and titles do not match its wave task files in order",
            ):
                archive_milestone.review_cycle_counts(archive)

    def test_preflight_derives_contiguous_cycles_and_requires_the_last_to_pass(self) -> None:
        for case in ("manifest-count", "cycle-gap", "last-blocked", "wrong-heading", "wrong-cycle"):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                archive = self.prepare_archive(repo)
                wave = archive / "review" / "wave-1.cycle1.md"
                if case == "cycle-gap":
                    cycle_two = archive / "review" / "wave-1.cycle2.md"
                    wave.rename(cycle_two)
                    cycle_two.write_text(
                        "# Review — wave 1, cycle 2\n\nWave verdict: pass\nCycle: 2\n"
                    )
                elif case == "last-blocked":
                    wave.write_text(wave.read_text().replace("Wave verdict: pass", "Wave verdict: blocked"))
                elif case == "wrong-heading":
                    wave.write_text(wave.read_text().replace("wave 1, cycle 1", "wave 2, cycle 1"))
                elif case == "wrong-cycle":
                    wave.write_text(wave.read_text().replace("Cycle: 1", "Cycle: 2"))
                self.write_manifest(archive)
                if case in {"manifest-count", "cycle-gap"}:
                    manifest = archive / "MANIFEST.md"
                    manifest.write_text(
                        manifest.read_text().replace("Review cycles used: 1", "Review cycles used: 2")
                    )

                preflight = self.preflight(repo)
                self.assertNotEqual(preflight.returncode, 0)
                self.assertIn("cycle", preflight.stderr.lower())

    def test_preflight_requires_final_pass_matching_criteria_and_complete_notes(self) -> None:
        for case in (
            "blocked-final",
            "wrong-evidence",
            "empty-notes",
            "placeholder-note",
            "manifest-placeholder",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                archive = self.prepare_archive(repo)
                self.write_manifest(archive)
                manifest = archive / "MANIFEST.md"
                final = archive / "review" / "FINAL.md"
                if case == "blocked-final":
                    final.write_text(final.read_text().replace("Overall verdict: pass", "Overall verdict: blocked"))
                elif case == "wrong-evidence":
                    manifest.write_text(
                        manifest.read_text().replace(
                            "| demo works | met | tests |",
                            "| demo works | met | wrong |",
                        )
                    )
                elif case == "empty-notes":
                    manifest.write_text(manifest.read_text().replace("\n- none\n", "\n"))
                elif case == "placeholder-note":
                    manifest.write_text(manifest.read_text().replace("- none", "- <note>"))
                else:
                    manifest.write_text(manifest.read_text() + "\n<!-- <unfinished> -->\n")

                preflight = self.preflight(repo)
                self.assertNotEqual(preflight.returncode, 0)
                expected = "final" if case == "blocked-final" else "criteria" if case == "wrong-evidence" else "notes"
                if case in {"placeholder-note", "manifest-placeholder"}:
                    expected = "placeholder"
                self.assertIn(expected, preflight.stderr.lower())

    def test_preflight_requires_contiguous_passing_gap_reviews_at_the_reviewed_head(self) -> None:
        for case in (
            "missing",
            "symlink",
            "number",
            "heading",
            "head",
            "risk",
            "waves",
            "fix",
            "blocked",
        ):
            with self.subTest(case=case), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                archive = self.prepare_archive(repo)
                gap = archive / "review" / "final-gap-1.md"
                if case == "missing":
                    gap.unlink()
                elif case == "symlink":
                    content = gap.read_text()
                    gap.unlink()
                    (archive / "review" / "gap-target.md").write_text(content)
                    gap.symlink_to("gap-target.md")
                elif case == "number":
                    gap.rename(archive / "review" / "final-gap-2.md")
                elif case == "heading":
                    gap.write_text(gap.read_text().replace("Gap Review — 1", "Gap Review — 2"))
                elif case == "head":
                    reviewed = gap.read_text().split("Reviewed HEAD: ", 1)[1].splitlines()[0]
                    gap.write_text(gap.read_text().replace(reviewed, "0" * 40))
                elif case == "risk":
                    gap.write_text(gap.read_text().replace("Risk: project Verify command", "Risk: <risk>"))
                elif case == "waves":
                    gap.write_text(gap.read_text().replace("Waves checked: 1\n", ""))
                elif case == "fix":
                    gap.write_text(
                        gap.read_text().replace(
                            "- **Fix direction**: none",
                            "- **Fix direction**: change the implementation",
                        )
                    )
                else:
                    gap.write_text(gap.read_text().replace("Gap verdict: pass", "Gap verdict: blocked"))
                self.write_manifest(archive)

                preflight = self.preflight(repo)
                self.assertNotEqual(preflight.returncode, 0)
                self.assertIn("gap", preflight.stderr.lower())

    def test_preflight_rejects_an_evidence_free_passing_gap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            gap = archive / "review" / "final-gap-1.md"
            reviewed_head = gap.read_text().split("Reviewed HEAD: ", 1)[1].splitlines()[0]
            gap.write_text(
                f"""# Gap Review — 1: project Verify command

Reviewed HEAD: {reviewed_head}
Gap verdict: pass
Risk: project Verify command
Waves checked: 1

## Checked evidence

- **Check**: none
- **Observed**: none
- **Reference**: none

## Finding

- **Found**: No checked result was recorded.
- **Fix direction**: none
"""
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("evidence", preflight.stderr.lower())

    def test_preflight_rejects_a_gap_heading_risk_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            gap = archive / "review" / "final-gap-1.md"
            gap.write_text(
                gap.read_text().replace(
                    "Risk: project Verify command", "Risk: release packaging"
                )
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("heading risk does not match Risk field", preflight.stderr)

    def test_preflight_rejects_a_post_review_stray_task_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            (archive / "tasks" / "review-notes.md").write_text(
                "not a task artifact\n"
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("canonical task artifacts", preflight.stderr)

    def test_preflight_rejects_a_passing_wave_without_task_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            wave = archive / "review" / "wave-1.cycle1.md"
            wave.write_text(
                """# Review — wave 1, cycle 1

Wave verdict: pass
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: pass
"""
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("evidence", preflight.stderr.lower())

    def test_preflight_rejects_none_as_passing_task_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            wave = archive / "review" / "wave-1.cycle1.md"
            wave.write_text(
                wave.read_text().replace(
                    "- ✅ demo works — focused Verify passed", "- ✅ none"
                )
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("non-placeholder evidence", preflight.stderr)

    def test_preflight_rejects_owned_sc_without_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            wave = archive / "review" / "wave-1.cycle1.md"
            wave.write_text(
                wave.read_text().replace("- ✅ focused Verify passed in tests\n", "")
            )
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("SC1 lacks non-placeholder evidence", preflight.stderr)

    def test_preflight_rejects_a_passing_wave_for_an_unknown_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            wave = archive / "review" / "wave-1.cycle1.md"
            wave.write_text(wave.read_text().replace("T001 — demo", "T999 — demo"))
            self.write_manifest(archive)

            preflight = self.preflight(repo)

            self.assertNotEqual(preflight.returncode, 0)
            self.assertIn("task", preflight.stderr.lower())

    def test_manifest_evidence_falls_back_from_final_reference_to_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            final = archive / "review" / "FINAL.md"
            final.write_text(final.read_text().replace("**Reference**: tests", "**Reference**: none"))
            self.write_manifest(archive)
            manifest = archive / "MANIFEST.md"
            manifest.write_text(
                manifest.read_text().replace(
                    "| demo works | met | tests |",
                    "| demo works | met | python -m unittest |",
                )
            )

            preflight = self.preflight(repo)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)

    def test_reviewed_head_must_match_preflight_head_and_ship_parent(self) -> None:
        for command in ("preflight", "validate"):
            with self.subTest(command=command), tempfile.TemporaryDirectory() as temporary_directory:
                repo = Path(temporary_directory)
                self.make_repo(repo)
                final = repo / ".project" / "review" / "FINAL.md"
                reviewed_head = final.read_text().split("Reviewed HEAD: ", 1)[1].splitlines()[0]
                final.write_text(final.read_text().replace(reviewed_head, "0" * 40))
                archive = self.prepare_archive(repo)
                self.write_manifest(archive)
                if command == "preflight":
                    result = self.preflight(repo)
                else:
                    self.mark_shipped(repo)
                    self.git(repo, "add", ".project")
                    ship = self.commit_ship(repo, archive)
                    self.assertEqual(ship.returncode, 0, ship.stderr)
                    result = self.run_command(
                        sys.executable,
                        str(ARCHIVE_SCRIPT),
                        "validate",
                        "--repo",
                        str(repo),
                        cwd=PROJECT_ROOT,
                    )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("reviewed head", result.stderr.lower())

    def test_validate_rejects_product_commits_after_shipping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)
            (repo / "feature.py").write_text("print('product work')\n")
            self.git(repo, "add", "feature.py")
            product = self.git(repo, "commit", "-q", "-m", "product work after shipping")
            self.assertEqual(product.returncode, 0, product.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("HEAD must equal", validate.stderr)

    def test_validate_rejects_project_history_changes_after_shipping(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)

            plan = archive / "plan" / "PLAN.md"
            plan.write_text(plan.read_text() + "\nPost-ship edit.\n")
            self.git(repo, "add", ".project")
            tamper = self.git(repo, "commit", "-q", "-m", "edit archived plan")
            self.assertEqual(tamper.returncode, 0, tamper.stderr)

            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertNotEqual(validate.returncode, 0)
            self.assertIn("HEAD must equal", validate.stderr)

    def test_evidence_allows_comparison_operators_and_escaped_pipes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            (repo / ".project" / "intent" / "INTENT.md").write_text(
                "# Intent\n\n## Success criteria\n\n1. latency budget\n"
            )
            wave = repo / ".project" / "review" / "wave-1.cycle1.md"
            wave.write_text(
                wave.read_text().replace(
                    "### SC1 — demo works: pass",
                    "### SC1 — latency budget: pass",
                )
            )
            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            (repo / ".project" / "review" / "FINAL.md").write_text(
                f"""# Final Review — demo

Reviewed HEAD: {reviewed_head}
Overall verdict: pass

## Success criteria

### SC1 — latency budget

- **Verdict**: met
- **Check**: `grep p95 bench.log | awk '{{print $2}}'`
- **Observed**: p95 120ms < 200ms target
- **Reference**: none
- **Finding**: none
- **Fix direction**: none
"""
            )
            archive = self.prepare_archive(repo)
            contents = sorted(
                path.relative_to(archive).as_posix()
                for path in archive.rglob("*")
                if path.is_file() and path.name != "MANIFEST.md"
            )
            listed_contents = "\n".join(f"- {path}" for path in contents)
            (archive / "MANIFEST.md").write_text(
                f"""# Archive — {archive.name}

Milestone: demo
Shipped: 2026-08-01
Final verdict: all criteria met; project verify passed
Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1
Carried forward: 1 DOCS-AUDIT ruling(s)

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| latency budget | met | grep p95 bench.log \\| awk '{{print $2}}' |

## Contents

{listed_contents}

## Notes

- none
"""
            )

            preflight = self.preflight(repo)
            self.assertEqual(preflight.returncode, 0, preflight.stderr)

            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(repo, archive)
            self.assertEqual(ship.returncode, 0, ship.stderr)
            validate = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(validate.returncode, 0, validate.stderr)

    def make_bound_repo(self, root: Path, branch: str = "gsd-path/M001") -> None:
        self.make_repo(root)
        baseline = self.git(root, "rev-parse", "HEAD").stdout.strip()
        local_main = self.git(root, "update-ref", "refs/heads/main", baseline)
        self.assertEqual(local_main.returncode, 0, local_main.stderr)
        updated = self.git(root, "update-ref", "refs/remotes/origin/main", baseline)
        self.assertEqual(updated.returncode, 0, updated.stderr)
        linked = self.git(
            root, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main"
        )
        self.assertEqual(linked.returncode, 0, linked.stderr)
        if branch != "gsd-path/M001":
            checkout = self.git(root, "checkout", "-q", "-b", branch)
            self.assertEqual(checkout.returncode, 0, checkout.stderr)
        state_path = root / ".project" / "STATE.md"
        state_path.write_text(
            state_path.read_text().replace("branch: gsd-path/M001", f"branch: {branch}")
        )

    def make_publishable_bound_repo(self, root: Path, remote: Path) -> None:
        created = self.run_command(
            "git",
            "init",
            "--bare",
            "-q",
            "-b",
            "main",
            str(remote),
            cwd=root.parent,
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.make_repo(root, branch="main")
        added = self.git(root, "remote", "add", "origin", str(remote))
        self.assertEqual(added.returncode, 0, added.stderr)
        pushed = self.git(root, "push", "-q", "-u", "origin", "main")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        linked = self.git(root, "remote", "set-head", "origin", "--auto")
        self.assertEqual(linked.returncode, 0, linked.stderr)
        checkout = self.git(root, "checkout", "-q", "-b", "gsd-path/M001")
        self.assertEqual(checkout.returncode, 0, checkout.stderr)
        state_path = root / ".project" / "STATE.md"
        state_path.write_text(
            state_path.read_text().replace("branch: main", "branch: gsd-path/M001")
        )

    def ship_bound(self, repo: Path) -> tuple:
        archive = self.prepare_archive(repo)
        self.write_manifest(archive)
        self.mark_shipped(repo)
        self.git(repo, "add", ".project")
        ship = self.commit_ship(repo, archive)
        self.assertEqual(ship.returncode, 0, ship.stderr)
        ship_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        return archive.name, ship_sha

    def ship_canonical_bound(self, repo: Path) -> tuple[str, str]:
        archive = self.prepare_archive(repo)
        rendered = self.render_manifest(repo)
        self.assertEqual(rendered.returncode, 0, rendered.stderr)
        checked = self.preflight(repo)
        self.assertEqual(checked.returncode, 0, checked.stderr)
        reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        self.mark_shipped(repo)
        self.git(repo, "add", ".project")
        ship = self.git(
            repo,
            "commit",
            "-q",
            "-m",
            pipeline_git.ship_subject(archive.name),
            "-m",
            pipeline_git.ship_commit_body(
                archive.relative_to(repo).as_posix(), reviewed_head
            ),
        )
        self.assertEqual(ship.returncode, 0, ship.stderr)
        return archive.name, self.git(repo, "rev-parse", "HEAD").stdout.strip()

    def integrate(self, repo: Path) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "integrate",
            "--repo",
            str(repo),
            "--slug",
            "demo",
            cwd=PROJECT_ROOT,
        )

    def enable_pull_request_integration(self, repo: Path) -> None:
        state = repo / ".project" / "STATE.md"
        state.write_text(
            state.read_text(encoding="utf-8").replace(
                "archive: null\n",
                "archive: null\n"
                "integration_default: pull-request\n"
                "integration: pull-request\n",
            ),
            encoding="utf-8",
        )

    def github_api(self, pulls):
        def run(*arguments: str) -> subprocess.CompletedProcess[str]:
            if arguments == ("gh", "auth", "status"):
                return subprocess.CompletedProcess(arguments, 0, "", "")
            if arguments[:3] == ("gh", "api", "graphql"):
                payload = {
                    "data": {
                        "repository": {
                            "pullRequest": {
                                "mergeQueue": {"nodes": []},
                                "autoMerge": {"nodes": []},
                            }
                        }
                    }
                }
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(payload), ""
                )
            if arguments[:3] == ("gh", "api", "repos/open-gsd/demo/pulls"):
                if "GET" in arguments:
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps(pulls), ""
                    )
                created = {
                    "number": 7,
                    "state": "open",
                    "html_url": "https://github.com/open-gsd/demo/pull/7",
                    "merged_at": None,
                    "merge_commit_sha": None,
                    "base": {"ref": "main"},
                    "head": {"ref": "gsd-path/M001", "sha": pulls[0]["head"]["sha"]}
                    if pulls
                    else {"ref": "gsd-path/M001", "sha": "created-by-github"},
                }
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(created), ""
                )
            return subprocess.CompletedProcess(arguments, 1, "", "unexpected command")

        return run

    def merged_pull_request(self, ship_sha: str, merge_sha: str) -> dict:
        return {
            "number": 7,
            "state": "closed",
            "html_url": "https://github.com/open-gsd/demo/pull/7",
            "merged_at": "2026-08-29T12:00:00Z",
            "merge_commit_sha": merge_sha,
            "base": {"ref": "main"},
            "head": {"ref": "gsd-path/M001", "sha": ship_sha},
            "body": archive_milestone.PR_CREDIT_LINE,
        }

    def test_pull_request_integration_creates_pr_after_publishing_ship(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            requests = []

            def github_api(*arguments: str) -> subprocess.CompletedProcess[str]:
                requests.append(arguments)
                if arguments == ("gh", "auth", "status"):
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if arguments[:3] != ("gh", "api", "repos/open-gsd/demo/pulls"):
                    return subprocess.CompletedProcess(
                        arguments, 1, "", "unexpected command"
                    )
                if "GET" in arguments:
                    return subprocess.CompletedProcess(arguments, 0, "[]", "")
                created = {
                    "number": 7,
                    "state": "open",
                    "html_url": "https://github.com/open-gsd/demo/pull/7",
                    "merged_at": None,
                    "merge_commit_sha": None,
                    "base": {"ref": "main"},
                    "head": {"ref": "gsd-path/M001", "sha": ship_sha},
                }
                return subprocess.CompletedProcess(
                    arguments, 0, json.dumps(created), ""
                )

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=github_api,
                ),
            ):
                result = archive_milestone.integrate(repo, "demo")

            self.assertEqual(result["status"], "awaiting-merge")
            self.assertEqual(
                self.git(remote, "rev-parse", "gsd-path/M001").stdout.strip(),
                ship_sha,
            )
            post = next(arguments for arguments in requests if "POST" in arguments)
            self.assertIn(
                f"title={pipeline_git.integrate_subject(archive_name, 'main')}",
                post,
            )
            self.assertIn("base=main", post)
            self.assertIn("head=gsd-path/M001", post)
            body = next(argument for argument in post if argument.startswith("body="))
            self.assertTrue(
                body.endswith(f"\n\n---\n{archive_milestone.PR_CREDIT_LINE}")
            )

    def test_pull_request_integration_waits_without_touching_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            _archive_name, ship_sha = self.ship_canonical_bound(repo)
            baseline = self.git(remote, "rev-parse", "main").stdout.strip()
            open_pull = {
                "number": 7,
                "state": "open",
                "html_url": "https://github.com/open-gsd/demo/pull/7",
                "merged_at": None,
                "merge_commit_sha": None,
                "base": {"ref": "main"},
                "head": {"ref": "gsd-path/M001", "sha": ship_sha},
                "body": archive_milestone.PR_CREDIT_LINE,
            }

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=self.github_api([open_pull]),
                ),
            ):
                result = archive_milestone.integrate(repo, "demo")

            self.assertEqual(result["status"], "awaiting-merge")
            self.assertEqual(result["pull_request"], open_pull["html_url"])
            self.assertEqual(self.git(remote, "rev-parse", "main").stdout.strip(), baseline)
            self.assertEqual(
                self.git(remote, "rev-parse", "gsd-path/M001").stdout.strip(),
                ship_sha,
            )
            self.assertNotEqual(
                self.git(remote, "show-ref", "--tags", "--quiet").returncode,
                0,
            )

    def test_pull_request_integration_repairs_reused_pr_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            _archive_name, ship_sha = self.ship_canonical_bound(repo)
            open_pull = {
                "number": 7,
                "state": "open",
                "html_url": "https://github.com/open-gsd/demo/pull/7",
                "merged_at": None,
                "merge_commit_sha": None,
                "base": {"ref": "main"},
                "head": {"ref": "gsd-path/M001", "sha": ship_sha},
                "body": "",
            }
            requests = []

            def github_api(*arguments: str) -> subprocess.CompletedProcess[str]:
                requests.append(arguments)
                if arguments == ("gh", "auth", "status"):
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if arguments[:3] == ("gh", "api", "repos/open-gsd/demo/pulls"):
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps([open_pull]), ""
                    )
                if arguments[:3] == ("gh", "api", "repos/open-gsd/demo/pulls/7"):
                    body = next(
                        argument.removeprefix("body=")
                        for argument in arguments
                        if argument.startswith("body=")
                    )
                    return subprocess.CompletedProcess(
                        arguments,
                        0,
                        json.dumps({**open_pull, "body": body}),
                        "",
                    )
                return subprocess.CompletedProcess(
                    arguments,
                    1,
                    "",
                    "unexpected command",
                )

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=github_api,
                ),
            ):
                result = archive_milestone.integrate(repo, "demo")

            self.assertEqual(result["status"], "awaiting-merge")
            patch = next(arguments for arguments in requests if "PATCH" in arguments)
            body = next(argument for argument in patch if argument.startswith("body="))
            self.assertTrue(
                body.endswith(f"\n\n---\n{archive_milestone.PR_CREDIT_LINE}")
            )

    def test_pull_request_integration_accepts_merge_and_deleted_head_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            self.git(repo, "push", "-q", "origin", "gsd-path/M001")
            merge_sha = self.integrate_bound(
                repo,
                archive_name,
                ship_sha,
                tag=False,
                subject="Merge pull request #7 from open-gsd/gsd-path/M001",
            )
            self.git(repo, "push", "-q", "origin", f"{merge_sha}:refs/heads/main")
            self.git(repo, "push", "-q", "origin", "--delete", "gsd-path/M001")
            pull = self.merged_pull_request(ship_sha, merge_sha)

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=self.github_api([pull]),
                ),
            ):
                result = archive_milestone.integrate(repo, "demo")

            self.assertEqual(result["mode"], "pull-request")
            self.assertEqual(result["landing"], merge_sha)
            self.assertEqual(result["base"], merge_sha)
            self.assertEqual(result["pull_request"], pull["html_url"])
            self.assertEqual(
                self.git(
                    remote, "rev-parse", f"milestone/{archive_name}^{{commit}}"
                ).stdout.strip(),
                merge_sha,
            )
            validated = archive_milestone.validate_integrated(repo, "demo")
            self.assertEqual(validated["landing"], merge_sha)

    def test_pull_request_integration_rejects_merge_queue_before_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            self.git(repo, "push", "-q", "origin", "gsd-path/M001")
            merge_sha = self.integrate_bound(
                repo,
                archive_name,
                ship_sha,
                tag=False,
                subject="Merge pull request #7 from open-gsd/gsd-path/M001",
            )
            self.git(repo, "push", "-q", "origin", f"{merge_sha}:refs/heads/main")
            pull = self.merged_pull_request(ship_sha, merge_sha)

            def github_api(*arguments: str) -> subprocess.CompletedProcess[str]:
                if arguments == ("gh", "auth", "status"):
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if arguments[:3] == ("gh", "api", "repos/open-gsd/demo/pulls"):
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps([pull]), ""
                    )
                if arguments[:3] == ("gh", "api", "graphql"):
                    payload = {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "mergeQueue": {
                                        "nodes": [
                                            {"__typename": "AddedToMergeQueueEvent"}
                                        ]
                                    },
                                    "autoMerge": {"nodes": []},
                                }
                            }
                        }
                    }
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps(payload), ""
                    )
                return subprocess.CompletedProcess(
                    arguments, 1, "", "unexpected command"
                )

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=github_api,
                ),
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError,
                    "merge queue",
                ):
                    archive_milestone.integrate(repo, "demo")

            self.assertNotEqual(
                self.git(remote, "show-ref", "--tags", "--quiet").returncode,
                0,
            )

    def test_pull_request_integration_rejects_auto_merge_before_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            self.git(repo, "push", "-q", "origin", "gsd-path/M001")
            merge_sha = self.integrate_bound(
                repo,
                archive_name,
                ship_sha,
                tag=False,
                subject="Merge pull request #7 from open-gsd/gsd-path/M001",
            )
            self.git(repo, "push", "-q", "origin", f"{merge_sha}:refs/heads/main")
            pull = self.merged_pull_request(ship_sha, merge_sha)

            def github_api(*arguments: str) -> subprocess.CompletedProcess[str]:
                if arguments == ("gh", "auth", "status"):
                    return subprocess.CompletedProcess(arguments, 0, "", "")
                if arguments[:3] == ("gh", "api", "repos/open-gsd/demo/pulls"):
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps([pull]), ""
                    )
                if arguments[:3] == ("gh", "api", "graphql"):
                    payload = {
                        "data": {
                            "repository": {
                                "pullRequest": {
                                    "mergeQueue": {"nodes": []},
                                    "autoMerge": {
                                        "nodes": [
                                            {"__typename": "AutoMergeEnabledEvent"}
                                        ]
                                    },
                                }
                            }
                        }
                    }
                    return subprocess.CompletedProcess(
                        arguments, 0, json.dumps(payload), ""
                    )
                return subprocess.CompletedProcess(
                    arguments, 1, "", "unexpected command"
                )

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=github_api,
                ),
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError,
                    "auto-merge",
                ):
                    archive_milestone.integrate(repo, "demo")

            self.assertNotEqual(
                self.git(remote, "show-ref", "--tags", "--quiet").returncode,
                0,
            )

    def test_pull_request_integration_rejects_non_merge_landing(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            self.enable_pull_request_integration(repo)
            _archive_name, ship_sha = self.ship_canonical_bound(repo)
            self.git(repo, "push", "-q", "origin", f"{ship_sha}:refs/heads/main")
            pull = self.merged_pull_request(ship_sha, ship_sha)

            with (
                mock.patch.object(
                    archive_milestone,
                    "github_repository",
                    return_value="open-gsd/demo",
                ),
                mock.patch.object(
                    archive_milestone,
                    "run_command",
                    side_effect=self.github_api([pull]),
                ),
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError,
                    "must use a two-parent merge commit",
                ):
                    archive_milestone.integrate(repo, "demo")

    def reject_remote_ref(self, remote: Path, ref: str) -> Path:
        hook = remote / "hooks" / "pre-receive"
        hook.write_text(
            "#!/bin/sh\n"
            "while read old new updated_ref; do\n"
            f'  if [ "$updated_ref" = "{ref}" ]; then\n'
            "    echo rejected-for-test >&2\n"
            "    exit 1\n"
            "  fi\n"
            "done\n"
        )
        hook.chmod(0o755)
        return hook

    def install_commit_guard(self, repo: Path) -> None:
        hook = repo / ".git" / "hooks" / "commit-msg"
        hook.write_text(
            "#!/bin/sh\n"
            f'exec "{sys.executable}" "{GIT_GUARD_SCRIPT}" commit-msg "$1"\n'
        )
        hook.chmod(0o755)

    def test_integrate_publishes_and_completed_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            self.install_commit_guard(repo)

            first = self.integrate(repo)
            retry = self.integrate(repo)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            first_payload = json.loads(first.stdout)
            retry_payload = json.loads(retry.stdout)
            self.assertEqual(retry_payload, first_payload)
            merge_sha = first_payload["integrate"]
            self.assertEqual(first_payload["commit"], ship_sha)
            self.assertEqual(first_payload["tag"], f"milestone/{archive_name}")
            self.assertEqual(
                self.git(remote, "rev-parse", "main").stdout.strip(), merge_sha
            )
            self.assertEqual(
                self.git(remote, "rev-parse", "gsd-path/M001").stdout.strip(), ship_sha
            )
            self.assertEqual(
                self.git(
                    remote, "rev-parse", f"milestone/{archive_name}^{{commit}}"
                ).stdout.strip(),
                merge_sha,
            )
            self.assertEqual(
                self.git(
                    remote, "cat-file", "-t", f"refs/tags/milestone/{archive_name}"
                ).stdout.strip(),
                "tag",
            )
            self.assertEqual(
                self.git(repo, "branch", "--list", "gsd-path-integrate/M001").stdout.strip(),
                "",
            )
            self.assertNotIn(
                "refs/heads/gsd-path-integrate/M001",
                self.git(repo, "worktree", "list", "--porcelain").stdout,
            )

    def test_integrate_resumes_a_merge_that_has_no_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            integration_branch = "gsd-path-integrate/M001"
            partial_worktree = root / "partial-integration"
            added = self.git(
                repo,
                "worktree",
                "add",
                "-q",
                "-b",
                integration_branch,
                str(partial_worktree),
                "origin/main",
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            merged = self.git(
                partial_worktree,
                "merge",
                "--no-ff",
                "-m",
                pipeline_git.integrate_subject(archive_name, "main"),
                "-m",
                pipeline_git.integrate_commit_body(
                    f".project/archive/{archive_name}",
                    ship_sha,
                    "main",
                    "gsd-path/M001",
                ),
                ship_sha,
            )
            self.assertEqual(merged.returncode, 0, merged.stderr)
            merge_sha = self.git(partial_worktree, "rev-parse", "HEAD").stdout.strip()
            removed = self.git(repo, "worktree", "remove", str(partial_worktree))
            self.assertEqual(removed.returncode, 0, removed.stderr)

            result = self.integrate(repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["integrate"], merge_sha)
            self.assertEqual(
                self.git(
                    remote, "rev-parse", f"milestone/{archive_name}^{{commit}}"
                ).stdout.strip(),
                merge_sha,
            )

    def test_integrate_resumes_ordered_push_failures(self) -> None:
        rejected_refs = (
            "refs/heads/main",
            "refs/tags/milestone/001-demo",
        )
        for rejected_ref in rejected_refs:
            with (
                self.subTest(rejected_ref=rejected_ref),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                root = Path(temporary_directory)
                repo = root / "primary"
                repo.mkdir()
                remote = root / "origin.git"
                self.make_publishable_bound_repo(repo, remote)
                archive_name, ship_sha = self.ship_canonical_bound(repo)
                baseline = self.git(remote, "rev-parse", "main").stdout.strip()
                hook = self.reject_remote_ref(remote, rejected_ref)

                partial = self.integrate(repo)

                self.assertNotEqual(partial.returncode, 0)
                self.assertIn("push", partial.stderr)
                self.assertEqual(
                    self.git(
                        repo,
                        "cat-file",
                        "-t",
                        f"refs/tags/milestone/{archive_name}",
                    ).stdout.strip(),
                    "tag",
                )
                self.assertNotIn(
                    "refs/heads/gsd-path-integrate/M001",
                    self.git(repo, "worktree", "list", "--porcelain").stdout,
                )
                if rejected_ref == "refs/heads/main":
                    self.assertEqual(
                        self.git(remote, "rev-parse", "main").stdout.strip(), baseline
                    )
                    self.assertNotEqual(
                        self.git(
                            remote,
                            "show-ref",
                            "--verify",
                            "refs/heads/gsd-path/M001",
                        ).returncode,
                        0,
                    )
                else:
                    self.assertNotEqual(
                        self.git(remote, "rev-parse", "main").stdout.strip(), baseline
                    )
                    self.assertEqual(
                        self.git(remote, "rev-parse", "gsd-path/M001").stdout.strip(), ship_sha
                    )
                    self.assertNotEqual(
                        self.git(remote, "show-ref", "--verify", rejected_ref).returncode,
                        0,
                    )

                hook.unlink()
                retry = self.integrate(repo)

                self.assertEqual(retry.returncode, 0, retry.stderr)
                self.assertEqual(json.loads(retry.stdout)["commit"], ship_sha)
                self.assertEqual(
                    self.git(
                        remote, "rev-parse", f"milestone/{archive_name}^{{commit}}"
                    ).returncode,
                    0,
                )

    def test_integrate_refuses_a_live_bound_branch_collision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            _archive_name, ship_sha = self.ship_canonical_bound(repo)
            ancestor = self.git(repo, "rev-parse", f"{ship_sha}^").stdout.strip()
            published = self.git(
                repo,
                "push",
                "-q",
                "origin",
                f"{ancestor}:refs/heads/gsd-path/M001",
            )
            self.assertEqual(published.returncode, 0, published.stderr)

            first = self.integrate(repo)
            retry = self.integrate(repo)

            self.assertNotEqual(first.returncode, 0)
            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("moved or collides", first.stderr)
            self.assertIn("moved or collides", retry.stderr)
            self.assertEqual(
                self.git(remote, "rev-parse", "gsd-path/M001").stdout.strip(),
                ancestor,
            )

    def test_integrate_rebuilds_an_unpublished_merge_after_main_advances(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            archive_name, ship_sha = self.ship_canonical_bound(repo)
            other = root / "other"
            cloned = self.run_command(
                "git", "clone", "-q", str(remote), str(other), cwd=root
            )
            self.assertEqual(cloned.returncode, 0, cloned.stderr)
            self.git(other, "config", "user.name", "Validation")
            self.git(other, "config", "user.email", "validation@example.invalid")
            original_run_git = archive_milestone.run_git
            advanced_main = None

            def race_main(project: Path, *arguments: str) -> subprocess.CompletedProcess:
                nonlocal advanced_main
                if (
                    advanced_main is None
                    and len(arguments) >= 3
                    and arguments[0:2] == ("push", "origin")
                    and arguments[-1].endswith(":refs/heads/main")
                ):
                    (other / "remote-only.txt").write_text("advanced\n")
                    self.git(other, "add", "remote-only.txt")
                    committed = self.git(other, "commit", "-q", "-m", "advance main")
                    self.assertEqual(committed.returncode, 0, committed.stderr)
                    pushed = self.git(other, "push", "-q", "origin", "main")
                    self.assertEqual(pushed.returncode, 0, pushed.stderr)
                    advanced_main = self.git(remote, "rev-parse", "main").stdout.strip()
                return original_run_git(project, *arguments)

            with mock.patch.object(
                archive_milestone, "run_git", side_effect=race_main
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError, "push integration merge"
                ):
                    archive_milestone.integrate(repo, "demo")

            self.assertIsNotNone(advanced_main)
            self.assertNotEqual(
                self.git(
                    remote, "show-ref", "--verify", "refs/heads/gsd-path/M001"
                ).returncode,
                0,
            )
            self.assertNotEqual(
                self.git(
                    remote,
                    "show-ref",
                    "--verify",
                    f"refs/tags/milestone/{archive_name}",
                ).returncode,
                0,
            )

            retry = self.integrate(repo)

            self.assertEqual(retry.returncode, 0, retry.stderr)
            payload = json.loads(retry.stdout)
            parents = self.git(
                repo, "rev-list", "--parents", "-n", "1", payload["integrate"]
            ).stdout.split()
            self.assertEqual(parents[1], advanced_main)
            self.assertEqual(parents[2], ship_sha)

    def test_integrate_aborts_conflicts_without_touching_the_bound_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            repo = root / "primary"
            repo.mkdir()
            remote = root / "origin.git"
            self.make_publishable_bound_repo(repo, remote)
            _archive_name, ship_sha = self.ship_canonical_bound(repo)
            other = root / "other"
            cloned = self.run_command(
                "git", "clone", "-q", str(remote), str(other), cwd=root
            )
            self.assertEqual(cloned.returncode, 0, cloned.stderr)
            self.git(other, "config", "user.name", "Validation")
            self.git(other, "config", "user.email", "validation@example.invalid")
            (other / ".project" / "STATE.md").write_text("remote-only state\n")
            self.git(other, "add", ".project/STATE.md")
            committed = self.git(other, "commit", "-q", "-m", "diverge main")
            self.assertEqual(committed.returncode, 0, committed.stderr)
            pushed = self.git(other, "push", "-q", "origin", "main")
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            remote_main = self.git(remote, "rev-parse", "main").stdout.strip()

            result = self.integrate(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("conflict", result.stderr.casefold())
            self.assertEqual(self.git(remote, "rev-parse", "main").stdout.strip(), remote_main)
            self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), ship_sha)
            self.assertEqual(self.git(repo, "status", "--porcelain").stdout, "")
            self.assertEqual(
                self.git(repo, "branch", "--list", "gsd-path-integrate/M001").stdout.strip(),
                "",
            )
            self.assertNotIn(
                "refs/heads/gsd-path-integrate/M001",
                self.git(repo, "worktree", "list", "--porcelain").stdout,
            )

    def integrate_bound(
        self,
        repo: Path,
        archive_name: str,
        merged_sha: str,
        branch: str = "gsd-path/M001",
        tag: bool = True,
        tag_sha=None,
        update_origin: bool = True,
        subject: Optional[str] = None,
        body: Optional[str] = None,
        default_branch: str = "main",
    ) -> str:
        remote_ref = f"refs/remotes/origin/{default_branch}"
        remote_default = self.git(repo, "rev-parse", remote_ref).stdout.strip()
        detach = self.git(repo, "checkout", "-q", "--detach", remote_default)
        self.assertEqual(detach.returncode, 0, detach.stderr)
        arguments = [
            "merge",
            "--no-ff",
            "-m",
            subject or pipeline_git.integrate_subject(archive_name, default_branch),
            "-m",
            body
            or pipeline_git.integrate_commit_body(
                f".project/archive/{archive_name}",
                merged_sha,
                default_branch,
                branch,
            ),
        ]
        merge = self.git(repo, *arguments, merged_sha)
        self.assertEqual(merge.returncode, 0, merge.stderr)
        merge_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
        back = self.git(repo, "checkout", "-q", branch)
        self.assertEqual(back.returncode, 0, back.stderr)
        if tag:
            tagged = self.git(
                repo,
                "tag",
                "-a",
                "-m",
                f"milestone {archive_name}",
                f"milestone/{archive_name}",
                tag_sha or merge_sha,
            )
            self.assertEqual(tagged.returncode, 0, tagged.stderr)
        if update_origin:
            updated = self.git(repo, "update-ref", remote_ref, merge_sha)
            self.assertEqual(updated.returncode, 0, updated.stderr)
            published_branch = self.git(
                repo, "update-ref", f"refs/remotes/origin/{branch}", merged_sha
            )
            self.assertEqual(published_branch.returncode, 0, published_branch.stderr)
            if tag:
                tag_object = self.git(
                    repo, "rev-parse", f"refs/tags/milestone/{archive_name}"
                ).stdout.strip()
                published_tag = self.git(
                    repo,
                    "update-ref",
                    f"refs/remotes/origin/tags/milestone/{archive_name}",
                    tag_object,
                )
                self.assertEqual(published_tag.returncode, 0, published_tag.stderr)
        return merge_sha

    def validate_integrated(self, repo: Path, slug: str = "demo") -> subprocess.CompletedProcess[str]:
        return self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "validate-integrated",
            "--repo",
            str(repo),
            "--slug",
            slug,
            cwd=PROJECT_ROOT,
        )

    def test_validate_integrated_accepts_integrated_ship(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            merge_sha = self.integrate_bound(repo, archive_name, ship_sha)

            result = self.validate_integrated(repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["archive"], f".project/archive/{archive_name}")
            self.assertEqual(payload["commit"], ship_sha)
            self.assertEqual(payload["integrate"], merge_sha)
            self.assertEqual(payload["tag"], f"milestone/{archive_name}")

    def test_validate_integrated_rejects_duplicate_canonical_merges(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            first = self.integrate_bound(repo, archive_name, ship_sha)
            tree = self.git(repo, "rev-parse", f"{first}^{{tree}}").stdout.strip()
            duplicate = self.git(
                repo,
                "commit-tree",
                tree,
                "-p",
                first,
                "-p",
                ship_sha,
                "-m",
                pipeline_git.integrate_subject(archive_name, "main"),
                "-m",
                pipeline_git.integrate_commit_body(
                    f".project/archive/{archive_name}",
                    ship_sha,
                    "main",
                    "gsd-path/M001",
                ),
            ).stdout.strip()
            updated = self.git(
                repo, "update-ref", "refs/remotes/origin/main", duplicate
            )
            self.assertEqual(updated.returncode, 0, updated.stderr)

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("multiple commits", result.stderr)

    def test_validate_integrated_rejects_a_missing_merge_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, _ = self.ship_bound(repo)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            expected = pipeline_git.integrate_subject(archive_name, "main")
            self.assertIn(f"no commit with exact subject {expected!r}", result.stderr)

    def test_validate_integrated_rejects_a_missing_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            self.integrate_bound(repo, archive_name, ship_sha, tag=False)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"missing milestone tag: milestone/{archive_name}", result.stderr)

    def test_validate_integrated_rejects_a_tag_pointing_elsewhere(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            baseline = self.git(repo, "rev-parse", "main").stdout.strip()
            self.integrate_bound(repo, archive_name, ship_sha, tag_sha=baseline)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("does not point at the integration merge", result.stderr)

    def test_validate_integrated_rejects_a_wrong_second_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            base = self.git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip()
            self.git(repo, "checkout", "-q", "-b", "decoy", base)
            (repo / "decoy.txt").write_text("decoy\n")
            self.git(repo, "add", "decoy.txt")
            decoy = self.git(repo, "commit", "-q", "-m", "decoy product work")
            self.assertEqual(decoy.returncode, 0, decoy.stderr)
            decoy_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            back = self.git(repo, "checkout", "-q", "gsd-path/M001")
            self.assertEqual(back.returncode, 0, back.stderr)
            self.integrate_bound(repo, archive_name, decoy_sha)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("integration merge second parent is not the ship commit", result.stderr)

    def test_validate_integrated_rejects_a_merge_not_on_the_remote_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            self.integrate_bound(repo, archive_name, ship_sha, update_origin=False)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            expected = pipeline_git.integrate_subject(archive_name, "main")
            self.assertIn(
                f"no commit with exact subject {expected!r} "
                "in origin/main first-parent history",
                result.stderr,
            )

    def test_find_ship_commit_uses_first_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.git(repo, "init", "-q", "-b", "gsd-path/demo")
            self.git(repo, "config", "user.name", "Validation")
            self.git(repo, "config", "user.email", "validation@example.invalid")

            def dated_commit(filename: str, message: str, date: str) -> str:
                (repo / filename).write_text(f"{message}\n")
                self.git(repo, "add", filename)
                env = dict(os.environ, GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
                committed = subprocess.run(
                    ("git", "commit", "-q", "-m", message),
                    cwd=repo,
                    env=env,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(committed.returncode, 0, committed.stderr)
                return self.git(repo, "rev-parse", "HEAD").stdout.strip()

            dated_commit("base.txt", "base", "2026-07-01T00:00:00")
            subject = pipeline_git.ship_subject("001-demo")
            ship_sha = dated_commit("ship.txt", subject, "2026-08-01T00:00:00")
            self.git(repo, "checkout", "-q", "-b", "side", "HEAD~1")
            decoy_sha = dated_commit("decoy.txt", subject, "2026-08-03T00:00:00")
            self.git(repo, "checkout", "-q", "gsd-path/demo")
            env = dict(
                os.environ,
                GIT_AUTHOR_DATE="2026-08-04T00:00:00",
                GIT_COMMITTER_DATE="2026-08-04T00:00:00",
            )
            merged = subprocess.run(
                ("git", "merge", "--no-ff", "-m", "merge side", "side"),
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(merged.returncode, 0, merged.stderr)
            self.assertNotEqual(ship_sha, decoy_sha)

            found = archive_milestone.find_ship_commit(repo.resolve(), "001-demo")
            self.assertEqual(found, ship_sha)

    def test_validate_integrated_accepts_m00n_subjects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.git(repo, "add", ".project")
            ship = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                "ship: M001 — demo",
                "-m",
                f"Archive: .project/archive/001-demo\nReviewed-HEAD: {reviewed_head}",
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            merge_sha = self.integrate_bound(
                repo,
                archive.name,
                ship_sha,
                branch="gsd-path/M001",
                subject="integrate: M001 — merge gsd-path/M001 into main",
                body=(
                    "Archive: .project/archive/001-demo\n"
                    f"Ship: {ship_sha}\n"
                    "Default: main\n"
                    "Branch: gsd-path/M001"
                ),
            )

            result = self.validate_integrated(repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["commit"], ship_sha)
            self.assertEqual(payload["integrate"], merge_sha)

    def test_validate_rejects_canonical_ship_without_required_field_body(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                pipeline_git.ship_subject(archive.name),
                "-m",
                "Notes: not the required ship fields",
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)

            result = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ship commit body", result.stderr)

    def test_validate_strict_loads_committed_state(self) -> None:
        mutations = (
            (
                "duplicate",
                lambda text: text.replace("status: done\n", "status: done\nstatus: done\n"),
                "repeats frontmatter field: status",
            ),
            (
                "extra",
                lambda text: text.replace("archive:", "unexpected: value\narchive:"),
                "unknown fields: unexpected",
            ),
        )
        for label, mutate, expected in mutations:
            with (
                self.subTest(label=label),
                tempfile.TemporaryDirectory() as temporary_directory,
            ):
                repo = Path(temporary_directory)
                self.make_repo(repo)
                archive = self.prepare_archive(repo)
                self.write_manifest(archive)
                self.mark_shipped(repo)
                state_path = repo / ".project" / "STATE.md"
                state_path.write_text(mutate(state_path.read_text()))
                self.git(repo, "add", ".project")
                ship = self.commit_ship(repo, archive)
                self.assertEqual(ship.returncode, 0, ship.stderr)

                result = self.run_command(
                    sys.executable,
                    str(ARCHIVE_SCRIPT),
                    "validate",
                    "--repo",
                    str(repo),
                    cwd=PROJECT_ROOT,
                )

                self.assertNotEqual(result.returncode, 0)
                self.assertIn("STATE.md is invalid", result.stderr)
                self.assertIn(expected, result.stderr)

    def test_validate_rejects_legacy_ship_subject_for_current_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_repo(repo)
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.commit_ship(
                repo,
                archive,
                subject=pipeline_git.legacy_ship_subject(archive.name),
                body="arbitrary legacy body",
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)

            result = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "validate",
                "--repo",
                str(repo),
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(pipeline_git.ship_subject(archive.name), result.stderr)

    def test_validate_integrated_rejects_canonical_merge_without_required_field_body(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            self.git(repo, "add", ".project")
            ship = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                pipeline_git.ship_subject(archive.name),
                "-m",
                pipeline_git.ship_commit_body(
                    f".project/archive/{archive.name}",
                    self.git(repo, "rev-parse", "HEAD").stdout.strip(),
                ),
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.integrate_bound(
                repo,
                archive.name,
                ship_sha,
                branch="gsd-path/M001",
                subject=pipeline_git.integrate_subject(archive.name, "main"),
                body=(
                    "Archive: wrong\n"
                    "Ship: wrong\n"
                    "Default: main\n"
                    "Branch: gsd-path/M001"
                ),
            )

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("integration commit body", result.stderr)

    def test_validate_integrated_rejects_legacy_merge_for_current_milestone(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo)
            archive_name, ship_sha = self.ship_bound(repo)
            self.integrate_bound(
                repo,
                archive_name,
                ship_sha,
                subject=pipeline_git.legacy_integrate_subject(archive_name),
                body="arbitrary legacy body",
            )

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(
                pipeline_git.integrate_subject(archive_name, "main"), result.stderr
            )

    def test_validate_integrated_rejects_bound_branch_as_default(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive_name, ship_sha = self.ship_bound(repo)
            pointed = self.git(
                repo, "update-ref", "refs/remotes/origin/gsd-path/M001", ship_sha
            )
            self.assertEqual(pointed.returncode, 0, pointed.stderr)
            linked = self.git(
                repo,
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/gsd-path/M001",
            )
            self.assertEqual(linked.returncode, 0, linked.stderr)

            result = self.validate_integrated(repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("is the remote default", result.stderr)

    def test_validate_integrated_rejects_remote_default_other_than_main(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            default_sha = self.git(
                repo, "rev-parse", "refs/remotes/origin/main"
            ).stdout.strip()
            pointed = self.git(
                repo, "update-ref", "refs/remotes/origin/master", default_sha
            )
            self.assertEqual(pointed.returncode, 0, pointed.stderr)
            linked = self.git(
                repo,
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/master",
            )
            self.assertEqual(linked.returncode, 0, linked.stderr)
            archive_name, ship_sha = self.ship_bound(repo)
            self.integrate_bound(
                repo,
                archive_name,
                ship_sha,
                branch="gsd-path/M001",
                subject=pipeline_git.integrate_subject(archive_name, "master"),
                body=pipeline_git.integrate_commit_body(
                    f".project/archive/{archive_name}",
                    ship_sha,
                    "master",
                    "gsd-path/M001",
                ),
                default_branch="master",
            )

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("remote default must be main", result.stderr)

    def test_prepare_rejects_noncanonical_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="feature/not-a-bound-branch")
            result = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "prepare",
                "--repo",
                str(repo),
                "--slug",
                "demo",
                cwd=PROJECT_ROOT,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("STATE.md is invalid", result.stderr)

    def test_validate_integrated_rejects_unpublished_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.git(repo, "add", ".project")
            ship = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                pipeline_git.ship_subject(archive.name),
                "-m",
                pipeline_git.ship_commit_body(
                    f".project/archive/{archive.name}",
                    reviewed_head,
                ),
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.integrate_bound(
                repo,
                archive.name,
                ship_sha,
                branch="gsd-path/M001",
                subject=pipeline_git.integrate_subject(archive.name, "main"),
                body=pipeline_git.integrate_commit_body(
                    f".project/archive/{archive.name}",
                    ship_sha,
                    "main",
                    "gsd-path/M001",
                ),
            )
            deleted = self.git(
                repo, "update-ref", "-d", "refs/remotes/origin/gsd-path/M001"
            )
            self.assertEqual(deleted.returncode, 0, deleted.stderr)

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing published bound branch", result.stderr)

    def test_validate_integrated_rejects_unpublished_milestone_tag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_bound_repo(repo, branch="gsd-path/M001")
            archive = self.prepare_archive(repo)
            self.write_manifest(archive)
            self.mark_shipped(repo)
            reviewed_head = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.git(repo, "add", ".project")
            ship = self.git(
                repo,
                "commit",
                "-q",
                "-m",
                pipeline_git.ship_subject(archive.name),
                "-m",
                pipeline_git.ship_commit_body(
                    f".project/archive/{archive.name}",
                    reviewed_head,
                ),
            )
            self.assertEqual(ship.returncode, 0, ship.stderr)
            ship_sha = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            self.integrate_bound(
                repo,
                archive.name,
                ship_sha,
                branch="gsd-path/M001",
                subject=pipeline_git.integrate_subject(archive.name, "main"),
                body=pipeline_git.integrate_commit_body(
                    f".project/archive/{archive.name}",
                    ship_sha,
                    "main",
                    "gsd-path/M001",
                ),
            )
            deleted = self.git(
                repo, "update-ref", "-d", "refs/remotes/origin/tags/milestone/001-demo"
            )
            self.assertEqual(deleted.returncode, 0, deleted.stderr)

            result = self.validate_integrated(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("missing published milestone tag", result.stderr)

    def test_refresh_origin_updates_stale_origin_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            remote = root / "remote.git"
            remote.mkdir()
            self.git(remote, "init", "-q", "--bare", "-b", "main")
            clone = root / "clone"
            cloned = self.run_command(
                "git", "clone", "-q", str(remote), str(clone), cwd=root
            )
            self.assertEqual(cloned.returncode, 0, cloned.stderr)
            self.git(clone, "config", "user.name", "Validation")
            self.git(clone, "config", "user.email", "validation@example.invalid")
            (clone / "README").write_text("main\n")
            self.git(clone, "add", "README")
            self.git(clone, "commit", "-q", "-m", "seed main")
            pushed = self.git(clone, "push", "-q", "-u", "origin", "main")
            self.assertEqual(pushed.returncode, 0, pushed.stderr)
            self.git(clone, "checkout", "-q", "-b", "gsd-path/M001")
            (clone / "work.txt").write_text("work\n")
            self.git(clone, "add", "work.txt")
            self.git(clone, "commit", "-q", "-m", "bound work")
            self.git(clone, "push", "-q", "-u", "origin", "gsd-path/M001")
            defaulted = self.run_command(
                "git",
                "--git-dir",
                str(remote),
                "symbolic-ref",
                "HEAD",
                "refs/heads/gsd-path/M001",
                cwd=root,
            )
            self.assertEqual(defaulted.returncode, 0, defaulted.stderr)
            fetched = self.git(clone, "fetch", "-q", "origin")
            self.assertEqual(fetched.returncode, 0, fetched.stderr)
            stale = self.git(
                clone,
                "symbolic-ref",
                "refs/remotes/origin/HEAD",
                "refs/remotes/origin/main",
            )
            self.assertEqual(stale.returncode, 0, stale.stderr)
            self.assertEqual(
                self.git(clone, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
                .stdout.strip(),
                "origin/main",
            )

            refreshed = self.run_command(
                sys.executable,
                str(ARCHIVE_SCRIPT),
                "refresh-origin",
                "--repo",
                str(clone),
                cwd=PROJECT_ROOT,
            )
            self.assertEqual(refreshed.returncode, 0, refreshed.stderr)
            self.assertEqual(
                json.loads(refreshed.stdout)["remote_default"],
                "origin/gsd-path/M001",
            )
            self.assertEqual(
                self.git(clone, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
                .stdout.strip(),
                "origin/gsd-path/M001",
            )

    def make_build_repo(self, root: Path, status: str = "blocked") -> None:
        self.git(root, "init", "-q", "-b", "gsd-path/M001")
        self.git(root, "config", "user.name", "Validation")
        self.git(root, "config", "user.email", "validation@example.invalid")

        project = root / ".project"
        for directory in ("intent", "research", "plan", "tasks", "review"):
            (project / directory).mkdir(parents=True, exist_ok=True)

        (project / "STATE.md").write_text(
            f"""---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: build
status: {status}
branch: gsd-path/M001
archive: null
---

# Project State

## Log
- 2026-08-01 — build — wave 1 {status}
"""
        )
        (project / "CHARTER.md").write_text("# Charter\n")
        (project / "ROADMAP.md").write_text(
            "# Roadmap\n\n### M001 — demo\n\nStatus: active\n"
        )
        (project / "intent" / "INTENT.md").write_text("# Intent\n")
        (project / "research" / "SYNTHESIS.md").write_text("# Synthesis\n")
        (project / "plan" / "PLAN.md").write_text("# Plan\n\n## Wave 1 — demo\n")
        (project / "tasks" / "T001-demo.md").write_text("# Task\n")
        (project / "review" / "wave-1.cycle1.md").write_text(
            """# Review — wave 1, cycle 1

Wave verdict: blocked
Cycle: 1
Depth: full
Tasks reviewed: 1

## T001 — demo: fail

- ❌ demo broken — focused Verify failed
"""
        )

        self.git(root, "add", ".project")
        baseline = self.git(root, "commit", "-q", "-m", "baseline")
        self.assertEqual(baseline.returncode, 0, baseline.stderr)

    def run_abandon(
        self, repo: Path, slug: str = "demo", reason: str = "User ruled: stop"
    ) -> subprocess.CompletedProcess[str]:
        return self.run_command(
            sys.executable,
            str(ARCHIVE_SCRIPT),
            "abandon",
            "--repo",
            str(repo),
            "--slug",
            slug,
            "--reason",
            reason,
            cwd=PROJECT_ROOT,
        )

    def test_abandon_archives_partial_build_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            project = repo / ".project"
            self.write_discussion(project / "discuss", phase_status="build/blocked")

            result = self.run_abandon(repo, reason="User ruled: stop this milestone")

            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(payload["archive"], ".project/archive/001-demo")
            self.assertEqual(
                self.git(repo, "rev-parse", "HEAD").stdout.strip(), payload["commit"]
            )
            archive = project / "archive" / "001-demo"
            for relative in (
                "intent/INTENT.md",
                "research/SYNTHESIS.md",
                "plan/PLAN.md",
                "tasks/T001-demo.md",
                "review/wave-1.cycle1.md",
                "discuss/DIALOGUE.md",
                "discuss/ANSWERS.md",
            ):
                self.assertTrue((archive / relative).is_file(), relative)
            self.assertFalse((archive / "review" / "FINAL.md").exists())
            self.assertFalse((project / "discuss").exists())

            manifest = (archive / "MANIFEST.md").read_text()
            self.assertIn("# Archive — 001-demo", manifest)
            self.assertIn("Milestone: demo", manifest)
            self.assertRegex(manifest, r"(?m)^Abandoned: \d{4}-\d{2}-\d{2}$")
            self.assertIn("Reason: User ruled: stop this milestone", manifest)
            for ship_field in ("Shipped:", "Final verdict:", "Waves:", "Carried forward:"):
                self.assertNotIn(ship_field, manifest)
            self.assertIn("## Contents", manifest)
            self.assertIn("## Notes", manifest)
            self.assertIn("- intent/INTENT.md", manifest)
            self.assertIn("- review/wave-1.cycle1.md", manifest)

            active = sorted(path.name for path in project.iterdir())
            self.assertEqual(
                active,
                ["CHARTER.md", "LESSONS.md", "ROADMAP.md", "STATE.md", "archive"],
            )
            state = (project / "STATE.md").read_text()
            self.assertIn("phase: roadmap", state)
            self.assertIn("status: active", state)
            self.assertIn("milestone: null", state)
            self.assertIn("archive: null", state)
            roadmap = (project / "ROADMAP.md").read_text()
            self.assertIn("Status: abandoned", roadmap)
            self.assertIn("Archive: .project/archive/001-demo", roadmap)
            self.assertIn(
                "- 001-demo — abandoned: User ruled: stop this milestone",
                (project / "LESSONS.md").read_text(),
            )
            self.assertEqual(
                self.git(repo, "log", "-1", "--format=%s").stdout.strip(),
                "build: abandon milestone demo",
            )
            self.assertEqual(
                self.git(repo, "log", "-1", "--format=%b").stdout.strip(),
                "Why: User ruled: stop this milestone",
            )

    def test_abandon_accepts_deep_review_lens_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            review = repo / ".project" / "review"
            (review / "wave-1.cycle1.adversarial.md").write_text("# Adversarial lens\n")

            result = self.run_abandon(repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            archive = repo / ".project" / "archive" / "001-demo"
            self.assertTrue(
                (archive / "review" / "wave-1.cycle1.adversarial.md").is_file()
            )

    def test_abandon_accepts_active_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo, status="active")

            result = self.run_abandon(repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["archive"], ".project/archive/001-demo"
            )

    def test_abandon_completed_retry_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)

            first = self.run_abandon(repo)
            retry = self.run_abandon(repo)

            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(retry.returncode, 0, retry.stderr)
            first_payload = json.loads(first.stdout)
            retry_payload = json.loads(retry.stdout)
            self.assertEqual(retry_payload["commit"], first_payload["commit"])
            self.assertEqual(retry_payload["archive"], first_payload["archive"])
            self.assertEqual(retry_payload["status"], "already-complete")

    def test_abandon_resume_completes_interrupted_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            project = repo / ".project"
            archive = project / "archive" / "001-demo"
            archive.mkdir(parents=True)
            shutil.move(str(project / "intent"), str(archive / "intent"))
            state_path = project / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace(
                    "archive: null", "archive: .project/archive/001-demo"
                )
            )

            result = self.run_abandon(repo)

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                json.loads(result.stdout)["archive"], ".project/archive/001-demo"
            )
            self.assertEqual(
                [path.name for path in (project / "archive").iterdir()], ["001-demo"]
            )
            self.assertTrue((archive / "intent" / "INTENT.md").is_file())
            self.assertTrue((archive / "plan" / "PLAN.md").is_file())
            self.assertTrue((archive / "MANIFEST.md").is_file())
            self.assertFalse((project / "plan").exists())
            self.assertIn("phase: roadmap", state_path.read_text())
            self.assertIn("archive: null", state_path.read_text())

    def test_abandon_resumes_after_archive_before_state_transition(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            with mock.patch.object(
                archive_milestone,
                "transition_state",
                side_effect=archive_milestone.PipelineStateError("injected crash"),
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError, "injected crash"
                ):
                    archive_milestone.abandon(repo, "demo", "User ruled: stop")

            journal = archive_milestone.abandon_journal_path(repo)
            self.assertTrue(journal.is_file())
            state = (repo / ".project" / "STATE.md").read_text()
            self.assertIn("phase: build", state)
            self.assertIn("archive: .project/archive/001-demo", state)

            retry = self.run_abandon(repo)

            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertFalse(journal.exists())
            self.assertIn("phase: roadmap", (repo / ".project" / "STATE.md").read_text())

    def test_abandon_resumes_after_state_transition_before_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            with mock.patch.object(
                archive_milestone,
                "isolation_checkpoint",
                side_effect=archive_milestone.IsolationError("injected crash"),
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError, "injected crash"
                ):
                    archive_milestone.abandon(repo, "demo", "User ruled: stop")

            journal = archive_milestone.abandon_journal_path(repo)
            self.assertTrue(journal.is_file())
            state = (repo / ".project" / "STATE.md").read_text()
            self.assertIn("phase: roadmap", state)
            self.assertIn("archive: null", state)

            retry = self.run_abandon(repo)

            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertFalse(journal.exists())

    def test_abandon_resume_rejects_a_different_ruling(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            with mock.patch.object(
                archive_milestone,
                "transition_state",
                side_effect=archive_milestone.PipelineStateError("injected crash"),
            ):
                with self.assertRaises(archive_milestone.ArchiveError):
                    archive_milestone.abandon(repo, "demo", "User ruled: stop")

            retry = self.run_abandon(repo, reason="User ruled: continue")

            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("differs from journal", retry.stderr)

    def test_abandon_checkpoint_recovery_rejects_manifest_reason_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            with mock.patch.object(
                archive_milestone,
                "isolation_checkpoint",
                side_effect=archive_milestone.IsolationError("injected crash"),
            ):
                with self.assertRaises(archive_milestone.ArchiveError):
                    archive_milestone.abandon(repo, "demo", "User ruled: stop")
            manifest = repo / ".project" / "archive" / "001-demo" / "MANIFEST.md"
            manifest.write_text(
                manifest.read_text().replace(
                    "Reason: User ruled: stop", "Reason: different ruling"
                )
            )

            retry = self.run_abandon(repo)

            self.assertNotEqual(retry.returncode, 0)
            self.assertIn("manifest Reason:", retry.stderr)

    def test_abandon_resumes_after_checkpoint_before_journal_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            original_checkpoint = archive_milestone.isolation_checkpoint

            def commit_then_crash(*args, **kwargs):
                original_checkpoint(*args, **kwargs)
                raise archive_milestone.IsolationError("injected post-commit crash")

            with mock.patch.object(
                archive_milestone,
                "isolation_checkpoint",
                side_effect=commit_then_crash,
            ):
                with self.assertRaisesRegex(
                    archive_milestone.ArchiveError, "post-commit crash"
                ):
                    archive_milestone.abandon(repo, "demo", "User ruled: stop")

            committed = self.git(repo, "rev-parse", "HEAD").stdout.strip()
            journal = archive_milestone.abandon_journal_path(repo)
            self.assertTrue(journal.is_file())

            retry = self.run_abandon(repo)

            self.assertEqual(retry.returncode, 0, retry.stderr)
            self.assertEqual(json.loads(retry.stdout)["status"], "already-complete")
            self.assertEqual(self.git(repo, "rev-parse", "HEAD").stdout.strip(), committed)
            self.assertFalse(journal.exists())

    def test_abandon_rejects_missing_roadmap(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            (repo / ".project" / "ROADMAP.md").unlink()

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ROADMAP", result.stderr)
            self.assertTrue((repo / ".project" / "plan" / "PLAN.md").is_file())

    def test_abandon_rejects_m000_roadmap_entry_without_project_mutation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            roadmap = repo / ".project" / "ROADMAP.md"
            roadmap.write_text(
                roadmap.read_text()
                + "\n### M000 — invalid\n\nStatus: pending\nArchive: null\n"
            )
            before = self.snapshot_worktree(repo)

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("ROADMAP milestone number must be >= 1", result.stderr)
            self.assertEqual(self.snapshot_worktree(repo), before)

    def test_abandon_rejects_non_build_phase(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace("phase: build", "phase: plan")
            )

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("phase", result.stderr)
            self.assertTrue((repo / ".project" / "intent" / "INTENT.md").is_file())

    def test_abandon_rejects_missing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            (repo / ".project" / "plan" / "PLAN.md").unlink()

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("plan/PLAN.md", result.stderr)

    def test_abandon_rejects_missing_intent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            (repo / ".project" / "intent" / "INTENT.md").unlink()

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("intent/INTENT.md", result.stderr)

    def test_abandon_rejects_mismatched_persisted_slug(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)
            state_path = repo / ".project" / "STATE.md"
            state_path.write_text(
                state_path.read_text().replace(
                    "archive: null", "archive: .project/archive/001-other"
                )
            )

            result = self.run_abandon(repo)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("archive does not match milestone", result.stderr)

    def test_abandon_collapses_multiline_reason(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            self.make_build_repo(repo)

            result = self.run_abandon(repo, reason="stop this\nmilestone now")

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = (
                repo / ".project" / "archive" / "001-demo" / "MANIFEST.md"
            ).read_text()
            reason_lines = [
                line for line in manifest.splitlines() if line.startswith("Reason:")
            ]
            self.assertEqual(reason_lines, ["Reason: stop this milestone now"])


if __name__ == "__main__":
    unittest.main()
