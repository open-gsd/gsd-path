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

    def test_allows_adds_copies_and_renames_into_archive(self):
        entries = [
            ("A", ".project/archive/002-next/MANIFEST.md", None),
            ("C", ".project/archive/001-mvp/DOCS-AUDIT.md", ".project/research/DOCS-AUDIT.md"),
            ("R", ".project/intent/INTENT.md", ".project/archive/002-next/intent/INTENT.md"),
        ]
        self.assertEqual(git_guard.violations(entries, "ship: 002-next"), [])

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

    def run_guard(self, subject):
        message = self.repo / "COMMIT_MSG"
        message.write_text(subject + "\n", encoding="utf-8")
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
        self.install_hooks()
        (self.repo / ".project" / "STATE.md").write_text("state\n", encoding="utf-8")
        self.git("add", "-A")
        self.commit("ship: 001-mvp")

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

    def test_fails_open_outside_git(self):
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
            self.assertEqual(result.returncode, 0)
            self.assertIn("skipped", result.stderr)


if __name__ == "__main__":
    unittest.main()
