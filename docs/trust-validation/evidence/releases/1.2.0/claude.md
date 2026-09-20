---
schema: gsd-path/live-evidence/v1
host: claude
package: 1.2.0
pipeline: gsd-path/v2
candidate: f36f24aed82ac0019d082c7e31b8a4342d8e03f1
verdict: blocked
---

# Claude release evidence blocked

The fresh retry completed its native wave review but exceeded the 30,000-output-token session limit: **32,066 aggregate** (parent 6,231 + reviewer 25,835). No final reuse proof, shipment, integration, or accepted receipt followed.

[Blocker and partial state](notes/claude-retry2-blocked.md) · [Native budget evidence](notes/claude-retry2-budget.json).

The previous failed-scenario receipt and every artifact byte are preserved in [history](notes/claude-history/qualified-first-receipt.md), with an [exact byte check](notes/claude-history/retirement-byte-check.json). This blocked current result must prevent fallback to a historical passing receipt.
