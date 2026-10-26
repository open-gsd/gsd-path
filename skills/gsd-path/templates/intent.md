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

Review panel: off   <!-- off | detected | claude,gpt,grok,composer,gemini,deepseek,kimi,qwen — this
                      milestone's panel setting. In program flow, copy
                      CHARTER.md's durable default and override only when
                      the user says so. off is the default. detected uses
                      advertised host families except the parent, at most 3.
                      Named families are an assertion, at most 3. Quick
                      lane stays off. -->

Finding skeptics: off   <!-- off | on — build spawns one read-only skeptic
                      per blocking deep-review finding before fix tasks
                      are opened; a refuted finding spawns no fix task unless
                      the user explicitly overrides all cycle refutations.
                      off is the default. Quick lane stays off. -->

Surfaces: none   <!-- none | comma-separated list of the human-facing
                      surfaces this milestone delivers: a web app, a CLI, an
                      HTTP API. Anything a person opens, sees, or types into
                      is a surface. Use none only when nobody touches this
                      work directly — a library, a migration, internals.
                      Every named surface needs a success criterion
                      observable there and a PLAN.md Surface contract. -->

## Summary

<3–5 sentences: the problem, who has it, what the first release does. This is the
paragraph the user signed off on — do not edit without a new sign-off.>

## Problem

<What hurts today, for whom, how badly. Evidence if the user gave any.>

## Users

<Who, how many, how technical, what they use today.>

## Success criteria

<!-- Observable statements, numbered from 1. PLAN.md maps each to a task
     AC and Verify as SC1, SC2, …. Wave review checks the SCs a wave owns.
     Final review checks every SC.
     Every surface named above needs at least one criterion a person can
     observe at that surface — a screen reached, an output seen — never a
     passing test standing in for the experience. -->
1. <criterion — a thing you can run/measure/see>
2. ...

## Edge coverage

<!-- Written by define's edge probe (references/spec-probes.md). Walk every
     success criterion; each applicable edge gets one row ruled by the user.
     Disposition: criterion SCn (stated in that criterion) | held-out (a named
     test pins the ruling written in Detail) | dismissed (Detail says why the
     edge cannot occur). Every SCn appears at least once; a criterion with no
     data shape gets category none, dismissed. Categories: boundary,
     adjacency, empty, encoding, ordering, precision, idempotency,
     concurrency, none. `check_handoffs.py intent` gates this table. -->

| Edge | Criterion | Category | Disposition | Detail |
|------|-----------|----------|-------------|--------|
| E1 | SC1 | <category> | <disposition> | <ruling, examples, or dismissal reason> |

## Prohibitions

<!-- Written by define's prohibition probe. What each criterion must never
     silently become: values, safety, privacy, fairness, transparency. Not
     routine engineering, not generic security canon.
     Disposition: criterion SCn (checkable; stated in that criterion) |
     judgment (final reviewer judges it; Detail says what to look for) |
     dismissed. A single row with Criterion `all`, Must not `none`, and
     disposition dismissed, and no other row, records work that affects no
     person directly. -->

| Prohibition | Criterion | Must not | Disposition | Detail |
|-------------|-----------|----------|-------------|--------|
| N1 | SC1 | <what it must never become> | <disposition> | <what the reviewer looks for, or why dismissed> |

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
- **Ground truth**: `<track>/research/evidence-codebase.md`, `<track>/research/DOCS-AUDIT.md`

## Risks

<!-- What the user is most unsure about. Research prioritizes these. -->
- <risk>

## Open questions

<!-- Unresolved at define end. Tags: RESEARCH (research phase answers it),
     NEEDS-USER (a human decision, surface at next checkpoint). -->
- [RESEARCH] <question>
- [NEEDS-USER] <question>

## Corrections

<!-- Verbatim user corrections from playback and later phases. Append-only,
     numbered from C1: the id gives a correction citable identity — wave
     dispositions and scope exclusions authorize through it. These are the
     highest-signal intent data in the file. -->
- C1 <YYYY-MM-DD>: "<what the user said>"
