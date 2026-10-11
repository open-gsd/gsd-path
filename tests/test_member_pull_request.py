import json
import subprocess
import unittest
from unittest import mock

from scripts import integration, members
from scripts.archive_milestone import ArchiveError
import tests.test_member_integration as member_integration

git = member_integration.git
ARCHIVE = member_integration.ARCHIVE
SUBJECT = member_integration.SUBJECT
TAG = member_integration.TAG
URL = "https://github.com/acme/web/pull/7"


class MemberPullRequestTests(unittest.TestCase):
    fixture = member_integration.MemberIntegrationTests.fixture

    def setUp(self) -> None:
        member_integration.MemberIntegrationTests.setUp(self)
        self.pulls, self.posts, self.patches = [], [], []
        self.tags_at_patch = []
        self.merge_queue = False

    remote_ref = member_integration.MemberIntegrationTests.remote_ref

    pulls: list
    posts: list

    def gh(self, *arguments: str) -> subprocess.CompletedProcess:
        def reply(payload) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")
        if arguments[:2] == ("gh", "auth"):
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if "graphql" in arguments:
            merged = [pull["merge_commit_sha"] for pull in self.pulls if pull["merged_at"]]
            nodes = [{"__typename": "MergedEvent", "actor": {"__typename": "User", "login": "owner"},
                      "commit": {"oid": merged[0]}}] if merged else []
            return reply({"data": {"repository": {"pullRequest": {
                "mergeQueue": {"nodes": [{"__typename": "AddedToMergeQueueEvent"}] if self.merge_queue else []},
                "autoMerge": {"nodes": []}, "mergeAction": {"nodes": nodes}}}}})
        if "PATCH" in arguments:
            self.patches.append(arguments)
            self.tags_at_patch.append(self.remote_ref(f"refs/tags/{TAG}"))
            self.pulls[0]["body"] = next(argument.removeprefix("body=") for argument in arguments
                                         if argument.startswith("body="))
            return reply(self.pulls[0])
        base = next((argument.removeprefix("base=") for argument in arguments if argument.startswith("base=")), None)
        if "POST" in arguments:
            self.posts.append(arguments)
            self.pulls.append({"number": 7, "state": "open", "html_url": URL, "merged_at": None,
                               "merge_commit_sha": None, "base": {"ref": base},
                               "body": next(argument.removeprefix("body=") for argument in arguments
                                            if argument.startswith("body=")),
                               "head": {"ref": "gsd-path/demo-M001", "sha": self.member_tip,
                                        "repo": {"full_name": "acme/web"}}})
            return reply(self.pulls[-1])
        # GitHub lists only the pull requests that target the requested base.
        return reply([[pull for pull in self.pulls if pull["base"]["ref"] == base]])

    def integrate(self) -> dict:
        with mock.patch.object(integration, "github_repository", return_value="acme/web"), \
                mock.patch.object(integration, "run_command", side_effect=self.gh):
            return integration.integrate_member_pull_request(self.root, "web", ARCHIVE, self.member_tip)

    def github_merge(self, *extra: str) -> str:
        """Merge the pull request on the remote the way GitHub's merge button does."""
        clone = self.root.parent / "github"
        git(self.root.parent, "clone", "-q", str(self.remote), str(clone))
        git(clone, "config", "user.name", "t")
        git(clone, "config", "user.email", "t@t")
        git(clone, "merge", "-q", *extra, "-m", "Merge pull request #7 from acme/gsd-path/demo-M001",
            "origin/gsd-path/demo-M001")
        if "--squash" in extra:
            git(clone, "commit", "-q", "-m", "Squashed pull request #7")
        git(clone, "push", "-q", "origin", "HEAD:refs/heads/" + getattr(self, "member_default", "main"))
        merge = git(clone, "rev-parse", "HEAD")
        self.pulls[0].update(state="closed", merged_at="2026-09-28T00:00:00Z", merge_commit_sha=merge)
        return merge

    def test_opens_one_pull_request_and_waits(self) -> None:
        result = self.integrate()
        self.assertEqual((result["status"], result["pull_request"]), ("awaiting-merge", URL))
        again = self.integrate()
        self.assertEqual(again["status"], "awaiting-merge")
        self.assertEqual(len(self.posts), 1)
        post = self.posts[0]
        self.assertIn(f"title={SUBJECT}", post)
        self.assertIn("head=gsd-path/demo-M001", post)
        self.assertIn("base=main", post)
        body = next(argument for argument in post if argument.startswith("body="))
        self.assertTrue(body.endswith(f"\n\n---\n{integration.PR_CREDIT_LINE}"))
        self.assertEqual(self.remote_ref("refs/heads/gsd-path/demo-M001"), self.member_tip)
        self.assertEqual(self.remote_ref("refs/heads/main"), self.main)
        self.assertTrue(members.authorized(self.member, "demo", "push", "refs/heads/gsd-path/demo-M001",
                                           self.member_tip))

    def test_merged_pull_request_is_tagged_and_validated(self) -> None:
        self.integrate()
        merge = self.github_merge("--no-ff")
        result = self.integrate()
        self.assertEqual(result["merge"], merge)
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), merge)
        message = git(self.remote, "for-each-ref", "--format=%(contents)", f"refs/tags/{TAG}")
        self.assertIn("Mode: pull-request", message)
        self.assertIn(f"Pull-Request: {URL}", message)
        self.assertIn(f"Reviewed-HEAD: {self.member_tip}", message)
        self.assertTrue(members.authorized(self.member, "demo", "push", f"refs/tags/{TAG}",
                                           self.remote_ref(f"refs/tags/{TAG}")))
        with mock.patch.object(integration, "github_repository", return_value="acme/web"), \
                mock.patch.object(integration, "run_command", side_effect=self.gh):
            self.assertEqual(integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip),
                             result)
            with self.assertRaisesRegex(ArchiveError, "different reviewed HEAD"):
                integration.validate_member_integrated(self.root, "web", ARCHIVE, self.main)

    def test_reused_open_pull_request_repairs_body_without_rewriting_title(self) -> None:
        self.integrate()
        self.pulls[0].update(title="Existing title", body="Missing credit")
        result = self.integrate()
        self.assertEqual(result["status"], "awaiting-merge")
        self.assertEqual(len(self.posts), 1)
        self.assertEqual(len(self.patches), 1)
        self.assertEqual(self.pulls[0]["title"], "Existing title")
        self.assertEqual(self.pulls[0]["body"],
                         f"Archive: {ARCHIVE}\nMember: web\nReviewed-HEAD: {self.member_tip}"
                         f"\n\n---\n{integration.PR_CREDIT_LINE}")

    def test_merged_pull_request_repairs_body_before_tagging(self) -> None:
        self.integrate()
        self.github_merge("--no-ff")
        self.pulls[0]["body"] = "Missing credit"
        result = self.integrate()
        self.assertEqual(result["tag"], TAG)
        self.assertEqual(len(self.patches), 1)
        self.assertEqual(self.tags_at_patch, [""])
        self.assertEqual(self.pulls[0]["body"],
                         f"Archive: {ARCHIVE}\nMember: web\nReviewed-HEAD: {self.member_tip}"
                         f"\n\n---\n{integration.PR_CREDIT_LINE}")

    def test_validation_rejects_unmatched_merge_and_merge_queue(self) -> None:
        self.integrate()
        merge = self.github_merge("--no-ff")
        self.integrate()
        with mock.patch.object(integration, "github_repository", return_value="acme/web"), \
                mock.patch.object(integration, "run_command", side_effect=self.gh):
            self.pulls[0]["merge_commit_sha"] = self.main
            with self.assertRaisesRegex(ArchiveError, "not merged at the tagged landing"):
                integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip)
            self.pulls[0]["merge_commit_sha"] = merge
            self.merge_queue = True
            with self.assertRaisesRegex(ArchiveError, "merge queue"):
                integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip)

    def test_squash_merge_is_refused(self) -> None:
        self.integrate()
        self.github_merge("--squash")
        with self.assertRaisesRegex(ArchiveError, "two-parent"):
            self.integrate()
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")

    def test_closed_pull_request_blocks(self) -> None:
        self.integrate()
        self.pulls[0]["state"] = "closed"
        with self.assertRaisesRegex(ArchiveError, "closed without merging"):
            self.integrate()


