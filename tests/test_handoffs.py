import contextlib
import io
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import check_handoffs


RESEARCH_HEAD = "a" * 40


def git(root: Path, *arguments: str) -> None:
    subprocess.run(
        ("git", "-C", str(root), *arguments),
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=True,
    )


def git_output(root: Path, *arguments: str) -> str:
    return subprocess.run(
        ("git", "-C", str(root), *arguments),
        encoding="utf-8", errors="replace",
        capture_output=True,
        check=True,
    ).stdout.strip()


ROADMAP = """# Roadmap — demo

## Milestones

### M001 — demo
Goal: First release
Depends on: []
Surfaces: Demo web app
Status: active
Archive: null
Integrated: null
Scope: in
- First capability
Scope: out
- None
Success criteria
1. First works
Risks
- Delivery risk
Open questions
- None
"""


SURFACE_CONTRACT = """
## Surface contract

### Demo web app — T001

Criteria: SC1
Entry: `/demo`
States: empty shows the starter card, loading a spinner, error a retry, success the report.
Walkthrough:
1. Open `/demo` and see the starter card.
"""


class HandoffValidationTests(unittest.TestCase):
    def write(self, root: Path, relative: str, content: str) -> None:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode("utf-8"))

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

    def write_dimension_assignment_case(
        self,
        root: Path,
        assignment_rows,
        dispatched_dimensions=("stack", "pitfalls"),
        questions=("Which approach is viable?",),
    ) -> None:
        self.write_state(root, "research", "active")
        question_text = "".join(f"- [RESEARCH] {question}\n" for question in questions)
        self.write_intent(root, question_text)

        dispatch_rows = []
        for dimension in check_handoffs.STANDARD_DIMENSIONS:
            if dimension in dispatched_dimensions:
                dispatch_rows.append(
                    f"- `{dimension}` — dispatched → `.project/research/evidence-{dimension}.md` — assigned question"
                )
            else:
                dispatch_rows.append(
                    f"- `{dimension}` — skipped → none — no question needs this dimension"
                )
        handoff = "\n".join(
            [
                "# Research Handoff",
                "",
                "Phase: research",
                "Status: complete",
                "Intent: `.project/intent/INTENT.md`",
                "",
                "## Dispatch",
                *dispatch_rows,
                "",
                "## Question assignments",
                *assignment_rows,
                "",
            ]
        )
        self.write(root, ".project/research/RESEARCH.md", handoff)
        for dimension in dispatched_dimensions:
            self.write_evidence(root, dimension, questions=questions)

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
            handoff.write_bytes(
                handoff.read_text(encoding="utf-8").replace(
                    "Intent: `.project/intent/INTENT.md`",
                    "Intent: `.project/CHARTER.md`",
                ).encode("utf-8"),
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

    def test_research_question_can_target_multiple_dispatched_dimensions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_dimension_assignment_case(
                root,
                ("- `[RESEARCH] Which approach is viable?` → `stack`, `pitfalls`",),
            )

            result = check_handoffs.validate_research(root)

            self.assertEqual(result["dispatched"], ["pitfalls", "stack"])
            self.assertEqual(result["questions"], 1)
            for dimension in ("stack", "pitfalls"):
                evidence = (root / f".project/research/evidence-{dimension}.md").read_text(
                    encoding="utf-8"
                )
                self.assertIn("Questions assigned: Which approach is viable?", evidence)

    def test_research_multi_dimension_assignment_requires_each_evidence_file(self) -> None:
        for dimension in ("stack", "pitfalls"):
            with self.subTest(dimension=dimension), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_dimension_assignment_case(
                    root,
                    ("- `[RESEARCH] Which approach is viable?` → `stack`, `pitfalls`",),
                )
                (root / f".project/research/evidence-{dimension}.md").unlink()

                with self.assertRaisesRegex(check_handoffs.HandoffError, dimension):
                    check_handoffs.validate_research(root)

    def test_research_multi_dimension_assignments_reject_invalid_rows(self) -> None:
        question_row = "- `[RESEARCH] Which approach is viable?` → `stack`, `pitfalls`"
        cases = (
            (
                "repeated target",
                ("- `[RESEARCH] Which approach is viable?` → `stack`, `stack`",),
                "repeats a target in a question assignment",
            ),
            (
                "undispatched target",
                ("- `[RESEARCH] Which approach is viable?` → `domain`",),
                "every assigned question must target a dispatched dimension",
            ),
            (
                "repeated question row",
                (question_row, question_row),
                "repeats a question assignment",
            ),
            (
                "mixed none and question row",
                ("- none", question_row),
                "mixes none with question assignments",
            ),
            (
                "unformatted comma-separated targets",
                ("- `[RESEARCH] Which approach is viable?` → `stack`, pitfalls",),
                "malformed question assignment",
            ),
        )
        for name, assignment_rows, error in cases:
            with self.subTest(case=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_dimension_assignment_case(root, assignment_rows)

                with self.assertRaisesRegex(check_handoffs.HandoffError, error):
                    check_handoffs.validate_research(root)

    def test_each_dispatched_dimension_still_needs_an_assigned_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_dimension_assignment_case(
                root,
                ("- `[RESEARCH] Which approach is viable?` → `stack`",),
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "dispatched pitfalls has no assigned research question",
            ):
                check_handoffs.validate_research(root)

    def test_research_can_skip_every_settled_dimension(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
            self.write_intent(root, "- None\n")
            self.write(
                root, ".project/research/RESEARCH.md",
                "# Research\n\nPhase: research\nStatus: complete\nIntent: .project/intent/INTENT.md\n\n"
                "## Dispatch\n" + "".join(
                    f"- `{dimension}` — skipped → none — approved intent has no open question\n"
                    for dimension in check_handoffs.STANDARD_DIMENSIONS
                ) + "\n## Question assignments\n- none\n",
            )
            result = check_handoffs.validate_research(root)
            self.assertEqual(result["dispatched"], [])
            self.assertEqual(result["questions"], 0)
            self.assertEqual(set(result["skipped"]), set(check_handoffs.STANDARD_DIMENSIONS))
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            with self.assertRaisesRegex(check_handoffs.HandoffError, "question assignments"):
                check_handoffs.validate_research(root)

    def test_research_transition_validates_evidence_before_writing_state(self):
        source = Path(__file__).resolve().parents[1]
        helpers = [source / "scripts/pipeline_state.py", *sorted(source.glob("skills/*/scripts/pipeline_state.py"))]
        for helper in helpers:
            for track in (".project", ".project/next"):
                for status in ("active", "done"):
                    with self.subTest(helper=helper, track=track, status=status), tempfile.TemporaryDirectory() as directory:
                        root = Path(directory)
                        self.write_state(root, "research", status, track)
                        self.write_intent(root, "- [RESEARCH] Which domain applies?\n", track)
                        self.write_research_handoff(root, track)
                        state = root / track / "STATE.md"
                        evidence = root / track / "research/evidence-domain.md"
                        valid = evidence.read_text(encoding="utf-8")
                        evidence.write_bytes(valid.replace("Questions assigned: Which domain applies?", "Questions assigned: wrong").encode("utf-8"))
                        original = state.read_bytes()
                        command = [sys.executable, "-B", str(helper), "transition", "--repo", str(root),
                                   "--project-dir", track, "--expect-phase", "research", "--expect-status", status,
                                   "--expect-branch", "null" if track.endswith("next") else "gsd-path/M001",
                                   "--expect-archive", "null", "--set-phase", "research" if status == "active" else "decide",
                                   "--set-status", "done" if status == "active" else "active", "--event", "research gate"]
                        failed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
                        self.assertNotEqual(failed.returncode, 0, failed.stdout)
                        self.assertIn("Questions assigned", failed.stderr)
                        self.assertEqual(state.read_bytes(), original)
                        evidence.write_bytes(valid.encode("utf-8"))
                        passed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
                        self.assertEqual(passed.returncode, 0, passed.stderr)
                        self.assertNotEqual(state.read_bytes(), original)

    def test_research_handoff_rejects_done_state_before_the_gate(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "done")
            self.write_intent(root, "- [RESEARCH] Which domain applies?\n")
            self.write_research_handoff(root)

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "STATE.md must be one of decide/active, research/active",
            ):
                check_handoffs.validate_research(root)

    def test_research_handoff_cli_runs_at_decide_active(self) -> None:
        script = Path(__file__).resolve().parents[1] / "scripts/check_handoffs.py"
        for track in (".project", ".project/next"):
            with self.subTest(track=track), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_state(root, "decide", "active", track)
                self.write_intent(root, "- [RESEARCH] Which domain applies?\n", track)
                self.write_research_handoff(root, track)
                command = [sys.executable, "-B", str(script), "research",
                           "--repo", str(root), "--project-dir", track]
                passed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
                self.assertEqual(passed.returncode, 0, passed.stderr)
                self.assertIn('"dispatched": ["domain"]', passed.stdout)

                evidence = root / track / "research/evidence-domain.md"
                evidence.write_bytes(evidence.read_text(encoding="utf-8").replace(
                    "Questions assigned: Which domain applies?", "Questions assigned: wrong").encode("utf-8"))
                failed = subprocess.run(command, capture_output=True, encoding="utf-8", errors="replace")
                self.assertNotEqual(failed.returncode, 0, failed.stdout)
                self.assertIn("Questions assigned", failed.stderr)

    def test_frontmatter_keeps_a_hash_inside_a_quoted_value(self) -> None:
        values = check_handoffs._strict_frontmatter(
            '---\ntitle: "Fix issue #12"  # comment\nfiles: [a.py, "b#.py"] # note\n'
            "deps:\n  - 'T00#1' # first\n---\n",
            "task",
        )
        self.assertEqual(values["title"], "Fix issue #12")
        self.assertEqual(values["files"], ["a.py", "b#.py"])
        self.assertEqual(values["deps"], ["T00#1"])

    def test_placeholder_scan_ignores_code_spans_not_whole_quoted_tokens(self) -> None:
        self.assertEqual(
            check_handoffs._non_placeholder(
                "`Record<ApprovalPolicyV1, { stage: ScheduleSweepStage }>`",
                "x",
            ),
            "Record<ApprovalPolicyV1, { stage: ScheduleSweepStage }>",
        )
        self.assertEqual(
            check_handoffs._non_placeholder("`Queues unavailable: <stored reason>`", "x"),
            "Queues unavailable: <stored reason>",
        )
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._non_placeholder("`<fill in>`", "label")
        self.assertIn("<fill in>", str(failure.exception))
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._non_placeholder("Queues unavailable: <stored reason>", "label")
        self.assertIn("<stored reason>", str(failure.exception))

    def test_repair_source_scans_intact_code_spans(self) -> None:
        for ticks in ("`", "``", "```"):
            evidence = f"{ticks}Queues unavailable: <stored reason>{ticks}"
            text = (
                "### SC1 — Demo\n"
                "- **Verdict**: not-met\n"
                f"- **Finding**: {evidence}\n"
                "- **Fix direction**: Restore queues\n"
            )
            with self.subTest(ticks=ticks):
                self.assertEqual(
                    check_handoffs._source_repair_fields("FINAL.md", text, "SC1"),
                    ("Queues unavailable: <stored reason>", "Restore queues"),
                )
                with self.assertRaises(check_handoffs.HandoffError):
                    check_handoffs._source_repair_fields(
                        "FINAL.md", text.replace(evidence, f"{ticks}<record observation>{ticks}"), "SC1"
                    )

    def test_placeholder_checks_accept_comparison_angle_brackets(self) -> None:
        self.assertEqual(
            check_handoffs._non_placeholder("p95 latency < 200ms and > 0", "x"),
            "p95 latency < 200ms and > 0",
        )
        block = "- **Finding**: p95 < 200ms\n- **Fix direction**: <describe the fix>\n"
        self.assertEqual(
            check_handoffs._source_field(block, "Finding", "review"), "p95 < 200ms"
        )
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._source_field(block, "Fix direction", "review")
        self.assertIn("<describe the fix>", str(failure.exception))
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._non_placeholder("<fill in>", "label")
        self.assertIn("label still contains the placeholder <fill in>", str(failure.exception))

    def test_task_log_is_exempt_from_the_placeholder_scan(self) -> None:
        """Log is append-only and immutable after landing, so it cannot be repaired."""
        def task(log: str, context: str = "Real context.") -> str:
            return (
                "---\n"
                "id: T001\n"
                "title: Demo task\n"
                "status: pending\n"
                "agent: null\n"
                "base: null\n"
                "worktree: null\n"
                "task_branch: null\n"
                "---\n\n"
                "## Context\n\n" + context + "\n\n"
                "## Approach\n\nReal approach.\n\n"
                "## Interface contract\n\nReal contract.\n\n"
                "## Log\n\n" + log + "\n"
            )

        # Unquoted <name> notation in Log is accepted: coders write key formats.
        check_handoffs._require_task_structure(
            "T001", task("Keyed report-schedule:<versionId>:<instant>."), initial=True
        )
        # The contract fields are still scanned.
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._require_task_structure(
                "T001", task("Real log.", context="<fill in the context>"), initial=True
            )
        self.assertIn("Context", str(failure.exception))
        for heading in ("Context", "Approach", "Interface contract"):
            for ticks in ("`", "``", "```"):
                with self.subTest(heading=heading, ticks=ticks):
                    text = task("Real log.")
                    body = check_handoffs._section(text, heading).strip()
                    with self.assertRaisesRegex(check_handoffs.HandoffError, heading):
                        check_handoffs._require_task_structure(
                            "T001", text.replace(body, f"{ticks}<record observation>{ticks}"), initial=True
                        )
        # Log must still be non-empty.
        with self.assertRaises(check_handoffs.HandoffError) as failure:
            check_handoffs._require_task_structure("T001", task(""), initial=True)
        self.assertIn("Log", str(failure.exception))

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
            evidence.write_bytes(
                evidence.read_text(encoding="utf-8").replace(
                    "- Which domain applies? → The evidence answers this with the cited source.\n",
                    "",
                ).encode("utf-8"),
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

    def test_research_rejects_a_settled_standard_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
            self.write_intent(root, "- none\n")
            self.write_research_handoff(root)
            handoff = root / ".project/research/RESEARCH.md"
            handoff.write_bytes(handoff.read_text(encoding="utf-8").replace(
                "- `[RESEARCH] Which domain applies?` → `domain`", "- none"
            ).encode("utf-8"))
            self.write_evidence(root, "domain", questions=())
            with self.assertRaisesRegex(check_handoffs.HandoffError, "no assigned research question"):
                check_handoffs.validate_research(root)

    def test_research_handoff_rejects_dispatch_without_a_question(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "research", "active")
            self.write_intent(root, "")
            self.write_custom_only_research_handoff(root)

            with self.assertRaisesRegex(check_handoffs.HandoffError, "no assigned research question"):
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
            final_review.write_bytes(
                final_review.read_text(encoding="utf-8").replace(
                    RESEARCH_HEAD, "b" * 40
                ).encode("utf-8"),
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
            patch.write_bytes(
                patch.read_text(encoding="utf-8").replace("`SC1`", "`SC2`", 1).encode("utf-8"),
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
            patch.write_bytes(
                patch.read_text(encoding="utf-8").replace(
                    "The demo does not run.", "An invented failure.", 1
                ).encode("utf-8"),
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
                patch.write_bytes(
                    patch.read_text(encoding="utf-8").replace(
                        "### P002 — project verify", malformed
                    ).encode("utf-8"),
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
        self, root: Path, project_dir: str = ".project", surfaces: str = "none"
    ) -> None:
        self.write(
            root,
            f"{project_dir}/intent/INTENT.md",
            f"""# Intent — demo

Surfaces: {surfaces}

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
        surface_contract: str = "",
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
{surface_contract}
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

    def test_build_plan_gate_preserves_progress_and_checks_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            task = root / ".project/tasks/T001-demo.md"
            progressed = task.read_text(encoding="utf-8").replace("status: pending", "status: done").replace(
                "base: null", "base: " + "a" * 40
            ).replace("agent: null", "agent: /root/build_t001")
            task.write_bytes(progressed.encode("utf-8"))
            # Patch mode: a landed task keeps its metadata while planning reopens.
            self.assertEqual(check_handoffs.validate_plan(root)["tasks"], 2)
            task.write_bytes(progressed.replace("status: done", "status: pending").encode("utf-8"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "initially"):
                check_handoffs.validate_plan(root)
            task.write_bytes(progressed.encode("utf-8"))
            self.write_state(root, "build", "active")
            self.assertEqual(check_handoffs.validate_plan(root)["tasks"], 2)
            self.assertEqual(task.read_text(encoding="utf-8"), progressed)
            task.write_bytes(progressed.replace("- SC1", "- SC2").encode("utf-8"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "Intent coverage"):
                check_handoffs.validate_plan(root)

    def test_plan_coverage_maps_each_success_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["phase"], "plan")
            self.assertEqual(result["criteria"], ["SC1", "SC2"])
            self.assertEqual(result["rows"], 2)
            self.assertEqual(result["tasks"], 2)

    def test_plan_preserves_inline_code_in_surface_names(self) -> None:
        surface = "CLI — `reports.py STORE total`; `reports.py STORE csv`"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces=surface)
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT.replace("Demo web app", surface),
            )

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["surfaces"], {surface: "T001"})

    def test_plan_accepts_typed_interface_and_rejects_unfilled_body(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            task = root / ".project/tasks/T001-demo.md"
            text = task.read_text(encoding="utf-8").replace(
                "## Interface contract\n\n- None",
                "## Interface contract\n\n- `total_amount(records) -> int`: return the sum.",
            )
            task.write_bytes(text.encode("utf-8"))
            self.assertEqual(check_handoffs.validate_plan(root)["tasks"], 2)
            task.write_bytes(text.replace("return the sum.", "<fill in>").encode("utf-8"))
            with self.assertRaisesRegex(check_handoffs.HandoffError, "placeholder"):
                check_handoffs.validate_plan(root)

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
            (root / ".project/tasks/notes.md").write_bytes(
                "post-review notes\n".encode("utf-8")
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "non-canonical task artifact"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_skips_an_ignored_ds_store_in_tasks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(("git", "init", "-q", str(root)), check=True)
            (root / ".git" / "info" / "exclude").write_bytes(".DS_Store\n".encode("utf-8"))
            self.write_plan_handoff(root)
            (root / ".project/tasks/.DS_Store").write_bytes("finder\n".encode("utf-8"))

            self.assertEqual(check_handoffs.validate_plan(root)["tasks"], 2)

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
            state.write_bytes(
                state.read_text(encoding="utf-8").replace("project: demo\n", "").encode("utf-8"),
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

    def test_plan_requires_a_surface_contract_for_each_declared_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("missing ## Surface contract", str(failure.exception))

    def test_plan_accepts_a_complete_surface_contract(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)

            result = check_handoffs.validate_plan(root)
            self.assertEqual(result["surfaces"], {"Demo web app": "T001"})

    def test_plan_allows_embedded_angle_brackets_in_surface_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            contract = (
                SURFACE_CONTRACT.replace("Entry: `/demo`", "Entry: GET /users/<id>")
                .replace(
                    "States: empty shows the starter card, loading a spinner, "
                    "error a retry, success the report.",
                    "States: inline <empty> state, loading, error, and success.",
                )
                .replace(
                    "Open `/demo` and see the starter card.",
                    "Run tool < request.json and inspect the response.",
                )
            )
            self.write_plan_coverage(root, surface_contract=contract)

            result = check_handoffs.validate_plan(root)
            self.assertEqual(result["surfaces"], {"Demo web app": "T001"})

            self.write_plan_coverage(
                root,
                surface_contract=contract.replace(
                    "Entry: GET /users/<id>",
                    "Entry: <the route, screen, or command a person opens>",
                ),
            )
            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "Demo web app surface Entry is still a placeholder",
                str(failure.exception),
            )

    def test_plan_distinguishes_bracketed_states_from_a_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            states = "<empty> shows help; <success> shows the report"
            contract = SURFACE_CONTRACT.replace(
                "empty shows the starter card, loading a spinner, "
                "error a retry, success the report.",
                states,
            )
            self.write_plan_coverage(root, surface_contract=contract)

            result = check_handoffs.validate_plan(root)
            self.assertEqual(result["surfaces"], {"Demo web app": "T001"})

            self.write_plan_coverage(
                root,
                surface_contract=contract.replace(
                    states,
                    "<what empty, loading, error, and success each show>",
                ),
            )
            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "Demo web app surface States is still a placeholder",
                str(failure.exception),
            )

    def test_plan_rejects_surface_blocks_when_intent_declares_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            message = str(failure.exception)
            self.assertIn("Demo web app", message)
            self.assertIn("INTENT.md declares no surfaces", message)

    def test_plan_rejects_a_criterion_shared_by_multiple_surfaces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app, Demo CLI")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT
                + SURFACE_CONTRACT.replace("## Surface contract\n\n", "").replace(
                    "Demo web app", "Demo CLI"
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            message = str(failure.exception)
            self.assertIn("SC1", message)
            self.assertIn("Demo web app", message)
            self.assertIn("Demo CLI", message)

    def test_plan_rejects_a_duplicate_surface_heading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT
                + SURFACE_CONTRACT.replace("## Surface contract\n\n", ""),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "Surface contract repeats the Demo web app surface",
                str(failure.exception),
            )

    def test_plan_rejects_a_duplicate_surface_contract_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT + SURFACE_CONTRACT,
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "PLAN.md repeats ## Surface contract",
                str(failure.exception),
            )

    def test_plan_rejects_a_surface_block_without_a_walkthrough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT.replace(
                    "1. Open `/demo` and see the starter card.\n", ""
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("Walkthrough has no steps", str(failure.exception))

    def test_plan_rejects_a_placeholder_walkthrough_step(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT.replace(
                    "Open `/demo` and see the starter card.",
                    "<step a reviewer performs>",
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "Demo web app surface Walkthrough step 1 is still a placeholder",
                str(failure.exception),
            )

    def test_plan_rejects_surface_criteria_the_owning_task_does_not_own(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                rows="| SC1 | T002 | AC1 |\n| SC2 | T002 | AC2 |\n",
                surface_contract=SURFACE_CONTRACT,
            )
            self.write_coverage_task(root, "T001", "- None")
            self.write_coverage_task(
                root,
                "T002",
                "- SC1\n- SC2",
                acceptance=(
                    "1. The demo command prints hello.\n"
                    "2. The demo test suite is green."
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "surface criteria are not owned by T001: SC1", str(failure.exception)
            )

    def test_plan_rejects_repeated_criteria_within_a_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                rows="| SC1 | T001 | AC1 |\n| SC2 | T001 | AC2 |\n",
                surface_contract=SURFACE_CONTRACT.replace(
                    "Criteria: SC1",
                    "Criteria: SC1\nCriteria: SC2",
                ),
            )
            self.write_coverage_task(
                root,
                "T001",
                "- SC1\n- SC2",
                acceptance=(
                    "1. The demo command prints hello.\n"
                    "2. The demo test suite is green."
                ),
            )
            self.write_coverage_task(root, "T002", "- None")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "Demo web app surface repeats Criteria",
                str(failure.exception),
            )

    def test_plan_rejects_repeated_entry_and_states_fields(self) -> None:
        fields = (
            ("Entry", "Entry: `/demo#tab`", "Entry: `/admin`"),
            (
                "States",
                "States: empty, loading, error, and success are visible.",
                "States: success only.",
            ),
        )
        for field, first, duplicate in fields:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_plan_handoff(root)
                    self.write_intent_criteria(root, surfaces="Demo web app")
                    original = next(
                        line
                        for line in SURFACE_CONTRACT.splitlines()
                        if line.startswith(f"{field}:")
                    )
                    self.write_plan_coverage(
                        root,
                        surface_contract=SURFACE_CONTRACT.replace(
                            original,
                            f"{first}\n{duplicate}",
                        ),
                    )

                    with self.assertRaises(check_handoffs.HandoffError) as failure:
                        check_handoffs.validate_plan(root)
                    self.assertIn(
                        f"Demo web app surface repeats {field}",
                        str(failure.exception),
                    )

    def test_surfaces_splits_only_on_top_level_commas(self) -> None:
        text = (
            "Surfaces: HTTP API (/api/v1 — revizie complete, ticket revizii list), "
            "Filament back office (ticket view)\n"
        )
        surfaces = check_handoffs._surfaces(text, "INTENT.md")
        self.assertEqual(
            surfaces,
            [
                "HTTP API (/api/v1 — revizie complete, ticket revizii list)",
                "Filament back office (ticket view)",
            ],
        )

    def test_plan_rejects_an_empty_surface_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces=",")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("names no surface", str(failure.exception))

    def test_plan_rejects_walkthrough_steps_outside_the_walkthrough(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT.replace(
                    "Walkthrough:\n1. Open `/demo` and see the starter card.",
                    "1. Open `/demo` and see the starter card.\nWalkthrough:",
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("Walkthrough has no steps", str(failure.exception))

    def test_plan_rejects_surfaces_that_differ_from_the_roadmap_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="none")
            self.write(root, ".project/ROADMAP.md", ROADMAP)

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn("do not match ROADMAP.md demo", str(failure.exception))

    def test_plan_requires_one_matching_roadmap_milestone_slug(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write(
                root,
                ".project/ROADMAP.md",
                ROADMAP.replace("### M001 — demo", "### M001 — demo-ui"),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "ROADMAP.md is missing milestone slug demo",
                str(failure.exception),
            )

            duplicate = ROADMAP.replace(
                "# Roadmap — demo\n\n## Milestones\n\n### M001 — demo",
                "### M002 — demo",
            )
            self.write(root, ".project/ROADMAP.md", ROADMAP + "\n" + duplicate)
            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "ROADMAP.md repeats milestone slug demo",
                str(failure.exception),
            )

    def test_roadmap_gate_requires_surfaces_on_an_unshipped_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "roadmap", "active")
            self.write(
                root,
                ".project/ROADMAP.md",
                ROADMAP.replace("Surfaces: Demo web app\n", "").replace(
                    "Status: active", "Status: pending"
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_roadmap(root)
            self.assertIn("M001 is missing Surfaces", str(failure.exception))

    def test_roadmap_rejects_repeated_surfaces_within_one_milestone(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "roadmap", "active")
            second_milestone = ROADMAP.replace(
                "# Roadmap — demo\n\n## Milestones\n\n### M001 — demo",
                "### M002 — second",
            ).replace("Surfaces: Demo web app", "Surfaces: Demo CLI")
            roadmap = ROADMAP + "\n" + second_milestone
            self.write(root, ".project/ROADMAP.md", roadmap)

            result = check_handoffs.validate_roadmap(root)
            self.assertEqual(result["milestones"], ["M001", "M002"])

            self.write(
                root,
                ".project/ROADMAP.md",
                roadmap.replace(
                    "Surfaces: Demo web app\n",
                    "Surfaces: Demo web app\nSurfaces: Demo CLI\n",
                    1,
                ),
            )
            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_roadmap(root)
            self.assertIn("M001 repeats Surfaces", str(failure.exception))

    def test_roadmap_rejects_duplicate_and_mixed_none_surfaces(self) -> None:
        cases = (
            ("Demo web app, demo WEB APP", "demo WEB APP"),
            ("none, Demo web app", "none"),
        )
        for surfaces, offending in cases:
            with self.subTest(surfaces=surfaces):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_state(root, "roadmap", "active")
                    self.write(
                        root,
                        ".project/ROADMAP.md",
                        ROADMAP.replace("Demo web app", surfaces),
                    )

                    with self.assertRaises(check_handoffs.HandoffError) as failure:
                        check_handoffs.validate_roadmap(root)
                    self.assertIn(offending, str(failure.exception))

    def test_plan_allows_project_verify_when_an_owned_sc_names_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "plan", "active")
            self.write(
                root,
                ".project/intent/INTENT.md",
                """# Intent — demo

Surfaces: none

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

    def test_plan_allows_same_wave_overlap_between_landed_tasks(self) -> None:
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
            self.write_coverage_task(root, "T001", "- SC1", files="src/app.py")
            self.write_coverage_task(
                root,
                "T002",
                "- SC2",
                acceptance="1. The demo test suite is green.",
                files="src/app.py",
            )
            for task_id in ("T001", "T002"):
                path = next(root.glob(f".project/tasks/{task_id}-*.md"))
                path.write_bytes(
                    path.read_text(encoding="utf-8")
                    .replace("status: pending", "status: done")
                    .replace("agent: null", "agent: coder")
                    .encode("utf-8")
                )
            check_handoffs.validate_plan(root)

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
            synthesis.write_bytes(
                synthesis.read_text(encoding="utf-8").replace(
                    "- **Evidence**: evidence-stack.md § Storage\n", ""
                ).encode("utf-8"),
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
            roadmap.write_bytes(
                roadmap.read_text(encoding="utf-8").replace(
                    "### M001 — first", "### M001 — renamed"
                ).encode("utf-8"),
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

    def test_wave_accepts_empty_lens_without_consuming_next_field(self) -> None:
        for field in ("Lens:", "Lens: \t"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_plan_handoff(root)
                relative = self.write_wave_review(root)
                review = root / relative
                review.write_bytes(review.read_text(encoding="utf-8").replace(
                    "Tasks reviewed:", field + "\nTasks reviewed:",
                ).encode("utf-8"))
                result = check_handoffs.validate_wave(root, review=relative)
                self.assertEqual(result["verdict"], "pass")
                review.write_bytes(review.read_text(encoding="utf-8").replace(field + "\n", "Lens: contract\n").encode("utf-8"))
                with self.assertRaisesRegex(check_handoffs.HandoffError, "must not declare a review lens"):
                    check_handoffs.validate_wave(root, review=relative)

    def test_wave_requires_owned_sc_headings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)

            result = check_handoffs.validate_wave(root, review=relative)

            self.assertEqual(result["owned"], ["SC1", "SC2"])
            self.assertEqual(result["verdict"], "pass")

    def test_reviews_bind_the_full_wrapped_intent_criterion(self) -> None:
        for phase in ("wave", "final"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_plan_handoff(root)
                if phase == "wave":
                    relative = self.write_wave_review(root)
                    validate = lambda: check_handoffs.validate_wave(root, review=relative)
                else:
                    self.write_state(root, "ship", "active")
                    self.write_final_review(root)
                    relative = ".project/review/FINAL.md"
                    validate = lambda: check_handoffs.validate_final(root)
                intent = root / ".project/intent/INTENT.md"
                intent.write_bytes(intent.read_text(encoding="utf-8").replace(
                    "1. The demo command prints hello.",
                    "1. The demo command prints\n   hello.\n   It preserves signed integers.",
                ).encode("utf-8"))
                review = root / relative
                original = review.read_text(encoding="utf-8")
                review.write_bytes(original.replace(
                    "### SC1 — The demo command prints hello.",
                    "### SC1 — The demo command prints hello. It preserves signed integers.",
                ).encode("utf-8"))
                self.assertEqual(validate()["verdict"], "pass")
                review.write_bytes(original.encode("utf-8"))
                with self.assertRaisesRegex(
                    check_handoffs.HandoffError, "SC1 heading text differs from INTENT.md"
                ):
                    validate()

    def test_reviews_bind_intent_criterion_with_sub_bullet_continuations(self) -> None:
        joined = (
            "At a store with a due review: - The board lists the store. "
            "- The dashboard shows a badge."
        )
        for phase in ("wave", "final"):
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_plan_handoff(root)
                if phase == "wave":
                    relative = self.write_wave_review(root)
                    validate = lambda: check_handoffs.validate_wave(root, review=relative)
                else:
                    self.write_state(root, "ship", "active")
                    self.write_final_review(root)
                    relative = ".project/review/FINAL.md"
                    validate = lambda: check_handoffs.validate_final(root)
                intent = root / ".project/intent/INTENT.md"
                intent.write_bytes(
                    intent.read_text(encoding="utf-8")
                    .replace(
                        "1. The demo command prints hello.",
                        "1. At a store with a due review:\n"
                        "   - The board lists the store.\n"
                        "   - The dashboard shows a badge.",
                    )
                    .encode("utf-8")
                )
                review = root / relative
                original = review.read_text(encoding="utf-8")
                review.write_bytes(
                    original.replace(
                        "### SC1 — The demo command prints hello.",
                        f"### SC1 — {joined}",
                    ).encode("utf-8")
                )
                self.assertEqual(validate()["verdict"], "pass")
                review.write_bytes(
                    original.replace(
                        "### SC1 — The demo command prints hello.",
                        "### SC1 — At a store with a due review: The board lists the store. "
                        "The dashboard shows a badge.",
                    ).encode("utf-8")
                )
                with self.assertRaisesRegex(
                    check_handoffs.HandoffError, "SC1 heading text differs from INTENT.md"
                ):
                    validate()

    def test_wave_checks_evidence_after_exact_quoted_task_criterion(self) -> None:
        for verdict, marker in (("pass", "✅"), ("fail", "❌")):
            with self.subTest(verdict=verdict), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_plan_handoff(root)
                relative = self.write_wave_review(root)
                criterion = "AC1 — `hello.py <integer>` prints the signed integer."
                self.write_coverage_task(
                    root, "T001", "- SC1",
                    acceptance="1. AC1 — `hello.py <integer>` prints\n   the signed integer.",
                )
                review = root / relative
                original = review.read_text(encoding="utf-8").replace(
                    "## T001 — Demo task T001: pass", f"## T001 — Demo task T001: {verdict}"
                )
                if verdict == "fail":
                    original = original.replace("Wave verdict: pass", "Wave verdict: blocked")
                old = "- ✅ The demo command prints hello. — ran hello.py"
                review.write_bytes(original.replace(old, f"- {marker} {criterion} — ran hello.py 7; stdout 7").encode("utf-8"))
                result = check_handoffs.validate_wave(root, review=relative)
                self.assertEqual(result["verdict"], "pass" if verdict == "pass" else "blocked")
                for evidence in ("<observed result>", "none", ""):
                    with self.subTest(evidence=evidence):
                        review.write_bytes(original.replace(old, f"- {marker} {criterion} — {evidence}").encode("utf-8"))
                        with self.assertRaises(check_handoffs.HandoffError):
                            check_handoffs.validate_wave(root, review=relative)
                review.write_bytes(original.replace(
                    old,
                    f"- {marker} AC1 — `other.py <integer>` prints the signed integer. — <observed result>",
                ).encode("utf-8"))
                with self.assertRaisesRegex(check_handoffs.HandoffError, "placeholder"):
                    check_handoffs.validate_wave(root, review=relative)

    def test_wave_rejects_placeholder_task_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_bytes(
                review.read_text(encoding="utf-8").replace(
                    "- ✅ The demo command prints hello. — ran hello.py",
                    "- ✅ none",
                ).encode("utf-8"),
            )

            with self.assertRaisesRegex(check_handoffs.HandoffError, "is empty"):
                check_handoffs.validate_wave(root, review=relative)

    def test_wave_requires_evidence_under_each_owned_sc(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            relative = self.write_wave_review(root)
            review = root / relative
            review.write_bytes(
                review.read_text(encoding="utf-8").replace(
                    "- ✅ hello.py output\n", ""
                ).encode("utf-8"),
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
            review.write_bytes(
                review.read_text(encoding="utf-8").replace("### SC2 —", "### SC9 —").encode("utf-8"),
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
            review.write_bytes(
                review.read_text(encoding="utf-8").replace(
                    "## T002 — Demo task T002: pass",
                    "## T003 — Demo task T003: pass",
                ).encode("utf-8"),
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
            review.write_bytes(
                review.read_text(encoding="utf-8").replace(
                    "Tasks reviewed: 2", "Tasks reviewed: 1"
                ).encode("utf-8"),
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
        observed: str = "hello",
        surface: str = "",
        project_dir: str = ".project",
    ) -> None:
        if not (root / ".git").exists():
            git(root, "init", "-q", "-b", "gsd-path/M001")
            git(root, "config", "user.email", "test@example.test")
            git(root, "config", "user.name", "Test")
            git(root, "add", ".")
            git(root, "commit", "-q", "-m", "reviewed product")
        reviewed_head = git_output(root, "rev-parse", "HEAD")
        surface = f"\n- **Surface**: {surface}" if surface else ""
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
- **Observed**: {observed}{surface}
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

    def test_final_requires_a_surface_criterion_to_name_its_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(root)

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("SC1 is missing Surface", str(failure.exception))

    def test_final_rejects_a_surface_criterion_walked_on_another_surface(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(root, surface="Some other screen")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("SC1 Surface must name Demo web app", str(failure.exception))

    def test_final_preserves_embedded_surface_delimiters(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="CLI `count.py`")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT.replace("Demo web app", "CLI `count.py`"))
            self.write_final_review(root, surface="CLI `count.py`")

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")

    def test_final_accepts_a_walked_surface_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(root, surface="Demo web app")

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")

    def test_final_accepts_embedded_angle_brackets_in_surface_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(
                root,
                check="tool < request.json",
                observed="the <empty> state renders the starter card",
                surface="Demo web app",
            )

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")

    def test_final_accepts_multiline_observed_sub_bullets(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(root, surface="Demo web app")
            final_path = root / ".project/review/FINAL.md"
            text = final_path.read_text(encoding="utf-8")
            text = text.replace(
                "- **Observed**: hello",
                """- **Observed**:
  - Both deactivations notified.
  - In the DB, rows stayed listed.""",
                1,
            )
            final_path.write_text(text, encoding="utf-8")

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")
            block = re.search(
                r"### SC1 — The demo command prints hello\.(.*)(?=### SC2)",
                text,
                re.DOTALL,
            )
            self.assertIsNotNone(block)
            observed = check_handoffs._raw_source_field(block.group(1), "Observed", "FINAL.md SC1")
            self.assertIn("Both deactivations notified.", observed)
            self.assertIn("In the DB, rows stayed listed.", observed)

    def test_final_rejects_a_surface_criterion_without_a_walked_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(root, surface="Demo web app", check="none")

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("lacks the walked Check", str(failure.exception))

    def test_final_rejects_absence_values_for_surface_evidence(self) -> None:
        cases = (
            ("Check", "n/a", "hello"),
            ("Observed", "`python3 hello.py`", "null"),
        )
        for field, check, observed in cases:
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_state(root, "ship", "active")
                    self.write_intent_criteria(root, surfaces="Demo web app")
                    self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
                    self.write_final_review(
                        root,
                        check=check,
                        observed=observed,
                        surface="Demo web app",
                    )

                    with self.assertRaises(check_handoffs.HandoffError) as failure:
                        check_handoffs.validate_final(root)
                    self.assertIn(
                        f"FINAL.md SC1 surface {field} is empty",
                        str(failure.exception),
                    )

    def test_final_rejects_quoted_absence_values_for_surface_evidence(self) -> None:
        cases = (
            ("Check", '"none"', "hello", "lacks the walked Check"),
            ("Observed", "`python3 hello.py`", "'null'", "surface Observed is empty"),
            ("Check", "`n/a`", "hello", "surface Check is empty"),
        )
        for field, check, observed, message in cases:
            with self.subTest(field=field, value=check if field == "Check" else observed):
                with tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    self.write_state(root, "ship", "active")
                    self.write_intent_criteria(root, surfaces="Demo web app")
                    self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
                    self.write_final_review(
                        root,
                        check=check,
                        observed=observed,
                        surface="Demo web app",
                    )

                    with self.assertRaises(check_handoffs.HandoffError) as failure:
                        check_handoffs.validate_final(root)
                    self.assertIn(message, str(failure.exception))

    def test_surface_values_reject_nested_quoted_placeholders_and_absence(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_plan_handoff(root)
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(
                root,
                surface_contract=SURFACE_CONTRACT.replace(
                    "Entry: `/demo`",
                    'Entry: " <the route, screen, or command a person opens> "',
                ),
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_plan(root)
            self.assertIn(
                "surface Entry is still a placeholder",
                str(failure.exception),
            )

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root, surfaces="Demo web app")
            self.write_plan_coverage(root, surface_contract=SURFACE_CONTRACT)
            self.write_final_review(
                root,
                observed='" \'null\' "',
                surface="Demo web app",
            )

            with self.assertRaises(check_handoffs.HandoffError) as failure:
                check_handoffs.validate_final(root)
            self.assertIn("surface Observed is empty", str(failure.exception))

    def test_final_rejects_pass_without_a_check_or_reference(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.write_state(root, "ship", "active")
            self.write_intent_criteria(root)
            self.write_final_review(root, check="none")
            final = root / ".project/review/FINAL.md"
            final.write_bytes(
                final.read_text(encoding="utf-8").replace(
                    "- **Reference**: hello.py:1",
                    "- **Reference**: none",
                ).encode("utf-8"),
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
            gap.write_bytes(
                gap.read_text(encoding="utf-8")
                .replace("Gap verdict: pass", "Gap verdict: blocked")
                .replace(
                    "- **Fix direction**: none",
                    "- **Fix direction**: Repair the integration and rerun the gap.",
                ).encode("utf-8"),
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
            final.write_bytes(
                final.read_text(encoding="utf-8").replace(
                    "- **Observed**: hello\n", ""
                ).encode("utf-8"),
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
            final.write_bytes(
                final.read_text(encoding="utf-8").replace(
                    "### SC1 — The demo command prints hello.",
                    "### SC1 — Something easier passes.",
                ).encode("utf-8"),
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
            final.write_bytes(
                final.read_text(encoding="utf-8").replace(
                    "- **Finding**: none\n",
                    "- **Finding**: none\n- **Finding**: none\n",
                    1,
                ).encode("utf-8"),
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "FINAL.md SC1 repeats Finding"
            ):
                check_handoffs.validate_final(root)

    def test_final_rejects_repeated_review_metadata_before_archiving(self) -> None:
        for name in ("FINAL.md", "final-gap-1.md"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.write_state(root, "ship", "active")
                self.write_intent_criteria(root)
                self.write_final_review(root)
                artifact = root / ".project/review" / name
                text = artifact.read_text(encoding="utf-8")
                header = next(line for line in text.splitlines()
                              if line.startswith("Reviewed HEAD:"))
                artifact.write_bytes((text + "\n## Recorded output\n\n" + header + "\n").encode("utf-8"))
                with self.assertRaisesRegex(check_handoffs.HandoffError,
                                            "repeats Reviewed HEAD"):
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
                check_handoffs.HandoffError, "is not the current HEAD"
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
            gap.write_bytes(
                gap.read_text(encoding="utf-8").replace(reviewed_head, "b" * 40).encode("utf-8"),
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
            gap.write_bytes(
                gap.read_text(encoding="utf-8").replace(
                    "# Gap Review — 1:", "# Gap Review — 2:"
                ).encode("utf-8"),
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
            gap.write_bytes(
                gap.read_text(encoding="utf-8").replace(
                    "Risk: Project verify", "Risk: release packaging"
                ).encode("utf-8"),
            )

            with self.assertRaisesRegex(
                check_handoffs.HandoffError,
                "heading risk does not match Risk field",
            ):
                check_handoffs.validate_final(root)


class SpecReachProbeTests(unittest.TestCase):
    """Spec-reach probes: Edge coverage, Prohibitions, Held-out checks, honest verifier."""

    write = HandoffValidationTests.write
    write_state = HandoffValidationTests.write_state
    write_intent_criteria = HandoffValidationTests.write_intent_criteria
    write_plan_coverage = HandoffValidationTests.write_plan_coverage
    write_coverage_task = HandoffValidationTests.write_coverage_task
    write_plan_handoff = HandoffValidationTests.write_plan_handoff
    write_final_review = HandoffValidationTests.write_final_review

    EDGE_HEAD = (
        "## Edge coverage\n\n"
        "| Edge | Criterion | Category | Disposition | Detail |\n"
        "|------|-----------|----------|-------------|--------|\n"
    )
    PROHIBITION_HEAD = (
        "## Prohibitions\n\n"
        "| Prohibition | Criterion | Must not | Disposition | Detail |\n"
        "|-------------|-----------|----------|-------------|--------|\n"
    )
    VALID_EDGES = (
        "| E1 | SC1 | boundary | held-out | the start date is inclusive |\n"
        "| E2 | SC1 | empty | dismissed | input is always a non-empty list |\n"
        "| E3 | SC2 | none | dismissed | static copy, no data shape |\n"
    )
    VALID_PROHIBITIONS = (
        "| N1 | SC2 | shame the user | judgment | wording is neutral, no guilt |\n"
        "| N2 | SC1 | none | dismissed | nothing else applies |\n"
    )

    def append_intent(self, root: Path, *sections: str) -> None:
        path = root / ".project/intent/INTENT.md"
        text = path.read_text(encoding="utf-8").rstrip("\n") + "\n\n"
        path.write_bytes((text + "\n".join(sections)).encode("utf-8"))

    def edges(self, rows: str) -> str:
        return self.EDGE_HEAD + rows

    def prohibitions(self, rows: str) -> str:
        return self.PROHIBITION_HEAD + rows

    def intent_root(self, root: Path, *sections: str) -> None:
        self.write_intent_criteria(root)
        if sections:
            self.append_intent(root, *sections)

    def assert_intent_error(self, root: Path, pattern: str) -> None:
        with self.assertRaisesRegex(check_handoffs.HandoffError, pattern):
            check_handoffs.validate_intent(root)

    # Intent

    def test_intent_without_probe_sections_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(root)

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["edge_coverage"], "absent")
            self.assertEqual(result["prohibitions"], "absent")

    def test_intent_accepts_valid_probe_tables(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(self.VALID_EDGES),
                self.prohibitions(self.VALID_PROHIBITIONS),
            )

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["held_out"], ["E1"])
            self.assertEqual(result["judgment"], ["N1"])
            self.assertEqual(result["edge_coverage"], 3)
            self.assertEqual(result["prohibitions"], 2)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(
                    check_handoffs.main(["intent", "--repo", str(root)]), 0
                )

    def test_intent_rejects_a_criterion_the_edge_walk_skips(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | held-out | the start date is inclusive |\n"
                ),
            )
            self.assert_intent_error(root, "does not walk SC2")

    def test_intent_rejects_an_unknown_edge_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | vibes | held-out | some ruling |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "unknown category")

    def test_intent_rejects_category_none_that_is_not_dismissed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | none | held-out | some ruling |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "category none must be dismissed")

    def test_intent_rejects_a_held_out_row_without_detail(self) -> None:
        for detail in ("none", ""):
            with self.subTest(detail=detail), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.intent_root(
                    root,
                    self.edges(
                        f"| E1 | SC1 | boundary | held-out | {detail} |\n"
                        "| E2 | SC2 | none | dismissed | static |\n"
                    ),
                )
                self.assert_intent_error(root, "Detail")

    def test_intent_rejects_a_disposition_naming_an_unknown_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | criterion SC9 | stated there |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "unknown SC9")

    def test_intent_rejects_noncontiguous_edge_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | held-out | the start date is inclusive |\n"
                    "| E3 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "contiguous")

    def test_intent_rejects_the_template_placeholder_edge_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | <category> | <disposition> | <detail> |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "unknown category")

    def test_intent_accepts_a_single_all_dismissed_prohibition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | all | none | dismissed | library, nobody touches it |\n"
                ),
            )

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["prohibitions"], 1)
            self.assertEqual(result["judgment"], [])

    def test_intent_rejects_criterion_all_with_judgment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | all | shame the user | judgment | wording is neutral |\n"
                ),
            )
            self.assert_intent_error(root, "criterion all must be dismissed")

    def test_intent_rejects_a_placeholder_must_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | SC1 | <what it must never become> | judgment | wording is neutral |\n"
                    "| N2 | SC2 | none | dismissed | nothing applies |\n"
                ),
            )
            self.assert_intent_error(root, "Must not")

    # Intent: further probe rules

    def test_intent_prohibitions_must_walk_every_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | SC1 | shame the user | judgment | wording is neutral |\n"
                ),
            )
            self.assert_intent_error(root, "does not walk SC2")

    def test_intent_rejects_an_invalid_prohibition_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | SC1 | shame the user | held-out | wording is neutral |\n"
                    "| N2 | SC2 | none | dismissed | nothing applies |\n"
                ),
            )
            self.assert_intent_error(
                root, "disposition must be criterion SCn, judgment, or dismissed"
            )

    def test_intent_rejects_an_exact_duplicate_edge_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | empty | dismissed | always non-empty |\n"
                    "| E2 | SC1 | empty | dismissed | always non-empty |\n"
                    "| E3 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "repeats an earlier row")

    def test_intent_accepts_same_criterion_and_category_with_different_rulings(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | dismissed | lower bound is fixed |\n"
                    "| E2 | SC1 | boundary | held-out | the upper bound is inclusive |\n"
                    "| E3 | SC1 | boundary | dismissed | no other bound applies |\n"
                    "| E4 | SC2 | none | dismissed | static |\n"
                ),
            )

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["edge_coverage"], 4)
            self.assertEqual(result["held_out"], ["E2"])

    def test_intent_rejects_category_none_mixed_with_a_real_category(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | none | dismissed | static |\n"
                    "| E2 | SC1 | empty | dismissed | always non-empty |\n"
                    "| E3 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "mixes category none")

    def test_intent_rejects_a_probe_section_without_rows(self) -> None:
        cases = {
            "edge header only": (self.EDGE_HEAD, "Edge coverage has no rows"),
            "prohibition header only": (self.PROHIBITION_HEAD, "Prohibitions has no rows"),
            "edge comment only": (
                "## Edge coverage\n\n<!-- | E1 | SC1 | boundary | held-out | x | -->\n",
                "Edge coverage has no rows",
            ),
            "prohibition comment only": (
                "## Prohibitions\n\n"
                "<!-- | N1 | SC1 | x | judgment | y | -->\n",
                "Prohibitions has no rows",
            ),
        }
        for name, (section, pattern) in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.intent_root(root, section)
                self.assert_intent_error(root, pattern)

    def test_intent_rejects_a_near_miss_probe_heading(self) -> None:
        table = self.EDGE_HEAD + self.VALID_EDGES
        prohibition_table = self.PROHIBITION_HEAD + self.VALID_PROHIBITIONS
        cases = {
            "wrong case": table.replace("## Edge coverage", "## Edge Coverage"),
            "wrong level": table.replace("## Edge coverage", "### Edge coverage"),
            "suffix": prohibition_table.replace(
                "## Prohibitions", "## Prohibitions (draft)"
            ),
        }
        for name, section in cases.items():
            with self.subTest(name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                self.intent_root(root, section)
                self.assert_intent_error(root, "must be exactly")

    def test_intent_rejects_a_repeated_probe_heading(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            table = self.edges(self.VALID_EDGES)
            self.intent_root(root, table, table)
            self.assert_intent_error(root, "repeats ## Edge coverage")

    def test_intent_ignores_a_probe_heading_inside_a_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root, "<!--\n" + self.edges(self.VALID_EDGES) + "\n-->\n"
            )

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["edge_coverage"], "absent")

    def test_intent_rejects_a_row_missing_its_leading_pipe(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | held-out | the start date is inclusive |\n"
                    "E2 | SC1 | empty | dismissed | x |\n"
                    "| E3 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, r"must start with \|")

    def test_intent_rejects_all_alongside_another_prohibition_row(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | all | none | dismissed | nobody touches it |\n"
                    "| N2 | SC1 | shame the user | judgment | wording is neutral |\n"
                ),
            )
            self.assert_intent_error(root, "criterion all must be the only row")

    def test_intent_rejects_all_whose_must_not_is_not_none(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | all | shame the user | dismissed | nobody touches it |\n"
                ),
            )
            self.assert_intent_error(root, "criterion all must be the only row")

    def test_intent_rejects_placeholders_in_dismissed_and_criterion_rows(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.prohibitions(
                    "| N1 | SC1 | <placeholder> | dismissed | nothing applies |\n"
                    "| N2 | SC2 | none | dismissed | nothing applies |\n"
                ),
            )
            self.assert_intent_error(root, "Must not still contains the placeholder")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| E1 | SC1 | boundary | criterion SC2 | <placeholder> |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
            )
            self.assert_intent_error(root, "Detail still contains the placeholder")

    def test_intent_parses_backticked_cells(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.intent_root(
                root,
                self.edges(
                    "| `E1` | `SC1` | boundary | held-out | x |\n"
                    "| `E2` | `SC2` | none | dismissed | static |\n"
                ),
            )

            result = check_handoffs.validate_intent(root)

            self.assertEqual(result["edge_coverage"], 2)
            self.assertEqual(result["held_out"], ["E1"])

    # Plan

    HELD_OUT_TABLE = (
        "\n## Held-out checks\n\n"
        "| Edge | Task | Test |\n"
        "|------|------|------|\n"
        "{rows}"
    )

    def plan_root(
        self,
        root: Path,
        *,
        check_rows: str = "| E1 | T001 | tests/test_heldout.py |\n",
        edges: str = "",
        files: str = "src/app.py\n  - tests/test_heldout.py",
        verify: str = "python3 src/app.py && python3 tests/test_heldout.py",
        acceptance: str = (
            "1. The demo command prints hello.\n"
            "2. E1: the start date is inclusive."
        ),
        with_section: bool = True,
    ) -> None:
        self.write_state(root, "plan", "active")
        self.write_intent_criteria(root)
        self.append_intent(root, self.edges(edges or self.VALID_EDGES))
        self.write_plan_coverage(root)
        plan = root / ".project/plan/PLAN.md"
        if with_section:
            plan.write_bytes(
                (
                    plan.read_text(encoding="utf-8")
                    + self.HELD_OUT_TABLE.format(rows=check_rows)
                ).encode("utf-8")
            )
        self.write_coverage_task(
            root, "T001", "- SC1", acceptance=acceptance, verify=verify, files=files
        )
        self.write_coverage_task(
            root, "T002", "- SC2", acceptance="1. The demo test suite is green."
        )

    def test_plan_rejects_a_missing_held_out_checks_section(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, with_section=False)
            with self.assertRaisesRegex(check_handoffs.HandoffError, "omits held-out E1"):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_check_for_a_dismissed_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(
                root,
                check_rows=(
                    "| E1 | T001 | tests/test_heldout.py |\n"
                    "| E2 | T001 | tests/test_heldout.py |\n"
                ),
            )
            with self.assertRaisesRegex(check_handoffs.HandoffError, "not held-out"):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_test_outside_the_task_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, files="src/app.py")
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "is not listed in T001 files"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_verify_that_skips_the_held_out_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, verify="python3 src/app.py")
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "must run held-out test"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_acceptance_that_omits_the_held_out_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, acceptance="1. The demo command prints hello.")
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "must state held-out E1"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_accepts_a_wired_held_out_check(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root)

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["held_out"], {"E1": "T001"})

    def test_plan_rejects_a_held_out_row_naming_an_unknown_task(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, check_rows="| E1 | T009 | tests/test_heldout.py |\n")
            with self.assertRaisesRegex(check_handoffs.HandoffError, "names unknown T009"):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_test_that_is_a_directory_prefix_of_another_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(
                root,
                check_rows="| E1 | T001 | tests/heldout |\n",
                files="src/app.py\n  - tests/heldout\n  - tests/heldout/case.py",
                verify="python3 src/app.py && python3 tests/heldout",
            )
            with self.assertRaisesRegex(check_handoffs.HandoffError, "names a directory"):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_a_test_only_named_in_a_verify_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(
                root,
                files="src/app.py\n  - tests/other.py\n  - tests/test_heldout.py",
                verify="python3 -m unittest tests/other.py # tests/test_heldout.py",
            )
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "must run held-out test"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_rejects_an_edge_id_only_inside_an_acceptance_comment(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(
                root,
                acceptance=(
                    "1. The demo command prints hello.\n"
                    "2. The start date is inclusive. <!-- E1 -->"
                ),
            )
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "must state held-out E1"
            ):
                check_handoffs.validate_plan(root)

    def test_plan_accepts_a_pytest_node_id_in_the_test_cell(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(
                root,
                check_rows="| E1 | T001 | tests/test_heldout.py::test_e1 |\n",
                verify="pytest tests/test_heldout.py::test_e1",
            )

            result = check_handoffs.validate_plan(root)

            self.assertEqual(result["held_out"], {"E1": "T001"})

    def test_plan_rejects_a_held_out_edge_assigned_to_a_task_that_does_not_own_it(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.plan_root(root, check_rows="| E1 | T002 | tests/test_app.py |\n")
            with self.assertRaisesRegex(check_handoffs.HandoffError, "does not own"):
                check_handoffs.validate_plan(root)

    # Final

    def final_root(
        self, root: Path, *sections: str, verdict: str = "pass", sc1: str = "met",
        observed: str = "hello",
    ) -> None:
        self.write_state(root, "ship", "active")
        self.write_intent_criteria(root)
        self.append_intent(root, *sections)
        self.write_final_review(root, verdict=verdict, sc1=sc1, observed=observed)

    def sc1_held_out(self) -> str:
        return self.edges(
            "| E1 | SC1 | boundary | held-out | the start date is inclusive |\n"
            "| E2 | SC2 | none | dismissed | static |\n"
        )

    def test_final_rejects_met_without_cited_held_out_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.final_root(root, self.sc1_held_out())
            with self.assertRaisesRegex(
                check_handoffs.HandoffError, "met without cited evidence for E1"
            ):
                check_handoffs.validate_final(root)

    def test_final_accepts_met_when_observed_cites_the_edge(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.final_root(
                root, self.sc1_held_out(), observed="E1 held: the start date is inclusive"
            )

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")

    def test_final_accepts_unverifiable_for_a_tagged_criterion(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.final_root(
                root, self.sc1_held_out(), verdict="blocked", sc1="unverifiable"
            )
            final = root / ".project/review/FINAL.md"
            text = final.read_text(encoding="utf-8")
            head, tail = text.split("### SC2", 1)
            head = head.replace(
                "- **Finding**: none",
                "- **Finding**: The inclusive start date could not be exercised.",
            ).replace(
                "- **Fix direction**: none",
                "- **Fix direction**: Provide a fixture and rerun the held-out test.",
            )
            final.write_bytes((head + "### SC2" + tail).encode("utf-8"))

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "blocked")

    def test_final_requires_a_judgment_prohibition_to_be_cited(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.final_root(
                root,
                self.prohibitions(
                    "| N1 | SC2 | shame the user | judgment | wording is neutral |\n"
                    "| N2 | SC1 | none | dismissed | nothing applies |\n"
                ),
            )
            with self.assertRaisesRegex(check_handoffs.HandoffError, "N1"):
                check_handoffs.validate_final(root)

    def test_final_accepts_untagged_criteria_without_citations(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.final_root(
                root,
                self.edges(
                    "| E1 | SC1 | none | dismissed | static |\n"
                    "| E2 | SC2 | none | dismissed | static |\n"
                ),
                self.prohibitions(
                    "| N1 | all | none | dismissed | nobody touches it |\n"
                ),
            )

            result = check_handoffs.validate_final(root)

            self.assertEqual(result["verdict"], "pass")

    def test_cites_matches_whole_tags_only(self) -> None:
        self.assertFalse(check_handoffs._cites("checked E10 only", "E1"))
        self.assertFalse(check_handoffs._cites("checked SE1 only", "E1"))
        self.assertTrue(check_handoffs._cites("E1: held", "E1"))
        self.assertTrue(check_handoffs._cites("held (E1)", "E1"))

    def test_cites_rejects_ids_inside_paths_and_longer_names(self) -> None:
        for text, tag in (
            ("see tests/E1.py", "E1"),
            ("see E2E/x.py", "E2"),
            ("see x-E1", "E1"),
            ("see E1_a", "E1"),
        ):
            with self.subTest(text=text):
                self.assertFalse(check_handoffs._cites(text, tag))

    def test_cites_accepts_ids_ending_a_sentence_or_followed_by_a_colon(self) -> None:
        for text in ("It held for E1.", "held (E1)", "E1: held"):
            with self.subTest(text=text):
                self.assertTrue(check_handoffs._cites(text, "E1"))


if __name__ == "__main__":
    unittest.main()
