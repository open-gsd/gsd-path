# Archive — 001-widget-counter-cli

Milestone: widget-counter-cli
Shipped: 2026-09-06
Final verdict: all criteria met; project verify passed
Waves: 1  Tasks: 1 done / 1 total  Review cycles used: 1
Carried forward: none

## Success criteria at ship

| Criterion | Verdict | Evidence |
|-----------|---------|----------|
| Running `python3 count.py` prints exactly `0 widgets` followed by a newline. A signed integer argument prints that integer count followed by ` widgets` and a newline, including zero, positive, and negative values. | met | .project/review/wave-1.cycle1.md — SC1 |
| `--json` alone, before a signed integer count, or after that count prints exactly one JSON object with only the `widgets` key and an integer value equal to the count; omitted count defaults to zero. Successful runs exit zero and emit no stderr. | met | .project/review/wave-1.cycle1.md — SC2 |
| Invalid input fails with a nonzero exit and a useful diagnostic on stderr, without success output or an unhandled traceback. Non-integer counts, unknown options, and extra positional arguments are invalid. | met | .project/review/wave-1.cycle1.md — SC3 |
| Standard-library real-CLI tests invoke count.py as a subprocess and check exit status, stdout, stderr, JSON shape and integer type, default count, signed counts, both flag placements, and invalid input. Tests must detect missing requested behavior. | met | .project/review/wave-1.cycle1.md — SC4 |

## Contents

- build/evidence.json
- build/verify-ledger.jsonl
- intent/INTENT.md
- plan/GATE.json
- plan/PLAN.md
- research/DOCS-AUDIT.md
- research/SYNTHESIS.md
- research/evidence-codebase.md
- review/FINAL.md
- review/final-gap-1.md
- review/wave-1.cycle1.md
- tasks/T001-widget-counter-cli.md

## Notes

- none
