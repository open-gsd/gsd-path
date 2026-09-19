# Model-selection verification

Status: implementation verified; independent Claude Fable review completed and reproduced findings addressed.

## Changed behavior and proof

| Canonical change | Executable proof |
|---|---|
| `scripts/model_policy.py` | `tests/test_model_policy.py`: field precedence, host settings, explicit inheritance, advertised capability rejection, argument delivery, native record scope, pinning, reassignment, and panel family validation |
| `scripts/dispatch_driver.py` | Same tests: real child arguments, saved selection on new attempts, fixed-argument conflicts, immutable earlier attempt evidence, full fixture wave and task landing, preflight before task isolation |
| `scripts/check_handoffs.py` | Same tests reject non-scalar task overrides; existing handoff and dispatch tests retain task-contract and landing behavior |
| `scripts/skill-resources.json`, `package.json`, generated skill resources | Every bundled model helper executes outside the source checkout; Node installer/package smoke tests; resource synchronization check |
| Dispatch instructions, task template, glossary and design notes | Source review; helper behavior tested as above. No claim of live execution on every host |

## RED

Before dispatch integration, these tests in `tests/test_model_policy.py`
failed with incorrect child arguments or an expected rejection not occurring:

```text
python3 -B -m unittest tests.test_model_policy.DispatchPolicyTests.test_project_choice_reaches_child tests.test_model_policy.DispatchPolicyTests.test_unsupported_explicit_choice_stops_before_attempt tests.test_model_policy.DispatchPolicyTests.test_retry_keeps_choice_after_policy_edit tests.test_model_policy.DispatchPolicyTests.test_task_partial_override_preserves_role_effort tests.test_model_policy.DispatchPolicyTests.test_opaque_command_cannot_ignore_explicit_choice
```

Result: five intended assertion failures. The native argument test also failed
against an inheritance-only resolver for every host in the installation manifest.
Later focused RED runs exposed fixed-argument conflicts, untyped malformed JSON,
missing reassignment, dropped effort on reassignment, invalid task scalars,
changed known inherited identity, and lost pinning on a newly built attempt.

## GREEN

- `python3 -B -m unittest tests.test_dispatch_driver tests.test_dispatch_contract tests.test_review_panel tests.test_handoffs`
  — 195 tests passed, 441.048 seconds.
- `npm test` — 152 tests passed; raw output:
  `/tmp/gsd-model-selection-node-tests.log`.
- `python3 -B -m unittest tests.test_model_policy tests.test_dispatch_driver.DispatchDriverTests.test_question_blocks_until_answered_then_redispatches_the_same_isolate tests.test_dispatch_driver.DispatchDriverTests.test_panel_named_family_runs_merges_and_checkpoints_with_the_review tests.test_dispatch_driver.DispatchDriverTests.test_panel_resumes_missing_family_and_pending_cleanup`
  — 23 tests passed after source restoration and final integration changes,
  37.491 seconds. Raw output: `/tmp/gsd-model-selection-final-tests.log`.
- `python3 -B scripts/sync_skill_resources.py --check` — 401 resources matched.
- `git diff --check` — passed.

The existing dispatch tests emitted subprocess ResourceWarnings. Their test
results passed; warnings are retained in the raw output rather than suppressed.

## Sabotage and restoration

Each mutation below caused an assertion failure in its focused command.
Original source bytes were restored in `finally` before the GREEN rerun.
Exact commands, exit codes, and failure output are recorded in
`/tmp/gsd-model-selection-sabotage.json`.

- Disable role selection: child delivery, native controls, and field-precedence checks fail.
- Disable capability validation: unsupported choices reach dispatch.
- Ignore saved selection: retry and native resume checks fail.
- Disable fixed-control conflict detection: a conflicting command is accepted.
- Ignore assignment scope: an old record is accepted for a new milestone.
- Disable panel independence: a forbidden family is accepted.
- Disable scalar validation: a list is accepted as a task model override.
- Remove preflight: a rejected choice creates an unwanted task-isolation branch.
- Drop unchanged fields during reassignment: the prior effort choice is lost.

The initial preflight sabotage survived a primary-file-only assertion. The
test was strengthened to inspect Git branches; it then detected the unwanted
task-isolation branch. This test repair is included in the passing final run.

## Post-review verification

