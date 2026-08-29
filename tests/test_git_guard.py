import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import git_guard

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git_guard.py"


class ViolationRuleTests(unittest.TestCase):
    """In-process rule matrix; end-to-end git behavior is covered below."""

    def test_blocks_modify_delete_and_rename_out_of_archive(self):
        for entry in (
            ("M", ".project/archive/001-mvp/MANIFEST.md", None),
            ("D", ".project/archive/001-mvp/MANIFEST.md", None),
            ("T", ".project/archive/001-mvp/MANIFEST.md", None),
            ("R", ".project/archive/001-mvp/MANIFEST.md", ".project/x.md"),
        ):
            with self.subTest(entry=entry):
                found = git_guard.violations([entry], "chore: anything")
                self.assertEqual(len(found), 1)
                self.assertIn("read-only", found[0])

    def test_allows_populating_only_the_current_new_ship_archive(self):
        entries = [
            ("A", ".project/archive/002-next/MANIFEST.md", None),
            ("C", ".project/archive/001-mvp/DOCS-AUDIT.md", ".project/research/DOCS-AUDIT.md"),
            ("R", ".project/intent/INTENT.md", ".project/archive/002-next/intent/INTENT.md"),
        ]
        self.assertEqual(
            git_guard.violations(
                entries,
                "ship: 002-next",
                {".project/archive/001-mvp"},
                ".project/archive/002-next",
            ),
            [],
        )

    def test_blocks_every_destination_write_into_an_existing_archive(self):
        existing = {".project/archive/001-mvp"}
        for entry in (
            ("A", ".project/archive/001-mvp/late.txt", None),
            ("C", "app.py", ".project/archive/001-mvp/copy.py"),
            ("R", "app.py", ".project/archive/001-mvp/moved.py"),
        ):
            with self.subTest(entry=entry):
                found = git_guard.violations(
                    [entry], "feat: archive tamper", existing, ".project/archive/002-next"
                )
                self.assertEqual(1, len(found))
                self.assertIn("read-only", found[0])

    def test_new_archive_requires_current_state_target_and_ship_subject(self):
        entry = ("A", ".project/archive/002-next/MANIFEST.md", None)
        self.assertIn(
            "current STATE.archive",
            git_guard.violations(
                [entry], "ship: 002-next", (), ".project/archive/003-other"
            )[0],
        )
        self.assertIn(
            "requires a ship commit",
            git_guard.violations(
                [entry], "feat: not shipping", (), ".project/archive/002-next"
            )[0],
        )
        self.assertEqual(
            [],
            git_guard.violations(
                [entry], None, (), ".project/archive/002-next"
            ),
        )

    def test_real_integration_merge_may_add_the_current_archive(self):
        entry = ("A", ".project/archive/002-next/MANIFEST.md", None)
        self.assertEqual(
            [],
            git_guard.violations(
                [entry],
                "integrate: M002 — merge gsd-path/M002 into main",
                (),
                ".project/archive/002-next",
                integration_merge=True,
            ),
        )
        blocked = git_guard.violations(
            [entry],
            "integrate: M002 — merge gsd-path/M002 into main",
            (),
            ".project/archive/002-next",
        )
        self.assertIn("requires a ship commit", blocked[0])

    def test_structural_abandon_commit_may_add_its_archive(self):
        entry = ("A", ".project/archive/002-next/MANIFEST.md", None)
        self.assertEqual(
            [],
            git_guard.violations(
                [entry],
                "build: abandon milestone next",
                (),
                ".project/archive/002-next",
                abandon_commit=True,
            ),
        )

    def test_ship_subject_requires_project_only_paths(self):
        entries = [("M", "app.py", None), ("A", ".project/STATE.md", None)]
        found = git_guard.violations(entries, "ship: 002-next")
        self.assertEqual(len(found), 1)
        self.assertIn("only touch .project/", found[0])
        self.assertEqual(git_guard.violations(entries, "feat: change app"), [])

    def test_ship_subject_is_case_insensitive(self):
        entries = [("M", "app.py", None)]
        found = git_guard.violations(entries, "Ship: 002-next")
        self.assertEqual(len(found), 1)
        self.assertIn("only touch .project/", found[0])


class GitGuardEndToEndTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name)
        self.git("init", "-q")
        archived = self.repo / ".project" / "archive" / "001-mvp"
        archived.mkdir(parents=True)
        (archived / "MANIFEST.md").write_text("manifest\n", encoding="utf-8")
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\narchive: null\n---\n",
            encoding="utf-8",
        )
        (self.repo / "app.py").write_text("print('hi')\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("seed")

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments):
        subprocess.run(["git", *arguments], cwd=self.repo, check=True)

    def commit(self, subject):
        self.git(
            "-c", "user.email=test@example.com", "-c", "user.name=Test",
            "commit", "-q", "-m", subject,
        )

    def run_guard(self, subject, body=""):
        message = self.repo / "COMMIT_MSG"
        rendered = subject + "\n"
        if body:
            rendered += "\n" + body.rstrip() + "\n"
        message.write_text(rendered, encoding="utf-8")
        return subprocess.run(
            [sys.executable, str(SCRIPT), str(message)],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

    def test_blocks_staged_archive_tamper_and_allows_clean_commit(self):
        (self.repo / ".project" / "archive" / "001-mvp" / "MANIFEST.md").write_text(
            "tampered\n", encoding="utf-8"
        )
        self.git("add", "-A")
        result = self.run_guard("fix: tweak manifest")
        self.assertEqual(result.returncode, 1)
        self.assertIn("read-only", result.stderr)

        self.git("restore", "--staged", ".")
        self.git("checkout", "--", ".")
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        self.git("add", "-A")
        result = self.run_guard("feat: change app")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_blocks_late_addition_to_a_committed_archive(self):
        (self.repo / ".project" / "archive" / "001-mvp" / "late.txt").write_text(
            "late\n", encoding="utf-8"
        )
        self.git("add", "-A")
        result = self.run_guard("feat: late archive addition")
        self.assertEqual(1, result.returncode)
        self.assertIn("read-only", result.stderr)

    def test_allows_only_the_staged_state_archive_during_ship(self):
        self.git("branch", "-m", "gsd-path/M002")
        archived = self.repo / ".project" / "archive" / "002-next"
        archived.mkdir()
        (archived / "MANIFEST.md").write_text("manifest\n", encoding="utf-8")
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: next\n"
            "phase: shipped\nstatus: done\nbranch: gsd-path/M002\n"
            "archive: .project/archive/002-next\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        reviewed_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        body = (
            "Archive: .project/archive/002-next\n"
            f"Reviewed-HEAD: {reviewed_head}"
        )

        pre_commit = subprocess.run(
            [sys.executable, str(SCRIPT), "pre-commit"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(0, pre_commit.returncode, pre_commit.stderr)
        self.assertEqual(
            0,
            self.run_guard("ship: M002 — next", body).returncode,
        )
        ordinary = self.run_guard("feat: not a ship")
        self.assertEqual(1, ordinary.returncode)
        self.assertIn("requires a ship commit", ordinary.stderr)

    def test_ship_accepts_complete_integration_state(self) -> None:
        self.git("branch", "-m", "gsd-path/M002")
        archived = self.repo / ".project" / "archive" / "002-next"
        archived.mkdir()
        (archived / "MANIFEST.md").write_text("manifest\n", encoding="utf-8")
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: next\n"
            "phase: shipped\nstatus: done\nbranch: gsd-path/M002\n"
            "archive: .project/archive/002-next\n"
            "integration_default: direct\nintegration: direct\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        reviewed_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        body = (
            "Archive: .project/archive/002-next\n"
            f"Reviewed-HEAD: {reviewed_head}"
        )

        result = self.run_guard("ship: M002 — next", body)

        self.assertEqual(0, result.returncode, result.stderr)

        state_path = self.repo / ".project" / "STATE.md"
        state_path.write_text(
            state_path.read_text(encoding="utf-8").replace(
                "integration: direct\n",
                "integration: direct\nintegration_source: default\n",
            ),
            encoding="utf-8",
        )
        self.git("add", ".project/STATE.md")
        result = self.run_guard("ship: M002 — next", body)
        self.assertEqual(0, result.returncode, result.stderr)

    def test_blocks_malformed_or_duplicate_ship_commits(self):
        self.git("branch", "-m", "gsd-path/M002")
        archive = self.repo / ".project/archive/002-next"
        archive.mkdir()
        (archive / "MANIFEST.md").write_text("manifest\n", encoding="utf-8")
        (self.repo / ".project/STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: next\n"
            "phase: shipped\nstatus: done\nbranch: gsd-path/M002\n"
            "archive: .project/archive/002-next\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        reviewed_head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        body = (
            "Archive: .project/archive/002-next\n"
            f"Reviewed-HEAD: {reviewed_head}"
        )

        wrong_subject = self.run_guard("Ship: M002 — next", body)
        self.assertEqual(1, wrong_subject.returncode)
        self.assertIn("subject must be", wrong_subject.stderr)
        wrong_body = self.run_guard("ship: M002 — next", "Archive: wrong")
        self.assertEqual(1, wrong_body.returncode)
        self.assertIn("body does not match", wrong_body.stderr)

        self.commit("seed archive without hooks")
        duplicate = self.run_guard("ship: M002 — next", body)
        self.assertEqual(1, duplicate.returncode)
        self.assertIn("exactly one new current archive", duplicate.stderr)

    def test_blocks_ship_commit_with_non_project_paths(self):
        (self.repo / "app.py").write_text("print('ship')\n", encoding="utf-8")
        (self.repo / ".project" / "STATE.md").parent.mkdir(parents=True, exist_ok=True)
        (self.repo / ".project" / "STATE.md").write_text("state\n", encoding="utf-8")
        self.git("add", "-A")
        result = self.run_guard("ship: 002-next")
        self.assertEqual(result.returncode, 1)
        self.assertIn("only touch .project/", result.stderr)

    def test_pre_commit_blocks_staged_archive_tamper(self):
        (self.repo / ".project" / "archive" / "001-mvp" / "MANIFEST.md").write_text(
            "tampered\n", encoding="utf-8"
        )
        self.git("add", "-A")
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "pre-commit"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("read-only", result.stderr)

    def install_hooks(self):
        hooks = self.repo / ".git" / "hooks"
        pre_commit = hooks / "pre-commit"
        pre_commit.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{SCRIPT}" pre-commit\n',
            encoding="utf-8",
        )
        commit_msg = hooks / "commit-msg"
        commit_msg.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{SCRIPT}" commit-msg "$1"\n',
            encoding="utf-8",
        )
        pre_commit.chmod(0o755)
        commit_msg.chmod(0o755)

    def test_commit_after_ship_commit_is_not_blocked_at_pre_commit(self):
        (self.repo / ".project" / "STATE.md").write_text("state\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("ship: stale previous message")
        self.install_hooks()

        # The next commit runs pre-commit while .git/COMMIT_EDITMSG still
        # holds the previous `ship:` subject; it must not be blocked.
        (self.repo / "app.py").write_text("print('changed')\n", encoding="utf-8")
        self.git("add", "-A")
        result = subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "feat: change app"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # A real ship-scope violation is still blocked at commit-msg.
        (self.repo / "app.py").write_text("print('ship')\n", encoding="utf-8")
        self.git("add", "-A")
        result = subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "ship: 002-next"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("only touch .project/", result.stderr)

    def test_hooks_allow_a_canonical_integration_merge_to_add_the_archive(self):
        self.git("branch", "-m", "main")
        self.git("checkout", "-q", "-b", "gsd-path/M002")
        archive = self.repo / ".project/archive/002-next"
        archive.mkdir()
        (archive / "MANIFEST.md").write_text("manifest\n", encoding="utf-8")
        (self.repo / ".project/STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: next\n"
            "phase: shipped\nstatus: done\nbranch: gsd-path/M002\n"
            "archive: .project/archive/002-next\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        self.commit("ship: M002 — next")
        self.git("checkout", "-q", "main")
        self.git("checkout", "-q", "-b", "gsd-path-integrate/M002")
        self.install_hooks()

        result = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "merge",
                "--no-ff",
                "-m",
                "integrate: M002 — merge gsd-path/M002 into main",
                "gsd-path/M002",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(archive.is_dir())

    def test_hooks_allow_a_canonical_milestone_abandon_commit(self):
        self.git("branch", "-m", "gsd-path/M002")
        archive = self.repo / ".project/archive/002-next"
        archive.mkdir()
        (archive / "MANIFEST.md").write_text(
            "# Archive — 002-next\n\nMilestone: next\nAbandoned: 2026-08-23\n"
            "Reason: User ruled: stop\n",
            encoding="utf-8",
        )
        (self.repo / ".project/ROADMAP.md").write_text(
            "# Roadmap\n\n### M002 — next\n\nStatus: abandoned\n"
            "Archive: .project/archive/002-next\n",
            encoding="utf-8",
        )
        (self.repo / ".project/STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: null\n"
            "phase: roadmap\nstatus: active\nbranch: gsd-path/M002\n"
            "archive: null\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        self.install_hooks()

        ordinary = self.run_guard("build: abandon milestone other")
        self.assertEqual(ordinary.returncode, 1)
        self.assertIn("milestone-abandon", ordinary.stderr)

        wrong_body = self.run_guard(
            "build: abandon milestone next", "Why: a different ruling"
        )
        self.assertEqual(wrong_body.returncode, 1)
        self.assertIn("MANIFEST Reason", wrong_body.stderr)

        result = subprocess.run(
            [
                "git",
                "-c",
                "user.email=test@example.com",
                "-c",
                "user.name=Test",
                "commit",
                "-q",
                "-m",
                "build: abandon milestone next",
                "-m",
                "Why: User ruled: stop",
            ],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(archive.is_dir())

    def test_fails_closed_outside_git(self):
        with tempfile.TemporaryDirectory() as empty:
            message = Path(empty) / "COMMIT_MSG"
            message.write_text("feat: anything\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(message)],
                cwd=empty,
                capture_output=True,
                text=True,
                env={"PATH": "/usr/bin:/bin", "HOME": empty,
                     "GIT_CONFIG_GLOBAL": str(Path(empty) / "nogitconfig"),
                     "GIT_CONFIG_SYSTEM": str(Path(empty) / "nogitconfig")},
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("inspection failed", result.stderr)


if __name__ == "__main__":
    unittest.main()
