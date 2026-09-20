# 1.2.0 release-readiness audit

Status: **BLOCKED**. Release target remains **1.2.0**. No external release, tag, push, or npm publication was performed.

Candidate: `f36f24aed82ac0019d082c7e31b8a4342d8e03f1`. This is the local release-cycle correction over main `45466c40e57c6cc0d7acd099e880d1644b33f5ee`. Remote main was rechecked with `git ls-remote origin refs/heads/main` at audit closeout and still matches that SHA. These receipts do not claim that unchanged remote main is ready.

## Required live hosts

Qwen, Kiro, and Zed are excluded from required evaluations by the owner. Their installer support remains. The required set is eight hosts.

| Host | Receipt | Other results / open item |
|---|---|---|
| Codex | Validated | Independent CLI oracle 6/6; full-wave final reuse passed |
| Claude | Validated | Oracle 6/6; quick-wave reuse failed Surface alignment; required final reviewer then passed; later same-HEAD reuse passed |
| Cursor | Validated | Oracle 6/6; separate shipment commands completed after guard denials |
| Copilot | Validated, qualified | Oracle 6/6; scenario failed: repeated project Verify, continued after helper failures, token-budget breach |
| Kimi | Validated, qualified | Oracle and both reuse checks passed; reviewer session totaled 32,951 output tokens including its child, above the 30,000 limit |
| Grok | Blocked | Native reviewer became unavailable; three recovery attempts exhausted; continuation ruling pending |
| OpenCode | Blocked | Native recovery changed closed review/runtime evidence during ship; fresh-fixture ruling pending |
| Antigravity | Blocked | Local integration and oracle 6/6 passed, but evaluator supplied wrong Verify branch in archived manifest; no passing receipt issued |

A valid structural receipt does not erase a protocol or budget failure. Five of eight required receipts validate structurally. Grok, OpenCode, and Antigravity are missing valid receipts. Copilot and Kimi budget/protocol findings also remain; this is not an all-pass release audit. See [receipt validation](receipt-validation.json), [branch/path provenance](task-sidecar-provenance.json), [Copilot failures](../copilot/SCENARIO-FAILURES.md), [Kimi budget/interruption evidence](../kimi/observations.md), [Grok blocker](grok-blocked/review-resume-blocker.json), [OpenCode blocker](opencode-blocked/BLOCKER.md), and [Antigravity blocker](antigravity-blocked/BLOCKER.md).

## Release-cycle repair

The workflow consumes the prepared version and verifies before tagging or publishing. It no longer pushes a version bump before gates. A retry retains the pending 1.2.0 version. See [release-cycle correction and regression evidence](RELEASE-CYCLE.md).

## Offline verification

- Node suite: 91 tests passed.
- Focused receipt suite: 47 tests passed.
- Release regression checks: 20 passed, with RED/GREEN and restored-original failure evidence.
- Initial `npm run verify`: failed after 1,747 Python tests with one failure and ten skips. `DispatchDriverTests.test_fix_tasks_resumes_after_only_first_batch_was_written` returned blocked instead of done.
- That test passed on isolated recheck (19.238 seconds). The complete Python recheck completed 1,747 tests successfully (ten skipped), including that test, with process exit 0. The diagnostic wrapper only captured the actual result after the tested call returned; its source is preserved under offline-checks. The initial failure did not reproduce; its cause remains unresolved. No speculative product fix was made.

The initial failure remains at `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-cycle-f36f24a/verify.log`; recheck output and captured actual dispatch result are in that same directory. No failed command is described as passing. The 459-resource synchronization check also passed. The strict receipt gate at evidence checkpoint `a7cc490` correctly failed on missing Grok, OpenCode, Antigravity, and Kimi evidence.

## Preserved attempts

Original 1.3.0 evidence was not relabeled. All failed 1.2.0 fixtures and native logs remain under `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/`. The Antigravity archived manifest remains unchanged; its capture error is attributed to the evaluator. No API-billed Qwen/Kiro/Zed evaluations were restarted.