`python3 -B -m unittest tests.test_model_policy` passed all 24 tests in 7.331
seconds after the review fixes and their sabotage checks were restored. Raw
output: `/tmp/gsd-model-selection-review/restored-green.log`. Resource sync
(401 resources) and whitespace checks passed again.

See [review and dispositions](model-selection-review.md) for each reproduced
finding, its correction, and the reviewer token-budget overrun.

## Limits

These results prove policy controls and regression behavior. They do not prove
cost savings, model quality rankings, current pricing, or live control on every
host. Host capability and argument fixtures are explicit inputs. An inherited
model identity hidden by a host remains unproven across fresh child sessions.

## Independent review

Requested model: Claude Fable. The reviewer runs read-only with Read, Grep,
and Glob; it cannot edit files or run tests. The [review and dispositions](model-selection-review.md) record its findings,
reproductions, corrections, and verification limits.

## Gate review verification

Scope: R1–R3 only, starting at `06b99697278ca75c75a3d96e216d221fc943902a`.
Canonical runtime changes are `scripts/dispatch_driver.py` and
`scripts/review_panel.py`; their generated copies were synced. Regression tests
are in `tests/test_model_policy.py`.

### RED and removal sensitivity

The original versions of both canonical scripts were restored after drafting
corrections, and the following command produced four intended failures:

```sh
python3 -B -m unittest \
  tests.test_model_policy.DispatchPolicyTests.test_rejected_task_does_not_stop_independent_sibling \
  tests.test_model_policy.DispatchPolicyTests.test_legacy_retry_does_not_adopt_new_policy \
  tests.test_model_policy.DispatchPolicyTests.test_legacy_retry_rejects_explicit_selection_without_migration \
  tests.test_model_policy.DispatchPolicyTests.test_detected_panel_excludes_canonical_family_before_persisting
```

- R1: T002 did not land when T001 requested an unavailable model, even though
  they were independent. The corrected fixture uses supported task frontmatter;
  an earlier unsupported CLI-flag failure was discarded as invalid evidence.
- R2: a legacy retry delivered `--model large` instead of its saved owner
  argument, and an explicit model override was accepted without migration.
- R3: the panel blocked on Claude instead of running the independent Grok child.

This original-code restoration also tests sensitivity to removing the fixes.
All four assertions failed, then the corrected sources were restored before
GREEN. Raw output: `.scratch/model-selection-review/red.log` in this worktree.

### GREEN

One focused verification command after restoring all fixes:

```sh
python3 -B -m unittest \
  tests.test_model_policy tests.test_review_panel \
  tests.test_dispatch_driver.DispatchDriverTests.test_parallel_round_lands_both_tasks_and_retires_isolates \
  tests.test_dispatch_driver.DispatchDriverTests.test_serial_rounds_reproduce_in_the_sidecar_and_unlock_dependents \
  tests.test_dispatch_driver.DispatchDriverTests.test_question_blocks_until_answered_then_redispatches_the_same_isolate \
  tests.test_dispatch_driver.DispatchDriverTests.test_round_stops_at_the_wave_boundary \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_refuses_verify_only_and_unlanded_waves \
  tests.test_dispatch_driver.DispatchDriverTests.test_panel_named_family_runs_merges_and_checkpoints_with_the_review \
  tests.test_dispatch_driver.DispatchDriverTests.test_panel_resumes_missing_family_and_pending_cleanup
```

Result: **60 tests passed in 71.198 seconds**. The new tests prove real sibling
landing, a named blocked receipt, no rejected-task isolate, retained legacy
child arguments, explicit-override rejection, and a persisted Grok-only panel
roster with a GPT parent and Claude canonical reviewer. Existing focused tests
cover dependency and wave gates, question resumes, explicit family validation,
and panel recovery. Raw output: `.scratch/model-selection-review/green.log`.
The existing subprocess ResourceWarnings remain visible in that log.

`python3 -B scripts/sync_skill_resources.py` completed with 401 resources and
zero warnings; `--check` confirmed all 401 resources. `git diff --check` passed.
No full repository test/lint suite, publication, or other gate phase ran.

## Final scoped verification

Starting HEAD: `9b8634584c55a3f6bda11786f9d1bc79c644adcf`. Scope: R4/R5,
completing the already accepted R1/R3 claims. Product changes are limited to
`scripts/dispatch_driver.py`; native contract changes are the canonical
`build-native.md` and `model-policy.md` references. Generated resources were synced.

