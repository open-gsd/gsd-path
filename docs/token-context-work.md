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

## Authorized next round: planning input

The owner authorized another optimization round with unchanged 4,000-token task
and 30,000-token session budgets. The source has no owned project state. Scope
was narrowed to a directly reproduced loading defect rather than splitting more
phase documents: the original planning trace executed full reads of both
check_handoffs.py and review_panel.py, plus the unused planner role and panel
template. Those four inputs total 24,493 o200k_base tokens. This is available
source size, not billed input or a claimed output saving; tool truncation and
repeat reads affect the actual transcript.

Planning now resolves executable paths and consumes helper results. It reads
source only for a concrete failure unexplained by documented recovery. Quick
planning loads its own plan/task templates, skips the child planner role and
runtime contract, and leaves the panel template to a ready panel. The canonical
`planning started` event is now explicit in Quick mode; skipped phases go in
synthesis, avoiding the rejected extended event seen in the native trace.

Ponytail review: changed instructions only; reused every existing helper and
gate. Deferred broad mode splitting and installer-provenance changes because
the trace supports this smaller change. No new engine, ledger, dependency, or
verification gate. Canonical sync passed with no warnings. The existing skill,
dispatch, and resource suites passed all 12 tests; git diff --check passed.
Runtime behavior and savings still require the phase replay below.

### Planning replay result

Candidate `232e810484c831815c85d5db792bc604efac63af` was exercised with
Codex CLI 0.154.0, gpt-6-astra/high. The evidence is in
[token-context-round4.json](token-context-round4.json), including native event
paths, gate output, command reads, and budget records. Both replay fixtures
start from the same approved intent, historical inspection artifacts, and
settled synthesis at the original approval checkpoint. Fixture setup restores
`define/done` before planning; this is not a new inspection or delivery receipt.

- First replay: 3,979 output tokens, 176.89 seconds. The host loaded its global
  old planning skill first and read both Python helpers. Retained as a
  contaminated attempt, not a matched control or candidate success.
- Exact-path candidate replay: 4,528 output tokens, 193.39 seconds. The native
  command trace contains no reads of either Python helper. The existing
  gate-plan command passed, and product source and approved intent stayed
  unchanged. The plan stopped at `plan/active` for owner approval. Output was
  528 over the unchanged 4,000 task budget; the completed counter was recorded
  through the canonical helper and retained.
- The candidate actor guessed a missing plan-bundle token helper, then found
  the router copy and ran the required diagnosis. The cloned fixture also had
  no origin/main ref. Those observed setup costs remain in the counters.
- Both native replays together used 8,507 output tokens. This excludes the
  optimization parent and fixture setup, so it is not complete session usage.

Executable evidence checks assert that the old-skill replay read helper source,
the exact candidate did not, each native plan gate exited zero, and neither
replay changed product source or approved intent. Documentation-only changes
need no new product tests. The earlier 12 contract/resource tests remain green.
No completed-delivery speedup, causal output reduction, or end-to-end budget
compliance is established. The original 21,877 pre-code output-token finding
remains open. Further speculative mode splitting and inventory exclusions were
not needed to prove this loading fix.

## Continued goal: evaluator overhead and audit scope

The owner requested continued work with the existing budgets. Three workstreams
were exercised: evaluator prompts, installed documentation, and docs-auditor
scope. See [round-five evidence](token-context-round5.json) and
[evaluator verification](token-harness-verification.json).

### Changes

- The evaluator names the installed candidate by absolute path. Its default
  prompts no longer require agent-authored timing wrappers. Native event and
  process timing capture remain; unclassified activity is not invented. The
  old review trace had two failed nested-shell attempts while writing its
  artifact. This is measurement overhead, separate from skill overhead.
- AGENTS.md scopes distribution paths and sync commands to the GSD Path source
  checkout. WORKFLOW.md distinguishes source references from installed paths,
  removes the stale catch-all commit ownership statement, and describes
  evidence for dispatched research dimensions rather than four mandatory ones.
