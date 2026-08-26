# Host trust matrix

`supported` means the installer and static dispatch contract exist. A release
is end-to-end trusted only when `npm run verify:release` finds a current passing
full-milestone receipt for every host below.

| Host | Install | Native guard installed | Full live milestone | Current posture |
|---|---|---|---|---|
| Codex | automated | project hook requires `/hooks` trust; Git hooks guaranteed | missing | release blocked |
| Claude Code | automated | fail-closed project hook + Git hooks | missing | release blocked |
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
