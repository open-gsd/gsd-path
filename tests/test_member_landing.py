import concurrent.futures
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import isolation, pipeline_state

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import _common
MEMBERS = ROOT / "scripts" / "members.py"
GIT_GUARD = ROOT / "scripts" / "git_guard.py"
STATE = (
    "---\npipeline: gsd-path/v2\nproject: acme\nmilestone: demo\nphase: plan\nstatus: done\n"
    "branch: gsd-path/M001\narchive: null\n---\n\n# Project State\n\n## Log\n\n- 2026-09-27 — plan — plan approved\n"
)
TASK_FILE = ".project/tasks/T001-change.md"
TASK = (
    "---\nid: T001\ntitle: Change app\nwave: 1\ndeps: []\nstatus: pending\nagent: null\n"
    "base: null\nworktree: null\ntask_branch: null\nrepo: web\nmodel: preferred\nfiles:\n  - app.py\n---\n# T001 — Change app\n\n## Log\n\n- created\n"
)
IDENTITY = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}


def git(repo: Path, *arguments: str, check: bool = True) -> str:
    return subprocess.run(["git", *arguments], cwd=repo, encoding="utf-8", errors="replace", capture_output=True,
                          check=check).stdout.strip()


class MemberLandingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {
            **IDENTITY, "GSD_PATH_WORKTREE_ROOT": str(self.root / "workspace")})
        environment.start()
        self.addCleanup(environment.stop)
        self.coordinator = self.root / "acme"
        (self.coordinator / ".project" / "tasks").mkdir(parents=True)
        git(self.root, "init", "-q", "-b", "gsd-path/M001", str(self.coordinator))
        (self.coordinator / ".project" / "STATE.md").write_bytes(STATE.encode("utf-8"))
        (self.coordinator / TASK_FILE).write_bytes(TASK.encode("utf-8"))
        git(self.coordinator, "add", "-A")
        git(self.coordinator, "commit", "-q", "-m", "plan")
        self.member = self.root / "web"
        self.member.mkdir()
        git(self.member, "init", "-q", "-b", "main")
        (self.member / "app.py").write_bytes("v1\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        subprocess.run([sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
                        "--name", "web", "--checkout", str(self.member)],
                       encoding="utf-8", errors="replace", capture_output=True, check=True)
        pipeline_state.transition_state(
            self.coordinator,
            {"phase": "plan", "status": "done", "branch": "gsd-path/M001", "archive": None},
            {"phase": "build", "status": "active"}, "build started")
        git(self.coordinator, "add", "-A")
        git(self.coordinator, "commit", "-q", "-m", "build: start milestone")
        self.base = git(self.coordinator, "rev-parse", "HEAD")
        isolated = isolation.isolate_member_task(self.coordinator, "web", "T001")
        self.sidecar = Path(isolated["worktree"])
        self.bound = Path(isolated["bound_checkout"])
        self.member_base = isolated["member_base"]
        isolation.activate_member_task(self.coordinator, "web", "T001", "coder", TASK_FILE, self.base)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def land(self):
        return isolation.land_member(self.coordinator, "web", "T001", "Change app", TASK_FILE,
                                     self.base, self.member_base)

    def edit(self, name: str = "app.py", text: str = "v2\n") -> None:
        (self.sidecar / name).write_bytes(text.encode("utf-8"))

    def prepare_second_task(self) -> str:
        second_file = ".project/tasks/T002-add.md"
        second_task = TASK.replace("T001", "T002").replace("Change app", "Add config").replace(
            "app.py", "config.py")
        (self.coordinator / second_file).write_bytes(second_task.encode("utf-8"))
        git(self.coordinator, "add", second_file)
        git(self.coordinator, "commit", "-q", "-m", "add second task")
        self.second_base = git(self.coordinator, "rev-parse", "HEAD")
        second = isolation.isolate_member_task(self.coordinator, "web", "T002")
        isolation.activate_member_task(self.coordinator, "web", "T002", "coder", second_file, self.second_base)
        (Path(second["worktree"]) / "config.py").write_bytes("added\n".encode("utf-8"))
        return second_file

    def journal(self) -> Path:
        common = git(self.coordinator, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return Path(common) / "gsd-path" / "member-landings" / "T001.json"

    def bound_tip(self) -> str:
        return git(self.bound, "rev-parse", "HEAD")

    def assert_landed_once(self, result=None) -> None:
        tip = self.bound_tip()
        self.assertEqual(git(self.bound, "rev-parse", f"{tip}^"), self.member_base)
        self.assertEqual((self.bound / "app.py").read_text(encoding="utf-8"), "v2\n")
        self.assertEqual(git(self.bound, "log", "-1", "--format=%s"), "T001: Change app")
        self.assertEqual(
            git(self.bound, "log", "-1", "--format=%b"),
            f"Task: {TASK_FILE}\nBase: {self.member_base}\nContract: {self.base}\nFiles:\n- app.py",
        )
        record = git(self.coordinator, "rev-parse", "HEAD")
        self.assertEqual(git(self.coordinator, "diff-tree", "--no-commit-id", "--name-only", "-r", record),
                         TASK_FILE)
        self.assertEqual(git(self.coordinator, "log", "-1", "--format=%s"), "T001: Change app")
        self.assertEqual(git(self.coordinator, "log", "-1", "--format=%b"),
                         f"Task: {TASK_FILE}\nBase: {self.base}\nMember: web {tip} {self.member_base}")
        stamped = (self.coordinator / TASK_FILE).read_text(encoding="utf-8")
        for line in ("status: done", f"base: {self.base}", f"member_base: {self.member_base}",
                     "worktree: null", "task_branch: null"):
            self.assertIn(line + "\n", stamped)
        self.assertEqual(git(self.coordinator, "status", "--porcelain"), "")
        self.assertFalse(self.journal().exists())
        if result is not None:
            self.assertEqual((result["landing"], result["commit"]), (tip, record))
        self.assertEqual(git(self.member, "branch", "--show-current"), "main")

    def test_member_task_lands_once_with_a_coordinator_record(self) -> None:
        self.edit()
        self.assert_landed_once(self.land())

    def test_member_copy_refuses_changed_dispatch_model(self) -> None:
        self.edit()
        copy = isolation.member_task_copy(self.sidecar, TASK_FILE)
        changed = copy.read_text(encoding="utf-8").replace("model: preferred\n", "model: other\n")
        copy.write_bytes((changed + "- coder Log\n").encode("utf-8"))
        contract = git(self.coordinator, "show", f"{self.base}:{TASK_FILE}") + "\n"
        with self.assertRaisesRegex(isolation.IsolationError, "changes contract fields"):
            isolation.member_log_delta(contract, changed)
        with self.assertRaisesRegex(isolation.IsolationError, "changes contract fields"):
            self.land()
        self.assertEqual(self.bound_tip(), self.member_base)

    def test_parallel_member_landings_use_successive_bound_parents(self) -> None:
        second_file = self.prepare_second_task()
        self.edit()
        first_checked = threading.Event()
        second_started = threading.Event()
        release_first = threading.Event()
        original_pick = isolation._pick_member_landing

        def pause_first(bound, journal):
            if journal["task_id"] == "T001":
                first_checked.set()
                if not release_first.wait(10):
                    raise AssertionError("second landing did not start")
            return original_pick(bound, journal)

        def land_second():
            second_started.set()
            return isolation.land_member(self.coordinator, "web", "T002", "Add config", second_file,
                                         self.second_base, self.member_base)

        with mock.patch.object(isolation, "_pick_member_landing", side_effect=pause_first):
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                try:
                    first_future = pool.submit(self.land)
                    self.assertTrue(first_checked.wait(10))
                    lock = self.journal().with_name(".lock")
                    with lock.open("r+b") as handle:
                        if sys.platform == "win32":
                            import msvcrt
                            handle.seek(0)
                            with self.assertRaises(OSError):
                                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        else:
                            import fcntl
                            with self.assertRaises(BlockingIOError):
                                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    second_future = pool.submit(land_second)
                    self.assertTrue(second_started.wait(10))
                finally:
                    release_first.set()
                first = first_future.result(timeout=10)
                second_result = second_future.result(timeout=10)
        self.assertEqual(git(self.bound, "rev-parse", f"{first['landing']}^"), self.member_base)
        self.assertEqual(git(self.bound, "rev-parse", f"{second_result['landing']}^"), first["landing"])
        self.assertEqual(self.bound_tip(), second_result["landing"])
        self.assertEqual((self.bound / "app.py").read_text(encoding="utf-8"), "v2\n")
        self.assertEqual((self.bound / "config.py").read_text(encoding="utf-8"), "added\n")
        self.assertEqual(git(self.coordinator, "log", "-2", "--format=%s").splitlines(),
                         ["T002: Add config", "T001: Change app"])
        self.assertFalse(self.journal().exists())
        self.assertFalse(self.journal().with_name("T002.json").exists())

    def test_member_landing_lock_waits_past_ten_seconds(self) -> None:
        lock_path = self.journal().with_name(".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        ready = threading.Event()

        def holder() -> None:
            with _common.exclusive_lock(lock_path):
                ready.set()
                time.sleep(12)

        thread = threading.Thread(target=holder)
        thread.start()
        self.assertTrue(ready.wait(5))
        start = time.monotonic()
        with isolation._member_landing_lock(self.coordinator):
            waited = time.monotonic() - start
        thread.join(20)
        self.assertGreaterEqual(waited, 11.0)

    def test_undeclared_member_path_is_refused_before_any_ref_moves(self) -> None:
        self.edit()
        self.edit("extra.py", "stray\n")
        with self.assertRaisesRegex(isolation.IsolationError, "extra.py"):
            self.land()
        self.assertEqual(git(self.sidecar, "rev-parse", "HEAD"), self.member_base)
        self.assertEqual(self.bound_tip(), self.member_base)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertFalse(self.journal().exists())

    def test_committed_undeclared_member_path_is_refused(self) -> None:
        self.edit()
        self.edit("extra.py", "stray\n")
        git(self.sidecar, "add", "-A")
        git(self.sidecar, "commit", "-q", "--no-verify", "-m", "coder commit")
        with self.assertRaisesRegex(isolation.IsolationError, "undeclared paths: extra.py"):
            self.land()
        self.assertEqual(self.bound_tip(), self.member_base)
        self.assertFalse(self.journal().exists())

    def land_directory_task(self, changed: str):
        """Land T002, which declares the directory `fixtures/set`, with one changed file."""
        task_file = ".project/tasks/T002-add.md"
        task = TASK.replace("T001", "T002").replace("Change app", "Add fixtures").replace(
            "app.py", "fixtures/set")
        (self.coordinator / task_file).write_bytes(task.encode("utf-8"))
        git(self.coordinator, "add", task_file)
        git(self.coordinator, "commit", "-q", "-m", "add directory task")
        base = git(self.coordinator, "rev-parse", "HEAD")
        sidecar = Path(isolation.isolate_member_task(self.coordinator, "web", "T002")["worktree"])
        isolation.activate_member_task(self.coordinator, "web", "T002", "coder", task_file, base)
        (sidecar / changed).parent.mkdir(parents=True, exist_ok=True)
        (sidecar / changed).write_bytes(b"{}\n")
        return task_file, isolation.land_member(
            self.coordinator, "web", "T002", "Add fixtures", task_file, base, self.member_base)

    def test_member_file_under_a_declared_directory_lands_and_is_proven(self) -> None:
        task_file, result = self.land_directory_task("fixtures/set/a.json")
        self.assertEqual(self.bound_tip(), result["landing"])
        self.assertEqual(
            git(self.bound, "diff-tree", "--no-commit-id", "--name-only", "-r", result["landing"]),
            "fixtures/set/a.json")
        proven = isolation.verify_landed_task_files(
            self.coordinator, [self.coordinator / task_file], ".project/tasks", result["commit"])
        self.assertEqual([(task["verdict"], task["landing"]) for task in proven["tasks"]],
                         [("recovered", result["landing"])])

    def test_member_sibling_of_a_declared_directory_is_refused(self) -> None:
        with self.assertRaisesRegex(isolation.IsolationError, "undeclared paths: fixtures/setx.json"):
            self.land_directory_task("fixtures/setx.json")
        self.assertEqual(self.bound_tip(), self.member_base)

    def test_coder_commit_needs_the_member_landing_body(self) -> None:
        self.edit()
        git(self.sidecar, "commit", "-q", "--no-verify", "-am", "T001: Change app", "-m", "free text")
        with self.assertRaisesRegex(isolation.IsolationError, "body"):
            self.land()
        self.assertEqual(self.bound_tip(), self.member_base)

    def test_conflict_leaves_both_repos_unchanged(self) -> None:
        (self.bound / "app.py").write_bytes("other\n".encode("utf-8"))
        git(self.bound, "commit", "-q", "--no-verify", "-am", "other landing")
        moved = self.bound_tip()
        self.edit()
        with self.assertRaisesRegex(isolation.IsolationError, "conflict"):
            self.land()
        self.assertEqual(self.bound_tip(), moved)
        self.assertEqual(git(self.bound, "status", "--porcelain"), "")
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertFalse(self.journal().exists())

    def test_landing_refuses_while_a_journal_is_pending(self) -> None:
        self.edit()
        self.journal().parent.mkdir(parents=True, exist_ok=True)
        self.journal().write_bytes("{}".encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "recover_member_landing"):
            self.land()

    def crash_then_recover(self, step: str) -> None:
        self.edit()
        with mock.patch.object(isolation, step, side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        self.assertTrue(self.journal().exists())
        result = isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(result["state"], "landed")
        self.assert_landed_once()

    def test_crash_before_the_cherry_pick_resumes_the_landing(self) -> None:
        self.crash_then_recover("_pick_member_landing")

    def test_pending_member_journal_blocks_next_task_until_recovery(self) -> None:
        second_file = self.prepare_second_task()
        self.edit()
        with mock.patch.object(isolation, "_pick_member_landing", side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        self.assertEqual(self.bound_tip(), self.member_base)
        with self.assertRaisesRegex(isolation.IsolationError, "T001.*recover_member_landing"):
            isolation.land_member(self.coordinator, "web", "T002", "Add config", second_file,
                                  self.second_base, self.member_base)
        self.assertTrue(self.journal().exists())
        self.assertFalse(self.journal().with_name("T002.json").exists())
        self.assertEqual(self.bound_tip(), self.member_base)
        first = isolation.recover_member_landing(self.coordinator, "T001")
        second = isolation.land_member(self.coordinator, "web", "T002", "Add config", second_file,
                                       self.second_base, self.member_base)
        self.assertEqual(git(self.bound, "rev-parse", f"{second['landing']}^"), first["landing"])
        self.assertEqual(git(self.coordinator, "log", "-2", "--format=%s").splitlines(),
                         ["T002: Add config", "T001: Change app"])
        self.assertFalse(self.journal().exists())
        self.assertFalse(self.journal().with_name("T002.json").exists())

    def test_crash_after_the_cherry_pick_does_not_pick_twice(self) -> None:
        original = isolation._record_member_journal

        def pick_then_crash(path, journal):
            if journal.get("landing"):
                raise RuntimeError("crash")
            return original(path, journal)

        self.edit()
        with mock.patch.object(isolation, "_record_member_journal", side_effect=pick_then_crash):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        tip = self.bound_tip()
        self.assertNotEqual(tip, self.member_base)
        isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(self.bound_tip(), tip)
        self.assert_landed_once()

    def test_crash_before_the_record_writes_the_record_only(self) -> None:
        self.crash_then_recover("_write_member_record")

    def test_crash_after_staging_the_record_recovers_once(self) -> None:
        self.edit()
        original = isolation.git_output

        def crash_before_commit(repo, *arguments):
            if repo == self.coordinator and arguments[0] == "commit":
                raise RuntimeError("crash")
            return original(repo, *arguments)

        with mock.patch.object(isolation, "git_output", side_effect=crash_before_commit):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        self.assertEqual(git(self.coordinator, "diff", "--cached", "--name-only"), TASK_FILE)
        result = isolation.recover_member_landing(self.coordinator, "T001")
        self.assert_landed_once(result)
        self.assertEqual(git(self.coordinator, "rev-list", "--count", f"{self.base}..HEAD"), "1")

    def test_recovery_refuses_a_different_staged_task_file(self) -> None:
        self.edit()
        original = isolation.git_output

        def crash_before_commit(repo, *arguments):
            if repo == self.coordinator and arguments[0] == "commit":
                raise RuntimeError("crash")
            return original(repo, *arguments)

        with mock.patch.object(isolation, "git_output", side_effect=crash_before_commit):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        task = self.coordinator / TASK_FILE
        stamped = task.read_text(encoding="utf-8")
        task.write_bytes((stamped + "- unrelated\n").encode("utf-8"))
        git(self.coordinator, "add", TASK_FILE)
        task.write_bytes(stamped.encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "coordinator worktree is dirty"):
            isolation.recover_member_landing(self.coordinator, "T001")

    def test_recovery_requires_the_coordinator_state_branch(self) -> None:
        self.edit()
        git(self.coordinator, "checkout", "-q", "-b", "gsd-path/M002")
        with self.assertRaisesRegex(isolation.IsolationError, "STATE bound branch"):
            self.land()
        self.assertEqual(self.bound_tip(), self.member_base)
        git(self.coordinator, "checkout", "-q", "gsd-path/M001")
        with mock.patch.object(isolation, "_write_member_record", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.land()
        landing = self.bound_tip()
        git(self.coordinator, "checkout", "-q", "gsd-path/M002")
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        with self.assertRaisesRegex(isolation.IsolationError, "STATE bound branch"):
            isolation.recover_member_landing(self.coordinator, "T001")
        self.assertTrue(self.journal().exists())
        self.assertEqual(self.bound_tip(), landing)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        git(self.coordinator, "checkout", "-q", "gsd-path/M001")
        self.assert_landed_once(isolation.recover_member_landing(self.coordinator, "T001"))

    def test_crash_after_record_commit_reuses_proven_record(self) -> None:
        self.edit()
        with mock.patch.object(Path, "unlink", side_effect=RuntimeError("crash")):
            with self.assertRaisesRegex(RuntimeError, "crash"):
                self.land()
        record = git(self.coordinator, "rev-parse", "HEAD")
        result = isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(result["commit"], record)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), record)
        self.assert_landed_once(result)

    def test_recovery_blocks_moved_tip_after_landing_was_recorded(self) -> None:
        self.edit()
        with mock.patch.object(isolation, "_write_member_record", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.land()
        (self.bound / "other.py").write_bytes("other\n".encode("utf-8"))
        git(self.bound, "add", "other.py")
        git(self.bound, "commit", "-q", "--no-verify", "-m", "other landing")
        moved = self.bound_tip()
        with self.assertRaisesRegex(isolation.IsolationError, "moved"):
            isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(self.bound_tip(), moved)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertTrue(self.journal().exists())

    def test_landing_and_recovery_reject_changed_immutable_task_contract(self) -> None:
        self.edit()
        task = self.coordinator / TASK_FILE
        task.write_bytes(TASK.replace("repo: web", "repo: sdk").encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "contract differs"):
            self.land()
        self.assertEqual(self.bound_tip(), self.member_base)
        task.write_bytes(TASK.encode("utf-8"))
        with mock.patch.object(isolation, "_write_member_record", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.land()
        landing = self.bound_tip()
        task.write_bytes(TASK.replace("repo: web", "repo: sdk").encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "contract differs"):
            isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(self.bound_tip(), landing)
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertTrue(self.journal().exists())

    def test_recovery_refuses_staged_coordinator_file_before_record(self) -> None:
        self.edit()
        with mock.patch.object(isolation, "_write_member_record", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.land()
        state = self.coordinator / ".project" / "STATE.md"
        state.write_bytes((STATE + "extra\n").encode("utf-8"))
        git(self.coordinator, "add", ".project/STATE.md")
        with self.assertRaisesRegex(isolation.IsolationError, "coordinator worktree is dirty"):
            isolation.recover_member_landing(self.coordinator, "T001")
        self.assertEqual(git(self.coordinator, "rev-parse", "HEAD"), self.base)
        self.assertTrue(self.journal().exists())

    def test_recovery_blocks_when_someone_else_moved_the_member_branch(self) -> None:
        self.edit()
        with mock.patch.object(isolation, "_pick_member_landing", side_effect=RuntimeError("crash")):
            with self.assertRaises(RuntimeError):
                self.land()
        (self.bound / "other.py").write_bytes("x\n".encode("utf-8"))
        git(self.bound, "add", "-A")
        git(self.bound, "commit", "-q", "--no-verify", "-m", "someone else")
        with self.assertRaisesRegex(isolation.IsolationError, "moved"):
            isolation.recover_member_landing(self.coordinator, "T001")
        self.assertTrue(self.journal().exists())

    def test_recovery_without_a_journal_is_a_no_op(self) -> None:
        self.assertEqual(isolation.recover_member_landing(self.coordinator, "T001")["state"], "none")

    def test_git_guard_refuses_direct_commits_on_the_member_bound_branch(self) -> None:
        (self.bound / "app.py").write_bytes("direct\n".encode("utf-8"))
        git(self.bound, "add", "app.py")
        guarded = subprocess.run([sys.executable, str(GIT_GUARD), "pre-commit"], cwd=self.bound,
                                 encoding="utf-8", errors="replace", capture_output=True, check=False)
        self.assertNotEqual(guarded.returncode, 0)
        self.assertIn("gsd-path/acme-M001", guarded.stderr)
        git(self.bound, "reset", "-q", "--hard")
        side = subprocess.run([sys.executable, str(GIT_GUARD), "pre-commit"], cwd=self.sidecar,
                              encoding="utf-8", errors="replace", capture_output=True, check=False)
        self.assertEqual(side.returncode, 0, side.stderr)


if __name__ == "__main__":
    unittest.main()
