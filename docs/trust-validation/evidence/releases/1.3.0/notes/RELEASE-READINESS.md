# Release readiness — 1.3.0

**Verdict: BLOCKED.** Seven of eleven required host receipts validate. The live-host matrix is incomplete. No release was published.

Candidate: `45466c40e57c6cc0d7acd099e880d1644b33f5ee`, reconfirmed as latest `origin/main`. Product code is unchanged; this branch adds evidence only.

## Host results

| Host | Result |
| --- | --- |
| codex | blocked: review-cycle recovery gap |
| claude | receipt validated |
| grok | receipt validated |
| opencode | receipt validated |
| copilot | receipt validated |
| qwen | blocked: provider credits |
| antigravity | receipt validated |
| cursor | receipt validated |
| zed | blocked: provider credits |
| kiro | blocked: Internal error |
| kimi | receipt validated |

Each supplied receipt includes native child proof, isolated task verification, final review, guard checks, archive and local-origin integration proof, and a Git bundle. Each completed fixture also passed the independent six-case CLI acceptance script. Local-origin integration does not claim GitHub PR/publication coverage.

## Blocking evidence

- [Codex recovery conflict](codex-blocker.md): cycle 1 failed review-format validation; the required new cycle passed, but build completion demands contiguous cycles. The earlier rejected review cannot be collected at the advanced primary HEAD through the canonical helper.
- [Kiro, Qwen, and Zed host errors](host-blockers.md): Kiro still returned `Internal error` on the user-authorized credit retry. Qwen and Zed returned explicit provider credit errors.

## Verification and limits

`npm run verify` passed at the frozen candidate: 89 Node tests, 1,744 Python tests (10 skipped), and 459 synchronized resources. Exact log and exit status: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-gate-1.3.0-45466c4/verify.log` and `verify.exit`.

The final committed-evidence check is recorded in the raw run root `receipt-validation.json` and `release-gate.stderr`. The full release gate remains blocked until every required host receipt is present. The product suite was not repeated for evidence-only changes.

[Run limitations](RUNS.md) preserve invalid attempts, native errors, historical token-budget breaches, and Claude's missing same-HEAD reuse checkpoint. [Grok provenance note](grok-notes.md) records the corrected session binding input. Validated receipts do not imply budget compliance or erase these gaps.

Raw runs and live progress: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/`.

## Next action

Resolve the Codex recovery contract and restore the blocked host/provider services. A product fix changes the frozen candidate and requires recalculating release evidence scope. Once those dependencies are resolved, a retry heartbeat can run the missing hosts and stop when all eleven receipts and the committed release validator pass. No heartbeat has been scheduled.
