# Release 1.7.0 live evaluation notes

Frozen candidate: `e2dd08576d7486b302dc7a870a47aaa7f788089f`.
Source base: `73f258d8632fc2003e4aa7bd741bef8ef319c8d5`.
Runs began on 2026-10-30 UTC and continued on 2026-10-31 UTC.
Run root: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.7.0-e2dd0857`.

Status: all seven receipts validated; all 42 external acceptance checks passed.
The publication workflow release gate remains required.

Every completed host used the pinned local installation in a fresh fixture,
real native children, a serial task with isolated Verify, full-wave final
review, runtime-owned project Verify, archive validation, and integration to
its own local bare origin. Repeating prepare-final at unchanged HEAD reused
both final review and verification without another ledger entry. Independent
widget acceptance ran on fresh clones of integrated origin/main; outputs are
in the `*-oracle.json` files beside this note.

## Completed runs

| Host | CLI version | Receipt | External checks |
| --- | --- | --- | --- |
| Codex | 0.157.1 | [pass](../codex.md) | [6 passed](codex-oracle.json) |
| Claude Code | 2.1.302 | [pass](../claude.md) | [6 passed](claude-oracle.json) |
| Grok | 1.0.70 | [pass](../grok.md) | [6 passed](grok-oracle.json) |
| OpenCode | 1.18.25 | [pass](../opencode.md) | [6 passed](opencode-oracle.json) |
| Antigravity | 1.4.8 | [pass](../antigravity.md) | [6 passed](antigravity-oracle.json) |
| Cursor | 2026.10.16-e3cb207 | [pass](../cursor.md) | [6 passed](cursor-oracle.json) |
| Kimi Code | 0.43.0 | [pass](../kimi.md) | [6 passed](kimi-oracle.json) |

Claude and Cursor supplied actual native-hook denial, successful read and
ordinary command, and unchanged protected-file hashes. Other evaluated hosts
use the declared git-only tier; native protection is not claimed. Every
receipt includes a real Git-hook archive refusal and an allowed ordinary
commit from an evaluator-owned disposable guard clone.

## Retained unsuccessful attempts and corrections

- Cursor attempt 1 invented an accept-drift owner ruling. It is invalid and
  supplies no passing evidence. The fresh attempt waited for real evaluator
  rulings. The old run remains in `cursor.invalid-invented-owner-ruling-1`.
- Codex attempt 1 received the evaluator's invalid uppercase child identifier
  `build_T001`. Native dispatch rejected it after activation. No manual
  pipeline repair was allowed. The run remains in
  `codex.invalid-evaluator-identifier-1`; a fresh run used `build_t001`.
- Restarting Codex initially left the invalid attempt's external Verify
  directory at a reused path. Ownership was proved from the old repository's
  worktree registration and base commit. The directory was preserved under
  the invalid run and only that old registration was repaired. The current
  fixture's pipeline state was not edited. See the local
  `codex/evaluator-sidecar-resolution.json` record.
- Kimi's intent-correction and archive-prepare requests encountered repeated
  API timeouts. Its native client recovered; timeout attempts do not establish
  a pass. The final archive and integration validators passed.
- Intent gates clarified Python int() token compatibility, exact text/JSON
  output, and rejection of repeated flags before approving plans. These were
  evaluator decisions, not hand edits of approved contracts.
- Some hosts attempted compound shell commands that the guard refused. They
  retried plain commands; refusals remain in native transcripts.
- The generic integration-resume prompt initially called guard evidence
  "native" for git-only hosts. The archived manifests and receipts correctly
  record native enforcement as not applicable; they are the authority.

## Release date ruling

Owner decision: "Match the changelog date to the release tag date before
publication (recommended; keeps the link valid)." The final release step must
check the actual tag commit date and the generated README changelog anchor.
No release-docs generator behavior was changed for this release.

## Reported usage

[Raw host counters](host-usage.json) retain each completed harness call.
Some counters exceed 30,000 output tokens; others are unavailable. Host
counter scopes differ, and resumed runs may report cumulative values, so
these values are not summed into a comparable session total. They are
observations, not invented release thresholds.
