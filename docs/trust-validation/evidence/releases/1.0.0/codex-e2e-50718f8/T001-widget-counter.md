---
id: T001
title: Implement widget-counter JSON mode and CLI tests
wave: 1
deps: []
status: done
agent: build_t001
base: c9b614a3e4fabf2f2eb824b6a50fe2ce6801f091
worktree: null
task_branch: null
files:
  - count.py
  - test_count.py
---

# T001 — Implement widget-counter JSON mode and CLI tests

## Context

The existing three-line count.py reads only the first argument. Text defaults and negative counts work; leading --json throws and trailing --json is silently ignored. No product tests exist. The approved intent and settled synthesis require one complete CLI deliverable with no dependencies.

## Approach

- Read the approved intent and codebase evidence before editing count.py. Preserve valid text behavior and handle argument errors as CLI errors.
- Keep changes within the declared script and test file. Blast radius is the CLI argument/output boundary; no product callers or shared modules were found.
- Choose the smallest standard-library implementation. Use /Users/jeremymcspadden/.codex/skills/test-writer/SKILL.md for code changes and /Users/jeremymcspadden/.codex/skills/code-simplifier/SKILL.md after changes.
- Tests invoke count.py as a real subprocess and assert output, JSON type/shape, stderr, and exit status. They must catch the original ignored-trailing-flag behavior.
- Use the evaluator activity wrapper with actual categories and explicit sidecar cwd. Do not read comparison arms or evaluator acceptance tests. Record failures and simplifier outcome in Log.
- Owner budgets: 4000 output tokens per task, 30000 session total. Parent supplies cumulative admission context; do not reset it or claim unsupported hard enforcement.

## Interface contract

- None

## Intent coverage

- SC1
- SC2
- SC3
- SC4
- SC5
- SC6

## Acceptance criteria

1. No arguments exit zero and print exactly 0 widgets plus newline.
2. One integer, including zero and negatives, exits zero and prints its value plus the literal suffix " widgets" and newline.
3. --json alone exits zero and emits exactly one object with only widgets, whose value is integer zero.
4. --json before or after a supplied integer, including a negative, exits zero and emits exactly one object with only widgets and the integer count.
5. Noninteger counts, unknown options, and extra positional input exit nonzero with useful stderr identifying the problem.
6. Useful standard-library subprocess tests cover AC1–AC5, including JSON object shape and integer type, and pass without new dependencies.

## Verify

```bash
python3 -B test_count.py
```

Heavy: no

## Log

- 2026-09-05 — Quick-lane task drafted from approved intent; no code changes or build approval yet.

- 2026-09-05 — Coder preflight: HEAD c9b614a3e4fabf2f2eb824b6a50fe2ce6801f091 on gsd-path/M001; branch absent from `git branch --merged origin/main`. Only orchestrator task frontmatter was dirty at dispatch. Read coder role, AGENTS.md, WORKFLOW.md, task template, full task, approved INTENT and codebase evidence. All referenced inputs exist; test_count.py is declared new; SC1–SC6 exist; no exchanged interface. Memtrace discovery tools unavailable, so used bounded static reads. Blast radius: count.py CLI arguments/stdout/stderr only; no shared product module or callers in inspection evidence.
- 2026-09-05 — Implementation: count.py now uses argparse for one optional integer, default zero, and --json in either position; json.dumps emits the integer widgets field. Invalid inputs use parser errors; long-option abbreviation is disabled. test_count.py uses unittest and real subprocess calls for four text cases, seven JSON cases and seven invalid-input cases. JSON parsing plus exact dict and integer-type assertions checks output shape. No dependencies added.
- 2026-09-05 — Test-writer RED: `python3 -B test_count.py` against the original count.py exited 1: `Ran 3 tests in 0.193s`, `FAILED (failures=11, errors=3)`. Leading JSON raised ValueError; trailing JSON produced text and JSONDecodeError; trailing unknown/extra input exited zero; invalid counts used tracebacks. Existing text cases passed. Every new behavior case failed before implementation for its intended contract gap.
- 2026-09-05 — Test-writer GREEN: `python3 -B test_count.py` exited 0: `Ran 3 tests in 0.359s`, `OK`.
- 2026-09-05 — Test-writer sabotage: a Python harness saved count.py bytes, temporarily replaced it with `print("wrong")`, executed `python3 -B test_count.py`, required nonzero exit, and restored original bytes in finally. Inner command exited 1: `Ran 3 tests in 0.194s`, `FAILED (failures=11, errors=7)`. All 18 subprocess cases detected broken CLI behavior; JSON cases rejected invalid output, text cases rejected wrong output, invalid-input cases rejected zero exit. Harness exited 0 after restoration. Final restored Verify `python3 -B test_count.py` exited 0: `Ran 3 tests in 0.310s`, `OK`.
- 2026-09-05 — Code-simplifier applied after test creation, implementation and temporary sabotage/restoration. Shared subprocess setup, case tables, standard-library parsing and explicit output branches are direct; no additional changes needed. All measured commands used `python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-e2e-50718f8/plugin/tests/evaluate_codex.py activity --arm /Users/jeremymcspadden/orca/evaluations/gsd-path-e2e-50718f8/path --category <implementation|verification|review> -- ...` with actual categories from the assigned primary serial worktree. No broad suite, comparison-arm reads, evaluator acceptance-test reads, plugin-source edits or Git mutations. Coder result: ready for independent orchestrator Verify; acceptance remains reviewer-owned.

- Orchestrator isolated Verify at c9b614a3e4fabf2f2eb824b6a50fe2ce6801f091 plus complete byte-matched task patch in /Users/jeremymcspadden/orca/evaluations/gsd-path-e2e-50718f8/path/repo.gsd-path/verify/task-t001-verify: python3 -B test_count.py; exit 0; exact output:

```text
...
----------------------------------------------------------------------
Ran 3 tests in 0.310s

OK
```
