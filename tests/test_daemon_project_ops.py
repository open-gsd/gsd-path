"""Project setup actions for the app: hooks, health check, and member repair.

The daemon chooses the helper command; the helper owns every rule. The daemon
also picks the hosts for Add guards and migrates a legacy runtime first.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon import project_ops
from gsd_daemon.model import ProjectStatus
from gsd_daemon.plugin import PluginManager


class Case(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name).resolve()
        self.root = str(self.base / "coordinator")
        self.member = str(self.base / "member-api")
        self.calls = []
        self.answers = {}  # first helper argument after the script -> (rc, stdout, stderr)

        def runner(argv, cwd=None):
            argv = [str(part) for part in argv]
            self.calls.append(argv)
            script = Path(argv[1]).name
            key = (script, argv[2])
            return self.answers.get(key, (0, "done\n", ""))

        self.plugin = PluginManager(home=self.base / "home", user_home=self.base / "user", runner=runner,
                                    git_runner=lambda argv, cwd=None: (0, "", ""), environ={},
                                    repo="https://example.invalid/gsd-path.git")
        (self.plugin.src_dir / ".git").mkdir(parents=True)
        self.handler = SimpleNamespace(plugin=self.plugin, watcher=SimpleNamespace(projects={self.root: ProjectStatus(root=self.root)}))
        self.members = {"members": [{"name": "api", "checkout": self.member, "remote": "git@x:api.git",
                                     "integration": "default"}]}

    def run_op(self, **body):
        return project_ops.run(self.handler, {"root": self.root, **body})

    def helper_args(self):
        return [call[2:] for call in self.calls]


def install_agent(plugin, host):
    skill = plugin.global_root(host) / "gsd-path"
    skill.mkdir(parents=True)
    (skill / "VERSION").write_text("1.0.0\n", encoding="utf-8")


class InstallerOpTests(Case):
    def test_each_op_runs_its_installer_flag_on_the_project(self):
        for op, flag in (("hooks-refresh", "--hooks-refresh"),
                         ("hooks-refresh-full", "--hooks-refresh-full"), ("runtime-restore", "--runtime-restore")):
            with self.subTest(op=op):
                self.calls.clear()
                result = self.run_op(op=op)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.calls, [[sys.executable, str(self.plugin.install_py), flag, "--project", self.root]])

    def test_hooks_init_passes_the_chosen_hosts_to_the_installer(self):
        self.run_op(op="hooks-init", hosts=["claude", "codex"])
        self.assertEqual(self.helper_args(), [["--hooks-init", "--claude", "--codex", "--project", self.root]])
        self.calls.clear()
        with self.assertRaises(ValueError):
            self.run_op(op="hooks-init", hosts=["--all"])
        self.assertEqual(self.calls, [])

    def test_hooks_init_without_hosts_uses_the_agents_installed_on_this_computer(self):
        install_agent(self.plugin, "grok")
        install_agent(self.plugin, "claude")
        for body in ({}, {"hosts": []}):
            with self.subTest(body=body):
                self.calls.clear()
                result = self.run_op(op="hooks-init", **body)
                self.assertTrue(result["ok"], result)
                self.assertEqual(self.helper_args(), [["--hooks-init", "--claude", "--grok", "--project", self.root]])

    def test_hooks_init_without_hosts_or_an_installed_agent_runs_nothing(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                result = self.run_op(op="hooks-init", dry_run=dry_run)
                self.assertEqual(result, {"ok": False, "stdout_tail": "", "error": project_ops.NO_AGENT_ERROR})
        self.assertEqual(
            project_ops.NO_AGENT_ERROR,
            "No agent has GSD Path skills installed on this computer. Install the skills for an agent first.")
        self.assertEqual(self.calls, [])

    def test_dry_run_adds_the_installer_preview_flag(self):
        self.run_op(op="hooks-refresh", dry_run=True)
        self.assertEqual(self.helper_args(), [["--hooks-refresh", "--project", self.root, "--dry-run"]])

    def test_health_check_returns_findings_even_when_the_installer_reports_problems(self):
        self.answers[("install.py", "--doctor")] = (1, "note: codex: not installed\n1 problem found.\n",
                                                    "error: claude: incomplete install\n")
        result = self.run_op(op="doctor")
        self.assertEqual(self.helper_args(), [["--doctor", "--project", self.root]])
        self.assertFalse(result["ok"])
        self.assertIn("1 problem found.", result["stdout_tail"])
        self.assertIn("incomplete install", result["error"])

    def test_an_unwatched_project_or_unknown_op_runs_nothing(self):
        for body in ({"root": "/etc", "op": "doctor"}, {"op": "rm -rf"}, {"op": None}, {"root": 5, "op": "doctor"}):
            with self.subTest(body=body), self.assertRaises(ValueError):
                project_ops.run(self.handler, {"root": self.root, **body})
        self.assertEqual(self.calls, [])

    def test_a_card_of_another_framework_runs_nothing(self):
        card = self.root + "::gsd-core"
        self.handler.watcher.projects[card] = ProjectStatus(root=self.root, id=card, flavor="gsd-core")
        with self.assertRaisesRegex(ValueError, "not a watched project"):
            project_ops.run(self.handler, {"root": card, "op": "doctor"})
        self.assertEqual(self.calls, [])

    def test_a_second_operation_is_refused_while_one_runs(self):
        release = threading.Event()
        started = threading.Event()
        inner = self.plugin.runner

        def slow(argv, cwd=None):
            started.set()
            release.wait(5)
            return inner(argv, cwd)
        self.plugin.runner = slow
        first = threading.Thread(target=lambda: self.run_op(op="doctor"))
        first.start()
        self.assertTrue(started.wait(5))
        try:
            with self.assertRaises(project_ops.Busy) as raised:
                self.run_op(op="hooks-refresh")
            self.assertEqual(raised.exception.status, 409)
        finally:
            release.set()
            first.join(5)
        self.assertEqual(len(self.calls), 1)


class LegacyRuntimeTests(Case):
    """The installer refuses a hook action on the old .gsd-path/runtime/ layout; one click migrates first."""

    def setUp(self):
        super().setUp()
        (Path(self.root) / ".gsd-path" / "runtime").mkdir(parents=True)
        self.migrate = ["--runtime-migrate", "--project", self.root]

    def test_a_hook_action_migrates_the_old_layout_first(self):
        self.answers[("install.py", "--runtime-migrate")] = (0, "migrated\n", "")
        self.answers[("install.py", "--hooks-refresh")] = (0, "refreshed\n", "")
        result = self.run_op(op="hooks-refresh")
        self.assertEqual(self.helper_args(), [self.migrate, ["--hooks-refresh", "--project", self.root]])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["stdout_tail"], "migrated\nrefreshed")
        self.calls.clear()
        self.run_op(op="hooks-init", hosts=["claude"])
        self.assertEqual(self.helper_args(), [self.migrate, ["--hooks-init", "--claude", "--project", self.root]])

    def test_add_guards_without_hosts_migrates_then_uses_the_installed_agents(self):
        install_agent(self.plugin, "claude")
        result = self.run_op(op="hooks-init")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.helper_args(), [self.migrate, ["--hooks-init", "--claude", "--project", self.root]])

    def test_add_guards_without_an_installed_agent_does_not_migrate(self):
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                result = self.run_op(op="hooks-init", dry_run=dry_run)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], project_ops.NO_AGENT_ERROR)
        self.assertEqual(self.calls, [])

    def test_a_preview_shows_only_the_migration_and_writes_nothing_else(self):
        self.run_op(op="hooks-refresh", dry_run=True)
        self.assertEqual(self.helper_args(), [[*self.migrate, "--dry-run"]])

    def test_a_failed_migration_stops_before_the_hook_action(self):
        self.answers[("install.py", "--runtime-migrate")] = (1, "", "error: resolve local edits first\n")
        result = self.run_op(op="hooks-refresh")
        self.assertEqual(self.helper_args(), [self.migrate])
        self.assertFalse(result["ok"])
        self.assertIn("resolve local edits first", result["error"])

    def test_other_actions_and_migrated_projects_do_not_migrate(self):
        self.run_op(op="doctor")
        self.assertEqual(self.helper_args(), [["--doctor", "--project", self.root]])
        self.calls.clear()
        (Path(self.root) / ".gsd-path" / "runtime.json").write_text("{}", encoding="utf-8")
        self.run_op(op="hooks-refresh")
        self.assertEqual(self.helper_args(), [["--hooks-refresh", "--project", self.root]])


class LegacyRuntimeInstallerTests(unittest.TestCase):
    """The same action against the real installer and a real Git project."""

    def legacy_project(self, guards):
        source = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(source))
        from scripts import install
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = Path(tmp.name).resolve()
        repo, home = base / "project", base / "home"
        repo.mkdir(); home.mkdir()
        environment = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}

        def git(*args):
            return subprocess.check_output(["git", "-c", "core.excludesFile=/dev/null", *args], cwd=repo,
                                           encoding="utf-8", errors="replace", stderr=subprocess.PIPE, env=environment).strip()
        git("init", "-b", "main"); git("config", "user.name", "t"); git("config", "user.email", "t@example.invalid")
        runtime = repo / ".gsd-path" / "runtime"
        runtime.mkdir(parents=True)
        for name in install.PROJECT_RUNTIME_SCRIPTS:
            shutil.copy2(source / "scripts" / name, runtime / name)
        for name in (*(install.GUARD_SCRIPTS if guards else ()), "status_runtime.py"):
            shutil.copy2(source / "scripts" / name, runtime.parent / name)
        git("add", "."); git("commit", "-m", "legacy runtime")

        def runner(argv, cwd=None):
            argv = [str(part) for part in argv]
            argv[1] = str(source / "scripts" / "install.py")  # the checkout under test, not a clone
            done = subprocess.run(argv, cwd=cwd, capture_output=True, encoding="utf-8", errors="replace", env=environment)
            return done.returncode, done.stdout, done.stderr

        plugin = PluginManager(home=base / "daemon-home", user_home=home, runner=runner,
                               git_runner=lambda argv, cwd=None: (0, "", ""), environ={},
                               repo="https://example.invalid/gsd-path.git")
        (plugin.src_dir / ".git").mkdir(parents=True)
        handler = SimpleNamespace(plugin=plugin, watcher=SimpleNamespace(projects={str(repo): ProjectStatus(root=str(repo))}))
        return repo, git, handler

    def assert_migrated(self, repo, git):
        self.assertFalse((repo / ".gsd-path" / "runtime").exists())
        self.assertTrue((repo / ".gsd-path" / "runtime.json").is_file())
        self.assertEqual(git("diff", "--cached", "--name-only"), "")  # migration never stages

    def test_refresh_on_a_legacy_project_migrates_and_refreshes_with_the_real_installer(self):
        repo, git, handler = self.legacy_project(guards=True)
        result = project_ops.run(handler, {"root": str(repo), "op": "hooks-refresh"})
        self.assertTrue(result["ok"], result)
        self.assert_migrated(repo, git)

    def test_add_guards_on_a_legacy_project_uses_the_installed_agent_with_the_real_installer(self):
        from scripts import install
        repo, git, handler = self.legacy_project(guards=False)
        install_agent(handler.plugin, "claude")
        result = project_ops.run(handler, {"root": str(repo), "op": "hooks-init"})
        self.assertTrue(result["ok"], result)
        self.assert_migrated(repo, git)
        for name in install.GUARD_SCRIPTS:
            self.assertTrue((repo / ".gsd-path" / name).is_file(), name)


class MemberTests(Case):
    def test_members_lists_each_member_with_marker_and_hook_state(self):
        self.answers[("members.py", "validate")] = (0, json.dumps(self.members), "")
        self.answers[("members.py", "detect")] = (0, json.dumps(
            {"member": True, "current": True, "checkout": self.member, "coordinator": self.root,
             "project": "demo", "name": "api"}), "")
        result = self.run_op(op="members")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.helper_args(), [["validate", "--repo", self.root], ["detect", "--checkout", self.member]])
        row = result["members"][0]
        self.assertEqual((row["name"], row["checkout"], row["integration"]), ("api", self.member, "default"))
        self.assertEqual(row["marker"], {"current": True, "reason": None})
        self.assertIs(row["hooks"], False)
        hooks_dir = Path(self.member) / ".git" / "hooks"
        hooks_dir.mkdir(parents=True)
        for name in ("pre-commit", "commit-msg", "pre-push"):
            (hooks_dir / name).write_text("#!/bin/sh\n# gsd-path member guard: runs the coordinator's guard\n")
        self.assertIs(self.run_op(op="members")["members"][0]["hooks"], True)
        (hooks_dir / "pre-push").write_text("#!/bin/sh\n")
        self.assertIs(self.run_op(op="members")["members"][0]["hooks"], False)

    def test_a_failed_validation_returns_the_helper_text_with_its_fix(self):
        text = f"error: member marker for api is missing or stale; run members.py repair --repo {self.root}\n"
        self.answers[("members.py", "validate")] = (1, "", text)
        result = self.run_op(op="members")
        self.assertEqual((result["ok"], result["members"]), (False, []))
        self.assertIn("run members.py repair", result["error"])

    def test_repair_runs_the_helper_and_has_no_preview(self):
        self.answers[("members.py", "repair")] = (0, json.dumps(self.members), "")
        result = self.run_op(op="member-repair")
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.helper_args(), [["repair", "--repo", self.root]])
        self.calls.clear()
        with self.assertRaises(ValueError):
            self.run_op(op="member-repair", dry_run=True)
        self.assertEqual(self.calls, [])

    def test_member_hooks_install_only_into_a_recorded_member(self):
        self.answers[("members.py", "validate")] = (0, json.dumps(self.members), "")
        result = self.run_op(op="member-hooks", member=self.member, dry_run=True)
        self.assertTrue(result["ok"], result)
        self.assertEqual(self.helper_args()[-1], ["--member-of", self.root, "--project", self.member, "--dry-run"])
        self.calls.clear()
        with self.assertRaises(ValueError):
            self.run_op(op="member-hooks", member=str(self.base / "elsewhere"))
        self.assertNotIn("--member-of", [arg for call in self.calls for arg in call])


class BoardMemberTests(Case):
    """The board reads each coordinator's members from the plugin status."""

    def setUp(self):
        super().setUp()
        (self.plugin.src_dir / "scripts").mkdir(parents=True)
        (self.plugin.src_dir / "scripts" / "members.py").write_text("", encoding="utf-8")

    def write_members_file(self):
        (Path(self.root) / ".project").mkdir(parents=True)
        (Path(self.root) / ".project" / "MEMBERS.md").write_text("# Members\n", encoding="utf-8")

    def test_a_project_without_a_members_file_is_not_a_coordinator_and_runs_no_helper(self):
        self.assertEqual(project_ops.board_members(self.plugin, self.root), {})
        self.assertEqual(self.calls, [])

    def test_a_coordinator_lists_its_members_with_marker_and_hook_state(self):
        self.write_members_file()
        self.answers[("members.py", "validate")] = (0, json.dumps(self.members), "")
        self.answers[("members.py", "detect")] = (0, json.dumps({"current": False, "reason": "marker names another coordinator"}), "")
        result = project_ops.board_members(self.plugin, self.root)
        self.assertIsNone(result["members_error"])
        self.assertEqual([(row["name"], row["checkout"]) for row in result["members"]], [("api", self.member)])
        self.assertEqual(result["members"][0]["marker"], {"current": False, "reason": "marker names another coordinator"})
        self.assertIs(result["members"][0]["hooks"], False)

    def test_a_members_file_that_does_not_validate_returns_the_helper_error(self):
        self.write_members_file()
        self.answers[("members.py", "validate")] = (1, "", "error: member api: marker is missing; run members.py repair\n")
        result = project_ops.board_members(self.plugin, self.root)
        self.assertEqual(result["members"], [])
        self.assertIn("run members.py repair", result["members_error"])

    def test_a_helper_that_cannot_run_returns_the_error_instead_of_raising(self):
        self.write_members_file()
        with mock.patch.object(self.plugin, "runner", side_effect=OSError("python not found")):
            result = project_ops.board_members(self.plugin, self.root)
        self.assertEqual(result, {"members": [], "members_error": "python not found"})

    def test_a_coordinator_without_the_plugin_source_reports_it_and_fetches_nothing(self):
        self.write_members_file()
        (self.plugin.src_dir / "scripts" / "members.py").unlink()
        git_calls = []
        self.plugin.git_runner = lambda argv, cwd=None: git_calls.append(argv) or (0, "", "")
        with mock.patch.object(self.plugin, "_fetch_release") as fetch:
            result = project_ops.board_members(self.plugin, self.root)
        self.assertEqual(result, {"members": [], "members_error": project_ops.NO_SOURCE_ERROR})
        self.assertEqual(self.calls, [])
        self.assertEqual(git_calls, [])
        fetch.assert_not_called()


