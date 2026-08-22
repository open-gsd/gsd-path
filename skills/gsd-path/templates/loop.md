# LOOP — <loop name>

<!-- Written by whoever designs the loop. Executed one bounded pass at a time
     by $gsd-path-loop. The key: value lines below are the machine fields read
     by scripts/loop_run.py — keep them exact: one field per line, no nesting,
     no duplicate fields except verify. A single trailing HTML comment on a
     field line is stripped by the parser. The prose sections are read by the
     model, never by the parser. Mandatory fields:
     loop, status, trigger, verify, max_iterations, wall_clock, log.
     Optional fields: cooldown, skip_when, period, period_budget. -->

loop: <kebab-case name>
status: active              <!-- active | paused | done -->
trigger: manual             <!-- who invokes one pass: manual | event | schedule -->
cooldown: 15m               <!-- optional: minimum gap between recorded passes -->
skip_when: <shell command>  <!-- optional: exit 0 = skip this pass -->
verify: <shell command>     <!-- repeat the line per verifier command, in order -->
max_iterations: 3           <!-- fix → verify cycles allowed in one pass -->
wall_clock: 30m             <!-- per-pass wall-clock budget -->
period: 24h                 <!-- optional: rolling window for period_budget -->
period_budget: 4h           <!-- optional: total wall-clock usable per period;
                                 requires period -->
log: .project/loop/<name>.LOG.jsonl

## Goal

<What "green" means — the one outcome the verify commands must prove. If the
loop cannot state this in a sentence, it is not ready to run.>

## Worker scope

<What one fix worker must do, and what it must never do: no commits, pushes,
or tags; no editing tests to match broken code; paths that are read-only to
the worker.>

## Feedback route

<On a failed verify, what the worker gets back: the exact failing command and
its output tail, aimed at the smallest failed unit — not a retry of the whole
goal.>

## Human gates

<Never-auto actions. When a fix requires one of these, the pass stops with
BLOCKED: <reason> and the named action goes to the user.>

## Stops

<Conditions that end a pass honestly: verify green (pass), max_iterations or
wall_clock spent (fail), a human-gate action required (blocked). Never keep
iterating past these.>

## Output

<What one pass reports to the user and where: the record appended to the log
path above, plus the Outcome / Review / Next report.>
