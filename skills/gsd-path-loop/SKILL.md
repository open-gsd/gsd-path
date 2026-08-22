---
name: gsd-path-loop
description: Use only when the user explicitly invokes $gsd-path-loop. Runs one bounded loop pass from a LOOP.md spec — gate checks, independent verification, one fix worker, telemetry. Autonomy lives in the external scheduler that invokes this skill; the skill never schedules itself.
---

# GSD Path Loop

One invocation = one bounded pass. The bundled deterministic helper
[loop_run.py](scripts/loop_run.py) owns the gates — run/skip, verify,
record, status — and its output is the only gate authority; do not
reimplement that logic in model reasoning. The model owns what the helper
cannot: reading the spec's prose, dispatching one fix worker, and feeding
failures back. Fill new specs from the canonical
[LOOP.md template](templates/loop.md); a filled dogfood example lives at
[examples/ci-repair.LOOP.md](examples/ci-repair.LOOP.md).

Run every helper command from the repository root — relative paths in the
spec (`log:`, `skip_when:`, `verify:`) resolve against the working
directory. Use the bundled copy of the helper next to this file. When the
repository has a `.project/`, first run the bundled
`scripts/discussion_records.py pending --repo <absolute-root>`; when
`.project/discuss/ANSWERS.md` is absent, continue. A pending follow-up owned
by loop work blocks the pass with links to ANSWERS.md.

This skill never advances a gsd-path phase gate: it wraps bounded work, it
does not route the pipeline.

## Process

1. **Gate.** Run `python3 scripts/loop_run.py check --spec <path>`. On
   `skip`, report the reason to the user and stop — no worker, no record.
2. **Read the spec.** Read the whole LOOP.md: machine fields and prose
   sections (Goal, Worker scope, Feedback route, Human gates, Stops, Output).
   The prose binds the worker brief below.
3. **Baseline verify.** Run `python3 scripts/loop_run.py verify --spec
   <path>`. On `pass`, the goal is already green: record `pass` with
   `--iterations 0`, report, and stop. A green baseline never dispatches a
   worker.
4. **One bounded worker.** On `fail`, dispatch ONE fix worker (v1: single
   worker, no fan-out) with the exact failing commands and output tails from
   the helper, plus the spec's Worker scope. The worker fixes the smallest
   failed unit named by the Feedback route — not the whole goal.
5. **Independent verify.** The wrapper re-runs `verify`; worker claims are
   not evidence. On `fail`, feed the new failing output back to the worker.
   Repeat up to `max_iterations` fix → verify cycles total and stop when the
   `wall_clock` budget is spent, whichever comes first.
6. **Blocked.** When the worker cannot proceed, or the only remaining fix
   needs a Human gates action, stop with `BLOCKED: <reason>` naming the
   gate — never perform the gated action to unblock.
7. **Record.** Append the outcome:
   `python3 scripts/loop_run.py record --spec <path> --result
   pass|fail|blocked|skipped --iterations <n> --used <duration> [--notes ...]
   [--rescue]`.
8. **Report.** Close per the AGENTS.md asking conventions: **Outcome** —
   what changed, or why nothing ran; **Review** — a Markdown link to the
   spec's log path (or the spec itself when no record was written), resolved
   absolute path printed if the host cannot render links; **Next** — the one
   question or action now required. `python3 scripts/loop_run.py status
   --spec <path>` gives the aggregate counters when the user asks how the
   loop is trending.

## Rules

- Never commit, push, tag, or mutate git state — a loop pass leaves version
  control to the user.
- Never edit tests to match broken code. If the test is the bug, say so in
  the report and stop; weakening a verifier is a human-gate action.
- Never touch paths the spec's Worker scope declares read-only.
- Human gates are never-auto: reaching one means `BLOCKED: <reason>`, not a
  judgment call.
- The helper's `check` output decides whether a pass runs at all; a `skip`
  is a valid, final outcome.
- A pass that cannot honestly reach green stops per the spec's Stops and
  records the truth; silent partial success is the worst outcome.
