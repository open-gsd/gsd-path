import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import build_state, check_handoffs, check_task_briefs, pipeline_state, state_checkpoint
from tests.test_build_state import BRANCH, plan_text, run_git, task_text
from tests.test_task_briefs import CONTRACT, PLAN_WAVE, TASK_TEMPLATE

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "scripts" / "members.py"
STATE = (
    "---\npipeline: gsd-path/v2\nproject: acme\nmilestone: demo\nphase: {phase}\n"
    "status: active\nbranch: {branch}\narchive: null\n---\n"
)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
                          cwd=repo, encoding="utf-8", errors="replace", capture_output=True, check=True).stdout.strip()


def member_task(task_id: str, files: str, context: str, repo: str = "web",
                contract: str = "- None", verify: str = "test -f src/app.py") -> str:
    text = TASK_TEMPLATE.format(
        task_id=task_id, files_block=f"  - {files}", context=context,
        approach="- Keep the change small.", contract=contract, verify=verify,
    )
    return text.replace("files:\n", f"repo: {repo}\nfiles:\n", 1) if repo else text


class MemberTaskBriefTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.coordinator = root / "acme"
        (self.coordinator / ".project" / "tasks").mkdir(parents=True)
        git(root, "init", "-q", "-b", "main", str(self.coordinator))
        (self.coordinator / ".project" / "STATE.md").write_bytes(
            STATE.format(phase="plan", branch="gsd-path/M001").encode("utf-8"))
        (self.coordinator / "lib").mkdir()
        (self.coordinator / "lib" / "server.py").write_bytes("coordinator only\n".encode("utf-8"))
        git(self.coordinator, "add", "-A")
        git(self.coordinator, "commit", "-q", "-m", "init")
        self.member = root / "web"
        self.member.mkdir()
        git(self.member, "init", "-q", "-b", "main")
        (self.member / "src").mkdir()
        (self.member / "src" / "app.py").write_bytes("member only\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        subprocess.run([sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
                        "--name", "web", "--checkout", str(self.member)],
                       encoding="utf-8", errors="replace", capture_output=True, check=True)
        self.head = git(self.coordinator, "rev-parse", "HEAD")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, task_id: str, text: str) -> None:
        (self.coordinator / ".project" / "tasks" / f"{task_id}-task.md").write_bytes(text.encode("utf-8"))

    def problems(self) -> str:
        try:
            check_task_briefs.validate_task_briefs(self.coordinator, self.head)
        except check_task_briefs.BriefError as error:
            return str(error)
        return ""

    def prepare_landed_member_task(self, coordinator_base: bool = True):
        member_base = git(self.member, "rev-parse", "HEAD")
        git(self.member, "rm", "-q", "src/app.py")
        git(self.member, "commit", "-q", "-m", "drop app")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        (self.coordinator / ".project" / "plan").mkdir(parents=True, exist_ok=True)
        (self.coordinator / ".project" / "plan" / "PLAN.md").write_bytes(
            PLAN_WAVE.format(title="demo").encode("utf-8"))
        task = member_task("T001", "src/new.py", "Follow `src/app.py`.",
                           verify="test -f src/app.py")
        recorded_base = self.head if coordinator_base else member_base
        task = task.replace("status: pending", "status: done").replace(
            "agent: null", "agent: coder").replace("base: null", f"base: {recorded_base}")
        task = self.set_member_base(task, f"member_base: {member_base}")
        self.write("T001", task)
        return member_base, task

    @staticmethod
    def set_member_base(task: str, field: str = None) -> str:
        task = "".join(line for line in task.splitlines(keepends=True)
                       if not line.startswith("member_base:"))
        if field is not None:
            task = task.replace("repo: web\n", f"repo: web\n{field}\n", 1)
        return task

    def assert_coordinator_base_misses_member_history(self, member_base: str) -> None:
        self.assertNotEqual(git(self.member, "rev-parse", "HEAD"), member_base)
        self.assertFalse((self.member / "src" / "app.py").exists())
        git(self.member, "cat-file", "-e", f"{member_base}:src/app.py")
        coordinator_has_member_base = subprocess.run(
            ["git", "-C", str(self.coordinator), "cat-file", "-e",
             f"{member_base}^{{commit}}"], capture_output=True, check=False,
        )
        self.assertNotEqual(coordinator_has_member_base.returncode, 0)
        with self.assertRaisesRegex(check_task_briefs.BriefError,
                                    "path missing at the layer base: src/app.py"):
            check_task_briefs.validate_task_briefs(
                self.coordinator, self.head, landed_bases={"T001": self.head})

    def test_member_task_paths_resolve_in_the_member(self) -> None:
        self.write("T001", member_task("T001", "src/new.py", "Follow `src/app.py` in the member.",
                                       verify="test -f src/app.py"))
        self.assertEqual(self.problems(), "")

    def test_member_task_paths_resolve_at_the_recorded_default_branch(self) -> None:
        # A master member. Its origin/main is an older remote branch without the file.
        api = self.coordinator.parent / "api"
        git(self.coordinator.parent, "init", "-q", "-b", "master", str(api))
        git(api, "commit", "-q", "--allow-empty", "-m", "old")
        git(api, "update-ref", "refs/remotes/origin/main", "HEAD")
        (api / "src").mkdir()
        (api / "src" / "api.py").write_bytes("on master\n".encode("utf-8"))
        git(api, "add", "-A")
        git(api, "commit", "-q", "-m", "add api")
        git(api, "remote", "add", "origin", "https://github.com/acme/api.git")
        git(api, "update-ref", "refs/remotes/origin/master", "HEAD")
        git(api, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
        subprocess.run([sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
                        "--name", "api", "--checkout", str(api)],
                       encoding="utf-8", errors="replace", capture_output=True, check=True)

        self.write("T001", member_task("T001", "src/new.py", "Follow `src/api.py` in the member.",
                                       repo="api", verify="test -f src/api.py"))
        self.assertEqual(self.problems(), "")

        git(api, "update-ref", "-d", "refs/remotes/origin/master")
        self.assertIn("member api is unavailable: member requires refs/remotes/origin/master", self.problems())

    def test_member_task_paths_do_not_resolve_in_the_coordinator(self) -> None:
        self.write("T001", member_task("T001", "src/app.py", "Read `lib/server.py` first.",
                                       verify="test -f lib/server.py"))
        problems = self.problems()
        self.assertIn("## Context names a path missing at the layer base: lib/server.py", problems)
        self.assertIn("## Verify names a path missing at the layer base: lib/server.py", problems)

    def test_coordinator_task_is_unchanged(self) -> None:
        self.write("T001", member_task("T001", "lib/server.py", "Edit `lib/server.py`.", repo="",
                                       verify="test -f lib/server.py"))
        self.assertEqual(self.problems(), "")
        self.write("T001", member_task("T001", "lib/server.py", "Read `src/app.py`.", repo=""))
        self.assertIn("path missing at the layer base: src/app.py", self.problems())

    def test_landed_member_task_checks_its_recorded_member_base(self) -> None:
        old = git(self.member, "rev-parse", "HEAD")
        git(self.member, "rm", "-q", "src/app.py")
        git(self.member, "commit", "-q", "-m", "drop app")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        self.write("T001", member_task("T001", "src/new.py", "Follow `src/app.py`.",
                                       verify="test -f src/app.py"))
        self.assertIn("path missing at the layer base: src/app.py", self.problems())
        check_task_briefs.validate_task_briefs(self.coordinator, self.head, landed_bases={"T001": old})

    def test_plan_checkpoint_uses_a_landed_members_recorded_member_base(self) -> None:
        member_base, _task = self.prepare_landed_member_task()
        self.assert_coordinator_base_misses_member_history(member_base)

        state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")

    def test_plan_task_gate_uses_a_landed_members_recorded_member_base(self) -> None:
        member_base, _task = self.prepare_landed_member_task()
        self.assert_coordinator_base_misses_member_history(member_base)

        result = check_task_briefs.validate_plan_task_briefs(self.coordinator, self.head, ".project")
        self.assertEqual(result["tasks"], 1)

    def test_invalid_landed_member_bases_are_rejected_by_both_plan_validators(self) -> None:
        member_base, task = self.prepare_landed_member_task()
        blob = git(self.member, "rev-parse", f"{member_base}:src/app.py")
        invalid = (
            ("malformed", "member_base: not-a-full-sha"),
            ("missing commit", f"member_base: {'0' * 40}"),
            ("coordinator commit", f"member_base: {self.head}"),
            ("member blob", f"member_base: {blob}"),
            ("non-string", "member_base: [not, a, commit]"),
        )
        for label, field in invalid:
            with self.subTest(member_base=label):
                self.write("T001", self.set_member_base(task, field))
                with self.assertRaisesRegex(pipeline_state.PipelineStateError,
                                            "invalid historical base"):
                    state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")
                with self.assertRaisesRegex(check_task_briefs.BriefError,
                                            "invalid historical base"):
                    check_task_briefs.validate_plan_task_briefs(self.coordinator, self.head, ".project")

    def test_absent_null_or_empty_member_base_keeps_legacy_base_resolution(self) -> None:
        member_base, task = self.prepare_landed_member_task(coordinator_base=False)
        for label, field in (("absent", None), ("null", "member_base: null"),
                             ("empty string", 'member_base: ""'), ("empty list", "member_base: []")):
            with self.subTest(member_base=label):
                self.write("T001", self.set_member_base(task, field))
                state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")
                result = check_task_briefs.validate_plan_task_briefs(self.coordinator, self.head, ".project")
                self.assertEqual(result["tasks"], 1)

    def test_landed_coordinator_task_ignores_member_base(self) -> None:
        member_base = git(self.member, "rev-parse", "HEAD")
        task = member_task("T001", "lib/server.py", "Edit `lib/server.py`.", repo="",
                           verify="test -f lib/server.py")
        task = task.replace("status: pending", "status: done").replace(
            "agent: null", "agent: coder").replace("base: null", f"base: {self.head}\nmember_base: {member_base}")
        self.write("T001", task)
        (self.coordinator / ".project" / "plan").mkdir(parents=True, exist_ok=True)
        (self.coordinator / ".project" / "plan" / "PLAN.md").write_bytes(
            PLAN_WAVE.format(title="demo").encode("utf-8"))

        state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")
        result = check_task_briefs.validate_plan_task_briefs(self.coordinator, self.head, ".project")
        self.assertEqual(result["tasks"], 1)

    def test_member_brief_during_build_resolves_at_the_bound_branch_tip(self) -> None:
        git(self.member, "checkout", "-q", "-b", "gsd-path/acme-M001")
        (self.member / "src" / "landed.py").write_bytes("earlier landing\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "earlier landing")
        git(self.member, "checkout", "-q", "main")
        self.write("T001", member_task("T001", "src/new.py", "Follow `src/landed.py`.",
                                       verify="test -f src/landed.py"))
        self.assertIn("path missing at the layer base: src/landed.py", self.problems())
        lock = self.coordinator / ".project" / "build" / "members.json"
        lock.parent.mkdir(parents=True)
        lock.write_bytes('{"schema": "gsd-path/member-lock/v1", "members": [{"name": "web", '
                        '"branch": "gsd-path/acme-M001", "base": "x"}]}'.encode("utf-8"))
        self.assertEqual(self.problems(), "")

    def test_plan_recovery_brief_uses_the_existing_build_lock(self) -> None:
        git(self.member, "checkout", "-q", "-b", "gsd-path/acme-M001")
        (self.member / "src" / "landed.py").write_bytes("earlier landing\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "earlier landing")
        git(self.member, "checkout", "-q", "main")
        (self.coordinator / ".project" / "plan").mkdir()
        (self.coordinator / ".project" / "plan" / "PLAN.md").write_bytes(
            PLAN_WAVE.format(title="demo").encode("utf-8"))
        self.write("T001", member_task("T001", "src/new.py", "Follow `src/landed.py`.",
                                       verify="test -f src/landed.py"))
        with self.assertRaisesRegex(pipeline_state.PipelineStateError, "src/landed.py"):
            state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")
        lock = self.coordinator / ".project" / "build" / "members.json"
        lock.parent.mkdir(parents=True)
        lock.write_bytes('{"schema": "gsd-path/member-lock/v1", "members": [{"name": "web", '
                        '"branch": "gsd-path/acme-M001", "base": "x"}]}'.encode("utf-8"))
        state_checkpoint._validate_plan_briefs(self.coordinator, "plan", ".project")

    def test_repo_must_name_a_member(self) -> None:
        self.write("T001", member_task("T001", "src/app.py", "Edit `src/app.py`.", repo="sdk"))
        self.assertIn("repo: names no member in MEMBERS.md: sdk", self.problems())


class MemberTaskReadyTests(unittest.TestCase):
    def test_same_path_in_different_repos_is_ready_together(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            run_git(repo, "init", "-q")
            run_git(repo, "config", "user.email", "t@t")
            run_git(repo, "config", "user.name", "t")
            run_git(repo, "switch", "-q", "-c", BRANCH)
            (repo / ".project" / "plan").mkdir(parents=True)
            (repo / ".project" / "tasks").mkdir()
            (repo / ".project" / "STATE.md").write_bytes(STATE.format(phase="build", branch=BRANCH).encode("utf-8"))
            (repo / ".project" / "plan" / "PLAN.md").write_bytes(plan_text(((
                ("T001", "One", (), ("app.py",)), ("T002", "Two", (), ("app.py",))),)).encode("utf-8"))
            (repo / ".project" / "tasks" / "T001-task.md").write_bytes(
                task_text("T001", "One", 1, (), ("app.py",)).encode("utf-8"))
            (repo / ".project" / "tasks" / "T002-task.md").write_bytes(
                task_text("T002", "Two", 1, (), ("app.py",)).replace("files:", "repo: web\nfiles:", 1).encode("utf-8"))
            run_git(repo, "add", "-A")
            run_git(repo, "commit", "-q", "-m", "plan")
            ready = build_state.ready(str(repo))
            self.assertEqual(sorted(task["id"] for task in ready["ready"]), ["T001", "T002"])
            self.assertEqual({task["id"]: task.get("repo") for task in ready["ready"]}, {"T001": None, "T002": "web"})


class MemberTaskGraphTests(unittest.TestCase):
    def graph(self, *tasks):
        texts = {task_id: text for task_id, text in tasks}
        return check_handoffs._validate_task_graph({1: "Deliver", 2: "Next"}, texts, initial=True)

    def task(self, task_id: str, files: str, repo: str = "", deps: str = "[]", wave: int = 1) -> tuple:
        text = member_task(task_id, files, "Change the module.", repo=repo)
        text = text.replace("deps: []", f"deps: {deps}").replace("wave: 1", f"wave: {wave}")
        return task_id, text

    def test_same_path_in_different_repos_does_not_overlap(self) -> None:
        self.graph(self.task("T001", "app.py"), self.task("T002", "app.py", repo="web"))
        with self.assertRaisesRegex(check_handoffs.HandoffError, "same-wave file overlap"):
            self.graph(self.task("T001", "app.py", repo="web"), self.task("T002", "app.py", repo="web"))

    def test_dependency_files_stay_in_their_repo(self) -> None:
        supplied = self.graph(
            self.task("T001", "shared.py"),
            self.task("T002", "client.py", repo="web", deps="[T001]", wave=2),
            self.task("T003", "server.py", deps="[T001]", wave=2),
        )
        self.assertEqual(supplied["T002"], set())
        self.assertEqual(supplied["T003"], {"shared.py"})


if __name__ == "__main__":
    unittest.main()
