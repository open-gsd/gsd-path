import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import integration, isolation, members, pipeline_git
from scripts.archive_milestone import ArchiveError
import tests.test_member_integration as member_integration
import tests.test_pipeline_git as pipeline_git_tests

git = member_integration.git
ARCHIVE = member_integration.ARCHIVE
TAG = member_integration.TAG
BOUND = "refs/heads/gsd-path/demo-M001"


class MemberRetirementTests(unittest.TestCase):
    fixture = member_integration.MemberIntegrationTests.fixture
    setUp = member_integration.MemberIntegrationTests.setUp
    remote_ref = member_integration.MemberIntegrationTests.remote_ref

    def retire(self) -> dict:
        return integration.retire_member(self.root, "web", ARCHIVE, self.member_tip, self.merge, TAG)

    def integrate(self) -> None:
        self.bound = Path(isolation.member_bound_checkout(self.root, "web")["checkout"])
        self.merge = integration.integrate_member(self.root, "web", ARCHIVE, self.member_tip)["merge"]

    def test_retirement_deletes_member_bound_branches_and_clears_authorizations(self) -> None:
        self.integrate()
        tag_object = self.remote_ref(f"refs/tags/{TAG}")
        self.retire()
        self.assertEqual(self.remote_ref(BOUND), "")
        self.assertEqual(git(self.member, "rev-parse", "--verify", "--quiet", BOUND, check=False), "")
        self.assertFalse(self.bound.exists())
        self.assertEqual(git(self.member, "for-each-ref", "refs/gsd-path/authorizations/demo/"), "")
        self.assertEqual(self.remote_ref("refs/heads/main"), self.merge)
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), tag_object)
        self.retire()  # a rerun after a crash finds nothing left to retire

    def test_retirement_removes_a_bound_checkout_with_submodules(self) -> None:
        # A member product tree can carry submodules that its Prepare step
        # initialises; git refuses a plain worktree removal for them no matter
        # how clean the superproject is (#486).
        nested = self.root.parent / "nested"
        git(self.root.parent, "init", "-q", "-b", "main", str(nested))
        git(nested, "config", "user.name", "t")
        git(nested, "config", "user.email", "t@t")
        (nested / "lib.txt").write_bytes("submodule\n".encode("utf-8"))
        git(nested, "add", ".")
        git(nested, "commit", "-q", "-m", "nested base")
        nested_tip = git(nested, "rev-parse", "HEAD")
        advance = self.root.parent / "advance"
        git(self.member, "worktree", "add", "-q", "--detach", str(advance), self.member_tip)
        (advance / ".gitmodules").write_bytes(
            (f'[submodule "vendor/lib"]\n\tpath = vendor/lib\nurl = {nested.as_posix()}\n').encode("utf-8"))
        git(advance, "add", ".gitmodules")
        git(advance, "update-index", "--add", "--cacheinfo", f"160000,{nested_tip},vendor/lib")
        git(advance, "commit", "-q", "-m", "member: vendor the lib")
        self.member_tip = git(advance, "rev-parse", "HEAD")
        git(self.member, "branch", "-f", "gsd-path/demo-M001", self.member_tip)
        # The advance worktree's own index carries the gitlink, so its removal
        # needs force too — the very refusal this test exercises at retire time.
        git(self.member, "worktree", "remove", "--force", str(advance))

        self.integrate()
        # Local-path submodule clones need the file transport, which git only
        # re-enables from the command line for submodules.
        initialised = subprocess.run(
            ["git", "-c", "protocol.file.allow=always", "-C", str(self.bound),
             "submodule", "update", "--init"], capture_output=True, encoding="utf-8")
        self.assertEqual(initialised.returncode, 0, initialised.stderr)
        self.assertEqual(git(self.bound, "status", "--porcelain", "--untracked-files=all"), "")
        self.assertTrue((self.bound / "vendor" / "lib" / "lib.txt").is_file())

        self.retire()

        self.assertFalse(self.bound.exists())
        self.assertEqual(self.remote_ref(BOUND), "")

    def test_dirty_bound_checkout_blocks_retirement_before_the_remote_delete(self) -> None:
        self.integrate()
        (self.bound / "dirty.txt").write_bytes("dirt\n".encode("utf-8"))
        with self.assertRaisesRegex(ArchiveError, "is not clean"):
            self.retire()
        self.assertEqual(self.remote_ref(BOUND), self.member_tip)

    def test_moved_remote_bound_branch_blocks_retirement(self) -> None:
        self.integrate()
        git(self.member, "push", "-q", "--force", "origin", f"{self.main}:{BOUND}")
        with self.assertRaisesRegex(ArchiveError, "moved"):
            self.retire()
        self.assertEqual(self.remote_ref(BOUND), self.main)

    def test_team_worktree_holding_bound_branch_is_preserved(self) -> None:
        self.integrate()
        git(self.member, "worktree", "remove", str(self.bound))
        team = self.root.parent / "team-bound"
        git(self.member, "worktree", "add", "-q", str(team), "gsd-path/demo-M001")
        with self.assertRaisesRegex(ArchiveError, "outside Path's workspace"):
            self.retire()
        self.assertTrue(team.exists())
        self.assertEqual(git(team, "symbolic-ref", "HEAD"), BOUND)
        self.assertEqual(self.remote_ref(BOUND), self.member_tip)

    def test_moved_local_bound_branch_preserves_remote(self) -> None:
        self.integrate()
        git(self.bound, "commit", "-q", "--allow-empty", "-m", "local move")
        moved = git(self.member, "rev-parse", BOUND)
        with self.assertRaisesRegex(ArchiveError, "moved"):
            self.retire()
        self.assertEqual(self.remote_ref(BOUND), self.member_tip)
        self.assertEqual(git(self.member, "rev-parse", BOUND), moved)
        self.assertTrue(self.bound.exists())

    def test_member_integrated_differently_from_the_ship_commit_is_not_retired(self) -> None:
        self.integrate()
        self.merge = "c" * 40
        with self.assertRaisesRegex(ArchiveError, "differs from the ship commit"):
            self.retire()
        self.assertEqual(self.remote_ref(BOUND), self.member_tip)

    def test_unintegrated_member_is_not_retired(self) -> None:
        self.merge = "c" * 40
        with self.assertRaisesRegex(ArchiveError, "integrate"):
            self.retire()
        self.assertNotEqual(git(self.member, "rev-parse", "--verify", "--quiet", BOUND, check=False), "")


