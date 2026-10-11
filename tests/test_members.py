import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import archive_milestone
import check_handoffs
import lean_verification
import members
from tests._platform import posix_permissions_only
from tests._platform import requires_symlink

SCRIPT = ROOT / "scripts" / "members.py"

STATE = """---
pipeline: gsd-path/v2
project: {project}
milestone: {milestone}
phase: {phase}
status: {status}
branch: {branch}
archive: {archive}
---
"""


def git(repo: Path, *arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=repo, encoding="utf-8", errors="replace", capture_output=True, check=True
    ).stdout.strip()


def write_state(root: Path, project: str, phase: str, status: str = "active",
                milestone: str = "demo", branch: str = "gsd-path/M001",
                archive: str = "null") -> None:
    (root / ".project").mkdir(exist_ok=True)
    (root / ".project" / "STATE.md").write_bytes(
        STATE.format(project=project, milestone=milestone, phase=phase,
                     status=status, branch=branch, archive=archive).encode("utf-8"),
    )


def commit_all(repo: Path, message: str = "init") -> None:
    git(repo, "add", "-A")
    git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", message)


class MemberTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.coordinator = self.root / "acme"
        self.coordinator.mkdir()
        git(self.coordinator, "init", "-q", "-b", "main")
        write_state(self.coordinator, "acme", "plan")
        (self.coordinator / ".project" / "REPOSITORY.md").write_bytes(
            "# Repository Binding\n\nKind: new-github\n".encode("utf-8")
        )
        commit_all(self.coordinator)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_member(self, name: str, parent: Optional[Path] = None,
                    remote: Optional[str] = None, default: str = "main") -> Path:
        member = (parent or self.root) / name
        member.mkdir()
        git(member, "init", "-q", "-b", "main")
        (member / "README.md").write_bytes(name.encode("utf-8"))
        commit_all(member)
        git(member, "remote", "add", "origin", remote or f"https://github.com/acme/{name}.git")
        git(member, "update-ref", f"refs/remotes/origin/{default}", "HEAD")
        git(member, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default}")
        return member

    def run_members(self, *arguments: str):
        return subprocess.run(
            [sys.executable, str(SCRIPT), arguments[0], "--repo", str(self.coordinator),
             *arguments[1:]],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )

    def add(self, name: str, checkout: Path, *extra: str):
        return self.run_members("add", "--name", name, "--checkout", str(checkout), *extra)

    def assert_refused(self, result, reason: str) -> None:
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn(reason, result.stderr)
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def test_add_records_members_in_order_without_touching_repository_binding(self) -> None:
        binding = (self.coordinator / ".project" / "REPOSITORY.md").read_bytes()
        web = self.make_member("web")
        sdk = self.make_member("sdk")
        self.assertEqual(self.add("web", web).returncode, 0)
        added = self.add("sdk", sdk, "--integration", "pull-request")
        self.assertEqual(added.returncode, 0, added.stderr)

        validated = self.run_members("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        members = json.loads(validated.stdout)["members"]
        self.assertEqual(
            members,
            [
                {"name": "web", "checkout": str(web), "remote": "https://github.com/acme/web.git",
                 "integration": "default", "default_branch": "main"},
                {"name": "sdk", "checkout": str(sdk), "remote": "https://github.com/acme/sdk.git",
                 "integration": "pull-request", "default_branch": "main"},
            ],
        )
        self.assertEqual((self.coordinator / ".project" / "REPOSITORY.md").read_bytes(), binding)

    def test_validate_without_members_file_reports_no_members(self) -> None:
        result = self.run_members("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"members": []})
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def members_text(self) -> str:
        return (self.coordinator / ".project" / "MEMBERS.md").read_text(encoding="utf-8")

    def set_origin_head(self, member: Path, default: str) -> None:
        git(member, "update-ref", f"refs/remotes/origin/{default}", "HEAD")
        git(member, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{default}")

    def test_add_records_the_member_default_branch_and_validate_follows_the_record(self) -> None:
        web = self.make_member("web", default="master")
        added = self.add("web", web)
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertIn("\nDefault branch: master\n", self.members_text())

        validated = self.run_members("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual(json.loads(validated.stdout)["members"][0]["default_branch"], "master")
        self.assertEqual(members.member_default_branch(self.coordinator, "web"), "master")

        # The record is the source of truth; a later origin/HEAD does not replace it.
        recorded = self.members_text()
        self.set_origin_head(web, "main")
        moved = self.run_members("validate")
        self.assertNotEqual(moved.returncode, 0, moved.stdout)
        self.assertIn("member remote default must be master, got main", moved.stderr)
        self.assertEqual(self.members_text(), recorded)

    def test_add_records_main_when_origin_head_is_unset(self) -> None:
        web = self.make_member("web")
        git(web, "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
        added = self.add("web", web)
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertIn("\nDefault branch: main\n", self.members_text())
        self.assertEqual(self.run_members("validate").returncode, 0)

    def test_add_refuses_a_member_default_branch_that_path_reserves(self) -> None:
        self.assert_refused(self.add("web", self.make_member("web", default="gsd-path/M001")),
                            "member default branch 'gsd-path/M001' cannot be recorded")

    def test_add_refuses_a_default_branch_that_was_not_fetched(self) -> None:
        web = self.make_member("web", default="master")
        git(web, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
        self.assert_refused(self.add("web", web), "member requires refs/remotes/origin/trunk")

    def test_row_without_default_branch_means_main_and_is_not_rewritten(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        path = self.coordinator / ".project" / "MEMBERS.md"
        legacy = self.members_text().replace("Default branch: main\n", "")
        self.assertNotIn("Default branch", legacy)
        path.write_bytes(legacy.encode("utf-8"))

        validated = self.run_members("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertNotIn("default_branch", json.loads(validated.stdout)["members"][0])
        self.assertEqual(members.member_default_branch(self.coordinator, "web"), "main")
        self.set_origin_head(web, "master")
        self.assertIn("member remote default must be main, got master", self.run_members("validate").stderr)
        self.set_origin_head(web, "main")

        # Members of one project can have different default branches.
        added = self.add("sdk", self.make_member("sdk", default="master"))
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertEqual(self.members_text(), legacy + "\n## sdk\n"
                         f"Checkout: {self.root / 'sdk'}\nRemote: https://github.com/acme/sdk.git\n"
                         "Integration: default\nDefault branch: master\n")
        self.assertEqual(self.run_members("validate").returncode, 0)

    def record_coordinator_default(self, name: str) -> None:
        path = self.coordinator / ".project" / "STATE.md"
        text = path.read_text(encoding="utf-8")
        path.write_bytes(text.replace("\n---\n", f"\ndefault_branch: {name}\n---\n", 1).encode("utf-8"))
        commit_all(self.coordinator, "record default branch")

    def test_coordinator_default_branch_can_differ_from_member_default_branches(self) -> None:
        self.record_coordinator_default("trunk")
        for name, default in (("web", "main"), ("sdk", "master")):
            added = self.add(name, self.make_member(name, default=default))
            self.assertEqual(added.returncode, 0, added.stderr)

        validated = self.run_members("validate")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertEqual([member["default_branch"] for member in json.loads(validated.stdout)["members"]],
                         ["main", "master"])

    def test_add_refuses_origin_outside_github(self) -> None:
        member = self.make_member("web", remote="https://gitlab.com/acme/web.git")
        self.assert_refused(self.add("web", member), "GitHub.com origin")

    def test_add_refuses_dirty_member_worktree(self) -> None:
        member = self.make_member("web")
        (member / "README.md").write_bytes("changed".encode("utf-8"))
        self.assert_refused(self.add("web", member), "uncommitted changes")

    def test_add_refuses_untracked_files_hidden_by_git_config(self) -> None:
        member = self.make_member("web")
        git(member, "config", "status.showUntrackedFiles", "no")
        (member / "untracked.txt").write_bytes("hidden".encode("utf-8"))
        self.assert_refused(self.add("web", member), "uncommitted changes")

    def test_add_refuses_member_nested_in_coordinator(self) -> None:
        member = self.make_member("web", parent=self.coordinator)
        self.assert_refused(self.add("web", member), "nested")

    def test_add_refuses_submodule_checkout(self) -> None:
        source = self.make_member("web-source")
        parent = self.make_member("host")
        git(parent, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "web")
        commit_all(parent, "add submodule")
        submodule = parent / "web"
        git(submodule, "remote", "set-url", "origin", "https://github.com/acme/web.git")
        git(submodule, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(submodule, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.assert_refused(self.add("web", submodule), "submodule")

    def test_add_refuses_member_with_active_milestone(self) -> None:
        member = self.make_member("web")
        write_state(member, "web", "build")
        commit_all(member, "path state")
        self.assert_refused(self.add("web", member), "active milestone")

    @requires_symlink
    def test_add_and_validate_refuse_unreadable_member_state(self) -> None:
        for kind in ("broken symlink", "live symlink", "directory"):
            with self.subTest(kind):
                member = self.make_member(kind.replace(" ", "-"))
                state = member / ".project" / "STATE.md"
                state.parent.mkdir()
                if kind == "directory":
                    state.mkdir()
                else:
                    if kind == "live symlink":
                        write_state(member, "web", "shipped", status="done")
                        state.rename(member / ".project" / "saved-state.md")
                        state.symlink_to("saved-state.md")
                    else:
                        state.symlink_to("missing-state.md")
                    commit_all(member, "state link")
                self.assert_refused(self.add("web", member), "member STATE.md is unreadable")

        member = self.make_member("valid")
        self.assertEqual(self.add("valid", member).returncode, 0)
        state = member / ".project" / "STATE.md"
        state.parent.mkdir()
        state.symlink_to("missing-state.md")
        commit_all(member, "state link")
        result = self.run_members("validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("member STATE.md is unreadable", result.stderr)

    def test_add_accepts_member_whose_own_milestone_shipped(self) -> None:
        member = self.make_member("web")
        write_state(member, "web", "shipped", status="done", milestone="demo",
                    archive=".project/archive/001-demo")
        commit_all(member, "path state")
        result = self.add("web", member)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_refuses_colliding_member_branch_or_tag(self) -> None:
        cases = {
            "branch": ("branch", "gsd-path/acme-M001"),
            "task": ("branch", "gsd-path-task/acme-T001"),
            "remote": ("update-ref", "refs/remotes/origin/gsd-path/acme-M002"),
            "tag": ("tag", "milestone/acme-001-demo"),
        }
        for label, (command, ref) in cases.items():
            with self.subTest(label):
                member = self.make_member(f"web-{label}")
                if command == "update-ref":
                    git(member, "update-ref", ref, "HEAD")
                else:
                    git(member, command, ref)
                self.assert_refused(self.add(f"web-{label}", member), "collide with coordinator")

    def test_add_ignores_member_refs_named_for_other_coordinators(self) -> None:
        member = self.make_member("web")
        git(member, "branch", "gsd-path/M001")
        git(member, "tag", "milestone/001-demo")
        git(member, "branch", "gsd-path/acmex-M001")
        result = self.add("web", member)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_validate_and_repair_allow_refs_path_created_during_build(self) -> None:
        member = self.joined()
        git(member, "branch", "gsd-path/acme-M001")
        git(member, "branch", "gsd-path-task/acme-T001")
        git(member, "tag", "milestone/acme-001-demo")
        for command in ("validate", "repair"):
            result = self.run_members(command)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_still_refuses_refs_path_creates_on_members(self) -> None:
        member = self.make_member("web")
        git(member, "branch", "gsd-path/acme-M001")
        git(member, "tag", "milestone/acme-001-demo")
        self.assert_refused(self.add("web", member), "collide with coordinator")

    def test_add_refuses_during_build_and_ship(self) -> None:
        member = self.make_member("web")
        for phase in ("build", "ship"):
            with self.subTest(phase):
                write_state(self.coordinator, "acme", phase)
                self.assert_refused(self.add("web", member), "milestone boundary")

    def test_add_refuses_duplicate_name_or_checkout(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        before = (self.coordinator / ".project" / "MEMBERS.md").read_bytes()
        for name, checkout in (("web", self.make_member("other")), ("web2", web)):
            with self.subTest(name):
                result = self.add(name, checkout)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("already", result.stderr)
                self.assertEqual((self.coordinator / ".project" / "MEMBERS.md").read_bytes(), before)

    def test_add_refuses_duplicate_github_origin_across_url_forms(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        before = (self.coordinator / ".project" / "MEMBERS.md").read_bytes()
        for name, remote in (("clone", "git@github.com:Acme/Web"),
                             ("clone2", "ssh://git@github.com/acme/web.git")):
            with self.subTest(remote):
                clone = self.make_member(name, remote=remote)
                result = self.add(name, clone)
                self.assertIn("member already recorded", result.stderr)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual((self.coordinator / ".project" / "MEMBERS.md").read_bytes(), before)

    def test_add_refuses_duplicate_git_common_dir(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        linked = self.root / "linked"
        git(web, "worktree", "add", "-q", "-b", "linked", str(linked))
        path = self.coordinator / ".project" / "MEMBERS.md"
        path.write_bytes(path.read_text(encoding="utf-8").replace(
            "https://github.com/acme/web.git", "https://github.com/acme/other.git"
        ).encode("utf-8"))
        before = path.read_bytes()
        result = self.add("linked", linked)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("member already recorded", result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_add_refuses_coordinator_as_its_own_member(self) -> None:
        self.assert_refused(self.add("acme", self.coordinator), "coordinator")

    def test_validate_rechecks_members_after_add(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        (web / "README.md").write_bytes("changed".encode("utf-8"))
        result = self.run_members("validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("uncommitted changes", result.stderr)

    def test_validate_refuses_member_whose_origin_changed(self) -> None:
        web = self.make_member("web")
        self.assertEqual(self.add("web", web).returncode, 0)
        git(web, "remote", "set-url", "origin", "https://github.com/acme/other.git")
        result = self.run_members("validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("origin changed", result.stderr)

    def test_validate_refuses_malformed_members_file(self) -> None:
        path = self.coordinator / ".project" / "MEMBERS.md"
        for label, body in {
            "unknown field": "## web\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: default\nColor: red\n",
            "bad name": "## Web App\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: default\n",
            "bad mode": "## web\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: squash\n",
            "section heading changed": "# web\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: default\n",
            "unexpected preamble": "extra\n## web\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: default\n",
            "repeated default branch": "## web\nCheckout: /x\nRemote: https://github.com/a/b\nIntegration: default\nDefault branch: main\nDefault branch: master\n",
        }.items():
            with self.subTest(label):
                path.write_bytes(("# Members\n\n" + body).encode("utf-8"))
                result = self.run_members("validate")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("MEMBERS.md", result.stderr)

    def test_validate_refuses_a_default_branch_that_cannot_be_recorded(self) -> None:
        path = self.coordinator / ".project" / "MEMBERS.md"
        row = f"# Members\n\n## web\nCheckout: {self.root / 'web'}\nRemote: https://github.com/a/b\nIntegration: default\n"
        for value in (" gsd-path/M001", " a b", ""):
            with self.subTest(value):
                path.write_bytes(f"{row}Default branch:{value}\n".encode("utf-8"))
                result = self.run_members("validate")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("MEMBERS.md member web has invalid Default branch", result.stderr)


    def marker_path(self, member: Path) -> Path:
        common = git(member, "rev-parse", "--path-format=absolute", "--git-common-dir")
        return Path(common) / "gsd-path" / "member.json"

    def joined(self, name: str = "web") -> Path:
        member = self.make_member(name)
        result = self.add(name, member)
        self.assertEqual(result.returncode, 0, result.stderr)
        return member

    def test_add_marks_member_without_tracked_files(self) -> None:
        member = self.joined()
        self.assertEqual(
            json.loads(self.marker_path(member).read_text(encoding="utf-8")),
            {"schema": "gsd-path/member/v1", "coordinator": str(self.coordinator),
             "project": "acme", "name": "web"},
        )
        self.assertEqual(git(member, "status", "--porcelain", "--untracked-files=all"), "")
        role = members.member_role(member)
        self.assertEqual(role, {"coordinator": self.coordinator, "project": "acme", "name": "web"})

    def test_member_role_is_none_without_marker(self) -> None:
        self.assertIsNone(members.member_role(self.make_member("web")))
        self.assertIsNone(members.member_role(self.coordinator))

    def test_member_role_holds_in_a_linked_worktree(self) -> None:
        member = self.joined()
        linked = self.root / "web-linked"
        git(member, "worktree", "add", "-q", "-b", "side", str(linked))
        self.assertEqual(members.member_role(linked)["name"], "web")

    def test_validate_and_role_fail_closed_on_missing_marker_until_repair(self) -> None:
        member = self.joined()
        self.marker_path(member).unlink()
        result = self.run_members("validate")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("members.py repair", result.stderr)
        repaired = self.run_members("repair")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(self.run_members("validate").returncode, 0)

    def test_role_fails_closed_when_coordinator_no_longer_lists_member(self) -> None:
        member = self.joined()
        (self.coordinator / ".project" / "MEMBERS.md").unlink()
        with self.assertRaisesRegex(members.MembersError, "members.py repair"):
            members.member_role(member)

    def test_role_fails_closed_when_coordinator_project_changed(self) -> None:
        member = self.joined()
        write_state(self.coordinator, "renamed", "plan")
        with self.assertRaisesRegex(members.MembersError, "members.py repair"):
            members.member_role(member)

    def test_role_fails_closed_when_members_file_names_another_repo(self) -> None:
        member = self.joined()
        other = self.make_member("other")
        path = self.coordinator / ".project" / "MEMBERS.md"
        path.write_bytes(path.read_text(encoding="utf-8").replace(str(member), str(other)).encode("utf-8"))
        with self.assertRaisesRegex(members.MembersError, "members.py repair"):
            members.member_role(member)

    def test_repair_follows_a_moved_coordinator(self) -> None:
        member = self.joined()
        moved = self.root / "acme-moved"
        self.coordinator.rename(moved)
        self.coordinator = moved
        stale = self.run_members("validate")
        self.assertNotEqual(stale.returncode, 0)
        self.assertIn("members.py repair", stale.stderr)
        self.assertEqual(self.run_members("repair").returncode, 0)
        self.assertEqual(members.member_role(member)["coordinator"], moved)

    @posix_permissions_only
    def test_repair_skips_valid_read_only_marker_and_fixes_missing_marker(self) -> None:
        first = self.joined("web")
        second = self.joined("sdk")
        first_marker = self.marker_path(first)
        self.marker_path(second).unlink()
        inode = first_marker.stat().st_ino
        directory = first_marker.parent
        original_mode = stat.S_IMODE(directory.stat().st_mode)
        directory.chmod(0o555)
        try:
            repaired = self.run_members("repair")
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertEqual(first_marker.stat().st_ino, inode)
            self.assertEqual(members.member_role(first)["coordinator"], self.coordinator)
            self.assertEqual(members.member_role(second)["coordinator"], self.coordinator)
        finally:
            directory.chmod(original_mode)

    def test_malformed_markers_fail_closed_and_can_be_repaired(self) -> None:
        member = self.joined()
        marker = self.marker_path(member)
        valid = json.loads(marker.read_text(encoding="utf-8"))
        for label, content in {
            "invalid JSON": "{invalid}",
            "truncated": '{"schema":',
            "null coordinator": json.dumps({**valid, "coordinator": None}),
            "null project": json.dumps({**valid, "project": None}),
            "null name": json.dumps({**valid, "name": None}),
            "null schema": json.dumps({**valid, "schema": None}),
            "blank name": json.dumps({**valid, "name": " "}),
            "relative coordinator": json.dumps({**valid, "coordinator": "acme"}),
        }.items():
            with self.subTest(label):
                marker.write_bytes(content.encode("utf-8"))
                with self.assertRaisesRegex(members.MembersError,
                                            "members.py repair --repo <coordinator>"):
                    members.member_role(member)
                result = self.run_members("validate")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"members.py repair --repo {self.coordinator}", result.stderr)
                repaired = self.run_members("repair")
                self.assertEqual(repaired.returncode, 0, repaired.stderr)
                self.assertEqual(members.member_role(member)["coordinator"], self.coordinator)

    def test_add_replaces_a_malformed_marker(self) -> None:
        member = self.make_member("web")
        marker = self.marker_path(member)
        marker.parent.mkdir(parents=True)
        marker.write_bytes('{"schema":'.encode("utf-8"))
        added = self.add("web", member)
        self.assertEqual(added.returncode, 0, added.stderr)
        self.assertEqual(members.member_role(member)["coordinator"], self.coordinator)

    @posix_permissions_only
    def test_add_marker_write_failure_leaves_members_unchanged_for_retry(self) -> None:
        member = self.make_member("web")
        marker = self.marker_path(member)
        directory = marker.parent
        directory.mkdir(parents=True)
        original_mode = stat.S_IMODE(directory.stat().st_mode)
        directory.chmod(0o555)
        try:
            failed = self.add("web", member)
            self.assertNotEqual(failed.returncode, 0)
            self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())
            self.assertFalse(marker.exists())
        finally:
            directory.chmod(original_mode)
        retried = self.add("web", member)
        self.assertEqual(retried.returncode, 0, retried.stderr)
        self.assertEqual(members.member_role(member)["coordinator"], self.coordinator)

    @requires_symlink
    def test_add_refuses_marker_directory_symlink_to_checkout(self) -> None:
        member = self.make_member("web")
        directory = self.marker_path(member).parent
        directory.symlink_to(member, target_is_directory=True)
        refused = self.add("web", member)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(str(directory), refused.stderr)
        self.assertFalse((member / "member.json").exists())
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())
        self.assertEqual(git(member, "status", "--porcelain", "--untracked-files=all"), "")
        with self.assertRaises(members.MembersError) as caught:
            members.member_role(member)
        self.assertIn(str(directory), str(caught.exception))
        (self.coordinator / ".project" / "MEMBERS.md").write_bytes(
            members.render([{"name": "web", "checkout": str(member),
                             "remote": "https://github.com/acme/web.git",
                             "integration": "default"}]).encode("utf-8"),
        )
        validation = self.run_members("validate")
        self.assertNotEqual(validation.returncode, 0)
        self.assertIn(str(directory), validation.stderr)
        self.assertIn(f"members.py repair --repo {self.coordinator}", validation.stderr)

    def test_nonfile_marker_requires_manual_removal_before_repair(self) -> None:
        member = self.joined()
        marker = self.marker_path(member)
        marker.unlink()
        marker.mkdir()
        contents = marker / "keep.txt"
        contents.write_bytes("keep".encode("utf-8"))
        for command in ("validate", "repair"):
            result = self.run_members(command)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(marker), result.stderr)
            self.assertIn("remove it by hand", result.stderr)
            self.assertIn("members.py repair --repo", result.stderr)
        with self.assertRaises(members.MembersError) as caught:
            members.member_role(member)
        self.assertIn("remove it by hand", str(caught.exception))
        self.assertEqual(contents.read_text(encoding="utf-8"), "keep")
        shutil.rmtree(marker)
        repaired = self.run_members("repair")
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        self.assertEqual(members.member_role(member)["coordinator"], self.coordinator)

    def test_add_refuses_nonfile_marker(self) -> None:
        member = self.make_member("web")
        marker = self.marker_path(member)
        marker.parent.mkdir(parents=True)
        marker.mkdir()
        refused = self.add("web", member)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn(str(marker), refused.stderr)
        self.assertIn("remove it by hand", refused.stderr)
        self.assertFalse((self.coordinator / ".project" / "MEMBERS.md").exists())

    def test_live_coordinator_copy_cannot_take_over_member(self) -> None:
        member = self.joined()
        marker = self.marker_path(member)
        original_marker = marker.read_bytes()
        original = self.coordinator
        copied = self.root / "acme-copy"
        shutil.copytree(original, copied)
        self.coordinator = copied
        refused = self.run_members("repair")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("already a member of", refused.stderr)
        self.assertEqual(marker.read_bytes(), original_marker)
        self.assertEqual(members.member_role(member)["coordinator"], original)
        (copied / ".project" / "MEMBERS.md").unlink()
        refused = self.add("web", member)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("already a member of", refused.stderr)
        self.assertEqual(marker.read_bytes(), original_marker)
        shutil.copyfile(original / ".project" / "MEMBERS.md",
                        copied / ".project" / "MEMBERS.md")
        (original / ".project" / "MEMBERS.md").unlink()
        transferred = self.run_members("repair")
        self.assertEqual(transferred.returncode, 0, transferred.stderr)
        self.assertEqual(members.member_role(member)["coordinator"], copied)

    def test_add_and_repair_refuse_a_member_of_another_coordinator(self) -> None:
        member = self.make_member("web")
        marker = self.marker_path(member)
        marker.parent.mkdir(parents=True)
        foreign = {"schema": "gsd-path/member/v1", "coordinator": str(self.root / "other"),
                   "project": "other", "name": "web"}
        marker.write_bytes(json.dumps(foreign).encode("utf-8"))
        self.assert_refused(self.add("web", member), "already a member of other")
        (self.coordinator / ".project" / "MEMBERS.md").write_bytes(
            members.render([{"name": "web", "checkout": str(member),
                             "remote": "https://github.com/acme/web.git",
                             "integration": "default"}]).encode("utf-8"),
        )
        result = self.run_members("repair")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("already a member of other", result.stderr)
        self.assertEqual(json.loads(marker.read_text(encoding="utf-8")), foreign)


class MembersArtifactTests(unittest.TestCase):
    def test_ship_verification_accepts_members_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            git(repo, "init", "-q", "-b", "gsd-path/M001")
            write_state(repo, "acme", "ship")
            (repo / ".project" / "MEMBERS.md").write_bytes("# Members\n".encode("utf-8"))
            commit_all(repo)
            head = git(repo, "rev-parse", "HEAD")
            lean_verification._require_ship_inputs(repo, head)
            (repo / ".project" / "STRAY.md").write_bytes("x".encode("utf-8"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "STRAY.md"):
                lean_verification._require_ship_inputs(repo, head)

    def test_ship_verification_prunes_empty_host_claude_dir(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            git(repo, "init", "-q", "-b", "gsd-path/M001")
            write_state(repo, "acme", "ship")
            commit_all(repo)
            head = git(repo, "rev-parse", "HEAD")
            (repo / ".project" / ".claude" / ".cc-writes").mkdir(parents=True)
            lean_verification._require_ship_inputs(repo, head)
            self.assertFalse((repo / ".project" / ".claude").exists())
            (repo / ".project" / ".claude").mkdir()
            (repo / ".project" / ".claude" / "note.txt").write_bytes("x".encode("utf-8"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "unsupported .project artifacts: .claude"):
                lean_verification._require_ship_inputs(repo, head)

    def test_ship_verification_skips_ignored_untracked_entries(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary).resolve()
            git(repo, "init", "-q", "-b", "gsd-path/M001")
            write_state(repo, "acme", "ship")
            (repo / ".gitignore").write_bytes(".DS_Store\n".encode("utf-8"))
            commit_all(repo)
            head = git(repo, "rev-parse", "HEAD")
            (repo / ".project" / ".DS_Store").write_bytes("x".encode("utf-8"))
            lean_verification._require_ship_inputs(repo, head)
            # A tracked copy ships, so it is an artifact again.
            git(repo, "add", "-f", ".project/.DS_Store")
            with self.assertRaisesRegex(check_handoffs.HandoffError, r"\.DS_Store"):
                lean_verification._require_ship_inputs(repo, head)

    def test_milestone_close_keeps_members_file_active(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            git(Path(temporary), "init", "-q")
            active = Path(temporary) / ".project"
            archive = active / "archive" / "001-demo"
            archive.mkdir(parents=True)
            (active / "STATE.md").write_bytes("state".encode("utf-8"))
            (active / "MEMBERS.md").write_bytes("# Members\n".encode("utf-8"))
            archive_milestone.require_clean_active_root(active, archive)
            (active / "STRAY.md").write_bytes("x".encode("utf-8"))
            with self.assertRaisesRegex(archive_milestone.ArchiveError, "STRAY.md"):
                archive_milestone.require_clean_active_root(active, archive)

    def test_milestone_close_skips_ignored_entries_but_not_pipeline_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            git(root, "init", "-q")
            (root / ".gitignore").write_bytes(".DS_Store\nintent/\n".encode("utf-8"))
            active = root / ".project"
            archive = active / "archive" / "001-demo"
            archive.mkdir(parents=True)
            (active / "STATE.md").write_bytes("state".encode("utf-8"))
            (active / ".DS_Store").write_bytes("x".encode("utf-8"))
            archive_milestone.require_clean_active_root(active, archive)
            (active / "intent").mkdir()
            (active / "intent" / "INTENT.md").write_bytes("x".encode("utf-8"))
            with self.assertRaisesRegex(archive_milestone.ArchiveError, "intent"):
                archive_milestone.require_clean_active_root(active, archive)


if __name__ == "__main__":
    unittest.main()
