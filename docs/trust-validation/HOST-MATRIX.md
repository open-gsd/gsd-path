# Host trust matrix

`supported` means the installer and static dispatch contract exist. A release
is end-to-end trusted only when `npm run verify:release` finds a current passing
full-milestone receipt for every host below.

| Host | Install | Native guard installed | Full live milestone | Current posture |
|---|---|---|---|---|
| Codex | automated | project hook requires `/hooks` trust; Git hooks guaranteed | regenerating at candidate 3c32f3d: run paused at the ship step by the Codex usage limit (resumes after 21:27 CDT); the tracked codex.md is bound to the earlier candidate 1e3a552 | release blocked until the 3c32f3d receipt lands |
| Claude Code | automated | fail-closed project hook + Git hooks | present: [claude.md](evidence/releases/1.0.0/claude.md), candidate 3c32f3d, 2026-09-06; native guard probe passed against the fixed guard | receipt passes the validator; release still blocked by the other hosts |
| Grok | automated | not installed; Git hooks | missing | release blocked |
| OpenCode | automated | not installed; Git hooks | missing | release blocked |
| GitHub Copilot CLI | automated | not installed; Git hooks | missing | release blocked |
| Qwen Code | automated | not installed; Git hooks | missing | release blocked |
| Antigravity CLI | automated | not installed; Git hooks | missing | release blocked |
| Cursor | automated | fail-closed project hook + Git hooks | missing | release blocked |
| Zed | automated | no native hook API; Git hooks | missing | release blocked |
| Kiro | automated | not installed; Git hooks | missing | release blocked |
| Kimi Code | automated | not installed; Git hooks | missing | release blocked |

Historical smoke evidence remains under `evidence/`; release receipts belong
under `evidence/releases/<version>/` and are never inferred from smoke runs.

## Release procedure (from the 2026-09-06 Codex receipt run)

`npm run verify:release` accepts only host receipts as `.md` files at the root
of `evidence/releases/<version>/`; other notes live under `notes/`. Every
receipt must name one frozen candidate, and only evidence files plus this
matrix and TRUST-EVIDENCE.md may change after that candidate. So the order
is: merge every code and documentation change first, freeze the candidate,
run all eleven host receipts against it, then publish. The Codex receipt
above proves the protocol and the assembly tool
(`evidence/releases/1.0.0/codex/release_receipt.py`); it is bound to its own
candidate and must be regenerated for the final release candidate.
