# Sub-agent orchestration options for path runs

Initial research: 2026-09-06, before implementation, on branch
`jeremymcs/subagent-orchestration` at `a972804`. The options and recommendation
below record that research; the 2026-09-07 owner decision supersedes the
proposed Orca adapter and runner action names. Current commands and behavior
are documented in [RUNTIME.md](../../RUNTIME.md#dispatch-driver).

## The problem, as measured

The parent orchestrator is a model reading a 630-line build contract and
sequencing about fifteen helper commands per task by hand. The runs on record
show where the output goes:

| Run | Parent output | Coder output | Total output | Parent share |
|---|---:|---:|---:|---:|
| Quick E2E `50718f8` | 34,553 | 4,226 | 54,636 | 63% |
| Lean quick E2E `62f5e0f` | 25,355 | 2,860 | 38,848 | 65% |

Source: `docs/trust-validation/e2e-50718f8.md` and
`docs/trust-validation/code-vs-verification.md`. The lean work cut reviewer
output by 57% and left the parent share unchanged. Reviews are no longer the
largest cost. Routing is.

The failures recorded in the same runs are routing failures, not judgment
failures: "used an incorrect initial binding event, omitted a required ship
argument, continued a command batch after failure, prematurely claimed a
corrected command passed." The 2026-08-22 audit
(`gsd-path-time-sink-is-verification-not-project`) adds parallel-load timeouts
and a heavy-suite serialization rule that lives only in prose.

Per task the parent performs, in order: `recover`, `ready`, brief lint,
coverage check, `prepare-task`, `activate-task`, spawn, wait, whole-diff path
check, sidecar reproduce (serial), Verify rerun, Log append, `land`,
`verify-record`, `retire`, then `ready` again. Only the spawn needs a model
host. Everything else is deterministic and already has a helper.

## Constraints any option must keep

1. Eleven supported hosts. The dispatch contract is a per-host adapter
   (`platforms/*/dispatch.md`); a Claude-only or Orca-only answer is an
   accelerator, not a replacement.
2. `isolation.py` owns checkouts, landing, and proof. No option may commit or
   create worktrees another way (ADR 0001).
3. `NEEDS-ORCHESTRATOR` needs a live ask/reply path where the host has one and
   a block-and-redispatch fallback where it does not.
4. Token accounting reads host event files (`token_budget.py record --events`).
   An option that hides the child's usage file loses the ledger.
5. Children never delegate. Parent owns timeout, cancellation, cleanup.

## Options

### A. Prompt-only tightening (status quo)

Keep the model as scheduler; add rules. This is what `b4827fd` tried. The
audit verdict stands: more ceremony, same cause. Rejected as the primary path.

### B. Deterministic round driver in Python

Extend `scripts/workflow_run.py` (102 lines today, already a fail-stop
sequencer of helpers) with two actions:

- `finish-task`: whole-diff path check, sidecar reproduce, Verify run and Log
  append, `land`, `verify-record`, `retire`, then `ready`. Zero dispatch.
  Pure routing. Removes roughly half the per-task parent steps and every
  "claimed pass after failure" class of error, because the runner stops on a
  non-zero exit and the parent only reads one JSON receipt.
- `run-round`: `recover`, `ready`, lint, `prepare-task`, `activate-task`,
  dispatch each coder through a **dispatch adapter**, wait, `finish-task` per
  result in task-id order, loop until the wave is done. Heavy-Verify
  serialization becomes a lock in code, not a sentence in prose.

Dispatch adapters, chosen by what is present on the machine:

| Adapter | Mechanism | Verified here | Gives |
|---|---|---|---|
| Headless CLI | `claude -p --output-format json`, `codex exec --json` | Yes, both ran nested inside this Claude Code session on 2026-09-06 and returned usage JSON | Portable across every host that has a CLI; exact per-child usage for `token_budget.py`; `--model`/`--effort` per child |
| Orca `worker-start` | see option D | Partly (see risks) | Live ask/reply, durable Task/Dispatch provenance, transcript reads |
| Host Agent tool | today's `platforms/*/dispatch.md` path | Yes (current behavior) | Fallback where no CLI or Orca exists; parent still spawns by hand but runs `finish-task` instead of fifteen steps |

The parent skill shrinks to: run `run-round`, act on its typed result
(`done`, `blocked`, `question`, `plan-defect`), answer questions, approve.
Model work is confined to judgment: coder briefs, reviewer verdicts,
`NEEDS-ORCHESTRATOR` answers, user rulings.

Risks to prove before adopting:

- Headless children need a permission posture. `claude -p` honors
  `--allowedTools` and project PreToolUse hooks (`guard_hook.py` still fires);
  `codex exec` needs `--sandbox` and trusted project hooks
  (`codex-project-hooks-loading-rules`). Decide per host; do not default to
  skip-permissions.
- A child that hangs is a parent timeout, not a host event. The driver needs
  a wall-clock bound sourced from the owner (no invented default).
- Blast radius: `isolation.py` (3,151 lines) is untouched; the new code is
  composition in `workflow_run.py` plus one adapter module. Tests exist for
  every composed helper (`tests/test_isolation.py`, `test_build_state.py`,
  `test_dispatch_contract.py`).

### C. Claude Code `Workflow` tool

A JavaScript script drives `agent()` calls with `pipeline`/`parallel`,
JSON-schema outputs, a journal, and resume-from-run caching. Concurrency is
capped at min(16, CPUs minus 2).

Fit: good for fan-out stages that are pure model work, such as a dispatch
round of coders, a deep review pair, or a skeptic set. The script has no
filesystem, so `prepare-task`, `land`, and `retire` stay outside it. It is
Claude-only, and the tool requires the user to opt in or a skill to instruct
it. Verdict: a possible Claude adapter for the coder fan-out inside option B,
not an orchestration layer for path runs.

### D. Orca orchestration (Run / Task / Dispatch)

Already anticipated by `platforms/shared-agents/dispatch.md` ("if the runtime
exposes structured Run/Task/Dispatch orchestration, bind one Run, create one
Task per brief, wait for every `worker_done`"). Orca 1.4.197 provides
`run-create`, `task-create --deps`, `worker-start --task --worktree <exact
existing> --agent claude|codex|opencode|grok --model --effort`, `check --wait
--types worker_done,escalation,question`, `ask`/`reply`, `worker-read`
transcripts, and `worker-release`.

Strengths that map directly onto Path's contract: dependency DAG, exactly-once
`worker_done` with `--outcome failed` never buried in prose, blocking
`ask`/`reply` for `NEEDS-ORCHESTRATOR`, nested-depth guard of 1 (matches
"children never delegate"), mixed hosts in one Run.

Risks:

- Requires the Orca app running and the experimental flag. Only this
  machine's runs benefit. Consumers on the other ten hosts get nothing.
- Observed on 2026-09-06: `worker-start --worktree current` settled
  `agent_prompt_stalled` because terminal startup exceeded the 60 s readiness
  window (`orca-worker-start-terminal-slow-start`). The workaround is
  terminal-first, then `worker-start --terminal`. A driver must encode that.
- Unverified: whether `--worktree` accepts a linked worktree created by
  `isolation.py` that Orca did not create. If not, the coder would need a
  pre-created terminal in that path via `terminal create --worktree` and
  `dispatch --inject`, which the guide documents as the low-level recipe.
- A worker is a full TUI session, heavier and slower to start than a headless
  CLI child. For a two-minute coder task the startup is a real fraction.
- The coordinator is still a model running `check --wait` loops unless option
  B wraps it. On its own it moves the routing, it does not remove it.

Verdict: the best adapter where present, because it is the only one with a
live ask channel. Not the primary layer.

### E. Standalone orchestrator (Agent SDK or provider APIs)

A daemon that owns dispatch through provider SDKs. Maximum control, most new
code, provider-specific, and it bypasses every host's own tool permissions,
hooks, and skill loading. It reintroduces the host matrix as a client matrix.
Rejected unless B and D both fail in practice.

### F. Hook-enforced sequencing

PreToolUse hooks that deny `isolation.py land` without a matching
`verify-record`, or deny a second spawn with a colliding logical name. Cheap,
already have `guard_hook.py`, but Claude, Codex, and Cursor only. This is a
guard, not a driver; it catches the wrong order after the model chose it.
Complement to B, not an alternative.

### G. `gsd-path-loop` as outer scheduler

Exists today for bounded, externally-scheduled passes. It wraps a whole pass;
it does not change how a wave dispatches. Useful for unattended repeated runs
of option B, orthogonal otherwise.

## Comparison

| Criterion | A | B | C | D | E | F |
|---|---|---|---|---|---|---|
| Removes model routing (the 63% share) | no | yes | partial | partial | yes | no |
| Portable to all eleven hosts | yes | yes with adapters | Claude only | Orca only | no | three hosts |
| Keeps `isolation.py` as sole git owner | yes | yes | yes | yes | yes | yes |
| Live ask/reply for `NEEDS-ORCHESTRATOR` | host-dependent | via D adapter | no | yes | build it | n/a |
| Exact child usage for token ledger | host-dependent | yes (CLI JSON) | journal only | transcript | yes | n/a |
| Crash recovery | `recover` | `recover` plus receipts | resume cache | Dispatch state | build it | n/a |
| New code | none | ~1 module + runner actions | script per phase | adapter | large | small |
| Proven here today | yes | headless probes yes | tool present | partly | no | hooks exist |

## Recommendation

Do B in two steps, with D and C as adapters rather than layers.

1. **`finish-task` first.** It touches no dispatch, composes helpers that
   already have tests, and deletes the largest block of prose from the build
   contract. Measure the parent share on the next quick-lane E2E against the
   65% baseline before step 2.
2. **`run-round` with the headless-CLI adapter**, Orca adapter when
   `orca status` is healthy, host Agent tool as the fallback that keeps
   today's per-host `dispatch.md` valid. Add F-style hooks only if a specific
   misorder recurs after B.

Things to prove before committing to step 2, each one command:

- Orca `worker-start --worktree <isolation.py path>` on a non-Orca worktree.
- `codex exec` nested inside a Codex parent (only Claude-parent nesting was
  tested).
- The permission posture per host for headless children, decided by the owner.
- An owner-supplied child wall-clock bound; the driver has no default.

## Evidence

- Measured shares: `docs/trust-validation/e2e-50718f8.md`,
  `docs/trust-validation/code-vs-verification.md`.
- Current contract: `skills/gsd-path-build/SKILL.md` wave loop,
  `platforms/claude/dispatch.md`, `platforms/shared-agents/dispatch.md`.
- Deterministic runner to extend: `scripts/workflow_run.py`.
- Orca guide: `orca skills get orchestration` on 1.4.197 (version-matched).
- Headless probes, 2026-09-06, from inside a Claude Code session:
  `claude -p "Reply with exactly: ok" --output-format json --max-turns 1`
  returned `stop_reason: end_turn` with `usage.output_tokens`;
  `codex exec --skip-git-repo-check --ephemeral --json "Reply with exactly:
  ok"` returned `turn.completed` with `usage.output_tokens`.

## Implementation plan (2026-09-07)

Decision: build the driver, not a message bus. Path's task frontmatter,
`isolation.py`, and `build_state.py` already hold the DAG, provenance, and
completion proof. The only missing piece is a process that spawns children,
waits on them, and calls the existing helpers in the contract's order.

### Implemented contract

The owner selected a Path-native driver with an owner-supplied headless child
command, without Orca orchestration. See the authoritative
[dispatch driver reference](../../RUNTIME.md#dispatch-driver) for commands,
records, recovery, and limits, and the
[build wave loop](../../skills/gsd-path-build/SKILL.md#wave-loop) for the parent
procedure. Regression coverage lives in
[tests/test_dispatch_driver.py](../../tests/test_dispatch_driver.py).

### Initial review outcome (2026-09-07)

Implemented as `scripts/dispatch_driver.py` with `isolation.task_log_delta`,
`workflow_run.py lint-round`, the coder brief's `RESULT:` line, and eleven
tests in `tests/test_dispatch_driver.py`.

Simplify pass (four lenses) applied: duplicate state fields dropped, one
`update_state`, `STOP_ERRORS`, lint through `workflow_run`, `isolation`
git helpers, `ready` only re-run after a landing or redispatch. Left in place
with a `ponytail:` note: sidecar reproduction stays in the driver until a
second caller needs it in `isolation.py`; the one-heavy-Verify rule stays in
the driver rather than `build_state.ready`; async Verify per isolate is a
design change, not waste.

Codex gpt-6-astra, two rounds. Round one: three P1 (wave pinned after
settlement, `finish` landing an unread child, stale record after a recovered
landing), three P2 (redispatch inherited completion fields, second question
misread, Verify output not preserved), plus capacity, retry hand-back, and a
step-5 wording conflict. Round two closed six and left three partial; all
three are now closed: the pinned wave includes open questions, `finish`
refuses any task with a dispatch record that is not an unread exit, manual
finishes keep `verify.json` under the records root, and `--capacity` must be
positive. Still deferred by design: token-budget admission for headless
children, and the parent-owned retry procedure.

### Follow-up (2026-09-07, after PR #75 review)

Owner ruling: safe defaults with per-milestone resets. Dispatch records and the
token ledger are now keyed by the bound branch, `--max-attempts` defaults to 2
(the contract's one logged redispatch), question redispatches do not count,
and budgets are opt-in through `--task-limit`, `--session-limit`, and
`--budget-authority` with a Claude JSON usage adapter in `token_budget.py`.
A child that writes a question and then fails is classified as a failure.
