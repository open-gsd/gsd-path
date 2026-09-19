# 1.1.0 validation run notes

Frozen candidate: `af0b082964510c471798826d7e2e05617d8d6dc3`.
Harness root: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.1.0-af0b082`.

## Passing observations

Validated receipts and external counter oracle pass: Claude, Codex, Copilot,
Cursor, OpenCode, Kimi, Zed, Antigravity, Grok, Kiro, and Qwen. Each receipt binds the native
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
- Qwen's three earlier attempts supply no passing receipt. The latest
  `qwen-rerun-2/quick/run-20260919T020511939359Z/events.jsonl` records parent-
  authored inspection output copied into sidecars without native child calls.
  The owner authorized one fresh Qwen CLI run using the existing OpenRouter
  Claude Sonnet backend; `qwen-sonnet/` holds this new attempt.

## Qwen retry resolution

After the owner added credits, the same authorized `qwen-sonnet/` fixture
completed with Qwen CLI 0.23.0 and `anthropic/claude-sonnet-5`. Native coder
`build_T001` ran in session `a1597ea1-c79a-48a6-ad6f-1f8695747d51`; its task
landed at `7431cc40e5cc6d5ef158724328583bbeb3f797a8`. Native inspections and
wave review are recorded in the transcripts. Fresh parent contexts continued
from persisted state after credit errors; no additional fixture was started.

A docs inspection first targeted the primary root and was corrected by a native
inspector in the sidecar. `finish-inspect` later failed after individual
artifact validation, collection, and retirement had already succeeded. The
pinned inspect contract's canonical expected-state transition completed that
phase after diagnosis; the failed wrapper is not recorded as a pass.
Wave review used the pinned native path's permitted validate/copy/retire flow.
A dirty-sidecar retirement refusal and its cleanup remain in the transcript.

Final preparation passed the project Verify once, reused the approved full-wave
review, and reused the same-HEAD verification receipt on its second call without
adding a ledger entry. The archive and integration validators passed:
ship `8249744589f93bb7eda87f160473d01f714c3a40`,
integration `ce89d360ea2237704e5df403fe43483999149bf9`.
Qwen receipt validation and the independent external CLI oracle both exited 0.
See [QWEN-BLOCK.md](QWEN-BLOCK.md) for the retained blocker history.

## Release gate

All eleven current-candidate receipts and external CLI checks pass.
Publication still requires the complete strict release gate on the committed
evidence, followed by the release workflow. Host receipt success alone is not
publication proof.
