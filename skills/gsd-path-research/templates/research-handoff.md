# Research Handoff

<!-- Written by the research orchestrator and consumed by decide. -->

Phase: research
Status: complete
Intent: `.project/intent/INTENT.md`
<!-- Program flow (no milestone INTENT exists): write the Intent line as
     `.project/CHARTER.md` instead — the validator accepts exactly one of the
     two paths, matching the file that actually exists. -->

## Dispatch

<!-- Include every standard dimension exactly once. A custom dimension may
     supplement these rows, never replace a standard row. -->
- `domain` — dispatched → `.project/research/evidence-domain.md` — <why this dimension ran>
- `stack` — dispatched → `.project/research/evidence-stack.md` — <why this dimension ran>
- `pitfalls` — skipped → none — <why this dimension was skipped>
- `similar` — skipped → none — <why this dimension was skipped>

## Question assignments

<!-- Copy every [RESEARCH] question from INTENT.md exactly once. Assign one or
     more dispatched dimensions on that row, each in its own code span and
     separated by commas. Every dispatched dimension must receive a question
     and answer all its assigned questions in its evidence file. Use `- none`
     only when INTENT.md has no [RESEARCH] questions. -->
- `[RESEARCH] <question copied from INTENT.md>` → `domain`, `stack`
