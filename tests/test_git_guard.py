import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import git_guard

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "git_guard.py"
TASK_FILE = (
    "---\nid: T001\ntitle: Demo task\nwave: 1\ndeps: []\nstatus: in-progress\n"
    "agent: coder\nbase: null\nworktree: active\ntask_branch: active\n"
    "files:\n  - app.py\n---\ntask T001\n"
)


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

    def head(self):
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

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
        reviewed_head = self.head()
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
        # The stored body keeps inner blank lines, and archive_milestone.py
        # validate rejects them, so the guard must reject them before the commit.
        split = self.run_guard("ship: M002 — next", body.replace("\nReviewed-HEAD", "\n\nReviewed-HEAD"))
        self.assertEqual(1, split.returncode)
        self.assertIn("ship commit body does not match", split.stderr)
        cleaned = self.run_guard("ship: M002 — next", "# comment\n" + body.replace("\n", "  \n") + "\n\n")
        self.assertEqual(0, cleaned.returncode, cleaned.stderr)
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
        reviewed_head = self.head()
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
        reviewed_head = self.head()
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
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\narchive: null\nnote: stale\n---\n", encoding="utf-8"
        )
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

    def test_hooks_allow_the_first_commit_on_an_unborn_head(self):
        repo = Path(self.temporary.name) / "fresh"
        repo.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
        hooks = repo / ".git" / "hooks"
        (hooks / "pre-commit").write_text(
            f'#!/bin/sh\nexec "{sys.executable}" "{SCRIPT}" pre-commit\n',
            encoding="utf-8",
        )
        (hooks / "pre-commit").chmod(0o755)
        (repo / "README.md").write_text("first\n", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

        result = subprocess.run(
            ["git", "-c", "user.email=test@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "chore: first commit"],
            cwd=repo,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)

    def test_hooks_allow_a_canonical_integration_merge_to_add_the_archive(self):
        self.git("config", "init.defaultBranch", "main")
        self.assert_integration_merge_allowed("main")

    def test_integration_merge_honors_a_configured_default_branch(self):
        self.git("config", "init.defaultBranch", "trunk")
        self.assert_integration_merge_allowed("trunk")

    def test_integration_merge_honors_the_origin_default_branch(self):
        self.git("config", "init.defaultBranch", "main")
        self.git("branch", "-m", "develop")
        self.git("update-ref", "refs/remotes/origin/develop", "HEAD")
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/develop")
        self.assert_integration_merge_allowed("develop")

    def assert_integration_merge_allowed(self, default):
        self.git("branch", "-m", default)
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
        self.git("checkout", "-q", default)
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
                f"integrate: M002 — merge gsd-path/M002 into {default}",
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

    def enter_build(self, phase="build", status="active"):
        self.git("branch", "-m", "gsd-path/M002")
        tasks = self.repo / ".project" / "tasks"
        tasks.mkdir()
        (tasks / "T001-demo.md").write_text(TASK_FILE, encoding="utf-8")
        return self.write_state(phase, status, subject="build: enter build")

    def write_state(self, phase, status, archive="null", subject=None):
        (self.repo / ".project" / "STATE.md").write_text(
            "---\npipeline: gsd-path/v2\nproject: demo\nmilestone: next\n"
            f"phase: {phase}\nstatus: {status}\nbranch: gsd-path/M002\narchive: {archive}\n---\n",
            encoding="utf-8",
        )
        self.git("add", "-A")
        self.commit(subject or f"router: enter {phase}/{status}")
        return self.head()

    def run_pre_push(self, *lines):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "pre-push", "origin", "https://example.invalid/r.git"],
            cwd=self.repo,
            capture_output=True,
            text=True,
            input="".join(line + "\n" for line in lines),
        )

    def stage_product_change(self):
        (self.repo / "app.py").write_text("print('landed')\n", encoding="utf-8")
        self.git("add", "-A")

    def stamp_task(self, base):
        """Rewrite the task file the way isolation.py land stamps a landed task."""
        task = self.repo / ".project" / "tasks" / "T001-demo.md"
        text = task.read_text()
        for field, value in (
            ("status", "done"), ("base", base), ("worktree", "null"), ("task_branch", "null")
        ):
            text = re.sub(rf"^{field}: .*$", f"{field}: {value}", text, count=1, flags=re.M)
        task.write_text(text + "landed\n", encoding="utf-8")

    def landing_body(self, base, *paths):
        return f"Task: .project/tasks/T001-demo.md\nBase: {base}\nFiles:\n" + "\n".join(
            f"- {path}" for path in sorted((".project/tasks/T001-demo.md", *paths))
        )

    def test_build_blocks_direct_and_forged_product_commits(self):
        head = self.enter_build(status="blocked")
        self.stage_product_change()
        result = self.run_guard("feat(app): change app directly")
        self.assertEqual(1, result.returncode)
        self.assertIn("isolation.py land", result.stderr)

        forged = self.run_guard("T001: Demo task")
        self.assertEqual(1, forged.returncode)
        self.assertIn("Base: must be", forged.stderr)

        task = self.repo / ".project" / "tasks" / "T001-demo.md"
        task.write_text(task.read_text().replace("in-progress", "done"), encoding="utf-8")
        self.git("add", "-A", "--", ".project/tasks/T001-demo.md")
        unstamped = self.run_guard("T001: Demo task", self.landing_body(head, "app.py"))
        self.assertEqual(1, unstamped.returncode)
        self.assertIn("landed task frontmatter has invalid", unstamped.stderr)

        self.stamp_task(head)
        (self.repo / "extra.py").write_text("print('stray')\n", encoding="utf-8")
        self.git("add", "-A", "--", "extra.py", ".project/tasks/T001-demo.md")
        stray = self.run_guard("T001: Demo task", self.landing_body(head, "app.py", "extra.py"))
        self.assertEqual(1, stray.returncode)
        self.assertIn("undeclared paths: extra.py", stray.stderr)

        retitled = self.run_guard("T001: Other title", self.landing_body(head, "app.py", "extra.py"))
        self.assertIn("expected 'T001: Demo task'", retitled.stderr)

    def test_build_active_allows_landing_and_bookkeeping_commits(self):
        head = self.enter_build()
        self.stage_product_change()
        self.stamp_task(head)
        self.git("add", "-A")
        landing = self.run_guard("T001: Demo task", self.landing_body(head, "app.py"))
        self.assertEqual(0, landing.returncode, landing.stderr)

        self.git("restore", "--staged", ".")
        self.git("checkout", "--", ".")
        (self.repo / ".project" / "STATE.md").write_text(
            (self.repo / ".project" / "STATE.md").read_text() + "log line\n",
            encoding="utf-8",
        )
        self.git("add", ".project/STATE.md")
        bookkeeping = self.run_guard("build: checkpoint bookkeeping")
        self.assertEqual(0, bookkeeping.returncode, bookkeeping.stderr)

    def test_a_task_lands_exactly_once(self):
        head = self.enter_build()
        self.stage_product_change()
        self.stamp_task(head)
        self.git("add", "-A", "--", "app.py", ".project/tasks/T001-demo.md")
        body = self.landing_body(head, "app.py")
        self.git(
            "-c", "user.email=test@example.com", "-c", "user.name=Test",
            "commit", "-q", "-m", "T001: Demo task", "-m", body,
        )

        (self.repo / "app.py").write_text("print('again')\n", encoding="utf-8")
        task = self.repo / ".project" / "tasks" / "T001-demo.md"
        task.write_text(task.read_text() + "more\n", encoding="utf-8")
        self.git("add", "-A", "--", "app.py", ".project/tasks/T001-demo.md")
        again = self.run_guard("T001: Demo task", body)
        self.assertEqual(1, again.returncode)
        self.assertIn("already done at HEAD", again.stderr)

    def test_landing_accepts_a_commented_inline_files_list(self):
        self.enter_build()
        task = self.repo / ".project" / "tasks" / "T001-demo.md"
        task.write_text(
            task.read_text().replace("files:\n  - app.py", "files: ['plan #1.py'] # planning note"),
            encoding="utf-8",
        )
        (self.repo / "plan #1.py").write_text("base\n", encoding="utf-8")
        self.git("add", "-A", "--", ".project/tasks/T001-demo.md", "plan #1.py")
        self.commit("build: declare a quoted path")
        head = self.head()
        (self.repo / "plan #1.py").write_text("done\n", encoding="utf-8")
        self.stamp_task(head)
        self.git("add", "-A", "--", ".project/tasks/T001-demo.md", "plan #1.py")
        landing = self.run_guard("T001: Demo task", self.landing_body(head, "plan #1.py"))
        self.assertEqual(0, landing.returncode, landing.stderr)

    def test_build_entry_commit_must_stay_project_only(self):
        self.enter_build(phase="plan")
        state = self.repo / ".project" / "STATE.md"
        state.write_text(state.read_text().replace("phase: plan", "phase: build"), encoding="utf-8")
        self.stage_product_change()
        result = self.run_guard("build: start plus product")
        self.assertEqual(1, result.returncode)
        self.assertIn("isolation.py land", result.stderr)

    def test_guard_install_artifacts_commit_as_bookkeeping(self):
        self.enter_build()
        (self.repo / ".gsd-path").mkdir()
        (self.repo / ".gsd-path" / "git_guard.py").write_text("# guard\n", encoding="utf-8")
        (self.repo / ".codex").mkdir()
        (self.repo / ".codex" / "hooks.json").write_text("{}\n", encoding="utf-8")
        self.git("add", "-A", "--", ".gsd-path", ".codex")
        result = self.run_guard("router: install guard hooks")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_product_commits_outside_build_are_refused_on_unshipped_lineage(self):
        self.enter_build(phase="define")
        for phase, status in (("plan", "active"), ("ship", "blocked")):
            with self.subTest(phase=phase, status=status):
                self.write_state(phase, status)
                self.stage_product_change()
                result = self.run_guard("fix(app): owner-requested hotfix outside build")
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn(f"STATE is {phase}", result.stderr)
                self.git("reset", "-q", "--hard", "HEAD")
        self.git("checkout", "-q", "-b", "hotfix/m002")  # cut from the bound branch
        self.stage_product_change()
        result = self.run_guard("fix(app): hotfix branch off unshipped lineage")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("STATE is ship", result.stderr)

    def test_pre_commit_refuses_product_files_outside_build_without_a_message(self):
        self.enter_build(phase="ship", status="blocked")
        self.stage_product_change()
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "pre-commit"],
            cwd=self.repo,
            capture_output=True,
            text=True,
        )
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("STATE is ship", result.stderr)

    def test_bookkeeping_commits_pass_outside_build(self):
        self.enter_build(phase="ship", status="blocked")
        (self.repo / ".project" / "note.md").write_text("ok\n", encoding="utf-8")
        self.git("add", "-A")
        result = self.run_guard("router: record final gap")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_shipped_lineage_is_ordinary_work(self):
        self.enter_build(phase="shipped", status="done")
        self.git("checkout", "-q", "-b", "feature/x")  # like a branch cut from main
        self.stage_product_change()
        result = self.run_guard("feat(app): ordinary work after integration")
        self.assertEqual(0, result.returncode, result.stderr)

    def test_closed_branch_refuses_new_work_even_after_state_rewrite(self):
        self.check_closed_branch_install([sys.executable, "-B", str(SCRIPT.with_name("install.py"))])

    def test_closed_branch_node_install(self):
        self.check_closed_branch_install(["node", str(SCRIPT.with_name("install.mjs"))])

    def check_closed_branch_install(self, installer):
        hooks = self.repo / ".gsd-path"
        installed = subprocess.run(
            [*installer, "--hooks-init", "--claude", "--project", str(self.repo)],
            capture_output=True, text=True,
        )
        self.assertEqual(0, installed.returncode, installed.stderr)
        # Fixture history includes deliberate out-of-band STATE rewrites.
        self.git("config", "core.hooksPath", "/dev/null")
        self.enter_build()
        self.write_state("shipped", "done", archive=".project/archive/002-next",
                         subject="ship: M002 — next")
        # Execute installed selection against a real committed roadmap and fetched ref.
        self.git("checkout", "-q", "-b", "fixture/default")
        (self.repo / ".project" / "ROADMAP.md").write_text("### M002 — next\nStatus: shipped\n\n### M003 — later\nStatus: pending\nDepends on: [M002]\n")
        self.git("add", ".project/ROADMAP.md")
        self.commit("fixture: next roadmap")
        base = self.head()
        self.git("update-ref", "refs/remotes/origin/main", base)
        self.git("checkout", "-q", "gsd-path/M002")
        selected = subprocess.run(
            [sys.executable, "-B", str(hooks / "runtime/promote_lookahead.py"), "select-base",
             "--repo", str(self.repo), "--base", base, "--remote-default", "origin/main"],
            capture_output=True, text=True,
        )
        self.assertEqual(0, selected.returncode, selected.stderr)
        self.assertEqual("gsd-path/M003", json.loads(selected.stdout)["branch"])
        for rewritten in (False, True):
            if rewritten:
                self.write_state("build", "active")
            for path in ("app.py", ".project/note.md"):
                (self.repo / path).write_text("new work\n")
                self.git("add", "-A")
                result = self.run_guard("chore: new work")
                with self.subTest(rewritten=rewritten, path=path):
                    self.assertEqual(1, result.returncode, result.stderr)
                    self.assertIn("closed milestone", result.stderr)
            for event in (
                {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / "app.py")}},
                {"tool_name": "Edit", "tool_input": {"file_path": str(self.repo / ".project/note.md")}},
                {"tool_name": "Bash", "tool_input": {"command": "echo new > app.py"}},
                {"tool_name": "Bash", "tool_input": {"command": "cat app.py > other.py"}},
                {"tool_name": "Bash", "tool_input": {"command": "git branch feature/new"}},
                {"tool_name": "Bash", "tool_input": {"command": "git branch -D gsd-path/M002"}},
                {"tool_name": "Bash", "tool_input": {"command": "git worktree add ../elsewhere"}},
                {"tool_name": "Bash", "tool_input": {"command": "git symbolic-ref HEAD refs/heads/main"}},
                {"tool_name": "Bash", "tool_input": {"command": "git cat-file --filters HEAD:app.py"}},
                {"tool_name": "Bash", "tool_input": {"command": "git cat-file --textcon HEAD:app.py"}},
                {"tool_name": "Bash", "tool_input": {"command": "git cat-file --filt HEAD:app.py"}},
                {"tool_name": "Bash", "tool_input": {"command": "git cat-file -p"}},
                {"tool_name": "Bash", "tool_input": {"command": "git cat-file -p HEAD HEAD"}},
                {"tool_name": "Bash", "tool_input": {"command": "git rev-list HEAD"}},
                {"tool_name": "Bash", "tool_input": {"command": "git rev-list --output=app.py HEAD"}},
                {"tool_name": "Bash", "tool_input": {"command": "git for-each-ref refs/heads"}},
                {"tool_name": "Bash", "tool_input": {"command": "git for-each-ref --format='%(signature:grade)' refs/heads"}},
            ):
                result = subprocess.run(
                    [sys.executable, str(hooks / "guard_hook.py")],
                    cwd=self.repo, input=json.dumps(event), capture_output=True, text=True,
                )
                with self.subTest(rewritten=rewritten, event=event):
                    self.assertEqual(2, result.returncode, result.stderr)
                    self.assertIn("closed milestone", result.stderr)

            for command in (
                "git status --short",
                'python3 -B -c "import sys; raise SystemExit(sys.version_info < (3, 9))"',
                "git fetch origin",
                "git rev-parse origin/main",
                "git worktree list --porcelain",
                "git branch -a",
                "git branch --show-current",
                "git symbolic-ref --short HEAD",
                "git cat-file -p HEAD",
                "git cat-file -t HEAD",
                "git cat-file -s HEAD",
                "git cat-file -e HEAD",
                "git ls-tree HEAD",
                "git show-ref --head",
                "git merge-base HEAD HEAD",
                f"python3 -B {hooks}/runtime/promote_lookahead.py select-base --repo {self.repo}",
                f"python3 -B {hooks}/status_runtime.py --repo {self.repo}",
                f"python3 -B {hooks}/runtime/pipeline_diagnose.py diagnose --repo {self.repo}",
                f"python3 -B {hooks}/runtime/archive_milestone.py validate-integrated --repo {self.repo}",
                f"python3 -B {hooks}/runtime/pipeline_git.py bind-next --repo {self.repo}",
            ):
                result = subprocess.run(
                    [sys.executable, str(hooks / "guard_hook.py")], cwd=self.repo,
                    input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command}}),
                    capture_output=True, text=True,
                )
                with self.subTest(allowed=command):
                    self.assertEqual(0, result.returncode, result.stderr)

        with tempfile.TemporaryDirectory() as directory:
            sibling = Path(directory) / "feature"
            self.git("worktree", "add", "-q", "-b", "feature/next", str(sibling))
            (self.repo / "link").symlink_to(sibling / "app.py")
            (self.repo / "dir-link").symlink_to(sibling, target_is_directory=True)
            (sibling / "dest").mkdir()
            (sibling / "dest/app.py").symlink_to(self.repo / "app.py")
            (sibling / "contents").mkdir()
            (sibling / "contents/app.py").symlink_to(self.repo / "app.py")
            (sibling / "safe").mkdir()
            (sibling / "src").mkdir()
            (sibling / "src/app.py").write_text("new\n")
            (sibling / "dest/src").mkdir()
            (sibling / "dest/src/app.py").symlink_to(self.repo / "app.py")
            other_hooks = sibling / ".gsd-path"
            for guard in (hooks / "guard_hook.py", other_hooks / "guard_hook.py"):
                for command, cwd, expected in (
                    (f"echo new > {sibling}/app.py", self.repo, 0),
                    (f"echo new > {self.repo}/app.py", sibling, 2),
                    ("echo new > app.py", sibling, 0),
                    ("echo new > app.py", self.repo, 2),
                    (f"cd {sibling} && echo new > app.py", self.repo, 0),
                    (f"cd {self.repo} && echo new > app.py", sibling, 2),
                    (f"git -C {self.repo} restore --source=HEAD~1 -- app.py", sibling, 2),
                    (f"git -C {self.repo} switch feature/next", sibling, 2),
                    (f"git -C{self.repo} switch feature/next", sibling, 2),
                    (f"git -C {self.repo.parent} -C {self.repo.name} switch feature/next", sibling, 2),
                    (f"git -C {self.repo} status --short", sibling, 0),
                    (f"git -C {self.repo} --work-tree={sibling} switch feature/next", sibling, 2),
                    (f"git --git-dir={self.repo}/.git --work-tree={sibling} switch feature/next", sibling, 2),
                    (f"git --git-dir {self.repo}/.git --work-tree {sibling} restore --source=HEAD -- app.py", sibling, 2),
                    (f"git -C {self.repo} --work-tree={sibling} status --short", sibling, 0),
                    (f"git --git-dir={self.repo}/.git --work-tree={sibling} log -1", sibling, 0),
                    (f"git -C {sibling} --work-tree={self.repo} restore --source=HEAD -- app.py", sibling, 2),

                    (f"git -C {sibling} restore --source=HEAD -- app.py", self.repo, 0),
                    (f"rm {self.repo}/link", sibling, 2),
                    (f"rm {self.repo}/dir-link", sibling, 2),
                    (f"cp {self.repo}/app.py {sibling}/copy.py", sibling, 0),
                    (f"cp {self.repo}/app.py {sibling}", sibling, 0),
                    (f"cp -t {sibling} {self.repo}/app.py", sibling, 0),
                    (f"cp --target-directory={sibling} {self.repo}/app.py", sibling, 0),
                    (f"cp {sibling}/app.py {self.repo}/app.py", sibling, 2),
                    (f"cp {sibling}/app.py {self.repo}/link", sibling, 2),
                    (f'D={sibling}/dest; cp {sibling}/app.py "$D"', sibling, 2),
                    (f'S={sibling}/app.py; D={sibling}/dest; cp "$S" "$D"', sibling, 2),
                    (f'D={sibling}/safe; cp {self.repo}/app.py "$D"', sibling, 0),
                    (f'D={self.repo}; cp {sibling}/app.py "$D"; D={sibling}', sibling, 2),
                    (f"cp -R {sibling}/src {sibling}/dest", sibling, 2),
                    (f"cp -R {sibling}/src {sibling}/safe", sibling, 0),
                    (f"cp -R {sibling}/src/. {sibling}/contents", sibling, 2),
                    (f"cp -R {sibling}/src/. {sibling}/safe", sibling, 0),
                    (f"cp -R {sibling}/src/ {sibling}/contents", sibling, 2),
                    (f"cp -R {sibling}/src/ {sibling}/safe", sibling, 0),
                    (f'export D={sibling}/dest; bash -c \'cp {sibling}/app.py "$D"\'', sibling, 2),

                    (f"cp -- {sibling}/app.py {self.repo}/app.py > {sibling}/copy.log", sibling, 2),
                    (f"cp -- {sibling}/app.py {self.repo}/app.py 2> {sibling}/copy.log", sibling, 2),
                    (f"cp -- {self.repo}/app.py {sibling}/copy.py > {sibling}/copy.log", sibling, 0),
                    (f"cp -- {self.repo}/app.py {sibling}/copy.py > {self.repo}/copy.log", sibling, 2),
                    (f"cp -- {sibling}/app.py > {sibling}/copy.log {self.repo}/app.py", sibling, 2),

                    ("python3 -c 'print(1)'", self.repo, 2),
                    ("git switch feature/next", self.repo, 2),
                    (f"python3 -B {hooks}/runtime/discussion_records.py pending --repo {self.repo}", self.repo, 0 if guard.parent == hooks else 2),
                    (f"python3 -B {hooks}/runtime/discussion_records.py dispose --repo {self.repo}", self.repo, 2),
                ):
                    for supplied in (True, False):
                        with self.subTest(guard=guard, command=command, cwd=cwd, supplied=supplied):
                            result = subprocess.run(
                                [sys.executable, str(guard)], cwd=cwd,
                                input=json.dumps({"tool_name": "Bash", "tool_input": {
                                    "command": command, **({"cwd": str(cwd)} if supplied else {}),
                                }}), capture_output=True, text=True,
                            )
                            self.assertEqual(expected, result.returncode, result.stderr)
            for target in (sibling / "app.py", Path(directory) / "note.md"):
                result = subprocess.run(
                    [sys.executable, str(hooks / "guard_hook.py")], cwd=self.repo,
                    input=json.dumps({"tool_name": "Edit", "tool_input": {"file_path": str(target)}}),
                    capture_output=True, text=True,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_landing_rule_covers_branches_cut_from_the_bound_branch(self):
        self.enter_build()
        self.git("checkout", "-q", "-b", "feature/x")
        self.stage_product_change()
        result = self.run_guard("feat(app): direct commit off the bound branch")
        self.assertEqual(1, result.returncode, result.stderr)
        self.assertIn("not a landing commit", result.stderr)

    def test_pre_push_publishes_milestone_work_only_as_its_ship_commit(self):
        unfinished = self.enter_build(phase="ship", status="blocked")
        ship = self.write_state(
            "shipped", "done", archive=".project/archive/002-next", subject="ship: M002 — next"
        )
        zero = git_guard.NULL_SHA
        bound = "refs/heads/gsd-path/M002"
        other = "refs/heads/hotfix/m002"
        cases = (
            (f"{bound} {unfinished} {bound} {zero}", "moves gsd-path/M002"),
            (f"HEAD {unfinished} {bound} {zero}", "moves gsd-path/M002"),
            (f"{bound} {ship} {bound} {zero}", None),
            (f"{bound} {ship} {bound} {unfinished}", None),
            (f"{bound} {ship} refs/heads/gsd-path/M003 {zero}", "moves gsd-path/M003"),
            (f"refs/heads/gsd-path/M003 {ship} {bound} {zero}", "moves gsd-path/M003"),
            (f"HEAD {ship} refs/heads/gsd-path/M003 {zero}", "moves gsd-path/M003"),
            (f"(delete) {zero} refs/heads/gsd-path/M003 {ship}", "moves gsd-path/M003"),
            (f"(delete) {zero} {bound} {unfinished}", "moves gsd-path/M002"),
            (f"(delete) {zero} {bound} {ship}", None),
            (f"(delete) {zero} {bound} {zero}", None),
            (f"{other} {unfinished} {other} {zero}", "carries unshipped gsd-path/M002 work (ship/blocked)"),
            (f"HEAD {unfinished} {other} {zero}", "carries unshipped"),
            (f"{other} {ship} {other} {zero}", None),
            (f"refs/tags/v1 {ship} refs/tags/v1 {zero}", None),
        )
        for line, expected in cases:
            with self.subTest(line=line):
                result = self.run_pre_push(line)
                self.assertEqual(0 if expected is None else 1, result.returncode, result.stderr)
                if expected:
                    self.assertIn(expected, result.stderr)
        self.assertEqual(0, self.run_pre_push().returncode)
        malformed = self.run_pre_push("refs/heads/x deadbeef")
        self.assertEqual(1, malformed.returncode)
        self.assertIn("inspection failed", malformed.stderr)

    def test_pre_push_rejects_malformed_shas_and_missing_objects(self):
        ref = "refs/heads/x"
        for local_sha, remote_sha in (
            ("not-a-sha", "not-a-sha"),
            ("not-a-sha", git_guard.NULL_SHA),
            (self.head(), "not-a-sha"),
            ("f" * 40, git_guard.NULL_SHA),
        ):
            with self.subTest(local_sha=local_sha, remote_sha=remote_sha):
                result = self.run_pre_push(f"{ref} {local_sha} {ref} {remote_sha}")
                self.assertEqual(1, result.returncode, result.stderr)
                self.assertIn("inspection failed; push blocked", result.stderr)

    def test_pre_push_allows_present_commit_without_state(self):
        self.git("rm", ".project/STATE.md")
        self.commit("chore: remove pipeline state")
        result = self.run_pre_push(
            f"refs/heads/x {self.head()} refs/heads/x {git_guard.NULL_SHA}"
        )
        self.assertEqual(0, result.returncode, result.stderr)

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
