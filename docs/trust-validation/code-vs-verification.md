# Code versus verification and recovery cost

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
