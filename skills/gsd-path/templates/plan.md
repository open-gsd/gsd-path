# Plan — <project name>

<!-- Written by the planner role. Executed wave-by-wave by $gsd-path-build. -->

Project verify: `<command that builds + tests the whole project>`
<!-- Run once at ship. A task Verify must not copy this command unless an
     owned INTENT success criterion names it. Otherwise the task Verify
     names a path from that task's files. -->

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

<!-- No task table. Task id, title, deps, and files live only in each
     `tasks/T###-slug.md` frontmatter; `wave: N` there assigns it here. -->

## Wave 2 — walking skeleton

Goal: <the end-to-end slice that runs>
Review depth: <full | deep | verify-only>

<!-- More waves: features by dependency, then polish. Rules:
     - deps only in earlier waves, or same wave with no file overlap
     - no two same-wave tasks share files
     - nothing from INTENT.md scope-out appears anywhere -->

## Surface contract

<!-- Required when INTENT.md `Surfaces:` is not `none`; omit the section
     entirely when it is. One block per declared surface, named exactly as
     INTENT.md names it, owned by the task that delivers it. That task must
     name in Criteria the success criteria this surface is proven by — the
     owning task must own exactly those in its Intent coverage. This is what
     the final reviewer walks before the milestone is called done, and
     FINAL.md records the surface it was walked on. -->

### <surface name as INTENT.md writes it> — T001

Criteria: SC1
Entry: <the route, screen, or command a person opens>
States: <what empty, loading, error, and success each show>
Walkthrough:
1. <step a reviewer performs to see this surface working>

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
