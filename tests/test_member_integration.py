import unittest
from pathlib import Path
from subprocess import CompletedProcess
from unittest import mock

from scripts import integration, members
from scripts.archive_milestone import ArchiveError
import tests.test_member_project_verify as member_verify

git = member_verify.git
ARCHIVE = ".project/archive/001-demo"
SUBJECT = "integrate: demo M001 — merge gsd-path/demo-M001 into main"
TAG = "milestone/demo-001-demo"


class MemberIntegrationTests(unittest.TestCase):
    fixture = member_verify.MemberProjectVerifyTests.fixture

    def setUp(self) -> None:
        member_verify.MemberProjectVerifyTests.setUp(self)
        git(self.member, "config", "user.name", "t")
        git(self.member, "config", "user.email", "t@t")
        # The member keeps its GitHub origin URL; Git rewrites it to a local bare remote.
        self.remote = self.root.parent / "web-remote.git"
        git(self.root.parent, "init", "-q", "--bare", str(self.remote))
        default = getattr(self, "member_default", "main")
        git(self.remote, "symbolic-ref", "HEAD", f"refs/heads/{default}")
        git(self.member, "config", "url." + str(self.remote) + ".insteadOf", "https://github.com/acme/web.git")
        git(self.member, "push", "-q", "origin", default)
        git(self.member, "fetch", "-q", "origin")
        self.main = git(self.member, "rev-parse", default)

    def remote_ref(self, ref: str) -> str:
        return git(self.remote, "rev-parse", "--verify", "--quiet", ref, check=False)

    def test_github_repository_uses_configured_origin_with_rewrite(self) -> None:
        self.assertEqual(git(self.member, "remote", "get-url", "origin"), str(self.remote))
        self.assertEqual(integration.github_repository(self.member), "acme/web")

    def integrate(self) -> dict:
        return integration.integrate_member(self.root, "web", ARCHIVE, self.member_tip)

    def test_direct_member_integration_publishes_bound_branch_merge_and_tag(self) -> None:
        result = self.integrate()
        merge = self.remote_ref("refs/heads/main")
        self.assertEqual(result["merge"], merge)
        self.assertEqual(git(self.remote, "rev-list", "--parents", "-n", "1", merge).split()[1:],
                         [self.main, self.member_tip])
        self.assertEqual(git(self.remote, "show", "-s", "--format=%s", merge), SUBJECT)
        self.assertEqual(git(self.remote, "show", "-s", "--format=%b", merge).strip(),
                         f"Archive: {ARCHIVE}\nMember: web\nReviewed-HEAD: {self.member_tip}")
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), self.member_tip)
        self.assertEqual(git(self.remote, "cat-file", "-t", f"refs/tags/{TAG}"), "tag")
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), merge)
        self.assertEqual(result["tag"], TAG)
        tag_object = self.remote_ref(f"refs/tags/{TAG}")
        for ref, sha in (("refs/heads/gsd-path/demo-M001", self.member_tip),
                         ("refs/heads/main", merge), (f"refs/tags/{TAG}", tag_object)):
            self.assertTrue(members.authorized(self.member, "demo", "push", ref, sha), ref)
        self.assertEqual(git(self.member, "branch", "--list", "gsd-path-integrate/*"), "")
        self.assertEqual(git(self.member, "worktree", "list", "--porcelain").count("worktree "), 1)

    def test_rerun_never_integrates_a_member_twice(self) -> None:
        first = self.integrate()
        second = self.integrate()
        self.assertEqual(second["merge"], first["merge"])
        self.assertEqual(self.remote_ref("refs/heads/main"), first["merge"])

    def test_resume_publishes_only_the_missing_tag(self) -> None:
        first = self.integrate()
        git(self.remote, "tag", "-d", TAG)
        git(self.member, "tag", "-d", TAG)
        result = self.integrate()
        self.assertEqual(result["merge"], first["merge"])
        self.assertEqual(self.remote_ref("refs/heads/main"), first["merge"])
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), first["merge"])

    def test_moved_bound_branch_is_refused_before_publishing(self) -> None:
        with self.assertRaisesRegex(ArchiveError, "gsd-path/demo-M001"):
            integration.integrate_member(self.root, "web", ARCHIVE, self.main)
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")

    def test_moved_remote_bound_branch_blocks(self) -> None:
        git(self.member, "push", "-q", "origin", "main:refs/heads/gsd-path/demo-M001")
        with self.assertRaisesRegex(ArchiveError, "moved"):
            self.integrate()
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)

    def test_stale_unpublished_merge_is_rebuilt_on_the_advanced_main(self) -> None:
        stale = self.root.parent / "stale"
        git(self.member, "worktree", "add", "-q", "-b", "gsd-path-integrate/demo-M001", str(stale), self.main)
        git(stale, "merge", "-q", "--no-ff", "-m", SUBJECT, "-m",
            f"Archive: {ARCHIVE}\nMember: web\nReviewed-HEAD: {self.member_tip}", self.member_tip)
        stale_merge = git(stale, "rev-parse", "HEAD")
        git(self.member, "worktree", "remove", str(stale))
        other = self.root.parent / "other"
        git(self.root.parent, "clone", "-q", str(self.remote), str(other))
        (other / "team.txt").write_text("team work\n", encoding="utf-8")
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "team work")
        git(other, "push", "-q", "origin", "main")
        advanced = git(other, "rev-parse", "HEAD")
        result = self.integrate()
        self.assertNotEqual(result["merge"], stale_merge)
        self.assertEqual(git(self.remote, "rev-list", "--parents", "-n", "1", result["merge"]).split()[1:],
                         [advanced, self.member_tip])

    def test_reviewed_head_on_main_requires_recovery_before_publishing(self) -> None:
        git(self.remote, "fetch", "-q", str(self.member), self.member_tip)
        git(self.remote, "update-ref", "refs/heads/main", self.member_tip)
        with self.assertRaisesRegex(ArchiveError, "outside Path; user-approved recovery required"):
            self.integrate()
        self.assertEqual(self.remote_ref("refs/heads/main"), self.member_tip)
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_merge_success_without_two_parents_cannot_publish(self) -> None:
        run_git = integration.run_git

        def no_op_merge(repo, *arguments):
            if arguments[:2] == ("merge", "--no-ff"):
                return CompletedProcess(arguments, 0, "", "")
            return run_git(repo, *arguments)

        with mock.patch.object(integration, "run_git", side_effect=no_op_merge):
            with self.assertRaises(ArchiveError):
                self.integrate()
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_interrupted_branch_at_creation_base_recreates_merge(self) -> None:
        interrupted = self.root.parent / "interrupted"
        branch = "gsd-path-integrate/demo-M001"
        git(self.member, "worktree", "add", "-q", "-b", branch, str(interrupted), self.main)
        git(self.member, "worktree", "remove", str(interrupted))
        result = self.integrate()
        self.assertEqual(git(self.remote, "rev-list", "--parents", "-n", "1", result["merge"]).split()[1:],
                         [self.main, self.member_tip])
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), result["merge"])
        self.assertEqual(git(self.member, "branch", "--list", branch), "")

    def test_integrate_refreshes_main_before_returning_validation(self) -> None:
        publish = integration._push_member_ref

        def publish_then_move(checkout, project, source, ref, sha, lease):
            publish(checkout, project, source, ref, sha, lease)
            if ref == f"refs/tags/{TAG}":
                git(self.remote, "update-ref", "refs/heads/main", self.main)

        with mock.patch.object(integration, "_push_member_ref", side_effect=publish_then_move):
            with self.assertRaisesRegex(ArchiveError, "has no .* merge on origin/main"):
                self.integrate()
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)

    def test_validate_requires_the_published_merge_and_tag(self) -> None:
        with self.assertRaisesRegex(ArchiveError, "integrate: demo M001"):
            integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip)
        result = self.integrate()
        self.assertEqual(integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip),
                         result)
        git(self.remote, "tag", "-f", "-a", "-m", "wrong", TAG, self.main)
        with self.assertRaisesRegex(ArchiveError, "integration merge"):
            integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip)
        git(self.remote, "tag", "-d", TAG)
        with self.assertRaisesRegex(ArchiveError, TAG):
            integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip)

    def test_read_only_validation_keeps_member_refs_unchanged(self) -> None:
        result = self.integrate()
        refs = ("refs/remotes/origin/main", f"refs/remotes/origin/tags/{TAG}")
        before = [git(self.member, "rev-parse", "--verify", ref) for ref in refs]
        git(self.remote, "update-ref", "refs/heads/main", self.main)
        git(self.remote, "tag", "-d", TAG)

        self.assertEqual(
            integration.validate_member_integrated(
                self.root, "web", ARCHIVE, self.member_tip, refresh=False), result)
        self.assertEqual([git(self.member, "rev-parse", "--verify", ref) for ref in refs], before)


