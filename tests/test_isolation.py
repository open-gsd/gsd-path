import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from scripts import isolation, pipeline_git


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TASK_FILE = (
    "---\nid: T001\ntitle: demo\nwave: 1\ndeps: []\nstatus: in-progress\n"
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
        git(root, "init", "-b", "gsd-path/demo")
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
            hook.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
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
        landed = isolation.land(
            self.repo, source, self.base, "T001", "add greeting",
            ".project/tasks/T001.md", ["src/app.py"],
        )
        report = self.recover()
        self.assertEqual(report["verdict"], "recovered")
        self.assertEqual(report["commit"], landed["commit"])

    def test_candidate_cannot_expand_parent_allow_list(self) -> None:
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
