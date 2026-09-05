# Archive — 001-widget-counter

Milestone: widget-counter
Shipped: 2026-09-05
Final verdict: all criteria met; project verify passed
Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1
Carried forward: none

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| Running python3 count.py without arguments exits zero and prints exactly 0 widgets followed by a newline. | met | count.py:5,12; .project/plan/PLAN.md CLI walkthrough step 1. |
| Running python3 count.py with one integer, including zero or a negative integer, exits zero and prints that integer followed by the literal suffix " widgets" and a newline. | met | count.py:5,12; .project/plan/PLAN.md CLI walkthrough step 1 plus explicit zero and positive checks. |
| Running python3 count.py --json without a count exits zero and emits exactly one JSON object whose only field is widgets with integer value 0. | met | count.py:5,9–10; .project/plan/PLAN.md CLI walkthrough step 2. |
| With an integer count, --json works before or after the count, including negative counts; stdout is exactly one JSON object whose only field is widgets with that integer value. | met | count.py:5–10; .project/plan/PLAN.md CLI walkthrough step 3. |
| Invalid input, including a noninteger count, an unknown option, or extra positional input, exits nonzero with a useful stderr error identifying the problem. | met | count.py:4–7; .project/plan/PLAN.md CLI walkthrough step 4. |
| Useful dependency-free tests exercise the CLI outputs, JSON field type and shape, flag positions, defaults, negative counts, and invalid input, and pass. | met | test_count.py:1–64; .project/tasks/T001-widget-counter.md:73–81; /Users/jeremymcspadden/orca/evaluations/gsd-path-e2e-50718f8/path/repo/.project/review/final-gap-1.md. |

## Contents

- build/RECOVERY.md
- build/evidence.json
- build/verify-ledger.jsonl
- intent/INTENT.md
- plan/PLAN.gate.json
- plan/PLAN.md
- research/DOCS-AUDIT.md
- research/SYNTHESIS.md
- research/evidence-codebase.md
- review/FINAL.md
- review/final-gap-1.md
- review/wave-1.cycle1.md
- tasks/T001-widget-counter.md

## Notes

- none
