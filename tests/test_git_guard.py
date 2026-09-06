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
