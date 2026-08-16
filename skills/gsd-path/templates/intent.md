# Intent — <project name>

<!-- Written by $gsd-path-define. Every downstream agent reads this first.
     Constraints and vetoes here override everything downstream. -->

Lane: standard   <!-- standard | quick | milestone — quick: at most two
                      deliverable-sized tasks in one wave, no RESEARCH or
                      NEEDS-USER items, no cross-wave risk; set by define at
                      approval. Quick skips research and decide. Milestone:
                      derived from an approved ROADMAP.md entry in a program;
                      research/decide run only when the entry has open
                      questions. -->

Review panel: off   <!-- off | detected | claude,gpt,grok,composer — this
                      milestone's panel setting. In program flow, copy
                      CHARTER.md's durable default and override only when
                      the user says so. off is the default. detected uses
                      advertised host families except the parent, at most 3.
                      Named families are an assertion. Quick lane stays off. -->

## Summary

<3–5 sentences: the problem, who has it, what the first release does. This is the
paragraph the user signed off on — do not edit without a new sign-off.>

## Problem

<What hurts today, for whom, how badly. Evidence if the user gave any.>

## Users

<Who, how many, how technical, what they use today.>

## Success criteria

<!-- Observable statements. The final review checks these one by one. -->
1. <criterion — a thing you can run/measure/see>
2. ...

## Scope: in

<The smallest version that hits the success criteria. Bullet list.>

## Scope: out (vetoes)

<!-- Hard constraints. Nothing in research, plans, or tasks may include these. -->
- <vetoed item> — <user's stated reason, verbatim where possible>

## Constraints

<Stack preferences, deadline, budget, existing code, integrations, compliance.>

## Current state (brownfield only)

<!-- Filled from evidence-codebase.md during brownfield define. Omit the
     section entirely for greenfield projects. -->
- **What exists**: <stack, architecture, maturity in 2–3 sentences>
- **Must not break**: <existing behavior the user ruled protected — these are vetoes>
- **Doc-vs-code rulings**: <each DOCS-AUDIT conflict → user's ruling: fix-doc | fix-code | accept-drift>
- **Ground truth**: `.project/research/evidence-codebase.md`, `.project/research/DOCS-AUDIT.md`

## Risks

<!-- What the user is most unsure about. Research prioritizes these. -->
- <risk>

## Open questions

<!-- Unresolved at define end. Tags: RESEARCH (research phase answers it),
     NEEDS-USER (a human decision, surface at next checkpoint). -->
- [RESEARCH] <question>
- [NEEDS-USER] <question>

## Corrections

<!-- Verbatim user corrections from playback and later phases. Append-only.
     These are the highest-signal intent data in the file. -->
- <date>: "<what the user said>"
