# Longer feature evaluation

This is an opt-in Codex evaluation, separate from release certification. It uses
real product work across milestones and separate scenarios for incompatible
branches of the workflow. It does not add sleeps, filler tasks, token budgets,
retry limits, or an invented implementation-to-verification ratio.

The main program has three milestones because it must observe two different
lookahead promotions: an unchanged plan, then a plan whose owned file changed.
A single milestone cannot prove either boundary.

## Prepare and run

Commit the candidate before preparing. The harness clones that exact revision,
installs its skills locally in isolated repositories, and uses local bare origins.
It preserves existing evaluation directories. The globally installed skills are
not changed. Local pinned skills keep later updates from changing a running test.

```sh
python3 -B tests/evaluate_features.py prepare --directory /absolute/new-evaluation
python3 -B tests/evaluate_features.py check --directory /absolute/new-evaluation
python3 -B tests/evaluate_features.py run --directory /absolute/new-evaluation --scenario program --model gpt-6-astra --reasoning high --sandbox danger-full-access
```

Use the prepared `plugin/tests/evaluate_features.py` for subsequent commands.
`check` runs each mapped Python test module once, the Node tests once, and the
resource sync check once. It preserves test-level failures and skips. Repeating
`check` reuses the candidate receipt; changed candidates require a new directory.
A failed receipt is retained, not silently retried into a pass.

The native runner records prompts, JSON events, CLI identity, model settings,
exit codes and elapsed time under each scenario's `run-*` directory. It stops at
owner gates. Read the canonical artifact before writing the explicit approval
or steering instruction into an external text file, then resume the thread ID
from its `thread.started` event:

```sh
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py run --directory /absolute/new-evaluation --scenario program --model gpt-6-astra --reasoning high --sandbox danger-full-access --resume THREAD_ID --prompt-file /absolute/owner-reply.txt
```

This is an attended test. The harness does not generate approvals or drive every
scenario to completion unattended. Approval and lookahead steering must be real
owner instructions. Preserve the thread and evidence directory between sessions.

## Scenario coverage and required native proof

| Scenario | Scope | Proof required |
|---|---|---|
| program | Brownfield inspection, definition, research routing, decisions, roadmap, standard planning/build, independent and dependent tasks, lookahead, direct ship | Canonical artifacts, task dispatch/landing order, both promotion outcomes, all milestone integration receipts and ledger oracle |
| quick | Quick lane, lean final review reuse, project Verify cache, guards | No final reviewer when eligible; one project Verify execution at unchanged HEAD; repeated prepare-final reuses its receipt; actual host guard refusal in an evaluator-owned disposable fixture |
| greenfield | Greenfield routing, actual research and synthesis, standard full review | Official Python evidence for the declared parser question, approved decision, canonical ship and counter oracle |
| reviews | Deep lenses, optional panel, finding skeptics and patch | Actual supported reviewer identities, advisory panel behavior, a real blocked criterion and its legal patch disposition; absent findings remain unexercised |
| discussion | Any-phase discussion and disposition gates | Append-only records, pending receipt refusal, legal disposition and unchanged product/state ownership |
| recovery | Forensics, undo and loop | Read-only diagnostic, reviewed undo target and receipt, explicit LOOP.md contract, no loop-owned commit or phase advance |
| abandon | Partial archive and roadmap re-slicing | Explicit abandonment ruling, retained product history, immutable partial archive, updated pending scope |
| docs-audit | Standalone documentation audit | Command-backed stale README finding in an owned disposable sidecar; unchanged source and docs |
| pull-request | PR integration | Approved GitHub target, same-PR reuse, required checks, owner merge commit, tag and canonical integration validation |
| bootstrap | New GitHub repository transaction | Exact target preview/approval, real journaled creation/resume, collision rejection and correct linked worktree |

The executable catalog is `tests/feature_scenarios.json`. Each prepared scenario
has its own prompt and `STEPS.md`. A native command failure or unavailable model
is evidence to classify, not permission to edit pipeline state by hand.

The `reviews` scenario does not guarantee a natural finding. If none occurs,
record patch/skeptics as unverifiable. A controlled native fault needs a reviewed,
concrete fault procedure; the deterministic failure tests alone do not prove a
live reviewer caught that fault. Recovery interruption paths have the same rule.

PR and bootstrap runs are blocked by the harness's `run` command. After approval
of exact targets, use the existing `evaluate_codex.py run --arm` runner with an
external prompt containing that ruling and the canonical bootstrap/ship flow.
For bootstrap, start from the approved invocation directory, not a manually
initialized pipeline checkout. Keep its receipts in the corresponding scenario.
No external target has been approved by this test plan.

This harness runs Codex. Other supported hosts require their existing host-matrix
receipts; a Codex pass cannot be relabeled as cross-host or release certification.