class MasterMemberIntegrationTests(unittest.TestCase):
    """Direct member close on a member whose recorded default branch is master."""
    member_default = "master"
    fixture = MemberIntegrationTests.fixture
    setUp = MemberIntegrationTests.setUp
    remote_ref = MemberIntegrationTests.remote_ref
    integrate = MemberIntegrationTests.integrate

    def test_direct_member_integration_lands_on_the_recorded_default_branch(self) -> None:
        self.assertIn("Default branch: master\n", (self.root / ".project/MEMBERS.md").read_text(encoding="utf-8"))
        validate = integration.validate_member_integrated
        tracking = []

        def record_tracking_refs(*arguments, **options):
            tracking.append(git(self.member, "for-each-ref", "--format=%(refname) %(objectname)",
                                "refs/remotes/origin/main", "refs/remotes/origin/master"))
            return validate(*arguments, **options)

        with mock.patch.object(integration, "validate_member_integrated", side_effect=record_tracking_refs):
            result = self.integrate()
        merge = self.remote_ref("refs/heads/master")
        self.assertEqual(tracking, [f"refs/remotes/origin/master {merge}"])
        self.assertEqual(result["merge"], merge)
        self.assertEqual(git(self.remote, "rev-list", "--parents", "-n", "1", merge).split()[1:],
                         [self.main, self.member_tip])
        self.assertEqual(git(self.remote, "show", "-s", "--format=%s", merge),
                         "integrate: demo M001 — merge gsd-path/demo-M001 into master")
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), merge)
        self.assertEqual(self.remote_ref("refs/heads/main"), "")
        self.assertTrue(members.authorized(self.member, "demo", "push", "refs/heads/master", merge))
        self.assertEqual(git(self.member, "rev-parse", "refs/remotes/origin/master"), merge)

        # A rerun and a read-only validation find the merge on origin/master.
        self.assertEqual(self.integrate(), result)
        self.assertEqual(integration.validate_member_integrated(
            self.root, "web", ARCHIVE, self.member_tip, refresh=False), result)
        self.assertEqual(git(self.remote, "rev-list", "--count", "--first-parent", f"{self.main}..master"), "1")

    def test_reviewed_head_on_the_recorded_default_branch_requires_recovery(self) -> None:
        git(self.remote, "fetch", "-q", str(self.member), self.member_tip)
        git(self.remote, "update-ref", "refs/heads/master", self.member_tip)
        with self.assertRaisesRegex(ArchiveError, "reached origin/master outside Path"):
            self.integrate()
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_forge_default_that_differs_from_the_record_blocks_before_publishing(self) -> None:
        git(self.remote, "branch", "main", "master")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/main")
        with self.assertRaisesRegex(ArchiveError, "member web remote default must be master, got 'main'"):
            self.integrate()
        self.assertEqual(self.remote_ref("refs/heads/master"), self.main)
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")

    def test_retirement_clears_the_default_branch_push_authorization(self) -> None:
        merge = self.integrate()["merge"]
        integration.retire_member(self.root, "web", ARCHIVE, self.member_tip, merge, TAG)
        self.assertEqual(git(self.member, "for-each-ref", "refs/gsd-path/authorizations/demo/"), "")
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), "")
        self.assertEqual(self.remote_ref("refs/heads/master"), merge)


if __name__ == "__main__":
    unittest.main()
