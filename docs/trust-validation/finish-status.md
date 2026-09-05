# Finish status — 2026-09-05

The owner requested “finish them” after the quick comparison stopped. The source
branch was clean and unmerged at d903128. No product or plugin source code changed
in this continuation.

## Completed recovery

The evaluator used the fixture's pinned canonical helpers. It transported the
existing passing native wave review unchanged through a fresh current-HEAD sidecar.
The collected bytes have SHA-256
`4c052dcf69e4de9e291a70a03e6e7eaa6c5da6a0ddfe7994e228f95a3d5599cf`.
This preserves the original task base, landing commit, reviewer evidence, and
failure history; it does not claim a new review.

The canonical wave gate and landing proof passed. Build completion was checkpointed
at `09d6e0b5398d967a70fa745c44f61222c6afab86`, and STATE routes to ship/active.
Project Verify ran once at this exact revision in its own canonical sidecar:

```text
python3 -B -m unittest discover -s . -p 'test_count.py' -v
```

Exit zero; all three test methods passed. The output was recorded in the Verify
ledger and collected as final-gap-1.md. Both recovery sidecars and the previous
review sidecar were retired. FINAL.md, shipping, archive, and integration remain.
These steps were evaluator-operated helper recovery, not additional native CLI
execution; the earlier benchmark's timing and token totals remain unchanged.

## Required input

The benchmark already used 33,998 generated output tokens against the owner's
30,000-token session budget. A revised total is required before another metered
model invocation. The owner was asked for that value. Do not reset the ledger or
silently start a replacement session to bypass it. Keep the 4,000 per-task policy
unless the owner changes it.

## Hard cap check

The installed CLI is still 0.153.4. Its generated experimental app-server schema
exposes thread goals with tokenBudget and budgetLimited state, but no hard
per-response output-token limit in TurnStartParams. The official
[app-server documentation](https://learn.chatgpt.com/docs/app-server) describes
persisted goal accounting; it does not establish a strict generation cap.

The [Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)
does provide max_output_tokens, including reasoning. That requires a different
API-backed execution path. No OPENAI_API_KEY is available in this environment.
No API request, credential migration, model substitution, or unsupported cap claim
was made. Existing strict admission still returns blocked on Codex CLI.

## Evidence

- [Canonical status](evidence/releases/1.0.0/codex-quick-finish/status.json)
- [Helper commands and exact results](evidence/releases/1.0.0/codex-quick-finish/commands.jsonl)
- [Collection proof](evidence/releases/1.0.0/codex-quick-finish/collection.json)
- [Project Verify](evidence/releases/1.0.0/codex-quick-finish/project-verify.json)
- [Collected gap artifact](evidence/releases/1.0.0/codex-quick-finish/final-gap-1.md)
- [Budget interface check](evidence/releases/1.0.0/codex-quick-finish/budget-interface-check.json)
