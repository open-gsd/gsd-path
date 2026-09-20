# Grok evidence limits and provenance

The native workflow completed and receipt validation passed. The original parent session exceeded the user 30,000-output-token ceiling; the first turn alone reported 39,893. Historical overrun is preserved. A fresh parent session performed shipment after the prepared-archive checkpoint.

The existing Grok receipt binder uses the last session ID from all supplied runs when binding an earlier child. Passing the whole multi-session host root incorrectly assigned the later ship session to the coder. Receipt input is now a scoped view linking the unedited native coder run `quick/run-20260920T144844178579Z`; full history remains in the host root. Correct coder parent: `01a0bf38-faf0-7030-a25f-0b1bc56f5f28`; later ship parent: `01a0bf5e-0116-7a92-869d-5201d0b4b2b3`. No raw event, archived manifest, or candidate code was changed. The receipt was regenerated and validated with the corrected input scope.

The review tool label was corrected from a descriptive name to the observed native `spawn_subagent` API. Exact native landing and successful archive/integration stdout remain in the receipt.
