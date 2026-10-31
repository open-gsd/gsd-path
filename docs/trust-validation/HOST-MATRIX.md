# Host trust matrix

`supported` means the installer and static dispatch contract exist. See the
[release contract](TRUST-VALIDATION-SPEC.md#release-contract) for release trust
and required live-check scope.

The historical results below do not define the current required host set;
see [Live-check scope](TRUST-VALIDATION-SPEC.md#live-check-scope).

Release 1.7.1 uses frozen candidate `ab909c7ddd43a178305672e74f48a6d3d5624e62`
prepared in PR #536. All seven required hosts ran fresh milestones on
2026-10-31 UTC; receipts are in `evidence/releases/1.7.1/`.

Release 1.7.0 used frozen candidate `e2dd08576d7486b302dc7a870a47aaa7f788089f`
prepared in PR #529. All seven required hosts ran fresh milestones on
2026-10-30–31 UTC; receipts are in `evidence/releases/1.7.0/`.

Release 1.6.2 used frozen candidate `c14248da2eb5db1362175f50382af8ecb9fd1bc3`
from main on 2026-10-16, after the 1.6.2 version change (PR #433). Its receipts
are in `evidence/releases/1.6.2/`. Release 1.6.1 used candidate
`ec116bf9af69af2a1769d73b566b53834fa4c327`; its receipts are in
`evidence/releases/1.6.1/`. Release 1.6.0 used candidate
`2aad06114ebf7d4b88ba70d3de63627e4c238c2f`; its receipts are in
`evidence/releases/1.6.0/`. Release 1.5.0 used candidate
`cab24a78d31ba41d9d1b357dd72aeae00775ef2d`; its receipts were recorded as
package 1.4.0 before the version change and stay in `evidence/releases/1.4.0/`.
The published 1.4.0 used candidate
`6d3e38ed525831217cf7d4790674feebd8afc75f`; tag `v1.4.0` has its receipts. Every host in the release
scope has a validated full-milestone receipt and a passing external CLI
acceptance check. The complete release gate remains required before
publication; see the [release contract](../../RELEASE.md#release-contract).

| Host | Install | Native guard installed | Full live milestone | Candidate result |
|---|---|---|---|---|
| Codex | automated | git-only tier: the `--ignore-user-config` harness run has no native hook, so Git hooks carry it | [codex.md](evidence/releases/1.7.1/codex.md) | **pass** on `ab909c7d` |
| Claude Code | automated | fail-closed project hook + Git hooks | [claude.md](evidence/releases/1.7.1/claude.md) | **pass** on `ab909c7d` |
| Grok | automated | not installed; Git hooks | [grok.md](evidence/releases/1.7.1/grok.md) | **pass** on `ab909c7d` |
| OpenCode | automated | not installed; Git hooks | [opencode.md](evidence/releases/1.7.1/opencode.md) | **pass** on `ab909c7d` |
| GitHub Copilot CLI | automated | not installed; Git hooks | not run: account quota exhausted | excluded at the maintainer's request until restored |
| Antigravity CLI | automated | not installed; Git hooks | [antigravity.md](evidence/releases/1.7.1/antigravity.md) | **pass** on `ab909c7d` |
| Cursor | automated | fail-closed project hook + Git hooks | [cursor.md](evidence/releases/1.7.1/cursor.md) | **pass** on `ab909c7d` |
| Kimi Code | automated | not installed; Git hooks | [kimi.md](evidence/releases/1.7.1/kimi.md) | **pass** on `ab909c7d` |
| Qwen Code | automated | not installed; Git hooks | not run (API credits) | excluded at the maintainer's request |
| Zed | automated | no native hook API; Git hooks | not run (API credits) | excluded at the maintainer's request |
| Kiro | automated | not installed; Git hooks | not run (API credits) | excluded at the maintainer's request |
| Muse Code | automated | not installed; Git hooks | not run: no recorded live release evidence yet | excluded until live evidence is recorded |

Historical smoke evidence remains under `evidence/`; release receipts belong
under `evidence/releases/<version>/` and are never inferred from smoke runs.

## 1.7.1 run notes

All seven required hosts completed fresh milestones and passed 42 external
CLI acceptance checks from clones of their integrated fixture origins. Each
reused its final review and project Verify result at unchanged HEAD. Claude
and Cursor proved native guard enforcement; the other hosts retained their
declared Git-only tier. Invalid attempts and provider failures remain
recorded. OpenCode recovered through refreshed OpenAI OAuth and a fresh
native conversation on the same fixture, preserving the original child and
verification records. See [run notes](evidence/releases/1.7.1/notes/RUNS.md).
The publication workflow still owns the full release gate.

## 1.7.0 run notes

All seven required hosts completed fresh milestones and passed the external
CLI acceptance check from clones of their integrated fixture origin/main.
Each reused its full-wave final review and repeated project-Verify result at
unchanged HEAD without another verification execution. Claude and Cursor
proved native-hook enforcement; the other five used their declared Git-only
tier. Invalid Cursor and Codex attempts were retained and supply no passing
proof. Kimi recovered from provider timeouts. See [run notes](evidence/releases/1.7.0/notes/RUNS.md)
for corrections, usage counters, and individual acceptance outputs. The
publication workflow still owns the full release gate.

## 1.6.2 run notes

All seven hosts in the live-check scope ran a fresh milestone on the 1.6.2
candidate on 2026-10-16; no earlier receipt was reused, because product
scripts changed after the 1.6.1 candidate. No attempt was invalid and no
candidate defect was found. On every host the final review was reused without
an extra dispatch (#428). GitHub Copilot CLI, Muse Code, Qwen Code, Zed and
Kiro stay excluded, as in the 1.4.0 notes below. Per-session output-token
usage over 30,000 is recorded as a finding and did not stop a run (owner
ruling). See [run notes](evidence/releases/1.6.2/notes/RUNS.md) for gate
corrections, token usage, and hardening gaps.

## 1.6.1 run notes

All seven hosts in the live-check scope ran a fresh milestone on the 1.6.1
candidate on 2026-10-15; no earlier receipt was reused, because product
scripts changed after the 1.6.0 candidate. One Cursor attempt was invalid
(a pre-ship checkpoint commit against the ship contract) and was re-run; no
candidate defect was found. GitHub Copilot CLI, Muse Code, Qwen Code, Zed and
Kiro stay excluded, as in the 1.4.0 notes below. Per-session output-token
usage over 30,000 is recorded as a finding and did not stop a run (owner
ruling). See [run notes](evidence/releases/1.6.1/notes/RUNS.md) for gate
corrections, token usage, and hardening gaps.

## 1.6.0 run notes

All seven hosts in the live-check scope ran a fresh milestone on the 1.6.0
candidate on 2026-10-11; no earlier receipt was reused, because product
scripts changed after the 1.5.0 candidate. No attempt was invalid and no
candidate defect was found. GitHub Copilot CLI, Muse Code, Qwen Code, Zed and
Kiro stay excluded, as in the 1.4.0 notes below. Per-session output-token
usage over 30,000 is recorded as a finding and did not stop a run (owner
ruling). See [run notes](evidence/releases/1.6.0/notes/RUNS.md) for gate
corrections, token usage, and hardening gaps.

## 1.4.0 run notes

Muse Code was not evaluated: the Muse delegation adapter was added from live
tool schemas; no recorded live release evidence yet. It is excluded from the
live-check scope until evidence is recorded; restore it by removing it from
`EXCLUDED_EVALUATION_HOSTS`. Exclusion is not a live-test pass.

Copilot was not evaluated: every Copilot-routed model, including zero-premium
models, returned HTTP 402 `quota_exceeded` for the account. The maintainer
excluded Copilot, first for 1.4.0; it stays excluded until the maintainer
restores it by removing it from `EXCLUDED_EVALUATION_HOSTS` before the next
release's evaluation. Exclusion is not a live-test pass. Per-session
output-token usage over 30,000 is recorded as a finding and did not stop a run
(owner ruling). See [run notes](evidence/releases/1.4.0/notes/RUNS.md) for gate corrections,
token usage, and hardening gaps.

## 1.1.0 results

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

Follow [Recording trust evidence](../../RELEASE.md#recording-trust-evidence)
and the [receipt format](LIVE-EVIDENCE-TEMPLATE.md). Keep non-receipt notes
under `evidence/releases/<version>/notes/`. For receipt assembly options,
see the [assembly tool](evidence/releases/1.0.0/codex/release_receipt.py)
usage docstring.

See [CI tiers](../../RELEASE.md#ci-tiers) for development and release checks.

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
