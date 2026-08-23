import tempfile
import unittest
from pathlib import Path

from scripts import check_handoffs


RESEARCH_HEAD = "a" * 40


class HandoffValidationTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_state(
        self, root: Path, phase: str, status: str, project_dir: str = ".project"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/STATE.md",
            f"""---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: {phase}
status: {status}
branch: main
archive: null
---

# Project State

## Log
- 2026-08-03 — {phase} — handoff ready
""",
        )

    def write_intent(
        self, root: Path, questions: str, project_dir: str = ".project"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/intent/INTENT.md",
            f"""# Intent — demo

## Open questions
{questions}
""",
        )

    def write_evidence(
        self, root: Path, dimension: str, project_dir: str = ".project"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/research/evidence-{dimension}.md",
            f"""# Evidence — {dimension}

## Finding: {dimension} finding

- **Claim**: The {dimension} claim is falsifiable.
- **Source**: https://example.test/{dimension}
- **Confidence**: high
- **Why it matters here**: It affects the demo intent.
""",
        )

    def write_research_handoff(
        self, root: Path, project_dir: str = ".project"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/research/RESEARCH.md",
            f"""# Research Handoff

Phase: research
Status: complete
Intent: `{project_dir}/intent/INTENT.md`

## Dispatch
- `domain` — dispatched → `{project_dir}/research/evidence-domain.md` — assigned question
- `stack` — skipped → none — intent settles the stack
- `pitfalls` — skipped → none — no risk was assigned
- `similar` — skipped → none — no comparison is needed

## Question assignments
- `[RESEARCH] Which domain applies?` → `domain`
""",
        )
        self.write_evidence(root, "domain", project_dir)

    def write_custom_only_research_handoff(self, root: Path) -> None:
        self.write(
            root,
            ".project/research/RESEARCH.md",
            """# Research Handoff

Phase: research
Status: complete
Intent: `.project/intent/INTENT.md`

## Dispatch
- `domain` — skipped → none — no domain question was assigned
- `stack` — skipped → none — the stack is settled
- `pitfalls` — skipped → none — no risk was assigned
- `similar` — skipped → none — no comparison is needed
- `security` — dispatched → `.project/research/evidence-security.md` — an intent risk needs a focused check

## Question assignments
- none
""",
        )
        self.write_evidence(root, "security")

    def test_research_handoff_program_flow_uses_charter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write(
                root,
                ".project/CHARTER.md",
                "# Charter — demo\n\n## Open questions\n- [RESEARCH] Which domain applies?\n",
            )
            self.write_research_handoff(root)
            handoff = root / ".project" / "research" / "RESEARCH.md"
            handoff.write_text(
                handoff.read_text(encoding="utf-8").replace(
                    "Intent: `.project/intent/INTENT.md`",
                    "Intent: `.project/CHARTER.md`",
                ),
                encoding="utf-8",
            )

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["phase"], "research")
            self.assertEqual(result["dispatched"], ["domain"])

    def test_research_handoff_intent_wins_when_both_exist(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write(root, ".project/CHARTER.md", "# Charter — demo\n")
            self.write_research_handoff(root)

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["phase"], "research")

    def test_research_handoff_program_flow_rejects_intent_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write(
                root,
                ".project/CHARTER.md",
                "# Charter — demo\n\n## Open questions\n- [RESEARCH] Which domain applies?\n",
            )
            self.write_research_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_research(root)
            self.assertIn("must point to .project/CHARTER.md", str(failure.exception))

    def test_research_handoff_validates_dispatch_and_question_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["phase"], "research")
            self.assertEqual(result["dispatched"], ["domain"])
            self.assertEqual(result["skipped"], ["pitfalls", "similar", "stack"])

    def test_research_handoff_rejects_an_unassigned_intent_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(
                root,
                "- [RESEARCH] Which domain applies?\n- [RESEARCH] Which risk matters?\n",
            )
            self.write_research_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_research(root)

    def test_research_handoff_requires_a_standard_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "")
            self.write_custom_only_research_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_research(root)

    def write_review_sources(self, root: Path, project_dir: str = ".project") -> None:
        self.write(
            root,
            f"{project_dir}/review/FINAL.md",
            f"""# Final Review — demo

Reviewed HEAD: {RESEARCH_HEAD}
Overall verdict: blocked

### SC1 — demo works
- **Verdict**: not-met
- **Finding**: The demo does not run.
- **Fix direction**: Make the demo run and rerun the criterion.

### SC2 — unrelated criterion
- **Verdict**: met
- **Check**: `python -m unittest`
- **Observed**: The unrelated criterion passed.
- **Reference**: tests/test_demo.py
- **Finding**: none
- **Fix direction**: none
""",
        )
        self.write(
            root,
            f"{project_dir}/review/final-gap-1.md",
            f"""# Gap Review — 1: project verify

Reviewed HEAD: {RESEARCH_HEAD}
Gap verdict: blocked
Risk: project Verify

## Finding

- **Found**: The project Verify risk is blocked.
- **Fix direction**: Run project Verify at the reviewed HEAD and fix the failure.
""",
        )

    def write_patch_findings(self, root: Path, project_dir: str = ".project") -> None:
        self.write(
            root,
            f"{project_dir}/review/PATCH-FINDINGS.md",
            f"""# Patch Findings

Reviewed HEAD: {RESEARCH_HEAD}
State: ship/blocked

## Findings
### P001 — demo criterion
- **Source**: `{project_dir}/review/FINAL.md`
- **Locator**: `SC1`
- **Evidence**: The demo does not run.
- **Fix direction**: Make the demo run and rerun the criterion.

### P002 — project verify
- **Source**: `{project_dir}/review/final-gap-1.md`
- **Locator**: `Risk: project Verify`
- **Evidence**: The project Verify risk is blocked.
- **Fix direction**: Run project Verify at the reviewed HEAD and fix the failure.
""",
        )

    def test_patch_findings_validate_selected_sources_and_reviewed_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)

            result = check_handoffs.validate_patch_findings(root)

            self.assertEqual(result["phase"], "ship")
            self.assertEqual(result["findings"], ["P001", "P002"])
            self.assertEqual(result["reviewed_head"], RESEARCH_HEAD)

    def test_patch_findings_reject_a_source_with_a_different_reviewed_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)
            final_review = root / ".project/review/FINAL.md"
            final_review.write_text(
                final_review.read_text(encoding="utf-8").replace(
                    RESEARCH_HEAD, "b" * 40
                ),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_patch_findings(root)

    def test_patch_findings_reject_a_passing_success_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)
            patch = root / ".project/review/PATCH-FINDINGS.md"
            patch.write_text(
                patch.read_text(encoding="utf-8").replace("`SC1`", "`SC2`", 1),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_patch_findings(root)

    def test_patch_findings_reject_fabricated_source_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)
            patch = root / ".project/review/PATCH-FINDINGS.md"
            patch.write_text(
                patch.read_text(encoding="utf-8").replace(
                    "The demo does not run.", "An invented failure.", 1
                ),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_patch_findings(root)

    def test_patch_findings_reject_a_malformed_finding_heading(self) -> None:
        for malformed in ("### P02 — project verify", "### P002 project verify"):
            with self.subTest(malformed=malformed), \
                    tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_state(root, "ship", "blocked")
                self.write_review_sources(root)
                self.write_patch_findings(root)
                patch = root / ".project/review/PATCH-FINDINGS.md"
                patch.write_text(
                    patch.read_text(encoding="utf-8").replace(
                        "### P002 — project verify", malformed
                    ),
                    encoding="utf-8",
                )

                with self.assertRaises(check_handoffs.HandoffError) as failure:
                    check_handoffs.validate_patch_findings(root)
                self.assertIn("P### ids", str(failure.exception))

    def test_research_handoff_passes_under_next_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done", ".project/next")
            self.write_intent(
                root, "- [RESEARCH] Which domain applies?\n", ".project/next"
            )
            self.write_research_handoff(root, ".project/next")

            exit_code = check_handoffs.main(
                ["research", "--repo", str(root), "--project-dir", ".project/next"]
            )

            self.assertEqual(exit_code, 0)

    def test_research_handoff_ignores_default_project_dir_in_lookahead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_research(root, ".project/next")

    def test_patch_findings_pass_under_next_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked", ".project/next")
            self.write_review_sources(root, ".project/next")
            self.write_patch_findings(root, ".project/next")

            result = check_handoffs.validate_patch_findings(root, ".project/next")

            self.assertEqual(result["findings"], ["P001", "P002"])
            self.assertEqual(
                result["sources"],
                [
                    ".project/next/review/FINAL.md",
                    ".project/next/review/final-gap-1.md",
                ],
            )

    def test_patch_findings_ignore_default_project_dir_in_lookahead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_patch_findings(root, ".project/next")

    def test_project_dir_rejects_an_absolute_path(self) -> None:
        with self.assertRaises(SystemExit):
            check_handoffs.main(
                ["research", "--repo", ".", "--project-dir", "/abs/path"]
            )

    def test_project_dir_rejects_parent_traversal(self) -> None:
        with self.assertRaises(SystemExit):
            check_handoffs.main(["research", "--repo", ".", "--project-dir", "../x"])

    def write_intent_criteria(
        self, root: Path, project_dir: str = ".project"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/intent/INTENT.md",
            """# Intent — demo

## Success criteria

1. The demo command prints hello.
2. The demo test suite is green.
""",
        )

    def write_plan_coverage(
        self,
        root: Path,
        rows: str = "| SC1 | T001 | AC1 |\n| SC2 | T002 | AC1 |\n",
        project_dir: str = ".project",
    ) -> None:
        self.write(
            root,
            f"{project_dir}/plan/PLAN.md",
            f"""# Plan — demo

Project verify: `python3 -m unittest discover`

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
{rows}
""",
        )

    def write_coverage_task(
        self,
        root: Path,
        task_id: str,
        owns: str,
        acceptance: str = "1. The demo behavior holds.",
        verify: str = "python3 -m unittest",
        project_dir: str = ".project",
    ) -> None:
        self.write(
            root,
            f"{project_dir}/tasks/{task_id}-demo.md",
            f"""---
id: {task_id}
title: Demo task {task_id}
wave: 1
deps: []
status: pending
agent: null
commit: null
base: null
worktree: null
task_branch: null
files:
  - src/app.py
---

# {task_id} — demo

## Context

The task implements the demo.

## Approach

- Keep the existing command.

## Interface contract

- None

## Intent coverage

{owns}

## Acceptance criteria

{acceptance}

## Verify

```bash
{verify}
```

## Log

- 2026-08-22 — created by planner
""",
        )

    def write_plan_handoff(self, root: Path, project_dir: str = ".project") -> None:
        self.write_state(root, "plan", "active", project_dir)
        self.write_intent_criteria(root, project_dir)
        self.write_plan_coverage(root, project_dir=project_dir)
        self.write_coverage_task(
            root,
            "T001",
            "- SC1",
            acceptance="1. The demo command prints hello.",
            project_dir=project_dir,
        )
        self.write_coverage_task(
            root,
            "T002",
            "- SC2",
            acceptance="1. The demo test suite is green.",
            project_dir=project_dir,
        )

    def test_plan_coverage_maps_each_success_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["criteria"], ["SC1", "SC2"])
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["tasks"], 2)

    def test_plan_coverage_rejects_an_omitted_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(root, rows="| SC1 | T001 | AC1 |\n")
            self.write_coverage_task(root, "T002", "- None")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("omits SC2", str(failure.exception))

    def test_plan_coverage_rejects_a_task_owns_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_coverage_task(
                root,
                "T001",
                "- None",
                acceptance="1. The demo command prints hello.",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("T001 Intent coverage does not match PLAN.md", str(failure.exception))

    def test_plan_coverage_rejects_a_missing_acceptance_item(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(
                root, rows="| SC1 | T001 | AC2 |\n| SC2 | T002 | AC1 |\n"
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("T001 has no AC2", str(failure.exception))

    def test_plan_coverage_passes_under_next_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root, ".project/next")

            exit_code = check_handoffs.main(
                ["plan", "--repo", str(root), "--project-dir", ".project/next"]
            )

            self.assertEqual(exit_code, 0)

    def test_plan_coverage_ignores_default_project_dir_in_lookahead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_plan(root, ".project/next")

    def test_plan_rejects_a_task_verify_that_copies_project_verify(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_coverage_task(
                root,
                "T001",
                "- SC1",
                acceptance="1. The demo command prints hello.",
                verify="python3 -m unittest discover",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("T001 Verify must not copy Project verify", str(failure.exception))

    def test_plan_allows_project_verify_when_an_owned_sc_names_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "plan", "active")
            self.write(
                root,
                ".project/intent/INTENT.md",
                """# Intent — demo

## Success criteria

1. python3 -m unittest discover is green at cutover.
2. The demo test suite is green.
""",
            )
            self.write_plan_coverage(root)
            self.write_coverage_task(
                root,
                "T001",
                "- SC1",
                acceptance="1. python3 -m unittest discover is green at cutover.",
                verify="python3 -m unittest discover",
            )
            self.write_coverage_task(
                root,
                "T002",
                "- SC2",
                acceptance="1. The demo test suite is green.",
            )

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["tasks"], 2)

    def write_wave_review(
        self,
        root: Path,
        *,
        sc1: str = "pass",
        sc2: str = "pass",
        verdict: str = "pass",
        extra: str = "",
        project_dir: str = ".project",
    ) -> str:
        relative = f"{project_dir}/review/wave-1.cycle1.md"
        self.write(
            root,
            relative,
            f"""# Review — wave 1, cycle 1

Wave verdict: {verdict}
Cycle: 1
Depth: verify-only
Tasks reviewed: 2

## T001 — demo: pass

- ✅ The demo command prints hello. — ran hello.py

## T002 — demo: pass

- ✅ The demo test suite is green. — unittest OK

## Intent coverage

### SC1 — hello prints: {sc1}
- ✅ hello.py output
### SC2 — The demo test suite is green.: {sc2}
- ✅ unittest
{extra}
""",
        )
        return relative

    def test_wave_requires_owned_sc_headings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)

            result = check_handoffs.validate_wave(root, review=relative)

            self.assertEqual(result["owned"], ["SC1", "SC2"])
            self.assertEqual(result["verdict"], "pass")

    def test_wave_rejects_pass_while_an_owned_sc_failed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root, sc1="fail", verdict="pass")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_wave(root, review=relative)
            self.assertIn("owned SC failed", str(failure.exception))

    def test_wave_rejects_a_missing_owned_sc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_text(
                review.read_text(encoding="utf-8").replace("### SC2 —", "### SC9 —"),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_wave(root, review=relative)
            self.assertIn("exactly SC1, SC2", str(failure.exception))

    def write_final_review(
        self,
        root: Path,
        *,
        verdict: str = "pass",
        sc1: str = "met",
        check: str = "`python3 hello.py`",
        project_dir: str = ".project",
    ) -> None:
        self.write(
            root,
            f"{project_dir}/review/FINAL.md",
            f"""# Final Review — demo

Reviewed HEAD: {RESEARCH_HEAD}
Overall verdict: {verdict}

## Success criteria

### SC1 — hello prints

- **Verdict**: {sc1}
- **Check**: {check}
- **Observed**: hello
- **Reference**: hello.py:1
- **Finding**: none
- **Fix direction**: none

### SC2 — The demo test suite is green.

- **Verdict**: met
- **Check**: `python3 -m unittest`
- **Observed**: OK
- **Reference**: tests/test_app.py
- **Finding**: none
- **Fix direction**: none
""",
        )

    def test_final_requires_a_verdict_per_intent_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["criteria"], ["SC1", "SC2"])
            self.assertEqual(result["verdict"], "pass")

    def test_final_rejects_pass_without_a_check_or_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root, check="none")
            final = root / ".project/review/FINAL.md"
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "- **Reference**: hello.py:1",
                    "- **Reference**: none",
                ),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("SC1 lacks a Check or Reference", str(failure.exception))


if __name__ == "__main__":
    unittest.main()
