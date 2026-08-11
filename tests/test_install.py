import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import install


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
            "shared dispatch for $gsd-path\n", encoding="utf-8"
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

    def tearDown(self):
        self.sync_patch.stop()
        self.temporary.cleanup()

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

    def test_all_platform_transforms(self):
        for target in install.TARGETS:
            with self.subTest(target=target):
                staged = self.root / f"staged-{target}"
                staged.mkdir()
                install.stage_target(self.source, target, staged)
                skill = staged / "gsd-path" / "SKILL.md"
                content = skill.read_text(encoding="utf-8")
                dispatch = (staged / "gsd-path" / "references" / "dispatch.md").read_text(
                    encoding="utf-8"
                )
                if target == "codex":
                    self.assertIn("$gsd-path", content)
                    self.assertNotIn("disable-model-invocation", content)
                    self.assertIn("codex dispatch for $gsd-path", dispatch)
                    self.assertTrue((staged / "gsd-path" / "agents" / "openai.yaml").is_file())
                elif target == "opencode":
                    self.assertIn(
                        "Run gsd-path, gsd-path-build, and gsd-path-discuss", content
                    )
                    self.assertNotIn("$gsd-path", content)
                    self.assertNotIn("/gsd-path", content)
                    self.assertIn("opencode dispatch for gsd-path", dispatch)
                    self.assertFalse((staged / "gsd-path" / "agents").exists())
                else:
                    self.assertIn("/gsd-path", content)
                    self.assertNotIn("$gsd-path", content)
                    self.assertIn(f"{target} dispatch for /gsd-path", dispatch)
                    self.assertFalse((staged / "gsd-path" / "agents").exists())
                if target in install.EXPLICIT_ONLY_TARGETS:
                    self.assertIn("disable-model-invocation: true", content)
                if target == "opencode":
                    self.assertIn('opencode/autoinvoke: "false"', content)
                    self.assertIn('opencode/slash: "true"', content)

        staged = self.root / "staged-shared"
        staged.mkdir()
        install.stage_target(self.source, install.SHARED_AGENT_PROFILE, staged)
        content = (staged / "gsd-path" / "SKILL.md").read_text(encoding="utf-8")
        dispatch = (
            staged / "gsd-path" / "references" / "dispatch.md"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "Run gsd-path, gsd-path-build, and gsd-path-discuss", content
        )
        self.assertNotIn("$gsd-path", content)
        self.assertNotIn("/gsd-path", content)
        self.assertIn("disable-model-invocation: true", content)
        self.assertIn('opencode/autoinvoke: "false"', content)
        self.assertIn('opencode/slash: "true"', content)
        self.assertIn("shared dispatch for gsd-path", dispatch)
        self.assertTrue((staged / "gsd-path" / "agents" / "openai.yaml").is_file())

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

    def test_codex_and_zed_share_one_deployment_at_the_same_root(self):
        root = self.root / "shared" / "skills"
        plans = [
            install.TargetPlan("codex", root),
            install.TargetPlan("zed", root),
        ]
        deployments = install._deployment_plans(plans)
        self.assertEqual(
            [
                install.DeploymentPlan(
                    install.SHARED_AGENT_PROFILE, root, ("codex", "zed")
                )
            ],
            deployments,
        )
        root.mkdir(parents=True)
        (root / "gsd-path-old").mkdir()

        status, output, error = self.run_main(
            [
                "--codex",
                "--zed",
                "--codex-root",
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
        pre_commit = project / ".git" / "hooks" / "pre-commit"
        commit_msg = project / ".git" / "hooks" / "commit-msg"
        self.assertEqual(install.PRE_COMMIT_HOOK, pre_commit.read_text(encoding="utf-8"))
        self.assertEqual(install.COMMIT_MSG_HOOK, commit_msg.read_text(encoding="utf-8"))
        self.assertTrue(os.access(commit_msg, os.X_OK))
        self.assertIn(".gsd-path/guard_hook.py", output)
        self.assertIn(".git/hooks/pre-commit", output)
        self.assertIn(".git/hooks/commit-msg", output)

    def test_hooks_skip_git_hook_without_repository(self):
        project = self.root / "project"
        target = self.root / "claude" / "skills"
        status, output, error = self.run_main(self.hooks_arguments(project, target))
        self.assertEqual(0, status, error)
        self.assertFalse((project / ".git").exists())
        self.assertNotIn("commit-msg", output)
        self.assertTrue((project / ".claude" / "settings.json").is_file())

    def test_hooks_collision_rolls_back_cleanly(self):
        project = self.root / "project"
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
            install.PRE_COMMIT_HOOK, pre_commit.read_text(encoding="utf-8")
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
            install.PRE_COMMIT_HOOK,
            (project / ".husky" / "pre-commit").read_text(encoding="utf-8"),
        )
        self.assertEqual(
            install.COMMIT_MSG_HOOK,
            (project / ".husky" / "commit-msg").read_text(encoding="utf-8"),
        )
        self.assertFalse((project / ".git" / "hooks" / "pre-commit").exists())
        self.assertIn(".husky/pre-commit", output)

    def test_hooks_report_cleanly_when_git_file_cannot_be_resolved(self):
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
                status, output, error = self.run_main(
                    self.hooks_arguments(project, target)
                )
        self.assertEqual(0, status, error)
        self.assertIn("could not resolve the git hooks directory", output)
        self.assertNotIn("pre-commit", output)
        self.assertTrue(
            (project / install.HOOKS_DIRECTORY / "guard_hook.py").is_file()
        )
        self.assertTrue((project / ".claude" / "settings.json").is_file())

    def test_hooks_refresh_full_preserves_user_hook_events_and_entries(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        self.run_main(self.hooks_arguments(project, target))
        settings_path = project / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["hooks"]["PreToolUse"][0]["matcher"] = "old"
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
        self.assertEqual(2, len(refreshed["hooks"]["PreToolUse"]))
        self.assertEqual(
            install.CLAUDE_MATCHER, refreshed["hooks"]["PreToolUse"][0]["matcher"]
        )
        self.assertEqual(user_entry, refreshed["hooks"]["PreToolUse"][1])

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

    def test_hook_install_is_skipped_with_note_when_no_interpreter_works(self):
        project = self.root / "project"
        (project / ".git").mkdir(parents=True)
        target = self.root / "claude" / "skills"
        with mock.patch.object(
            install, "_detect_python_interpreter", return_value=None
        ):
            status, output, error = self.run_main(
                self.hooks_arguments(project, target)
            )
        self.assertEqual(0, status, error)
        self.assertIn("no working python3 or python interpreter", output)
        self.assertFalse((project / install.HOOKS_DIRECTORY).exists())
        self.assertFalse((project / ".claude" / "settings.json").exists())
        self.assertFalse((project / ".git" / "hooks" / "pre-commit").exists())
        self.assertTrue((project / "AGENTS.md").is_file())

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
