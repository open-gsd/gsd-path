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

            missing = self.run_sync(root, "--check")
            self.assertNotEqual(missing.returncode, 0)

            sync = self.run_sync(root)
            self.assertEqual(sync.returncode, 0, sync.stderr)
            self.assertTrue(generated.is_file())

            clean = self.run_sync(root, "--check")
            self.assertEqual(clean.returncode, 0, clean.stderr)

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

    def test_distribution_is_self_contained_and_explicit_only(self) -> None:
        skill_directories = sorted((PROJECT_ROOT / "skills").glob("gsd-path*"))
        self.assertEqual(len(skill_directories), 9)

        link_pattern = re.compile(r"\[[^]]+\]\(([^)#]+)(?:#[^)]*)?\)")
        for skill_directory in skill_directories:
            skill_text = (skill_directory / "SKILL.md").read_text()
            self.assertNotIn("../gsd-path/", skill_text, skill_directory.name)
            self.assertIn("Use only when", skill_text, skill_directory.name)
            if skill_directory.name != "gsd-path":
                self.assertIn(
                    "caller handoff, not permission to trigger an explicit-only skill",
                    skill_text,
                    skill_directory.name,
                )

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
        self.assertIn("pipeline: gsd-path/v1", state_template)
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

        build_contract = (PROJECT_ROOT / "skills" / "gsd-path-build" / "SKILL.md").read_text()
        self.assertIn("On entry from `plan/done`, set STATE", build_contract)
        self.assertIn("`build/active`, append `build started`", build_contract)
        self.assertIn("`build/done`", build_contract)
        self.assertIn("retry never reuses a rejected dirty worktree", build_contract)
        plan_contract = (PROJECT_ROOT / "skills" / "gsd-path-plan" / "SKILL.md").read_text()
        self.assertIn("`build/done` is", plan_contract)
        self.assertIn("reserved exclusively", plan_contract)
        review_contract = (PROJECT_ROOT / "skills" / "gsd-path-review" / "SKILL.md").read_text()
        self.assertIn("Always include PLAN.md's project", review_contract)
        self.assertIn("blocked gap with valid evidence", review_contract)
        docs_audit_contract = (
            PROJECT_ROOT / "skills" / "gsd-path-docs-audit" / "SKILL.md"
        ).read_text()
        self.assertIn("Require an existing `.project/STATE.md`", docs_audit_contract)
        self.assertIn("`shipped/done`", docs_audit_contract)
        grill_contract = (PROJECT_ROOT / "skills" / "gsd-path-grill" / "SKILL.md").read_text()
        self.assertIn("appended to DOCS-AUDIT.md's `## User rulings` table", grill_contract)
        router_contract = (PROJECT_ROOT / "skills" / "gsd-path" / "SKILL.md").read_text()
        self.assertIn("treat it as orphaned active pipeline", router_contract)
        self.assertIn("artifacts or foreign state", router_contract)

        readme = (PROJECT_ROOT / "README.md").read_text()
        self.assertNotIn("cp -n AGENTS.md WORKFLOW.md", readme)
        self.assertIn("A direct phase run stops at its handoff", readme)
        for contract in (
            "BUILD.md",
            "DOCS-AUDIT.md",
            "GRILL.md",
            "ONBOARD.md",
            "PLAN.md",
            "RESEARCH.md",
            "REVIEW.md",
            "SYNTHESIZE.md",
        ):
            self.assertTrue((PROJECT_ROOT / "skills" / "gsd-path" / contract).is_file(), contract)


if __name__ == "__main__":
    unittest.main()
