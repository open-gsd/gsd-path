# Live release evidence — 1.3.0

Candidate: `45466c40e57c6cc0d7acd099e880d1644b33f5ee`.

Raw native runs: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4`.

This evaluation completed seven host receipts; four hosts remain blocked. A validated host receipt does not erase failed attempts or prove every optional scenario checkpoint. No release-ready claim is made while required hosts are missing.

## Preserved negatives

- Kiro: three build attempts returned `Internal error`. User authorized retry after possible credit restoration; fourth attempt also returned `Internal error`. No coder run or receipt.
- Qwen first fixture: native parent wrote phase artifacts and advanced without required child evidence/approvals. Invalid run retained. Fresh Qwen host with Sonnet model later stopped on provider HTTP402.
- Zed: planning stopped on provider credit error. Native result reports 39,264 output tokens, exceeding the user session limit of 30,000. This remains a failed budget check.
- Codex first fixture: evaluator supplied uppercase `build_T001`, incompatible with native lowercase task-name requirement. No coder ran. Fresh fixture uses canonical `build_t001` activation.
- Cursor first fixture: parent edited accepted review headings. Invalid. Second fixture: unsupported sidecar recovery and unsupplied owner rulings. Invalid. Final third fixture is evaluated separately.
- Copilot: full-wave reuse rejected missing required walkthrough format; a real native final reviewer passed instead. Same-HEAD repeat reused that existing final review and project Verify. After successful integration, host unnecessarily attempted `render-manifest`; helper refused with `current archive is already committed; run validate instead`. Preserved native output and late read-only diagnosis. No archive edits resulted.
- Claude: helper invocation/sidecar retirement failures and late passing diagnosis preserved. Host advanced to archive preparation without the requested same-HEAD `prepare-final` repeat; that checkpoint remains unproven. No archive rollback or fabricated repeat evidence.
- Antigravity: child was interrupted across CLI server restart, then same native child resumed. Host advanced through requested final-ready pause but stopped at required pre-manifest archive checkpoint. Evaluator reviewed final artifacts before approving ship.

## Receipt validation

- OpenCode: assembler validated all 10 steps; independent six-case CLI acceptance passed.
- Copilot: assembler validated all 10 steps; independent six-case CLI acceptance passed.

- Antigravity: assembler validated all 10 steps; independent six-case CLI acceptance passed.
- Claude: assembler validated all 10 steps; independent six-case CLI acceptance passed; same-HEAD repeat gap remains.
- Grok: assembler validated all 10 steps; independent six-case CLI acceptance passed.

- Cursor: assembler validated all 10 steps; independent six-case CLI acceptance passed.
- Kimi: assembler validated all 10 steps; independent six-case CLI acceptance passed; same-HEAD repeat proved unchanged two-entry ledger.

Remaining host status is in the raw run root `LIVE-RESULTS.md`. Codex recovery is blocked as detailed in codex-blocker.md.

## Native budget observations

Native fields are retained in raw run.json/result.json. Per-turn and cumulative fields differ between hosts; they must not be blindly summed. Observed historical session breaches include Grok (first turn alone 39,893 output), Antigravity (reported cumulative 97,813 before ship), Qwen second fixture (83,976), Cursor final fixture (31,057), and Zed planning turn (39,264). Fresh contexts do not erase these failures. Grok was interrupted at a prepared archive checkpoint once the overrun was found and resumed shipping in a fresh native context. Other hosts with absent or ambiguous usage do not receive an inferred budget pass. OpenCode parent step-finish output totals 25710 across captured unique steps; child totals are separate.
