# Review — wave <N>, cycle <C>

<!-- Written by the reviewer role in wave mode. File: wave-N.cycleC.md.
     Keep validated fields on their own lines: Cycle holds only the number
     (C > 1 means re-review after fixes; see previous cycle file). -->

Wave verdict: <pass | blocked — blocked if any task fails>
Cycle: <C>
Depth: <full | verify-only — verify-only is orchestrator-written from its
        isolated Verify evidence; no independent reviewer ran>
Tasks reviewed: <count>

## T001 — <title>: <pass | fail>

<!-- Per criterion: -->
- ✅ <criterion> — <evidence: verify output / file:line checked>
- ❌ <criterion> — found: <what exists instead, file:line>
  fix: <concrete direction a coder can execute without re-investigating>

Warnings (non-blocking):
- <weakened test / unfailable verify / none>

Contract violations (blocking):
- ❌ <task changed path outside its files list> — <evidence and fix direction>

<!-- Repeat per task. -->

## Fixed since last cycle

<!-- C > 1 only: previously failed criteria now confirmed fixed (re-checked,
     not assumed), and any regressions the fixes introduced. -->
- <criterion> — confirmed fixed / regressed: <evidence>

## Summary for orchestrator

- blocked → fix tasks needed: <one per disjoint file scope, findings
  batched: T00xF<C> — scope + findings covered, ...>
- repeat offenders: <criteria failing across cycles — possible plan defect>
- warnings worth a human eye: <...or none>
