# Runtime follow-up from the Codex comparison

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

The unchanged-candidate quick comparison is recorded separately. Its recovery
failures are benchmark evidence, not successful behavior of the updated runner.
