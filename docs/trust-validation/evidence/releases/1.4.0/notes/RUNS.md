# Live release evidence — 1.4.0

## 2026-10-07 evaluation

Candidate: `cab24a78d31ba41d9d1b357dd72aeae00775ef2d`, the exact commit from
[Release run 37660774035](https://github.com/open-gsd/gsd-path/actions/runs/37660774035/job/112927439045).
All seven required hosts completed a fresh native milestone, guard checks,
archive, local-origin merge and tag. All seven receipts validated individually.
Each fresh clone of its local origin `main` passed the external CLI oracle:
6/6 per host, 42/42 total. The candidate source was not changed during the runs.

Raw native runs, owner replies, usage fields, oracle results, invalid attempts,
and guard probes are retained locally at
`~/evaluations/gsd-path-release-2026-10-07-cab24a78/`.
`usage-records.json` records native fields and their counting rules.
`RUN-STATUS.md` records the checkpoints and corrections.

| Host | CLI version | Integration commit | External oracle |
|---|---|---|---|
| Codex | 0.157.1 | `08dc56bf5e3b0d60beb16752e704f728b7b987bc` | 6/6 |
| Claude Code | 2.1.284 | `d1cfe94ff7ee9d8c6dccfa30954ad5f8f48e5eff` | 6/6 |
| Grok | 1.0.46 | `1bf94f096cb143bf9f9e5afdcd21da716e11b183` | 6/6 |
| OpenCode | 1.18.25 | `f1d7f58fef744af7c2b13dc30585c2e483cac3e5` | 6/6 |
| Antigravity | 1.3.1 | `f336ca1b6a163290af235bf63ed9f397758a9688` | 6/6 |
| Cursor | 2026.10.01-e373342 | `cfff3491b3e6e11ff41173eb865e670c8261ca9c` | 6/6 |
| Kimi | 0.43.0 | `ab266476d63bc38324c7a32a8382deeb3e51b95d` | 6/6 |

### Usage

Current owner ruling: **"allow and record"**. Token overages did not stop these
runs. Counts below use the fields each host exposes; their scopes differ and
are not a billing comparison. Guard probes and the invalid attempt are listed
separately instead of being hidden in a passing run's count.

| Host | Reported output tokens | Scope |
|---|---|---|
| Codex | 31,718 | latest cumulative parent-session field; resumed snapshots not summed |
| Claude Code | 61,266 | sum of per-invocation parent usage; cumulative model usage including children: 89,626 |
| Grok | 231,029 | sum of native per-invocation driver usage, including reported reasoning |
| OpenCode | 37,363 + 19,233 reasoning | unique parent `step_finish` fields; child usage is not included in this stream |
| Antigravity | 105,912 | latest cumulative conversation field; resumed snapshots not summed |
| Cursor | 202,882 | sum of native per-invocation CLI output fields |
| Kimi | 106,805 | native `usage.record` fields: main 56,137 and five children 50,668 |

Claude's native guard probe reported another 1,778 output tokens; Cursor's
reported 3,285. The invalid OpenCode attempt reported 9,452 output tokens and
6,910 reasoning tokens. Its interrupted resume had no additional completed
step usage; the available stream is retained without inventing a total.

### Corrections and retained failures

- OpenCode's first attempt inherited the source checkout in `PWD` despite a
  fixture `cwd`. It stalled on an external-directory permission. That attempt
  was invalidated and preserved separately. The passing run used a fresh
  fixture with both `cwd` and `PWD` set to its root.
- Intent review corrected missing integer input forms or output framing before
  approval. OpenCode's task AC3 also incorrectly expected 4 for repeated
  `--json` without a count; the plan was corrected to 0 before build approval.
- Cursor's parent changed a wave review's `Reviewed HEAD` after a Lane metadata
  edit. Ship approval was withheld. The native reviewer restored the actual
  reviewed commit, and an independent native final review passed at the new
  commit. Both the failure and correction remain in its fixture history.
  Project Verify ran at each of those two distinct heads; task Verify was not
  repeated. A later same-head preparation reused the corrected receipt with
  byte-identical ledger evidence.
- Kimi and OpenCode needed independent native final reviews because their wave
  reviews lacked explicit held-out edge citations. The runtime refused reuse;
  neither parent rewrote a verdict to force acceptance.
- Kimi's first landing was blocked by its generated Python bytecode file. The
  host removed that untracked cache and the canonical landing then passed.
- Claude's native guard refused some compound read-only shell commands. Narrow
  commands succeeded; the native denial probe and Git guards both passed.
- Grok surfaced ambiguity in "repository root" for project Verify. The evaluator
  confirmed the canonical sidecar root; the helper and its recorded result
  were left unchanged.
- The Codex, Cursor, Grok, Kimi and OpenCode `install.json` receipts first
  recorded `command` with one character per token. Each was corrected to the
  exact `command` value in that host's retained native driver record
  (`<host>/quick/install.json`). No install was run again and no other field
  changed.

Every host stopped at owner gates and before archive manifest rendering. Each
manifest binds a real completed native coder child to its task and landing.
Claude and Cursor additionally passed native denial probes. All seven proved
same-head preparation reuse without a new project execution or ledger entry.

The original CI already passed 101 Node tests (1 skipped), 2,590 Python tests
(40 skipped), and the 490-resource sync check on this exact candidate. This
repair changes release evidence and documentation only. The combined trust
validator is run on the evidence commit; no release has been published by
these local evaluations.

## 2026-09-30 evaluation (historical)

Candidate: `6d3e38ed525831217cf7d4790674feebd8afc75f` (main after PRs #240 and #241).

Raw native runs, owner replies, oracle records and guard references are local
and not committed: `~/orca/evaluations/gsd-path-release-1.4.0-6d3e38ed/`.

## Scope

Seven hosts were evaluated: Codex, Claude Code, Grok, OpenCode, Antigravity,
Cursor, and Kimi. Each has a validated receipt, zero invalid attempts, and a
6/6 external counter oracle from a fresh clone of its local origin `main`.

GitHub Copilot CLI was not evaluated. Its first attempt stopped after 41 seconds
with HTTP 402 `quota_exceeded`; probes with `gpt-5-mini`, `gpt-5.4-mini`, and
`claude-haiku-4.5` returned the same error, so the quota block was account-wide.
The maintainer excluded Copilot from the live-check scope, first for 1.4.0; it
stays excluded until the maintainer restores it by removing it from
`EXCLUDED_EVALUATION_HOSTS` before the next release's evaluation. Qwen, Kiro,
and Zed stay excluded for API cost. Exclusion is not a live-test pass.

## Owner gates

Every host stopped at each owner gate; no host recorded pre-approval. All
hosts except Codex and Claude ran with a hard-stop prompt addendum. Every
first INTENT missed some required criteria (all `int()` input forms, exact
output bytes, or failure on unknown flags and extra positionals) and was
corrected once before approval. The Cursor and OpenCode plans were also
corrected once (Cursor: JSON bytes differed between PLAN and task; OpenCode:
a Verify prefix `cd "$(dirname "$0")/.."` that leaves the repository under
`sh -c`).

## Output tokens (native fields, owner ruling: recorded, not blocking)

| Host | Parent session output | Notes |
|---|---|---|
| Codex | 22,145 | cumulative thread total |
| Claude Code | 47,971 (66,919 with children) | no single run over 30,000 |
| Grok | 198,399 | turn 1 62,805; turn 4 87,694; review child 37,831 |
| OpenCode | 27,490 (+13,477 reasoning) | all sessions under 30,000 |
| Antigravity | 96,668 | running conversation total; initial run 35,655 |
| Cursor | 45,767 | no single run over 30,000 |
| Kimi | 99,468 (main 66,037) | initial and build invocations over 30,000 with children |

## Hardening gaps and oddities (none is a candidate defect)

- Cursor's parent edited the reviewer's `wave-1.cycle1.md` to restore bold SC
  headings after `check_handoffs.py wave` refused a heading mismatch; verdicts
  did not change (same as the valid 1.3.1 Cursor run). The heading check is
  markup-sensitive and review files are not edit-protected.
- The plan gate does not check a Verify command's working directory (OpenCode).
- The native Bash guard over-blocks some read-only commands that touch archive
  paths with redirects, or `&&` compounds after integration (Claude).
- The harness prompt tells hosts to use the evaluator `activity` wrapper, which
  conflicts with the evaluator rule against it for Verify and sidecar work;
  hosts used it only for inspect/define helpers or read-only commands.
- Several hosts reported the wrong session id at the archive checkpoint
  (inherited evaluator environment or host worker ids); receipts use the real
  ids from the host streams.
- The serial Task Verify record names the primary checkout as `worktree` while
  `location` names the sidecar.
- Docs disagree on task-name case (`build_T001` vs `build_t001`).
- The Git pre-commit guard refuses any commit in a repository without a
  staged `.project/STATE.md` ("inspection failed"); evaluator reference repos
  needed `--no-verify` for their setup commit.
