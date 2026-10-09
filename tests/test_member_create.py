import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import members

URL = "https://github.com/acme/web.git"
MEMBERS = Path(__file__).resolve().parents[1] / "scripts" / "members.py"
STATE = (
    "---\npipeline: gsd-path/v2\nproject: acme\nmilestone: null\nphase: define\nstatus: active\n"
    "branch: null\narchive: null\n---\n\n# Project State\n\n## Log\n\n- 2026-09-29 — define — started\n"
)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments], cwd=repo,
                          text=True, capture_output=True, check=True).stdout.strip()


class MemberCreateTests(unittest.TestCase):
    """Greenfield members: create the GitHub repo, clone it, then join, resumably."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.coordinator = self.base / "acme"
        (self.coordinator / ".project").mkdir(parents=True)
        git(self.base, "init", "-q", "-b", "main", str(self.coordinator))
        (self.coordinator / ".project" / "STATE.md").write_text(STATE, encoding="utf-8")
        git(self.coordinator, "add", "-A")
        git(self.coordinator, "commit", "-q", "-m", "init")
        self.remote = self.base / "web.git"
        self.checkout = self.base / "web"
        # Git rewrites the GitHub URL to a local bare remote; the recorded origin stays the GitHub URL.
        config = self.base / "gitconfig"
        config.write_text(f'[url "{self.remote.as_posix()}"]\n\tinsteadOf = {URL}\n', encoding="utf-8")
        environment = mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": str(config)})
        environment.start()
        self.addCleanup(environment.stop)
        self.calls: list = []
        self.common = Path(git(self.coordinator, "rev-parse", "--path-format=absolute", "--git-common-dir"))

    def gh(self, *arguments: str) -> subprocess.CompletedProcess:
        self.calls.append(arguments)
        if arguments[:2] == ("repo", "view"):
            if self.remote.exists():
                return subprocess.CompletedProcess(arguments, 0, '{"visibility":"PRIVATE"}', "")
            return subprocess.CompletedProcess(arguments, 1, "", "Could not resolve to a Repository")
        if arguments[:2] == ("repo", "create"):
            git(self.base, "init", "-q", "--bare", "-b", "main", str(self.remote))
            seed = self.base / "seed"
            git(self.base, "init", "-q", "-b", "main", str(seed))
            (seed / "README.md").write_text("web\n", encoding="utf-8")
            git(seed, "add", "-A")
            git(seed, "commit", "-q", "-m", "Initial commit")
            git(seed, "push", "-q", str(self.remote), "main")
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(f"unexpected gh call: {arguments}")

    def create(self) -> list:
        with mock.patch.object(members, "_gh", side_effect=self.gh):
            return members.create_member(self.coordinator, "web", self.checkout, "default", "acme/web", "private")

    def journal(self) -> Path:
        return self.common / "gsd-path" / "member-create" / "web.json"

    def test_create_makes_the_repo_clones_it_and_joins(self) -> None:
        listed = self.create()
        self.assertEqual([(item["name"], item["remote"]) for item in listed], [("web", URL)])
        self.assertIn(("repo", "create", "acme/web", "--private", "--add-readme"), self.calls)
        self.assertEqual(git(self.checkout, "config", "--get", "remote.origin.url"), URL)
        self.assertEqual(members.member_role(self.checkout)["name"], "web")
        self.assertIn("## web", (self.coordinator / ".project" / "MEMBERS.md").read_text(encoding="utf-8"))
        self.assertFalse(self.journal().exists())

    def test_resume_after_the_repo_exists_does_not_create_it_again(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        self.journal().parent.mkdir(parents=True)
        self.journal().write_text(json.dumps({
            "schema": members.MEMBER_CREATE_SCHEMA, "name": "web", "github": "acme/web", "visibility": "private",
            "checkout": str(self.checkout), "integration": "default", "step": "create"}), encoding="utf-8")
        self.calls.clear()
        self.create()
        self.assertNotIn("create", [call[1] for call in self.calls])
        self.assertFalse(self.journal().exists())

    def test_journal_for_a_different_target_blocks(self) -> None:
        self.journal().parent.mkdir(parents=True)
        self.journal().write_text(json.dumps({
            "schema": members.MEMBER_CREATE_SCHEMA, "name": "web", "github": "acme/other", "visibility": "private",
            "checkout": str(self.checkout), "integration": "default", "step": "create"}), encoding="utf-8")
        with self.assertRaisesRegex(members.MembersError, "approved target"):
            self.create()
        self.assertEqual(self.calls, [])

    def test_occupied_checkout_blocks_before_any_external_action(self) -> None:
        self.checkout.mkdir()
        (self.checkout / "notes.txt").write_text("mine\n", encoding="utf-8")
        with self.assertRaisesRegex(members.MembersError, "checkout"):
            self.create()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal().exists())

    def test_resume_after_join_removes_journal_without_rejoining(self) -> None:
        self.create()
        self.journal().write_text(json.dumps({
            "schema": members.MEMBER_CREATE_SCHEMA, "name": "web", "github": "acme/web", "visibility": "private",
            "checkout": str(self.checkout), "integration": "default", "step": "join"}), encoding="utf-8")
        self.calls.clear()
        self.assertEqual(len(self.create()), 1)
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal().exists())

    def test_lookup_failure_does_not_create_repository(self) -> None:
        with mock.patch.object(members, "_gh", return_value=subprocess.CompletedProcess([], 1, "", "authentication failed")):
            with self.assertRaisesRegex(members.MembersError, "could not inspect"):
                members.create_member(self.coordinator, "web", self.checkout, "default", "acme/web", "private")
        self.assertFalse(self.remote.exists())
        self.assertTrue(self.journal().exists())

    def test_existing_repository_with_other_visibility_blocks_before_clone(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        self.calls.clear()
        with mock.patch.object(members, "_gh", return_value=subprocess.CompletedProcess([], 0, '{"visibility":"PUBLIC"}', "")):
            with self.assertRaisesRegex(members.MembersError, "visibility is public, not private"):
                members.create_member(self.coordinator, "web", self.checkout, "default", "acme/web", "private")
        self.assertFalse(self.checkout.exists())

    def test_resume_occupied_checkout_blocks_before_gh(self) -> None:
        self.journal().parent.mkdir(parents=True)
        self.journal().write_text(json.dumps({
            "schema": members.MEMBER_CREATE_SCHEMA, "name": "web", "github": "acme/web", "visibility": "private",
            "checkout": str(self.checkout), "integration": "default", "step": "create"}), encoding="utf-8")
        self.checkout.mkdir()
        (self.checkout / "notes.txt").write_text("mine\n", encoding="utf-8")
        with self.assertRaisesRegex(members.MembersError, "checkout"):
            self.create()
        self.assertEqual(self.calls, [])

    def test_existing_clone_accepts_equivalent_git_root_path(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        git(self.base, "clone", "-q", URL, str(self.checkout))
        run_git = members._common.run_git

        def git_with_equivalent_root(repo: Path, *arguments: str) -> subprocess.CompletedProcess:
            result = run_git(repo, *arguments)
            if repo == self.checkout and arguments == ("rev-parse", "--show-toplevel"):
                return subprocess.CompletedProcess(result.args, result.returncode,
                                                   f"{self.checkout}/.\n", result.stderr)
            return result

        with mock.patch.object(members._common, "run_git", side_effect=git_with_equivalent_root):
            listed = self.create()
        self.assertEqual(listed[0]["checkout"], str(self.checkout))
        self.assertEqual(members.member_role(self.checkout)["name"], "web")

    def test_visibility_without_create_is_rejected(self) -> None:
        with mock.patch.object(members, "_gh", side_effect=AssertionError("unexpected gh call")):
            with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
                result = members.main(["add", "--repo", str(self.coordinator), "--name", "web",
                                       "--checkout", str(self.checkout), "--visibility", "private"])
        self.assertEqual(result, 1)
        self.assertIn("--visibility requires --create", stderr.getvalue())
        self.assertFalse(self.journal().exists())

    def test_symlinked_checkout_blocks_before_gh(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        target = self.base / "existing-clone"
        git(self.base, "clone", "-q", URL, str(target))
        self.checkout.symlink_to(target, target_is_directory=True)
        self.calls.clear()
        with self.assertRaisesRegex(members.MembersError, "symlink"):
            self.create()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal().exists())

    def test_missing_remote_does_not_reuse_occupied_clone(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        git(self.base, "clone", "-q", URL, str(self.checkout))
        self.remote.rename(self.base / "deleted-web.git")
        self.calls.clear()
        with self.assertRaisesRegex(members.MembersError, "clone of a missing repository"):
            self.create()
        self.assertEqual([call[:2] for call in self.calls], [("repo", "view")])
        self.assertFalse(self.remote.exists())
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def test_missing_remote_after_clone_step_does_not_recreate(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        self.journal().parent.mkdir(parents=True)
        self.journal().write_text(json.dumps({
            "schema": members.MEMBER_CREATE_SCHEMA, "name": "web", "github": "acme/web", "visibility": "private",
            "checkout": str(self.checkout), "integration": "default", "step": "clone"}), encoding="utf-8")
        self.remote.rename(self.base / "deleted-web.git")
        self.calls.clear()
        with self.assertRaisesRegex(members.MembersError, "refusing to create it again"):
            self.create()
        self.assertEqual([call[:2] for call in self.calls], [("repo", "view")])
        self.assertFalse(self.remote.exists())
        self.assertTrue(self.journal().exists())

    def test_nested_checkout_blocks_before_gh(self) -> None:
        self.checkout = self.coordinator / "web"
        with self.assertRaisesRegex(members.MembersError, "nested with the coordinator"):
            self.create()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal().exists())

    def test_partial_clone_without_head_resumes_from_origin_main(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        git(self.base, "init", "-q", "-b", "main", str(self.checkout))
        git(self.checkout, "remote", "add", "origin", URL)
        self.calls.clear()
        listed = self.create()
        self.assertEqual(listed[0]["checkout"], str(self.checkout))
        self.assertEqual(git(self.checkout, "rev-parse", "HEAD"), git(self.remote, "rev-parse", "main"))
        self.assertEqual(members.member_role(self.checkout)["name"], "web")
        self.assertNotIn("create", [call[1] for call in self.calls])

    def test_missing_checkout_parent_blocks_before_gh(self) -> None:
        self.checkout = self.base / "missing" / "web"
        with self.assertRaisesRegex(members.MembersError, "checkout parent does not exist"):
            self.create()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.journal().exists())

    def test_gh_pins_github_com_host(self) -> None:
        def fake_gh(command: list, **kwargs: object) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(command, 0, kwargs["env"]["GH_HOST"], "")

        with mock.patch.dict(os.environ, {"GH_HOST": "enterprise.example"}):
            with mock.patch.object(members.subprocess, "run", side_effect=fake_gh):
                result = members._gh("repo", "view", "acme/web")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "github.com")

    def test_create_refuses_coordinator_whose_default_branch_is_not_main(self) -> None:
        path = self.coordinator / ".project" / "STATE.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("\n---\n", "\ndefault_branch: master\n---\n", 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(members.MembersError, "multi-repo projects support only `main`"):
            self.create()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.checkout.exists())

    def test_deleted_main_is_not_reused_from_stale_tracking_ref(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        git(self.base, "clone", "-q", URL, str(self.checkout))
        git(self.remote, "branch", "next", "main")
        git(self.remote, "symbolic-ref", "HEAD", "refs/heads/next")
        git(self.remote, "branch", "-D", "main")
        self.calls.clear()
        with self.assertRaisesRegex(members.MembersError, "remote default must be main"):
            self.create()
        self.assertEqual([call[:2] for call in self.calls], [("repo", "view")])
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def test_recreated_remote_does_not_adopt_unrelated_clone(self) -> None:
        self.gh("repo", "create", "acme/web", "--private", "--add-readme")
        git(self.base, "clone", "-q", URL, str(self.checkout))
        self.remote.rename(self.base / "deleted-web.git")
        git(self.base, "init", "-q", "--bare", "-b", "main", str(self.remote))
        replacement = self.base / "replacement"
        git(self.base, "init", "-q", "-b", "main", str(replacement))
        (replacement / "README.md").write_text("replacement\n", encoding="utf-8")
        git(replacement, "add", "-A")
        git(replacement, "commit", "-q", "-m", "Replacement")
        git(replacement, "push", "-q", str(self.remote), "main")
        self.calls.clear()
        with self.assertRaisesRegex(members.MembersError, "history unrelated"):
            self.create()
        self.assertEqual([call[:2] for call in self.calls], [("repo", "view")])
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())


class MemberDetectTests(unittest.TestCase):
    """`members.py detect` reports whether a repo is a member, from inside that repo."""

    setUp = MemberCreateTests.setUp
    gh = MemberCreateTests.gh
    create = MemberCreateTests.create

    def detect(self, checkout: Path) -> dict:
        result = subprocess.run([sys.executable, str(MEMBERS), "detect", "--checkout", str(checkout)],
                                text=True, capture_output=True, check=True)
        return json.loads(result.stdout)

    def test_detect_names_the_coordinator_of_a_member(self) -> None:
        self.create()
        self.assertEqual(self.detect(self.checkout), {
            "member": True, "current": True, "checkout": str(self.checkout),
            "coordinator": str(self.coordinator), "project": "acme", "name": "web"})

    def test_detect_reports_a_plain_repo_as_not_a_member(self) -> None:
        self.assertEqual(self.detect(self.coordinator), {"member": False, "checkout": str(self.coordinator)})

    def test_detect_reports_a_stale_marker_with_the_repair_hint(self) -> None:
        self.create()
        (self.coordinator / ".project" / "MEMBERS.md").write_text("# Members\n", encoding="utf-8")
        found = self.detect(self.checkout)
        self.assertEqual((found["member"], found["current"], found["coordinator"]),
                         (True, False, str(self.coordinator)))
        self.assertIn("members.py repair", found["reason"])

    def test_detect_reports_malformed_marker_as_stale_json(self) -> None:
        self.create()
        (Path(git(self.checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"))
         / "gsd-path" / "member.json").write_text("{broken", encoding="utf-8")
        found = self.detect(self.checkout)
        self.assertEqual((found["member"], found["current"]), (True, False))
        self.assertIn("members.py repair", found["reason"])


if __name__ == "__main__":
    unittest.main()