class MemberAddTests(Case):
    """Add member: the app sends the form, members.py add owns every rule."""

    def test_add_runs_members_add_with_each_field(self):
        self.answers[("members.py", "add")] = (0, json.dumps(self.members), "")
        result = self.run_op(op="member-add", name=" api ", checkout=self.member, integration="pull-request")
        self.assertEqual(result, {"ok": True, "stdout_tail": json.dumps(self.members), "error": None})
        self.assertEqual(self.helper_args(), [["add", "--repo", self.root, "--name=api", f"--checkout={self.member}",
                                               "--integration=pull-request"]])

    def test_a_new_github_repository_passes_create_and_visibility(self):
        self.run_op(op="member-add", name="web", checkout="~/work/web", create="acme/web", visibility="private")
        self.assertEqual(self.helper_args(), [["add", "--repo", self.root, "--name=web",
                                               f"--checkout={os.path.expanduser('~/work/web')}", "--integration=default",
                                               "--create=acme/web", "--visibility=private"]])

    def test_a_value_that_looks_like_an_option_stays_a_value(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import members
        self.run_op(op="member-add", name="--create=evil/repo", checkout=self.member)
        parsed = members.parser().parse_args(self.helper_args()[0])
        self.assertEqual((parsed.name, str(parsed.checkout)), ("--create=evil/repo", self.member))
        self.assertIsNone(parsed.create)
        self.assertIsNone(parsed.visibility)

    def test_a_missing_or_non_text_field_runs_nothing(self):
        for body, text in (({"checkout": self.member}, "name is required"), ({"name": "api"}, "checkout is required"),
                           ({"name": "  ", "checkout": self.member}, "name is required"),
                           ({"name": "api", "checkout": self.member, "create": ["acme/web"]}, "create must be text")):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, text):
                self.run_op(op="member-add", **body)
        self.assertEqual(self.calls, [])

    def test_a_relative_checkout_runs_nothing(self):
        for checkout in ("api", "work/api", "./api"):
            with self.subTest(checkout=checkout), self.assertRaisesRegex(ValueError, "full folder path"):
                self.run_op(op="member-add", name="api", checkout=checkout, create="acme/api")
        self.assertEqual(self.calls, [])

    def test_add_has_no_preview(self):
        with self.assertRaisesRegex(ValueError, "no preview"):
            self.run_op(op="member-add", name="api", checkout=self.member, dry_run=True)
        self.assertEqual(self.calls, [])

    def test_a_refused_add_returns_the_helper_text(self):
        self.answers[("members.py", "add")] = (1, "", "error: members change only at a milestone boundary, not during build or ship\n")
        result = self.run_op(op="member-add", name="api", checkout=self.member)
        self.assertFalse(result["ok"])
        self.assertIn("milestone boundary", result["error"])


