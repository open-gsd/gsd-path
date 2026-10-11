import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import isolation, lean_verification
import tests.test_lean_verification as lean_tests

ROOT = Path(__file__).resolve().parents[1]
MEMBERS = ROOT / "scripts" / "members.py"
COMMAND = "test -f ../web/lib.py && python3 -m unittest -q test_hello"


def git(repo: Path, *arguments: str, check: bool = True) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=repo,
                          encoding="utf-8", errors="replace", capture_output=True, check=check).stdout.strip()


class MemberProjectVerifyTests(unittest.TestCase):
    fixture = lean_tests.LeanVerificationTests.fixture

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name).resolve()
        environment = mock.patch.dict(os.environ, {"GSD_PATH_WORKTREE_ROOT": str(base / "workspace")})
        environment.start()
        self.addCleanup(environment.stop)
        self.root = base / "acme"
        self.root.mkdir()
        self.fixture(self.root)
        self.member = base / "frontend-checkout"
        self.member.mkdir()
        # Classes that borrow this fixture set member_default for another default branch.
        default = getattr(self, "member_default", "main")
        git(self.member, "init", "-q", "-b", default)
        (self.member / "README.md").write_bytes("web\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", f"refs/remotes/origin/{default}", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default}")
        state = self.root / ".project" / "STATE.md"
        shipping = state.read_text(encoding="utf-8")
        state.write_bytes(shipping.replace("phase: ship", "phase: plan").encode("utf-8"))
        joined = subprocess.run([sys.executable, str(MEMBERS), "add", "--repo", str(self.root), "--name", "web",
                                 "--checkout", str(self.member)], encoding="utf-8", errors="replace", capture_output=True)
        self.assertEqual(joined.returncode, 0, joined.stderr)
        state.write_bytes(shipping.encode("utf-8"))
        git(self.member, "checkout", "-q", "-b", "gsd-path/demo-M001")
        (self.member / "lib.py").write_bytes("landed = True\n".encode("utf-8"))
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "member landing")
        self.member_tip = git(self.member, "rev-parse", "HEAD")
        git(self.member, "checkout", "-q", default)
        lock = self.root / ".project" / "build" / "members.json"
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_bytes(json.dumps({"schema": "gsd-path/member-lock/v1", "members": [
            {"name": "web", "branch": "gsd-path/demo-M001", "base": git(self.member, "rev-parse", default)}]}).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "member milestone")
        self.head = git(self.root, "rev-parse", "HEAD")

    def use_member_verify_command(self) -> None:
        plan = self.root / ".project" / "plan" / "PLAN.md"
        text = plan.read_text(encoding="utf-8")
        start = text.index("Project verify:")
        end = text.index("\n", start)
        plan.write_bytes((text[:start] + f"Project verify: {COMMAND}" + text[end:]).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "project verify uses the member")
        self.head = git(self.root, "rev-parse", "HEAD")

    def ledger_rows(self) -> list:
        ledger = self.root / ".project" / "build" / "verify-ledger.jsonl"
        return [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines()] if ledger.exists() else []

    def test_project_verify_sees_member_sidecars_beside_the_coordinator(self) -> None:
        self.use_member_verify_command()
        self.assertNotEqual(self.member.name, "web")
        result = lean_verification.verify_project(self.root, self.head)
        self.assertTrue(result["passed"], result["execution"])
        self.assertEqual(result["execution"]["members"], {"web": self.member_tip})
        self.assertEqual(git(self.member, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.member, "branch", "--list", "gsd-path-verify/*"), "")

    def test_existing_member_sidecar_survives_failed_setup(self) -> None:
        sidecar = self.root.parent / "verify" / "coordinator"
        created = isolation.isolate_member_verify(self.root, sidecar)
        with self.assertRaisesRegex(isolation.IsolationError, "path already exists"):
            isolation.isolate_member_verify(self.root, sidecar)
        self.assertTrue(Path(created["web"]["worktree"]).is_dir())
        self.assertEqual(git(self.member, "rev-parse", created["web"]["branch"]), self.member_tip)
        isolation.retire_member_verify(created)

    def test_member_named_project_verify_is_refused_before_sidecar_creation(self) -> None:
        listed = self.root / ".project" / "MEMBERS.md"
        listed.write_bytes(listed.read_text(encoding="utf-8").replace("## web\n", "## project-verify\n").encode("utf-8"))
        marker = Path(git(self.member, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "gsd-path" / "member.json"
        role = json.loads(marker.read_text(encoding="utf-8"))
        role["name"] = "project-verify"
        marker.write_bytes(json.dumps(role).encode("utf-8"))
        lock = self.root / ".project" / "build" / "members.json"
        locked = json.loads(lock.read_text(encoding="utf-8"))
        locked["members"][0]["name"] = "project-verify"
        lock.write_bytes(json.dumps(locked).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "lock colliding member name")
        head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(isolation.IsolationError, "locked member project-verify collides"):
            lean_verification.verify_project(self.root, head)
        self.assertEqual(git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.root, "branch", "--list", "gsd-path-verify/*"), "")
        self.assertEqual(git(self.member, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_unlocked_stale_marker_does_not_block_cleanup(self) -> None:
        api = self.root.parent / "api-checkout"
        api.mkdir()
        git(api, "init", "-q", "-b", "main")
        listed = self.root / ".project" / "MEMBERS.md"
        listed.write_bytes((listed.read_text(encoding="utf-8") + f"\n## api\nCheckout: {api}\nRemote: https://github.com/acme/api.git\nIntegration: default\n").encode("utf-8"))
        marker = api / ".git" / "gsd-path" / "member.json"
        marker.parent.mkdir()
        marker.write_bytes(json.dumps({"schema": "gsd-path/member/v1", "coordinator": str(self.root),
                                      "project": "wrong", "name": "api"}).encode("utf-8"))
        self.use_member_verify_command()
        result = lean_verification.verify_project(self.root, self.head)
        self.assertTrue(result["passed"], result)

    def test_member_cleanup_surfaces_git_failures(self) -> None:
        for operation in ("remove", "delete"):
            with self.subTest(operation=operation):
                sidecar = self.root.parent / operation / "coordinator"
                created = isolation.isolate_member_verify(self.root, sidecar)
                original = isolation.run_git

                def fail_selected(repo, *arguments):
                    if ((operation == "remove" and arguments[:2] == ("worktree", "remove"))
                            or (operation == "delete" and arguments[:2] == ("branch", "-D"))):
                        return subprocess.CompletedProcess(arguments, 1, "", "cleanup failed")
                    return original(repo, *arguments)

                with mock.patch.object(isolation, "run_git", side_effect=fail_selected):
                    with self.assertRaisesRegex(isolation.IsolationError, "cleanup failed"):
                        isolation.retire_member_verify(created)
                if operation == "remove":
                    self.assertTrue(Path(created["web"]["worktree"]).exists())
                    isolation.retire_member_verify(created)
                else:
                    self.assertEqual(git(self.member, "branch", "--list", created["web"]["branch"]),
                                     created["web"]["branch"])
                    git(self.member, "branch", "-D", created["web"]["branch"])

    def test_member_verify_rejects_changed_sidecar_head(self) -> None:
        self.use_member_verify_command()
        plan = self.root / ".project" / "plan" / "PLAN.md"
        plan.write_bytes(plan.read_text(encoding="utf-8").replace(COMMAND, "git -C ../web reset --hard main").encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "verify changes member head")
        head = git(self.root, "rev-parse", "HEAD")
        gap = self.root / ".project/review/final-gap-1.md"
        before = gap.read_bytes() if gap.exists() else None
        with self.assertRaisesRegex(isolation.IsolationError, "HEAD changed"):
            lean_verification.verify_project(self.root, head)
        self.assertEqual(gap.read_bytes() if gap.exists() else None, before)
        self.assertEqual(git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.root, "branch", "--list", "gsd-path-verify/*"), "")
        git(self.member, "reset", "--hard", self.member_tip)
        retry = lean_verification.verify_project(self.root, head)
        self.assertTrue(retry["passed"], retry)

    def test_detached_member_sidecar_is_retired_before_retry(self) -> None:
        self.use_member_verify_command()
        plan = self.root / ".project" / "plan" / "PLAN.md"
        plan.write_bytes(plan.read_text(encoding="utf-8").replace(COMMAND, "git -C ../web checkout --detach HEAD").encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "verify detaches member")
        head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(isolation.IsolationError, "HEAD is detached"):
            lean_verification.verify_project(self.root, head)
        self.assertEqual(git(self.member, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.member, "branch", "--list", "gsd-path-verify/*"), "")
        self.assertEqual(git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        plan.write_bytes(plan.read_text(encoding="utf-8").replace("git -C ../web checkout --detach HEAD", COMMAND).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "restore verify command")
        retry = lean_verification.verify_project(self.root, git(self.root, "rev-parse", "HEAD"))
        self.assertTrue(retry["passed"], retry)

    def test_member_sidecar_on_another_branch_is_retired_before_retry(self) -> None:
        self.use_member_verify_command()
        plan = self.root / ".project" / "plan" / "PLAN.md"
        command = "git -C ../web checkout gsd-path/demo-M001"
        plan.write_bytes(plan.read_text(encoding="utf-8").replace(COMMAND, command).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "verify switches member branch")
        head = git(self.root, "rev-parse", "HEAD")
        with self.assertRaisesRegex(isolation.IsolationError, "branch changed"):
            lean_verification.verify_project(self.root, head)
        self.assertEqual(git(self.member, "rev-parse", "gsd-path/demo-M001"), self.member_tip)
        self.assertEqual(git(self.member, "worktree", "list", "--porcelain").count("worktree "), 1)
        self.assertEqual(git(self.member, "branch", "--list", "gsd-path-verify/*"), "")
        self.assertEqual(git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)
        plan.write_bytes(plan.read_text(encoding="utf-8").replace(command, COMMAND).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "restore verify command")
        retry = lean_verification.verify_project(self.root, git(self.root, "rev-parse", "HEAD"))
        self.assertTrue(retry["passed"], retry)
        self.assertEqual(git(self.member, "rev-parse", "gsd-path/demo-M001"), self.member_tip)

    def test_failed_member_verify_keeps_exact_output_in_gap(self) -> None:
        self.use_member_verify_command()
        command = "printf 'out\\x60\\x60\\x60\\x60text\\n'; printf 'member failure \\x60\\x60\\x60 detail\\n' >&2; exit 7"
        plan = self.root / ".project" / "plan" / "PLAN.md"
        plan.write_bytes(plan.read_text(encoding="utf-8").replace(COMMAND, command).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "record failing member verify")
        result = lean_verification.verify_project(self.root, git(self.root, "rev-parse", "HEAD"))
        self.assertFalse(result["passed"])
        self.assertEqual(result["execution"]["stdout"], "out````text\n")
        self.assertEqual(result["execution"]["stderr"], "member failure ``` detail\n")
        gap = (self.root / ".project/review/final-gap-1.md").read_text(encoding="utf-8")
        self.assertIn("exact stdout and stderr are in the Output section", gap)
        self.assertIn("### stdout\n\n`````\nout````text\n`````", gap)
        self.assertIn("### stderr\n\n`````\nmember failure ``` detail\n`````", gap)
        self.assertEqual([row for row in self.ledger_rows() if row["command"] == command], [])

    def test_prepare_final_does_not_accept_existing_member_review(self) -> None:
        self.use_member_verify_command()
        lean_verification.verify_project(self.root, self.head)
        lean_tests.test_handoffs.HandoffValidationTests().write_final_review(self.root)
        result = lean_verification.prepare_final(self.root, self.head)
        self.assertEqual(result["status"], "complete")
        self.assertFalse(result["final"]["reused"])
        self.assertEqual(result["next"], "review-final")

    def test_stale_member_marker_leaves_no_verify_sidecar(self) -> None:
        self.use_member_verify_command()
        marker = Path(git(self.member, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "gsd-path" / "member.json"
        marker.unlink()
        with self.assertRaisesRegex(Exception, "member marker for web"):
            lean_verification.verify_project(self.root, self.head)
        self.assertEqual(git(self.root, "branch", "--list", "gsd-path-verify/*"), "")
        self.assertEqual(git(self.root, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_member_milestone_verify_is_never_reused_from_the_ledger(self) -> None:
        self.use_member_verify_command()
        first = lean_verification.verify_project(self.root, self.head)
        second = lean_verification.verify_project(self.root, self.head)
        self.assertFalse(first["reused"])
        self.assertFalse(second["reused"])
        self.assertEqual([row for row in self.ledger_rows() if row["command"] == COMMAND], [])

    def test_final_review_is_not_reused_for_a_member_milestone(self) -> None:
        wave = next((self.root / ".project" / "review").glob("wave-1.cycle*.md"))
        text = wave.read_text(encoding="utf-8")
        start = text.index("Reviewed HEAD:")
        end = text.index("\n", start)
        wave.write_bytes((text[:start] + f"Reviewed HEAD: {self.head}" + text[end:]).encode("utf-8"))
        git(self.root, "add", "-A")
        git(self.root, "commit", "-q", "-m", "review covers the member milestone")
        head = git(self.root, "rev-parse", "HEAD")
        result = lean_verification.reuse_final(self.root, head)
        self.assertFalse(result["reused"])
        self.assertIn("member", result["reason"])


if __name__ == "__main__":
    unittest.main()
