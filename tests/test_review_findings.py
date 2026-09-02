"""review_findings.py computes the build step 7 finding sets from disk."""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "review_findings.py"
sys.path.insert(0, str(ROOT / "scripts"))

import review_findings  # noqa: E402

PLAN = """# Plan — demo

Project verify: `python3 -m unittest`

## Config

- max_review_cycles: {cycles}
- wave_budget: none
- review_panel: off
- finding_skeptics: {skeptics}

## Wave 1 — risk burn-down

Goal: prove the parser
Review depth: {depth}
"""

TASK = """---
id: {id}
title: {title}
wave: 1
deps: []
status: done
agent: null
base: null
worktree: null
task_branch: null
files:
{files}
---

# {id} — {title}

## Interface contract

- {interface}

## Intent coverage

- {owned}

## Acceptance criteria

1. {ac1}
2. {ac2}

## Verify

```bash
python3 -m unittest tests.test_demo
```

## Log

- 2026-09-01 — created by planner
"""

LENS = """# Review — wave 1, cycle {cycle}

Wave verdict: {verdict}
Cycle: {cycle}
Depth: {depth}
{lens_line}Tasks reviewed: 2

## T001 — Parse input: {t001}

{t001_body}
Warnings (non-blocking):
- none

Contract violations (blocking):
{t001_violations}

## T002 — Render output: pass

- ✅ Renders a table — verified render.py:10

## Intent coverage

### SC1 — Parser accepts CSV: {sc1}
{sc1_body}
"""

SKEPTIC = """# Skeptic — wave 1, cycle {cycle}

- Criterion: Parses CSV rows
- Criterion locator: {locator}
- Lenses: contract

## Observations

{observations}
## Observation verdicts

{observation_verdicts}
## Verdict

{verdict}

## Evidence

Re-ran the verify in the sidecar.
"""


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def lens_text(cycle=1, depth="deep", lens="contract", verdict="blocked", t001_fails=None,
              violations=("none",), sc1_fails=None):
    t001_fails = list(t001_fails or [])
    sc1_fails = list(sc1_fails or [])
    t001_body = "\n".join(
        [f"- ❌ {item}\n  fix: correct it" for item in t001_fails]
        or ["- ✅ Parses CSV rows — verified parser.py:5"]
    )
    sc1_body = "\n".join([f"- ❌ {item}" for item in sc1_fails] or ["- ✅ verified parser.py:5"])
    return LENS.format(
        cycle=cycle,
        verdict=verdict,
        depth=depth,
        lens_line=f"Lens: {lens}\n" if depth == "deep" else "",
        t001="fail" if t001_fails or violations != ("none",) else "pass",
        t001_body=t001_body,
        t001_violations="\n".join(f"- ❌ {item}" if item != "none" else "- none" for item in violations),
        sc1="fail" if sc1_fails else "pass",
        sc1_body=sc1_body,
    )


def skeptic_text(locator, cycle, verdict, observations):
    blocks = "\n".join(
        f"### Observation {n} — contract\n\n{text}\n" for n, text in enumerate(observations, 1)
    )
    verdicts = "\n".join(
        f"### Observation {n}: {verdict}\n\nchecked\n" for n in range(1, len(observations) + 1)
    )
    return SKEPTIC.format(
        cycle=cycle, locator=locator, verdict=verdict, observations=blocks,
        observation_verdicts=verdicts,
    )


class Fixture:
    def __init__(self, test, cycles=3, skeptics="on", depth="deep"):
        self.dir = tempfile.TemporaryDirectory()
        test.addCleanup(self.dir.cleanup)
        self.root = Path(self.dir.name)
        self.project = self.root / ".project"
        write(self.project / "plan" / "PLAN.md", PLAN.format(cycles=cycles, skeptics=skeptics, depth=depth))
        write(
            self.project / "tasks" / "T001-parse-input.md",
            TASK.format(id="T001", title="Parse input", files="  - src/parser.py", interface="None",
                        owned="SC1", ac1="Parses CSV rows", ac2="Rejects malformed rows"),
        )
        write(
            self.project / "tasks" / "T002-render-output.md",
            TASK.format(id="T002", title="Render output", files="  - src/render.py", interface="None",
                        owned="None", ac1="Renders a table", ac2="Handles empty input"),
        )

    def lens(self, lens, cycle=1, **kwargs):
        name = f"wave-1.cycle{cycle}.{lens}.md" if lens in {"contract", "adversarial"} else f"wave-1.cycle{cycle}.md"
        write(self.project / "review" / name, lens_text(cycle=cycle, lens=lens, **kwargs))

    def skeptic(self, locator, cycle, verdict, observations):
        write(
            self.project / "review" / f"wave-1.cycle{cycle}.skeptic-{locator}.md",
            skeptic_text(locator, cycle, verdict, observations),
        )

    def run(self, cycle=1, extra=()):
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "collect", "--repo", str(self.root),
             "--wave", "1", "--cycle", str(cycle), *extra],
            capture_output=True, text=True, check=False,
        )
        return result.returncode, json.loads(result.stdout)


