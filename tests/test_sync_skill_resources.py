import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class SyncSkillResourcesTests(unittest.TestCase):
    def run_sync(self, root: Path, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(root / "scripts" / "sync_skill_resources.py"), "--root", str(root), *args],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_sync_repairs_missing_and_corrupt_phase_resources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bundle"
            shutil.copytree(
                PROJECT_ROOT,
                root,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )

            generated = root / "skills" / "gsd-path-build" / "references" / "coder.md"
            if generated.exists():
                generated.unlink()
            discussion_template = (
                root / "skills" / "gsd-path-discuss" / "templates" / "dialogue.md"
            )
            discussion_template.unlink()
            bundled_contract = root / "skills" / "gsd-path" / "INSPECT.md"
            inspect_resource = (
                root / "skills" / "gsd-path-inspect" / "templates" / "codebase.md"
            )
            bundled_contract.unlink()
            inspect_resource.write_text("stale inspect resource\n")

            missing = self.run_sync(root, "--check")
            self.assertNotEqual(missing.returncode, 0)

            sync = self.run_sync(root)
            self.assertEqual(sync.returncode, 0, sync.stderr)
            self.assertTrue(generated.is_file())
            self.assertEqual(
                bundled_contract.read_bytes(),
                (root / "skills" / "gsd-path-inspect" / "SKILL.md").read_bytes(),
            )
            self.assertEqual(
                inspect_resource.read_bytes(),
                (root / "skills" / "gsd-path" / "templates" / "codebase.md").read_bytes(),
            )
            self.assertEqual(
                discussion_template.read_bytes(),
                (root / "skills" / "gsd-path" / "templates" / "dialogue.md").read_bytes(),
            )

            clean = self.run_sync(root, "--check")
            self.assertEqual(clean.returncode, 0, clean.stderr)

            canonical_dispatch = (
                root / "skills" / "gsd-path" / "references" / "dispatch.md"
            )
            shared_dispatch = root / "platforms" / "shared-agents" / "dispatch.md"
            canonical_dispatch.write_text("stale shared dispatch\n")
            stale_shared = self.run_sync(root, "--check")
            self.assertNotEqual(stale_shared.returncode, 0)
            repaired_shared = self.run_sync(root)
            self.assertEqual(repaired_shared.returncode, 0, repaired_shared.stderr)
            self.assertEqual(shared_dispatch.read_bytes(), canonical_dispatch.read_bytes())

            generated.write_text("corrupt\n")
            corrupt = self.run_sync(root, "--check")
            self.assertNotEqual(corrupt.returncode, 0)

            generated.write_bytes((PROJECT_ROOT / "skills" / "gsd-path" / "references" / "coder.md").read_bytes())
            junk = root / "skills" / "gsd-path-build" / ".DS_Store"
            junk.write_bytes(b"finder metadata")
            junk_check = self.run_sync(root, "--check")
            self.assertNotEqual(junk_check.returncode, 0)
            self.assertIn("unexpected package metadata", junk_check.stderr)

            repaired = self.run_sync(root)
            self.assertEqual(repaired.returncode, 0, repaired.stderr)
            self.assertFalse(junk.exists())
            final_check = self.run_sync(root, "--check")
            self.assertEqual(final_check.returncode, 0, final_check.stderr)

    def test_sync_warns_on_newer_divergent_generated_resource(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory) / "bundle"
            shutil.copytree(
                PROJECT_ROOT,
                root,
                ignore=shutil.ignore_patterns(".git", "__pycache__"),
            )

            canonical = root / "skills" / "gsd-path" / "references" / "coder.md"
            generated = root / "skills" / "gsd-path-build" / "references" / "coder.md"
            generated.write_text("edited the generated copy by mistake\n")

            check = self.run_sync(root, "--check")
            self.assertNotEqual(check.returncode, 0)
            self.assertIn("wrong-direction edit", check.stderr)
            self.assertIn("gsd-path-build/references/coder.md", check.stderr)

            sync = self.run_sync(root)
            self.assertEqual(sync.returncode, 0, sync.stderr)
            self.assertIn("wrong-direction edit", sync.stderr)
            self.assertEqual(generated.read_bytes(), canonical.read_bytes())

            clean = self.run_sync(root, "--check")
            self.assertEqual(clean.returncode, 0, clean.stderr)

            generated.write_text("stale but older\n")
            old = canonical.stat().st_mtime - 10
            os.utime(generated, (old, old))
            stale = self.run_sync(root, "--check")
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("stale generated resource", stale.stderr)
            self.assertNotIn("wrong-direction edit", stale.stderr)

    def test_distribution_is_self_contained_and_explicit_only(self) -> None:
        skill_directories = sorted((PROJECT_ROOT / "skills").glob("gsd-path*"))
        self.assertEqual(len(skill_directories), 12)

        link_pattern = re.compile(r"\[[^]]+\]\(([^)#]+)(?:#[^)]*)?\)")
        for skill_directory in skill_directories:
            skill_text = (skill_directory / "SKILL.md").read_text()
            self.assertNotIn("../gsd-path/", skill_text, skill_directory.name)
            self.assertIn("Use only when", skill_text, skill_directory.name)
            for codex_only_term in (
                "Codex dispatch contract",
                "agent_type:",
                "fork_turns",
                "task_name:",
                "built-in `worker`",
                "built-in `default`",
            ):
                self.assertNotIn(codex_only_term, skill_text, skill_directory.name)

            openai_yaml = (skill_directory / "agents" / "openai.yaml").read_text()
            self.assertIn("allow_implicit_invocation: false", openai_yaml, skill_directory.name)

            for linked_path in link_pattern.findall(skill_text):
                if "://" in linked_path or linked_path.startswith("#"):
                    continue
                target = (skill_directory / linked_path).resolve()
                self.assertTrue(target.is_file(), f"missing {linked_path} from {skill_directory.name}")
                self.assertTrue(
                    target.is_relative_to(skill_directory.resolve()),
                    f"link escapes {skill_directory.name}: {linked_path}",
                )

        state_template = (PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "state.md").read_text()
        self.assertIn("pipeline: gsd-path/v2", state_template)
        self.assertIn("milestone: null", state_template)
        self.assertIn("branch: null", state_template)
        self.assertIn("archive: null", state_template)
        task_template = (PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "task.md").read_text()
        self.assertIn("base: null", task_template)
        self.assertIn("worktree: null", task_template)
        self.assertIn("task_branch: null", task_template)
        final_review = (
            PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "final-review.md"
        ).read_text()
        gap_review = (
            PROJECT_ROOT / "skills" / "gsd-path" / "templates" / "gap-review.md"
        ).read_text()
        self.assertIn("Reviewed HEAD: <full SHA>", final_review)
        self.assertIn("Reviewed HEAD: <full SHA>", gap_review)

        readme = (PROJECT_ROOT / "README.md").read_text()
        self.assertNotIn("cp -n AGENTS.md WORKFLOW.md", readme)
        for contract in (
            "BUILD.md",
            "DECIDE.md",
            "DEFINE.md",
            "DOCS-AUDIT.md",
            "INSPECT.md",
            "PLAN.md",
            "RESEARCH.md",
            "ROADMAP.md",
            "SHIP.md",
        ):
            self.assertTrue((PROJECT_ROOT / "skills" / "gsd-path" / contract).is_file(), contract)

        for removed in ("gsd-path-onboard", "gsd-path-grill", "gsd-path-synthesize", "gsd-path-review"):
            self.assertFalse((PROJECT_ROOT / "skills" / removed).exists())

        adapters = {
            "claude": "Claude Code's `Agent` tool",
            "grok": "Grok's `spawn_subagent` tool",
            "opencode": "OpenCode",
            "copilot": "Copilot CLI's `task` tool",
            "qwen": "Qwen Code's `agent` tool",
            "antigravity": "Antigravity's `invoke_subagent` tool",
            "cursor": "custom `gsd-path` subagent",
            "kiro": "default general-purpose subagent",
            "shared-agents": "Shared Agent Skills",
        }
        # Codex and Zed deploy the shared-agents profile (see deploymentPlans in
        # scripts/install.mjs and scripts/install.py); they have no per-platform
        # adapter of their own.
        for shared_profile_runtime in ("codex", "zed"):
            self.assertFalse(
                (PROJECT_ROOT / "platforms" / shared_profile_runtime).exists(),
                shared_profile_runtime,
            )
        for runtime, required_text in adapters.items():
            adapter = PROJECT_ROOT / "platforms" / runtime / "dispatch.md"
            self.assertTrue(adapter.is_file(), runtime)
            adapter_text = adapter.read_text()
            self.assertIn(required_text, adapter_text, runtime)
            self.assertIn("inspect_codebase", adapter_text, runtime)
            self.assertIn("inspect_docs", adapter_text, runtime)
            self.assertIn("`decide`", adapter_text, runtime)
            self.assertNotIn("onboard_codebase", adapter_text, runtime)
            self.assertNotIn("onboard_docs", adapter_text, runtime)
        claude_adapter = (
            PROJECT_ROOT / "platforms" / "claude" / "dispatch.md"
        ).read_text()
        self.assertNotIn("SendMessage", claude_adapter)
        cursor_agent = PROJECT_ROOT / "platforms" / "cursor" / "agent.md"
        self.assertTrue(cursor_agent.is_file())
        self.assertIn("model: inherit", cursor_agent.read_text())
        self.assertEqual(
            (PROJECT_ROOT / "platforms" / "shared-agents" / "dispatch.md").read_bytes(),
            (PROJECT_ROOT / "skills" / "gsd-path" / "references" / "dispatch.md").read_bytes(),
        )

    def test_every_skill_can_run_its_bundled_pending_discussion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            repo = Path(temporary_directory)
            project = repo / ".project"
            project.mkdir()
            (project / "STATE.md").write_text(
                """---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: plan
status: active
branch: main
archive: null
---
""",
                encoding="utf-8",
            )

            for skill_directory in sorted((PROJECT_ROOT / "skills").glob("gsd-path*")):
                script = skill_directory / "scripts" / "discussion_records.py"
                result = subprocess.run(
                    [sys.executable, str(script), "pending", "--repo", str(repo)],
                    cwd=repo,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, f"{skill_directory.name}: {result.stderr}")
                self.assertEqual({"pending": []}, json.loads(result.stdout), skill_directory.name)

    def test_shared_agent_dispatch_has_unambiguous_current_runtime_branches(self) -> None:
        dispatch = (PROJECT_ROOT / "platforms" / "shared-agents" / "dispatch.md").read_text()

        for required_text in (
            "`spawn_subagent` tool",
            "`subagent_type: general-purpose`",
            "`capability_mode: all`",
            "`resume_from`",
            "`background: true`",
            "`wait_commands_or_subagents`",
            "`Task` tool advertising the built-in `general` subagent",
            "OpenCode v2 host exposes the renamed `subagent`",
            "fresh `general` child",
            "`spawn_agent` tool exposing",
            "`spawn_agent` tool without",
            "custom `gsd-path` subagent",
            "`task` tool advertising the `general-purpose` child",
            "use exactly one matching branch",
            "If the tool schema is ambiguous",
        ):
            self.assertIn(required_text, dispatch)
        normalized = re.sub(r"\s+", " ", dispatch)
        self.assertIn(
            "`high` for the portable `heavy` tier and `low` for the portable `light` tier",
            normalized,
        )


if __name__ == "__main__":
    unittest.main()
