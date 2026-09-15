# Token context work

## Contract

Reduce irrelevant instructions and model-managed bookkeeping without weakening
approved constraints, task isolation, review, or publication gates.

- Load build procedures and reviewer modes only when their branch applies.
- Generate coder intent context from approved files, preserving constraints,
  vetoes, corrections, source identity, and owned success criteria. Ambiguous
  input retains full intent; it must never silently lose a requirement.
- Use the existing deterministic driver for supported operations; preserve a
  native-tool path when no owner-supplied child command exists.
- Verify generated context and installed resource loading, measure before/after
  instruction size, and exercise a completed delivery before claiming runtime
  token savings.

## Baseline

Clean evaluation branch `jeremymcs/token-eval`, HEAD and live origin/main
`ca1152d69e0a8e57bdbb9ddaae00708823587e5c`; no merged PR for this branch and
no active `.project/STATE.md`. No CONTRIBUTING.md exists at this revision.

Measured with o200k_base: build plus required role/template reads 17,637 tokens;
coder role, task template, and repository AGENTS.md 7,098 tokens, before task,
intent, product source, or host context. Historical runs are evidence of prior
overhead, not a measurement of this change.

## Implementation

- Build loads the driver path first. Native dispatch/recovery and abandon are
  separate procedures. Optional review templates are loaded only on their branch.
- Reviewer modes have separate procedures with common authority and evidence rules.
- Coder briefs contain a deterministic intent view with source/task hashes. All
  non-criterion text stays verbatim, including unknown sections. Owned criteria
  and explicit SC references in task/global text are retained. Unfamiliar criteria
  formatting retains full intent. Invalid ownership fails before dispatch.
- Native coders use the existing `finish` runtime after returning; both dispatch
  paths use `complete`. This removes manual verification/landing and completion
  sequences without introducing a new orchestration engine.
- Canonical resources were synchronized into standalone skills and the alias.

## Evidence

- RED: `python3 -B -m unittest tests.test_task_context.TaskContextTests.test_dispatch_supplies_context_without_a_second_intent_read`
  failed because the existing dispatch supplied only the intent path, with no
  required criterion or global rule in the brief.
- GREEN: `python3 -B -m unittest tests.test_task_context tests.test_dispatch_contract tests.test_skill_commands tests.test_sync_skill_resources`
  passed 14 tests. This exercises generated output, ambiguous-format fallback,
  explicit cross-criterion references, invalid ownership, standalone bundled
  execution, resource synchronization, and disclosed command/name contracts.
- `python3 -B -m unittest tests.test_dispatch_driver` passed 65 tests, including
  isolated serial/parallel coding, native finish, collection, retry, and completion.
- `python3 -B -m unittest tests.test_router_contract tests.test_lean_verification`
  passed 15 tests, including final-review reuse and project verification evidence.
- Sabotage: patched `scripts.dispatch_driver.task_context.render` in a disposable
  Python process to return full intent. The dispatch contract test failed because
  it received the unrelated SC2. The patch was restored on context-manager exit.
- `python3 -B scripts/sync_skill_resources.py` completed with no divergence warnings.
- Ponytail review: reused the existing driver and handoff parser; no dependency,
  new tracking ledger, or model-based routing was added.

## Measured prompt load

See [machine counts](token-context-metrics.json). Build's initial driver path fell
from 17,637 to 2,333 o200k_base tokens before conditional host-counter instructions.
With those instructions the driver path totals 4,399; the native path totals 12,179.
Coder fixed instructions, including repository AGENTS.md, fell from 7,098 to 6,519.
The intent view's hashes/header add input; savings depend on how many unrelated
criteria can be omitted. Small/all-owned intents may not shrink. These counts
exclude tool output, host context, caching, and model behavior.

## Open work

Native attempts and their accounting are recorded below. Successful end-to-end
delivery within the owner budget remains unproven. No runtime token saving or
whole-pipeline completion improvement is claimed from static counts.

The fresh matched fixture is `/Users/jeremymcspadden/orca/evaluations/token-context-504ebeb`.
It pins candidate `504ebeb580bf80b4d86b5a35c17a5403f4562966`, uses the same widget
requirements for quick Path and direct coding, and records Codex CLI 0.154.0,
gpt-6-astra/high, danger-full-access. Both remotes are local fixture repositories.
Raw prompts, command events, counters, and execution status are in each arm's
`run-*` directories. Path thread: `01a0a553-5d16-77b3-b6e2-e43f35ec379c`;
direct thread: `01a0a553-8e49-7da0-abaa-55ebc5997950`.

### Live finding: installed alias entered the docs audit

The first Path run reached the intent gate without coding. Its frozen inventory
contained 51 Markdown files, including 48 files from `.agents/skills/path/`.
The existing exclusion recognized `gsd-path*` but missed the distributed `path`
alias. The resulting audit created 12 unrelated alias findings, plus three
fixture-root tooling findings. Parent output alone reached 6,050 tokens.
The direct arm completed in 144.99 seconds with 3,347 output tokens.

