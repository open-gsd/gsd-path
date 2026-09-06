# Plan — Widget counter CLI

Project verify: `python3 -B -m unittest discover -s . -p 'test_*.py' -v`

## Config

- max_review_cycles: 3
- wave_budget: none
- review_panel: off
- finding_skeptics: off

The review cycle value comes from the pinned plan template and project policy. No testing token or time limit is imposed.

## Wave 1 — Complete the widget counter CLI

Goal: Deliver and prove every approved success criterion through the real count.py command and its regression tests, preserving default and signed integer text output.
Review depth: full

One deliverable task: T001, including implementation and tests. No cross-task or cross-wave dependency exists.

## Surface contract

### count.py CLI — T001

Criteria: SC1, SC2, SC3
Entry: `python3 count.py` from the disposable review worktree at the recorded review revision.
States: Omitted count prints zero; signed integer input prints its count; JSON mode emits one object containing only integer widgets; invalid input exits nonzero with useful stderr and no success output or traceback. This synchronous CLI has no loading state.
Walkthrough:
1. Run `python3 -B count.py`, then with `0`, `5`, `+5`, and `-3`. Observe exact count plus ` widgets` and a newline, exit zero, and empty stderr.
2. Run `python3 -B count.py --json`. Observe exactly one JSON object with only widgets equal to integer zero, exit zero, and empty stderr.
3. Run `python3 -B count.py --json -3`, `python3 -B count.py -3 --json`, `python3 -B count.py --json +5`, and `python3 -B count.py +5 --json`. Observe the matching integer widgets value in the single JSON object, exit zero, and empty stderr.
4. Run `python3 -B count.py abc`, `python3 -B count.py 1.5`, `python3 -B count.py --unknown`, and `python3 -B count.py 1 2`. Observe nonzero exits, useful stderr, empty stdout, and no traceback. Also exercise invalid text with --json before and after it.

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |
| SC2 | T001 | AC2 |
| SC3 | T001 | AC3 |
| SC4 | T001 | AC4 |

## Dependency notes

None. One task owns the full CLI feature and its tests. The blast radius is the count.py process interface; inspection found no other product modules or callers. The existing text interface is protected by AC1 and AC4.

## Verification and final scope

- Task Verify runs the owned test file in canonical isolation. The orchestrator records the isolated result; the wave reviewer consumes that recorded output and isolated diff without rerunning Task Verify.
- The native full-wave reviewer uses the pinned wave-review template, records the actual full `Reviewed HEAD` and `Review scope: final`, checks all SC1–SC4, and records `Surface`, `Check`, and `Observed` fields for SC1–SC3 using the final-review format. Perform the required surface walkthroughs in the assigned review sidecar and keep their concrete command/output evidence in that review once.
- Project verify discovers the complete product test suite. It runs only through canonical `workflow_run.py prepare-final` in its owned sidecar. No dependency installation is required.
- Stop after the full-wave review for capture. Then prepare-final must classify whether the unchanged product and contracts permit reuse; do not dispatch review_final when the runtime generates FINAL.md from the complete full-wave review.
- Stop at final-ready and identify canonical artifacts. Before shipment, repeat prepare-final at the same HEAD and compare its actual receipt and execution ledger to prove reuse without another execution or ledger entry. Never fabricate that result.
- Archive and integrate through canonical gates using only the existing local origin. Stop at integrated and identify canonical artifacts; run the external counter oracle as requested without reading evaluator tests.
- Run the guard demonstration only in an evaluator-owned disposable fixture. Preserve actual host hook evidence and target hashes; absent runtime enforcement is unverifiable. Do not attempt destructive operations in this product repository.

## Execution constraints

Use only the pinned skill at `.agents/skills/gsd-path/SKILL.md` and sibling bundles. Use native children for coding and full review; quick planning is orchestrator-written as required by PLAN.md Quick mode. No installed-skill edits, state hand repairs, new dependencies, GitHub actions, or other-scenario reads. Apply the exact activity wrapper from INTENT.md to measured shell work and set sidecar cwd explicitly. Stop at reviewable owner gates and named capture checkpoints. Approved INTENT.md remains unchanged.

## Approval record

Intent approval received in owner chat on 2026-09-06: "approve the drafted INTENT.md exactly as written. Quick lane, one full wave, no panel, no skeptics."
Plan approval is pending. No build dispatch or plan checkpoint is authorized yet.
