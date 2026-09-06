# Codex comparison — implementation evidence

Candidate: `c9e92cc5922555d52df0e35b3f66f825b46690b4`

This is an evaluation report, not a release-trust receipt.

## Implemented

- Exact-command, versioned verification reuse; legacy rows cannot authorize new passes.
- Versioned multiline attestations with historical legacy recovery preserved.
- Explicit historical task verification against recovery-proven landing commits.
- Semantic checking of the smoke fixture's unsupported JSON claim.
- Independent product checks, matched local fixtures, native Codex event capture,
  measured subprocess activities, setup evidence, and JSON/Markdown reports.

## Executable evidence

The full gate on the runtime checkpoint passed: `npm run verify` ran 133 Node
tests, 1,051 Python tests (two skipped), and the 181-resource sync check.
The later evaluator-only changes passed `python3 -B -m unittest
tests.test_evaluate_codex` (four tests). No runtime code changed after the full
gate began.

| Test | Failure evidence | Passing evidence |
|---|---|---|
| `tests.test_build_state.BuildStateTests.test_verify_ledger_preserves_shell_semantics_and_ignores_legacy` | Original quoted-space cache collision; normalization sabotage exited 1 | Targeted ledger suite |
| `tests.test_isolation.RecoverTests.test_attest_preserves_multiline_verify` | Original serialization rejected the exact command; normalization sabotage exited 1 | Targeted isolation suite |
| `tests.test_isolation.RecoverTests.test_attest_refuses_legacy_ledger_for_new_attestation` | Original code admitted a legacy pass; schema bypass sabotage exited 1 | Targeted isolation suite |
| `tests.test_isolation.RecoverTests.test_legacy_attestation_remains_recoverable` | Compatibility test reconstructs a committed legacy attestation | Targeted isolation suite |
| `tests.test_isolation.RecoverTests.test_historical_verify_recovers_landing_after_head_advances` | Original CLI rejected the required mode; mode removal sabotage exited 1 | Historical sidecar executes the product and retires without moving primary HEAD |
| `tests.test_dogfood.DogfoodContractTests.test_live_audit_requires_correct_fixture_classification` | Original smoke accepted the wrong verdict; forced-pass sabotage exited 1 | `python3 -B -m unittest tests.test_dogfood` |
| `tests.test_evaluate_codex.EvaluationTests.test_oracle_rejects_old_constant_and_wrong_json_outputs` | Original widget script failed independent JSON checks; forced-pass sabotage exited 1 | Oracle accepts the conforming fixture and rejects broken implementations |
| `tests.test_evaluate_codex.EvaluationTests.test_activity_records_real_exit_and_missing_data_stays_unavailable` | Report originally returned 0 for incomplete evidence; exit-code sabotage exited 1 | Actual subprocess exit, missing measurements, and report exit codes checked |
| `tests.test_evaluate_codex.EvaluationTests.test_prepare_isolates_arms_at_same_product_base_and_refuses_reuse` | Missing install receipt reproduced; receipt-loss sabotage exited 1 | Actual local clones and installer checked |
| `tests.test_evaluate_codex.EvaluationTests.test_runner_uses_and_pins_explicit_sandbox` | CLI rejected explicit sandbox selection; sandbox substitution sabotage exited 1 | A fixture host process receives the requested mode and prompt |

Each named unittest can be run with `python3 -B -m unittest TEST_NAME`.
Sabotage changes were temporary and restored before committing.

## Live setup evidence

An initial direct run at candidate `8ed6c74` produced correct product output
but could not commit: Codex CLI 0.153.4's `workspace-write` sandbox denied
`.git/index.lock`. Its 130.964 seconds are setup-failure evidence, not part of
the final matched comparison. The evaluator now requires an explicit sandbox
and refuses differing settings across arms.

Initial attempt:
`/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-8ed6c74/comparison.json`

The final comparison uses `gpt-6-astra`, high reasoning, and
`danger-full-access`, matching the approved parent environment. Both arms
receive the same explicit paths to the required test-writer and code-simplifier
skills. Activity labels are caller-declared; elapsed durations come from actual
subprocess execution. Unwrapped activity and unavailable usage remain unknown.

Final fixture:
`/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-c9e92cc`

## Live outcome

| Arm | Independent product checks | Agent elapsed | Delivery |
|---|---|---|---|
| Direct Codex | All six passed | 119.095 seconds | Clean commit `b8d024b905082fbe394b8bf09e7b74a98a0372d6` |
| GSD Path | Failed; product unchanged | 76.861 seconds | Blocked during initial branch binding |

These durations are not a speed comparison: Path stopped before implementation.
The direct run's successful outcome does not supply Path's missing milestone
proof. Model usage is retained verbatim in `codex-comparison.json`; no token
budget compliance or dollar-cost claim is made.

The live Path agent selected the globally installed skill bundle despite the
local candidate installation. Therefore the live Path run does not establish
candidate provenance. It also tried a state transition after a helper failure,
then reported that process error. No native inspection children started.

The operator reproduced the binding failure using the frozen candidate itself:

```bash
python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-astra-c9e92cc/plugin/scripts/pipeline_git.py bind-initial --repo /Users/jeremymcspadden/orca/evaluations/gsd-path-astra-c9e92cc/path/repo --branch gsd-path/M001 --remote-default origin/main --base 2caddecdee123a54a3df0aa2f7328067654ca649
```

Exit 1, stderr verbatim:

```text
error: primary worktree is not clean
```

The required follow-up diagnostic was run:

```bash
python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-astra-c9e92cc/plugin/scripts/pipeline_diagnose.py diagnose --repo /Users/jeremymcspadden/orca/evaluations/gsd-path-astra-c9e92cc/path/repo
```

It exited 0. It reports valid state, `dirty: [".project/STATE.md"]`, no recovery
journal, and `route.action: bind-initial`. Its diagnostic `status: ok` means
the probes completed; it does not mean the milestone can advance.

The canonical router initializes STATE.md before binding
(`skills/gsd-path/SKILL.md:111`), while the binding helper rejects every
uncommitted path (`scripts/pipeline_git.py:501`). Both behaviors are present in
the frozen candidate. This conflict blocks the planned live milestone.

## Open items

- Resolve initialization ownership: recommended ruling is to let initial
  binding admit only a validated helper-created STATE.md while rejecting all
  other dirt, retaining exact-base and branch-collision checks. An alternative
  is a single journaled initialization-and-binding transaction.
- Pin the next Path invocation explicitly to its local candidate skill and
  helper paths. Do not accept a global-bundle run as candidate proof.
- After that contract ruling and repair, rerun the complete live milestone and
  produce native child, landing, review, archive, and integration receipts.

The implementation loop has reached the owner's three-round fuse. No manual
state or Git repair was performed in the blocked fixture. Full-milestone trust
and an efficiency comparison remain unproven; the all-host release gate stays
unchanged.
