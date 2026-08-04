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

    def write_state(self, root: Path, phase: str, status: str) -> None:
        self.write(
            root,
            ".project/STATE.md",
            f"""---
pipeline: gsd-path/v1
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

    def write_intent(self, root: Path, questions: str) -> None:
        self.write(
            root,
            ".project/intent/INTENT.md",
            f"""# Intent — demo

## Open questions
{questions}
""",
        )

    def write_evidence(self, root: Path, dimension: str) -> None:
        self.write(
            root,
            f".project/research/evidence-{dimension}.md",
            f"""# Evidence — {dimension}

## Finding: {dimension} finding

- **Claim**: The {dimension} claim is falsifiable.
- **Source**: https://example.test/{dimension}
- **Confidence**: high
- **Why it matters here**: It affects the demo intent.
""",
        )

    def write_research_handoff(self, root: Path) -> None:
        self.write(
            root,
            ".project/research/RESEARCH.md",
            """# Research Handoff

Phase: research
Status: complete
Intent: `.project/intent/INTENT.md`

## Dispatch
- `domain` — dispatched → `.project/research/evidence-domain.md` — assigned question
- `stack` — skipped → none — intent settles the stack
- `pitfalls` — skipped → none — no risk was assigned
- `similar` — skipped → none — no comparison is needed

## Question assignments
- `[RESEARCH] Which domain applies?` → `domain`
""",
        )
        self.write_evidence(root, "domain")

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

    def write_review_sources(self, root: Path) -> None:
        self.write(
            root,
            ".project/review/FINAL.md",
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
            ".project/review/final-gap-1.md",
            f"""# Gap Review — 1: project verify

Reviewed HEAD: {RESEARCH_HEAD}
Gap verdict: blocked
Risk: project Verify

## Finding

- **Found**: The project Verify risk is blocked.
- **Fix direction**: Run project Verify at the reviewed HEAD and fix the failure.
""",
        )

    def write_patch_findings(self, root: Path) -> None:
        self.write(
            root,
            ".project/review/PATCH-FINDINGS.md",
            f"""# Patch Findings

Reviewed HEAD: {RESEARCH_HEAD}
State: review/blocked

## Findings
### P001 — demo criterion
- **Source**: `.project/review/FINAL.md`
- **Locator**: `SC1`
- **Evidence**: The demo does not run.
- **Fix direction**: Make the demo run and rerun the criterion.

### P002 — project verify
- **Source**: `.project/review/final-gap-1.md`
- **Locator**: `Risk: project Verify`
- **Evidence**: The project Verify risk is blocked.
- **Fix direction**: Run project Verify at the reviewed HEAD and fix the failure.
""",
        )

    def test_patch_findings_validate_selected_sources_and_reviewed_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "review", "blocked")
            self.write_review_sources(root)
            self.write_patch_findings(root)

            result = check_handoffs.validate_patch_findings(root)

            self.assertEqual(result["phase"], "review")
            self.assertEqual(result["findings"], ["P001", "P002"])
            self.assertEqual(result["reviewed_head"], RESEARCH_HEAD)

    def test_patch_findings_reject_a_source_with_a_different_reviewed_head(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "review", "blocked")
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
            self.write_state(root, "review", "blocked")
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
            self.write_state(root, "review", "blocked")
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


if __name__ == "__main__":
    unittest.main()
