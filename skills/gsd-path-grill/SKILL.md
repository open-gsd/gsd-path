---
name: gsd-path-grill
description: Interview the user and turn an idea into an approved .project/intent/INTENT.md. Use only when the user explicitly invokes $gsd-path-grill or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Grill Session

Turn a vague idea into `.project/intent/INTENT.md`. Run this phase in the
main conversation; never delegate the interview.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## State ownership

If STATE.md exists, require `pipeline: gsd-path/v1`; a missing or different
marker returns to `$gsd-path` for ownership checking. Legal existing-state
entry is `onboard/done` (transition to `grill/active`) or
`grill/active|blocked`. `grill/done` or any later phase blocks rather than
overwriting approved intent and leaving downstream artifacts stale. If
STATE.md is missing and `.project/` contains any artifact, return to
`$gsd-path` for orphaned-state recovery; existing evidence does not prove its
pipeline version or phase and must not be reused or overwritten by inference.
Otherwise perform the router's brownfield detection before interviewing. Any
brownfield signal routes to `$gsd-path-onboard`. Only a greenfield directory
may initialize STATE.md directly from the local
[state template](templates/state.md), with a deterministic project slug from
the working-directory name, `pipeline: gsd-path/v1`, `phase: grill`,
`status: active`, `milestone: null`, `branch: null`, `archive: null`, and an
initialization Log entry. No template placeholder may remain.

## Coverage checklist

Obtain a confident answer in every area before finishing:

1. **Problem** — what hurts, for whom, and how badly.
2. **Users** — who uses this, how many, how technical, and what they use now.
3. **Success** — what observable result makes the first release complete.
4. **Scope in** — the smallest version that achieves that result.
5. **Scope out** — explicit vetoes that downstream phases must not include.
6. **Constraints** — stack, deadline, budget, code, integrations, compliance.
7. **Risks** — the assumptions and unknowns research must investigate.

## Brownfield mode

When `.project/research/evidence-codebase.md` exists (the router ran
`$gsd-path-onboard`), read it and `.project/research/DOCS-AUDIT.md` before the
first question. The rules change:

- Established facts are not questions. Never ask what the stack is or what
  the code does — the map answers that. State it and let the user correct.
- The interview centers on deltas: what should change, what must not break,
  and the goal of THIS milestone against the code that already exists.
- Work through the mapper's `## Open questions for the grill` and the
  audit's `NEEDS-USER` remediation rows — each doc-vs-code conflict gets a
  ruling (`fix-doc`, `fix-code`, or `accept-drift`) recorded verbatim in
  INTENT.md and appended to DOCS-AUDIT.md's `## User rulings` table.
  `fix-doc` and `fix-code` rows receive `planned: no`; `accept-drift` receives
  `planned: n/a (accept-drift)`. Never leave the durable alignment queue only
  in INTENT.md.
- Existing behavior the user wants preserved is recorded under Scope out as
  a veto ("do not break X"); accepted `fix-code` items become scope.
- Fill INTENT.md's `## Current state` from the codebase map so downstream
  phases inherit ground truth without re-scanning.

## Process

1. Ask for a one-paragraph idea description if the user has not supplied one.
   In brownfield mode, instead present the one-screen ground truth (from
   onboarding) and ask what this milestone should achieve.
2. Ask rounds of two or three questions aimed at the weakest checklist areas.
   Use an interactive user-input tool when available. Otherwise ask concise
   numbered questions in chat and stop for the reply. Never send more than
   three questions in one round.
3. Surface contradictions immediately and ask the user to choose. Never
   average incompatible answers.
4. Challenge the largest assumption at least once: ask what happens if it is
   false.
5. Stop when coverage is complete or the user says `enough`. Record remaining
   uncertainty under `## Open questions` with `RESEARCH` or `NEEDS-USER`.
6. Read the local [intent template](templates/intent.md), draft
   `.project/intent/INTENT.md`, show the Summary section, and obtain explicit
   approval. Record corrections verbatim under `## Corrections` before asking
   again.

## Output contract

After approval, finalize `.project/intent/INTENT.md` and update STATE.md to
`phase: grill`, `status: done`, set its `milestone` field to this
milestone's slug, and append the transition to its log. Report
that research is next. When routed by an active `$gsd-path`, return control to
that router so its bundled research contract can auto-advance. When invoked
directly, stop and tell the user to explicitly invoke `$gsd-path` or
`$gsd-path-research`; do not invoke an explicit-only sibling skill yourself.

## Rules

- Trace every question to a checklist gap; omit curiosity questions.
- Treat solution-shaped problems as hypotheses and uncover the underlying pain.
- Preserve vetoes and corrections verbatim.
- Aim for three to five rounds. After six, wrap up and tag remaining gaps.
