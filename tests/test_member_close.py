import json
import re
import shutil
import unittest
from pathlib import Path
from unittest import mock

from scripts import integration, members
from scripts.archive_milestone import ArchiveError
from scripts.pipeline_git import ship_commit_body
import tests.test_member_integration as member_integration

git = member_integration.git
ARCHIVE = member_integration.ARCHIVE
TAG = member_integration.TAG


class MemberCloseTests(unittest.TestCase):
    fixture = member_integration.MemberIntegrationTests.fixture
    remote_ref = member_integration.MemberIntegrationTests.remote_ref

    def setUp(self) -> None:
        member_integration.MemberIntegrationTests.setUp(self)
        state = self.root / ".project/STATE.md"
        state.write_bytes(state.read_text(encoding="utf-8").replace("archive: null", f"archive: {ARCHIVE}").encode("utf-8"))
        archive = self.root / ARCHIVE
        (archive / "build").mkdir(parents=True)
        (archive / "review").mkdir()
        shutil.move(str(self.root / ".project/build/members.json"), archive / "build/members.json")
        self.final = archive / "review/FINAL.md"
        self.final.write_bytes(f"# Final Review\n\nReviewed HEAD: {self.head}\n"
                              f"Member reviewed HEAD: web {self.member_tip}\n".encode("utf-8"))
        self.journal = Path(git(self.root, "rev-parse", "--path-format=absolute", "--git-common-dir")) \
            / "gsd-path/member-close/001-demo.json"

    def set_integration(self, mode: str) -> None:
        listed = self.root / ".project/MEMBERS.md"
        listed.write_bytes(re.sub(r"(?m)^Integration: .*$", f"Integration: {mode}",
                                 listed.read_text(encoding="utf-8")).encode("utf-8"))

    def test_close_members_integrates_each_locked_member_and_journals_it(self) -> None:
        result = integration.close_members(self.root)
        merge = self.remote_ref("refs/heads/main")
        row = {"name": "web", "mode": "direct", "reviewed_head": self.member_tip, "status": "integrated",
               "merge": merge, "tag": TAG}
        self.assertEqual(result["status"], "integrated")
        self.assertEqual(result["members"], [row])
        self.assertEqual(json.loads(self.journal.read_text(encoding="utf-8"))["members"], [row])
        self.assertEqual(result["body"], ship_commit_body(ARCHIVE, self.head, [row]))
        self.assertTrue(result["body"].endswith(
            f"Member-Reviewed-HEAD: web@{self.member_tip}\nMember: web {merge} {TAG}\n"))

    def test_rerun_verifies_integrated_members_without_integrating_again(self) -> None:
        first = integration.close_members(self.root)
        with mock.patch.object(integration, "integrate_member", side_effect=AssertionError("integrated twice")):
            second = integration.close_members(self.root)
        self.assertEqual(second["members"], first["members"])

    def blocked_landing(self) -> None:
        """Fast-forward the member default onto the reviewed HEAD (#458).

        This is the state an earlier, user-approved publication leaves: the
        reviewed HEAD is on the member default branch with no Path merge.
        """
        git(self.remote, "fetch", "-q", str(self.member), self.member_tip)
        git(self.remote, "update-ref", "refs/heads/main", self.member_tip)

    def test_adopt_landed_member_closes_only_when_asked(self) -> None:
        self.blocked_landing()
        with self.assertRaisesRegex(ArchiveError, "--adopt-landed-member web="):
            integration.close_members(self.root)
        self.assertEqual(self.remote_ref("refs/heads/main"), self.member_tip)
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

        result = integration.close_members(self.root, adopt={"web": self.member_tip})
        self.assertEqual(result["status"], "integrated")
        row = result["members"][0]
        self.assertIs(row["adopted"], True)
        self.assertEqual(row["merge"], self.member_tip)
        self.assertEqual(row["tag"], TAG)
        # The adoption publishes the bound branch and tag; the default branch is untouched.
        self.assertEqual(self.remote_ref("refs/heads/main"), self.member_tip)
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), self.member_tip)
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), self.member_tip)
        message = git(self.remote, "for-each-ref", "--format=%(contents)", f"refs/tags/{TAG}")
        self.assertIn("Mode: adopted-landing", message)
        self.assertIn(f"Reviewed-HEAD: {self.member_tip}", message)
        self.assertIn(f"Landing: {self.member_tip}", message)
        self.assertIn("Path made no merge", message)
        self.assertTrue(result["body"].endswith(
            f"Member-Reviewed-HEAD: web@{self.member_tip}\nMember: web {self.member_tip} {TAG}\n"))
        self.assertEqual(json.loads(self.journal.read_text(encoding="utf-8"))["members"], [row])

    def test_adoption_refuses_a_mismatched_sha_and_an_unlanded_head(self) -> None:
        # A fresh reviewed HEAD (never landed) with an adoption flag is refused.
        with self.assertRaisesRegex(ArchiveError, "has not reached"):
            integration.close_members(self.root, adopt={"web": self.member_tip})
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

        self.blocked_landing()
        stale = git(self.member, "rev-parse", f"{self.member_tip}~1")
        with self.assertRaisesRegex(ArchiveError, "--adopt-landed-member names"):
            integration.close_members(self.root, adopt={"web": stale})
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_adoption_rerun_validates_without_the_flag(self) -> None:
        self.blocked_landing()
        integration.close_members(self.root, adopt={"web": self.member_tip})
        with mock.patch.object(integration, "integrate_member", side_effect=AssertionError("adopted twice")):
            rerun = integration.close_members(self.root)
        self.assertEqual(rerun["status"], "integrated")
        self.assertIs(rerun["members"][0]["adopted"], True)
        self.assertEqual(rerun["members"][0]["merge"], self.member_tip)

    def test_adoption_flag_names_only_locked_direct_members(self) -> None:
        with self.assertRaisesRegex(ArchiveError, "not locked in this milestone"):
            integration.close_members(self.root, adopt={"other": "a" * 40})
        self.set_integration("pull-request")
        # Refused up front, before any member ref has moved.
        with self.assertRaisesRegex(ArchiveError, "not a direct-mode member"):
            integration.close_members(self.root, adopt={"web": self.member_tip})
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_adoption_cli_rejects_a_malformed_member_sha_pair(self) -> None:
        from scripts import archive_milestone
        for malformed in (f"={'a' * 40}", "web=abc", "web"):
            with self.subTest(item=malformed):
                code = archive_milestone.main(
                    ["close-members", "--repo", str(self.root), "--adopt-landed-member", malformed]
                )
                self.assertEqual(code, 2)

    def test_journal_that_disagrees_with_the_member_origin_blocks(self) -> None:
        integration.close_members(self.root)
        journal = json.loads(self.journal.read_text(encoding="utf-8"))
        journal["members"][0]["merge"] = self.main
        self.journal.write_bytes(json.dumps(journal).encode("utf-8"))
        with self.assertRaisesRegex(ArchiveError, "differs from its member-close journal"):
            integration.close_members(self.root)

    def test_member_is_journaled_pending_before_it_moves(self) -> None:
        with mock.patch.object(integration, "integrate_member", side_effect=ArchiveError("push failed")):
            with self.assertRaisesRegex(ArchiveError, "push failed"):
                integration.close_members(self.root)
        row = json.loads(self.journal.read_text(encoding="utf-8"))["members"][0]
        self.assertEqual((row["name"], row["status"], row["reviewed_head"]), ("web", "pending", self.member_tip))

    def test_pull_request_member_waits_with_a_pending_journal_row(self) -> None:
        self.set_integration("pull-request")
        waiting = {"status": "awaiting-merge", "pull_request": "https://github.com/acme/web/pull/7"}
        with mock.patch.object(integration, "integrate_member_pull_request", return_value=waiting) as opened:
            result = integration.close_members(self.root)
        opened.assert_called_once_with(self.root.resolve(), "web", ARCHIVE, self.member_tip)
        self.assertEqual((result["status"], result["member"]), ("awaiting-merge", "web"))
        row = json.loads(self.journal.read_text(encoding="utf-8"))["members"][0]
        self.assertEqual((row["status"], row["mode"], row["pull_request"]),
                         ("pending", "pull-request", waiting["pull_request"]))

    def test_default_member_follows_the_coordinator_integration(self) -> None:
        self.set_integration("default")
        state = self.root / ".project/STATE.md"
        state.write_bytes(state.read_text(encoding="utf-8").replace(
            "archive:", "integration_default: direct\nintegration: pull-request\nintegration_source: milestone\narchive:").encode("utf-8"))
        waiting = {"status": "awaiting-merge", "pull_request": "https://github.com/acme/web/pull/7"}
        with mock.patch.object(integration, "integrate_member_pull_request", return_value=waiting):
            self.assertEqual(integration.close_members(self.root)["status"], "awaiting-merge")

    def test_final_review_must_bind_every_locked_member(self) -> None:
        self.final.write_bytes(f"# Final Review\n\nReviewed HEAD: {self.head}\n".encode("utf-8"))
        with self.assertRaisesRegex(ArchiveError, "Member reviewed HEAD"):
            integration.close_members(self.root)
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)

    def test_milestone_without_members_closes_nothing(self) -> None:
        (self.root / ARCHIVE / "build/members.json").unlink()
        self.final.write_bytes(f"# Final Review\n\nReviewed HEAD: {self.head}\n".encode("utf-8"))
        result = integration.close_members(self.root)
        self.assertEqual((result["status"], result["members"]), ("integrated", []))
        self.assertEqual(result["body"], ship_commit_body(ARCHIVE, self.head))
        self.assertFalse(self.journal.exists())


if __name__ == "__main__":
    unittest.main()