## Seeing lookahead work

M001 builds ledger storage in `ledger.py`. M002 plans reporting in `reports.py`,
`total.py`, and `export.py` while M001 is still `build/active`. Its owned paths
remain unchanged, so promotion should preserve `plan/done`.

M003 plans prefix filtering in `reports.py` while M002 is `build/active`, before
M002 changes that file. Once M002 lands, M003 promotion must identify changed
drift and reopen `plan/active`. Replan and approve through the legal gate.

Capture at the named checkpoints in `program/STEPS.md`:

```sh
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py capture --directory /absolute/new-evaluation --scenario program --label m2-lookahead-approved
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py capture --directory /absolute/new-evaluation --scenario program --label m2-promoted --promotion /absolute/actual-promotion-receipt.json
```

Use the raw canonical helper JSON for `--promotion`, saved when the helper ran.
The capture must match the current milestone and HEAD. Capture M003 in the same
way. The recorder calls the installed status helper; it does not parse or repair
STATE.md. Never reconstruct a missed checkpoint after shipment.

Planning during `build/active` proves phase overlap. Concurrent agents require
actual dispatch/completion intervals in host traces. The automatic report leaves
concurrency unverifiable; an operator must inspect those intervals separately.
An approval cannot move primary HEAD while an in-flight task or review requires
it fixed. If no legal scheduling point exists, that is a blocked lookahead
finding, not a reason to fake overlap or alter a base.

## Product, spin and evidence review

After the final program ship, run the external oracle. It exercises persisted
storage, invalid-write preservation, sorting, CSV quoting, totals and filtering.
Quick and greenfield use the independent counter oracle.

```sh
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py accept --directory /absolute/new-evaluation --scenario program
```

For spin analysis, use the existing activity wrapper shown in each prompt.
Report implementation, verification and review durations separately. Missing
measurements stay unavailable; shell durations do not measure all agent work,
and overlapping intervals cannot be summed into wall time.

Review the traces and canonical logs for:

- Coder and reviewer dispatches, repair rounds, and task-to-landing intervals.
- The same command repeated against the same isolated patch or unchanged HEAD.
- Whether a repeat had a real failure/change that justified fresh evidence.
- Product/test changes versus pipeline artifact changes, using Git diffs.
- Time from the last coding completion to integration, excluding recorded owner waits.

Do not turn observed proportions into gates. A redundant spin is an execution
that proves an already closed claim without changed inputs, a failure, or an
explicit test instruction. The quick scenario's deliberate cache probe must be
reported separately from accidental duplicate work.

The operator records a verdict per feature with hashed evidence paths and a
reason. Native run evidence must exist first. Changed evidence invalidates the
review. Choose `fail` for a reproduced contract break and `unverifiable` for
missing evidence or prerequisites.

```sh
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py review --directory /absolute/new-evaluation --feature lookahead --verdict pass --evidence /absolute/new-evaluation/program/captures.jsonl --evidence /absolute/new-evaluation/program/run-TIMESTAMP/events.jsonl --reason 'Both approved future plans were observed during build; canonical promotion receipts prove clean preservation and changed-file reopening.'
python3 -B /absolute/new-evaluation/plugin/tests/evaluate_features.py report --directory /absolute/new-evaluation
```

`REPORT.md` and `report.json` keep deterministic and native columns separate.
A CLI exit or agent's prose cannot mark a feature as passed. The overall report
remains incomplete until all listed features have the required proof and the
program, quick and greenfield product oracles pass. An omitted scenario remains
untested. The stop condition is complete evidence or a concrete reported block,
not elapsed time or an invented coverage percentage.

## Harness verification

`tests/test_evaluate_features.py` exercises real fixture preparation and install,
product CLI behavior, test-result collection, evidence hashing, receipt reuse,
and lookahead observation rules. The existing `tests/test_evaluate_codex.py`
checks the reused native runner, resume arguments, activity wrapper and counter
oracle against executable fixtures.

RED: focused evaluator tests failed on missing preparation/collection behavior,
false lookahead passes without observations, and stale product results retained
as passes. Commands used `python3 -B -m unittest` with the matching methods in
`tests.test_evaluate_features.FeatureEvaluationTests`.

GREEN: the evaluator suite passed 10 tests. The combined evaluator/native-runner
check before the last stale-product test passed 13 tests. After simplification,
the five changed evidence predicates were checked again and passed.

Sabotage: temporarily disabling skip rejection, lookahead timing, drift reopening,
product hash comparison, and subtest failure collection made each corresponding
focused test fail with exit 1. All mutations were restored. The program oracle
test also executes a real CLI with its prefix filter disabled and rejects it.
These results validate the harness, not the native skill features.
