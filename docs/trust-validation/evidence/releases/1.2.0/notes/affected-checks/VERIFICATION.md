# Affected release checks

Owner decision: "Yes — use affected checks (recommended)".

Implemented: validate each host receipt against its original candidate and current
host contract; reuse it only while relevant inputs remain unchanged. Keep original
version, candidate, native run, task, archive, and integration evidence. Current
receipts take precedence over historical passes. Missing evidence never becomes
an implicit pass through a release tag. Preparation selects only required runs;
--full prepares the manual matrix. Qwen/Kiro/Zed remain excluded.

The release workflow verifies once, then publishes with --ignore-scripts. Local
prepublishOnly remains. Package version is still1.2.0; no publication occurred.

## Executed proof

- RED: original validator failed4 new behavior checks; original preparation failed2.
- GREEN: receipt-validation suite53/53 passed (437.498s). One additional no-run
  preparation test and expanded existing checks were then covered by focused runs.
- Additional focused checks3/3 passed (35.760s).
- Restored-original sabotage: original validator rejected unchanged historical
  evidence; original preparer selected alpha and beta when only alpha needed work.
  Both expected failures reproduced; process exit1.
- Restored implementation:8 focused checks passed (97.922s), including unchanged
  history, one-host invalidation, shared invalidation, corrupt history, failed
  current receipt precedence, manual full matrix, zero preparation when unchanged,
  and independent host candidates.
- Release workflow tests18/18 passed. Actual offline npm lifecycle counted one
  explicit gate, preserved local prepublishOnly, and stopped publication on failure.
  Removing --ignore-scripts reproduced duplicate verification in worker sabotage.
- Resource synchronization:459resources checked. Shell syntax and whitespace passed.
- Ponytail review reused the existing change classifier and strict receipt/bundle
  checks. No model calls, new dependency, or runtime abstraction was introduced.

No full-repository test rerun was needed for these release-policy-only changes.
The prior full-suite failure and successful component rechecks remain documented
in ../READINESS.md; this report does not relabel the failed command as passing.

The OpenCode retry3 identity-binding blocker remains independent of this gate
optimization. The new gate does not waive it or create a passing receipt.

## Clean-checkout acceptance

At7b5ffe6, the actual --plan CLI exited0 in10.939seconds, validated six host
receipts, and selected exactlyClaude/OpenCode as required runs. The strict CLI
exited1 in10.954seconds for their explicit blocked results. Neither command
called a live host. Raw stdout/stderr and exact commands are in the adjacent
`affected-plan-result.json` and `affected-strict-result.json` files.

The feature is verified; release1.2.0 remains blocked. No additional live run,
version bump, push, tag, or publication followed this check.
