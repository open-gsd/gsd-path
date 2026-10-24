import re
import shutil
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import tests.test_member_landing as landing
from scripts import isolation
from tests._platform import requires_symlink

TASK_FILE = landing.TASK_FILE
git = landing.git
AUTH = "refs/gsd-path/task-authorizations/acme-T001"


class MemberPrepareTests(unittest.TestCase):
    setUp = landing.MemberLandingTests.setUp
    tearDown = landing.MemberLandingTests.tearDown

    def declare_prepare(self, command: str) -> None:
        path = self.coordinator / ".project" / "MEMBERS.md"
        text = path.read_text(encoding="utf-8")
        if re.search(r"(?m)^Prepare: .*$", text):
            text = re.sub(r"(?m)^Prepare: .*$", f"Prepare: {command}", text)
        else:
            text = text.replace("Integration: default\n", f"Integration: default\nPrepare: {command}\n")
        path.write_bytes(text.encode("utf-8"))

    def test_prepare_provisions_a_fresh_task_isolate_before_any_verify(self) -> None:
        bound = Path(isolation.member_bound_checkout(self.coordinator, "web")["checkout"])
        (bound / ".gitignore").write_bytes(b"build/\n")
        git(bound, "add", ".gitignore")
        git(bound, "commit", "-q", "-m", "ignore build")
        self.declare_prepare("mkdir -p build && printf sdk > build/sdk.h")
        isolated = isolation.isolate_member_task(self.coordinator, "web", "T002")
        sidecar = Path(isolated["worktree"])
        # Provisioned before return: a Verify needing build/sdk.h would pass.
        self.assertEqual((sidecar / "build" / "sdk.h").read_text(encoding="utf-8"), "sdk")
        self.assertIsNotNone(isolated["prepare"])
        self.assertEqual(isolated["prepare"]["exit_code"], 0)
        # Activation and landing gates are unaffected by ignored provisioning.
        self.assertEqual(sorted(isolation.uncommitted_paths(sidecar)), [])

    def test_prepare_failure_fails_isolation_loudly(self) -> None:
        self.declare_prepare("exit 3")
        with self.assertRaisesRegex(isolation.IsolationError, "Prepare failed"):
            isolation.isolate_member_task(self.coordinator, "web", "T002")

    def test_prepare_failure_retires_the_fresh_isolate_so_retry_works(self) -> None:
        self.declare_prepare("exit 3")
        with self.assertRaisesRegex(isolation.IsolationError, "Prepare failed"):
            isolation.isolate_member_task(self.coordinator, "web", "T002")
        # A retry isolates cleanly instead of refusing on the existing path.
        self.declare_prepare("true")
        isolated = isolation.isolate_member_task(self.coordinator, "web", "T002")
        self.assertIsNotNone(isolated["prepare"])

    def test_prepare_may_not_link_out_of_the_isolate(self) -> None:
        target = self.root / "shared-sdk"
        target.mkdir()
        (target / "sdk.h").write_text("shared\n", encoding="utf-8")
        self.declare_prepare(f"ln -s {target} build-link")
        with self.assertRaisesRegex(isolation.IsolationError, "never link"):
            isolation.isolate_member_task(self.coordinator, "web", "T002")
        self.assertEqual((target / "sdk.h").read_text(encoding="utf-8"), "shared\n")

    def test_a_member_without_prepare_isolates_unchanged(self) -> None:
        isolated = isolation.isolate_member_task(self.coordinator, "web", "T002")
        self.assertIsNone(isolated["prepare"])
        self.assertFalse((Path(isolated["worktree"]) / "build").exists())

    def test_prepare_runs_for_fresh_member_verify_sidecars(self) -> None:
        self.declare_prepare("printf sdk > sdk.h")
        from scripts import members as members_module
        # Ship-time regression verifies create fresh member sidecars beside the
        # coordinator verify sidecar; Prepare must provision each one (#463).
        lock = self.coordinator / members_module.LOCK_PATH
        lock.parent.mkdir(parents=True, exist_ok=True)
        bound = git(self.member, "rev-parse", "gsd-path/acme-M001")
        lock.write_bytes((__import__("json")).dumps({"schema": members_module.LOCK_SCHEMA, "members": [
            {"name": "web", "checkout": str(self.member), "branch": "gsd-path/acme-M001",
             "base": bound}]}, indent=2).encode("utf-8"))
        coordinator_sidecar = self.root / "workspace" / "verify"
        coordinator_sidecar.parent.mkdir(parents=True, exist_ok=True)
        created = isolation.isolate_member_verify(self.coordinator, coordinator_sidecar)
        try:
            self.assertEqual((Path(created["web"]["worktree"]) / "sdk.h").read_text(encoding="utf-8"), "sdk")
        finally:
            isolation.retire_member_verify(created)


