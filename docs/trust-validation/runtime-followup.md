# Runtime follow-up from the Codex comparison

## Active goal: lean verification

Owner request: "it should be lean verification - not redudant or double work.
code output should equal ratio of work verification phases - impplement this
under /goal". This supersedes the earlier requirement to keep duplicate review
dispatches when an existing full review already proves the same outcome. No
numeric ratio or new limit is inferred. Product scope stays outcome-driven.

Implementation contract:

- Runtime-owned project verification creates its sidecar, executes the command,
  records output, collects the gap artifact, and retires the sidecar. A valid
  command/commit receipt is reused on re-entry rather than rerun.
- Quick lane with one complete wave may reuse its independent full review for
  final review only with explicit final scope, all intent coverage and surface
  walkthroughs, and Git proof that product and approved contracts have not
  changed. New code, changed intent/plan/task contracts, incomplete evidence,
  deep/verify-only review, or multiple waves require fresh final review.
- The runtime generates the final view from existing evidence. Agents do not
  rewrite proofs or introduce execution logs outside canonical artifact paths.
- Final metadata must pass the same uniqueness rules before archival; malformed
  evidence cannot pass final review and then strand archive recovery.
- Update canonical phase/role contracts, synchronize distributions, and validate
  the packaged command. Test reuse and invalidation through executable behavior.
- Run a fresh native quick E2E and record coding versus review dispatches,
  verification executions, artifact work, recovery spins, and delivered behavior.
  Token usage is secondary. Completion requires evidence, not changed files.

Progress: duplicate Reviewed HEAD rejection is implemented in the handoff gate.
Its regression failed for FINAL.md and final-gap-1.md before implementation;
three focused tests passed afterward; removing the guard made the regression
fail again, and the source was restored. Simplifier review retained the small
shared reviewed-head guard and existing fixture helpers.

Implemented: isolated project execution and output persistence, receipt reuse and
interrupted-sidecar cleanup, deterministic final views from complete quick full
waves, dirty-input and changed-contract rejection, and the packaged ship runner.
Canonical phase/role instructions now assign final scope to that wave reviewer
and prohibit a second review or duplicate output narrative when proof is reused.

Proof so far: 136 focused Python tests passed across lean verification, workflow
runner, handoffs, build state, and resource sync. All 133 Node packaging/install
checks passed. The new tests first failed on missing reuse, missing runtime
sequencing, duplicated output, dirty input, and interrupted cleanup. The packaged
CLI failed before bundling and now returns `final-gate` on both first execution
and receipt reuse. Six sabotage mutations fail their matching behavioral tests;
see [mutation results](evidence/releases/1.0.0/lean-verification-sabotage.json).
The earlier duplicate-header sabotage also failed for both FINAL and gap files.
Simplifier review reused existing dirty-path, atomic-write, and isolation helpers;
no new numeric code-to-verification target or model routing was introduced.
Fresh native E2E completed against `62f5e0f26ba2ab600494785b54d56fa92c06a5a5`
at `/Users/jeremymcspadden/orca/evaluations/gsd-path-lean-62f5e0f`.
Parent thread: `01a0729e-8e86-7f52-91e5-70716ca22574`. It used one full-wave
reviewer, zero separate final reviewers, and one project Verify execution. The
runtime generated FINAL.md and the gap view. Canonical archive and local
integration passed at `459e4cb6b6ec72d3bd8dfa0918d87935b8ce6034`; all six external
CLI checks passed. No post-coding metadata repair or archive recovery occurred.
The initial global-skill selection, two pre-coding event-argument corrections,
and a documentation-audit repository-root correction remain reported; no testing token/time limit was applied. Legacy receipts missing
exact command output still require reconciliation rather than a blind rerun.

[Measured outcome and limits](code-vs-verification.md): reviewer time 6.73 → 2.62
minutes; active post-coder work 25.62 → 7.43 minutes; artifacts 16 → 15, with the
product remaining 12 lines. This is one fixture comparison with different recovery
histories, not a universal timing guarantee.

Verification map for this change:

| Source | Executable proof |
|---|---|
| lean_verification.py | test_lean_verification: complete/surface reuse, changed-input rejection, exact-output persistence, retry reconstruction, and real bundled CLI |
| isolation.py | owned-sidecar cleanup, interrupted cleanup, primary and changed-HEAD refusal |
| build_state.py | real ledger persistence/reuse in lean tests plus existing build-state suite |
| check_handoffs.py | repeated-header regression for FINAL and gap, stale HEAD and surface checks, existing handoff suite |
| workflow_run.py | fail-stop landing regression and successful native prepare-final invocation |
| Resource manifest and generated bundles | actual ship-bundle CLI, sync suite, and all 133 Node installation/package checks |

RED: the new lean tests failed before their behaviors were implemented, including
uncommitted-contract acceptance and a leftover sidecar after interrupted collection.
`test_ship_bundle_returns_final_gate_without_review_dispatch` failed before the
helper was bundled. `test_ship_preparation_stops_at_unproven_landing` failed while
the CLI lacked prepare-final. `test_final_rejects_repeated_review_metadata_before_archiving`
failed for both FINAL and final-gap before the guard.

