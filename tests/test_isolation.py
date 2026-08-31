import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional
from unittest import mock

from scripts import isolation, pipeline_git


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = (
    "---\nid: T001\ntitle: add greeting\nwave: 1\ndeps: []\nstatus: in-progress\n"
    "agent: coder\nbase: null\nworktree: active\ntask_branch: active\n"
    "files:\n  - src/app.py\n---\ntask T001\n"
)
ISOLATION_SCRIPT = PROJECT_ROOT / "scripts" / "isolation.py"
BUNDLED_ISOLATION_SCRIPTS = tuple(
    PROJECT_ROOT / relative
    for relative in (
        "skills/gsd-path/scripts/isolation.py",
        "skills/gsd-path-build/scripts/isolation.py",
        "skills/gsd-path-inspect/scripts/isolation.py",
        "skills/gsd-path-docs-audit/scripts/isolation.py",
        "skills/gsd-path-ship/scripts/isolation.py",
    )
)


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(root), *arguments),
        text=True,
        capture_output=True,
        check=True,
    )
    return result.stdout.strip()


class IsolationTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def init_bound_repo(self, root: Path) -> str:
        git(root, "init", "-b", "gsd-path/M001")
        git(root, "config", "user.email", "test@example.test")
        git(root, "config", "user.name", "Test")
        self.write(root, "src/app.py", "print('base')\n")
        self.write(root, ".project/tasks/T001.md", TASK_FILE)
        git(root, "add", "src/app.py", ".project/tasks/T001.md")
        git(root, "commit", "-q", "-m", "base")
        return git(root, "rev-parse", "HEAD")

    def run_cli(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            (sys.executable, str(ISOLATION_SCRIPT), *arguments),
            text=True,
            capture_output=True,
            check=False,
        )

    def test_serial_isolate_uses_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            result = isolation.isolate_task(repo, base, "T001", 1)
            self.assertEqual(result["mode"], "serial")
            self.assertIsNone(result["task_branch"])
            self.assertEqual(result["worktree"], str(repo.resolve()))
            self.assertFalse(result["detached"])
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")
            listed = git(repo, "worktree", "list")
            self.assertNotIn("detached", listed)

    def test_parallel_isolate_creates_named_branch_not_detached(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            first = isolation.isolate_task(repo, base, "T001", 2)
            second = isolation.isolate_task(repo, base, "T002", 2)
            self.assertEqual(first["mode"], "parallel")
            self.assertEqual(first["task_branch"], "gsd-path-task/T001")
            self.assertFalse(first["detached"])
            worktree = Path(first["worktree"])
            self.assertEqual(git(worktree, "branch", "--show-current"), "gsd-path-task/T001")
            self.assertEqual(git(worktree, "rev-parse", "HEAD"), base)
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")
            listed = git(repo, "worktree", "list")
            self.assertNotIn("detached", listed)
            self.assertIn("gsd-path-task/T002", second["task_branch"])

    def test_parallel_worktree_authorization_requires_isolation_proof(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            pending = (
                TASK_FILE.replace("status: in-progress", "status: pending")
                .replace("agent: coder", "agent: null")
                .replace("worktree: active", "worktree: null")
                .replace("task_branch: active", "task_branch: null")
            )
            (repo / ".project" / "tasks" / "T001.md").write_text(
                pending, encoding="utf-8"
            )
            git(repo, "add", ".project/tasks/T001.md")
            git(repo, "commit", "--amend", "-q", "--no-edit")
            base = git(repo, "rev-parse", "HEAD")
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            worktree = Path(isolated["worktree"])
            task = worktree / ".project" / "tasks" / "T001.md"
            task.write_text(
                pending.replace("status: pending", "status: in-progress")
                .replace("agent: null", "agent: coder")
                .replace("base: null", f"base: {base}")
                .replace("worktree: null", f"worktree: {worktree}")
                .replace("task_branch: null", "task_branch: gsd-path-task/T001"),
                encoding="utf-8",
            )

            self.assertFalse(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )
            task.write_text(pending, encoding="utf-8")
            result = isolation.activate_task(
                worktree,
                base,
                "T001",
                "coder",
                ".project/tasks/T001.md",
                "gsd-path-task/T001",
            )
            self.assertEqual("in-progress", result["status"])
            self.assertTrue(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )
            git(
                worktree,
                "update-ref",
                "-d",
                isolation.task_authorization_ref("T001"),
            )
            self.assertFalse(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )
            recovered = isolation.activate_task(
                worktree,
                base,
                "T001",
                "coder",
                ".project/tasks/T001.md",
                "gsd-path-task/T001",
            )
            self.assertEqual("in-progress", recovered["status"])
            self.assertTrue(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )
            deactivated = isolation.deactivate_task(
                worktree, "T001", "gsd-path-task/T001"
            )
            self.assertEqual("deactivated", deactivated["status"])
            retried = isolation.deactivate_task(
                worktree, "T001", "gsd-path-task/T001"
            )
            self.assertEqual("deactivated", retried["status"])
            self.assertFalse(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )
            self.assertTrue(worktree.exists())
            task.write_text(
                task.read_text(encoding="utf-8").replace(
                    f"worktree: {worktree}", "worktree: /tmp/unowned"
                ),
                encoding="utf-8",
            )
            self.assertFalse(
                isolation.authorized_task_worktree(worktree, "gsd-path/M001")
            )

    def test_parallel_isolation_does_not_remove_a_concurrent_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            branch = isolation.task_branch_name("T001")
            destination = isolation.sidecar_root(repo.resolve(), "task", "T001")
            original = isolation.run_git
            raced = False

            def concurrent_reservation(primary, *arguments, **kwargs):
                nonlocal raced
                if arguments[:2] == ("update-ref", f"refs/heads/{branch}") and not raced:
                    raced = True
                    created = original(
                        primary,
                        "worktree",
                        "add",
                        "-b",
                        branch,
                        str(destination),
                        base,
                    )
                    self.assertEqual(created.returncode, 0, created.stderr)
                    (destination / "other-agent.txt").write_text(
                        "live work\n", encoding="utf-8"
                    )
                return original(primary, *arguments, **kwargs)

            with mock.patch.object(
                isolation, "run_git", side_effect=concurrent_reservation
            ):
                with self.assertRaisesRegex(isolation.IsolationError, "branch already exists"):
                    isolation.create_named_worktree(repo.resolve(), branch, destination, base)

            self.assertTrue(raced)
            self.assertTrue((destination / "other-agent.txt").is_file())
            self.assertEqual(git(destination, "branch", "--show-current"), branch)
            self.assertEqual(
                git(repo, "show-ref", "--verify", f"refs/heads/{branch}").split()[0],
                base,
            )

    def test_parallel_task_isolation_rejects_a_stale_primary_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "advanced\n")
            git(repo, "add", ".project/STATE.md")
            git(repo, "commit", "-q", "-m", "advanced")

            with self.assertRaisesRegex(isolation.IsolationError, "primary HEAD"):
                isolation.isolate_task(repo, base, "T001", 2)

    def test_task_isolation_requires_a_clean_primary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, "src/app.py", "print('dirty')\n")

            with self.assertRaisesRegex(isolation.IsolationError, "clean primary"):
                isolation.isolate_task(repo, base, "T001", 2)

    def test_isolate_verify_names_sidecar_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            result = isolation.isolate_verify(repo, base, "wave-1-cycle-1")
            worktree = Path(result["worktree"])
            self.assertEqual(result["branch"], "gsd-path-verify/wave-1-cycle-1")
            self.assertFalse(result["detached"])
            self.assertEqual(
                git(worktree, "branch", "--show-current"),
                "gsd-path-verify/wave-1-cycle-1",
            )
            self.assertNotIn("detached", git(repo, "worktree", "list"))

    def test_verify_isolation_rejects_a_stale_primary_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "advanced\n")
            git(repo, "add", ".project/STATE.md")
            git(repo, "commit", "-q", "-m", "advanced")

            with self.assertRaisesRegex(isolation.IsolationError, "primary HEAD"):
                isolation.isolate_verify(repo, base, "stale-review")

    def test_verify_isolation_rejects_product_dirt_but_allows_project_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, "src/app.py", "print('dirty')\n")
            with self.assertRaisesRegex(isolation.IsolationError, "non-.project"):
                isolation.isolate_verify(repo, base, "dirty-review")

            self.write(repo, "src/app.py", "print('base')\n")
            self.write(repo, ".project/review/existing.md", "collected\n")
            result = isolation.isolate_verify(repo, base, "project-dirt-review")
            self.assertEqual(result["base"], base)

    def test_serial_land_commits_on_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            result = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )
            self.assertEqual(result["mode"], "serial")
            self.assertEqual(result["subject"], "T001: add greeting")
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")
            self.assertEqual(git(repo, "log", "-1", "--format=%s"), "T001: add greeting")
            body = git(repo, "log", "-1", "--format=%b")
            self.assertIn("Task: .project/tasks/T001.md", body)
            self.assertIn("- src/app.py", body)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), result["commit"])

    def test_serial_land_rejects_hook_staged_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            hook = repo / ".git/hooks/pre-commit"
            hook.write_text(
                "#!/bin/sh\nprintf 'hooked\\n' > SECRET.md\ngit add SECRET.md\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)

            with self.assertRaisesRegex(
                isolation.IsolationError, "undeclared paths: SECRET.md"
            ):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(
                (repo / "src/app.py").read_text(encoding="utf-8"),
                "print('done')\n",
            )

    def test_serial_land_rejects_hook_mutated_declared_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('verified')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            hook = repo / ".git/hooks/pre-commit"
            hook.write_text(
                "#!/bin/sh\nprintf \"print('hooked')\\n\" > src/app.py\n"
                "git add src/app.py\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)

            with self.assertRaisesRegex(
                isolation.IsolationError,
                "landing commit tree differs from the verified changes",
            ):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(
                (repo / "src/app.py").read_text(encoding="utf-8"),
                "print('verified')\n",
            )

    def test_serial_land_accepts_plain_apostrophe_title_with_comment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)
            task_path = repo / ".project/tasks/T001.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "title: add greeting", "title: Don't regress # planning note"
                ),
                encoding="utf-8",
            )
            git(repo, "add", ".project/tasks/T001.md")
            git(repo, "commit", "--amend", "--no-edit", "-q")
            base = git(repo, "rev-parse", "HEAD")
            self.write(repo, "src/app.py", "print('done')\n")
            with task_path.open("a") as log:
                log.write("log\n")

            result = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "Don't regress",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )

            self.assertEqual(result["subject"], "T001: Don't regress")
            report = isolation.recover(repo, Path(".project/tasks"))["tasks"][0]
            self.assertEqual(report["verdict"], "recovered")

    def test_serial_land_rejects_head_past_the_recorded_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('committed')\n")
            git(repo, "add", "src/app.py")
            git(repo, "commit", "-q", "-m", "partial task work")
            committed = git(repo, "rev-parse", "HEAD")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")

            with self.assertRaisesRegex(isolation.IsolationError, "HEAD to equal"):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), committed)

    def test_serial_land_rejects_live_task_recorded_at_another_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            recorded_base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "advanced\n")
            git(repo, "add", ".project/STATE.md")
            git(repo, "commit", "-q", "-m", "build: advance base")
            current_base = git(repo, "rev-parse", "HEAD")
            task_path = repo / ".project/tasks/T001.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "base: null", f"base: {recorded_base}"
                )
                + "log\n",
                encoding="utf-8",
            )
            self.write(repo, "src/app.py", "print('done')\n")
            task_before = task_path.read_bytes()

            with self.assertRaisesRegex(
                isolation.IsolationError,
                "task frontmatter base must be null or match landing base",
            ):
                isolation.land(
                    repo,
                    repo,
                    current_base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), current_base)
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertIn(
                "status: in-progress",
                (repo / ".project/tasks/T001.md").read_text(encoding="utf-8"),
            )

    def test_serial_land_accepts_quoted_recorded_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            task_path = repo / ".project/tasks/T001.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "base: null", f"base: '{base}'"
                )
                + "log\n",
                encoding="utf-8",
            )
            self.write(repo, "src/app.py", "print('done')\n")
            result = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )
            fields, error = isolation.task_frontmatter(
                task_path.read_text(encoding="utf-8")
            )

            self.assertIsNone(error)
            self.assertIsNotNone(fields)
            self.assertEqual(result["mode"], "serial")
            self.assertEqual(fields["base"], base)
            self.assertEqual(fields["status"], "done")

    def test_parallel_land_cherry_picks_onto_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(repo, ".project/STATE.md", "dispatch\n")
            git(repo, "add", ".project/STATE.md")
            git(repo, "commit", "-q", "-m", "dispatch bookkeeping")
            self.write(source, "src/app.py", "print('done')\n")
            self.write(source, ".project/tasks/T001.md", TASK_FILE + "log\n")
            result = isolation.land(
                repo,
                source,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )
            self.assertEqual(result["mode"], "parallel")
            self.assertEqual(git(repo, "log", "-1", "--format=%s"), "T001: add greeting")
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")
            self.assertNotEqual(result["commit"], result["source_commit"])
            self.assertEqual(
                git(source, "branch", "--show-current"), "gsd-path-task/T001"
            )

    def test_parallel_land_accepts_one_clean_commit_from_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('done')\n")
            landed_task = isolation._landed_task_text(TASK_FILE + "log\n", base)
            self.write(source, ".project/tasks/T001.md", landed_task)
            changed = {".project/tasks/T001.md", "src/app.py"}
            body = pipeline_git.task_commit_body(
                ".project/tasks/T001.md", changed, base
            )
            git(source, "add", *sorted(changed))
            git(source, "commit", "-q", "-m", "T001: add greeting", "-m", body)

            result = isolation.land(
                repo,
                source,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )

            self.assertEqual(result["mode"], "parallel")
            self.assertEqual((repo / "src/app.py").read_text(), "print('done')\n")

    def test_parallel_land_rejects_a_symlink_task_in_a_clean_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            task_file = ".project/tasks/T001.md"
            landed_task = isolation._landed_task_text(TASK_FILE + "log\n", base)
            task_path = source / task_file
            task_path.unlink()
            task_path.symlink_to(landed_task)
            self.write(source, "src/app.py", "print('done')\n")
            changed = {task_file, "src/app.py"}
            body = pipeline_git.task_commit_body(task_file, changed, base)
            git(source, "add", *sorted(changed))
            git(source, "commit", "-q", "-m", "T001: add greeting", "-m", body)

            with self.assertRaisesRegex(isolation.IsolationError, "regular file"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    task_file,
                    ["src/app.py"],
                )

            self.assertFalse((repo / task_file).is_symlink())
            self.assertEqual((repo / "src/app.py").read_text(), "print('base')\n")

    def test_parallel_land_rejects_dirty_source_past_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('first')\n")
            git(source, "add", "src/app.py")
            git(source, "commit", "-q", "-m", "partial task work")
            source_head = git(source, "rev-parse", "HEAD")
            self.write(source, "src/app.py", "print('second')\n")
            self.write(source, ".project/tasks/T001.md", TASK_FILE + "log\n")

            with self.assertRaisesRegex(isolation.IsolationError, "HEAD must equal"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(git(source, "rev-parse", "HEAD"), source_head)
            self.assertIn(
                "status: in-progress",
                (source / ".project/tasks/T001.md").read_text(),
            )

    def test_parallel_land_rejects_two_clean_source_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('first')\n")
            git(source, "add", "src/app.py")
            git(source, "commit", "-q", "-m", "partial task work")
            task_file = ".project/tasks/T001.md"
            self.write(
                source,
                task_file,
                isolation._landed_task_text(TASK_FILE + "log\n", base),
            )
            body = pipeline_git.task_commit_body(
                task_file, {task_file, "src/app.py"}, base
            )
            git(source, "add", task_file)
            git(source, "commit", "-q", "-m", "T001: add greeting", "-m", body)

            with self.assertRaisesRegex(isolation.IsolationError, "parent must equal"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    task_file,
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual((repo / "src/app.py").read_text(), "print('base')\n")

    def test_clean_source_commit_cannot_authorize_an_extra_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            task_file = ".project/tasks/T001.md"
            expanded = TASK_FILE.replace(
                "  - src/app.py\n", "  - src/app.py\n  - SECRET.md\n"
            )
            self.write(
                source,
                task_file,
                isolation._landed_task_text(expanded + "log\n", base),
            )
            self.write(source, "SECRET.md", "secret\n")
            changed = {task_file, "SECRET.md"}
            body = pipeline_git.task_commit_body(task_file, changed, base)
            git(source, "add", *sorted(changed))
            git(source, "commit", "-q", "-m", "T001: add greeting", "-m", body)

            with self.assertRaises(isolation.IsolationError):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    task_file,
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertFalse((repo / "SECRET.md").exists())

    def test_clean_source_commit_obeys_cli_allow_list(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            task_file = ".project/tasks/T001.md"
            self.write(source, "src/app.py", "print('done')\n")
            self.write(
                source,
                task_file,
                isolation._landed_task_text(TASK_FILE + "log\n", base),
            )
            changed = {task_file, "src/app.py"}
            body = pipeline_git.task_commit_body(task_file, changed, base)
            git(source, "add", *sorted(changed))
            git(source, "commit", "-q", "-m", "T001: add greeting", "-m", body)

            with self.assertRaisesRegex(isolation.IsolationError, "allow-list"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    task_file,
                    [],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_quoted_hash_title_lands_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)
            task_path = repo / ".project/tasks/T001.md"
            task_path.write_text(
                task_path.read_text().replace(
                    "title: add greeting\n", 'title: "Fix #123"\n'
                )
            )
            git(repo, "add", ".project/tasks/T001.md")
            git(repo, "commit", "-q", "-m", "plan: quote task title")
            base = git(repo, "rev-parse", "HEAD")
            self.write(repo, "src/app.py", "print('done')\n")
            with task_path.open("a") as log:
                log.write("log\n")

            landed = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "Fix #123",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )
            report = isolation.recover(repo, Path(".project/tasks"))["tasks"][0]

            self.assertEqual(report["verdict"], "recovered")
            self.assertEqual(report["commit"], landed["commit"])

    def test_quoted_hash_inline_file_lands_and_recovers(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)
            task_path = repo / ".project/tasks/T001.md"
            task_path.write_text(
                task_path.read_text(encoding="utf-8").replace(
                    "files:\n  - src/app.py",
                    "files: ['src/plan #1.py'] # planning note",
                ),
                encoding="utf-8",
            )
            self.write(repo, "src/plan #1.py", "base\n")
            git(repo, "add", ".project/tasks/T001.md", "src/plan #1.py")
            git(repo, "commit", "--amend", "--no-edit", "-q")
            base = git(repo, "rev-parse", "HEAD")
            self.write(repo, "src/plan #1.py", "done\n")
            with task_path.open("a") as log:
                log.write("log\n")

            landed = isolation.land(
                repo,
                repo,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/plan #1.py"],
            )
            report = isolation.recover(repo, Path(".project/tasks"))["tasks"][0]

            self.assertEqual(report["verdict"], "recovered")
            self.assertEqual(report["commit"], landed["commit"])

    def test_land_rejects_a_symlink_task_without_writing_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            task_path = repo / ".project/tasks/T001.md"
            target = root / "outside-task.md"
            target.write_text(TASK_FILE + "log\n", encoding="utf-8")
            target_before = target.read_bytes()
            task_path.unlink()
            task_path.symlink_to(target)
            self.write(repo, "src/app.py", "print('done')\n")

            with self.assertRaisesRegex(isolation.IsolationError, "regular file"):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(target.read_bytes(), target_before)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_land_replaces_the_task_file_instead_of_writing_through_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, "src/app.py", "print('done')\n")
            task_path = repo / ".project/tasks/T001.md"
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            task_path.chmod(0o640)
            original_mode = stat.S_IMODE(task_path.stat().st_mode)
            linked_copy = root / "linked-task.md"
            os.link(task_path, linked_copy)

            isolation.land(
                repo,
                repo,
                base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )

            self.assertIn("status: done", task_path.read_text(encoding="utf-8"))
            self.assertEqual(stat.S_IMODE(task_path.stat().st_mode), original_mode)
            self.assertIn(
                "status: in-progress", linked_copy.read_text(encoding="utf-8")
            )

    def test_parallel_land_rejects_a_bodyless_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('done')\n")
            self.write(source, ".project/tasks/T001.md", TASK_FILE + "log\n")
            git(source, "add", "src/app.py", ".project/tasks/T001.md")
            git(source, "commit", "-q", "-m", "T001: add greeting")

            with self.assertRaisesRegex(isolation.IsolationError, "commit body"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

    def test_parallel_land_rejects_multiple_precommitted_source_commits(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('first')\n")
            git(source, "add", "src/app.py")
            git(source, "commit", "-q", "-m", "partial work")
            self.write(
                source,
                ".project/tasks/T001.md",
                isolation._landed_task_text(TASK_FILE + "log\n", base),
            )
            paths = [".project/tasks/T001.md", "src/app.py"]
            git(source, "add", ".project/tasks/T001.md")
            git(
                source,
                "commit",
                "-q",
                "-m",
                "T001: add greeting",
                "-m",
                isolation.task_commit_body(paths[0], paths, base),
            )

            with self.assertRaisesRegex(isolation.IsolationError, "parent must equal"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    paths[0],
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_parallel_land_rejects_pending_work_after_a_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('committed')\n")
            git(source, "add", "src/app.py")
            git(source, "commit", "-q", "-m", "partial work")
            self.write(source, ".project/tasks/T001.md", TASK_FILE + "log\n")

            with self.assertRaisesRegex(isolation.IsolationError, "dirty parallel source"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_land_rejects_unexpected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, "SECRET.md", "nope\n")
            task_path = repo / ".project/tasks/T001.md"
            task_before = task_path.read_bytes()
            status_before = git(repo, "status", "--porcelain", "--untracked-files=all")
            with self.assertRaises(isolation.IsolationError) as raised:
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )
            self.assertIn("unexpected paths: SECRET.md", str(raised.exception))
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(
                git(repo, "status", "--porcelain", "--untracked-files=all"),
                status_before,
            )

    def test_failed_commit_restores_task_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('staged')\n")
            git(repo, "add", "src/app.py")
            self.write(repo, "src/app.py", "print('unstaged')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            hook = repo / ".git/hooks/pre-commit"
            observed = repo / ".git/pre-commit-task-state"
            hook.write_text(
                "#!/bin/sh\n"
                "sed -n 's/^status: //p' .project/tasks/T001.md > "
                ".git/pre-commit-task-state\n"
                "exit 1\n",
                encoding="utf-8",
            )
            hook.chmod(0o755)
            task_path = repo / ".project/tasks/T001.md"
            task_before = task_path.read_bytes()
            cached_before = git(repo, "diff", "--cached", "--binary")
            working_before = git(repo, "diff", "--binary")

            with self.assertRaises(isolation.IsolationError):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(git(repo, "diff", "--cached", "--binary"), cached_before)
            self.assertEqual(git(repo, "diff", "--binary"), working_before)
            self.assertEqual(observed.read_text(encoding="utf-8").strip(), "done")

    def test_keyboard_interrupt_restores_task_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('staged')\n")
            git(repo, "add", "src/app.py")
            self.write(repo, "src/app.py", "print('unstaged')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")
            task_path = repo / ".project/tasks/T001.md"
            task_before = task_path.read_bytes()
            cached_before = git(repo, "diff", "--cached", "--binary")
            working_before = git(repo, "diff", "--binary")

            def interrupt(*_args: object, **_kwargs: object) -> str:
                git(repo, "add", "-A")
                raise KeyboardInterrupt

            with mock.patch.object(
                isolation, "commit_allowed_changes", side_effect=interrupt
            ):
                with self.assertRaises(KeyboardInterrupt):
                    isolation.land(
                        repo,
                        repo,
                        base,
                        "T001",
                        "add greeting",
                        ".project/tasks/T001.md",
                        ["src/app.py"],
                    )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertEqual(task_path.read_bytes(), task_before)
            self.assertEqual(git(repo, "diff", "--cached", "--binary"), cached_before)
            self.assertEqual(git(repo, "diff", "--binary"), working_before)

    def test_parallel_land_rejects_a_precommitted_product_only_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('done')\n")
            git(source, "add", "src/app.py")
            git(
                source,
                "commit",
                "-q",
                "-m",
                "T001: add greeting",
                "-m",
                isolation.task_commit_body(
                    ".project/tasks/T001.md", ["src/app.py"], base
                ),
            )

            with self.assertRaisesRegex(isolation.IsolationError, "does not touch the task file"):
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_land_rejects_a_non_append_task_change(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(
                repo,
                ".project/tasks/T001.md",
                TASK_FILE.replace("task T001", "changed task") + "log\n",
            )

            with self.assertRaisesRegex(isolation.IsolationError, "append-only"):
                isolation.land(
                    repo,
                    repo,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_parallel_conflict_aborts_and_keeps_primary_clean(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(repo, "src/app.py", "print('primary')\n")
            git(repo, "add", "src/app.py")
            git(repo, "commit", "-q", "-m", "bookkeeping overlap")
            self.write(source, "src/app.py", "print('task')\n")
            self.write(source, ".project/tasks/T001.md", TASK_FILE + "log\n")
            with self.assertRaises(isolation.IsolationError) as raised:
                isolation.land(
                    repo,
                    source,
                    base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )
            self.assertIn("conflict:", str(raised.exception))
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")
            self.assertFalse(git(repo, "status", "--porcelain"))
            in_progress = subprocess.run(
                ("git", "-C", str(repo), "rev-parse", "-q", "--verify", "CHERRY_PICK_HEAD"),
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(in_progress.returncode, 0)

    def test_retire_serial_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            result = isolation.retire(repo, repo, None, False)
            self.assertFalse(result["retired"])
            self.assertEqual(result["reason"], "serial")
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")

    def test_retire_removes_named_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "inspect-codebase")
            worktree = Path(isolated["worktree"])
            isolation.retire(repo, worktree, isolated["branch"], False)
            self.assertFalse(worktree.exists())
            missing = subprocess.run(
                (
                    "git",
                    "-C",
                    str(repo),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    "refs/heads/gsd-path-verify/inspect-codebase",
                ),
                check=False,
            )
            self.assertNotEqual(missing.returncode, 0)
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/M001")

    def test_collect_artifact_copies_only_the_expected_real_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "review-final")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "reviewed\n")

            result = isolation.collect_artifact(
                repo,
                source,
                base,
                isolated["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
            )
            retried = isolation.collect_artifact(
                repo,
                source,
                base,
                isolated["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
            )

            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "reviewed\n",
            )
            self.assertEqual(result["bytes"], 9)
            self.assertEqual(len(result["sha256"]), 64)
            self.assertEqual(result, retried)
            self.assertFalse(git(source, "status", "--porcelain"))
            self.assertTrue(source.exists())

    def test_collect_artifact_rejects_extra_sidecar_changes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "review-final")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "reviewed\n")
            self.write(source, "unexpected.txt", "no\n")

            with self.assertRaisesRegex(isolation.IsolationError, "unexpected sidecar paths"):
                isolation.collect_artifact(
                    repo,
                    source,
                    base,
                    isolated["branch"],
                    ".project/review/FINAL.md",
                    ".project/review/FINAL.md",
                )
            self.assertFalse((repo / ".project/review/FINAL.md").exists())

    def test_collect_artifact_rejects_a_stale_primary_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "stale-review")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "reviewed\n")
            self.write(repo, ".project/STATE.md", "advanced\n")
            git(repo, "add", ".project/STATE.md")
            git(repo, "commit", "-q", "-m", "advance primary")

            with self.assertRaisesRegex(isolation.IsolationError, "primary worktree HEAD"):
                isolation.collect_artifact(
                    repo,
                    source,
                    base,
                    isolated["branch"],
                    ".project/review/FINAL.md",
                    ".project/review/FINAL.md",
                )

            self.assertFalse((repo / ".project/review/FINAL.md").exists())

    def test_collect_artifact_refuses_to_overwrite_different_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "existing-review")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "new review\n")
            self.write(repo, ".project/review/FINAL.md", "existing review\n")

            with self.assertRaisesRegex(isolation.IsolationError, "proven expected version"):
                isolation.collect_artifact(
                    repo,
                    source,
                    base,
                    isolated["branch"],
                    ".project/review/FINAL.md",
                    ".project/review/FINAL.md",
                )

            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "existing review\n",
            )

    def test_collect_artifact_replaces_a_destination_proven_at_base(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)
            self.write(repo, ".project/review/FINAL.md", "old review\n")
            git(repo, "add", ".project/review/FINAL.md")
            git(repo, "commit", "-q", "-m", "old review")
            base = git(repo, "rev-parse", "HEAD")
            isolated = isolation.isolate_verify(repo, base, "replace-base-review")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "new review\n")

            result = isolation.collect_artifact(
                repo,
                source,
                base,
                isolated["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
                "base",
            )
            retried = isolation.collect_artifact(
                repo,
                source,
                base,
                isolated["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
                "base",
            )

            self.assertTrue(result["replaced"])
            self.assertEqual(result, retried)
            self.assertFalse(git(source, "status", "--porcelain"))
            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "new review\n",
            )

    def test_collect_artifact_retries_with_the_prior_collected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            first = isolation.isolate_verify(repo, base, "first-review")
            first_source = Path(first["worktree"])
            self.write(first_source, ".project/review/FINAL.md", "first review\n")
            first_result = isolation.collect_artifact(
                repo,
                first_source,
                base,
                first["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
            )
            second = isolation.isolate_verify(repo, base, "second-review")
            second_source = Path(second["worktree"])
            self.write(second_source, ".project/review/FINAL.md", "fixed review\n")

            result = isolation.collect_artifact(
                repo,
                second_source,
                base,
                second["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
                first_result["sha256"],
            )

            self.assertEqual(result["previous_sha256"], first_result["sha256"])
            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "fixed review\n",
            )

    def test_collect_artifact_rejects_a_stale_expected_hash(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "stale-hash-review")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "new review\n")
            self.write(repo, ".project/review/FINAL.md", "current review\n")

            with self.assertRaisesRegex(
                isolation.IsolationError, "changed after its expected version"
            ):
                isolation.collect_artifact(
                    repo,
                    source,
                    base,
                    isolated["branch"],
                    ".project/review/FINAL.md",
                    ".project/review/FINAL.md",
                    "0" * 64,
                )

            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "current review\n",
            )

    def test_collect_artifact_cleans_a_staged_new_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "staged-review")
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "reviewed\n")
            git(source, "add", ".project/review/FINAL.md")

            isolation.collect_artifact(
                repo,
                source,
                base,
                isolated["branch"],
                ".project/review/FINAL.md",
                ".project/review/FINAL.md",
            )

            self.assertFalse(git(source, "status", "--porcelain"))
            self.assertEqual(
                (repo / ".project/review/FINAL.md").read_text(encoding="utf-8"),
                "reviewed\n",
            )

    def test_checkpoint_commits_only_allowlisted_paths_with_canonical_message(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "roadmap done\n")

            result = isolation.checkpoint(
                repo,
                base,
                "roadmap: program roadmap approved",
                "Why: approved roadmap checkpoint",
                [".project"],
            )

            self.assertEqual(result["paths"], [".project/STATE.md"])
            self.assertEqual(git(repo, "log", "-1", "--format=%s"), result["subject"])
            self.assertEqual(
                git(repo, "log", "-1", "--format=%b"),
                "Why: approved roadmap checkpoint",
            )

    def test_checkpoint_retry_returns_the_exact_existing_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "roadmap done\n")
            first = isolation.checkpoint(
                repo,
                base,
                "roadmap: program roadmap approved",
                "Why: approved roadmap checkpoint",
                [".project"],
            )

            retried = isolation.checkpoint(
                repo,
                base,
                "roadmap: program roadmap approved",
                "Why: approved roadmap checkpoint",
                [".project"],
            )

            self.assertEqual(first["commit"], retried["commit"])
            self.assertEqual("committed", first["status"])
            self.assertEqual("already-complete", retried["status"])
            self.assertEqual("2", git(repo, "rev-list", "--count", "HEAD"))

    def test_checkpoint_retry_rejects_a_different_message_or_dirty_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "roadmap done\n")
            isolation.checkpoint(
                repo,
                base,
                "roadmap: program roadmap approved",
                "Why: approved roadmap checkpoint",
                [".project"],
            )

            with self.assertRaisesRegex(isolation.IsolationError, "HEAD differs"):
                isolation.checkpoint(
                    repo,
                    base,
                    "build: dispatch wave 1",
                    "Why: a different checkpoint",
                    [".project"],
                )

            self.write(repo, ".project/dirty.md", "unfinished\n")
            with self.assertRaisesRegex(isolation.IsolationError, "HEAD differs"):
                isolation.checkpoint(
                    repo,
                    base,
                    "roadmap: program roadmap approved",
                    "Why: approved roadmap checkpoint",
                    [".project"],
                )

    def test_checkpoint_rejects_unrelated_changes_without_moving_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "roadmap done\n")
            self.write(repo, "notes.txt", "user change\n")

            with self.assertRaisesRegex(isolation.IsolationError, "unexpected paths"):
                isolation.checkpoint(
                    repo,
                    base,
                    "roadmap: program roadmap approved",
                    "Why: approved roadmap checkpoint",
                    [".project"],
                )
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)
            self.assertTrue((repo / "notes.txt").exists())

    def test_checkpoint_rejects_a_non_bound_primary_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            git(repo, "switch", "-q", "-c", "main")
            self.write(repo, ".project/STATE.md", "roadmap done\n")

            with self.assertRaisesRegex(
                isolation.IsolationError,
                "primary branch must be canonical",
            ):
                isolation.checkpoint(
                    repo,
                    base,
                    "roadmap: program roadmap approved",
                    "Why: approved roadmap checkpoint",
                    [".project"],
                )
            self.assertEqual(git(repo, "rev-parse", "HEAD"), base)

    def test_abandon_checkpoint_requires_one_normalized_ruling_line(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "abandoned\n")

            with self.assertRaisesRegex(
                isolation.IsolationError, "one Why line"
            ):
                isolation.checkpoint(
                    repo,
                    base,
                    "build: abandon milestone demo",
                    "Why: user ruling\nTasks: none",
                    [".project"],
                )
            with self.assertRaisesRegex(
                isolation.IsolationError, "reason must be normalized"
            ):
                isolation.checkpoint(
                    repo,
                    base,
                    "build: abandon milestone demo",
                    "Why: user  ruling",
                    [".project"],
                )

    def test_retire_refuses_a_dirty_sidecar_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "dirty")
            worktree = Path(isolated["worktree"])
            self.write(worktree, "dirty.txt", "keep\n")

            with self.assertRaisesRegex(isolation.IsolationError, "worktree is dirty"):
                isolation.retire(repo, worktree, isolated["branch"], False)
            self.assertTrue(worktree.exists())

    def test_retire_refuses_the_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)

            with self.assertRaisesRegex(isolation.IsolationError, "bound branch"):
                isolation.retire(repo, repo, "gsd-path/M001", False)

    def test_retire_refuses_a_mismatched_branch_name(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_verify(repo, base, "expected")
            worktree = Path(isolated["worktree"])

            with self.assertRaisesRegex(
                isolation.IsolationError,
                "expected gsd-path-verify/other",
            ):
                isolation.retire(
                    repo,
                    worktree,
                    "gsd-path-verify/other",
                    False,
                )
            self.assertTrue(worktree.exists())

    def test_retire_refuses_an_unrecognized_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            worktree = Path(temporary) / "feature"
            git(repo, "worktree", "add", "-q", "-b", "feature", str(worktree), base)

            with self.assertRaisesRegex(isolation.IsolationError, "unrecognized branch"):
                isolation.retire(repo, worktree, "feature", False)
            self.assertTrue(worktree.exists())

    def test_retire_refuses_an_unrecognized_branch_when_worktree_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            git(repo, "branch", "feature", base)
            missing = Path(temporary) / "missing-feature-worktree"

            with self.assertRaisesRegex(isolation.IsolationError, "unrecognized branch"):
                isolation.retire(repo, missing, "feature", True)

            self.assertEqual(git(repo, "rev-parse", "feature"), base)

    def test_retire_removes_a_merged_task_branch_when_worktree_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            branch = "gsd-path-task/T001"
            git(repo, "branch", branch, base)
            missing = isolation.sidecar_root(repo.resolve(), "task", "T001")

            result = isolation.retire(repo, missing, branch, True)

            self.assertEqual(result["reason"], "branch-only")
            self.assertNotEqual(
                subprocess.run(
                    ("git", "-C", str(repo), "show-ref", "--verify", "--quiet", f"refs/heads/{branch}"),
                    check=False,
                ).returncode,
                0,
            )

    def test_retire_cleans_authorization_when_branch_is_already_absent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            branch = "gsd-path-task/T001"
            authorization = isolation.task_authorization_ref("T001")
            git(repo, "update-ref", authorization, base)
            missing = isolation.sidecar_root(repo.resolve(), "task", "T001")

            result = isolation.retire(repo, missing, branch, True)

            self.assertEqual("already-absent", result["reason"])
            self.assertNotEqual(
                subprocess.run(
                    (
                        "git",
                        "-C",
                        str(repo),
                        "show-ref",
                        "--verify",
                        "--quiet",
                        authorization,
                    ),
                    check=False,
                ).returncode,
                0,
            )

    def test_retire_refuses_a_foreign_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            self.init_bound_repo(repo)
            foreign = Path(temporary) / "foreign"
            foreign.mkdir()
            git(foreign, "init", "-b", "gsd-path-verify/foreign")
            git(foreign, "config", "user.email", "test@example.test")
            git(foreign, "config", "user.name", "Test")
            self.write(foreign, "README.md", "foreign\n")
            git(foreign, "add", "README.md")
            git(foreign, "commit", "-q", "-m", "foreign base")

            with self.assertRaisesRegex(isolation.IsolationError, "another repository"):
                isolation.retire(
                    repo,
                    foreign,
                    "gsd-path-verify/foreign",
                    False,
                )
            self.assertTrue(foreign.exists())

    def test_cli_isolate_task_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            completed = self.run_cli(
                "isolate-task",
                "--repo",
                str(repo),
                "--base",
                base,
                "--task-id",
                "T001",
                "--round-size",
                "1",
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["mode"], "serial")
            self.assertFalse(payload["detached"])

    def test_cli_land_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, ".project/tasks/T001.md", TASK_FILE + "log\n")

            completed = self.run_cli(
                "land",
                "--repo",
                str(repo),
                "--source",
                str(repo),
                "--base",
                base,
                "--task-id",
                "T001",
                "--title",
                "add greeting",
                "--task-file",
                ".project/tasks/T001.md",
                "--allow-path",
                "src/app.py",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["mode"], "serial")
            self.assertEqual(git(repo, "rev-parse", "HEAD"), payload["commit"])

    def test_cli_checkpoint_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            self.write(repo, ".project/STATE.md", "roadmap done\n")

            completed = self.run_cli(
                "checkpoint",
                "--repo",
                str(repo),
                "--expected-head",
                base,
                "--subject",
                "roadmap: program roadmap approved",
                "--body",
                "Why: approved roadmap checkpoint",
                "--allow-path",
                ".project",
            )

            self.assertEqual(completed.returncode, 0, completed.stderr)
            payload = json.loads(completed.stdout)
            self.assertEqual(payload["paths"], [".project/STATE.md"])
            self.assertEqual(git(repo, "rev-parse", "HEAD"), payload["commit"])

    def test_cli_collect_and_retire_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            created = self.run_cli(
                "isolate-verify",
                "--repo",
                str(repo),
                "--base",
                base,
                "--name",
                "cli-review",
            )
            self.assertEqual(created.returncode, 0, created.stderr)
            isolated = json.loads(created.stdout)
            source = Path(isolated["worktree"])
            self.write(source, ".project/review/FINAL.md", "reviewed\n")

            collected = self.run_cli(
                "collect-artifact",
                "--repo",
                str(repo),
                "--source",
                str(source),
                "--base",
                base,
                "--branch",
                isolated["branch"],
                "--source-path",
                ".project/review/FINAL.md",
                "--destination-path",
                ".project/review/FINAL.md",
            )
            self.assertEqual(collected.returncode, 0, collected.stderr)
            retired = self.run_cli(
                "retire",
                "--repo",
                str(repo),
                "--worktree",
                str(source),
                "--branch",
                isolated["branch"],
            )
            self.assertEqual(retired.returncode, 0, retired.stderr)
            self.assertFalse(source.exists())