class MemberActivationTests(unittest.TestCase):
    setUp = landing.MemberLandingTests.setUp
    tearDown = landing.MemberLandingTests.tearDown
    land = landing.MemberLandingTests.land
    edit = landing.MemberLandingTests.edit

    def copy(self) -> Path:
        return self.sidecar / ".gsd-path-coordinator" / TASK_FILE

    def test_activation_writes_an_excluded_live_copy_and_authorization(self) -> None:
        text = self.copy().read_text(encoding="utf-8")
        for line in ("status: in-progress", "agent: coder", f"base: {self.base}",
                     f"member_base: {self.member_base}", f"worktree: {self.sidecar}",
                     "task_branch: gsd-path-task/acme-T001"):
            self.assertIn(line + "\n", text)
        self.assertEqual(git(self.sidecar, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertEqual(git(self.member, "rev-parse", AUTH), self.member_base)
        self.assertEqual(git(self.coordinator, "status", "--porcelain"), "")
        self.assertIn("status: pending\n", (self.coordinator / TASK_FILE).read_text(encoding="utf-8"))

    def test_activation_is_idempotent_for_the_same_agent(self) -> None:
        before = self.copy().read_bytes()
        isolation.activate_member_task(self.coordinator, "web", "T001", "coder", TASK_FILE, self.base)
        self.assertEqual(self.copy().read_bytes(), before)

    def test_activation_requires_an_assigned_single_line_agent(self) -> None:
        self.copy().unlink()
        git(self.member, "update-ref", "-d", AUTH)
        for agent in ("", "null", "coder\nother"):
            with self.subTest(agent=agent):
                with self.assertRaisesRegex(isolation.IsolationError, "assigned agent"):
                    isolation.activate_member_task(self.coordinator, "web", "T001", agent, TASK_FILE, self.base)
                self.assertFalse(self.copy().exists())
                self.assertEqual(git(self.member, "rev-parse", "--verify", "--quiet", AUTH, check=False), "")

    def test_activation_rejects_a_copy_from_an_older_coordinator_base(self) -> None:
        before = self.copy().read_bytes()
        (self.coordinator / "other.txt").write_bytes("unrelated\n".encode("utf-8"))
        git(self.coordinator, "add", "other.txt")
        git(self.coordinator, "commit", "-q", "-m", "unrelated")
        new_base = git(self.coordinator, "rev-parse", "HEAD")
        with self.assertRaisesRegex(isolation.IsolationError, "another agent or base"):
            isolation.activate_member_task(self.coordinator, "web", "T001", "coder", TASK_FILE, new_base)
        self.assertEqual(self.copy().read_bytes(), before)
        self.assertEqual(git(self.member, "rev-parse", AUTH), self.member_base)

    def test_activation_requires_the_sidecar_at_its_member_base(self) -> None:
        self.copy().unlink()
        git(self.member, "update-ref", "-d", AUTH)
        self.edit()
        git(self.sidecar, "commit", "-q", "--no-verify", "-am", "early")
        with self.assertRaisesRegex(isolation.IsolationError, "member base"):
            isolation.activate_member_task(self.coordinator, "web", "T001", "coder", TASK_FILE, self.base)

    @requires_symlink
    def test_activation_refuses_a_tracked_copy_root_symlink(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_bytes("keep\n".encode("utf-8"))
        git(self.member, "update-ref", "-d", AUTH)
        copy_root = self.sidecar / ".gsd-path-coordinator"
        shutil.rmtree(copy_root)
        copy_root.symlink_to(outside, target_is_directory=True)
        git(self.sidecar, "add", "-f", ".gsd-path-coordinator")
        git(self.sidecar, "commit", "-q", "--no-verify", "-m", "track copy root")
        git(self.bound, "reset", "--hard", git(self.sidecar, "rev-parse", "HEAD"))
        with self.assertRaisesRegex(isolation.IsolationError, "copy directory is tracked"):
            isolation.activate_member_task(self.coordinator, "web", "T001", "coder", TASK_FILE, self.base)
        self.assertEqual([(path.name, path.read_text(encoding="utf-8")) for path in outside.iterdir()],
                         [("keep.txt", "keep\n")])
        self.assertEqual(git(self.member, "rev-parse", "--verify", "--quiet", AUTH, check=False), "")

    def test_landing_requires_activation_and_its_authorization(self) -> None:
        self.edit()
        git(self.member, "update-ref", "-d", AUTH)
        with self.assertRaisesRegex(isolation.IsolationError, "authoriz"):
            self.land()
        git(self.member, "update-ref", AUTH, self.member_base)
        self.copy().unlink()
        with self.assertRaisesRegex(isolation.IsolationError, "activ"):
            self.land()
        self.assertEqual(git(self.bound, "rev-parse", "HEAD"), self.member_base)

    def test_coder_log_lands_in_the_coordinator_record(self) -> None:
        self.edit()
        path = self.copy()
        path.write_bytes((path.read_text(encoding="utf-8") + "- coder: changed app\n").encode("utf-8"))
        self.land()
        record = (self.coordinator / TASK_FILE).read_text(encoding="utf-8")
        self.assertIn("- coder: changed app\n", record)
        self.assertIn("status: done\n", record)
        self.assertEqual(git(self.coordinator, "show", f"HEAD:{TASK_FILE}"), record.rstrip("\n"))

    def test_copy_must_keep_the_contract_and_only_grow_its_log(self) -> None:
        self.edit()
        path = self.copy()
        original = path.read_text(encoding="utf-8")
        path.write_bytes(original.replace("  - app.py", "  - app.py\n  - extra.py").encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "contract"):
            self.land()
        path.write_bytes(original.replace("- created\n", "- rewritten\n").encode("utf-8"))
        with self.assertRaisesRegex(isolation.IsolationError, "append-only"):
            self.land()
        self.assertEqual(git(self.bound, "rev-parse", "HEAD"), self.member_base)

    def test_landing_rejects_a_copy_without_an_assigned_agent(self) -> None:
        self.edit()
        original = self.copy().read_text(encoding="utf-8")
        for agent in ("null", ""):
            with self.subTest(agent=agent):
                self.copy().write_bytes(original.replace("agent: coder\n", f"agent: {agent}\n").encode("utf-8"))
                with self.assertRaisesRegex(isolation.IsolationError, "assigned agent"):
                    self.land()
                self.assertEqual(git(self.bound, "rev-parse", "HEAD"), self.member_base)
                self.assertFalse(landing.MemberLandingTests.journal(self).exists())

    @requires_symlink
    def test_landing_refuses_a_symlinked_copy_parent(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_bytes("keep\n".encode("utf-8"))
        copy_root = self.sidecar / ".gsd-path-coordinator"
        shutil.rmtree(copy_root)
        copy_root.symlink_to(outside, target_is_directory=True)
        self.edit()
        with self.assertRaisesRegex(isolation.IsolationError, "copy parent is not a real directory"):
            self.land()
        self.assertEqual([(path.name, path.read_text(encoding="utf-8")) for path in outside.iterdir()],
                         [("keep.txt", "keep\n")])
        self.assertEqual(git(self.bound, "rev-parse", "HEAD"), self.member_base)

    def test_unstaged_bookkeeping_may_stay_dirty_while_landing(self) -> None:
        ledger = self.coordinator / ".project" / "build" / "verify-ledger.jsonl"
        ledger.write_bytes("{}\n".encode("utf-8"))
        self.edit()
        self.land()
        self.assertEqual(git(self.coordinator, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"),
                         TASK_FILE)

    def test_staged_bookkeeping_never_enters_the_record(self) -> None:
        ledger = self.coordinator / ".project" / "build" / "verify-ledger.jsonl"
        ledger.write_bytes("{}\n".encode("utf-8"))
        git(self.coordinator, "add", "-f", str(ledger))
        self.edit()
        with self.assertRaisesRegex(isolation.IsolationError, "verify-ledger"):
            self.land()
        self.assertEqual(git(self.bound, "rev-parse", "HEAD"), self.member_base)

    def test_retire_clears_the_authorization(self) -> None:
        self.edit()
        self.land()
        isolation.retire_member_task(self.coordinator, "web", "T001")
        self.assertEqual(git(self.member, "rev-parse", "--verify", "--quiet", AUTH, check=False), "")

    def test_retire_reports_authorization_deletion_failure(self) -> None:
        self.edit()
        self.land()
        original = isolation.run_git

        def reject_authorization(repo, *arguments):
            if arguments == ("update-ref", "-d", AUTH):
                return subprocess.CompletedProcess(arguments, 1, "", "ref deletion failed")
            return original(repo, *arguments)

        with mock.patch.object(isolation, "run_git", side_effect=reject_authorization):
            with self.assertRaisesRegex(isolation.IsolationError, "ref deletion failed"):
                isolation.retire_member_task(self.coordinator, "web", "T001")
        self.assertEqual(git(self.member, "rev-parse", AUTH), self.member_base)


if __name__ == "__main__":
    unittest.main()