GREEN: `python3 -B -m unittest tests.test_lean_verification tests.test_workflow_run
tests.test_handoffs tests.test_build_state tests.test_sync_skill_resources` passed
136 tests. After simplification/restoration, the 14 lean/runtime tests passed again.
`npm test` passed 133 checks. Six targeted `python3 -B -m unittest <test>` sabotage
runs are recorded in the linked mutation JSON; each exited nonzero for its broken
behavior, and every mutation was restored. No full Python repository suite was
run. The native E2E supplies the successful packaged workflow and archive proof.


## Contract

Benchmark the existing quick lane against direct implementation; remove the
observed preflight failures; move repeated helper sequencing into code; preserve
isolated verification; and make supported budget enforcement durable and explicit.
Use generated output as the budget metric, including reasoning already counted by
the host. The owner supplied 4,000 per task and 30,000 per session for the evaluation;
the implementation supplies no default limits.

## Implemented

- Task briefs permit new owned directories and reject existing non-directory
  ancestors and Git metadata paths. Plan approval validates briefs before writing
  state or its checkpoint journal, including Git-backed deferred patch approval.
- The dependency is shipped with every approval helper and the project runtime.
- The workflow runner sequences plan gates and approval, returns exact helper
  receipts, and stops on failure. It wraps routing and landing evidence.
- Serial preparation creates the canonical verification sidecar at the clean base
  before the coder changes the primary. This resolves the ordering conflict seen
  in the quick benchmark while preserving the isolation helper's clean-base rule.
- The budget helper records host usage across resumptions, deduplicates observations,
  blocks observed exhaustion, and refuses to claim an unsupported hard cap.
  CLI event wrappers and single-invocation native child sessions are supported.
- Phase and dispatch contracts use the new entry points. Generated copies were
  refreshed from canonical sources without divergence warnings.

See [runtime usage and limitations](../../RUNTIME.md). The runner is a bounded
wrapper over existing helpers; phase judgment, native agent dispatch, archive,
integration, and recovery still follow the existing pipeline contracts.

## Verification

RED commands observed before the fixes:

- `python3 -B -m unittest tests.test_task_briefs.TaskBriefTests.test_declared_file_with_new_parent_directory_passes` — failed because a new parent directory was rejected.
- `python3 -B -m unittest tests.test_task_briefs.TaskBriefTests.test_new_path_rejects_non_directory_ancestors tests.test_pipeline_state.PipelineStateTests.test_plan_approval_rejects_invalid_brief_before_state_or_commit` — failed because unsafe ancestors passed and invalid plans were approved.
- `python3 -B -m unittest tests.test_workflow_run` — the unimplemented runner failed to stop a bad plan or create approval evidence.
- `python3 -B -m unittest tests.test_workflow_run.WorkflowRunTests.test_serial_prepare_creates_verification_before_product_changes` — failed because preparation was unsupported.
- `python3 -B -m unittest tests.test_token_budget` — the unimplemented admission gate allowed exhausted and unsupported hard-cap requests; persistence was absent.

GREEN after restoring all sabotage changes:

```text
python3 -B -m unittest tests.test_task_briefs tests.test_pipeline_state tests.test_workflow_run tests.test_token_budget tests.test_install.InstallerTests.test_packaged_approval_validates_new_paths tests.test_install.InstallerTests.test_update_keeps_project_contracts_and_refreshes_the_managed_runtime tests.test_sync_skill_resources
```

111 tests passed. `npm test` passed all 133 Node checks, including packed helpers,
manifest policy, and platform installation. `sync_skill_resources.py --check`
passed for 196 resources. `git diff --check` passed. The full Python repository
suite was not run; these checks cover changed runtime, checkpoint, installer, and
packaging behavior.

Sabotage: restoring the original brief validator, removing approval validation,
and omitting the packaged dependency each made its regression fail. Disabling
runner failure handling, serial sidecar creation, budget exhaustion, strict-cap
blocking, and child counter parsing each failed its corresponding test. The latter
commands and full results are retained in
[runtime-fixes-sabotage.json](evidence/releases/1.0.0/runtime-fixes-sabotage.json).
Every temporary mutation was restored. Simplifier review kept the existing
checkpoint, isolation, atomic-write, and file-lock helpers as the authorities.

## Limits

Codex CLI does not expose a hard generation cap in the checked interface. Observed
admission cannot prevent an in-flight overrun or prove unreported usage. A strict
request returns blocked. The new runner has executable regression and package
coverage; its end-to-end time and token savings have not been measured yet.

The [unchanged-candidate quick comparison](evidence/releases/1.0.0/notes/codex-quick-run.md)
ended build/blocked after passing product checks and an uncollected passing wave
review. Its recovery failures are benchmark evidence, not successful behavior of
the updated runner. Build instructions also clarify that wave collection uses a
fresh sidecar at current primary HEAD, separate from the earlier serial Task
Verify sidecar. This clarification was synchronized; the recovery fuse precluded
another native run. The budget helper independently read that run's completed
host events, totaled 33,998 output tokens, and blocked further admission.
