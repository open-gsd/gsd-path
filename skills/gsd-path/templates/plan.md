# Plan — <project name>

<!-- Written by the planner role. Executed wave-by-wave by $gsd-path-build. -->

Project verify: `<command that builds + tests the whole project>`

## Config

- max_review_cycles: 3   <!-- review→fix→re-review loops per wave before escalating -->

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

## Dependency notes

<Per non-obvious edge: the exact data or landed effect that makes X precede Y,
and how a reviewer sees it. Narrative order is not a dependency.>