class MasterMemberPullRequestTests(unittest.TestCase):
    """Pull-request member close on a member whose recorded default branch is master."""
    member_default = "master"
    fixture = MemberPullRequestTests.fixture
    setUp = MemberPullRequestTests.setUp
    remote_ref = MemberPullRequestTests.remote_ref
    gh = MemberPullRequestTests.gh
    integrate = MemberPullRequestTests.integrate
    github_merge = MemberPullRequestTests.github_merge

    def test_pull_request_targets_the_recorded_default_branch_and_is_validated_there(self) -> None:
        waiting = self.integrate()
        self.assertEqual((waiting["status"], waiting["pull_request"]), ("awaiting-merge", URL))
        self.assertEqual(self.integrate()["status"], "awaiting-merge")
        self.assertEqual(len(self.posts), 1)
        self.assertIn("base=master", self.posts[0])
        self.assertIn("title=integrate: demo M001 — merge gsd-path/demo-M001 into master", self.posts[0])
        self.assertEqual(self.remote_ref("refs/heads/master"), self.main)
        # A body repair checks the pull request against the same base.
        self.pulls[0]["body"] = "Missing credit"
        self.assertEqual(self.integrate()["status"], "awaiting-merge")
        self.assertEqual(len(self.patches), 1)

        merge = self.github_merge("--no-ff")
        self.pulls[0]["body"] = "Missing credit"
        result = self.integrate()
        self.assertEqual(len(self.patches), 2)
        self.assertEqual(result["merge"], merge)
        self.assertEqual(self.remote_ref("refs/heads/master"), merge)
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}^{{commit}}"), merge)
        with mock.patch.object(integration, "github_repository", return_value="acme/web"), \
                mock.patch.object(integration, "run_command", side_effect=self.gh):
            self.assertEqual(integration.validate_member_integrated(self.root, "web", ARCHIVE, self.member_tip),
                             result)

    def test_merge_that_is_not_on_the_recorded_default_branch_is_refused(self) -> None:
        self.integrate()
        # The human merged the bound branch into another branch, then repointed the pull request.
        self.member_default = "release"
        git(self.remote, "branch", "release", "master")
        merge = self.github_merge("--no-ff")
        self.assertEqual(self.remote_ref("refs/heads/master"), self.main)
        with self.assertRaisesRegex(ArchiveError, "pull-request merge is not on origin/master first-parent history"):
            self.integrate()
        self.assertEqual(self.remote_ref(f"refs/tags/{TAG}"), "")
        self.assertNotEqual(merge, self.main)


if __name__ == "__main__":
    unittest.main()