class BindNextRetiresMembersTests(unittest.TestCase):
    def test_bind_next_retires_each_member_named_by_the_ship_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _, repo, _, _ = pipeline_git_tests.make_integrated_milestone(tmp)
            rows = [{"name": "web", "reviewed_head": "b" * 40, "merge": "c" * 40, "tag": TAG}]
            pipeline_git_tests.run_git(repo, "commit", "--allow-empty", "--amend", "-m", "ship: M001 — first",
                                       "-m", pipeline_git.ship_commit_body(".project/archive/001-first", "d" * 40, rows))
            ship = pipeline_git_tests.run_git(repo, "rev-parse", "HEAD").stdout.strip()
            pipeline_git_tests.run_git(repo, "push", "-q", "--force", "origin", "gsd-path/M001")
            pipeline_git_tests.run_git(repo, "switch", "-q", "main")
            pipeline_git_tests.run_git(repo, "reset", "-q", "--hard", "origin/main~1")
            pipeline_git_tests.run_git(repo, "merge", "-q", "--no-ff", "gsd-path/M001", "-m",
                                       "integrate: M001 — merge gsd-path/M001 into main")
            landing = pipeline_git_tests.run_git(repo, "rev-parse", "HEAD").stdout.strip()
            pipeline_git_tests.run_git(repo, "push", "-q", "--force", "origin", "main")
            pipeline_git_tests.run_git(repo, "fetch", "-q", "origin")
            pipeline_git_tests.run_git(repo, "switch", "-q", "gsd-path/M001")
            with mock.patch.object(integration, "retire_member") as retired:
                pipeline_git.bind_next_milestone_branch(repo, "gsd-path/M002", "gsd-path/M001", ship,
                                                        "origin/main", landing, landing)
            retired.assert_called_once_with(repo.resolve(), "web", ".project/archive/001-first", "b" * 40,
                                            "c" * 40, TAG)


if __name__ == "__main__":
    unittest.main()