class MemberChangeTests(Case):
    """Remove a member and change its integration: members.py owns every rule."""

    def test_remove_runs_members_remove_with_the_name(self):
        out = json.dumps({"members": [], "cleaned": [self.member + "/.git/gsd-path/member.json"]})
        self.answers[("members.py", "remove")] = (0, out, "")
        result = self.run_op(op="member-remove", name=" api ")
        self.assertEqual(result, {"ok": True, "stdout_tail": out, "error": None})
        self.assertEqual(self.helper_args(), [["remove", "--repo", self.root, "--name=api"]])

    def test_integration_runs_set_integration_with_name_and_mode(self):
        self.run_op(op="member-integration", name="api", integration="pull-request")
        self.assertEqual(self.helper_args(), [["set-integration", "--repo", self.root, "--name=api",
                                               "--integration=pull-request"]])

    def test_a_name_that_looks_like_an_option_stays_a_value(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
        import members
        self.run_op(op="member-remove", name="--repo=/elsewhere")
        parsed = members.parser().parse_args(self.helper_args()[0])
        self.assertEqual((parsed.name, str(parsed.repo)), ("--repo=/elsewhere", self.root))

    def test_a_missing_field_or_a_preview_runs_nothing(self):
        for body, text in (({"op": "member-remove"}, "name is required"),
                           ({"op": "member-remove", "name": ["api"]}, "name is required"),
                           ({"op": "member-integration", "name": "api"}, "integration is required"),
                           ({"op": "member-remove", "name": "api", "dry_run": True}, "no preview"),
                           ({"op": "member-integration", "name": "api", "integration": "direct", "dry_run": True}, "no preview")):
            with self.subTest(body=body), self.assertRaisesRegex(ValueError, text):
                self.run_op(**body)
        self.assertEqual(self.calls, [])

    def test_a_refused_change_returns_the_helper_text(self):
        self.answers[("members.py", "remove")] = (1, "", "error: task briefs name member api; change those tasks before removing it\n")
        result = self.run_op(op="member-remove", name="api")
        self.assertFalse(result["ok"])
        self.assertIn("task briefs name member api", result["error"])


if __name__ == "__main__":
    unittest.main()
