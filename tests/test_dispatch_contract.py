"""Check the final reviewer brief emitted by the dispatch driver."""

import argparse
import unittest
from pathlib import Path

from scripts import dispatch_driver

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def dispatch_adapters():
    """Every platform dispatch adapter that exists (codex/zed/antigravity use the shared profile)."""
    return sorted((PROJECT_ROOT / "platforms").glob("*/dispatch.md"))


class DispatchContractTests(unittest.TestCase):
    def test_adapters_exist_including_the_shared_profile(self):
        adapters = dispatch_adapters()
        self.assertTrue(adapters, "no platform dispatch adapters found")
        self.assertIn(
            PROJECT_ROOT / "platforms" / "shared-agents" / "dispatch.md", adapters
        )

    def test_emitted_review_brief_preserves_dispatch_and_evidence_contract(self):
        primary = PROJECT_ROOT / "primary"
        options = argparse.Namespace(
            role_brief=PROJECT_ROOT / "skills/gsd-path/references/reviewer.md",
            template=PROJECT_ROOT / "skills/gsd-path/templates/wave-review.md",
            repair_evidence=None,
        )
        tasks = [{"task_id": "T001", "task": ".project/tasks/T001.md",
                  "base": "task-base", "commit": "task-landing"}]
        for lens in (None, "contract", "adversarial"):
            with self.subTest(lens=lens):
                name = "review_wave_1_cycle_2" + (f"_{lens}" if lens else "")
                sidecar = PROJECT_ROOT / name
                relative = f".project/review/{name}.md"
                state = {"wave": 1, "cycle": 2, "lens": lens, "task_id": name,
                         "worktree": str(sidecar), "branch": f"verify/{name}",
                         "base": "review-base", "relative": relative}
                brief = dispatch_driver.review_brief(state, options, primary, tasks, False, None)
                lines = brief.splitlines()
                self.assertEqual(
                    lines[0],
                    f"You are the reviewer for GSD Path wave 1, cycle 2; logical task name {name}. "
                    + "Mode: wave" + (f"; lens: {lens}." if lens else "."),
                )
                self.assertIn(f"Repository root, read-only: {primary}", lines)
                self.assertIn(
                    f"Your verify sidecar root, the only place you may write or apply patches: {sidecar} "
                    f"on branch verify/{name} at the recorded review base review-base.", lines,
                )
                self.assertIn(f"Write exactly this output file: {sidecar / relative}", lines)
                self.assertIn(f"Template (use only this): {options.template}", lines)
                self.assertIn(
                    f"- T001: {primary / tasks[0]['task']} — base task-base, landing commit task-landing",
                    lines,
                )


if __name__ == "__main__":
    unittest.main()