- The auditor scopes claims to the repository's product. Excluded dependency
  internals do not create unverifiable findings. Mixed documents retain their
  application commands, configuration, and integration promises. GSD Path's own
  source repository still audits its pipeline as the product. Instructions and
  authority conflicts remain binding. Fixed-format inventory and remediation
  fields retain exact paths and claims; explanations go in separate prose.

### Observed verification

The fresh native workflow at `b1962b1` stopped before coding at six docs rulings.
The parent used 5,367 output tokens; code inspection used 2,962 and docs
inspection 3,193. Its canonical ledger retains all 11,522 tokens. Both inspectors
were within the 4,000 task budget; the parent was not. This run did not establish
a completed-delivery improvement.

A separate audit after the source-document clarification used 4,650 tokens and
created 18 unverifiable dependency-internal findings. That failed result exposed
the remaining scope bug; it is retained, not counted as a success.

The scope proof used a fixture with a deliberately false README claim: running
count.py with 9 allegedly prints 10 widgets. The real command prints 9 widgets.
The auditor caught that drift, verified the correct CLI claim, and accounted for
AGENTS.md and WORKFLOW.md as two descriptive documents. It created zero
unverifiable dependency findings. Initial output was 1,496 tokens, but the parent
format gate rejected explanations embedded in path bullets and mismatched
remediation fields. The original wrapper captured that gate's stderr without
retaining it; the failure is recorded explicitly. Diagnosis passed, reporting
only expected uncommitted state and the active verification sidecar.

A same-thread format repair consumed another 896 tokens, for 2,392 total charged
to the same docs task. It used the corrected role at `80ae763`, reused the
recorded product evidence, and did not repeat product checks. The canonical docs
gate then passed; canonical collection and retirement also passed. Native
cumulative counters were recorded with the verified previous-events convention,
not summed twice. This is a successful scope-and-drift proof, not a fresh
end-to-end run of the final candidate.

All 25 existing docs-audit and resource tests passed. The evaluator's generated
input integration check failed on the old unbound prompt, passed on the new
installed candidate, failed when that candidate file was removed in a separate
disposable fixture, and passed after restoration. A preliminary byte-equality
assertion was rejected because installation legitimately transforms host syntax;
the corrected check verifies the installed target and candidate receipt. No new
product tests or full-repository suite were needed. Ponytail review retained the
existing helpers, evidence formats, and gates without adding another runtime or
ledger design.

### Open contract

Native trials in this pass used 18,564 output tokens, including the format repair.
That number excludes the optimization conversation and fixture setup, so it is
not complete session accounting. The last whole-workflow attempt exceeded the
parent task budget. End-to-end delivery within both owner budgets remains
unproven. The three-round fuse ends this pass; the remaining necessary work is
reducing parent orchestration and measuring completed delivery. No universal
optimality, causal whole-pipeline saving, or goal completion is claimed.

## Parent inspection preparation runtime

The continued goal targets the measured 5,367-token parent overrun. The existing
workflow runtime now has `prepare-inspect` for an initial active-track inspection
with no prior inspection outputs and a clean Git product. It validates state and
pending discussion, freezes the canonical inventory outside .project, creates the
two canonical verify sidecars, and generates exact role/template/output briefs.
The parent dispatches brief-file references plus current user constraints, then
uses the existing artifact gates, collection, retirement, and phase transition.
Prior evidence, lookahead, and dirty/non-Git inspection retain the existing path.
There is no new ledger, agent launcher, or phase-state writer.

RED: the public CLI test failed because prepare-inspect was not a supported
action. GREEN: the same test created two distinct worktrees at the recorded HEAD,
kept later documents outside the frozen inventory and sidecars, and left primary
research outputs untouched. The standalone inspect bundle passed the same test.
Prior evidence and later phases block before sidecar creation. One initial test
fixture lacked its research directory; after correcting the fixture, that guard
test passed. The 20 targeted workflow/resource/command checks passed across the
focused runs. Sabotage blanked the inventory write in the canonical runtime; the
CLI test failed on missing AGENTS.md/README.md, then passed after restoration.
Resource sync completed without warnings. Ponytail review: fixed composition of
existing canonical helpers; original audit, isolation, and publication gates stay
in force. Native end-to-end budget evidence is still pending.
