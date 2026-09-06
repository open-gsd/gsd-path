# Quick-lane Codex comparison

Tested candidate: `76051f9ce85d55728311141fe4a7d0c0ed356b80`.
Model: gpt-6-astra, high reasoning, Codex CLI 0.153.4, danger-full-access.
The fixture used quick planning, full review, no optional panel, and direct local
integration. Exact evaluator approvals and recovery rulings are retained.

## Outcome

Both products pass all six independent CLI acceptance checks. Direct completed
cleanly. Path landed the product and its isolated Task Verify passed. The native
full wave reviewer returned pass for all five intent criteria, but collection of
that review failed. Path stopped under the owner's three-round recovery fuse.
It remains build/blocked; it did not run ship, archive, or integrate.

| Recorded measure | Direct | Quick Path |
| --- | ---: | ---: |
| Agent execution time | 127.751 s | 1,107.171 s, incomplete workflow |
| Wall time through final stop | 127.751 s | 1,489.927 s |
| Parent and native child output tokens | 3,509 | 33,998 |
| Independent product checks | 6 passed | 6 passed |
| Shipped/integrated pipeline | Not applicable | No |
| Final worktree | Clean | Dirty, preserved recovery records |

These are observed costs, not a completed speedup comparison. The earlier
[standard-lane run](codex-completed-run.md) completed at 61,294 output tokens;
quick's lower partial count does not establish equivalent delivery or an optimum.

## Where the output tokens went

| Responsibility | Output tokens |
| --- | ---: |
| Parent orchestration across five invocations | 19,949 |
| Coder, including tests and sabotage checks | 3,502 |
| Code inspection | 3,297 |
| Documentation inspection | 2,749 |
| Full wave review | 4,501 |

The coder's 3,502 tokens were close to direct's entire 3,509-token implementation.
Quick planning skipped research, decision, and planner children. Workflow
coordination still dominated. The wave reviewer exceeded the owner's 4,000-token
per-task budget. Aggregate observed session output exceeded 30,000. Parent-only
usage was below 30,000; the accounting above explicitly includes native children.

The new budget helper was then exercised against these actual completed event
files. It reconstructed exactly 33,998 output tokens and blocked the next task on
session exhaustion. A strict admission request separately returned
`hard_cap_supported: false`. This post-run observation does not retroactively make
the baseline run budget-compliant or prove in-flight enforcement.

## Failures and fixes informed by this run

- Initial routing used a rejected event, then corrected it after diagnosis.
- A log-only state transition omitted changed fields and was rejected.
- Serial coding dirtied the primary before verification-sidecar creation. The
  helper correctly refused a dirty base. The new runner prepares that sidecar
  before dispatch; its regression test verifies the ordering.
- Recovery checkpointed while the task remained in progress, moving HEAD beyond
  its base. The final evaluator ruling specified clean pending bookkeeping,
  pre-created isolations, activation, verification, and landing without an
  intermediate checkpoint. The task then landed as
  `de16e99cb0ca4ab7107b88db8025f569a601442b`.
- The wave reviewer used the earlier task sidecar. Collection correctly refused
  its stale base. The build instructions now name a fresh sidecar at current
  clean primary HEAD for review collection, while task base/landing pairs still
  determine each isolated review diff. This clarification has not had another
  native run; the recovery fuse ended this benchmark.

No installed plugin source or archived artifact was repaired. The new source
fixes and their [verification record](../../../runtime-followup.md) are separate
from this unchanged candidate's measurement.

## Evidence and limits

Parent usage sums completed CLI invocation counters. Each completed native child
uses its cumulative counter. Reasoning fields are retained and not added to output
again. Effective recorded permissions remained danger-full-access. Operator work
is outside the arm counters. Activity labels cover only wrapped commands; their
failed-command count omits unwrapped failures and is not a defect count.

The generic comparison exited 3 because formal pipeline trust was unproven. In
this run the milestone is also independently known to be blocked, unlike the
completed standard comparison. No release-host receipt is claimed.

- [Machine comparison](codex-quick-run/comparison.json)
- [Metrics and roles](codex-quick-run/metrics.json)
- [Native session metadata and counters](codex-quick-run/native-sessions.json)
- [Final state and failure history](codex-quick-run/STATE.md)
- [Task and verification log](codex-quick-run/T001.md)
- [Passing but uncollected wave review](codex-quick-run/wave-review.md)
- [Observed budget ledger](codex-quick-run/observed-budget.json) and [executed budget receipts](codex-quick-run/budget-receipts.json)
- [Git evidence](codex-quick-run/git-evidence.json), [verified bundle](codex-quick-run/fixture.bundle), and [bundle verification](codex-quick-run/bundle-verification.txt)
- [Preserved raw fixture](/Users/jeremymcspadden/orca/evaluations/gsd-path-quick-76051f9)