class GroupingTest(unittest.TestCase):
    def test_groups_by_locator_and_keeps_distinct_observations(self):
        fixture = Fixture(self)
        fixture.lens("contract", t001_fails=["Rejects malformed rows — found: accepts them, parser.py:9"],
                     sc1_fails=["Parser accepts CSV — found: TSV only, parser.py:3"])
        fixture.lens("adversarial", t001_fails=["Rejects malformed rows — found: crashes on quotes, parser.py:12"],
                     violations=["task changed path outside its files list — src/render.py edited"])
        code, result = fixture.run()
        self.assertEqual(code, 0, result)
        by_locator = {group["locator"]: group for group in result["groups"]}
        self.assertEqual(sorted(by_locator), ["sc1", "t001_ac2", "t001_files"])
        ac2 = by_locator["t001_ac2"]
        self.assertEqual(ac2["lenses"], ["contract", "adversarial"])
        self.assertEqual(len(ac2["observations"]), 2)
        self.assertEqual(ac2["criterion"], "Rejects malformed rows")
        self.assertEqual(by_locator["sc1"]["tasks"], ["T001"])
        self.assertEqual(result["skeptic_groups"], ["sc1", "t001_ac2", "t001_files"])
        self.assertTrue(result["blocked"])
        self.assertFalse(result["cap_reached"])

    def test_true_duplicates_collapse(self):
        fixture = Fixture(self)
        same = "Rejects malformed rows — found: accepts them, parser.py:9"
        fixture.lens("contract", t001_fails=[same])
        fixture.lens("adversarial", t001_fails=[same])
        _, result = fixture.run()
        (group,) = result["groups"]
        self.assertEqual(len(group["observations"]), 1)
        self.assertEqual(group["lenses"], ["contract", "adversarial"])

    def test_unlocatable_finding_is_structural(self):
        fixture = Fixture(self)
        fixture.lens("contract", t001_fails=["Some paraphrase — found: nothing, x.py:1"])
        fixture.lens("adversarial", verdict="pass")
        _, result = fixture.run()
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["structural_blockers"][0]["kind"], "invalid-artifact")
        self.assertIn("names no task criterion", result["structural_blockers"][0]["detail"])


class SkepticSelectionTest(unittest.TestCase):
    def test_skeptics_off_sends_groups_to_fix(self):
        fixture = Fixture(self, skeptics="off")
        fixture.lens("contract", t001_fails=["Parses CSV rows — found: no, parser.py:1"])
        fixture.lens("adversarial", verdict="pass")
        _, result = fixture.run()
        self.assertFalse(result["skeptics_active"])
        self.assertEqual(result["skeptic_groups"], [])
        self.assertEqual(result["fix_groups"], ["t001_ac1"])
        self.assertEqual(result["fix_batches"], [{"locators": ["t001_ac1"], "files": ["src/parser.py"]}])

    def test_skeptics_on_but_full_depth_stays_off(self):
        fixture = Fixture(self, depth="full")
        fixture.lens("canonical", depth="full", t001_fails=["Parses CSV rows — found: no, parser.py:1"])
        _, result = fixture.run()
        self.assertFalse(result["skeptics_active"])
        self.assertEqual(result["fix_groups"], ["t001_ac1"])

    def test_current_cycle_skeptic_verdicts(self):
        fixture = Fixture(self)
        obs_a = "Parses CSV rows — found: no, parser.py:1 fix: correct it"
        obs_b = "Rejects malformed rows — found: accepts them, parser.py:9 fix: correct it"
        fixture.lens("contract", t001_fails=[obs_a.replace(" fix: correct it", ""),
                                              obs_b.replace(" fix: correct it", "")])
        fixture.lens("adversarial", verdict="pass")
        fixture.skeptic("t001_ac1", 1, "refuted", [obs_a])
        fixture.skeptic("t001_ac2", 1, "stands", [obs_b])
        _, result = fixture.run()
        self.assertEqual(result["refuted_groups"], ["t001_ac1"])
        self.assertEqual(result["fix_groups"], ["t001_ac2"])
        self.assertEqual(result["skeptic_groups"], [])
        self.assertFalse(result["all_refuted"])

    def test_all_refuted_branch(self):
        fixture = Fixture(self)
        obs = "Parses CSV rows — found: no, parser.py:1 fix: correct it"
        fixture.lens("contract", t001_fails=[obs.replace(" fix: correct it", "")])
        fixture.lens("adversarial", verdict="pass")
        fixture.skeptic("t001_ac1", 1, "refuted", [obs])
        _, result = fixture.run()
        self.assertTrue(result["all_refuted"])


