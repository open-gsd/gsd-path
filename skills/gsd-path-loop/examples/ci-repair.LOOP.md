# LOOP — ci-repair

<!-- Dogfood spec for the gsd-path distribution repo itself. One pass repairs
     a failing CI trio: pytest, the node installer tests, and the resource
     sync check. Invoke from the repository root. -->

loop: ci-repair
status: active
trigger: manual
cooldown: 10m
verify: python3 -m pytest tests/ -q
verify: node --test tests/install.test.mjs tests/package.test.mjs
verify: python3 scripts/sync_skill_resources.py --check
max_iterations: 3
wall_clock: 30m
period: 24h
period_budget: 4h
log: .project/loop/ci-repair.LOG.jsonl

## Goal

The three verifier commands above all exit 0 — the same trio
`.github/workflows/ci.yml` runs. Anything less is a failure, not a partial
success.

## Worker scope

One fix worker repairs the failing test, installer check, or sync drift at
its root cause. The worker must never: commit, push, or tag; edit a test to
match broken product code; edit generated per-skill copies under
`skills/gsd-path-*/{references,templates,scripts}/` instead of their
canonical sources (`skills/gsd-path/` and `scripts/`); or touch files outside
the failing unit's blast radius.

## Feedback route

On a failed verify, the worker gets the exact failing command and its output
tail from `loop_run.py verify`, aimed at the smallest failed unit — the one
failing test file, installer assertion, or sync mismatch — not the whole
suite.

## Human gates

- Any commit, push, or tag.
- Weakening, deleting, or skipping a test or verifier to reach green.
- Editing a canonical template/reference and its generated copies in
  conflicting directions (sync's wrong-direction-edit warning).
- Changing CI itself (`.github/workflows/ci.yml`).

## Stops

- `pass` — all three verify commands exit 0.
- `fail` — max_iterations or the 30m wall_clock budget is spent.
- `blocked` — the only remaining fix needs a human-gate action; report
  `BLOCKED: <reason>` and stop.

## Output

One JSON record appended to `.project/loop/ci-repair.LOG.jsonl` via
`loop_run.py record`, then the Outcome / Review / Next report naming the
verify result, iterations used, and the log path.
