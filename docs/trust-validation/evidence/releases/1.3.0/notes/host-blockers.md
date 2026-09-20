# Incomplete native host runs

Candidate: `45466c40e57c6cc0d7acd099e880d1644b33f5ee`. No passing receipts are supplied for these hosts.

## kiro

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/kiro/quick/run-20260920T144039301554Z`
  - Exit: `1`; session: `f1e916cc-d658-4213-acd2-0bf62e4a8861`.
  - Observed: Internal error

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/kiro/quick/run-20260920T144528811852Z`
  - Exit: `1`; session: `f1e916cc-d658-4213-acd2-0bf62e4a8861`.
  - Observed: Internal error

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/kiro/quick/run-20260920T144645825704Z`
  - Exit: `1`; session: `6c370c10-1335-4099-80a2-e77813aca269`.
  - Observed: Internal error

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/kiro/quick/run-20260920T145309185426Z`
  - Exit: `1`; session: `12c9cbb7-6681-46c8-8df8-2d846565fce4`.
  - Observed: Internal error

## qwen-sonnet

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/qwen-sonnet/quick/run-20260920T144528797383Z`
  - Exit: `0`; session: `1009b0e2-0520-460f-aa3f-988ee5355bae`.
  - Observed: [API Error: 402 This request would exceed your available credits given your current in-flight requests. Retry after in-flight requests settle, or add credits.]

## zed

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/zed/quick/run-20260920T142936491038Z`
  - Exit: `1`; session: `None`.
  - Observed: Provider anthropic is not authenticated

- Native run: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/zed/quick/run-20260920T145239308958Z`
  - Exit: `1`; session: `None`.
  - Observed: agent run failed: This request would exceed your available credits given your current in-flight requests. Retry after in-flight requests settle, or add credits.

User authorized one more Kiro retry after possible credit restoration. It failed with the same Internal error. Qwen and Zed later returned explicit provider credit errors; no replenishment confirmation was received. Their state and native logs remain intact.

Qwen wrapper exit 0 is not a workflow pass: the final native message is the credit error. Zed reports 39,264 output tokens for the failed planning turn, exceeding the 30,000 session ceiling.
