import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import install
import members
from tests._platform import requires_symlink

INSTALL = ROOT / "scripts" / "install.py"
MEMBERS = ROOT / "scripts" / "members.py"
STATE = (
    "---\npipeline: gsd-path/v2\nproject: {project}\nmilestone: demo\nphase: {phase}\n"
    "status: {status}\nbranch: gsd-path/M001\narchive: {archive}\n---\n"
)
GUARD_LAUNCHER = (
    "# gsd-path guard — stable runtime launcher\n"
    "import runpy\n"
    f"runpy.run_path({str(ROOT / 'scripts' / 'git_guard.py')!r}, run_name='__main__')\n"
)


def git(repo: Path, *arguments: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *arguments],
        cwd=repo, encoding="utf-8", errors="replace", capture_output=True, check=check,
    )


def write_state(repo: Path, project: str, phase: str, status: str, archive: str = "null") -> None:
    (repo / ".project").mkdir(exist_ok=True)
    (repo / ".project" / "STATE.md").write_bytes(
        STATE.format(project=project, phase=phase, status=status, archive=archive).encode("utf-8")
    )


def executable(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class MemberInstallTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        self.coordinator = self.root / "acme"
        self.coordinator.mkdir()
        git(self.coordinator, "init", "-q", "-b", "main")
        write_state(self.coordinator, "acme", "plan", "active")
        git(self.coordinator, "add", "-A")
        git(self.coordinator, "commit", "-q", "-m", "init")
        (self.coordinator / ".gsd-path").mkdir()
        (self.coordinator / ".gsd-path" / "git_guard.py").write_bytes(GUARD_LAUNCHER.encode("utf-8"))
        self.member = self.root / "web"
        self.member.mkdir()
        git(self.member, "init", "-q", "-b", "main")
        (self.member / "app.py").write_bytes("print('v1')\n".encode("utf-8"))
        write_state(self.member, "web", "shipped", "done", ".project/archive/001-demo")
        git(self.member, "add", "-A")
        git(self.member, "commit", "-q", "-m", "init")
        git(self.member, "remote", "add", "origin", "https://github.com/acme/web.git")
        git(self.member, "update-ref", "refs/remotes/origin/main", "HEAD")
        git(self.member, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main")
        self.remote = self.root / "remote.git"
        git(self.root, "init", "-q", "--bare", str(self.remote))
        self.hooks = self.member / ".git" / "hooks"
        self.hooks.mkdir(exist_ok=True)
        for sample in self.hooks.glob("*.sample"):
            sample.unlink()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def join(self) -> None:
        result = subprocess.run(
            [sys.executable, str(MEMBERS), "add", "--repo", str(self.coordinator),
             "--name", "web", "--checkout", str(self.member)],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def install(self, coordinator=None, member=None):
        return subprocess.run(
            [sys.executable, str(INSTALL), "--member-of", str(coordinator or self.coordinator),
             "--project", str(member or self.member)],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )

    def installed(self) -> None:
        self.join()
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)

    def change(self, text: str = "print('v2')\n") -> subprocess.CompletedProcess:
        (self.member / "app.py").write_bytes(text.encode("utf-8"))
        git(self.member, "add", "app.py")
        return git(self.member, "commit", "-q", "-m", "feat: member change", check=False)

    def branch(self, name: str) -> str:
        git(self.member, "checkout", "-q", "-b", name)
        (self.member / "app.py").write_bytes(f"print({name!r})\n".encode("utf-8"))
        git(self.member, "add", "app.py")
        git(self.member, "commit", "-q", "--no-verify", "-m", f"work on {name}")
        sha = git(self.member, "rev-parse", "HEAD").stdout.strip()
        git(self.member, "checkout", "-q", "main")
        return sha

    def push(self, ref: str) -> subprocess.CompletedProcess:
        return git(self.member, "push", "-q", str(self.remote), ref, check=False)

    def test_installed_hooks_run_the_coordinator_guard(self) -> None:
        self.installed()
        self.assertEqual(git(self.member, "status", "--porcelain", "--untracked-files=all").stdout, "")
        committed = self.change()
        self.assertEqual(committed.returncode, 0, committed.stderr)
        work = self.branch("gsd-path/acme-M001")
        refused = self.push("gsd-path/acme-M001")
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("not authorized", refused.stderr)
        members.authorize_push(self.member, "acme", "refs/heads/gsd-path/acme-M001", work)
        allowed = self.push("gsd-path/acme-M001")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)

    def test_existing_hooks_are_chained_after_the_guard(self) -> None:
        executable(self.hooks / "pre-commit",
                   '#!/bin/sh\necho ran >> "$(git rev-parse --git-dir)/chained-ran"\n')
        executable(self.hooks / "pre-push",
                   '#!/bin/sh\ncat >> "$(git rev-parse --git-dir)/push-stdin"\n')
        original = (self.hooks / "pre-commit").read_text(encoding="utf-8")
        self.installed()
        self.assertEqual((self.hooks / "pre-commit.gsd-path-chained").read_text(encoding="utf-8"), original)
        self.assertEqual(self.change().returncode, 0)
        ran = self.member / ".git" / "chained-ran"
        self.assertEqual(ran.read_text(encoding="utf-8"), "ran\n")
        self.branch("feature/x")
        pushed = self.push("feature/x")
        self.assertEqual(pushed.returncode, 0, pushed.stderr)
        self.assertIn("refs/heads/feature/x", (self.member / ".git" / "push-stdin").read_text(encoding="utf-8"))
        (self.coordinator / ".project" / "MEMBERS.md").unlink()
        blocked = self.change("print('v3')\n")
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("members.py repair", blocked.stderr)
        self.assertEqual(ran.read_text(encoding="utf-8"), "ran\n", "a blocked guard must not run the chained hook")

    def test_remove_deletes_member_hooks_and_restores_chained_hooks(self) -> None:
        self.assertEqual((members.MEMBER_HOOK_MARKER, members.CHAINED_HOOK_SUFFIX),
                         (install.MEMBER_HOOK_MARKER, install.CHAINED_HOOK_SUFFIX))
        original = '#!/bin/sh\necho ran >> "$(git rev-parse --git-dir)/chained-ran"\n'
        executable(self.hooks / "pre-commit", original)
        self.installed()
        removed = subprocess.run(
            [sys.executable, str(MEMBERS), "remove", "--repo", str(self.coordinator), "--name", "web"],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(removed.returncode, 0, removed.stderr)
        self.assertEqual(sorted(path.name for path in self.hooks.iterdir()), ["pre-commit"])
        self.assertEqual((self.hooks / "pre-commit").read_text(encoding="utf-8"), original)
        # Without the marker a member hook would refuse every commit; the restored hook runs instead.
        committed = self.change()
        self.assertEqual(committed.returncode, 0, committed.stderr)
        self.assertEqual((self.member / ".git" / "chained-ran").read_text(encoding="utf-8"), "ran\n")

    def test_dry_run_writes_nothing(self) -> None:
        executable(self.hooks / "pre-commit", "#!/bin/sh\nexit 0\n")
        self.join()
        result = subprocess.run(
            [sys.executable, str(INSTALL), "--member-of", str(self.coordinator),
             "--project", str(self.member), "--dry-run"],
            encoding="utf-8", errors="replace", capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("dry run", result.stdout)
        self.assertEqual(sorted(path.name for path in self.hooks.iterdir()), ["pre-commit"])

    def test_install_is_idempotent(self) -> None:
        executable(self.hooks / "pre-commit", "#!/bin/sh\nexit 0\n")
        self.installed()
        first = {path.name: path.read_text(encoding="utf-8") for path in self.hooks.iterdir()}
        again = self.install()
        self.assertEqual(again.returncode, 0, again.stderr)
        second = {path.name: path.read_text(encoding="utf-8") for path in self.hooks.iterdir()}
        self.assertEqual(first, second)

    def test_member_own_path_hooks_are_replaced_not_chained(self) -> None:
        executable(self.hooks / "pre-commit", install.pre_commit_hook("python3"))
        self.installed()
        self.assertFalse((self.hooks / "pre-commit.gsd-path-chained").exists())
        self.assertEqual(self.change().returncode, 0)

    def test_a_deliberately_disabled_hook_stays_disabled(self) -> None:
        # A user-disabled hook (renamed to <hook>.disabled*) must not be
        # silently re-enabled by reinstalling beside the rename (#469).
        disabled = self.hooks / "pre-push.disabled-2026"
        executable(disabled, "#!/bin/sh\nexit 0\n")

        self.installed()

        self.assertFalse((self.hooks / "pre-push").exists())
        self.assertTrue(disabled.is_file())
        self.assertIn("(left disabled)", self.install().stdout)

        # A leftover ACTIVE hook beside the rename is never hidden: a foreign
        # one still chains instead of being skipped as disabled.
        executable(self.hooks / "pre-push", "#!/bin/sh\nexit 3\n")
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("chained", result.stdout)
        self.assertTrue((self.hooks / "pre-push.gsd-path-chained").is_file())

    def test_hooks_follow_a_moved_coordinator_after_repair(self) -> None:
        self.installed()
        moved = self.root / "acme-moved"
        self.coordinator.rename(moved)
        self.assertNotEqual(self.change().returncode, 0)
        git(self.member, "reset", "-q", "--hard")
        repaired = subprocess.run([sys.executable, str(MEMBERS), "repair", "--repo", str(moved)],
                                  encoding="utf-8", errors="replace", capture_output=True, check=False)
        self.assertEqual(repaired.returncode, 0, repaired.stderr)
        committed = self.change()
        self.assertEqual(committed.returncode, 0, committed.stderr)

    def test_install_refusals_leave_hooks_unchanged(self) -> None:
        executable(self.hooks / "pre-commit", "#!/bin/sh\nexit 0\n")
        not_member = self.install()
        self.assertNotEqual(not_member.returncode, 0)
        self.assertIn("not a member", not_member.stderr)
        self.join()
        other = self.root / "other"
        other.mkdir()
        self.assertIn("not a member", self.install(other).stderr)
        guard = self.coordinator / ".gsd-path" / "git_guard.py"
        guard.rename(guard.with_suffix(".bak"))
        self.assertIn("coordinator guard", self.install().stderr)
        guard.with_suffix(".bak").rename(guard)
        executable(self.hooks / "pre-commit.gsd-path-chained", "#!/bin/sh\nexit 0\n")
        self.assertIn("chained", self.install().stderr)
        (self.hooks / "pre-commit.gsd-path-chained").unlink()
        git(self.member, "config", "core.hooksPath", ".hooks")
        self.assertIn("inside the member worktree", self.install().stderr)
        self.assertEqual(sorted(path.name for path in self.hooks.iterdir()), ["pre-commit"])
        self.assertEqual((self.hooks / "pre-commit").read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")

    def test_unmanaged_coordinator_guard_refuses_without_writing_hooks(self) -> None:
        self.join()
        guard = self.coordinator / ".gsd-path" / "git_guard.py"
        guard.write_bytes("raise SystemExit(0)\n".encode("utf-8"))

        result = self.install()

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("coordinator guard is not installed", result.stderr)
        self.assertEqual(list(self.hooks.iterdir()), [])

    @requires_symlink
    def test_existing_temporary_symlink_refuses_without_changing_hooks(self) -> None:
        self.join()
        executable(self.hooks / "pre-commit", "#!/bin/sh\nexit 0\n")
        target = self.member / "app.py"
        original = target.read_bytes()
        (self.hooks / ".pre-commit.gsd-path-tmp").symlink_to(target)

        result = self.install()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(target.read_bytes(), original)
        self.assertEqual((self.hooks / "pre-commit").read_text(encoding="utf-8"), "#!/bin/sh\nexit 0\n")
        self.assertFalse((self.hooks / "pre-commit.gsd-path-chained").exists())
        self.assertEqual(sorted(path.name for path in self.hooks.iterdir()),
                         [".pre-commit.gsd-path-tmp", "pre-commit"])

    def test_linked_worktree_refuses_hooks_inside_primary_checkout(self) -> None:
        self.join()
        linked = self.root / "web-linked"
        git(self.member, "worktree", "add", "-q", "-b", "linked", str(linked))
        primary_hooks = self.member / ".hooks"
        primary_hooks.mkdir()
        executable(primary_hooks / "pre-commit", "#!/bin/sh\nexit 0\n")
        git(self.member, "config", "core.hooksPath", str(primary_hooks))

        result = self.install(member=linked)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("inside the member worktree", result.stderr)
        self.assertEqual(sorted(path.name for path in primary_hooks.iterdir()), ["pre-commit"])
        self.assertEqual((primary_hooks / "pre-commit").read_text(encoding="utf-8"),
                         "#!/bin/sh\nexit 0\n")


if __name__ == "__main__":
    unittest.main()
