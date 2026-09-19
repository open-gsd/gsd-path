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
