# Claude retry2 blocked by native output budget

Candidate: `f36f24aed82ac0019d082c7e31b8a4342d8e03f1`. Package: `1.2.0`. This attempt has no accepted release receipt.

Native review session `5bfb8f0f-a227-4dd7-8636-26c6a8c9d6f7` completed with **32,066 output tokens**: parent 6,231 plus reviewer child 25,835. This exceeds the owner's 30,000 aggregate session limit by 2,066. Child `a6ae87439f4052289` and parent both finished normally. Neither was interrupted. The first observed over-limit sample was 30,279; the final count was 32,066. The child had already returned and model policy was released when the overrun was detected.

Evidence:

- [Native budget counters and raw file hashes](claude-retry2-budget.json).
- [Unchanged native terminal result](claude-history/retry2/review-native-result.json).
- [Native review artifact](claude-history/retry2/wave-1.cycle1.md).
- Raw stream: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/claude-retry2/quick/run-20260920T185544703152Z/events.jsonl`; `run.json` is beside it.

Terminal `modelUsage` output matches deduplicated assistant output from the parent and subagent JSONL files. Top-level `usage.output_tokens` counts only the parent and cannot prove aggregate session compliance.

Installation, initialization, both native inspection children, collection, definition, plan approval, the native coder, isolated task verification (8 tests), and canonical task landing completed. Task base: `eb0cc8fc866e068b14721b288a2a6be263728c22`. Landing: `426bd9f0447406d0a96d97815908cb277c3fa194`. Primary HEAD: `52bca9fe60bbdb72023c752470bb2d5366ed2dbf`.

The reviewer passed SC1–SC6 and authored final scope with the exact surface `count.py command line`. The test-only SC6 used recorded verification. Its artifact remains uncollected in the original sidecar. No collection, review checkpoint, build completion, final preparation or reuse checks, archive, shipment, integration, external oracle, or receipt assembly followed the budget failure. STATE remains `build/active`.

The [fresh native archive guard probe](claude-history/retry2/native-guard-probe.json) passed: reading and the allowed shell probe succeeded; the actual PreToolUse hook refused Edit; the target hash stayed unchanged. That result does not waive the budget failure.

Other observations remain preserved. The docs parent incorrectly called 104,869 input-plus-output subagent tokens an overrun; its actual aggregate output was 13,799. Its original message remains in `run.json`; the budget record explains the correction. The intent draft invented a ban on reading pipeline instructions. The native definition owner corrected it before approval and recorded the evaluator ruling verbatim. No manual state repair or parent edit of a reviewer artifact occurred.

The root coordinator stopped further native phases and fixture retries in response to the owner's cost and time constraint. This was the coordinator's operational decision, not a verbatim user ban. This evaluator made no source product changes or external publication. Completed pipeline CLI results report **$18.686602** in list-price cost. Guard and evaluator orchestration costs are separate, so this is not a complete campaign bill.

The previous structurally valid Claude receipt failed the original full-wave reuse scenario. All its original bytes remain in `claude-history/qualified-first-receipt.md` and `claude-history/qualified-first-run/`. The current `claude.md` is explicitly blocked so historical passing evidence cannot be selected as current acceptance.
