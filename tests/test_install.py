import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import install


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_GIT_HOOKS_RESOLVER = install._resolve_git_hooks_path


class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        (self.source / "skills").mkdir(parents=True)
        (self.source / "AGENTS.md").write_text("agents\n", encoding="utf-8")
        (self.source / "WORKFLOW.md").write_text("workflow\n", encoding="utf-8")
        for name in install.SKILL_NAMES:
            skill = self.source / "skills" / name
            (skill / "references").mkdir(parents=True)
            (skill / "agents").mkdir()
            canonical = install.SKILL_ALIASES.get(name)
            body = (
                f"# Deprecated alias\n\nInvoke ${name}, then read "
                "[the canonical skill](CANONICAL.md).\n"
                if canonical
                else "Run $gsd-path, $gsd-path-build, and $gsd-path-discuss.\n"
            )
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: test\n---\n{body}",
                encoding="utf-8",
            )
            if canonical:
                (skill / "CANONICAL.md").write_text(
                    f"---\nname: {canonical}\ndescription: test\n---\nUse ${canonical}.\n",
                    encoding="utf-8",
                )
            (skill / "guide.md").write_text("Use $gsd-path.\n", encoding="utf-8")
            (skill / "agents" / "openai.yaml").write_text(
                'default_prompt: "Use $gsd-path."\n', encoding="utf-8"
            )
            (skill / "references" / "dispatch.md").write_text(
                "old dispatch\n", encoding="utf-8"
            )
        for target in install.TARGETS:
            adapter = self.source / "platforms" / target / "dispatch.md"
            adapter.parent.mkdir(parents=True)
            adapter.write_text(f"{target} dispatch for $gsd-path\n", encoding="utf-8")
        shared_adapter = (
            self.source
            / "platforms"
            / install.SHARED_AGENT_PROFILE
            / "dispatch.md"
        )
        shared_adapter.parent.mkdir(parents=True)
        shared_adapter.write_text(
            "shared dispatch for $gsd-path with invoke_subagent\n", encoding="utf-8"
        )
        (self.source / "platforms" / "cursor" / "agent.md").write_text(
            "---\nname: gsd-path\ndescription: test\nmodel: inherit\n---\ncursor agent\n",
            encoding="utf-8",
        )
        scripts = self.source / "scripts"
        scripts.mkdir(exist_ok=True)
        for name in install.GUARD_SCRIPTS:
            (scripts / name).write_text(
                f"# {name}\n{install.GUARD_MARKER}\n", encoding="utf-8"
            )
        self.sync_patch = mock.patch.object(
            install.sync_skill_resources, "mismatches", return_value=[]
        )
        self.sync_patch.start()
        self.git_hooks_patch = mock.patch.object(
            install, "_resolve_git_hooks_path", side_effect=self.resolve_test_hooks_path
        )
        self.git_hooks_patch.start()

    def tearDown(self):
        self.git_hooks_patch.stop()
        self.sync_patch.stop()
        self.temporary.cleanup()

    def resolve_test_hooks_path(self, project):
        resolved = ORIGINAL_GIT_HOOKS_RESOLVER(project)
        dot_git = project / ".git"
        if resolved is not None:
            return resolved
        return dot_git / "hooks" if dot_git.is_dir() else None

    def run_main(self, arguments, environment=None):
        output = io.StringIO()
        error = io.StringIO()
        env = {"CODEX_HOME": str(self.root / "legacy")}
        if environment:
            env.update(environment)
        with mock.patch.dict(os.environ, env, clear=False):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                status = install.main(arguments)
        return status, output.getvalue(), error.getvalue()

    def test_default_path_resolution(self):
        claude = install.default_root("claude", {"CLAUDE_CONFIG_DIR": "/tmp/c"})
        grok = install.default_root("grok", {"GROK_HOME": "/tmp/g"})
        xdg = install.default_root("opencode", {"XDG_CONFIG_HOME": "/tmp/x"})
        self.assertEqual(Path("/tmp/c/skills"), claude)
        self.assertEqual(Path("/tmp/g/skills"), grok)
        self.assertEqual(Path("/tmp/x/opencode/skills"), xdg)
        config = self.root / "opencode.json"
        config.write_text("{}", encoding="utf-8")
        self.assertEqual(
            self.root / "skills",
            install.default_root("opencode", {"OPENCODE_CONFIG": str(config)}),
        )

        self.assertEqual(
            self.root / "future" / "skills",
            install.default_root(
                "opencode", {"OPENCODE_CONFIG": str(self.root / "future" / "opencode.json")}
            ),
        )
        self.assertEqual(
            Path.home() / ".agents" / "skills", install.default_root("codex", {})
        )
        self.assertEqual(
            Path.home() / ".agents" / "skills", install.default_root("zed", {})
        )
        self.assertEqual(
            Path("/tmp/copilot/skills"),
            install.default_root("copilot", {"COPILOT_HOME": "/tmp/copilot"}),
        )
        self.assertEqual(
            Path("/tmp/qwen/skills"),
            install.default_root("qwen", {"QWEN_HOME": "/tmp/qwen"}),
        )
        self.assertEqual(
            Path("/tmp/kiro/skills"),
            install.default_root("kiro", {"KIRO_HOME": "/tmp/kiro"}),
        )
        self.assertEqual(
            Path("/tmp/kimi-code/skills"),
            install.default_root("kimi", {"KIMI_CODE_HOME": "/tmp/kimi-code"}),
        )
        self.assertEqual(
            Path.home() / ".kimi-code" / "skills",
            install.default_root("kimi", {}),
        )
        self.assertEqual(
            Path.home() / ".gemini" / "antigravity-cli" / "skills",
            install.default_root("antigravity", {}),
        )
        self.assertEqual(
            Path.home() / ".cursor" / "skills", install.default_root("cursor", {})
        )
        empty_variables = {
            "claude": "CLAUDE_CONFIG_DIR",
            "grok": "GROK_HOME",
            "copilot": "COPILOT_HOME",
            "qwen": "QWEN_HOME",
            "kiro": "KIRO_HOME",
            "kimi": "KIMI_CODE_HOME",
        }
        for target, variable in empty_variables.items():
            with self.subTest(target=target, variable=variable):
                self.assertEqual(
                    install.default_root(target, {}),
                    install.default_root(target, {variable: ""}),
                )
        self.assertEqual(
            install.default_root("opencode", {}),
            install.default_root("opencode", {"XDG_CONFIG_HOME": ""}),
        )
        self.assertEqual(
            Path.home() / ".codex" / "skills",
            install.legacy_codex_root({"CODEX_HOME": ""}),
        )

    def test_skill_names_are_derived_from_resource_manifest(self):
        manifest = {
            "skills": ["gsd-path", "gsd-path-alpha", "gsd-path-zeta"],
        }

        self.assertEqual(
            install.skill_names_for_manifest(manifest),
            ("gsd-path", "gsd-path-alpha", "gsd-path-zeta"),
        )

    def test_targets_and_local_roots_are_derived_from_resource_manifest(self):
        manifest = {
            "hosts": {
                "alpha": {"local_root": ".alpha/skills"},
                "beta": {"local_root": ".beta/skills"},
            }
        }

        self.assertEqual(install.targets_for_manifest(manifest), ("alpha", "beta"))
        self.assertEqual(
            install.local_roots_for_manifest(manifest),
            {"alpha": ".alpha/skills", "beta": ".beta/skills"},
        )

    def test_local_root_resolution_matches_manifest(self):
        project = self.root / "project"

        for target, relative in install.LOCAL_ROOTS.items():
            with self.subTest(target=target):
                self.assertEqual(project / relative, install.local_root(target, project))

        with self.assertRaisesRegex(ValueError, "unsupported target"):
            install.local_root("unknown", project)

    def test_local_install_and_update_match_node_behavior(self):
        project = self.root / "project"
        project.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(project)
            status, _, error = self.run_main(
                ["--claude", "--local", "--source-root", str(self.source)]
            )
            self.assertEqual(0, status, error)
            installed = project / ".claude" / "skills" / "gsd-path" / "SKILL.md"
            self.assertTrue(installed.is_file())

            source_skill = self.source / "skills" / "gsd-path" / "SKILL.md"
            source_skill.write_text(
                "---\nname: gsd-path\ndescription: updated\n---\nupdated\n",
                encoding="utf-8",
            )
            status, output, error = self.run_main(
                ["--update", "--local", "--source-root", str(self.source)]
            )
            self.assertEqual(0, status, error)
            self.assertIn("description: updated", installed.read_text(encoding="utf-8"))
            self.assertIn("updated", output)
            self.assertTrue((project / ".claude" / "disabled-gsd-skills").is_dir())
        finally:
            os.chdir(previous)

    def test_update_without_an_existing_install_fails_cleanly(self):
        project = self.root / "project"
        project.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(project)
            status, _, error = self.run_main(
                ["--update", "--local", "--source-root", str(self.source)]
            )
        finally:
            os.chdir(previous)

        self.assertEqual(1, status)
        self.assertIn("no existing GSD Path skills found to update", error)

    def test_all_local_install_and_update_share_agent_bundle(self):
        project = self.root / "project"
        project.mkdir()
        previous = Path.cwd()
        try:
            os.chdir(project)
            status, output, error = self.run_main(
                ["--all", "--local", "--source-root", str(self.source)]
            )
            self.assertEqual(0, status, error)
            self.assertIn("codex+antigravity+zed: installed", output)

            source_skill = self.source / "skills" / "gsd-path" / "SKILL.md"
            source_skill.write_text(
                "---\nname: gsd-path\ndescription: shared update\n---\nupdated\n",
                encoding="utf-8",
            )
            status, output, error = self.run_main(
                ["--update", "--local", "--source-root", str(self.source)]
            )
        finally:
            os.chdir(previous)

        self.assertEqual(0, status, error)
        self.assertIn("codex+antigravity+zed: updated", output)
        installed = project / ".agents" / "skills" / "gsd-path" / "SKILL.md"
        self.assertIn(
            "description: shared update", installed.read_text(encoding="utf-8")
        )
        dispatch = installed.parent / "references" / "dispatch.md"
        self.assertIn("invoke_subagent", dispatch.read_text(encoding="utf-8"))

    def test_discussion_skill_is_installed_and_invocable(self):
        self.assertIn("gsd-path-discuss", install.SKILL_NAMES)
        target = self.root / "discussion" / "skills"

        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
            ]
        )

        self.assertEqual(0, status, error)
        discussion = target / "gsd-path-discuss" / "SKILL.md"
        self.assertTrue(discussion.is_file())
        self.assertIn("/gsd-path-discuss", discussion.read_text(encoding="utf-8"))

    def test_v2_canonical_skills_are_installed_without_aliases(self):
        self.assertEqual({}, install.SKILL_ALIASES)

        target = self.root / "terminology" / "skills"
        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
            ]
        )

        self.assertEqual(0, status, error)
        for canonical in (
            "gsd-path-inspect",
            "gsd-path-define",
            "gsd-path-decide",
            "gsd-path-roadmap",
            "gsd-path-ship",
        ):
            skill = target / canonical / "SKILL.md"
            self.assertTrue(skill.is_file())
            self.assertIn(f"name: {canonical}", skill.read_text(encoding="utf-8"))

    @staticmethod
    def staged_skill_directories(staged):
        return sorted(entry.name for entry in staged.iterdir() if entry.is_dir())

    def test_all_platform_transforms(self):
        for target in (*install.TARGETS, install.SHARED_AGENT_PROFILE):
            with self.subTest(target=target):
                staged = self.root / f"staged-{target}"
                staged.mkdir()
                install.stage_target(self.source, target, staged)
                staged_skills = self.staged_skill_directories(staged)
                self.assertEqual(sorted(install.SKILL_NAMES), staged_skills)
                for name in staged_skills:
                    skill = staged / name / "SKILL.md"
                    content = skill.read_text(encoding="utf-8")
                    dispatch_path = staged / name / "references" / "dispatch.md"
                    self.assertTrue(dispatch_path.is_file(), name)
                    dispatch = dispatch_path.read_text(encoding="utf-8")
                    if target == "codex":
                        self.assertIn("$gsd-path", content, name)
                        self.assertNotIn("disable-model-invocation", content, name)
                        self.assertIn("codex dispatch for $gsd-path", dispatch, name)
                        self.assertTrue(
                            (staged / name / "agents" / "openai.yaml").is_file(), name
                        )
                    elif target == "opencode":
                        self.assertIn(
                            "Run gsd-path, gsd-path-build, and gsd-path-discuss",
                            content,
                            name,
                        )
                        self.assertNotIn("$gsd-path", content, name)
                        self.assertNotIn("/gsd-path", content, name)
                        self.assertIn("opencode dispatch for gsd-path", dispatch, name)
                        self.assertFalse((staged / name / "agents").exists(), name)
                    elif target == install.SHARED_AGENT_PROFILE:
                        self.assertIn(
                            "Run gsd-path, gsd-path-build, and gsd-path-discuss",
                            content,
                            name,
                        )
                        self.assertNotIn("$gsd-path", content, name)
                        self.assertNotIn("/gsd-path", content, name)
                        self.assertIn("shared dispatch for gsd-path", dispatch, name)
                        self.assertTrue(
                            (staged / name / "agents" / "openai.yaml").is_file(), name
                        )
                    else:
                        self.assertIn("/gsd-path", content, name)
                        self.assertNotIn("$gsd-path", content, name)
                        self.assertIn(f"{target} dispatch for /gsd-path", dispatch, name)
                        self.assertFalse((staged / name / "agents").exists(), name)
                    if target in install.EXPLICIT_ONLY_TARGETS:
                        self.assertIn("disable-model-invocation: true", content, name)
                    if target in ("opencode", install.SHARED_AGENT_PROFILE):
                        self.assertIn('opencode/autoinvoke: "false"', content, name)
                        self.assertIn('opencode/slash: "true"', content, name)

    def test_real_repo_staging_applies_real_adapter_to_every_skill(self):
        repo = Path(install.__file__).resolve().parents[1]
        cases = (
            ("claude", "claude", "/gsd-path"),
            (install.SHARED_AGENT_PROFILE, install.SHARED_AGENT_PROFILE, "gsd-path"),
        )
        for target, adapter_directory, invocation in cases:
            with self.subTest(target=target):
                staged = self.root / f"staged-real-{target}"
                staged.mkdir()
                install.stage_target(repo, target, staged)
                expected = (
                    (repo / "platforms" / adapter_directory / "dispatch.md")
                    .read_text(encoding="utf-8")
                    .replace("$gsd-path", invocation)
                )
                checked = 0
                for name in self.staged_skill_directories(staged):
                    dispatch = staged / name / "references" / "dispatch.md"
                    if not dispatch.exists():
                        continue
                    checked += 1
                    self.assertEqual(
                        expected, dispatch.read_text(encoding="utf-8"), name
                    )
                self.assertGreaterEqual(
                    checked, 2, "expected multiple dispatch-bearing skills"
                )

    def test_stage_target_stamps_version_from_package_manifest(self):
        staged = self.root / "staged-unstamped"
        staged.mkdir()
        install.stage_target(self.source, "claude", staged)
        self.assertFalse((staged / "gsd-path" / "VERSION").exists())

        (self.source / "package.json").write_text('{"version": "9.9.9"}', encoding="utf-8")
        staged = self.root / "staged-version"
        staged.mkdir()
        install.stage_target(self.source, "claude", staged)
        self.assertEqual(
            "9.9.9\n", (staged / "gsd-path" / "VERSION").read_text(encoding="utf-8")
        )

    def test_all_installs_each_target(self):
        roots = {target: self.root / target / "skills" for target in install.TARGETS}
        roots["zed"] = roots["codex"]
        arguments = ["--all", "--source-root", str(self.source)]
        for target, root in roots.items():
            arguments.extend([f"--{target}-root", str(root)])
        status, output, error = self.run_main(arguments)
        self.assertEqual(0, status, error)
        self.assertEqual(10, len(set(roots.values())))
        for root in set(roots.values()):
            self.assertEqual(set(install.SKILL_NAMES), {entry.name for entry in root.iterdir()})
        cursor_agent = roots["cursor"].parent / "agents" / install.CURSOR_AGENT_FILENAME
        self.assertTrue(
            cursor_agent.read_text(encoding="utf-8").endswith("cursor agent\n")
        )
        self.assertIn(
            f"codex+zed: installed {len(install.SKILL_NAMES)} shared skills",
            output,
        )
        self.assertIn("custom subagent", output)
        self.assertIn("OpenCode stable discovers", output)
        self.assertIn("Antigravity discovers", output)
        self.assertIn("Kiro discovers", output)

    def test_codex_dry_run_validates_resolved_shared_profile_from_real_repository(self):
        target = self.root / "real-codex" / "skills"

        status, output, error = self.run_main(
            [
                "--codex",
                "--codex-root",
                str(target),
                "--dry-run",
                "--source-root",
                str(PROJECT_ROOT),
            ]
        )

        self.assertEqual(0, status, error)
        self.assertIn("codex: would install", output)
        self.assertFalse(target.exists())

    def test_shared_agent_hosts_use_one_deployment_at_the_same_root(self):
        root = self.root / "shared" / "skills"
        plans = [
            install.TargetPlan("codex", root),
            install.TargetPlan("antigravity", root),
            install.TargetPlan("zed", root),
        ]
        deployments = install._deployment_plans(plans)
        self.assertEqual(
            [
                install.DeploymentPlan(
                    install.SHARED_AGENT_PROFILE,
                    root,
                    ("codex", "antigravity", "zed"),
                )
            ],
            deployments,
        )
        root.mkdir(parents=True)
        (root / "gsd-path-old").mkdir()

        status, output, error = self.run_main(
            [
                "--codex",
                "--antigravity",
                "--zed",
                "--codex-root",
                str(root),
                "--antigravity-root",
                str(root),
                "--zed-root",
                str(root),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(0, status, error)
        self.assertEqual(
            1,
            output.count(f"installed {len(install.SKILL_NAMES)} shared skills"),
        )
        self.assertEqual(1, output.count("backed up 1 entries"))
        self.assertTrue(
            (root.parent / "disabled-gsd-skills" / "gsd-path-old").is_dir()
        )
        content = (root / "gsd-path" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("disable-model-invocation: true", content)
        self.assertIn(
            "Run gsd-path, gsd-path-build, and gsd-path-discuss", content
        )
        self.assertTrue((root / "gsd-path" / "agents" / "openai.yaml").is_file())

    def test_distinct_codex_and_zed_roots_each_use_the_shared_profile(self):
        codex = self.root / "codex-distinct" / "skills"
        zed = self.root / "zed-distinct" / "skills"
        deployments = install._deployment_plans(
            [install.TargetPlan("codex", codex), install.TargetPlan("zed", zed)]
        )
        self.assertEqual(
            [install.SHARED_AGENT_PROFILE, install.SHARED_AGENT_PROFILE],
            [deployment.profile for deployment in deployments],
        )

    def test_unrelated_targets_cannot_share_or_overlap_roots(self):
        root = self.root / "collision"
        cases = (
            [install.TargetPlan("copilot", root), install.TargetPlan("qwen", root)],
            [
                install.TargetPlan("claude", root),
                install.TargetPlan("grok", root / "nested"),
            ],
        )
        for plans in cases:
            with self.subTest(plans=plans):
                with self.assertRaisesRegex(install.InstallerError, "share|overlap"):
                    install.install(self.source, plans)
                self.assertFalse(root.exists())

    def test_case_only_aliases_cannot_bypass_path_guards(self):
        source_alias = self.source.with_name(self.source.name.upper()) / "skills"
        case_root = self.root / "CaseRoots"
        plans = [
            install.TargetPlan("claude", case_root / "Skills"),
            install.TargetPlan("grok", case_root.with_name("caseroots") / "skills"),
        ]
        with mock.patch.object(install.sys, "platform", "darwin"):
            with self.assertRaisesRegex(
                install.InstallerError, "overlaps source repository"
            ):
                install.install(
                    self.source, [install.TargetPlan("claude", source_alias)]
                )
            with self.assertRaisesRegex(install.InstallerError, "share|overlap"):
                install.install(self.source, plans)
        self.assertTrue(
            (self.source / "skills" / "gsd-path" / "agents" / "openai.yaml").is_file()
        )
        self.assertFalse(case_root.exists())

    def test_non_shared_host_cannot_write_the_standard_shared_root(self):
        with self.assertRaisesRegex(install.InstallerError, "shared ~/.agents/skills"):
            install._deployment_plans(
                [install.TargetPlan("copilot", install.default_root("codex", {}))]
            )

    def test_cursor_subagent_is_installed_and_existing_copy_is_backed_up(self):
        root = self.root / "cursor-install" / "skills"
        agent = root.parent / "agents" / install.CURSOR_AGENT_FILENAME
        agent.parent.mkdir(parents=True)
        agent.write_text("old agent\n", encoding="utf-8")

        status, output, error = self.run_main(
            [
                "--cursor",
                "--cursor-root",
                str(root),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(0, status, error)
        self.assertIn("custom subagent", output)
        self.assertIn("cursor agent", agent.read_text(encoding="utf-8"))
        backup = root.parent / "disabled-gsd-skills"
        self.assertEqual(
            "old agent\n",
            (backup / install.CURSOR_AGENT_BACKUP_NAME).read_text(encoding="utf-8"),
        )

    def test_parser_exposes_every_target_flag(self):
        parsed = install.parser().parse_args(["--all"])
        self.assertTrue(parsed.all_targets)
        for target in install.TARGETS:
            self.assertTrue(hasattr(parsed, target))
            self.assertTrue(hasattr(parsed, f"{target}_root"))

    def test_existing_managed_entries_are_backed_up_and_unrelated_preserved(self):
        target = self.root / "codex" / "skills"
        target.mkdir(parents=True)
        for name in ("ogsd", "ogsd-old", "gsd-path", "gsd-path-old"):
            (target / name).mkdir()
            (target / name / "old.txt").write_text(name, encoding="utf-8")
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "marker").write_text("preserve", encoding="utf-8")
        (target / "ogsd-link").symlink_to(outside, target_is_directory=True)
        unrelated = target / "other-skill"
        unrelated.mkdir()
        status, output, error = self.run_main(
            ["--codex", "--codex-root", str(target), "--source-root", str(self.source)]
        )
        self.assertEqual(0, status, error)
        backup = target.parent / "disabled-gsd-skills"
        self.assertEqual(
            {"ogsd", "ogsd-old", "ogsd-link", "gsd-path", "gsd-path-old"},
            {entry.name for entry in backup.iterdir()},
        )
        self.assertTrue((backup / "ogsd-link").is_symlink())
        self.assertEqual("preserve", (outside / "marker").read_text(encoding="utf-8"))
        self.assertTrue(unrelated.is_dir())
        self.assertIn("backed up 5 entries", output)

    def test_case_variant_managed_entry_is_backed_up_before_install(self):
        target = self.root / "case-entry" / "skills"
        old = target / "GSD-PATH"
        old.mkdir(parents=True)
        (old / "marker").write_text("old", encoding="utf-8")

        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(0, status, error)
        backup = target.parent / "disabled-gsd-skills" / "GSD-PATH"
        self.assertEqual("old", (backup / "marker").read_text(encoding="utf-8"))
        self.assertTrue((target / "gsd-path" / "SKILL.md").is_file())

    def test_codex_migrates_legacy_root_and_preserves_unrelated_entries(self):
        legacy = self.root / "legacy" / "skills"
        legacy.mkdir(parents=True)
        (legacy / "gsd-path-old").mkdir()
        (legacy / "unrelated").mkdir()
        target = self.root / "new" / "skills"
        status, output, error = self.run_main(
            ["--codex", "--codex-root", str(target), "--source-root", str(self.source)]
        )
        self.assertEqual(0, status, error)
        self.assertTrue(
            (legacy.parent / "disabled-gsd-skills" / "gsd-path-old").is_dir()
        )
        self.assertTrue((legacy / "unrelated").is_dir())
        self.assertNotIn("gsd-path", {entry.name for entry in legacy.iterdir()})
        self.assertIn("codex-legacy: backed up 1 entries", output)

    def test_dry_run_makes_no_destination_changes(self):
        target = self.root / "dry" / "skills"
        project = self.root / "project"
        status, output, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
                "--project",
                str(project),
                "--dry-run",
            ]
        )
        self.assertEqual(0, status, error)
        self.assertFalse(target.exists())
        self.assertFalse(project.exists())
        self.assertIn(f"would install {len(install.SKILL_NAMES)} skills", output)
        self.assertIn(".claude/CLAUDE.md", output)

    def test_dry_run_reports_the_registered_skill_count(self):
        extra_name = "gsd-path-extra"
        shutil.copytree(
            self.source / "skills" / "gsd-path",
            self.source / "skills" / extra_name,
        )
        skill_names = (*install.SKILL_NAMES, extra_name)
        with mock.patch.object(install, "SKILL_NAMES", skill_names):
            status, output, error = self.run_main(
                [
                    "--claude",
                    "--claude-root",
                    str(self.root / "dynamic" / "skills"),
                    "--source-root",
                    str(self.source),
                    "--dry-run",
                ]
            )

        self.assertEqual(0, status, error)
        self.assertIn(f"would install {len(skill_names)} skills", output)

    def test_project_collision_fails_before_install_mutation(self):
        project = self.root / "project"
        project.mkdir()
        (project / "AGENTS.md").write_text("existing", encoding="utf-8")
        target = self.root / "claude" / "skills"
        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
                "--project",
                str(project),
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(target.exists())
        self.assertIn("already exists", error)

    def test_project_contract_created_after_validation_is_preserved(self):
        project = self.root / "project-race"
        project.mkdir()
        target = self.root / "project-race-target" / "skills"
        original = install._apply_target

        def create_contract_after_target(plan, staged, transaction):
            original(plan, staged, transaction)
            (project / "AGENTS.md").write_text("concurrent", encoding="utf-8")

        with mock.patch.object(
            install, "_apply_target", side_effect=create_contract_after_target
        ):
            with self.assertRaisesRegex(install.InstallerError, "already exists"):
                install.install(
                    self.source,
                    [install.TargetPlan("grok", target)],
                    project,
                )
        self.assertEqual(
            "concurrent", (project / "AGENTS.md").read_text(encoding="utf-8")
        )
        self.assertFalse((project / "WORKFLOW.md").exists())
        self.assertFalse(target.exists())

    def test_project_contracts_cannot_overlap_target_or_auxiliary_roots(self):
        project = self.root / "project-overlap"
        cases = (
            (
                "claude",
                project / "AGENTS.md",
                "skills root",
            ),
            (
                "cursor",
                project.parent / "skills",
                "Cursor agent root",
            ),
        )
        for target, root, message in cases:
            selected_project = project if target == "claude" else root.parent / "agents"
            with self.subTest(target=target):
                status, _, error = self.run_main(
                    [
                        f"--{target}",
                        f"--{target}-root",
                        str(root),
                        "--source-root",
                        str(self.source),
                        "--project",
                        str(selected_project),
                    ]
                )
                self.assertEqual(1, status)
                self.assertFalse(root.exists())
                self.assertIn(message, error)

    def test_claude_project_bridge_uses_imports_and_never_overwrites(self):
        project = self.root / "project"
        target = self.root / "claude" / "skills"
        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
                "--project",
                str(project),
            ]
        )
        self.assertEqual(0, status, error)
        self.assertEqual(
            install.CLAUDE_BRIDGE,
            (project / ".claude" / "CLAUDE.md").read_text(encoding="utf-8"),
        )

        second_target = self.root / "claude-2" / "skills"
        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(second_target),
                "--source-root",
                str(self.source),
                "--project",
                str(project),
            ]
        )
        self.assertEqual(1, status)
        self.assertFalse(second_target.exists())
        self.assertIn("already exists", error)

    def test_stale_sync_fails_before_mutation(self):
        install.sync_skill_resources.mismatches.return_value = [
            "stale generated resource: skills/gsd-path-build/references/dispatch.md"
        ]
        target = self.root / "codex" / "skills"
        status, _, error = self.run_main(
            ["--codex", "--codex-root", str(target), "--source-root", str(self.source)]
        )
        self.assertEqual(1, status)
        self.assertFalse(target.exists())
        self.assertIn("source resources are stale", error)

    def test_target_root_must_not_contain_or_descend_from_source(self):
        parent_alias = self.root / "parent-alias"
        parent_alias.symlink_to(self.root.parent, target_is_directory=True)
        targets = (
            self.root,
            self.source / "nested" / "skills",
            parent_alias / self.root.name,
        )
        for target in targets:
            with self.subTest(target=target):
                plan = install.TargetPlan("claude", target)
                with self.assertRaisesRegex(
                    install.InstallerError, "overlaps source repository"
                ):
                    install.install(self.source, [plan])
                self.assertTrue((self.source / "skills" / "gsd-path").is_dir())
                self.assertFalse((self.root / "disabled-gsd-skills").exists())

    def test_codex_legacy_root_cannot_overlap_source(self):
        target = self.root / "new-codex" / "skills"
        with mock.patch.dict(
            os.environ, {"CODEX_HOME": str(self.source)}, clear=False
        ):
            with self.assertRaisesRegex(
                install.InstallerError, "legacy root overlaps source repository"
            ):
                install.install(
                    self.source, [install.TargetPlan("codex", target)]
                )
        self.assertTrue((self.source / "skills" / "gsd-path").is_dir())
        self.assertFalse((self.source / "disabled-gsd-skills").exists())
        self.assertFalse(target.exists())

    def test_backup_root_cannot_overlap_another_target(self):
        first = self.root / "backup-collision" / "skills"
        first.mkdir(parents=True)
        (first / "gsd-path-old").mkdir()
        second = first.parent / "disabled-gsd-skills"
        plans = [
            install.TargetPlan("claude", first),
            install.TargetPlan("grok", second),
        ]
        with self.assertRaisesRegex(install.InstallerError, "backup overlaps"):
            install.install(self.source, plans)
        self.assertTrue((first / "gsd-path-old").is_dir())
        self.assertFalse(second.exists())

    def test_multi_target_failure_rolls_back_prior_target_and_backup(self):
        codex = self.root / "codex" / "skills"
        codex.mkdir(parents=True)
        old = codex / "gsd-path-old"
        old.mkdir()
        (old / "marker").write_text("old", encoding="utf-8")
        claude = self.root / "claude" / "skills"
        original = install._apply_target
        calls = 0

        def fail_second(plan, staged, transaction):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected failure")
            original(plan, staged, transaction)

        plans = [
            install.TargetPlan("codex", codex),
            install.TargetPlan("claude", claude),
        ]
        with mock.patch.dict(os.environ, {"CODEX_HOME": str(self.root / "legacy")}, clear=False):
            with mock.patch.object(install, "_apply_target", side_effect=fail_second):
                with self.assertRaisesRegex(install.InstallerError, "rolled back"):
                    install.install(self.source, plans)
        self.assertTrue((codex / "gsd-path-old" / "marker").is_file())
        self.assertFalse((codex / "gsd-path").exists())
        self.assertFalse((codex.parent / "disabled-gsd-skills").exists())
        self.assertFalse(claude.exists())

    def test_keyboard_interrupt_rolls_back_prior_target_and_backup(self):
        codex = self.root / "codex-interrupt" / "skills"
        codex.mkdir(parents=True)
        old = codex / "gsd-path-old"
        old.mkdir()
        (old / "marker").write_text("old", encoding="utf-8")
        claude = self.root / "claude-interrupt" / "skills"
        original = install._apply_target
        calls = 0

        def interrupt_second(plan, staged, transaction):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise KeyboardInterrupt
            original(plan, staged, transaction)

        plans = [
            install.TargetPlan("codex", codex),
            install.TargetPlan("claude", claude),
        ]
        with mock.patch.dict(
            os.environ, {"CODEX_HOME": str(self.root / "legacy")}, clear=False
        ):
            with mock.patch.object(
                install, "_apply_target", side_effect=interrupt_second
            ):
                with self.assertRaisesRegex(
                    install.InstallerError, "rolled back: interrupted"
                ):
                    install.install(self.source, plans)
        self.assertTrue((codex / "gsd-path-old" / "marker").is_file())
        self.assertFalse((codex / "gsd-path").exists())
        self.assertFalse((codex.parent / "disabled-gsd-skills").exists())
        self.assertFalse(claude.exists())

    def test_interrupt_after_backup_move_still_restores_original(self):
        target = self.root / "move-interrupt" / "skills"
        old = target / "gsd-path-old"
        old.mkdir(parents=True)
        (old / "marker").write_text("old", encoding="utf-8")
        original_replace = install.os.replace
        interrupted = False

        def move_then_interrupt(source, destination):
            nonlocal interrupted
            original_replace(source, destination)
            if not interrupted:
                interrupted = True
                raise KeyboardInterrupt

        with mock.patch.object(install.os, "replace", side_effect=move_then_interrupt):
            with self.assertRaisesRegex(
                install.InstallerError, "rolled back: interrupted"
            ):
                install.install(
                    self.source, [install.TargetPlan("claude", target)]
                )
        self.assertEqual("old", (old / "marker").read_text(encoding="utf-8"))
        self.assertFalse((target.parent / "disabled-gsd-skills").exists())

    def test_interrupt_after_directory_creation_removes_created_directories(self):
        target = self.root / "mkdir-interrupt" / "skills"
        original_mkdir = Path.mkdir
        interrupted = False

        def mkdir_then_interrupt(path, *args, **kwargs):
            nonlocal interrupted
            original_mkdir(path, *args, **kwargs)
            if path == target and not interrupted:
                interrupted = True
                raise KeyboardInterrupt

        with mock.patch.object(Path, "mkdir", new=mkdir_then_interrupt):
            with self.assertRaisesRegex(
                install.InstallerError, "rolled back: interrupted"
            ):
                install.install(
                    self.source, [install.TargetPlan("claude", target)]
                )
        self.assertFalse(target.parent.exists())

    def test_install_collision_does_not_remove_a_concurrent_destination(self):
        target = self.root / "concurrent-install" / "skills"
        destination = target / install.SKILL_NAMES[0]
        original = install._reserve_directory
        raced = False

        def concurrent_reservation(path):
            nonlocal raced
            if path == destination and not raced:
                raced = True
                path.mkdir()
                (path / "other-installer.txt").write_text(
                    "live install\n", encoding="utf-8"
                )
            original(path)

        with mock.patch.object(
            install, "_reserve_directory", side_effect=concurrent_reservation
        ):
            with self.assertRaisesRegex(install.InstallerError, "rolled back"):
                install.install(
                    self.source, [install.TargetPlan("claude", target)]
                )

        self.assertTrue(raced)
        self.assertEqual(
            (destination / "other-installer.txt").read_text(encoding="utf-8"),
            "live install\n",
        )

    def test_active_target_owner_prevents_backup_mutation(self):
        target = self.root / "owned-install" / "skills"
        existing = target / "gsd-path-old"
        existing.mkdir(parents=True)
        (existing / "marker").write_text("old\n", encoding="utf-8")
        (target.parent / ".gsd-path-install-lock").mkdir()

        with self.assertRaisesRegex(install.InstallerError, "already in progress"):
            install.install(self.source, [install.TargetPlan("claude", target)])

        self.assertEqual(
            "old\n",
            (existing / "marker").read_text(encoding="utf-8"),
        )
        self.assertFalse((target.parent / "disabled-gsd-skills").exists())

    def test_failure_restores_cursor_subagent(self):
        cursor = self.root / "cursor-rollback" / "skills"
        agent = cursor.parent / "agents" / install.CURSOR_AGENT_FILENAME
        agent.parent.mkdir(parents=True)
        agent.write_text("old cursor agent\n", encoding="utf-8")
        claude = self.root / "claude-after-cursor" / "skills"
        original = install._apply_target
        calls = 0

        def fail_second(plan, staged, transaction):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected failure")
            original(plan, staged, transaction)

        plans = [
            install.TargetPlan("cursor", cursor),
            install.TargetPlan("claude", claude),
        ]
        with mock.patch.object(install, "_apply_target", side_effect=fail_second):
            with self.assertRaisesRegex(install.InstallerError, "rolled back"):
                install.install(self.source, plans)
        self.assertEqual("old cursor agent\n", agent.read_text(encoding="utf-8"))
        self.assertFalse(cursor.exists())
        self.assertFalse((cursor.parent / "disabled-gsd-skills").exists())
        self.assertFalse(claude.exists())


    def hooks_arguments(self, project, target):
        return [
            "--claude",
            "--claude-root",
            str(target),
            "--source-root",
            str(self.source),
            "--project",
            str(project),
            "--hooks",
        ]

    def test_hooks_require_project(self):
        target = self.root / "claude" / "skills"
        status, _, error = self.run_main(
            [
                "--claude",
                "--claude-root",
                str(target),
                "--source-root",
                str(self.source),
                "--hooks",
            ]
        )
        self.assertEqual(1, status)
        self.assertIn("--hooks requires --project", error)
        self.assertFalse(target.exists())

    def test_hooks_install_guard_scripts_settings_and_git_hook(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        status, output, error = self.run_main(self.hooks_arguments(project, target))
        self.assertEqual(0, status, error)
        for name in install.GUARD_SCRIPTS:
            self.assertEqual(
                f"# {name}\n{install.GUARD_MARKER}\n",
                (project / install.HOOKS_DIRECTORY / name).read_text(encoding="utf-8"),
            )
        settings = json.loads(
            (project / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        self.assertIn("PreToolUse", settings["hooks"])
        self.assertEqual(settings["hooks"]["PreToolUse"][0]["matcher"], install.CLAUDE_MATCHER)
        self.assertIsNotNone(
            re.fullmatch(settings["hooks"]["PreToolUse"][0]["matcher"], "PowerShell")
        )
        pre_commit = project / ".git" / "hooks" / "pre-commit"
        commit_msg = project / ".git" / "hooks" / "commit-msg"
        self.assertEqual(install.pre_commit_hook("python3"), pre_commit.read_text(encoding="utf-8"))
        self.assertEqual(install.commit_msg_hook("python3"), commit_msg.read_text(encoding="utf-8"))
        self.assertTrue(os.access(commit_msg, os.X_OK))
        self.assertIn(".gsd-path/guard_hook.py", output)
        self.assertIn(".git/hooks/pre-commit", output)
        self.assertIn(".git/hooks/commit-msg", output)

    def test_hooks_install_native_codex_and_cursor_project_configs(self):
        project = self.root / "native-hooks-project"
        (project / ".git").mkdir(parents=True)
        plans = [
            install.TargetPlan("codex", self.root / "codex" / "skills"),
            install.TargetPlan("cursor", self.root / "cursor" / "skills"),
        ]
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)

        codex = json.loads(
            (project / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            'python3 "$(git rev-parse --show-toplevel)/.gsd-path/guard_hook.py"',
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )
        self.assertIn(
            ".gsd-path\\guard_hook.py",
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["commandWindows"],
        )
        cursor = json.loads(
            (project / ".cursor" / "hooks.json").read_text(encoding="utf-8")
        )
        self.assertEqual(1, cursor["version"])
        self.assertEqual(
            'python3 ".gsd-path/guard_hook.py"',
            cursor["hooks"]["preToolUse"][0]["command"],
        )
        self.assertTrue(cursor["hooks"]["preToolUse"][0]["failClosed"])

    def test_hooks_install_merges_selected_native_configs(self):
        project = self.root / "existing-native-hooks-project"
        (project / ".git").mkdir(parents=True)
        codex_path = project / ".codex" / "hooks.json"
        cursor_path = project / ".cursor" / "hooks.json"
        codex_path.parent.mkdir()
        cursor_path.parent.mkdir()
        codex_path.write_text(
            json.dumps(
                {
                    "userSetting": True,
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Write",
                                "hooks": [
                                    {"type": "command", "command": "custom-codex"}
                                ],
                            }
                        ]
                    },
                }
            )
            + "\n",
            encoding="utf-8",
        )
        cursor_path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "userSetting": True,
                    "hooks": {"preToolUse": [{"command": "custom-cursor"}]},
                }
            )
            + "\n",
            encoding="utf-8",
        )
        plans = [
            install.TargetPlan("codex", self.root / "codex" / "skills"),
            install.TargetPlan("cursor", self.root / "cursor" / "skills"),
        ]

        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)

        codex = json.loads(codex_path.read_text(encoding="utf-8"))
        self.assertTrue(codex["userSetting"])
        self.assertEqual(2, len(codex["hooks"]["PreToolUse"]))
        self.assertEqual("Write", codex["hooks"]["PreToolUse"][0]["matcher"])
        self.assertEqual(
            "custom-codex",
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )
        self.assertIn(
            "guard_hook.py",
            codex["hooks"]["PreToolUse"][1]["hooks"][0]["command"],
        )
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        self.assertTrue(cursor["userSetting"])
        self.assertEqual(2, len(cursor["hooks"]["preToolUse"]))
        self.assertEqual(
            "custom-cursor", cursor["hooks"]["preToolUse"][0]["command"]
        )
        self.assertIn(
            "guard_hook.py", cursor["hooks"]["preToolUse"][1]["command"]
        )

    def test_native_hook_commands_run_from_supported_working_directories(self):
        project = self.root / "native hooks project"
        project.mkdir()
        subprocess.run(["git", "init", "-q"], cwd=project, check=True)
        plans = [
            install.TargetPlan("codex", self.root / "codex" / "skills"),
            install.TargetPlan("cursor", self.root / "cursor" / "skills"),
        ]
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)
        guard = project / install.HOOKS_DIRECTORY / "guard_hook.py"
        guard.write_text('print("guard-ran")\n', encoding="utf-8")
        subdirectory = project / "nested"
        subdirectory.mkdir()
        codex = json.loads(
            (project / ".codex" / "hooks.json").read_text(encoding="utf-8")
        )
        codex_command = codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        cursor = json.loads(
            (project / ".cursor" / "hooks.json").read_text(encoding="utf-8")
        )
        cursor_command = cursor["hooks"]["preToolUse"][0]["command"]

        codex_result = subprocess.run(
            codex_command, cwd=subdirectory, shell=True, text=True, capture_output=True
        )
        cursor_result = subprocess.run(
            cursor_command, cwd=project, shell=True, text=True, capture_output=True
        )

        self.assertEqual(0, codex_result.returncode, codex_result.stderr)
        self.assertEqual("guard-ran", codex_result.stdout.strip())
        self.assertEqual(0, cursor_result.returncode, cursor_result.stderr)
        self.assertEqual("guard-ran", cursor_result.stdout.strip())

    def test_native_hook_install_rejects_unsafe_project_directories(self):
        for host in ("codex", "cursor"):
            with self.subTest(host=host):
                project = self.root / f"unsafe-{host}-project"
                (project / ".git").mkdir(parents=True)
                outside = self.root / f"outside-{host}"
                outside.mkdir()
                (project / f".{host}").symlink_to(outside, target_is_directory=True)
                target = self.root / host / "skills"
                with mock.patch.object(
                    install, "_detect_python_interpreter", return_value="python3"
                ):
                    with self.assertRaisesRegex(
                        install.InstallerError,
                        f"unsafe {host.title()} project directory",
                    ):
                        install.install(
                            self.source,
                            [install.TargetPlan(host, target)],
                            project=project,
                            hooks=True,
                        )
                self.assertFalse((outside / "hooks.json").exists())
                self.assertFalse(target.exists())

    def test_native_hooks_require_initialized_repository(self):
        project = self.root / "project"
        target = self.root / "claude" / "skills"
        status, _, error = self.run_main(self.hooks_arguments(project, target))
        self.assertEqual(1, status)
        self.assertRegex(error, "initialized Git repository.*selected hosts: claude")
        self.assertFalse((project / ".git").exists())
        self.assertFalse((project / ".claude" / "settings.json").exists())
        self.assertFalse(target.exists())

    def test_git_only_hooks_require_initialized_repository(self):
        project = self.root / "plain-project"
        target = self.root / "grok" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            with self.assertRaisesRegex(
                install.InstallerError,
                "initialized Git repository.*selected hosts: grok",
            ):
                install.install(
                    self.source,
                    [install.TargetPlan("grok", target)],
                    project=project,
                    hooks=True,
                )

        self.assertFalse(target.exists())
        self.assertFalse((project / "AGENTS.md").exists())

    def test_git_only_hooks_require_python_interpreter(self):
        project = self.root / "grok-project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "grok" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value=None
        ):
            with self.assertRaisesRegex(
                install.InstallerError,
                "working Python interpreter.*selected hosts: grok",
            ):
                install.install(
                    self.source,
                    [install.TargetPlan("grok", target)],
                    project=project,
                    hooks=True,
                )

        self.assertFalse(target.exists())
        self.assertFalse((project / "AGENTS.md").exists())

    def test_hooks_collision_rolls_back_cleanly(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        (project / ".claude").mkdir(parents=True)
        (project / ".claude" / "settings.json").write_text("{}", encoding="utf-8")
        target = self.root / "claude" / "skills"
        status, _, error = self.run_main(self.hooks_arguments(project, target))
        self.assertEqual(1, status)
        self.assertIn("already exists", error)
        self.assertFalse(target.exists())
        self.assertFalse((project / "AGENTS.md").exists())
        self.assertEqual(
            "{}", (project / ".claude" / "settings.json").read_text(encoding="utf-8")
        )

    def test_hooks_dry_run_lists_files_without_writing(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        status, output, error = self.run_main(
            [*self.hooks_arguments(project, target), "--dry-run"]
        )
        self.assertEqual(0, status, error)
        self.assertIn(".gsd-path/guard_hook.py", output)
        self.assertIn(".git/hooks/commit-msg", output)
        self.assertFalse(target.exists())
        self.assertFalse((project / install.HOOKS_DIRECTORY).exists())

    def test_hooks_refresh_updates_managed_guard_scripts(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        (self.source / "scripts" / "guard_hook.py").write_text(
            f"# guard v2\n{install.GUARD_MARKER}\n", encoding="utf-8"
        )
        status, output, error = self.run_main(
            [
                "--hooks-refresh",
                "--project",
                str(project),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(0, status, error)
        self.assertIn(
            "guard v2",
            (project / install.HOOKS_DIRECTORY / "guard_hook.py").read_text(
                encoding="utf-8"
            ),
        )
        self.assertTrue(target.exists())

    def test_hooks_refresh_rejects_unmanaged_guard_scripts(self):
        project = self.root / "project"
        (project / install.HOOKS_DIRECTORY).mkdir(parents=True)
        (project / install.HOOKS_DIRECTORY / "guard_hook.py").write_text(
            "custom\n", encoding="utf-8"
        )
        status, _, error = self.run_main(
            [
                "--hooks-refresh",
                "--project",
                str(project),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(1, status)
        self.assertIn("not a managed GSD Path guard script", error)

    def refresh_full_arguments(self, project):
        return [
            "--hooks-refresh-full",
            "--project",
            str(project),
            "--source-root",
            str(self.source),
        ]

    def test_hooks_refresh_full_merges_settings_preserving_user_keys(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["PreToolUse"][0]["matcher"] = "old"
        settings["permissions"] = {"allow": ["Bash(npm test)"]}
        settings["model"] = "opus"
        settings_path.write_text(json.dumps(settings) + "\n", encoding="utf-8")
        status, _, error = self.run_main(self.refresh_full_arguments(project))
        self.assertEqual(0, status, error)
        refreshed = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(
            install.CLAUDE_MATCHER, refreshed["hooks"]["PreToolUse"][0]["matcher"]
        )
        self.assertEqual({"allow": ["Bash(npm test)"]}, refreshed["permissions"])
        self.assertEqual("opus", refreshed["model"])

    def test_hooks_refresh_full_updates_native_codex_and_cursor_configs(self):
        project = self.root / "native-hooks-project"
        (project / ".git").mkdir(parents=True)
        plans = [
            install.TargetPlan("codex", self.root / "codex" / "skills"),
            install.TargetPlan("cursor", self.root / "cursor" / "skills"),
        ]
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)
        codex_path = project / ".codex" / "hooks.json"
        codex = json.loads(codex_path.read_text(encoding="utf-8"))
        codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"] = (
            'python "C:\\repo\\.gsd-path\\guard_hook.py"'
        )
        codex["hooks"]["PreToolUse"][0]["matcher"] = "Write"
        codex["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "custom-codex"}
        )
        codex["userSetting"] = True
        codex_path.write_text(json.dumps(codex) + "\n", encoding="utf-8")
        cursor_path = project / ".cursor" / "hooks.json"
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        cursor["hooks"]["preToolUse"][0]["command"] = (
            'python "C:\\repo\\.gsd-path\\guard_hook.py"'
        )
        cursor["userSetting"] = True
        cursor_path.write_text(json.dumps(cursor) + "\n", encoding="utf-8")

        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, _, error = self.run_main(self.refresh_full_arguments(project))

        self.assertEqual(0, status, error)
        refreshed_codex = json.loads(codex_path.read_text(encoding="utf-8"))
        self.assertEqual(
            'python3 "$(git rev-parse --show-toplevel)/.gsd-path/guard_hook.py"',
            refreshed_codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )
        self.assertTrue(refreshed_codex["userSetting"])
        self.assertEqual(2, len(refreshed_codex["hooks"]["PreToolUse"]))
        self.assertEqual(1, len(refreshed_codex["hooks"]["PreToolUse"][0]["hooks"]))
        self.assertEqual(
            "Write", refreshed_codex["hooks"]["PreToolUse"][1]["matcher"]
        )
        self.assertEqual(
            "custom-codex",
            refreshed_codex["hooks"]["PreToolUse"][1]["hooks"][0]["command"],
        )
        refreshed_cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        self.assertEqual(
            'python3 ".gsd-path/guard_hook.py"',
            refreshed_cursor["hooks"]["preToolUse"][0]["command"],
        )
        self.assertTrue(refreshed_cursor["hooks"]["preToolUse"][0]["failClosed"])
        self.assertTrue(refreshed_cursor["userSetting"])
        self.assertEqual(1, len(refreshed_cursor["hooks"]["preToolUse"]))

    def test_hooks_refresh_full_creates_selected_missing_native_configs(self):
        project = self.root / "existing-project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))

        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, _, error = self.run_main(
                [*self.refresh_full_arguments(project), "--codex", "--cursor"]
            )

        self.assertEqual(0, status, error)
        self.assertTrue((project / ".codex" / "hooks.json").is_file())
        self.assertTrue((project / ".cursor" / "hooks.json").is_file())
        self.assertEqual(
            "agents\n", (project / "AGENTS.md").read_text(encoding="utf-8")
        )

    def test_hooks_refresh_full_merges_selected_foreign_native_configs(self):
        project = self.root / "foreign-native-project"
        (project / ".git").mkdir(parents=True)
        self.run_main(self.hooks_arguments(project, self.root / "claude" / "skills"))
        codex_path = project / ".codex" / "hooks.json"
        cursor_path = project / ".cursor" / "hooks.json"
        codex_path.parent.mkdir()
        cursor_path.parent.mkdir()
        codex_path.write_text(
            json.dumps(
                {
                    "custom": "codex",
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": "Custom",
                                "hooks": [{"type": "command", "command": "custom-codex"}],
                            }
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )
        cursor_path.write_text(
            json.dumps(
                {
                    "custom": "cursor",
                    "hooks": {
                        "preToolUse": [
                            {"matcher": "Custom", "command": "custom-cursor"}
                        ]
                    },
                }
            ),
            encoding="utf-8",
        )

        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, _, error = self.run_main(
                [*self.refresh_full_arguments(project), "--codex", "--cursor"]
            )

        self.assertEqual(0, status, error)
        codex = json.loads(codex_path.read_text(encoding="utf-8"))
        cursor = json.loads(cursor_path.read_text(encoding="utf-8"))
        self.assertEqual("codex", codex["custom"])
        self.assertEqual(
            "custom-codex",
            codex["hooks"]["PreToolUse"][0]["hooks"][0]["command"],
        )
        self.assertEqual(2, len(codex["hooks"]["PreToolUse"]))
        self.assertEqual("cursor", cursor["custom"])
        self.assertEqual(
            "custom-cursor", cursor["hooks"]["preToolUse"][0]["command"]
        )
        self.assertEqual(2, len(cursor["hooks"]["preToolUse"]))

    def test_hooks_refresh_full_rejects_unselected_foreign_native_config(self):
        project = self.root / "unselected-foreign-project"
        (project / ".git").mkdir(parents=True)
        self.run_main(self.hooks_arguments(project, self.root / "claude" / "skills"))
        settings = project / ".codex" / "hooks.json"
        settings.parent.mkdir()
        original = (
            json.dumps(
                {
                    "hooks": {
                        "PreToolUse": [
                            {
                                "matcher": ".*",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": "echo .gsd-path/guard_hook.py",
                                    }
                                ],
                            }
                        ]
                    }
                }
            )
            + "\n"
        )
        settings.write_text(original, encoding="utf-8")

        status, _, error = self.run_main(self.refresh_full_arguments(project))

        self.assertEqual(1, status)
        self.assertIn("not a managed GSD Path hook settings file", error)
        self.assertEqual(original, settings.read_text(encoding="utf-8"))

    def test_hooks_refresh_full_does_not_follow_legacy_temporary_symlink(self):
        project = self.root / "temporary-symlink-project"
        (project / ".git").mkdir(parents=True)
        plans = [install.TargetPlan("codex", self.root / "codex" / "skills")]
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)
        outside = self.root / "outside-hooks.json"
        outside.write_text("outside\n", encoding="utf-8")
        legacy_temporary = project / ".codex" / ".hooks.json.gsd-path-tmp"
        legacy_temporary.symlink_to(outside)

        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, _, error = self.run_main(
                [*self.refresh_full_arguments(project), "--codex"]
            )

        self.assertEqual(0, status, error)
        self.assertEqual("outside\n", outside.read_text(encoding="utf-8"))
        self.assertTrue(legacy_temporary.is_symlink())

    def test_hooks_refresh_full_rejects_symlinked_native_parent(self):
        project = self.root / "symlink-parent-project"
        (project / ".git").mkdir(parents=True)
        plans = [install.TargetPlan("codex", self.root / "codex" / "skills")]
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            install.install(self.source, plans, project=project, hooks=True)
        outside = self.root / "outside-codex"
        (project / ".codex").rename(outside)
        (project / ".codex").symlink_to(outside, target_is_directory=True)
        before = (outside / "hooks.json").read_text(encoding="utf-8")

        status, _, error = self.run_main(self.refresh_full_arguments(project))

        self.assertEqual(1, status)
        self.assertIn("symlink", error)
        self.assertEqual(
            before, (outside / "hooks.json").read_text(encoding="utf-8")
        )

    def test_hooks_refresh_full_rejects_malformed_managed_settings(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        settings_path.write_text("{ guard_hook.py .gsd-path\n", encoding="utf-8")
        status, _, error = self.run_main(self.refresh_full_arguments(project))
        self.assertEqual(1, status)
        self.assertIn("not valid JSON", error)
        self.assertEqual(
            "{ guard_hook.py .gsd-path\n", settings_path.read_text(encoding="utf-8")
        )

    def test_hooks_refresh_full_recreates_missing_git_hooks_and_modes(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        pre_commit = project / ".git" / "hooks" / "pre-commit"
        commit_msg = project / ".git" / "hooks" / "commit-msg"
        pre_commit.unlink()
        commit_msg.chmod(0o644)
        status, _, error = self.run_main(self.refresh_full_arguments(project))
        self.assertEqual(0, status, error)
        self.assertEqual(
            install.pre_commit_hook("python3"), pre_commit.read_text(encoding="utf-8")
        )
        self.assertTrue(os.access(pre_commit, os.X_OK))
        self.assertTrue(os.access(commit_msg, os.X_OK))

    def test_hooks_refresh_full_rejects_symlinked_settings(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        outside = self.root / "outside-settings.json"
        settings_path.rename(outside)
        settings_path.symlink_to(outside)
        before = outside.read_text(encoding="utf-8")
        status, _, error = self.run_main(self.refresh_full_arguments(project))
        self.assertEqual(1, status)
        self.assertIn("symlink", error)
        self.assertEqual(before, outside.read_text(encoding="utf-8"))

    def run_git(self, *args):
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True, check=False
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_hooks_install_into_core_hookspath_directory(self):
        project = self.root / "hookspath-project"
        project.mkdir()
        self.run_git("init", "-q", str(project))
        self.run_git("-C", str(project), "config", "core.hooksPath", ".husky")
        target = self.root / "claude" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, output, error = self.run_main(
                self.hooks_arguments(project, target)
            )
        self.assertEqual(0, status, error)
        self.assertEqual(
            install.pre_commit_hook("python3"),
            (project / ".husky" / "pre-commit").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            install.commit_msg_hook("python3"),
            (project / ".husky" / "commit-msg").read_text(encoding="utf-8"),
        )
        self.assertFalse((project / ".git" / "hooks" / "pre-commit").exists())
        self.assertIn(".husky/pre-commit", output)

    def test_hooks_reject_git_file_that_cannot_be_resolved(self):
        project = self.root / "gitfile-project"
        project.mkdir()
        (project / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
        target = self.root / "claude" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            with mock.patch.object(
                install, "_resolve_git_hooks_path", return_value=None
            ):
                status, _, error = self.run_main(
                    self.hooks_arguments(project, target)
                )
        self.assertEqual(1, status)
        self.assertRegex(error, "initialized Git repository.*selected hosts: claude")
        self.assertFalse((project / install.HOOKS_DIRECTORY).exists())
        self.assertFalse((project / ".claude" / "settings.json").exists())
        self.assertFalse(target.exists())

    def test_hooks_refresh_full_preserves_user_hook_events_and_entries(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["PreToolUse"][0]["matcher"] = "Write"
        settings["hooks"]["PreToolUse"][0]["label"] = "user-scope"
        settings["hooks"]["PreToolUse"][0]["hooks"].append(
            {"type": "command", "command": "echo nested"}
        )
        user_entry = {
            "matcher": "WebFetch",
            "hooks": [{"type": "command", "command": "echo user"}],
        }
        settings["hooks"]["PreToolUse"].append(user_entry)
        stop_entry = [{"hooks": [{"type": "command", "command": "echo done"}]}]
        settings["hooks"]["Stop"] = stop_entry
        settings_path.write_text(json.dumps(settings) + "\n", encoding="utf-8")
        status, _, error = self.run_main(self.refresh_full_arguments(project))
        self.assertEqual(0, status, error)
        refreshed = json.loads(settings_path.read_text(encoding="utf-8"))
        self.assertEqual(stop_entry, refreshed["hooks"]["Stop"])
        self.assertEqual(3, len(refreshed["hooks"]["PreToolUse"]))
        self.assertEqual(
            install.CLAUDE_MATCHER, refreshed["hooks"]["PreToolUse"][0]["matcher"]
        )
        self.assertEqual(1, len(refreshed["hooks"]["PreToolUse"][0]["hooks"]))
        self.assertEqual(
            {
                "matcher": "Write",
                "label": "user-scope",
                "hooks": [{"type": "command", "command": "echo nested"}],
            },
            refreshed["hooks"]["PreToolUse"][1],
        )
        self.assertEqual(user_entry, refreshed["hooks"]["PreToolUse"][2])

    def test_emitted_hooks_use_probed_interpreter_token(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="pythonX"
        ):
            status, _, error = self.run_main(self.hooks_arguments(project, target))
        self.assertEqual(0, status, error)
        pre_commit = (project / ".git" / "hooks" / "pre-commit").read_text(
            encoding="utf-8"
        )
        self.assertIn('exec pythonX "', pre_commit)
        settings = json.loads(
            (project / ".claude" / "settings.json").read_text(encoding="utf-8")
        )
        command = settings["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        self.assertTrue(command.startswith('pythonX "'), command)

    def test_native_hook_install_requires_interpreter(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value=None
        ):
            status, _, error = self.run_main(
                self.hooks_arguments(project, target)
            )
        self.assertEqual(1, status)
        self.assertRegex(error, "working Python interpreter.*selected hosts: claude")
        self.assertFalse((project / install.HOOKS_DIRECTORY).exists())
        self.assertFalse((project / ".claude" / "settings.json").exists())
        self.assertFalse((project / ".git" / "hooks" / "pre-commit").exists())
        self.assertFalse((project / "AGENTS.md").exists())

    def test_hooks_refresh_full_rejects_before_writes_without_interpreter(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        settings_before = settings_path.read_text(encoding="utf-8")
        pre_commit = project / ".git" / "hooks" / "pre-commit"
        hook_before = pre_commit.read_text(encoding="utf-8")
        (self.source / "scripts" / "guard_hook.py").write_text(
            f"# guard v2\n{install.GUARD_MARKER}\n", encoding="utf-8"
        )
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value=None
        ):
            status, _, error = self.run_main(
                self.refresh_full_arguments(project)
            )
        self.assertEqual(1, status)
        self.assertIn("working Python interpreter", error)
        self.assertNotIn(
            "guard v2",
            (project / install.HOOKS_DIRECTORY / "guard_hook.py").read_text(encoding="utf-8"),
        )
        self.assertEqual(settings_before, settings_path.read_text(encoding="utf-8"))
        self.assertEqual(hook_before, pre_commit.read_text(encoding="utf-8"))

    def test_selected_full_refresh_requires_repository_before_writes(self):
        project = self.root / "plain-refresh-project"
        managed = project / install.HOOKS_DIRECTORY
        managed.mkdir(parents=True)
        for name in install.GUARD_SCRIPTS:
            (managed / name).write_text(
                f"old\n{install.GUARD_MARKER}\n", encoding="utf-8"
            )
        before = (managed / "guard_hook.py").read_text(encoding="utf-8")
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value="python3"
        ):
            status, _, error = self.run_main(
                [
                    "--hooks-refresh-full",
                    "--grok",
                    "--project",
                    str(project),
                    "--source-root",
                    str(self.source),
                ]
            )
        self.assertEqual(1, status)
        self.assertIn("initialized Git repository", error)
        self.assertEqual(before, (managed / "guard_hook.py").read_text(encoding="utf-8"))

    def test_hooks_refresh_dry_run_never_probes_interpreter(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        with mock.patch.object(
            install,
            "_detect_python_interpreter",
            side_effect=AssertionError("dry-run refresh must not probe"),
        ):
            status, _, error = self.run_main(
                [*self.refresh_full_arguments(project), "--dry-run"]
            )
        self.assertEqual(0, status, error)

    def test_hooks_refresh_rejects_non_utf8_guard_script_without_traceback(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        (project / install.HOOKS_DIRECTORY / "guard_hook.py").write_bytes(
            b"\xff\xfe binary\n"
        )
        status, _, error = self.run_main(
            [
                "--hooks-refresh",
                "--project",
                str(project),
                "--source-root",
                str(self.source),
            ]
        )
        self.assertEqual(1, status)
        self.assertIn("not a managed GSD Path guard script", error)
        self.assertNotIn("Traceback", error)


if __name__ == "__main__":
    unittest.main()
