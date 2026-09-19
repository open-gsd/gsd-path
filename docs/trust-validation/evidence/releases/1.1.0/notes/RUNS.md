# 1.1.0 validation run notes

Frozen candidate: `af0b082964510c471798826d7e2e05617d8d6dc3`.
Harness root: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082`.

## Passing observations

Validated receipts and external counter oracle pass: Claude, Codex, Copilot,
Cursor, OpenCode, Kimi, Zed, Antigravity, Grok, and Kiro. Each receipt binds the native
host run, task landing, committed archive, integration, and guard evidence.

Antigravity completed a native independent final review. Its attempted wave
review reuse was rejected because its approved INTENT Lane value contains an
inline hash comment. The runtime did not accept that value as `quick`.
The negative reuse result remains in `antigravity-rerun/quick/` raw transcripts;
the independent final review passed. This is not a passing reuse observation.

Claude and Cursor guards rejected post-shipment activity wrappers and output
redirection. The direct canonical validation/integration helpers succeeded.
Their receipt assembly uses the exact successful JSON outputs extracted from
native transcripts, without repeating validation or editing committed archives.

## Retained failed attempts

- `opencode/`: manifest assembly named the bound milestone branch instead of
  the retired task Verify branch. Its invalid assembled receipt is retained
  under `opencode-receipt-assembly-error/`. A fresh `opencode-rerun/` passed.
- Earlier Codex and Cursor attempts remain in their harness directories.
  Their proof was not reused by the passing fresh fixtures.
- `kiro-rerun/`: inspection wrapper failed after already collected/retired
  native inspection sidecars. Later, a malformed SC6 heading in cycle 1 was
  corrected by a native cycle 2, but completion rejected the historical
  malformed cycle. This attempt is blocked and supplies no passing receipt.
- Qwen's three attempts supply no passing receipt. The latest
  `qwen-rerun-2/quick/run-20260919T020511939359Z/events.jsonl` records parent-
  authored inspection output copied into sidecars without native child calls.
  The owner authorized one fresh Qwen CLI run using the existing OpenRouter
  Claude Sonnet backend; `qwen-sonnet/` holds this new attempt.

## Open work

Ten host receipts and external counter checks pass. Qwen remains incomplete:
the authorized backend retry reached a native inspector call but returned
OpenRouter HTTP 402 twice. It is paused pending available credits or released
credit reservations. See [QWEN-BLOCK.md](QWEN-BLOCK.md).

Publication remains blocked until Qwen has a valid current-candidate receipt
and the complete strict release gate passes. Version 1.1.0 is not published.
