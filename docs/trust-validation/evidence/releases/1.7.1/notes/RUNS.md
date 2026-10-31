# Release 1.7.1 live evaluation notes

Frozen candidate: `ab909c7ddd43a178305672e74f48a6d3d5624e62`.
Source base: `ac5ce7bed64c9c7fb5225f22ac60552674ecb7e0`.
Runs began on 2026-10-31 UTC.
Run root: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.7.1-ab909c7d`.

Status: all seven required receipts validated; 42 external checks passed.
Publication remains pending the evidence PR and release workflow.

Completed hosts used the pinned local installation in a fresh fixture,
real native children, serial task execution with isolated Verify, full-wave
final review, runtime-owned project Verify, archive validation, and integration
to a local bare origin. Independent widget acceptance ran on fresh clones of
integrated origin/main. Repeated prepare-final reused existing results.

## Completed runs

| Host | CLI version | Receipt | External checks |
| --- | --- | --- | --- |
| Codex | 0.157.1 | [pass](../codex.md) | [6 passed](codex-oracle.json) |
| Claude Code | 2.1.302 | [pass](../claude.md) | [6 passed](claude-oracle.json) |
| Antigravity | 1.4.12 | [pass](../antigravity.md) | [6 passed](antigravity-oracle.json) |
| Kimi Code | 0.43.0 | [pass](../kimi.md) | [6 passed](kimi-oracle.json) |
| Grok | 1.0.70 | [pass](../grok.md) | [6 passed](grok-oracle.json) |
| Cursor | 2026.10.22-27dcf5f | [pass](../cursor.md) | [6 passed](cursor-oracle.json) |
| OpenCode | 1.18.25 | [pass](../opencode.md) | [6 passed](opencode-oracle.json) |

## Retained unsuccessful attempts and corrections

- Initial Codex attempt supplied an invalid branch-binding default and
  advanced state after the helper failed. Retained as invalid; the fresh
  `codex-retry-branch-binding` run supplies the passing receipt.
- Cursor attempt 1 invented an accept-drift ruling and substituted manual
  inspection after canonical preparation failed. Attempt 2 reran project
  Verify in wave review, so it cannot prove single execution at ship.
  Attempt 3 invented intent and plan approvals. All remain invalid.
- The owner authorized a further Cursor attempt with Opus 5.5. Cursor rejected
  that model before any work because it was not included in weekly usage.
  The owner then authorized Grok; the same untouched fixture resumed with
  request-scoped `--model grok-4.7-high`. No account settings changed.
- Intent rulings preserved Python int() token compatibility and clarified
  invalid-input handling before plan approval. Grok's plan walkthrough was
  corrected before approval to read recorded test evidence instead of
  rerunning the task test command.
- Antigravity first passed invalid render-manifest arguments; the helper
  refused them. It read the shipped command contract and retried successfully.
  Native command displays truncate long arguments, so exact receipt command
  strings come from the evaluator activity log, bound to the successful native
  tool results. No test was repeated to recapture command text.

- OpenCode GLM continuation stalled twice without events or fixture changes.
  The configured OpenCode Opus provider then rejected an expired key. The
  owner authorized continuation through the existing OpenAI connection.
  That OpenAI OAuth continuation failed with `Token refresh failed: 401`
  before any host tool ran. Same session and evidence are retained; no
  credentials were changed. The owner authorized other configured providers.
  OpenRouter Opus 5.5 and GPT-6.1 returned no events for 487 and 501 seconds.
  Both were stopped with FINAL, gap, and ledger unchanged. Google then
  rejected its key as reported leaked. No host tool ran in those attempts.
  The three-round fuse stopped further retries until the owner refreshed
  OpenAI OAuth. A fresh native connection probe returned OK. The original
  conversation remained silent after refresh and was stopped unchanged.
  OpenCode continued the same fixture from its canonical files in fresh
  native conversation `ses_e6d215f46ffeZLGCD6bMNYPgjT`, preserving original
  child evidence from `ses_e6dc70908ffe5URo2hXe6BquUf`. It proved cached
  reuse without another test or ledger entry, then completed canonical
  archive and integration. No pipeline state was hand-repaired.
- Cursor plan wording briefly confused the logical task name with an opaque
  native ID after an ambiguous evaluator prompt. It was corrected before
  plan approval and dispatch.
- Kimi reported the outer evaluator session ID once. The harness and archived
  manifest retain the correct native Kimi session; the host acknowledged the
  correction. An evaluator capture script assertion failed before a prompt
  was written; its empty harness setup was retained separately. No host or
  pipeline mutation occurred during that failed capture setup.

## Publication boundary

PR #536 merged the version and release notes after all 25 checks passed.
The evidence PR and publication workflow's full release gate remain required.
The changelog date must match the actual release tag date before publication.

## Reported usage

[Raw host counters](host-usage.json) retain completed harness calls. Counter
scopes differ and resumed calls can report cumulative values. They are not
summed into a comparable session total. Missing counters remain null.
