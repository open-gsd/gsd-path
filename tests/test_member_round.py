import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import _common, build_state, dispatch_driver, isolation
from tests.test_dispatch_driver import ROLE_BRIEF, SCRIPT, TASK_TEMPLATE
import tests.test_dispatch_driver as driver_tests

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "scripts" / "members.py"
T002 = ".project/tasks/T002-demo-task-t002.md"


def git(repo: Path, *arguments: str, check: bool = True) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=repo,
                          encoding="utf-8", errors="replace", capture_output=True, check=check).stdout.strip()


class MemberRoundTests(unittest.TestCase):
    """End to end: one build round lands a coordinator task and a member task."""

    fixture = driver_tests.DispatchDriverTests.fixture
    head = driver_tests.DispatchDriverTests.head

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        self.root = base / "repo"
        self.root.mkdir()
        self.workspace = base / "workspace"
        self.fixture(self.root, state=("plan", "done"))
        task_path = next((self.root / ".project" / "tasks").glob("T002-*.md"))
        self.task_file = task_path.relative_to(self.root).as_posix()
        self.member = base / "web"
        shutil.copytree(self.root, self.member, ignore=shutil.ignore_patterns(".git", ".project", "fake_*.py"))
        git(self.member, "init", "-q", "-b", "main")
        git(self.member, "config", "user.name", "Test")
        git(self.member, "config", "user.email", "test@example.test")
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "--allow-empty", "-m", "member init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        joined = subprocess.run([sys.executable, str(MEMBERS), "add", "--repo", str(self.root), "--name", "web",
                                 "--checkout", str(self.member)], encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(joined.returncode, 0, joined.stderr)
        task_path.write_bytes(task_path.read_text(encoding="utf-8").replace("files:", "repo: web\nfiles:", 1).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "plan: T002 changes the web member")

    def round(self) -> dict:
        env = dict(os.environ, FAKE_MODE="ready", GSD_PATH_WORKTREE_ROOT=str(self.workspace))
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "round", "--wave", "1", "--child-command",
             f"{sys.executable} {self.root / 'fake_coder.py'}", "--role-brief", str(ROLE_BRIEF),
             "--task-template", str(TASK_TEMPLATE), "--wait", "60", "--repo", str(self.root)],
            capture_output=True, encoding="utf-8", errors="replace", env=env)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def blocked_wave(self) -> None:
        """Both tasks land, then the wave 1 cycle 1 review fails each task on its own criterion."""
        self.assertEqual(self.round()["status"], "done")
        lines = ["# Review — wave 1, cycle 1", "", "Wave verdict: blocked", "Cycle: 1", "Depth: full", "Tasks reviewed: 2"]
        for task, criterion in (("T001", "The demo command prints hello."), ("T002", "The demo test suite is green.")):
            lines += ["", f"## {task} — Demo task {task}: fail", "", f"- ❌ {criterion} — found: wrong output\n  fix: correct it"]
        review = self.root / ".project/review/wave-1.cycle1.md"
        review.parent.mkdir(exist_ok=True)
        review.write_bytes(("\n".join(lines) + "\n").encode("utf-8"))

    def two_repo_finding(self) -> dict:
        """Findings where the owners of one failed criterion are in the coordinator and in the member."""
        findings = dispatch_driver.review_findings.compute(self.root, ".project", 1, 1)
        group = dict(findings["groups"][0], tasks=["T001", "T002"])
        self.assertEqual(group["locator"], "t001_ac1")
        return dict(findings, groups=[group], fix_batches=[
            {"locators": ["t001_ac1"], "files": ["src/app.py"]},
            {"locators": ["t001_ac1"], "files": ["tests/test_app.py"], "repo": "web"}])

    def fix_task(self, item: dict) -> tuple:
        text = (self.root / item["path"]).read_text(encoding="utf-8")
        fields = isolation.task_frontmatter(text)[0]
        return fields.get("repo"), fields["deps"], fields["files"], _common.task_verify_command(text)

    def test_fix_tasks_writes_a_lint_clean_member_fix_task_and_carries_findings_by_repo(self) -> None:
        self.blocked_wave()
        completed = subprocess.run([sys.executable, "-B", str(SCRIPT), "fix-tasks", "--wave", "1", "--cycle", "1",
                                    "--repo", str(self.root)], capture_output=True, encoding="utf-8", errors="replace")
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        receipt = json.loads(completed.stdout)
        self.assertEqual(receipt["status"], "created", receipt)
        self.assertEqual([step["exit_code"] for step in receipt["steps"] if step["script"] == "check_task_briefs.py"], [0])
        coordinator, member = receipt["created"]
        self.assertEqual((coordinator["task"], coordinator["locators"], "repo" in coordinator), ("T003", ["t001_ac1"], False))
        self.assertEqual((member["task"], member["locators"], member["repo"]), ("T004", ["t002_ac1"], "web"))
        self.assertEqual(self.fix_task(coordinator), (None, ["T001"], ["src/app.py"], "set -e\n(\npython3 src/app.py\n)"))
        self.assertEqual(self.fix_task(member),
                         ("web", ["T002"], ["tests/test_app.py"], "set -e\n(\npython3 tests/test_app.py\n)"))
        self.assertEqual({task["id"]: task.get("repo") for task in build_state.ready(str(self.root))["ready"]},
                         {"T003": None, "T004": "web"})
        # Cycle 2 repeats t001_ac1 for both repos. T003 carries it only for the coordinator.
        findings = self.two_repo_finding()
        with mock.patch.object(dispatch_driver.review_findings, "compute", return_value=findings):
            repeat = dispatch_driver.fix_tasks(self.root, argparse.Namespace(project_dir=".project", wave=1, cycle=2))
        self.assertEqual(repeat["status"], "created", repeat)
        self.assertEqual(repeat["carried"], [findings["fix_batches"][0]])
        self.assertEqual([(item["task"], item["repo"]) for item in repeat["created"]], [("T005", "web")])
        self.assertEqual(self.fix_task(repeat["created"][0]),
                         ("web", ["T002"], ["tests/test_app.py"], "set -e\n(\npython3 tests/test_app.py\n)"))

    def test_fix_tasks_resumes_the_member_half_of_a_two_repo_finding(self) -> None:
        self.blocked_wave()
        findings = self.two_repo_finding()
        write = _common.atomic_write

        def interrupt(path, text):
            if path.name == "T004-fix-wave-1-cycle-1.md":
                raise dispatch_driver.DriverStop("interrupted second batch")
            return write(path, text)

        options = argparse.Namespace(project_dir=".project", wave=1, cycle=1)
        with mock.patch.object(dispatch_driver.review_findings, "compute", return_value=findings):
            with mock.patch.object(_common, "atomic_write", side_effect=interrupt):
                self.assertEqual(dispatch_driver.fix_tasks(self.root, options)["status"], "blocked")
            receipt = dispatch_driver.fix_tasks(self.root, options)
            again = dispatch_driver.fix_tasks(self.root, options)
        self.assertEqual(receipt["status"], "created", receipt)
        self.assertEqual([(item["task"], item.get("repo")) for item in receipt["existing"]], [("T003", None)])
        self.assertEqual([(item["task"], item["repo"]) for item in receipt["created"]], [("T004", "web")])
        self.assertEqual(self.fix_task(receipt["existing"][0]),
                         (None, ["T001"], ["src/app.py"], "set -e\n(\npython3 src/app.py\n)"))
        self.assertEqual(self.fix_task(receipt["created"][0]),
                         ("web", ["T002"], ["tests/test_app.py"], "set -e\n(\npython3 tests/test_app.py\n)"))
        self.assertEqual(again["status"], "exists", again)
        self.assertEqual([(item["task"], item.get("repo")) for item in again["existing"]], [("T003", None), ("T004", "web")])

    def test_round_lands_a_coordinator_task_and_a_member_task(self) -> None:
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        landed = {item["task"]: item for item in receipt["landed"]}
        self.assertEqual(set(landed), {"T001", "T002"})
        self.assertEqual(landed["T002"]["mode"], "member")
        self.assertTrue(landed["T002"]["ledger"])
        rows = [json.loads(line) for line in
                (self.root / ".project" / "build" / "verify-ledger.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertIn(("web", landed["T002"]["landing"]), [(row.get("repo"), row["commit"]) for row in rows])
        bound = "gsd-path/demo-M001"
        self.assertEqual(git(self.member, "show", f"{bound}:tests/test_app.py"), "print('hello')")
        self.assertEqual(git(self.member, "log", "-1", "--format=%s", bound), "T002: Demo task T002")
        record = git(self.root, "show", f"HEAD:{self.task_file}")
        self.assertIn("status: done", record)
        self.assertIn("implemented tests/test_app.py", record)
        self.assertEqual(git(self.root, "show", "HEAD:tests/test_app.py", check=False), "")
        self.assertEqual(git(self.member, "branch", "--show-current"), "main")
        self.assertEqual(git(self.member, "branch", "--list", "gsd-path-task/demo-T002"), "")

    def test_failed_member_verify_clears_authorization_and_lands_nothing(self) -> None:
        env_mode = os.environ.get("FAKE_MODE")
        os.environ["FAKE_MODE"] = "badverify"
        try:
            receipt = self.round_with_mode("badverify")
        finally:
            if env_mode is None:
                os.environ.pop("FAKE_MODE", None)
        self.assertNotEqual(receipt["status"], "done")
        self.assertEqual(git(self.member, "rev-parse", "--verify", "--quiet",
                             "refs/gsd-path/task-authorizations/demo-T002", check=False), "")
        self.assertEqual(git(self.member, "rev-parse", "gsd-path/demo-M001"),
                         git(self.member, "rev-parse", "main"))

    def round_with_mode(self, mode: str) -> dict:
        env = dict(os.environ, FAKE_MODE=mode, GSD_PATH_WORKTREE_ROOT=str(self.workspace))
        completed = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), "round", "--wave", "1", "--child-command",
             f"{sys.executable} {self.root / 'fake_coder.py'}", "--role-brief", str(ROLE_BRIEF),
             "--task-template", str(TASK_TEMPLATE), "--wait", "60", "--repo", str(self.root)],
            capture_output=True, encoding="utf-8", errors="replace", env=env)
        self.assertTrue(completed.stdout.strip(), completed.stderr)
        return json.loads(completed.stdout)

    def test_round_finishes_a_pending_member_landing_journal(self) -> None:
        from unittest import mock
        from scripts import isolation, pipeline_state
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            head = git(self.root, "rev-parse", "HEAD")
            isolated = isolation.isolate_member_task(self.root, "web", "T002")
            isolation.activate_member_task(self.root, "web", "T002", "build_t002", self.task_file, head)
            target = Path(isolated["worktree"]) / "tests" / "test_app.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes("print('hello')\n".encode("utf-8"))
            with mock.patch.object(isolation, "_write_member_record", side_effect=RuntimeError("crash")):
                with self.assertRaises(RuntimeError):
                    isolation.land_member(self.root, "web", "T002", "Demo task T002", self.task_file,
                                          head, isolated["member_base"])
        receipt = self.round()
        steps = [step for step in receipt["steps"] if step.get("script") == "isolation.recover_member_landing"]
        self.assertEqual([step["result"]["state"] for step in steps], ["landed"])
        self.assertIn("status: done", git(self.root, "show", f"HEAD:{self.task_file}"))
        self.assertFalse(Path(isolated["worktree"]).exists())
        self.assertEqual(git(self.member, "branch", "--list", isolated["task_branch"]), "")

    def test_round_retires_a_member_task_after_its_record_was_committed(self) -> None:
        from unittest import mock
        from scripts import isolation, pipeline_state
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            head = git(self.root, "rev-parse", "HEAD")
            isolated = isolation.isolate_member_task(self.root, "web", "T002")
            isolation.activate_member_task(self.root, "web", "T002", "build_t002", self.task_file, head)
            target = Path(isolated["worktree"]) / "tests" / "test_app.py"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes("print('hello')\n".encode("utf-8"))
            landed = isolation.land_member(self.root, "web", "T002", "Demo task T002", self.task_file,
                                           head, isolated["member_base"])
        self.assertTrue(Path(isolated["worktree"]).exists())
        self.assertIn(isolated["task_branch"], git(self.member, "branch", "--list", isolated["task_branch"]))
        journal = isolation.common_git_dir(self.root).joinpath(*isolation.MEMBER_LANDING_DIR, "T002.json")
        self.assertFalse(journal.exists())
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        self.assertEqual(git(self.root, "log", "--format=%s", f"{head}..HEAD").splitlines().count(
            "T002: Demo task T002"), 1)
        self.assertIn("status: done", git(self.root, "show", f"{landed['commit']}:{self.task_file}"))
        self.assertFalse(Path(isolated["worktree"]).exists())
        self.assertEqual(git(self.member, "branch", "--list", isolated["task_branch"]), "")

    def test_round_reuses_an_activated_member_task_without_a_dispatch_record(self) -> None:
        from scripts import isolation, pipeline_state
        from unittest import mock
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            head = git(self.root, "rev-parse", "HEAD")
            isolated = isolation.isolate_member_task(self.root, "web", "T002")
            isolation.activate_member_task(self.root, "web", "T002", "build_t002", self.task_file, head)
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        self.assertIn("T002", {item["task"] for item in receipt["landed"]})
        self.assertFalse(Path(isolated["worktree"]).exists())

    def test_round_recreates_an_unused_member_isolate(self) -> None:
        from scripts import isolation, pipeline_state
        from unittest import mock
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            isolation.isolate_member_task(self.root, "web", "T002")
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        self.assertIn("T002", {item["task"] for item in receipt["landed"]})

    def test_round_recreates_an_isolate_after_activation_loses_its_authorization(self) -> None:
        from scripts import isolation, pipeline_state
        from unittest import mock
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            head = git(self.root, "rev-parse", "HEAD")
            isolated = isolation.isolate_member_task(self.root, "web", "T002")
            original = isolation.run_git

            def stop_before_authorization(repo, *arguments):
                if arguments[:2] == ("update-ref", "refs/gsd-path/task-authorizations/demo-T002"):
                    raise RuntimeError("stopped before authorization")
                return original(repo, *arguments)

            with mock.patch.object(isolation, "run_git", side_effect=stop_before_authorization):
                with self.assertRaisesRegex(RuntimeError, "stopped before authorization"):
                    isolation.activate_member_task(self.root, "web", "T002", "build_t002", self.task_file, head)
            self.assertTrue(isolation.member_task_copy(Path(isolated["worktree"]), self.task_file).is_file())
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        self.assertIn("T002", {item["task"] for item in receipt["landed"]})
        self.assertFalse(Path(isolated["worktree"]).exists())

    def test_round_recreates_an_unused_isolate_after_another_member_task_lands(self) -> None:
        from scripts import isolation, pipeline_state
        from unittest import mock
        first_file = ".project/tasks/T001-demo.md"
        first_task = self.root / first_file
        first_task.write_bytes(first_task.read_text(encoding="utf-8").replace("files:", "repo: web\nfiles:", 1).encode("utf-8"))
        with mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(self.workspace),
                                          "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                          "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}):
            state, _, _ = pipeline_state.load_state(self.root)
            pipeline_state.transition_state(
                self.root, {"phase": "plan", "status": "done", "branch": state.branch, "archive": None},
                {"phase": "build", "status": "active"}, "build started")
            git(self.root, "add", "-A")
            git(self.root, "commit", "-q", "-m", "build: start milestone")
            head = git(self.root, "rev-parse", "HEAD")
            waiting = isolation.isolate_member_task(self.root, "web", "T002")
            first = isolation.isolate_member_task(self.root, "web", "T001")
            isolation.activate_member_task(self.root, "web", "T001", "build_t001", first_file, head)
            first_product = Path(first["worktree"]) / "src/app.py"
            first_product.parent.mkdir(parents=True, exist_ok=True)
            first_product.write_bytes("print('first')\n".encode("utf-8"))
            landed = isolation.land_member(self.root, "web", "T001", "Demo task T001", first_file,
                                           head, first["member_base"])
            isolation.retire_member_task(self.root, "web", "T001")
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:4000])
        self.assertIn("T002", {item["task"] for item in receipt["landed"]})
        self.assertEqual(git(self.member, "rev-parse", f"{receipt['landed'][-1]['landing']}^"),
                         landed["landing"])
        self.assertNotEqual(waiting["member_base"], landed["landing"])

    def test_second_member_landing_on_a_moved_tip_gets_no_ledger_row(self) -> None:
        t001 = next((self.root / ".project" / "tasks").glob("T001-*.md"))
        t001.write_bytes(t001.read_text(encoding="utf-8").replace("files:", "repo: web\nfiles:", 1).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "plan: T001 also changes the web member")
        receipt = self.round()
        self.assertEqual(receipt["status"], "done", json.dumps(receipt, indent=1)[:3000])
        ledgers = sorted(item["ledger"] for item in receipt["landed"])
        self.assertEqual(ledgers, [False, True])


if __name__ == "__main__":
    unittest.main()
