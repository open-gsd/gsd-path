# Host trust matrix

`supported` means the installer and static dispatch contract exist. A release
is end-to-end trusted only when `npm run verify:release` finds a current passing
full-milestone receipt for every host below.

All eleven hosts hold a passing receipt on the frozen candidate
`091d27927a2c0c2ecc55ce386fb2232556da6336`, verified 2026-09-09.

| Host | Install | Native guard installed | Full live milestone | Current posture |
|---|---|---|---|---|
| Codex | automated | git-only tier: the `--ignore-user-config` harness run has no native hook, so Git hooks carry it | present: [codex.md](evidence/releases/1.0.0/codex.md) | receipt passes the validator |
| Claude Code | automated | fail-closed project hook + Git hooks | present: [claude.md](evidence/releases/1.0.0/claude.md); native guard probe passed | receipt passes the validator |
| Grok | automated | not installed; Git hooks | present: [grok.md](evidence/releases/1.0.0/grok.md) | receipt passes the validator |
| OpenCode | automated | not installed; Git hooks | present: [opencode.md](evidence/releases/1.0.0/opencode.md) | receipt passes the validator |
| GitHub Copilot CLI | automated | not installed; Git hooks | present: [copilot.md](evidence/releases/1.0.0/copilot.md) | receipt passes the validator; needed the hard-stop prompt addendum to honor owner gates |
| Qwen Code | automated | not installed; Git hooks | present: [qwen.md](evidence/releases/1.0.0/qwen.md) | receipt passes the validator; see the Qwen note below |
| Antigravity CLI | automated | not installed; Git hooks | present: [antigravity.md](evidence/releases/1.0.0/antigravity.md) | receipt passes the validator; the 5-minute print timeout is bridged with resumes |
| Cursor | automated | fail-closed project hook + Git hooks | present: [cursor.md](evidence/releases/1.0.0/cursor.md); native guard probe passed | receipt passes the validator; needed the hard-stop prompt addendum to honor owner gates |
| Zed | automated | no native hook API; Git hooks | present: [zed.md](evidence/releases/1.0.0/zed.md) | receipt passes the validator; see the Zed note below |
| Kiro | automated | not installed; Git hooks | present: [kiro.md](evidence/releases/1.0.0/kiro.md) | receipt passes the validator; see the Kiro note below |
| Kimi Code | automated | not installed; Git hooks | present: [kimi.md](evidence/releases/1.0.0/kimi.md) | receipt passes the validator; needed the hard-stop prompt addendum to honor owner gates |

Historical smoke evidence remains under `evidence/`; release receipts belong
under `evidence/releases/<version>/` and are never inferred from smoke runs.

## Host notes

**Qwen Code.** Qwen's own OAuth tier ended, so the run authenticates through an
OpenAI-compatible endpoint. Its always-on per-turn tool-call cap halts a
pipeline mid-phase and is not covered by `model.skipLoopDetection`; set
`model.maxToolCallsPerTurn` to `0` in `~/.qwen/settings.json` to disable it.
Qwen needed the hard-stop prompt addendum to honor owner gates.

**Zed.** Zed has no native hook API, and its agent terminal sandbox denies
writes under `.git`, which blocks every Git-driven pipeline step. The receipt
run therefore uses a local `eval_cli` build that sets
`agent.sandbox_permissions.allow_unsandboxed` when `ZED_EVAL_UNSANDBOXED` is
present. `eval-cli` cannot resume a session, so each owner ruling is a fresh
session that reads persisted `.project` state; the receipt's run id is the run
directory rather than a session id. Zed honored every owner gate without the
hard-stop addendum, and twice declined to repair a pipeline artifact or push
around the bound-branch guard without an explicit ruling. Two host behaviours
need care when driving it: it may dispatch a child under a label whose case
differs from the `agent:` field it writes, which the validator rejects, and it
commits final-gate evidence as its own commit, which moves HEAD past the
reviewed revision so `preflight` refuses to ship. Both are caught before the
ship commit by the manifest phase of the assembly tool.

**Kiro.** `kiro-cli chat` returns `runError: Internal error` at the prompt stage
under sustained agent load, at varying points in a run; a trivial prompt with
the same flags succeeds, so this is a host-side fault rather than a
configuration problem. The pipeline resumes from persisted state after each
occurrence. Kiro honored every owner gate without the hard-stop addendum. It
re-ran the full-wave review through six passing cycles, so its `FINAL.md`
reuses `wave-1.cycle6`.

## Release procedure (from the 2026-09-06 Codex receipt run)

`npm run verify:release` accepts only host receipts as `.md` files at the root
of `evidence/releases/<version>/`; other notes live under `notes/`. Every
receipt must name one frozen candidate, and only evidence files plus this
matrix and TRUST-EVIDENCE.md may change after that candidate. So the order
is: merge every code and documentation change first, freeze the candidate,
run all eleven host receipts against it, then publish. For receipt assembly
options, see the [assembly tool](evidence/releases/1.0.0/codex/release_receipt.py)
usage docstring.
