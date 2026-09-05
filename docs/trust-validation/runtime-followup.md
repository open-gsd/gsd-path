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
Fresh native E2E is pending. Legacy receipts missing exact command output block
for reconciliation rather than silently rerunning verification.

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

The [unchanged-candidate quick comparison](evidence/releases/1.0.0/codex-quick-run.md)
ended build/blocked after passing product checks and an uncollected passing wave
review. Its recovery failures are benchmark evidence, not successful behavior of
the updated runner. Build instructions also clarify that wave collection uses a
fresh sidecar at current primary HEAD, separate from the earlier serial Task
Verify sidecar. This clarification was synchronized; the recovery fuse precluded
another native run. The budget helper independently read that run's completed
host events, totaled 33,998 output tokens, and blocked further admission.
