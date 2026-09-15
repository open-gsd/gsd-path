## Wave mode

Use task acceptance criteria and the INTENT.md success criteria owned by
tasks in this wave as the rubric. For each task:

1. Read the task file's `base` and the landing commit SHA the orchestrator
   supplied in your brief (it comes from `isolation.py land`/`recover`).
   Never infer either SHA from task ids, branch position, or nearby history.
2. Fail a missing, malformed, or invalid SHA. Inspect the commit with
   `git show --format=fuller --stat --patch <commit> --`.
3. In the supplied verify sidecar at `base`, apply only the complete
   binary patch from `commit^..commit` for the task's declared product files
   and inspect the diff. Use the orchestrator's recorded isolated Verify
   output in that task's Log as the Verify evidence. Do not re-run the
   task Verify command or PLAN.md's project Verify. Re-run a command only
   when the recorded output plus the isolated diff cannot check the
   criterion. Never use the primary worktree or branch tip as task
   evidence. Do not create or remove Git worktrees yourself.
4. Mark `pass` or `fail`. Before the evidence separator (` — `), copy the
   complete task acceptance or interface criterion verbatim, joining wrapped
   lines with spaces. Do not substitute an AC id or summary: finding grouping
   binds this text to the task. Give the observed result, `file:line`, and
   concrete fix direction for each failure.

Then check each INTENT.md success criterion owned by a task in this wave
against that same isolated product. Copy the criterion verbatim from
INTENT.md. Mark `pass` or `fail` with evidence; a failed owned SC blocks
the wave. Omit the Intent coverage section when no task in the wave owns
an SC.

Allow changed paths only in the task's `files` plus its assigned task file.
Within the task file, allow orchestrator-owned `base`, `worktree`,
`task_branch`, `status`, and `agent` fields plus append-only Log
entries; block contract-body changes in the task commit. Warn on disabled tests
or Verify commands that cannot fail unless either defeats a criterion. Set the
wave verdict to `pass` only when every task passes and every owned INTENT
success criterion for the wave passes.

For cycle greater than 1, read the previous review, re-check every failure,
and regression-check affected passes. State when the same criterion fails for
a different reason. Use only the wave-review template.

### Re-review after a proven repair

When the brief supplies a `review_findings.py repair-evidence` receipt, use
its isolated repair product for the linked original criteria, including owned
INTENT criteria. The original faulty landing and earlier verdicts remain
historical evidence; they do not force the later verdict to remain failed.
Reconstruct the receipt's repair `base` plus only its `commit^..commit` patch
for `files` inside the supplied sidecar. Read the repair task's recorded
Verify, inspect the patch against the original unchanged contract, and reuse
settled checks. Check unaffected criteria from their prior evidence plus the
repair diff for regressions. Cite the receipt, repair landing and task Log in
the new review. A receipt proves provenance, not acceptance: judge whether the
repair actually satisfies the criterion. A missing or rejected receipt blocks
using that repair; the parent resolves it rather than creating another product
fix for the unchanged historical failure.

## Final scope in a quick full wave

When explicitly briefed with final scope, record `Review scope: final` and the
full supplied review HEAD in the wave artifact. Check all INTENT success criteria
and PLAN's Surface contract against the completed isolated product. Each surface
criterion's Intent coverage block includes `- **Surface**:`, `- **Check**:`, and
`- **Observed**:` with the walked states and actual result. Reuse recorded task
output if it proves that exact walkthrough; run only a missing check. Final-scope
coverage shares this wave artifact; do not write a second report. Shipping's
runtime checks freshness and derives the final view from these records.

## Deep review lenses

A `deep` wave spawns two independent reviewers in parallel, each with a fresh
context and its own verify sidecar at the recorded review base. Every
Wave mode rule above applies to both lenses.

- **Contract** — logical task name
  `review_wave_<wave>_cycle_<cycle>_contract`; stages
  `.project/review/wave-N.cycleC.contract.md`. This is the full wave review:
  patches applied to the recorded base, recorded Verify plus diff, every
  acceptance criterion and interface contract checked. Record `Lens:
  contract`.
- **Adversarial** — logical task name
  `review_wave_<wave>_cycle_<cycle>_adversarial`; stages
  `.project/review/wave-N.cycleC.adversarial.md`. Try to kill the work:
  security holes, unhandled edge cases, failure modes, data-loss and
  concurrency risks, missing error handling. Record `Lens: adversarial`.

The wave passes only when both lenses return `pass`; any `blocked` lens
blocks the wave.

