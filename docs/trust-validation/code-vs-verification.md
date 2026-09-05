# Code versus verification and recovery cost

## Owner objective

Owner correction, verbatim:

> im not focused so much on token reduction - as i am on spins. the actual code being generated is too small when compared to the verification work + files. If we get that fixed, the token count would naturalyl follow with less usage

The primary target is less orchestration, repeated verification, and artifact
handling per completed requested outcome. Token usage is a secondary measurement.
Do not increase code volume, enlarge scope, or add work to improve a ratio.

The latest fixture already used one task for the whole CLI deliverable. At the
ship commit it has 12 lines in count.py, 64 lines in test_count.py, and 16 tracked
pipeline artifact files under .project (including recovery artifacts, excluding
installed plugin bundles and external evaluator reports). These counts describe
the observed workload; they are not targets or acceptance thresholds.

### Direction for the next implementation

- Move the remaining deterministic verification and closeout sequencing into
  the runtime. workflow_run.py currently covers plan gates, preparation, and
  landing evidence; the ship skill still asks the model to coordinate helper
  calls, sidecars, collection, evidence records, and archive steps individually.
- Keep one authoritative record for a verification result and reference it from
  later gates. Generate metadata and required report formatting from checked
  data so agents supply judgment rather than duplicate evidence or invent paths.
- Review the quick lane's required artifact set with its consumers. Consolidate
  redundant records through an explicit contract change; do not silently delete
  required artifacts or replace proof with shorter prose.
- Reject invalid paths and metadata before they enter an archive transaction.
  Normal interruption recovery must not require another implementation/review
  cycle to repair paperwork.
- Keep task verification, wave review, and final review requirements until their
  governing contracts change. Show a reduction in repeated dispatches, repeated
  checks, evidence rewriting, and recovery cycles while proving the same outcome.

This records the corrected objective and the observed implementation seam. It
does not claim these next source changes have been implemented. Existing passing
product checks do not prove that workflow overhead is fixed.

## Measurement correction

The user corrected the evaluation focus: total tokens did not explain the time
spent spinning through verification compared with writing code. The stage-level
comparison supports that concern. This is an observed comparison of two completed
runs, not a controlled experiment: the earlier run used standard lane, the latest
used quick lane and needed additional authorized recovery.

## Observed change

| Measure | Earlier completed run | Latest completed run | Change |
|---|---:|---:|---:|
| Coder task time, including its own tests | 2.10 min | 2.89 min | +37.4% |
| Active workflow time after coder handoff | 9.91 min | 25.62 min | +158.5% |
| Reviewer task time | 3.99 min | 6.73 min | +68.7% |
| Total native CLI execution time | 32.94 min | 38.47 min | +16.8% |
| Coder output tokens, including tests | 3,222 | 4,226 | +31.2% |
| Wave and final reviewer output tokens | 6,736 | 9,787 | +45.3% |
| Parent orchestration output tokens | 34,147 | 34,553 | +1.2% |
| Recorded total output tokens | 61,294 | 54,636 | -10.9% |

Reviewer time is part of the workflow after handoff; do not add these rows.
After-handoff workflow includes isolated verification, review, orchestration,
recovery, archive, and integration. It excludes time waiting between native CLI
invocations, including owner approvals. It is not a measurement of tests alone.
Parent costs mix phases and must not all be labeled verification.

In the latest run, active work after coding took 8.86 times the coder task time.
In the earlier run it took 4.71 times. The implementation was already correct;
shipping instruction, bookkeeping, and metadata recovery failures prolonged the
workflow. A bookkeeping correction changed the reviewed commit and required a
second project verification and final review. The reviewer evidence records two
final-review invocations in the latest run versus one in the earlier run.

The previous total-token answer was incomplete: fewer total tokens did not mean
less verification overhead or faster delivery. This run does not demonstrate an
improvement in the user's code-versus-verification efficiency concern.

## Method and limits

Native `task_started` and `task_complete` timestamps define coder and reviewer
intervals. Each task turn's final cumulative output counter supplies its tokens;
a reused reviewer thread is counted once per invocation. After-handoff time is
the intersection of completed parent CLI run intervals with time after the coder
finished. This excludes between-run pauses and avoids summing overlapping parent
and child time. Total CLI time is the sum of the measured run durations.

Coder time includes implementation, tests, and task logging. It does not isolate
pure code generation. Review time includes the reviewer's reads, judgment,
walkthroughs, and writing. A precise token split for the parent's individual
verification and recovery steps was not captured. Caller-declared shell activity
categories measure subprocess duration and omit model and coordination time, so
those totals cannot stand in for workflow cost.

The useful measures for future controlled comparisons are coder time/tokens,
authoritative verification execution, review time/tokens, recovery time/tokens,
and time from coder handoff to validated integration. Fixed acceptance criteria
and separately reported recoveries are needed to attribute savings to changes.
No new limits or acceptance thresholds are proposed.

## Evidence

- [Per-turn timestamps, counters, and calculations](evidence/releases/1.0.0/codex-e2e-50718f8/code-vs-verification.json)
- [Earlier completed run](evidence/releases/1.0.0/codex-completed-run.md)
- [Latest completed run and recovery](e2e-50718f8.md)
