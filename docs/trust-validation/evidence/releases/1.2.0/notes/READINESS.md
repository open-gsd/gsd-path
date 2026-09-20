# 1.2.0 release-readiness audit

Status: **NOT READY — continued evaluation active**. Release target remains **1.2.0**. No external release, tag, push, or npm publication was performed.

Candidate: `f36f24aed82ac0019d082c7e31b8a4342d8e03f1`. This is the local release-cycle correction over main `45466c40e57c6cc0d7acd099e880d1644b33f5ee`. Remote main was rechecked with `git ls-remote origin refs/heads/main` at audit closeout and still matches that SHA. These receipts do not claim that unchanged remote main is ready.

## Required live hosts

Qwen, Kiro, and Zed are excluded from required evaluations by the owner. Their installer support remains. The required set is eight hosts.

| Host | Current evidence | Remaining work |
|---|---|---|
| Codex | Receipt, oracle6/6, both reuse checks pass | None |
| Cursor | Receipt, oracle6/6, both reuse checks pass | None; guard-command recovery preserved |
| Antigravity | Fresh retry4 receipt, oracle6/6, both reuse checks pass; maximum native session16,553 output tokens | None; inspection resumes and invocation errors preserved |
| Kimi | Fresh retry2 receipt, oracle6/6, both reuse checks pass; maximum native session17,497 output tokens | None; previous overrun retained in history |
| Grok | Fresh retry3 receipt, oracle6/6, both reuse checks pass; maximum native session14,229 output tokens | None; recovered invocation errors preserved |
| Claude | Previous structural receipt valid, full-wave reuse failed | Fresh retry2 active |
| Copilot | Fresh retry4 receipt, oracle6/6, both reuse checks pass; maximum native session21,937 output tokens | None; recovered path error and diagnosis-order deviation disclosed |
| OpenCode | Retry3 coder/review/oracle/reuse passed; receipt binding failed | Task agent build_T001 differs from native child build_t001; stopped before shipment |

Six of eight hosts now prove all requested scenario claims. A structural receipt alone does not prove a failed reuse, budget, or candidate-provenance claim. The aggregate gate will run after the remaining current receipts are complete and checkpointed. Recovered nonmutating invocation errors remain disclosed; they are not erased or described as flawless execution. See [Antigravity proof](antigravity-passed/scenario-proof.json), [Kimi observations](../kimi/observations.md), [Grok run notes](../grok/run-notes.md), and [OpenCode provenance failure](opencode-history/retry2/BLOCKER.md).

## Release-cycle repair

The workflow consumes the prepared version and verifies before tagging or publishing. It no longer pushes a version bump before gates. A retry retains the pending 1.2.0 version. See [release-cycle correction and regression evidence](RELEASE-CYCLE.md).

## Offline verification

- Node suite: 91 tests passed.
- Focused receipt suite: 47 tests passed.
- Release regression checks: 20 passed, with RED/GREEN and restored-original failure evidence.
- Initial `npm run verify`: failed after 1,747 Python tests with one failure and ten skips. `DispatchDriverTests.test_fix_tasks_resumes_after_only_first_batch_was_written` returned blocked instead of done.
- That test passed on isolated recheck (19.238 seconds). The complete Python recheck completed 1,747 tests successfully (ten skipped), including that test, with process exit 0. The diagnostic wrapper only captured the actual result after the tested call returned; its source is preserved under offline-checks. The initial failure did not reproduce; its cause remains unresolved. No speculative product fix was made.

The initial failure remains at `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-cycle-f36f24a/verify.log`; recheck output and captured actual dispatch result are in that same directory. No failed command is described as passing. The 459-resource synchronization check also passed. The strict receipt gate at checkpoint `a7cc490` failed on four missing hosts. After Kimi completed, the gate at clean checkpoint `2492d5a` exited 1 with `missing host evidence: grok, opencode, antigravity`. See [final gate output](offline-checks/receipt-gate-closeout.log).

## Preserved attempts

Original 1.3.0 evidence was not relabeled. All failed 1.2.0 fixtures and native logs remain under `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/`. The Antigravity archived manifest remains unchanged; its capture error is attributed to the evaluator. No API-billed Qwen/Kiro/Zed evaluations were restarted.

## Continued evaluation

Owner ruling, verbatim: "run till all pass". The previous round stop is lifted; no new approval is needed for diagnosed native retries. See [active acceptance and attempt record](RUN-UNTIL-PASS.md). Codex, Cursor, Antigravity, Kimi, Grok, and Copilot now prove all requested scenario claims. Claude continues for its remaining claims. OpenCode is stopped at a documented identity-binding conflict; see [retry3 blocker](opencode-history/retry3/BLOCKED.md). Historical failures remain; a recovered gate rejection is not silently removed.

## Faster routine releases

Owner ruling, verbatim: "Yes — use affected checks (recommended)".
Routine releases reuse validated live receipts when that host's runtime and
integration inputs are unchanged. Original candidates and versions stay intact.
Only missing, invalid, or stale hosts need new runs. Shared runtime changes
invalidate every host they affect. Qwen/Kiro/Zed remain excluded. The full
matrix is manual. Current Claude/OpenCode attempts may finish; no new full
fixture retry is planned if they fail.

The release workflow now runs its explicit offline gate once and skips npm
lifecycle scripts in the subsequent publish step. Local npm publication keeps
its prepublishOnly gate. The real offline publish fixture detected two runs
before the fix and one after; restored-original sabotage reproduced the failure.
Affected-evidence validation passed: receipt suite53/53, restored focused checks8/8, release workflow checks18/18, and restored-original failures reproduced. See [verification and raw logs](affected-checks/VERIFICATION.md). This is not release approval.
