import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import members

SCRIPT = ROOT / "scripts" / "git_guard.py"
MEMBERS = ROOT / "scripts" / "members.py"
NULL = "0" * 40
BOUND = "refs/heads/gsd-path/acme-M001"
TAG = "refs/tags/milestone/acme-001-demo"
STATE = (
    "---\npipeline: gsd-path/v2\nproject: {project}\nmilestone: demo\nphase: {phase}\n"
    "status: {status}\nbranch: gsd-path/M001\narchive: {archive}\n---\n"
)


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repo, encoding="utf-8", errors="replace", capture_output=True, check=True
    ).stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def write_state(repo: Path, project: str, phase: str, status: str, archive: str = "null") -> None:
    (repo / ".project").mkdir(exist_ok=True)
    (repo / ".project" / "STATE.md").write_bytes(
        STATE.format(project=project, phase=phase, status=status, archive=archive).encode("utf-8"),
    )


class MemberGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name).resolve()
        self.coordinator = root / "acme"
        self.coordinator.mkdir()
        git(self.coordinator, "init", "-q", "-b", "main")
        write_state(self.coordinator, "acme", "plan", "active")
        commit_all(self.coordinator, "init")
        self.member = root / "web"
        self.member.mkdir()
        git(self.member, "init", "-q", "-b", "main")
        (self.member / "app.py").write_bytes("print('v1')\n".encode("utf-8"))
        # The member's own Path history: shipped, but its tag was never fetched,
        # so a single-repo guard treats that milestone as unverified.
        write_state(self.member, "web", "shipped", "done", ".project/archive/001-demo")
        self.base = commit_all(self.member, "init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def join(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
             "--name", "web", "--checkout", str(self.member)],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def guard(self, *arguments: str, stdin: str = ""):
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments], cwd=self.member,
            encoding="utf-8", errors="replace", capture_output=True, input=stdin, check=False,
        )

    def stage_product_commit(self):
        (self.member / "app.py").write_bytes("print('v2')\n".encode("utf-8"))
        git(self.member, "add", "app.py")
        message = self.member / ".git" / "TEST_MSG"
        message.write_bytes("feat: member change\n".encode("utf-8"))
        return self.guard("pre-commit"), self.guard("commit-msg", str(message))

    def push(self, *lines: str):
        return self.guard("pre-push", "origin", "https://github.com/acme/web.git",
                          stdin="".join(line + "\n" for line in lines))

    def member_commit(self, branch: str) -> str:
        git(self.member, "checkout", "-q", "-b", branch)
        (self.member / "app.py").write_bytes(f"print('{branch}')\n".encode("utf-8"))
        sha = commit_all(self.member, f"work on {branch}")
        git(self.member, "checkout", "-q", "-")
        return sha

    def test_pre_push_measures_member_work_from_the_recorded_default_branch(self) -> None:
        # A master member. Its origin/main is an older remote branch, not the default.
        git(self.member, "branch", "-m", "main", "master")
        (self.member / "app.py").write_bytes("print('published')\n".encode("utf-8"))
        published = commit_all(self.member, "published on master")
        git(self.member, "update-ref", "refs/remotes/origin/master", published)
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master")
        self.join()
        work = self.member_commit("gsd-path/acme-M001")
        feature = self.member_commit("feature/x")
        feature_line = f"refs/heads/feature/x {feature} refs/heads/feature/x {NULL}"

        allowed = self.push(feature_line)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        refused = self.push(f"refs/heads/master {work} refs/heads/master {published}")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("carries unpublished acme member work", refused.stderr)

        git(self.member, "update-ref", "-d", "refs/remotes/origin/master")
        missing = self.push(feature_line)
        self.assertNotEqual(missing.returncode, 0)
        self.assertIn("member requires refs/remotes/origin/master; run git fetch origin", missing.stderr)

    def test_member_commit_ignores_the_member_own_state(self) -> None:
        pre_commit, commit_msg = self.stage_product_commit()
        self.assertNotEqual(commit_msg.returncode, 0, "single-repo guard should hold this commit")
        git(self.member, "reset", "-q", "--hard")
        self.join()
        pre_commit, commit_msg = self.stage_product_commit()
        self.assertEqual(pre_commit.returncode, 0, pre_commit.stderr)
        self.assertEqual(commit_msg.returncode, 0, commit_msg.stderr)

    def test_stale_marker_blocks_commit_and_push(self) -> None:
        self.join()
        (self.coordinator / ".project" / "MEMBERS.md").unlink()
        _, commit_msg = self.stage_product_commit()
        self.assertNotEqual(commit_msg.returncode, 0)
        self.assertIn("members.py repair", commit_msg.stderr)
        pushed = self.push(f"refs/heads/main {self.base} refs/heads/main {NULL}")
        self.assertNotEqual(pushed.returncode, 0)
        self.assertIn("members.py repair", pushed.stderr)

    def test_join_requires_origin_main_baseline(self) -> None:
        git(self.member, "update-ref", "-d", "refs/remotes/origin/main")
        result = subprocess.run(
            [sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
             "--name", "web", "--checkout", str(self.member)],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refs/remotes/origin/main", result.stderr)
        self.assertIn("git fetch origin", result.stderr)
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def test_pre_push_blocks_when_origin_main_baseline_disappears(self) -> None:
        self.join()
        self.member_commit("gsd-path/acme-M001")
        git(self.member, "update-ref", "-d", "refs/remotes/origin/main")
        result = self.push(f"refs/heads/main {self.base} refs/heads/main {NULL}")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("refs/remotes/origin/main", result.stderr)
        self.assertIn("git fetch origin", result.stderr)

    def test_member_path_refs_publish_only_when_authorized(self) -> None:
        self.join()
        work = self.member_commit("gsd-path/acme-M001")
        line = f"{BOUND} {work} {BOUND} {NULL}"
        refused = self.push(line)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not authorized", refused.stderr)
        members.authorize_push(self.member, "acme", BOUND, self.base)
        self.assertNotEqual(self.push(line).returncode, 0, "authorization is per object")
        members.authorize_push(self.member, "acme", BOUND, work)
        allowed = self.push(line)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_member_tag_publishes_only_its_authorized_tag_object(self) -> None:
        self.join()
        git(self.member, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a",
            "milestone/acme-001-demo", "-m", "close")
        tag_object = git(self.member, "rev-parse", TAG)
        line = f"{TAG} {tag_object} {TAG} {NULL}"
        self.assertNotEqual(self.push(line).returncode, 0)
        members.authorize_push(self.member, "acme", TAG, tag_object)
        allowed = self.push(line)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_other_refs_publish_unless_they_carry_member_work(self) -> None:
        self.join()
        work = self.member_commit("gsd-path/acme-M001")
        feature = self.member_commit("feature/x")
        cases = {
            f"refs/heads/main {self.base} refs/heads/main {NULL}": True,
            f"refs/heads/feature/x {feature} refs/heads/feature/x {NULL}": True,
            f"refs/heads/gsd-path/other-M001 {feature} refs/heads/gsd-path/other-M001 {NULL}": True,
            f"refs/heads/main {work} refs/heads/main {self.base}": False,
            f"HEAD {work} refs/heads/hotfix {NULL}": False,
        }
        for line, allowed in cases.items():
            with self.subTest(line=line):
                result = self.push(line)
                self.assertEqual(result.returncode == 0, allowed, result.stderr)
                if not allowed:
                    self.assertIn("carries unpublished acme member work", result.stderr)
        members.authorize_push(self.member, "acme", "refs/heads/main", work)
        authorized = self.push(f"refs/heads/main {work} refs/heads/main {self.base}")
        self.assertEqual(authorized.returncode, 0, authorized.stderr)

    def test_member_path_ref_deletion_needs_its_expected_remote_sha(self) -> None:
        self.join()
        work = self.member_commit("gsd-path/acme-M001")
        line = f"(delete) {NULL} {BOUND} {work}"
        refused = self.push(line)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("deletion is not authorized", refused.stderr)
        members.authorize_delete(self.member, "acme", BOUND, self.base)
        self.assertNotEqual(self.push(line).returncode, 0, "delete authorization pins the remote SHA")
        members.authorize_delete(self.member, "acme", BOUND, work)
        allowed = self.push(line)
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        other = self.push(f"(delete) {NULL} refs/heads/feature/x {work}")
        self.assertEqual(other.returncode, 0, other.stderr)

    def test_authorization_refuses_other_refs_and_missing_objects(self) -> None:
        self.join()
        with self.assertRaises(members.MembersError):
            members.authorize_push(self.member, "acme", "refs/remotes/origin/main", self.base)
        with self.assertRaises(members.MembersError):
            members.authorize_push(self.member, "acme", BOUND, "f" * 40)


if __name__ == "__main__":
    unittest.main()
