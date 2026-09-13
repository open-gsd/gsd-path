# Host trust matrix

`supported` means the installer and static dispatch contract exist. A release
is end-to-end trusted only when `npm run verify:release` finds a current passing
full-milestone receipt for every host below.

Release candidate `bd7516713dd33ba483129ac9ba5cc16f5a3b7e18` is frozen on the
release branch (2026-09-13; includes PR #101 plus release-prep tooling). All
eleven host receipts are being refreshed against it;
`npm run verify:release` stays red until every receipt passes.

Historical receipts on `091d27927a2c0c2ecc55ce386fb2232556da6336` remain under
`evidence/releases/1.0.0/` for comparison but no longer satisfy the validator
once non-evidence files change after that candidate.

| Host | Install | Native guard installed | Full live milestone | Current posture |
|---|---|---|---|---|
| Codex | automated | git-only tier: the `--ignore-user-config` harness run has no native hook, so Git hooks carry it | prior: [codex.md](evidence/releases/1.0.0/codex.md) | **refresh pending** on `bd75167` |
| Claude Code | automated | fail-closed project hook + Git hooks | prior: [claude.md](evidence/releases/1.0.0/claude.md) | **refresh pending** on `bd75167` |
| Grok | automated | not installed; Git hooks | prior: [grok.md](evidence/releases/1.0.0/grok.md) | **refresh pending** on `bd75167` |
| OpenCode | automated | not installed; Git hooks | prior: [opencode.md](evidence/releases/1.0.0/opencode.md) | **refresh pending** on `bd75167` |
| GitHub Copilot CLI | automated | not installed; Git hooks | prior: [copilot.md](evidence/releases/1.0.0/copilot.md) | **refresh pending** on `bd75167` |
| Qwen Code | automated | not installed; Git hooks | prior: [qwen.md](evidence/releases/1.0.0/qwen.md) | **refresh pending** on `bd75167` |
| Antigravity CLI | automated | not installed; Git hooks | prior: [antigravity.md](evidence/releases/1.0.0/antigravity.md) | **refresh pending** on `bd75167` |
| Cursor | automated | fail-closed project hook + Git hooks | prior: [cursor.md](evidence/releases/1.0.0/cursor.md) | **refresh pending** on `bd75167` |
| Zed | automated | no native hook API; Git hooks | prior: [zed.md](evidence/releases/1.0.0/zed.md) | **refresh pending** on `bd75167` |
| Kiro | automated | not installed; Git hooks | prior: [kiro.md](evidence/releases/1.0.0/kiro.md) | **refresh pending** on `bd75167` |
| Kimi Code | automated | not installed; Git hooks | prior: [kimi.md](evidence/releases/1.0.0/kimi.md) | **refresh pending** on `bd75167` |

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
reviewed revision so `preflight` refuses to ship. The assembly tool’s manifest
phase catches the child-label mismatch. `archive_milestone.py preflight` catches
the reviewed-HEAD drift before the ship commit.

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
run all eleven host receipts against it, then seek the separate
[publication decision](TRUST-EVIDENCE.md#release-evidence-2026-09-13). For receipt assembly
options, see the [assembly tool](evidence/releases/1.0.0/codex/release_receipt.py)
usage docstring.

### 1.0.0 refresh (2026-09-13)

Frozen candidate: `bd7516713dd33ba483129ac9ba5cc16f5a3b7e18` (release branch
after PR #101 and release-prep tooling). Prepare every host harness:

```bash
bash scripts/prepare_release_evidence.sh \
  --candidate "$(git rev-parse HEAD)" \
  --output-base "$HOME/evaluations/gsd-path-release-e6f4833"
```

Run each host's quick-lane milestone from its prepared directory, assemble
receipts with `release_receipt.py`, then `npm run verify:release`.
