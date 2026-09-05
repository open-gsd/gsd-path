# Code versus verification and recovery work

## Owner objective

Owner correction, verbatim:

> im not focused so much on token reduction - as i am on spins. the actual code being generated is too small when compared to the verification work + files. If we get that fixed, the token count would naturalyl follow with less usage

The target is less orchestration, repeated verification, and report writing per
completed outcome. Product scope and line counts must not grow to improve a ratio.
No numeric code-to-verification target or new limit is inferred.

## Implemented and exercised

Candidate `62f5e0f26ba2ab600494785b54d56fa92c06a5a5` reuses a complete quick-lane
full-wave review for final scope when Git proves unchanged product and contracts.
The reviewer records required walkthroughs once. The runtime generates FINAL.md
from that evidence instead of dispatching another model to review and rewrite it.
Multiple waves, other review depths, missing evidence, or changed inputs retain
fresh final review.

The ship runtime owns project Verify isolation, execution, output recording,
collection, and cleanup. Exact stdout/stderr live once in the existing ledger;
the project gap references that receipt. A retry rebuilds the view and retires an
interrupted sidecar without rerunning the command. Dirty inputs are rejected.
Legacy entries without exact output require reconciliation, not a blind rerun.
Duplicate Reviewed HEAD metadata is rejected before archive entry.

The fresh native quick-lane E2E completed with one coder, one full-wave reviewer,
no separate final reviewer, one project Verify execution, no post-coding metadata
repair, and no archive recovery. Canonical archive/integration validation passed;
the local integration is `459e4cb6b6ec72d3bd8dfa0918d87935b8ce6034`, tagged
`milestone/001-widget-counter`. All six external CLI checks passed. The primary
is clean, all sidecars are retired, and the pinned installed plugin is unchanged.

## Observed comparison

| Measure | Previous quick run, 50718f8 | Lean quick run, 62f5e0f |
|---|---:|---:|
| Coder time, including its tests | 2.89 min | 2.09 min |
| Reviewer time | 6.73 min | 2.62 min |
| Active workflow after coder handoff | 25.62 min | 7.43 min |
| Total native CLI execution | 38.47 min | 25.51 min |
| Full-wave reviewer invocations | 1 | 1 |
| Separate final-review invocations | 2 | 0 |
| Project Verify executions | 2 | 1 |
| Tracked pipeline artifact files | 16 | 15 |
| Product / product-test lines | 12 / 64 | 12 / 66 |
| Coder output tokens | 4,226 | 2,860 |
| Reviewer output tokens | 9,787 | 4,232 |
| Parent output tokens | 34,553 | 25,355 |
| Total output tokens | 54,636 | 38,848 |

Reviewer time fell 61.1%; active work after coding fell 71.0%. In the new run,
reviewer time is 1.26 times coder time; all post-coding work is 3.56 times coder
time, down from 8.86. These are observations, not acceptance targets. The product
remained 12 lines; the change did not inflate code volume to improve the ratio.

The main reduction is model work: three review invocations became one, and the
final and project-gap views required no model authoring. Required views still
exist on disk; this did not eliminate the pipeline's artifact structure. The new
run also retained plan gate and transition receipts. File count alone does not
measure avoided review and report-writing work.

## Method and limits

Both quick runs use the same widget-counter requirements, Codex CLI 0.153.4,
gpt-6-astra/high, full review, no panel, and direct integration to a local origin.
The old run needed explicit recovery and a second final review/project Verify
following a bookkeeping correction. The new run did not. This is one observed
comparison, not a controlled timing estimate or a claim that every run saves 71%.

The new run still had pre-coding overhead: an interrupted global-skill selection
(53.85 seconds, included in total execution), two rejected transition event
arguments followed by diagnostics, a documentation-audit check with the wrong
repository root, and an owner ruling on unrelated installed documentation links. These remain visible in the evidence. This change targets
verification after coding; it does not remove inspection and planning overhead.

Native task_started/task_complete timestamps define coder and reviewer intervals.
Each turn's final output counter supplies tokens, including already-counted
reasoning without adding it again. Active work after handoff intersects completed
parent CLI intervals with time after the coder finished; it excludes between-run
approval pauses. Reviewer time overlaps parent time and must not be added to it.
Coder time includes tests and logging. Neither interval isolates pure code
sampling or pure command execution. External evaluator checks are separate from
the native delivery cost.

The earlier completed standard-lane run took 2.10 minutes of coder time, 3.99
minutes of reviewer time, 9.91 active minutes after handoff, and 32.94 total CLI
minutes. Different lanes and recoveries limit causal comparisons with that run.

## Evidence

- [New run: timestamps, counters, runtime reuse, product checks, and integration receipt](evidence/releases/1.0.0/lean-verification-e2e.json)
- [Behavioral sabotage results](evidence/releases/1.0.0/lean-verification-sabotage.json)
- [Implementation and regression proof](runtime-followup.md)
- [Previous quick run and recovery](e2e-50718f8.md)
- [Earlier per-turn comparison](evidence/releases/1.0.0/codex-e2e-50718f8/code-vs-verification.json)
