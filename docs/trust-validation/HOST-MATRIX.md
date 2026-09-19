# Host trust matrix

`supported` means the installer and static dispatch contract exist. A release
is end-to-end trusted only when `npm run verify:release` finds a current passing
full-milestone receipt for every host below.

Release 1.1.0 uses frozen candidate `af0b082964510c471798826d7e2e05617d8d6dc3`
from main on 2026-09-18, after PRs #124 and #125. Every host below has a
validated full-milestone receipt and a passing external CLI acceptance check.
The complete release gate remains required before publication; see the
[release contract](../../RELEASE.md#release-contract).

| Host | Install | Native guard installed | Full live milestone | Candidate result |
|---|---|---|---|---|
| Codex | automated | git-only tier: the `--ignore-user-config` harness run has no native hook, so Git hooks carry it | [codex.md](evidence/releases/1.1.0/codex.md) | **pass** on `af0b082` |
| Claude Code | automated | fail-closed project hook + Git hooks | [claude.md](evidence/releases/1.1.0/claude.md) | **pass** on `af0b082` |
| Grok | automated | not installed; Git hooks | [grok.md](evidence/releases/1.1.0/grok.md) | **pass** on `af0b082` |
| OpenCode | automated | not installed; Git hooks | [opencode.md](evidence/releases/1.1.0/opencode.md) | **pass** on `af0b082` |
| GitHub Copilot CLI | automated | not installed; Git hooks | [copilot.md](evidence/releases/1.1.0/copilot.md) | **pass** on `af0b082` |
| Qwen Code | automated | not installed; Git hooks | [qwen.md](evidence/releases/1.1.0/qwen.md) | **pass** on `af0b082` |
| Antigravity CLI | automated | not installed; Git hooks | [antigravity.md](evidence/releases/1.1.0/antigravity.md) | **pass** on `af0b082` |
| Cursor | automated | fail-closed project hook + Git hooks | [cursor.md](evidence/releases/1.1.0/cursor.md) | **pass** on `af0b082` |
| Zed | automated | no native hook API; Git hooks | [zed.md](evidence/releases/1.1.0/zed.md) | **pass** on `af0b082` |
| Kiro | automated | not installed; Git hooks | [kiro.md](evidence/releases/1.1.0/kiro.md) | **pass** on `af0b082` |
| Kimi Code | automated | not installed; Git hooks | [kimi.md](evidence/releases/1.1.0/kimi.md) | **pass** on `af0b082` |

Historical smoke evidence remains under `evidence/`; release receipts belong
under `evidence/releases/<version>/` and are never inferred from smoke runs.

## 1.1.0 run notes

Qwen completed the authorized retry through its native CLI with the existing
OpenRouter `anthropic/claude-sonnet-5` backend. Credit failures and invalid
previous attempts remain recorded; they do not supply passing proof. Fresh
parent contexts continued the same fixture from its recorded state.

Antigravity completed an independent native final review after the runtime
rejected full-wave review reuse. Its receipt proves the full milestone, not
successful review reuse. See [run notes](evidence/releases/1.1.0/notes/RUNS.md)
for retained failures and evidence capture details.

## Historical host notes (1.0.0)

**Qwen Code.** Qwen's own OAuth tier ended, so the run authenticates through an
OpenAI-compatible endpoint. Its always-on per-turn tool-call cap halts a
pipeline mid-phase and is not covered by `model.skipLoopDetection`; set
`model.maxToolCallsPerTurn` to `0` in `~/.qwen/settings.json` to disable it.
Qwen needed the hard-stop prompt addendum to honor owner gates. Qwen writes
session scratch under `.qwen/tmp/` in the repository, which the run excluded
through `.git/info/exclude`.

**Zed.** Zed has no native hook API, and its agent terminal sandbox denies
writes under `.git`, which blocks every Git-driven pipeline step. The receipt
run therefore uses a local `eval_cli` build that sets
`agent.sandbox_permissions.allow_unsandboxed` when `ZED_EVAL_UNSANDBOXED` is
present. `eval-cli` cannot resume a session, so each owner ruling is a fresh
session that reads persisted `.project` state; the receipt's run id is the run
directory rather than a session id. Zed stopped at every owner gate. On the 0524757 run, one
attempt was invalidated because Zed hand-edited a wave review the gate had
refused (issue #112). The passing run's owner replies required the reviewer to
omit `Lens:` and to redispatch on any gate refusal. Zed may dispatch a child
under a label whose case differs from the `agent:` field it writes; the
assembly tool's manifest phase catches that. `archive_milestone.py prepare`
refuses a final review whose Reviewed HEAD is not HEAD (PR #108).

**Kiro.** `kiro-cli chat` returns `runError: Internal error` at the prompt stage
under sustained agent load, at varying points in a run; a trivial prompt with
the same flags succeeds, so this is a host-side fault rather than a
configuration problem. The pipeline resumes from persisted state after each
occurrence. On the 0524757 candidate Kiro needed the hard-stop prompt addendum,
plus an instruction to propose doc-vs-code rulings without writing them.

## Release procedure (from the 2026-09-06 Codex receipt run)

`npm run verify:release` accepts only host receipts as `.md` files at the root
of `evidence/releases/<version>/`; other notes live under `notes/`. Every
receipt must name one frozen candidate, and only evidence files plus this
matrix and TRUST-EVIDENCE.md may change after that candidate. So the order
is: merge every code and documentation change first, freeze the candidate,
run all eleven host receipts against it, then publish only with owner authorization. For receipt assembly
options, see the [assembly tool](evidence/releases/1.0.0/codex/release_receipt.py)
usage docstring.

Ordinary PR and `main` CI run automated tests, including the trust validator
tests; they do not require refreshed release receipts. The manual **Release
trust evidence** workflow validates a frozen candidate and its receipts. Both
npm `prepublishOnly` and the Release workflow still require `verify:release`
with current proof from all eleven hosts. Existing receipts remain evidence
for their named candidate only.

### 1.0.0 receipts (2026-09-15)

Frozen candidate: `052475792bbe211f104d34a524c22db056bdee71`. Harnesses were
prepared with:

```bash
bash scripts/prepare_release_evidence.sh \
  --candidate "$(git rev-parse HEAD)" \
  --output-base "$HOME/orca/evaluations/gsd-path-release"
```

Each host ran its quick-lane milestone from its prepared directory. Receipts
were assembled with `release_receipt.py` and validated together with
`npm run verify:release`.
