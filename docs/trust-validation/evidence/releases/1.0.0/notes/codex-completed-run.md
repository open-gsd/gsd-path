# Completed Codex delivery comparison

Tested candidate: `a84bb28c5c1e039a2d48110230d600d4364d51c5`.
Run date: 2026-09-04, America/Chicago.

## Outcome

Both arms delivered the requested widget-counter CLI and pass all six independent
acceptance checks. Path completed native coding, isolated task verification, one
full wave review, project verification, final review, archive, and direct integration
to its local remote. Both worktrees are clean. The installed candidate was unchanged.

| Observed measure | Direct | Path |
| --- | ---: | ---: |
| Agent execution time | 117.514 s | 1,976.461 s |
| Delivery time, including resumptions | 117.514 s | 2,072.895 s |
| Output tokens, parent plus native children | 3,000 | 61,294 |
| Input tokens, including cached repetitions | 279,018 | 18,569,613 |
| Cached input tokens | 253,824 | 18,102,272 |
| Independent acceptance checks | 6 passed | 6 passed |
| Failed measured commands | 1 | 11 |

Path took 16.8 times the agent execution time and recorded 20.4 times the output
tokens for this fixture. This is a completed standard-lane comparison, not proof
of global optimality. Direct committed its product; Path also performed the
explicitly requested planning, review, archive, and integration workflow.

## Code versus workflow cost

| Path responsibility | Recorded output tokens |
| --- | ---: |
| Parent orchestration across four runs | 34,147 |
| Coder, including its own tests and sabotage checks | 3,222 |
| Code and documentation inspection | 8,805 |
| Research | 3,260 |
| Decisions | 2,044 |
| Planning | 3,080 |
| Wave and final review | 6,736 |

The coder's 3,222 output tokens were close to direct's complete 3,000-token run.
The other 58,072 Path tokens came from the recorded workflow roles. These role
totals do not isolate every verification action: the coder and parent also verify.
Do not label all non-coder work as verification or infer exclusive time percentages.

The user's task budget was 4,000 tokens; the documentation inspector recorded
5,088 output tokens alone. The user's session budget was 30,000; the same parent
thread recorded 34,147 output tokens across its resumptions. This run therefore
provides no budget-compliance result, even before considering input tokens.
The budgets were supplied in the prompts but did not prevent these overruns.

## Delivery proof

- Product baseline: `208d2c29a0b57bc20d24ec318b86173c754636df`.
- Installed Path baseline: `f1d2b5b4ecb8fd6d2047c9f53157d6494eaffda4`.
- Direct product commit: `dcf82dac4ee1625e0c3fbaa588e9cbf30ddb1d4a`.
- Native task landing: `d122d669aeba718e1eee4f275f66f22c311c93f6`.
- Ship commit: `ab349821e7df6ab859879084c5bc4a51a0c03a81`.
- Published integration: `3ad456b25a3fc8a36c4a17c09843a2bb951b2654`.
- Annotated tag: `milestone/001-widget-counter-cli`, targeting integration.

Recorded `validate-integrated` exited zero. Independent Git reads confirmed the
exact remote-tracking ref, the local bare remote's main ref, both merge parents,
and the tag target. The only remaining worktree is the primary bound worktree at
the ship commit. STATE records shipped/done. The Git bundle verifies and retains
the product, task log, ledger, reviews, archive, and merge history.

Task Verify ran successfully in its isolated sidecar; project Verify ran once
at ship in its own sidecar. The three test methods contain 20 process cases.
Independent evaluator checks then passed for each delivered product. Native
session metadata identifies the coder and the completed inspection, research,
decision, planning, wave-review, and final-review children.

## Failures and operator interventions

Failed attempts remain in the evidence, including intentional RED/sabotage tests,
incorrect transition events, research manifest formatting, an all-skipped research
manifest, the new test-directory preflight failure, and an absolute-path completion
argument rejected by a helper. Failed-command counts are not defect counts.

The evaluator reviewed and approved the intent and plan. Build preflight then
rejected `tests/test_count.py` because its parent did not exist at the task base.
After reading the proposed correction, the evaluator authorized root-level
`test_count.py` and matching Verify commands. The plan and brief were re-gated and
checkpointed before coding. These were explicit evaluator approvals, not newly
claimed human approvals. No installed plugin source or archived artifact was repaired.

## Measurement limits

Both arms used Codex CLI 0.153.4, gpt-6-astra, high reasoning, and effective
danger-full-access permissions. All five parent turn contexts confirm those
permissions. Exact prompts are retained. The local candidate was explicitly pinned.

Parent usage sums completed CLI run counters. Each native child's usage is its
last cumulative session counter. Input totals include repeated cached context;
they are not unique text size or dollar cost. Reasoning-token fields are retained
separately and are not added to output-token totals. Operator evaluation work is
outside the arm token counters. Measured shell categories are partial and may overlap.

The generic comparison command returns 3 and labels pipeline trust `unverifiable`
because no formal release-host receipt was supplied. That stricter receipt also
requires dedicated guard evidence and an integration-bound run manifest. The
observed milestone completion is established by the recorded canonical validations
and Git evidence above; this run does not qualify every supported release host.

## Inspectable evidence

- [Machine comparison](codex-completed-run/comparison.json)
- [Native sessions and usage](codex-completed-run/native-sessions.json)
- [Pipeline commands, outputs, and Git checks](codex-completed-run/pipeline-evidence.json)
- [Effective permissions](codex-completed-run/effective-permissions.json)
- [Reproducible Git bundle](codex-completed-run/fixture.bundle)
- [Bundle verification](codex-completed-run/bundle-verification.txt)
- [Raw run directory](/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-a84bb28)