RED command (two intended failures):

```sh
python3 -B -m unittest \
  tests.test_model_policy.DispatchPolicyTests.test_rejected_review_lens_does_not_stop_independent_lens \
  tests.test_model_policy.DispatchPolicyTests.test_rejected_answered_task_does_not_stop_answered_sibling
```

Both failed before correction: no adversarial lens was collected, and T002 did
not land. Temporarily restoring the starting dispatch script after correction
produced the same two assertion failures; fixed bytes were restored in `finally`.
Logs: `.scratch/model-selection-review-round3/red.log` and `sabotage.log`.

The native roster regression executes the real helper with both the old and
corrected argument sets and checks the child independence validator. It uses
no source-text assertions. No helper implementation change was needed for R5.

Focused GREEN command after all fixes and resource sync:

```sh
python3 -B -m unittest \
  tests.test_model_policy \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_deep_runs_both_lenses \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_resumes_only_missing_deep_lens \
  tests.test_dispatch_driver.DispatchDriverTests.test_question_blocks_until_answered_then_redispatches_the_same_isolate \
  tests.test_dispatch_driver.DispatchDriverTests.test_interrupted_redispatch_preserves_the_answer_for_retry \
  tests.test_dispatch_driver.DispatchDriverTests.test_serial_rounds_reproduce_in_the_sidecar_and_unlock_dependents \
  tests.test_dispatch_driver.DispatchDriverTests.test_panel_resumes_missing_family_and_pending_cleanup \
  tests.test_dispatch_driver.DispatchDriverTests.test_skeptics_run_once_per_locator_and_fix_tasks_batches_what_stands
```

Result: **38 tests passed in 94.316 seconds**. Raw output is
`.scratch/model-selection-review-round3/green.log`; existing subprocess
ResourceWarnings are retained. The regressions prove collection of the valid
adversarial lens without a rejected-lens isolate or passing checkpoint, and
landing of the valid answered sibling while the rejected question keeps its
original attempt and answer. Existing recovery and dependency checks passed.

Resource sync reported zero warnings; `--check` confirmed 401 resources.
`git diff --check` passed. No full repository suite or other gate phase ran.
No accepted R4/R5 claim remains open. The owner review-round cap ends this
scoped correction; no additional review/fix loop was started.

## R6 recovery verification

Starting HEAD: `10d41e2b428efe7a5864d23dd1e6bcef75c51bf5`. The owner explicitly
authorized this additional cycle for R6 only. Canonical runtime change:
`scripts/dispatch_driver.py`, synchronized to its generated copies. The existing
regression in `tests/test_model_policy.py` now continues through model correction
and same-cycle recovery.

RED and removal-sabotage command:

```sh
python3 -B -m unittest tests.test_model_policy.DispatchPolicyTests.test_rejected_review_lens_does_not_stop_independent_lens
```

Before the fix, recovery returned `blocked` because the collected adversarial
artifact made the primary dirty. Temporarily restoring the starting dispatch
script reproduced that same assertion failure; fixed bytes were restored in
`finally`. Logs: `.scratch/model-selection-review-r6/red.log` and `sabotage.log`.

Focused GREEN command after all changes and resource sync:

```sh
python3 -B -m unittest \
  tests.test_model_policy.DispatchPolicyTests.test_rejected_review_lens_does_not_stop_independent_lens \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_resumes_only_missing_deep_lens \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_recovers_validated_collection_after_interruption \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_rejects_changed_inputs_after_pass \
  tests.test_dispatch_driver.DispatchDriverTests.test_review_rejects_changed_or_missing_collected_artifact
```

The extended regression checks altered collected content, an unrelated file,
and an uncollected review file all block before the missing assignment gets a
record. After restoring valid inputs, both lenses pass at the original base,
the existing sibling's record and artifact bytes remain unchanged, each lens
has one attempt, and temporary isolation branches are retired.

Result: **5 tests passed in 43.044 seconds**. Raw output:
`.scratch/model-selection-review-r6/green.log`. Existing subprocess
ResourceWarnings remain in the log. Resource sync completed without warnings;
`--check` confirmed all 401 resources, and `git diff --check` passed. No full
repository suite or other gate phase ran. R6 is resolved within the authorized
additional cycle; PR delivery remains with the outer executor.
