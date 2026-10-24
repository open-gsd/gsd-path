import json
import shutil
import unittest
from pathlib import Path

from scripts import archive_milestone, discussion_validate, lean_verification
from scripts import check_handoffs as contracts
import tests.test_handoffs as test_handoffs
import tests.test_member_project_verify as member_verify

git = member_verify.git


class MemberFinalReviewTests(unittest.TestCase):
    setUp = member_verify.MemberProjectVerifyTests.setUp
    fixture = member_verify.MemberProjectVerifyTests.fixture
    use_member_verify_command = member_verify.MemberProjectVerifyTests.use_member_verify_command

    def write_final(self, *member_lines: str, keep_gap: bool = False) -> Path:
        review = self.root / ".project/review"
        kept = (review / "final-gap-1.md").read_text(encoding="utf-8") if keep_gap else None
        test_handoffs.HandoffValidationTests().write_final_review(self.root)
        # The helper writes FINAL.md and a matching gap; both carry the member lines.
        for path in (review / "FINAL.md", review / "final-gap-1.md"):
            text = path.read_text(encoding="utf-8")
            end = text.index("\n", text.index("Reviewed HEAD:"))
            path.write_bytes((text[:end] + "".join(f"\n{line}" for line in member_lines) + text[end:]).encode("utf-8"))
        if kept is not None:
            (review / "final-gap-1.md").write_bytes(kept.encode("utf-8"))
        return review / "FINAL.md"

    def test_final_review_must_name_each_locked_member_head(self) -> None:
        self.write_final()
        with self.assertRaisesRegex(contracts.HandoffError, "Member reviewed HEAD"):
            contracts.validate_final(self.root)
        self.write_final(f"Member reviewed HEAD: web {self.member_tip}")
        self.assertEqual(contracts.validate_final(self.root)["verdict"], "pass")

    def test_final_validation_in_a_review_sidecar_resolves_members_through_the_primary(self) -> None:
        # Issue #467: the final reviewer runs in an isolate-verify sidecar of
        # the coordinator; member markers name the primary, so validation must
        # resolve members through the sidecar's owning primary.
        from scripts import isolation
        self.write_final(f"Member reviewed HEAD: web {self.member_tip}")
        head = git(self.root, "rev-parse", "HEAD")
        created = isolation.isolate_verify(self.root, head, "review-final")
        sidecar = Path(created["worktree"])
        # The reviewer writes its artifact inside the sidecar.
        (sidecar / ".project/review").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.root / ".project/review/FINAL.md",
            sidecar / ".project/review/FINAL.md",
        )
        shutil.copyfile(
            self.root / ".project/review/final-gap-1.md",
            sidecar / ".project/review/final-gap-1.md",
        )

        self.assertEqual(contracts.validate_final(sidecar)["verdict"], "pass")

    def test_review_sidecar_still_refuses_a_stale_member_head(self) -> None:
        from scripts import isolation
        self.write_final(f"Member reviewed HEAD: web {git(self.member, 'rev-parse', 'main')}")
        head = git(self.root, "rev-parse", "HEAD")
        created = isolation.isolate_verify(self.root, head, "review-final")
        sidecar = Path(created["worktree"])
        (sidecar / ".project/review").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(
            self.root / ".project/review/FINAL.md",
            sidecar / ".project/review/FINAL.md",
        )
        shutil.copyfile(
            self.root / ".project/review/final-gap-1.md",
            sidecar / ".project/review/final-gap-1.md",
        )

        with self.assertRaisesRegex(contracts.HandoffError, "Member reviewed HEAD"):
            contracts.validate_final(sidecar)

    def test_stale_member_head_is_refused(self) -> None:
        self.write_final(f"Member reviewed HEAD: web {git(self.member, 'rev-parse', 'main')}")
        with self.assertRaisesRegex(contracts.HandoffError, "Member reviewed HEAD"):
            contracts.validate_final(self.root)

    def test_member_head_without_a_lock_is_refused(self) -> None:
        (self.root / ".project/build/members.json").unlink()
        self.write_final(f"Member reviewed HEAD: web {self.member_tip}")
        with self.assertRaisesRegex(contracts.HandoffError, "Member reviewed HEAD"):
            contracts.validate_final(self.root)

    def test_project_verify_gap_carries_member_heads_and_must_match_final(self) -> None:
        self.use_member_verify_command()
        self.assertTrue(lean_verification.verify_project(self.root, self.head)["passed"])
        self.write_final(f"Member reviewed HEAD: web {self.member_tip}", keep_gap=True)
        self.assertEqual(contracts.validate_final(self.root)["verdict"], "pass")
        gap = self.root / ".project/review/final-gap-1.md"
        gap.write_bytes(gap.read_text(encoding="utf-8").replace(
            f"Member reviewed HEAD: web {self.member_tip}\n", "").encode("utf-8"))
        with self.assertRaisesRegex(contracts.HandoffError, "final-gap-1.md Member reviewed HEAD"):
            contracts.validate_final(self.root)

    def test_member_head_in_quoted_output_does_not_bind(self) -> None:
        final = self.write_final(f"Member reviewed HEAD: web {self.member_tip}")
        final.write_bytes((final.read_text(encoding="utf-8") + "\n## Output\n\nMember reviewed HEAD: api " + "0" * 40 + "\n").encode("utf-8"))
        self.assertEqual(contracts.validate_final(self.root)["verdict"], "pass")

    def test_member_head_in_header_comment_does_not_bind(self) -> None:
        self.write_final(f"<!--\nMember reviewed HEAD: web {self.member_tip}\n-->")
        with self.assertRaisesRegex(contracts.HandoffError, "Member reviewed HEAD"):
            contracts.validate_final(self.root)

    def test_commented_heading_does_not_end_visible_header(self) -> None:
        self.write_final("<!--\n## Hidden heading\n-->",
                         f"Member reviewed HEAD: web {self.member_tip}")
        self.assertEqual(contracts.validate_final(self.root)["verdict"], "pass")

    def archive(self) -> Path:
        self.use_member_verify_command()
        self.assertTrue(lean_verification.verify_project(self.root, self.head)["passed"])
        archive = self.root / "archived"
        (archive / "build").mkdir(parents=True)
        shutil.copytree(self.root / ".project/review", archive / "review")
        shutil.copy(self.root / ".project/build/members.json", archive / "build/members.json")
        (archive / "review/FINAL.md").write_bytes("# Final Review\n".encode("utf-8"))
        return archive

    def test_archived_final_review_names_each_locked_member(self) -> None:
        archive = self.archive()
        with self.assertRaisesRegex(archive_milestone.ArchiveError, "Member reviewed HEAD"):
            discussion_validate.validate_gap_reviews(archive, self.head)
        final = archive / "review/FINAL.md"
        final.write_bytes(f"Member reviewed HEAD: web {self.member_tip}\n".encode("utf-8"))
        discussion_validate.validate_gap_reviews(archive, self.head)
        lock = archive / "build/members.json"
        lock.write_bytes(json.dumps({"schema": "gsd-path/member-lock/v1", "members": []}).encode("utf-8"))
        with self.assertRaisesRegex(archive_milestone.ArchiveError, "Member reviewed HEAD"):
            discussion_validate.validate_gap_reviews(archive, self.head)

    def test_archived_gap_must_repeat_final_member_heads(self) -> None:
        archive = self.archive()
        (archive / "review/FINAL.md").write_bytes(
            f"Member reviewed HEAD: web {self.member_tip}\n".encode("utf-8"))
        gap = archive / "review/final-gap-1.md"
        gap.write_bytes(gap.read_text(encoding="utf-8").replace(self.member_tip, "0" * 40).encode("utf-8"))
        with self.assertRaisesRegex(archive_milestone.ArchiveError, "final-gap-1.md Member reviewed HEAD"):
            discussion_validate.validate_gap_reviews(archive, self.head)


if __name__ == "__main__":
    unittest.main()