class CarryForwardTest(unittest.TestCase):
    def test_earlier_refutation_with_unchanged_evidence_is_carried(self):
        fixture = Fixture(self)
        obs = "Parses CSV rows — found: no, parser.py:1 fix: correct it"
        fixture.lens("contract", cycle=1, t001_fails=[obs.replace(" fix: correct it", "")])
        fixture.lens("adversarial", cycle=1, verdict="pass")
        fixture.skeptic("t001_ac1", 1, "refuted", [obs])
        fixture.lens("contract", cycle=2, t001_fails=[obs.replace(" fix: correct it", "")])
        fixture.lens("adversarial", cycle=2, verdict="pass")
        _, result = fixture.run(cycle=2)
        (group,) = result["groups"]
        self.assertEqual(group["disposition"], "refuted-earlier")
        self.assertEqual(group["skeptic"]["cycle"], 1)
        self.assertTrue(group["repeat"])
        self.assertEqual(result["refuted_groups"], ["t001_ac1"])
        self.assertEqual(result["skeptic_groups"], [])
        self.assertEqual(result["carried_refutations"][0]["locator"], "t001_ac1")

    def test_earlier_refutation_with_new_evidence_goes_to_fix_without_skeptic(self):
        fixture = Fixture(self)
        old = "Parses CSV rows — found: no, parser.py:1 fix: correct it"
        fixture.lens("contract", cycle=1, t001_fails=[old.replace(" fix: correct it", "")])
        fixture.lens("adversarial", cycle=1, verdict="pass")
        fixture.skeptic("t001_ac1", 1, "refuted", [old])
        fixture.lens("contract", cycle=2, t001_fails=["Parses CSV rows — found: drops header, parser.py:4"])
        fixture.lens("adversarial", cycle=2, verdict="pass")
        _, result = fixture.run(cycle=2)
        (group,) = result["groups"]
        self.assertEqual(group["disposition"], "fix")
        self.assertEqual(len(group["new_evidence"]), 1)
        self.assertEqual(result["skeptic_groups"], [])
        self.assertEqual(result["fix_groups"], ["t001_ac1"])


class StructuralTest(unittest.TestCase):
    def test_missing_lens_and_helper_failure_bypass_skeptics(self):
        fixture = Fixture(self)
        fixture.lens("contract", t001_fails=["Parses CSV rows — found: no, parser.py:1"])
        _, result = fixture.run(extra=["--helper-failure", "check_handoffs.py wave exit 2: Depth mismatch"])
        kinds = sorted(item["kind"] for item in result["structural_blockers"])
        self.assertEqual(kinds, ["helper-failure", "missing-artifact"])
        self.assertTrue(result["blocked"])
        self.assertFalse(result["all_refuted"])
        self.assertEqual(result["skeptic_groups"], ["t001_ac1"])

    def test_invalid_skeptic_file_is_structural_not_refuted(self):
        fixture = Fixture(self)
        fixture.lens("contract", t001_fails=["Parses CSV rows — found: no, parser.py:1"])
        fixture.lens("adversarial", verdict="pass")
        write(fixture.project / "review" / "wave-1.cycle1.skeptic-t001_ac1.md",
              "# Skeptic\n\n- Criterion locator: t001_ac1\n\n## Verdict\n\nmaybe\n")
        _, result = fixture.run()
        self.assertEqual(result["structural_blockers"][0]["kind"], "invalid-skeptic")
        self.assertEqual(result["skeptic_groups"], ["t001_ac1"])
        self.assertEqual(result["refuted_groups"], [])


class CapAndConfigTest(unittest.TestCase):
    def test_cap_reached_at_max_review_cycles(self):
        fixture = Fixture(self, cycles=2)
        fixture.lens("contract", cycle=2, t001_fails=["Parses CSV rows — found: no, parser.py:1"])
        fixture.lens("adversarial", cycle=2, verdict="pass")
        _, result = fixture.run(cycle=2)
        self.assertTrue(result["cap_reached"])
        self.assertEqual(result["config"]["max_review_cycles"], 2)
        _, earlier = Fixture(self, cycles=2).run(cycle=1)
        self.assertFalse(earlier["cap_reached"])

    def test_config_typo_is_rejected_by_key(self):
        fixture = Fixture(self)
        plan = fixture.project / "plan" / "PLAN.md"
        plan.write_text(plan.read_text().replace("finding_skeptics: on", "finding_sceptics: on"))
        code, result = fixture.run()
        self.assertEqual(code, 2)
        self.assertIn("finding_sceptics", result["error"])

    def test_config_bad_values_name_the_key(self):
        for key, bad in (("max_review_cycles", "three"), ("finding_skeptics", "yes"), ("wave_budget", "")):
            with self.subTest(key=key):
                text = PLAN.format(cycles=3, skeptics="on", depth="deep")
                text = text.replace(
                    {"max_review_cycles": "max_review_cycles: 3", "finding_skeptics": "finding_skeptics: on",
                     "wave_budget": "wave_budget: none"}[key],
                    f"{key}: {bad}",
                )
                with self.assertRaises(review_findings.ReviewFindingsError) as raised:
                    review_findings.parse_config(text)
                self.assertIn(key, str(raised.exception))

    def test_config_defaults_when_keys_absent(self):
        config = review_findings.parse_config("## Config\n\n- review_panel: off\n\n## Wave 1 — x\n")
        self.assertEqual(config, {"max_review_cycles": 3, "finding_skeptics": "off", "wave_budget": "none"})


if __name__ == "__main__":
    unittest.main()
