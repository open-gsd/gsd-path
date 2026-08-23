import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import isolation


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ISOLATION_SCRIPT = PROJECT_ROOT / "scripts" / "isolation.py"


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
        git(root, "init", "-b", "gsd-path/demo")
        git(root, "config", "user.email", "test@example.test")
        git(root, "config", "user.name", "Test")
        self.write(root, "src/app.py", "print('base')\n")
        self.write(root, ".project/tasks/T001.md", "task T001\n")
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

    def test_helper_source_never_detaches(self) -> None:
        source = ISOLATION_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("--detach", source)
        self.assertNotIn("checkout --detach", source)

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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")
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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")
            listed = git(repo, "worktree", "list")
            self.assertNotIn("detached", listed)
            self.assertIn("gsd-path-task/T002", second["task_branch"])

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

    def test_serial_land_commits_on_bound_branch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, ".project/tasks/T001.md", "task T001\nlog\n")
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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")
            self.assertEqual(git(repo, "log", "-1", "--format=%s"), "T001: add greeting")
            body = git(repo, "log", "-1", "--format=%b")
            self.assertIn("Task: .project/tasks/T001.md", body)
            self.assertIn("- src/app.py", body)
            self.assertEqual(git(repo, "rev-parse", "HEAD"), result["commit"])

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
            self.write(source, ".project/tasks/T001.md", "task T001\nlog\n")
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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")
            self.assertNotEqual(result["commit"], result["source_commit"])
            self.assertEqual(
                git(source, "branch", "--show-current"), "gsd-path-task/T001"
            )

    def test_parallel_land_rejects_a_bodyless_source_commit(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolated = isolation.isolate_task(repo, base, "T001", 2)
            source = Path(isolated["worktree"])
            self.write(source, "src/app.py", "print('done')\n")
            self.write(source, ".project/tasks/T001.md", "task T001\nlog\n")
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

    def test_land_rejects_unexpected_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            base = self.init_bound_repo(repo)
            isolation.isolate_task(repo, base, "T001", 1)
            self.write(repo, "src/app.py", "print('done')\n")
            self.write(repo, "SECRET.md", "nope\n")
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
            self.write(source, ".project/tasks/T001.md", "task T001\nlog\n")
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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")
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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")

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
            self.assertEqual(git(repo, "branch", "--show-current"), "gsd-path/demo")

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


if __name__ == "__main__":
    unittest.main()
