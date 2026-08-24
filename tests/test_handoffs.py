import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts import check_handoffs


RESEARCH_HEAD = "a" * 40


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(root), *arguments),
        text=True,
        capture_output=True,
        check=True,
    )


def git_output(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()


class HandoffValidationTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def write_state(
        self, root: Path, phase: str, status: str, project_dir: str = ".project"
    ) -> None:
        branch = "null" if project_dir == ".project/next" else "gsd-path/M001"
        self.write(
            root,
            f"{project_dir}/STATE.md",
            f"""---
pipeline: gsd-path/v2
project: demo
milestone: demo
phase: {phase}
status: {status}
branch: {branch}
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
        self,
        root: Path,
        dimension: str,
        project_dir: str = ".project",
        questions=("Which domain applies?",),
    ) -> None:
        assigned = "; ".join(questions) if questions else "none"
        answers = (
            "\n".join(
                f"- {question} → The evidence answers this with the cited source."
                for question in questions
            )
            if questions
            else "- none"
        )
        self.write(
            root,
            f"{project_dir}/research/evidence-{dimension}.md",
            f"""# Evidence — {dimension}

Dimension: {dimension}
Questions assigned: {assigned}

## Finding: {dimension} finding

- **Claim**: The {dimension} claim is falsifiable.
- **Source**: https://example.test/{dimension}
- **Confidence**: high
- **Why it matters here**: It affects the demo intent.

## Assigned questions — answers

{answers}
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
        self.write_evidence(root, "security", questions=())

    def test_research_handoff_program_flow_uses_charter(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
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
            self.write_state(root, "research", "active")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write(root, ".project/CHARTER.md", "# Charter — demo\n")
            self.write_research_handoff(root)

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["phase"], "research")

    def test_research_handoff_program_flow_rejects_intent_pointer(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
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
            self.write_state(root, "research", "active")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["phase"], "research")
            self.assertEqual(result["dispatched"], ["domain"])
            self.assertEqual(result["skipped"], ["pitfalls", "similar", "stack"])

    def test_research_handoff_rejects_done_state_before_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "STATE.md must be research/active",
            ):
                check_handoffs.validate_research(root)

    def test_research_handoff_rejects_placeholder_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)
            template = (
                Path(__file__).resolve().parents[1]
                / "skills/gsd-path/templates/evidence.md"
            ).read_text(encoding="utf-8")
            self.write(root, ".project/research/evidence-domain.md", template)

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "evidence dimension|placeholder"
            ):
                check_handoffs.validate_research(root)

    def test_research_handoff_rejects_an_unanswered_assigned_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)
            evidence = root / ".project/research/evidence-domain.md"
            evidence.write_text(
                evidence.read_text(encoding="utf-8").replace(
                    "- Which domain applies? → The evidence answers this with the cited source.\n",
                    "",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "answers do not match"
            ):
                check_handoffs.validate_research(root)

    def test_research_handoff_rejects_an_unassigned_intent_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
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
            self.write_state(root, "research", "active")
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
            self.write_state(root, "research", "active", ".project/next")
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
            self.write_state(root, "research", "active")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_research(root, ".project/next")

    def test_patch_findings_are_illegal_under_next_project_dir(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "blocked", ".project/next")
            self.write_review_sources(root, ".project/next")
            self.write_patch_findings(root, ".project/next")

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "ship phase requires a branch"
            ):
                check_handoffs.validate_patch_findings(root, ".project/next")

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
        task_rows: str = (
            "| T001 | Demo task T001 | — | src/app.py |\n"
            "| T002 | Demo task T002 | — | tests/test_app.py |\n"
        ),
        project_dir: str = ".project",
    ) -> None:
        self.write(
            root,
            f"{project_dir}/plan/PLAN.md",
            f"""# Plan — demo

Project verify: `python3 -m unittest discover`

## Config

- max_review_cycles: 3
- wave_budget: none
- review_panel: off

## Wave 1 — demo

Goal: Prove the demo behavior.
Review depth: full

| Task | Title | Deps | Files |
|------|-------|------|-------|
{task_rows}

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
        verify: str = "",
        wave: int = 1,
        deps: str = "[]",
        files: str = "",
        project_dir: str = ".project",
    ) -> None:
        task_file = files or (
            "src/app.py" if task_id == "T001" else "tests/test_app.py"
        )
        verify_command = verify or f"python3 {task_file}"
        self.write(
            root,
            f"{project_dir}/tasks/{task_id}-demo.md",
            f"""---
id: {task_id}
title: Demo task {task_id}
wave: {wave}
deps: {deps}
status: pending
agent: null
base: null
worktree: null
task_branch: null
files:
  - {task_file}
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
{verify_command}
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

    def test_plan_rejects_a_noncanonical_task_filename(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            (root / ".project/tasks/notes.md").write_text(
                "post-review notes\n", encoding="utf-8"
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "non-canonical task artifact"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_task_filename_id_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            (root / ".project/tasks/T001-demo.md").rename(
                root / ".project/tasks/T009-demo.md"
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "does not match task id T001"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_an_unsafe_declared_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_coverage_task(
                root,
                "T001",
                "- SC1",
                files="../src/app.py",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "task files has an unsafe or non-canonical path",
            ):
                check_handoffs.validate_plan(root)

    def test_plan_uses_the_strict_pipeline_state_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            state = root / ".project/STATE.md"
            state.write_text(
                state.read_text(encoding="utf-8").replace("project: demo\n", ""),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "STATE.md is missing fields: project"
            ):
                check_handoffs.validate_plan(root)

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

    def test_plan_rejects_a_task_verify_that_names_no_files_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_coverage_task(
                root,
                "T001",
                "- SC1",
                acceptance="1. The demo command prints hello.",
                verify="pnpm test",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("T001 Verify must name a path from files", str(failure.exception))

    def test_plan_allows_a_task_verify_with_a_pytest_node_id(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_coverage_task(
                root,
                "T001",
                "- SC1",
                acceptance="1. The demo command prints hello.",
                verify="pytest src/app.py::test_hello",
            )

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["tasks"], 2)

    def test_plan_rejects_unknown_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(
                root,
                task_rows=(
                    "| T001 | Demo task T001 | T999 | src/app.py |\n"
                    "| T002 | Demo task T002 | — | tests/test_app.py |\n"
                ),
            )
            self.write_coverage_task(root, "T001", "- SC1", deps="[T999]")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("unknown dependency T999", str(failure.exception))

    def test_plan_rejects_same_wave_file_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(
                root,
                task_rows=(
                    "| T001 | Demo task T001 | — | src/app.py |\n"
                    "| T002 | Demo task T002 | — | src/app.py |\n"
                ),
            )
            self.write_coverage_task(
                root,
                "T002",
                "- SC2",
                acceptance="1. The demo test suite is green.",
                files="src/app.py",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("same-wave file overlap", str(failure.exception))

    def test_plan_rejects_dependency_cycles(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(
                root,
                task_rows=(
                    "| T001 | Demo task T001 | T002 | src/app.py |\n"
                    "| T002 | Demo task T002 | T001 | tests/test_app.py |\n"
                ),
            )
            self.write_coverage_task(root, "T001", "- SC1", deps="[T002]")
            self.write_coverage_task(
                root,
                "T002",
                "- SC2",
                acceptance="1. The demo test suite is green.",
                deps="[T001]",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("dependency cycle", str(failure.exception))

    def test_decide_gate_requires_complete_decision_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "decide", "active")
            self.write(root, ".project/CHARTER.md", "# Charter — demo\n")
            self.write(
                root,
                ".project/SYNTHESIS.md",
                """# Synthesis

## Settled
- Runtime — Python (`INTENT.md`)

## Decisions
### Storage
- **Decision**: Files
- **Runner-up**: SQLite; unnecessary here
- **Evidence**: evidence-stack.md § Storage
- **Confidence**: high

## For the planner
- **Wave-1 blockers**: File locking
- **Walking skeleton**: One append flow
- **Pitfalls → tasks**: interrupted write → recovery task

## User rulings
- None

## Still unknown
- None
""",
            )

            result = check_handoffs.validate_decide(root)
            self.assertEqual(result["decisions"], ["Storage"])

            synthesis = root / ".project/SYNTHESIS.md"
            synthesis.write_text(
                synthesis.read_text(encoding="utf-8").replace(
                    "- **Evidence**: evidence-stack.md § Storage\n", ""
                ),
                encoding="utf-8",
            )
            with self.assertRaises(check_handoffs.HandoffError):
                check_handoffs.validate_decide(root)

    def test_roadmap_gate_rejects_forward_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "roadmap", "active")
            self.write(
                root,
                ".project/ROADMAP.md",
                """# Roadmap — demo

## Milestones

### M001 — first
Goal: First release
Depends on: [M002]
Status: pending
Archive: null
Integrated: null
Scope: in
- First capability
Scope: out
- Later capability
Success criteria
1. First works
Risks
- Delivery risk
Open questions
- None

### M002 — second
Goal: Second release
Depends on: [M001]
Status: pending
Archive: null
Integrated: null
Scope: in
- Second capability
Scope: out
- None
Success criteria
1. Second works
Risks
- Delivery risk
Open questions
- None
""",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_roadmap(root)
            self.assertIn("earlier milestones", str(failure.exception))

    def test_roadmap_gate_protects_a_shipped_milestone_slug(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            git(root, "init", "-b", "gsd-path/demo")
            git(root, "config", "user.email", "test@example.test")
            git(root, "config", "user.name", "Test")
            self.write_state(root, "roadmap", "active")
            self.write(
                root,
                ".project/ROADMAP.md",
                """# Roadmap — demo

## Milestones

### M001 — first
Goal: First release
Depends on: []
Status: shipped
Archive: .project/archive/001-first
Integrated: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
Scope: in
- First capability
Scope: out
- Later capability
Success criteria
1. First works
Risks
- Delivery risk
Open questions
- None
""",
            )
            git(root, "add", ".project")
            git(root, "commit", "-q", "-m", "roadmap")
            roadmap = root / ".project/ROADMAP.md"
            roadmap.write_text(
                roadmap.read_text(encoding="utf-8").replace(
                    "### M001 — first", "### M001 — renamed"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_roadmap(root)
            self.assertIn("immutable content", str(failure.exception))

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
        self.write_state(root, "build", "active", project_dir)
        relative = f"{project_dir}/review/wave-1.cycle1.md"
        sc1_marker = "✅" if sc1 == "pass" else "❌"
        sc2_marker = "✅" if sc2 == "pass" else "❌"
        self.write(
            root,
            relative,
            f"""# Review — wave 1, cycle 1

Wave verdict: {verdict}
Cycle: 1
Depth: full
Tasks reviewed: 2

## T001 — Demo task T001: pass

- ✅ The demo command prints hello. — ran hello.py

## T002 — Demo task T002: pass

- ✅ The demo test suite is green. — unittest OK

## Intent coverage

### SC1 — The demo command prints hello.: {sc1}
- {sc1_marker} hello.py output
### SC2 — The demo test suite is green.: {sc2}
- {sc2_marker} unittest
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

    def test_wave_rejects_placeholder_task_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_text(
                review.read_text(encoding="utf-8").replace(
                    "- ✅ The demo command prints hello. — ran hello.py",
                    "- ✅ none",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(check_handoffs.HandoffError, "is empty"):
                check_handoffs.validate_wave(root, review=relative)

    def test_wave_requires_evidence_under_each_owned_sc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_text(
                review.read_text(encoding="utf-8").replace(
                    "- ✅ hello.py output\n", ""
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "SC1 lacks pass evidence"
            ):
                check_handoffs.validate_wave(root, review=relative)

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

    def test_wave_rejects_a_noncanonical_review_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "wave review must be the canonical path"
            ):
                check_handoffs.validate_wave(root, review="/" + relative)

    def test_wave_rejects_the_wrong_task_standing_in(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_text(
                review.read_text(encoding="utf-8").replace(
                    "## T002 — Demo task T002: pass",
                    "## T003 — Demo task T003: pass",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "must review exactly T001, T002"
            ):
                check_handoffs.validate_wave(root, review=relative)

    def test_wave_still_checks_structure_when_it_owns_no_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(
                root,
                rows="| SC1 | T003 | AC1 |\n| SC2 | T003 | AC2 |\n",
                task_rows=(
                    "| T001 | Demo task T001 | — | src/app.py |\n"
                    "| T002 | Demo task T002 | — | tests/test_app.py |\n"
                    "\n## Wave 2 — coverage\n\n"
                    "Goal: Cover intent.\n"
                    "Review depth: full\n\n"
                    "| Task | Title | Deps | Files |\n"
                    "|------|-------|------|-------|\n"
                    "| T003 | Demo task T003 | — | docs/result.md |\n"
                ),
            )
            self.write_coverage_task(root, "T001", "- None")
            self.write_coverage_task(root, "T002", "- None")
            self.write_coverage_task(
                root,
                "T003",
                "- SC1\n- SC2",
                acceptance=(
                    "1. The demo command prints hello.\n"
                    "2. The demo test suite is green."
                ),
                verify="python3 docs/result.md",
                wave=2,
                files="docs/result.md",
            )
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_text(
                review.read_text(encoding="utf-8").replace(
                    "Tasks reviewed: 2", "Tasks reviewed: 1"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "Tasks reviewed does not match Wave 1"
            ):
                check_handoffs.validate_wave(root, review=relative)

    def write_final_review(
        self,
        root: Path,
        *,
        verdict: str = "pass",
        sc1: str = "met",
        check: str = "`python3 hello.py`",
        project_dir: str = ".project",
    ) -> None:
        if not (root / ".git").exists():
            git(root, "init", "-q", "-b", "gsd-path/M001")
            git(root, "config", "user.email", "test@example.test")
            git(root, "config", "user.name", "Test")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "reviewed product")
        reviewed_head = git_output(root, "rev-parse", "HEAD")
        self.write(
            root,
            f"{project_dir}/review/FINAL.md",
            f"""# Final Review — demo

Reviewed HEAD: {reviewed_head}
Overall verdict: {verdict}

## Success criteria

### SC1 — The demo command prints hello.

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
        self.write(
            root,
            f"{project_dir}/review/final-gap-1.md",
            f"""# Gap Review — 1: project verify

Reviewed HEAD: {reviewed_head}
Gap verdict: pass
Risk: Project verify
Waves checked: 1

## Checked evidence
- **Check**: `python3 -m unittest`
- **Observed**: OK
- **Reference**: tests/test_app.py

## Finding
- **Found**: Project verify passed.
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

    def test_final_requires_evidence_for_a_blocked_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root, verdict="blocked", sc1="not-met")

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "not-met verdict requires a Finding and Fix direction",
            ):
                check_handoffs.validate_final(root)

    def test_final_allows_a_blocked_gap_when_all_criteria_are_met(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root, verdict="blocked")
            gap = root / ".project/review/final-gap-1.md"
            gap.write_text(
                gap.read_text(encoding="utf-8")
                .replace("Gap verdict: pass", "Gap verdict: blocked")
                .replace(
                    "- **Fix direction**: none",
                    "- **Fix direction**: Repair the integration and rerun the gap.",
                ),
                encoding="utf-8",
            )

            result = check_handoffs.validate_final(root)

            self.assertEqual("blocked", result["verdict"])

    def test_final_requires_one_observed_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            final = root / ".project/review/FINAL.md"
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "- **Observed**: hello\n", ""
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "FINAL.md SC1 is missing Observed"
            ):
                check_handoffs.validate_final(root)

    def test_final_binds_each_heading_to_the_intent_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            final = root / ".project/review/FINAL.md"
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "### SC1 — The demo command prints hello.",
                    "### SC1 — Something easier passes.",
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "SC1 heading text differs from INTENT.md"
            ):
                check_handoffs.validate_final(root)

    def test_final_rejects_a_duplicate_evidence_field(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            final = root / ".project/review/FINAL.md"
            final.write_text(
                final.read_text(encoding="utf-8").replace(
                    "- **Finding**: none\n",
                    "- **Finding**: none\n- **Finding**: none\n",
                    1,
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "FINAL.md SC1 repeats Finding"
            ):
                check_handoffs.validate_final(root)

    def test_final_rejects_a_stale_reviewed_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            self.write(root, "product.txt", "later\n")
            git(root, "add", "product.txt")
            git(root, "commit", "-q", "-m", "later product")

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "Reviewed HEAD must equal current HEAD"
            ):
                check_handoffs.validate_final(root)

    def test_final_validates_numbered_gap_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            reviewed_head = git_output(root, "rev-parse", "HEAD")
            self.write(
                root,
                ".project/review/final-gap-1.md",
                f"""# Gap Review — 1: project verify

Reviewed HEAD: {reviewed_head}
Gap verdict: pass
Risk: Project verify
Waves checked: 1

## Checked evidence
- **Check**: `python3 -m unittest`
- **Observed**: OK
- **Reference**: tests/test_app.py

## Finding
- **Found**: Project verify passed.
- **Fix direction**: none
""",
            )

            result = check_handoffs.validate_final(root)
            self.assertEqual(result["gaps"], [1])

            gap = root / ".project/review/final-gap-1.md"
            gap.write_text(
                gap.read_text(encoding="utf-8").replace(reviewed_head, "b" * 40),
                encoding="utf-8",
            )
            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("Reviewed HEAD differs", str(failure.exception))

    def test_final_rejects_a_gap_heading_with_the_wrong_number(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            gap = root / ".project/review/final-gap-1.md"
            gap.write_text(
                gap.read_text(encoding="utf-8").replace(
                    "# Gap Review — 1:", "# Gap Review — 2:"
                ),
                encoding="utf-8",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("heading does not match", str(failure.exception))

    def test_final_rejects_a_gap_heading_risk_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root)
            gap = root / ".project/review/final-gap-1.md"
            gap.write_text(
                gap.read_text(encoding="utf-8").replace(
                    "Risk: Project verify", "Risk: release packaging"
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "heading risk does not match Risk field",
            ):
                check_handoffs.validate_final(root)


if __name__ == "__main__":
    unittest.main()
