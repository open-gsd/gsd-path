"""Router contract: Markdown delegates routing to the executable state helper."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import pipeline_state


ROUTER_DIR = Path(__file__).resolve().parents[1] / "skills" / "gsd-path"
CONTRACTS = {
    "inspect": "INSPECT.md",
    "define": "DEFINE.md",
    "research": "RESEARCH.md",
    "decide": "DECIDE.md",
    "roadmap": "ROADMAP.md",
    "plan": "PLAN.md",
    "build": "BUILD.md",
    "ship": "SHIP.md",
}


def state_text(phase, status):
    archive = ".project/archive/001-demo/" if phase == "shipped" else "null"
    return f"""---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: {phase}
status: {status}
branch: gsd-path/M001
archive: {archive}
---

# Project State

## Log
- 2026-08-23 — {phase} — fixture
"""


class RouterContractTests(unittest.TestCase):
    def route(self, phase, status):
        with tempfile.TemporaryDirectory() as directory:
            repo = Path(directory)
            subprocess.run(
                ["git", "init", "-q", "-b", "gsd-path/M001", str(repo)],
                check=True,
            )
            project = repo / ".project"
            (project / "intent").mkdir(parents=True)
            (project / "STATE.md").write_text(state_text(phase, status), encoding="utf-8")
            (project / "intent" / "INTENT.md").write_text(
                "# Intent — demo\n\nLane: quick\n",
                encoding="utf-8",
            )
            return pipeline_state.route_state(repo)["route"]

    def test_every_executable_phase_target_has_a_bundled_contract(self):
        for phase, filename in CONTRACTS.items():
            with self.subTest(phase=phase):
                self.assertTrue((ROUTER_DIR / filename).is_file())

    def test_phase_matrix_routes_through_the_helper(self):
        cases = (
            ("inspect", "active", "run-phase", "inspect"),
            ("inspect", "done", "run-phase", "define"),
            ("define", "active", "run-phase", "define"),
            ("define", "done", "run-phase", "plan"),
            ("research", "active", "run-phase", "research"),
            ("research", "done", "run-phase", "decide"),
            ("decide", "active", "run-phase", "decide"),
            ("decide", "done", "run-phase", "plan"),
            ("roadmap", "active", "run-phase", "roadmap"),
            ("roadmap", "done", "run-phase", "define"),
            ("plan", "active", "run-phase", "plan"),
            ("plan", "done", "run-phase", "build"),
            ("build", "active", "run-phase", "build"),
            ("build", "done", "run-phase", "build"),
            ("ship", "active", "run-phase", "ship"),
            ("ship", "done", "run-phase", "ship"),
            ("shipped", "done", "run-phase", "ship"),
        )
        for phase, status, action, target in cases:
            with self.subTest(phase=phase, status=status):
                route = self.route(phase, status)
                self.assertEqual(route["action"], action)
                self.assertEqual(route["phase"], target)
                self.assertIn(target, CONTRACTS)

    def test_ship_blocked_without_valid_findings_blocks(self):
        route = self.route("ship", "blocked")
        self.assertEqual(route["action"], "block")
        self.assertIn("PATCH-FINDINGS.md", route["reason"])


if __name__ == "__main__":
    unittest.main()
