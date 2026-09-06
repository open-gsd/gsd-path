# Full run evaluation — candidate 4295d75 (2026-09-06)

Owner request: run the full pipeline on the current main, and prove that the
code the pipeline ships is the code its verification phases checked. Owner
ruling during the run: nothing is released until everything works.

Candidate `4295d759e104671ff1dbdf6ba0edc6475a5ef602` is origin/main HEAD after
PR #62. The evaluation directory is
`/Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75`; the
tracked subset is under
[evidence/releases/1.0.0/codex-quick-4295d75](evidence/releases/1.0.0/codex-quick-4295d75/).

## Result

| Gate | Result | Evidence |
|---|---|---|
| `npm run verify:release` at candidate | tests pass (Node 133, Python 1112, 2 skipped); fails only on `missing host evidence` for all 11 hosts | run log in session |
| Pinned deterministic `evaluate_features.py check` | 1034 tests, exit 0 | [automated-summary.json](evidence/releases/1.0.0/codex-quick-4295d75/automated-summary.json) |
| Live quick-lane milestone on Codex (inspect, define, plan, build, review, prepare-final, ship, archive, integrate) | complete, all canonical gates passed, worktree clean | [native-runs.json](evidence/releases/1.0.0/codex-quick-4295d75/native-runs.json), [captures.jsonl](evidence/releases/1.0.0/codex-quick-4295d75/captures.jsonl) |
| Same-HEAD prepare-final repeat | receipt reused, ledger byte-identical, no new execution | [prepare-final-comparison.json](evidence/releases/1.0.0/codex-quick-4295d75/prepare-final-comparison.json) |
| Canonical `validate-integrated` | pass: ship `65ea78b`, merge `ae730d8`, tag `milestone/001-widget-counter-cli` | [integration.json](evidence/releases/1.0.0/codex-quick-4295d75/integration.json) |
| Independent widget oracle at shipped HEAD | pass, 6 of 6 checks | [product.json](evidence/releases/1.0.0/codex-quick-4295d75/product.json) |
| Verification replay against shipped code | pass: 16 of 16 recorded walkthroughs and both ledger entries reproduce | [replay.json](evidence/releases/1.0.0/codex-quick-4295d75/replay.json) |
| Native Codex guard (PreToolUse) | pass under the working host recipe; unverifiable from inside the harness run | [guard/](evidence/releases/1.0.0/codex-quick-4295d75/guard/) |

The pipeline did what it claims at this candidate. No product defect was found.
The release gate remains blocked on host receipts, as designed.

## Code output versus verification phases

The replay script re-executes every verification claim against the shipped
commits in fresh temporary clones. Walkthrough output is compared exactly;
ledger output uses the normalization described below. It is tracked beside
its result as
[replay_verification.py](evidence/releases/1.0.0/codex-quick-4295d75/replay_verification.py).

- FINAL.md `Reviewed HEAD` `7d4f9bc` is an ancestor of the shipped HEAD, and
  the product files outside `.project/` are byte-identical between them. The
  review verified the code that shipped.
- The wave review records 16 CLI walkthrough commands as JSON lines with exit,
  stdout and stderr. All 16 reproduce exactly at the reviewed commit.
- The task Verify at landing commit `775dcb3` reproduces the exit code,
  stdout, and stderr in [task-verify.json](evidence/releases/1.0.0/codex-quick-4295d75/task-verify.json);
  the receipt's product and test file hashes match that commit. Task bookkeeping
  under `.project/` is excluded from hash matching. The task ledger itself records
  only pass/fail. The project Verify at `7d4f9bc` reproduces the exit code,
  stdout, and stderr in its ledger `execution` field. Both output comparisons
  strip surrounding whitespace and normalize unittest wall time.
  Replay discovers `task-verify*.json` beside the script, or accepts an explicit
  receipt as its third argument after the repository and oracle import root.
  Missing milestone directories fail replay; an absent `count.py` records a
  skipped optional oracle.
- The independent oracle, which the agents never read, passes at the shipped
  HEAD.

Product size: `count.py` is 12 lines, `test_count.py` is 59 lines. The
milestone archive holds 13 pipeline files. The coder wrote one landing commit;
the reviewer wrote one review; project Verify ran once.

## Native run footprint

Five harness invocations on one Codex thread, model gpt-6-astra, reasoning
high, sandbox danger-full-access, CLI 0.153.4.

| Step | Elapsed | Output tokens |
|---|---:|---:|
| inspect and define, stop at intent gate | 336 s | 5,851 |
| plan, stop at plan gate | 173 s | 4,436 |
| build, isolated Task Verify, landing, full-wave review, prepare-final | 729 s | 8,479 |
| repeat prepare-final, ship, archive, integrate | 127 s | 2,253 |
| guard step inside the harness (reported unverifiable) | 189 s | 4,655 |
| total | 25.9 min | 25,674 |

Four extra `codex exec` guard probes ran outside the harness, about 30 seconds
each.

## Observed friction, not defects

- The model supplied free-text transition events twice; the state helper
  rejected both with the exact expected event named in the error, and the
  documented event string worked on retry. Same behavior as the 2026-09-05 run.
- The first wave-review artifact failed `check_handoffs.py wave` with
  `SC1 lacks pass evidence`; the reviewer corrected the format without rerunning
  any command.
- The planner's Approval record section in PLAN.md still reads
  `Plan approval is pending` after approval. GATE.json and the checkpoint are
  canonical, so it is harmless, but the coder stopped to confirm.

## Native guard finding

Inside the harness run the guard step correctly reported unverifiable: the
runner passes `--ignore-user-config`, and Codex 0.153.4 then never loads the
project's `.codex/hooks.json`. A traced hook proved the project hook is not
invoked with `-C <fixture>` or with `--ignore-user-config`, and is invoked
only when the process cwd is inside the fixture and user config is loaded. The
hook trust hash in `hooks.state` is not the raw file SHA-256;
`--dangerously-bypass-hook-trust` is the supported automation path. Under that
recipe the pinned, unmodified guard denied the `apply_patch` write to a
committed archive file before execution, the allowed read succeeded, and the
target hash was unchanged. Payloads and decisions are in
[traced-hook-payloads.log](evidence/releases/1.0.0/codex-quick-4295d75/guard/traced-hook-payloads.log).
Git hooks are unaffected by this and always apply.

## What still blocks release

- No host has a release receipt in the
  [LIVE-EVIDENCE-TEMPLATE](LIVE-EVIDENCE-TEMPLATE.md) format. That receipt needs
  a run manifest committed inside the fixture at the integration commit and a
  structured child-spawn binding, which the quick scenario does not produce.
  Today's run cannot be converted after the fact. A dedicated Codex
  release-evidence run is the next step, then the other ten hosts.
- The 2026-09-05 long-run items stay open: private PR #1 awaiting an owner
  merge commit, LOOP.md numeric fields, and an independent model family for
  the review panel.
