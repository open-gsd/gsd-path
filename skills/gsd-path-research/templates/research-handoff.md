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
- `stack` — skipped → none — <why this dimension was skipped>
- `pitfalls` — skipped → none — <why this dimension was skipped>
- `similar` — skipped → none — <why this dimension was skipped>

## Question assignments

<!-- Copy every [RESEARCH] question from INTENT.md exactly once. Use `- none`
     only when INTENT.md has no [RESEARCH] questions. The question is a
     CommonMark code span: choose a fence length not used by a backtick run in
     the question (a longer fence is usually easiest), with one space of
     padding on each side. For example:
     - `` [RESEARCH] Does `Widget` match the pinned `sample.json` fixture? `` → `domain`
     A question that ends in a backtick also needs padding, as in:
     - `` [RESEARCH] Does the label end with `Widget`?` `` → `domain`
     After removing the fence and CommonMark padding, the text must equal the
     INTENT question exactly. -->
- `[RESEARCH] <question copied from INTENT.md>` → `domain`
