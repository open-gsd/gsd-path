# Plan — <project name>

<!-- Written by the planner role. Executed wave-by-wave by $gsd-path-build. -->

Project verify: `<command that builds + tests the whole project>`

## Config

- max_review_cycles: 3   <!-- review→fix→re-review loops per wave before escalating -->
- wave_budget: none      <!-- none | optional per-wave resource cap: wall-clock,
                             tokens, or cost (e.g. 2h, 500k tokens). Reaching the
                             cap blocks the wave like an exhausted cycle cap and
                             escalates to the user. none is default. -->
- review_panel: off      <!-- off | detected | claude,gpt,grok — optional
                             cross-model panel. off is default. detected uses
                             advertised host families except the parent, cap 3.
                             Named families are an assertion. Quick lane stays
                             off. The planner copies INTENT.md; it does not
                             invent a non-off value. -->

## Wave 1 — risk burn-down

Goal: <what this wave proves; if it fails, what changes>
Review depth: full   <!-- full | deep | verify-only. Wave 1 and auth/payments/
                          data migration/concurrency waves must be full or
                          deep. Assign deep sparingly: irreversible or
                          security-critical merges. -->

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T001 | <title> | — | <paths> |

## Wave 2 — walking skeleton

Goal: <the end-to-end slice that runs>
Review depth: <full | deep | verify-only>

| Task | Title | Deps | Files |
|------|-------|------|-------|
| T00x | <title> | T001 | <paths> |

<!-- More waves: features by dependency, then polish. Rules:
     - deps only in earlier waves, or same wave with no file overlap
     - no two same-wave tasks share files
     - nothing from INTENT.md scope-out appears anywhere -->

## Intent coverage

<!-- Every INTENT.md success criterion, as SCn, maps to at least one task
     acceptance item. The named task's Verify command is what must fail if
     that criterion is skipped. `scripts/check_handoffs.py plan` gates this
     table against INTENT.md and each task's Intent coverage section. -->

| Criterion | Task | Acceptance |
|-----------|------|------------|
| SC1 | T001 | AC1 |

## Dependency notes

<Per non-obvious edge: the exact data or landed effect that makes X precede Y,
and how a reviewer sees it. Narrative order is not a dependency.>
