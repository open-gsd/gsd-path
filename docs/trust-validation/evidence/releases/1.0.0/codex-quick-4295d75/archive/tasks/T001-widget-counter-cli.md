---
id: T001
title: Add JSON output and validated arguments to the widget counter
wave: 1
deps: []
status: done
agent: build_t001
base: 0753119a96ef3458edc33fc56e0daea6d9a9b0c2
worktree: null
task_branch: null
files:
  - count.py
  - test_count.py
---

# T001 — Add JSON output and validated arguments to the widget counter

## Context

The existing count.py uses sys.argv, int conversion, and direct text output. Inspection proved that default and signed counts work, leading --json raises a traceback, trailing --json is ignored, and invalid text raises a traceback. No product test suite or dependency manifest exists. Approved INTENT.md SC1–SC4 and SYNTHESIS.md settle this as one standard-library CLI feature with real subprocess coverage.

## Approach

- Read count.py and the inspection evidence before editing. Preserve the existing text interface; the affected boundary is command-line parsing, exit status, stdout, and stderr.
- Keep implementation compatible with Python 3.9.6 and use only the standard library. The coder owns the parsing approach; negative integers must not be confused with options.
- Add test_count.py using unittest and subprocess execution of the real count.py with the current interpreter. Assert observable output and status, not internal helper details; JSON assertions must reject extra keys and non-integer values, including booleans.
- Include omitted, zero, positive, explicitly positive, and negative counts; both JSON flag positions; and invalid non-integer, unknown-option, and extra-positional cases. Preserve existing behavior coverage while adding new behavior coverage.
- Follow the pinned coder and isolation contracts. Modify only the declared files and append the task Log. Do not edit installed skills, evaluator files, approved intent, or task lifecycle fields; do not stage or commit.

## Interface contract

- None

## Intent coverage

- SC1
- SC2
- SC3
- SC4

## Acceptance criteria

1. Running count.py with no count prints exactly `0 widgets` followed by a newline; zero, positive, explicitly positive, and negative integer counts print that integer followed by ` widgets` and a newline. Successful text runs exit zero with empty stderr.
2. --json alone or before or after the optional signed integer count emits exactly one JSON object containing only widgets with the matching integer value, default zero. Successful JSON runs exit zero with empty stderr.
3. Invalid non-integer counts, unknown options, and extra positional arguments fail with a nonzero exit, useful stderr, empty stdout, and no unhandled traceback; invalid input is rejected in JSON mode as well.
4. test_count.py contains standard-library real-CLI subprocess tests that check exit status, stdout, stderr, JSON shape and integer type, default and signed counts, both flag placements, and invalid inputs. These tests fail against the missing JSON behavior in the original count.py and pass after implementation, with no new dependencies.

## Verify

```bash
python3 -B test_count.py
```

Heavy: no

## Log

- 2026-09-06 — Created during quick planning from approved INTENT.md; implementation has not started.

- 2026-09-06 — Preflight: HEAD is assigned base 0753119a96ef3458edc33fc56e0daea6d9a9b0c2 on unmerged gsd-path/M001; count.py exists, test_count.py is declared new, SC1–SC4 and Verify map to this task; no sibling interface exchange. Scope is CLI parsing and process outputs.
- 2026-09-06 — Orchestrator answer: Owner explicitly ruled "approve PLAN.md and T001 exactly as written. Start the build." Canonical plan checkpoint 9ec47f5a835664d2a376a246595a5e991aead272 and build entry 0753119a96ef3458edc33fc56e0daea6d9a9b0c2 supersede the stale draft Approval record; leave PLAN unchanged.
- 2026-09-06 — Red evidence before changing count.py: `python3 -B test_count.py WidgetCounterTests.test_json_default` exited 1; 1 test failed because original count.py exited 1 with `ValueError: invalid literal for int() with base 10: '--json'`. The test invokes the actual CLI and requires successful JSON output.
- 2026-09-06 — Implemented standard-library argparse validation with abbreviation disabled, optional integer count defaulting to zero, and JSON rendering through json.dumps. Preserved exact text output. Invalid counts, unknown options, and extra positionals use parser diagnostics and nonzero exit before output. No dependencies or additional product paths.
- 2026-09-06 — Added unittest subprocess coverage: 5 text cases, 1 JSON default, 8 signed-count/flag-placement cases, and 15 invalid-input cases across text and both JSON placements. Assertions cover status, stdout, stderr, exact JSON key set, exact int type (rejecting bool), matching values, and absence of traceback.
- 2026-09-06 — Task Verify `python3 -B test_count.py` through required activity wrapper exited 0: `Ran 4 tests in 0.539s`, `OK`. All 29 CLI invocations passed. `git diff --check` exited 0. Diff review found changes limited to declared product files and this Log; direct parser/output logic requires no extra abstraction. No project-wide Verify was run. Ready for orchestrator isolated verification and reviewer acceptance; no Git mutations performed by coder.

- 2026-09-06 — Orchestrator isolated Task Verify: complete declared patch (including the new test file) reproduced byte-for-byte in /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/quick/repo.gsd-path/verify/task-t001-verify at base 0753119a96ef3458edc33fc56e0daea6d9a9b0c2. Tracked binary diff and all copied bytes match the primary task patch; changed-path allowlist and git diff --check passed. Command: `python3 -B test_count.py`; exit: 0. Exact stdout: ""; exact stderr: "....\n----------------------------------------------------------------------\nRan 4 tests in 0.574s\n\nOK\n".
