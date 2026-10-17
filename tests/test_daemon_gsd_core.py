import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "daemon"))

from gsd_daemon.flavors import probe_foreign

STATE = """---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: Hardening
current_phase: 2
current_phase_name: Beta
status: {status}
last_activity_desc: Plan 02-01 done
progress:
  total_phases: 3
  percent: 50
---

# Project State

### Blockers/Concerns

- Needs CRON_SECRET in production

## Session Continuity
"""

ROADMAP = """# Roadmap

### Phase 1: Alpha Work

**Goal:** Ship alpha.

- [x] 01-01-PLAN.md — Build the alpha store

### Phase 2: Beta Work

**Goal:** Ship beta.

- [x] 02-01-PLAN.md — First beta plan
- [ ] 02-02-PLAN.md — Second beta plan

### Phase 3: Gamma Work
"""

MILESTONES = """# Milestones

## v1.1 Hardening (Planned: 2026-07-27)

**Goal:** Make it safe.

## v1.0 First Release (Shipped: 2026-07-01)

**Goal:** Make it work.
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def verification(status: str) -> str:
    return f"---\nphase: x\nstatus: {status}\n---\n\n# Verification\n"


class GsdCoreReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "app"
        self.base = self.root / ".planning"
        write(self.base / "STATE.md", STATE.format(status="executing"))
        write(self.base / "ROADMAP.md", ROADMAP)
        write(self.base / "MILESTONES.md", MILESTONES)
        write(self.base / "milestones" / "v1.0-ROADMAP.md", "# v1.0\n")
        write(self.base / "PROJECT.md", "# Demo App\n\n## Core Value\n\nUsers trust it.\n")
        alpha = self.base / "phases" / "01-alpha-work"
        write(alpha / "01-01-PLAN.md", "---\nphase: 01\nfiles_modified:\n  - src/store.py\n  - tests/test_store.py\n---\n")
        write(alpha / "01-01-SUMMARY.md", "done\n")
        write(alpha / "01-VERIFICATION.md", verification("passed"))
        beta = self.base / "phases" / "02-beta-work"
        write(beta / "02-01-PLAN.md", "---\nphase: 02\n---\n")
        write(beta / "02-01-SUMMARY.md", "done\n")
        write(beta / "02-02-PLAN.md", "---\nphase: 02\n---\n")
        write(beta / "02-UAT.md", "---\nstatus: pending\n---\n")
        write(self.base / "phases" / "03-gamma-work" / "03-CONTEXT.md", "context\n")

    def probe(self) -> dict:
        return probe_foreign(self.root, "gsd-core").to_dict()

    def test_reads_milestone_phases_plans_and_reviews(self) -> None:
        card = self.probe()
        self.assertEqual(card["phases"], ["discuss", "research", "plan", "execute", "verify"])
        self.assertEqual(card["record_files"][:2], [{"path": ".planning/STATE.md", "label": "State"},
                                                    {"path": ".planning/ROADMAP.md", "label": "Roadmap"}])
        self.assertEqual((card["project"], card["milestone"], card["status"]), ("Demo App", "Hardening", "executing"))
        self.assertEqual((card["phase"], card["current_wave"]), ("execute", 2))
        self.assertEqual(card["waves"], {"1": "01 Alpha Work", "2": "02 Beta Work", "3": "03 Gamma Work"})
        self.assertEqual([(t["id"], t["wave"], t["status"], t["title"]) for t in card["tasks"]], [
            ("01-01", 1, "done", "Build the alpha store"),
            ("02-01", 2, "done", "First beta plan"),
            ("02-02", 2, "pending", "Second beta plan")])
        self.assertEqual(card["tasks"][0]["files"], ["src/store.py", "tests/test_store.py"])
        self.assertEqual((card["tasks_done"], card["tasks_total"]), (2, 3))
        self.assertEqual([(m["number"], m["slug"], m["status"], m["goal"], m["archive"]) for m in card["roadmap_milestones"]], [
            ("v1.0", "First Release", "shipped", "Make it work.", ".planning/milestones/v1.0-ROADMAP.md"),
            ("v1.1", "Hardening", "active", "Make it safe.", None)])
        self.assertEqual([(r["file"], r["kind"], r["verdict"]) for r in card["reviews"]], [
            (".planning/phases/01-alpha-work/01-VERIFICATION.md", "verification", "pass"),
            (".planning/phases/02-beta-work/02-UAT.md", "uat", "pending")])
        self.assertEqual((card["vision"], card["intent"]), ("Users trust it.", "Plan 02-01 done"))
        self.assertEqual(card["workflow"], {"state": "active", "label": "In execute"})
        self.assertIn({"kind": "blocked", "label": "Needs CRON_SECRET in production", "ref": "STATE.md"}, card["attention"])
        self.assertEqual(card["health"], "red")

    def test_step_follows_the_files_of_the_current_phase(self) -> None:
        state = self.base / "STATE.md"
        state.write_text(STATE.format(status="planning").replace("current_phase: 2", "current_phase: 3"), encoding="utf-8")
        self.assertEqual(self.probe()["phase"], "research")  # CONTEXT only
        gamma = self.base / "phases" / "03-gamma-work"
        write(gamma / "03-RESEARCH.md", "research\n")
        self.assertEqual(self.probe()["phase"], "plan")
        write(gamma / "03-01-PLAN.md", "---\nphase: 03\n---\n")
        self.assertEqual(self.probe()["phase"], "execute")
        write(gamma / "03-01-SUMMARY.md", "done\n")
        self.assertEqual(self.probe()["phase"], "verify")
        (gamma / "03-CONTEXT.md").unlink()
        (gamma / "03-RESEARCH.md").unlink()
        (gamma / "03-01-PLAN.md").unlink()
        (gamma / "03-01-SUMMARY.md").unlink()
        self.assertEqual(self.probe()["phase"], "discuss")

    def test_verification_results_drive_attention_and_shipped(self) -> None:
        beta = self.base / "phases" / "02-beta-work"
        write(beta / "02-VERIFICATION.md", verification("human_needed"))
        card = self.probe()
        self.assertIn({"kind": "question", "label": "Phase 02 needs a human check", "ref": "02-VERIFICATION.md"}, card["attention"])
        write(beta / "02-VERIFICATION.md", verification("gaps_found"))
        self.assertTrue(any(item["kind"] == "failed" for item in self.probe()["attention"]))
        # Every phase verified as passed: the milestone is shipped.
        write(beta / "02-VERIFICATION.md", verification("passed"))
        write(self.base / "phases" / "03-gamma-work" / "03-VERIFICATION.md", verification("passed"))
        self.assertEqual(self.probe()["workflow"], {"state": "shipped", "label": "Shipped"})

    def test_roadmap_phase_without_folder_waits_at_discuss(self) -> None:
        shutil.rmtree(self.base / "phases" / "03-gamma-work")
        write(self.base / "phases" / "02-beta-work" / "02-02-SUMMARY.md", "done\n")
        write(self.base / "phases" / "02-beta-work" / "02-VERIFICATION.md", verification("passed"))
        state = STATE.format(status="ready_to_plan").replace("current_phase: 2", "current_phase: 3")
        (self.base / "STATE.md").write_text(state, encoding="utf-8")
        card = self.probe()
        self.assertEqual((card["phase"], card["current_wave"]), ("discuss", 3))
        self.assertEqual(card["waves"]["3"], "3 Gamma Work")
        self.assertEqual(card["workflow"], {"state": "active", "label": "In discuss"})

    def test_archived_roadmap_phases_do_not_become_waves(self) -> None:
        archive = "## v1.0 archive\n\n### Phase 0: Old Spike\n\n"
        (self.base / "ROADMAP.md").write_text(ROADMAP.replace("# Roadmap\n", "# Roadmap\n\n" + archive), encoding="utf-8")
        card = self.probe()
        self.assertEqual(card["waves"], {"1": "01 Alpha Work", "2": "02 Beta Work", "3": "03 Gamma Work"})

    def test_state_status_blocked_and_between_milestones(self) -> None:
        (self.base / "STATE.md").write_text(STATE.format(status="blocked"), encoding="utf-8")
        self.assertEqual(self.probe()["workflow"]["state"], "blocked")
        between = STATE.format(status="milestone_complete").replace("milestone: v1.1", "milestone: none")
        (self.base / "STATE.md").write_text(between, encoding="utf-8")
        card = self.probe()
        self.assertEqual((card["workflow"]["state"], card["milestone"]), ("shipped", None))
        self.assertNotIn("none", [m["number"] for m in card["roadmap_milestones"]])

    def test_project_without_phases_is_not_started(self) -> None:
        bare = Path(self.tmp.name) / "bare"
        write(bare / ".planning" / "ROADMAP.md", "# Roadmap\n")
        card = probe_foreign(bare, "gsd-core").to_dict()
        self.assertEqual(card["workflow"]["state"], "idle")
        self.assertEqual((card["tasks_total"], card["phase"], card["roadmap_milestones"]), (0, None, []))


if __name__ == "__main__":
    unittest.main()