class RecoverTests(unittest.TestCase):
    TASK = (
        "---\nid: T001\ntitle: add greeting\nwave: {wave}\ndeps: []\nstatus: {status}\n"
        "agent: {agent}\nbase: {base}\nworktree: {worktree}\ntask_branch: {task_branch}\n"
        "files:\n{files}\n---\n\n# T001\n\n## Log\n{log}"
    )

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-b", "gsd-path/M001")
        git(self.repo, "config", "user.email", "t@example.test")
        git(self.repo, "config", "user.name", "T")
        (self.repo / "src").mkdir()
        (self.repo / "src/app.py").write_text("print('base')\n")
        self.write_task("pending", "null")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def write_task(
        self,
        status: str,
        base: str,
        *,
        root: Optional[Path] = None,
        agent: str = "null",
        worktree: str = "null",
        task_branch: str = "null",
        files: tuple[str, ...] = ("src/app.py",),
        wave: int = 1,
        log: str = "",
    ) -> None:
        path = (root or self.repo) / ".project/tasks/T001.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            self.TASK.format(
                status=status,
                agent=agent,
                base=base,
                worktree=worktree,
                task_branch=task_branch,
                files="\n".join(f"  - {item}" for item in files),
                wave=wave,
                log=log,
            ),
            encoding="utf-8",
        )

    def dispatch(
        self, root: Optional[Path] = None, task_branch: str = "null"
    ) -> None:
        task_root = root or self.repo
        self.write_task(
            "in-progress",
            self.base,
            root=task_root,
            agent="coder",
            worktree=str(task_root),
            task_branch=task_branch,
        )

    def land(self, *, dispatch: bool = True) -> str:
        if dispatch:
            self.dispatch()
        (self.repo / "src/app.py").write_text("print('hello')\n")
        with (self.repo / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        return isolation.land(
            self.repo, self.repo, self.base, "T001", "add greeting",
            ".project/tasks/T001.md", ["src/app.py"],
        )["commit"]

    def land_parallel(self, content: bytes) -> Path:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_bytes(content)
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        isolation.land(
            self.repo,
            source,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        return source

    def recover(self) -> dict:
        return isolation.recover(self.repo, Path(".project/tasks"))["tasks"][0]

    def commit_candidate(
        self, *, files: tuple[str, ...] = ("src/app.py",), wave: int = 1
    ) -> str:
        self.write_task(
            "done",
            self.base,
            agent="coder",
            files=files,
            wave=wave,
            log="- done\n",
        )
        (self.repo / "src/app.py").write_text("print('hello')\n")
        for path in files:
            if path != "src/app.py":
                (self.repo / path).write_text("candidate\n", encoding="utf-8")
        changed = {".project/tasks/T001.md", *files}
        git(self.repo, "add", *sorted(changed))
        body = pipeline_git.task_commit_body(
            ".project/tasks/T001.md", changed, self.base
        )
        git(
            self.repo,
            "commit",
            "-q",
            "-m",
            "T001: add greeting",
            "-m",
            body,
        )
        return git(self.repo, "rev-parse", "HEAD")

    def test_landed_commit_is_recovered(self) -> None:
        commit = self.land()
        self.assertEqual(self.recover()["verdict"], "recovered")
        self.assertEqual(self.recover()["commit"], commit)

    def test_recovery_rejects_whitespace_changed_retained_branch(self) -> None:
        source = self.land_parallel(b"print('hello')\n")
        (source / "src/app.py").write_text("print( 'hello' )\n")
        git(source, "add", "src/app.py")
        git(source, "commit", "--amend", "--no-edit", "-q")

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("retained task branch differs", report["reason"])

    def test_recovery_rejects_binary_changed_retained_branch(self) -> None:
        source = self.land_parallel(b"\0original\n")
        (source / "src/app.py").write_bytes(b"\0different\n")
        git(source, "add", "src/app.py")
        git(source, "commit", "--amend", "--no-edit", "-q")

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("retained task branch differs", report["reason"])

    def test_recovery_blocks_missing_tracked_task(self) -> None:
        (self.repo / ".project/tasks/T001.md").unlink()

        report = isolation.recover(self.repo, Path(".project/tasks"))

        self.assertEqual(report["verdict"], "block")
        self.assertEqual(report["tasks"], [])
        self.assertIn("missing .project/tasks/T001.md", report["reason"])

    def test_recovery_blocks_task_deleted_by_current_head(self) -> None:
        git(self.repo, "rm", ".project/tasks/T001.md")
        git(self.repo, "commit", "-q", "-m", "invalid task deletion")

        report = isolation.recover(self.repo, Path(".project/tasks"))

        self.assertEqual(report["verdict"], "block")
        self.assertEqual(report["tasks"], [])
        self.assertIn("missing .project/tasks/T001.md", report["reason"])

    def test_recovery_blocks_unexpected_task(self) -> None:
        (self.repo / ".project/tasks/T002.md").write_text("unexpected\n")

        report = isolation.recover(self.repo, Path(".project/tasks"))

        self.assertEqual(report["verdict"], "block")
        self.assertEqual(report["tasks"], [])
        self.assertIn("unexpected .project/tasks/T002.md", report["reason"])

    def test_clean_filtered_crlf_task_lands_and_recovers(self) -> None:
        git(self.repo, "config", "core.autocrlf", "true")
        self.dispatch()
        task_path = self.repo / ".project/tasks/T001.md"
        dispatched = task_path.read_text(encoding="utf-8") + "- done\n"
        task_path.write_bytes(dispatched.replace("\n", "\r\n").encode("utf-8"))
        (self.repo / "src/app.py").write_text("print('hello')\n")

        landed = isolation.land(
            self.repo,
            self.repo,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        report = self.recover()

        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], landed["commit"])

    def test_interrupted_serial_landing_is_retryable(self) -> None:
        self.dispatch()
        task_path = self.repo / ".project/tasks/T001.md"
        (self.repo / "src/app.py").write_text("print('hello')\n")
        with task_path.open("a") as log:
            log.write("- done\n")
        isolation.stamp_task_landed(task_path, self.base)

        report = self.recover()

        self.assertEqual(report["verdict"], "resume")
        self.assertTrue(report["landing_retry"])
        landed = isolation.land(
            self.repo,
            self.repo,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        self.assertEqual(self.recover()["verdict"], "recovered")
        self.assertEqual(
            git(self.repo, "rev-list", "--count", f"{self.base}..HEAD"), "1"
        )
        self.assertEqual(landed["commit"], git(self.repo, "rev-parse", "HEAD"))

    def test_in_progress_without_landing_resumes(self) -> None:
        self.dispatch()
        report = self.recover()
        self.assertEqual(report["verdict"], "resume")
        self.assertEqual(report["base"], self.base)
        self.assertEqual(report["worktree"]["path"], str(self.repo.resolve()))

    def test_stray_same_subject_commit_is_rejected_not_chosen(self) -> None:
        commit = self.land()
        (self.repo / "src/app.py").write_text("print('stray')\n")
        git(self.repo, "commit", "-qam", "T001: add greeting")
        report = self.recover()
        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], commit)
        self.assertEqual(len(report["rejected"]), 1)

    def test_done_without_landing_blocks(self) -> None:
        self.write_task("done", self.base, agent="coder")
        git(self.repo, "commit", "-qam", "build: bogus")
        self.assertEqual(self.recover()["verdict"], "block")

    def test_land_stamps_frontmatter_done(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('hello')\n")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        isolation.land(
            self.repo,
            source,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        text = (self.repo / ".project/tasks/T001.md").read_text()
        fields, error = isolation.task_frontmatter(text)
        self.assertIsNone(error)
        self.assertIsNotNone(fields)
        self.assertEqual(
            {key: fields[key] for key in ("status", "base", "worktree", "task_branch")},
            {
                "status": "done",
                "base": self.base,
                "worktree": "null",
                "task_branch": "null",
            },
        )
        self.assertIn(f"Base: {self.base}", git(self.repo, "log", "-1", "--format=%b"))

    def test_parallel_in_flight_resumes_then_recovers(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('hello')\n")
        report = self.recover()
        self.assertEqual(report["verdict"], "resume")
        self.assertEqual(report["base"], self.base)
        self.assertEqual(report["task_branch"], "gsd-path-task/T001")
        self.assertEqual(report["worktree"]["branch"], "gsd-path-task/T001")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        (self.repo / ".project/STATE.md").write_text("wave advanced\n")
        git(self.repo, "add", ".project/STATE.md")
        git(self.repo, "commit", "-q", "-m", "build: unrelated landing state")
        landed = isolation.land(
            self.repo, source, self.base, "T001", "add greeting",
            ".project/tasks/T001.md", ["src/app.py"],
        )
        report = self.recover()
        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], landed["commit"])

    def test_pristine_parallel_isolate_retries_dispatch(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)

        report = self.recover()

        self.assertEqual(report["verdict"], "resume")
        self.assertTrue(report["dispatch_retry"])
        self.assertEqual(report["base"], self.base)
        self.assertEqual(report["task_branch"], isolated["task_branch"])
        self.assertEqual(report["worktree"]["path"], isolated["worktree"])

    def test_parallel_land_rejects_tree_different_from_source(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('verified')\n")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        original_run_git = isolation.run_git
        mutated = False

        def mutate_landing(
            repo: Path, *arguments: str, input: Optional[str] = None
        ) -> subprocess.CompletedProcess[str]:
            nonlocal mutated
            result = original_run_git(repo, *arguments, input=input)
            if arguments and arguments[0] == "cherry-pick" and result.returncode == 0:
                mutated = True
                (repo / "src/app.py").write_text("print('mutated')\n")
                git(repo, "add", "src/app.py")
                git(repo, "commit", "--amend", "--no-edit", "-q")
            return result

        with mock.patch.object(
            isolation, "run_git", side_effect=mutate_landing
        ):
            with self.assertRaisesRegex(
                isolation.IsolationError,
                "landing commit tree differs from the verified changes",
            ):
                isolation.land(
                    self.repo,
                    source,
                    self.base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

        self.assertTrue(mutated)
        self.assertEqual(git(self.repo, "rev-parse", "HEAD"), self.base)
        self.assertFalse(git(self.repo, "status", "--porcelain"))

    def test_interrupted_parallel_landing_is_retryable(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        task_path = source / ".project/tasks/T001.md"
        (source / "src/app.py").write_text("print('hello')\n")
        with task_path.open("a") as log:
            log.write("- done\n")

        original_run_git = isolation.run_git

        def interrupt_cherry_pick(
            repo: Path, *arguments: str, input: Optional[str] = None
        ) -> subprocess.CompletedProcess[str]:
            if arguments and arguments[0] == "cherry-pick":
                raise KeyboardInterrupt
            return original_run_git(repo, *arguments, input=input)

        with mock.patch.object(
            isolation, "run_git", side_effect=interrupt_cherry_pick
        ):
            with self.assertRaises(KeyboardInterrupt):
                isolation.land(
                    self.repo,
                    source,
                    self.base,
                    "T001",
                    "add greeting",
                    ".project/tasks/T001.md",
                    ["src/app.py"],
                )

        report = self.recover()

        self.assertEqual(report["verdict"], "resume")
        self.assertTrue(report["landing_retry"])
        self.assertEqual(
            report["source_commit"], git(source, "rev-parse", "HEAD")
        )
        landed = isolation.land(
            self.repo,
            source,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        report = self.recover()
        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], landed["commit"])

    def test_branch_only_pending_task_resumes_at_base(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        git(self.repo, "worktree", "remove", str(source))

        report = self.recover()

        self.assertEqual(report["verdict"], "resume")
        self.assertEqual(report["base"], self.base)
        self.assertIsNone(report["worktree"])

    def test_resume_blocks_when_parallel_branch_advances(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        git(source, "commit", "--allow-empty", "-q", "-m", "unexpected commit")

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("advanced past its base", report["reason"])

    def test_resume_blocks_when_serial_head_advances(self) -> None:
        self.dispatch()
        git(self.repo, "commit", "--allow-empty", "-q", "-m", "unexpected commit")

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("advanced past its base", report["reason"])

    def test_parallel_resume_rejects_mismatched_dispatch_metadata(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        task_path = source / ".project/tasks/T001.md"
        valid = task_path.read_text(encoding="utf-8")
        cases = {
            "id": ("id: T001", "id: T002"),
            "title": ("title: add greeting", "title: stale greeting"),
            "status": ("status: in-progress", "status: pending"),
            "agent": ("agent: coder", "agent: null"),
            "base": (f"base: {self.base}", f"base: {'0' * 40}"),
            "worktree": (f"worktree: {source}", "worktree: /stale/worktree"),
            "task_branch": (
                f"task_branch: {isolated['task_branch']}",
                "task_branch: gsd-path-task/stale",
            ),
        }
        for field, (expected, replacement) in cases.items():
            with self.subTest(field=field):
                task_path.write_text(
                    valid.replace(expected, replacement), encoding="utf-8"
                )
                report = self.recover()
                self.assertEqual(report["verdict"], "block")
                self.assertIn(field, report["reason"])
        task_path.write_text(
            valid.replace(
                "status: in-progress", "status: failed\nstatus: in-progress"
            ),
            encoding="utf-8",
        )
        report = self.recover()
        self.assertEqual(report["verdict"], "block")
        self.assertIn("status", report["reason"])
        task_path.write_text(valid, encoding="utf-8")

    def test_done_task_with_dirty_retained_sidecar_blocks(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('hello')\n")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        landed = isolation.land(
            self.repo,
            source,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        (source / "src/app.py").write_text("print('unknown')\n")

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertEqual(report["commit"], landed["commit"])
        self.assertIn("dirty worktree", report["reason"])

    def test_candidate_cannot_expand_parent_allow_list(self) -> None:
        self.commit_candidate(files=("src/app.py", "SECRET.md"))
        report = self.recover()
        self.assertEqual(report["verdict"], "block")
        self.assertIn("SECRET.md", report["rejected"][0]["reason"])

    def test_intervening_commit_cannot_expand_base_allow_list(self) -> None:
        self.write_task(
            "pending", "null", files=("src/app.py", "SECRET.md")
        )
        git(self.repo, "add", ".project/tasks/T001.md")
        git(self.repo, "commit", "-q", "-m", "build: drift task files")
        self.commit_candidate(files=("src/app.py", "SECRET.md"))

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("SECRET.md", report["rejected"][0]["reason"])

    def test_candidate_cannot_change_immutable_frontmatter(self) -> None:
        self.commit_candidate(wave=2)
        report = self.recover()
        self.assertEqual(report["verdict"], "block")
        self.assertIn("outside landing metadata", report["rejected"][0]["reason"])

    def test_done_task_must_match_its_landing_commit(self) -> None:
        self.land()
        task_path = self.repo / ".project/tasks/T001.md"
        task_path.write_text(
            task_path.read_text(encoding="utf-8").replace("wave: 1\n", "wave: 2\n"),
            encoding="utf-8",
        )
        git(self.repo, "commit", "-qam", "build: drift task contract")
        report = self.recover()
        self.assertEqual(report["verdict"], "block")
        self.assertIn("differs from its landing commit", report["rejected"][0]["reason"])

    def test_done_task_requires_stamped_base(self) -> None:
        self.land()
        task_path = self.repo / ".project/tasks/T001.md"
        task_path.write_text(
            task_path.read_text(encoding="utf-8").replace(
                f"base: {self.base}\n", "base: null\n"
            ),
            encoding="utf-8",
        )
        report = self.recover()
        self.assertEqual(report["verdict"], "block")
        self.assertIn("invalid base", report["reason"])

    def test_reused_task_id_ignores_older_landing(self) -> None:
        old_commit = self.land()
        self.write_task("pending", "null")
        git(self.repo, "add", ".project/tasks/T001.md")
        git(self.repo, "commit", "-q", "-m", "plan: reslice task")
        self.base = git(self.repo, "rev-parse", "HEAD")

        self.assertEqual(self.recover()["verdict"], "none")
        self.dispatch()
        report = self.recover()
        self.assertEqual(report["verdict"], "resume")
        self.assertEqual(report["base"], self.base)

        new_commit = self.land(dispatch=False)
        report = self.recover()
        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], new_commit)
        self.assertNotEqual(report["commit"], old_commit)

    def test_failed_and_blocked_retained_isolates_reconcile(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        for status in ("failed", "blocked"):
            with self.subTest(status=status):
                self.write_task(
                    status,
                    self.base,
                    agent="coder",
                    worktree=isolated["worktree"],
                    task_branch=isolated["task_branch"],
                )
                report = self.recover()
                self.assertEqual(report["verdict"], "reconcile")
                self.assertEqual(report["base"], self.base)
                self.assertEqual(report["task_branch"], isolated["task_branch"])
                self.assertEqual(report["worktree"]["path"], isolated["worktree"])

    def test_failed_and_blocked_serial_tasks_reconcile_in_primary(self) -> None:
        for status in ("failed", "blocked"):
            with self.subTest(status=status):
                self.write_task(
                    status,
                    self.base,
                    agent="coder",
                    worktree=str(self.repo.resolve()),
                )

                report = self.recover()

                self.assertEqual(report["verdict"], "reconcile")
                self.assertEqual(report["base"], self.base)
                self.assertIsNone(report["task_branch"])
                self.assertEqual(report["worktree"]["path"], str(self.repo.resolve()))

    def test_partial_sidecar_path_blocks_recovery(self) -> None:
        expected = isolation.sidecar_root(self.repo.resolve(), "task", "T001")
        expected.mkdir(parents=True)
        self.write_task(
            "in-progress",
            self.base,
            agent="coder",
            worktree=str(expected),
            task_branch="gsd-path-task/T001",
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("invalid sidecar worktree", report["reason"])

    def test_foreign_repository_at_sidecar_path_blocks_recovery(self) -> None:
        expected = isolation.sidecar_root(self.repo.resolve(), "task", "T001")
        expected.mkdir(parents=True)
        git(expected, "init", "-b", "gsd-path-task/T001")
        self.write_task(
            "in-progress",
            self.base,
            agent="coder",
            worktree=str(expected),
            task_branch="gsd-path-task/T001",
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("another repository", report["reason"])

    def test_nested_repository_path_blocks_recovery(self) -> None:
        expected = isolation.sidecar_root(self.repo.resolve(), "task", "T001")
        git(
            self.repo,
            "worktree",
            "add",
            "-b",
            "gsd-path-task/T001",
            str(expected.parent),
            self.base,
        )
        expected.mkdir()
        self.write_task(
            "in-progress",
            self.base,
            agent="coder",
            worktree=str(expected),
            task_branch="gsd-path-task/T001",
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("not its Git root", report["reason"])

    def test_sidecar_on_another_branch_blocks_recovery(self) -> None:
        expected = isolation.sidecar_root(self.repo.resolve(), "task", "T001")
        git(
            self.repo,
            "worktree",
            "add",
            "-b",
            "gsd-path-task/other",
            str(expected),
            self.base,
        )
        self.write_task(
            "in-progress",
            self.base,
            agent="coder",
            worktree=str(expected),
            task_branch="gsd-path-task/T001",
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("expected gsd-path-task/T001", report["reason"])

    def test_failed_serial_task_requires_a_valid_recorded_base(self) -> None:
        self.write_task(
            "failed",
            "null",
            agent="coder",
            worktree=str(self.repo.resolve()),
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("invalid base", report["reason"])

    def test_failed_task_without_a_retained_isolate_needs_nothing(self) -> None:
        self.write_task("failed", self.base, agent="coder")

        report = self.recover()

        self.assertEqual(report["verdict"], "none")

    def test_unknown_status_blocks_with_a_retained_isolate(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        self.write_task(
            "paused",
            self.base,
            agent="coder",
            worktree=isolated["worktree"],
            task_branch=isolated["task_branch"],
        )

        report = self.recover()

        self.assertEqual(report["verdict"], "block")
        self.assertIn("unknown task status", report["reason"])

    def test_branch_only_recovery_can_finish_proven_retirement(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('hello')\n")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- done\n")
        (self.repo / ".project/STATE.md").write_text("another task landed\n")
        git(self.repo, "add", ".project/STATE.md")
        git(self.repo, "commit", "-q", "-m", "build: advance primary")
        landed = isolation.land(
            self.repo,
            source,
            self.base,
            "T001",
            "add greeting",
            ".project/tasks/T001.md",
            ["src/app.py"],
        )
        git(self.repo, "worktree", "remove", str(source))

        report = self.recover()

        self.assertEqual(report["verdict"], "recovered")
        self.assertIsNone(report["worktree"])
        self.assertEqual(report["task_branch"], isolated["task_branch"])
        rejected = subprocess.run(
            (
                sys.executable,
                str(ISOLATION_SCRIPT),
                "retire",
                "--repo",
                str(self.repo),
                "--branch",
                isolated["task_branch"],
                "--force",
                "--landed-commit",
                self.base,
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(
            git(self.repo, "rev-parse", isolated["task_branch"]),
            landed["source_commit"],
        )
        retired = subprocess.run(
            (
                sys.executable,
                str(ISOLATION_SCRIPT),
                "retire",
                "--repo",
                str(self.repo),
                "--branch",
                isolated["task_branch"],
                "--force",
                "--landed-commit",
                landed["commit"],
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(retired.returncode, 0, retired.stderr)
        self.assertEqual(json.loads(retired.stdout)["reason"], "branch-only")
        missing = subprocess.run(
            (
                "git",
                "-C",
                str(self.repo),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{isolated['task_branch']}",
            ),
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)

    def test_branch_only_failed_recovery_can_finish_retirement(self) -> None:
        isolated = isolation.isolate_task(self.repo, self.base, "T001", 2)
        source = Path(isolated["worktree"])
        self.dispatch(source, isolated["task_branch"])
        (source / "src/app.py").write_text("print('task')\n")
        with (source / ".project/tasks/T001.md").open("a") as log:
            log.write("- rejected\n")
        (self.repo / "src/app.py").write_text("print('primary')\n")
        git(self.repo, "add", "src/app.py")
        git(self.repo, "commit", "-q", "-m", "build: conflicting task")
        with self.assertRaisesRegex(isolation.IsolationError, "conflict:"):
            isolation.land(
                self.repo,
                source,
                self.base,
                "T001",
                "add greeting",
                ".project/tasks/T001.md",
                ["src/app.py"],
            )
        source_commit = git(source, "rev-parse", "HEAD")
        self.write_task(
            "failed",
            self.base,
            agent="coder",
            worktree=isolated["worktree"],
            task_branch=isolated["task_branch"],
        )
        git(self.repo, "add", ".project/tasks/T001.md")
        git(self.repo, "commit", "-q", "-m", "build: record failed task")
        git(self.repo, "worktree", "remove", str(source))

        report = self.recover()

        self.assertEqual(report["verdict"], "reconcile")
        self.assertIsNone(report["worktree"])
        self.assertEqual(report["task_branch"], isolated["task_branch"])
        self.assertEqual(
            git(self.repo, "rev-parse", isolated["task_branch"]), source_commit
        )
        self.write_task(
            "in-progress",
            self.base,
            agent="coder",
            worktree=isolated["worktree"],
            task_branch=isolated["task_branch"],
        )
        rejected = subprocess.run(
            (
                sys.executable,
                str(ISOLATION_SCRIPT),
                "retire",
                "--repo",
                str(self.repo),
                "--branch",
                isolated["task_branch"],
                "--force",
                "--task-file",
                ".project/tasks/T001.md",
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(rejected.returncode, 0)
        self.assertEqual(
            git(self.repo, "rev-parse", isolated["task_branch"]), source_commit
        )
        self.write_task(
            "failed",
            self.base,
            agent="coder",
            worktree=isolated["worktree"],
            task_branch=isolated["task_branch"],
        )
        retired = subprocess.run(
            (
                sys.executable,
                str(ISOLATION_SCRIPT),
                "retire",
                "--repo",
                str(self.repo),
                "--branch",
                isolated["task_branch"],
                "--force",
                "--task-file",
                ".project/tasks/T001.md",
            ),
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(retired.returncode, 0, retired.stderr)
        self.assertEqual(json.loads(retired.stdout)["reason"], "branch-only")
        missing = subprocess.run(
            (
                "git",
                "-C",
                str(self.repo),
                "show-ref",
                "--verify",
                "--quiet",
                f"refs/heads/{isolated['task_branch']}",
            ),
            check=False,
        )
        self.assertNotEqual(missing.returncode, 0)

    def test_pending_task_needs_nothing_and_cli_emits_json(self) -> None:
        result = subprocess.run(
            (sys.executable, str(ISOLATION_SCRIPT), "recover", "--repo", str(self.repo)),
            text=True, capture_output=True, check=True,
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["verdict"], "ok")
        self.assertEqual(payload["tasks"][0]["verdict"], "none")

    def test_bundled_recover_clis_are_self_contained(self) -> None:
        environment = os.environ.copy()
        environment["PYTHONPATH"] = ""
        for script in BUNDLED_ISOLATION_SCRIPTS:
            with self.subTest(script=script):
                result = subprocess.run(
                    (
                        sys.executable,
                        str(script),
                        "recover",
                        "--repo",
                        str(self.repo),
                    ),
                    cwd=self.repo,
                    env=environment,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                payload = json.loads(result.stdout)
                self.assertEqual(payload["tasks"][0]["verdict"], "none")


if __name__ == "__main__":
    unittest.main()