The alias exclusion now matches the canonical bundle exclusion. On the same live
fixture the command emits only AGENTS.md, README.md, and WORKFLOW.md. RED:
`python3 -B -m unittest tests.test_check_docs_audit.CheckDocsAuditTests.test_inventory_command_excludes_the_installed_path_router_alias`
failed with two alias files in the result. GREEN: all 19 docs-audit tests passed.
Sabotage: temporarily restored the old predicate in the canonical source; the
same CLI test failed, then the exact source bytes were restored. An initial
in-process mock did not affect the CLI subprocess and was correctly rejected as
proof. Ponytail review: extended the existing exclusion; no new inventory or
classification mechanism. The first native thread is terminal at the intent
gate; it is retained as a partial run, not a completed benchmark.

### Corrected candidate and cumulative counter proof

The second fixture is `/Users/jeremymcspadden/orca/evaluations/token-context-efe4163`,
pinning `efe4163a3707740ac3ca4c7f90d9268ab310c588`. Its native thread is
`01a0a55b-9996-7681-8377-bdfd8d9a62c2`. Required general skill paths were supplied
explicitly to remove fixture catalog ambiguity. The first invocation ended after
inspection: parent 4,148, code inspector 3,672, docs inspector 4,173 output tokens.
The three remaining root tooling findings received explicit fixture-only
accept-drift rulings. These phases still exceed some per-task budgets; no budget
compliance is claimed.

The current CLI's native trace proves counters persist across resume: the first
parent invocation ended at 4,148; the first counter in the next invocation was
4,524 and its final counter was 8,226. The next invocation therefore generated
4,078, not 8,226 additional tokens. Its artifact/owner-ruling work still cost more
than 4,000. Do not sum the two cumulative totals. Historical CLI versions need
their own trace interpretation; this finding does not recalculate old benchmarks.

`token_budget.py record --previous-events` now supports an explicitly verified
cumulative CLI counter convention. It requires the same thread, an unchanged
recorded predecessor, and a non-reset counter. It retains the raw counter and
predecessor while charging only the increment to that invocation's task. Ordinary
per-invocation counters retain their existing behavior. See
[real-trace accounting proof](token-context-counter-proof.json): parent total
8,226, plus inspectors 7,845 = 16,071 through the intent draft.

RED: `python3 -B -m unittest tests.test_token_budget.TokenBudgetTests.test_cumulative_resume_records_only_new_output`
failed because the CLI lacked the predecessor option. GREEN: six token-budget
tests passed. Sabotage replaced the subtraction with the full counter; the same
test failed on 7,100 versus expected 4,100, then exact source was restored. The
test also proves duplicate records do not add cost and a different thread cannot
alter the ledger. Real preserved CLI events exercised the new option successfully.
Ponytail review: extended the existing recorder, with no replacement ledger.

Additional provenance check: temporarily replacing byte reads with newline-
normalizing text reads made the CRLF source-hash test fail. The restored byte
reader passed. This changes tests only; the tested candidate already reads bytes.

The pinned native fixture remains unchanged. Its old recorder receives an
evaluator-produced, source-linked usage delta file so the live ledger remains
accurate without patching the installed candidate. Intent has been reviewed and
approved with a precise positive-veto wording correction.

## Final live result: delivery incomplete

[Full machine evidence](token-context-live.json) records the completed native
invocations and their sources. The coder landed its task and full wave review
passed all five criteria. Both Path and direct products passed all six independent
CLI acceptance checks. The Path run stopped at `observed output budget exhausted`
before build completion and shipment. No integration or completed-run token saving
is claimed.

| Responsibility | Output tokens |
|---|---:|
| Parent, cumulative total across four invocations | 18,346 |
| Code inspection | 3,672 |
| Docs inspection | 4,173 |
| Coder including tests | 3,058 |
| Full wave review | 6,153 |
| **Total** | **35,402** |

Direct completed at 3,347 tokens and 144.99 native seconds. Path used 1,186.12
native parent-execution seconds, including waits for its children, and remains
unshipped. Owner waiting time is excluded. These are different delivery endpoints,
so this is not a completed speedup comparison.

The budget ledger now includes the final parent increment of 4,314, with source
provenance, rather than stopping at the parent's partial 31,088 report. The
session exceeded 30,000 by 5,402. The code inspector and coder stayed under 4,000;
the docs inspector, reviewer, and each parent invocation exceeded it. In-flight
generation was not hard-capped. Preserve these failures; do not reset the ledger.

The source changes and focused verification are complete, with three local
implementation checkpoints: `504ebeb`, `efe4163`, and `0c9c7df`. Remaining scope:
a completed native pipeline run within the owner budget is unproven. Static
loading improved and wrong inventory data was removed, but the live run still
spent 21,877 tokens before coding and 32,344 outside the coder. Another optimization
round needs a ruling under the supplied MSW three-round fuse; finishing this same
native run would also require an explicit budget change. No further model work
has been dispatched in the exhausted fixture.
