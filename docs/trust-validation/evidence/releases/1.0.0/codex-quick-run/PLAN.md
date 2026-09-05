# Plan — Widget counter CLI

Project verify: `python3 -B -m unittest discover -s . -p 'test_count.py' -v`

## Config

- max_review_cycles: 3
- wave_budget: none
- review_panel: off
- finding_skeptics: off

The review-cycle value comes from the local plan template and AGENTS.md MSW fuse. Per-task 4000 tokens and per-session 30000 tokens are owner policy; no additional time or retry limit is introduced.

## Wave 1 — Complete widget-counter CLI

Goal: Deliver plain text and JSON counts with useful errors and focused CLI tests. This is one coherent task, T001, including implementation and tests.
Review depth: full

## Surface contract

### widget-counter CLI — T001

Criteria: SC1, SC2, SC3, SC4
Entry: python3 count.py [INTEGER] [--json], with --json also accepted before INTEGER.
States: Empty input prints 0 widgets; loading has no separate state because the command is synchronous; successful input prints text or one JSON object; invalid input prints a useful stderr error and exits nonzero.
Walkthrough:
1. Observe no-argument output and plain text output for zero, 1, a positive count, and a negative count.
2. Observe JSON with no count and with positive and negative counts on either side of --json; parse stdout and check its sole widgets field is an integer.
3. Observe nonzero exit and useful stderr for a noninteger, an unknown option, and extra positional arguments, with no successful count output.

## Intent coverage

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |
| SC2 | T001 | AC2 |
| SC3 | T001 | AC3 |
| SC4 | T001 | AC4 |
| SC5 | T001 | AC5 |

## Dependency notes

None. One task owns count.py and its tests; no cross-task interface or cross-wave risk exists.

## Execution and evidence

- Product scope is count.py and new test_count.py. Existing valid CLI callers keep their text output; invalid-input callers gain explicit rejection. There are no other product modules or test consumers in the inspection evidence.
- Read the exact required test-writer and code-simplifier skill files named in INTENT. Use native children and fixture-local canonical build, isolation, and review helpers. Quick planning itself dispatches no planner child under the local PLAN.md Quick mode contract.
- The coder records test failures and results in T001's Log. The orchestrator reruns Task Verify against the recorded base plus only the task patch. The full wave reviewer consumes that output and the isolated diff without rerunning Task Verify.
- Project verify runs once at ship in its assigned sidecar; it is limited to the entire product test file and does not discover pipeline or evaluator tests. The final reviewer records the CLI surface evidence against SC1–SC4.
- All measured shell work uses the owner-supplied activity wrapper with implementation, verification, or review as the actual category. Wrapped sidecar commands explicitly change to the assigned sidecar directory because the wrapper resets cwd to the arm repository. Never estimate unclassified duration.
- No dependencies, singular-label change, other comparison-arm reads, evaluator acceptance-test reads, global pipeline bundles, or installed-source edits.
- Direct integration targets the existing local origin after the remaining approval gates. No PR is planned.
- Intent approval is the supplied evaluator approval, not a new human receipt. Plan approval has not been received. Prior helper failures remain in STATE.md's append-only Log.

## Approval record

2026-09-04 — Evaluator approval supplied in the user channel; not a new human receipt. The earlier pending-approval execution note is superseded by this record.

> Parent evaluator approval under the user-authorized comparison: I reviewed PLAN.md and T001-widget-counter.md. The one-task scope, root test_count.py path, all five criteria, isolated task Verify, full wave review, and ship-only Project verify match the supplied contract. Approve and continue build and ship through direct integration to this fixture's local origin. This is evaluator approval, not a new human receipt. Use ONLY fixture-local .agents/skills/gsd-path* bundles. Preserve recorded failures. Do not edit installed plugin source. Explicitly chdir inside wrapped sidecar commands.
