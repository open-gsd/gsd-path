---
name: gsd-path-synthesize
description: Convert approved GSD Path intent and complete research evidence into settled implementation decisions. Use only when the user explicitly invokes $gsd-path-synthesize or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Synthesis Phase

Dispatch one reasoning-intensive synthesizer and validate its decision artifact.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions

Require `pipeline: gsd-path/v1` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Legal entry is
`research/done` (transition to `synthesize/active`) or
`synthesize/active|blocked`; `synthesize/done` or any later phase blocks rather
than replacing decisions beneath an existing plan. Require
`.project/intent/INTENT.md`, `.project/research/RESEARCH.md`, and every
`evidence-*.md` file named as `dispatched` there. A standard file may be absent
only when the handoff manifest records that dimension as skipped; a missing or
invalid manifest or dispatched file routes to `$gsd-path-research`. Include
every additional `evidence-*.md` file present only when the manifest names it.

## Process

1. Read the local [synthesis template](templates/synthesis.md),
   `.project/research/RESEARCH.md`, and the bundled `scripts/check_handoffs.py`;
   resolve each to an absolute path. Run the research hand-off validator before
   dispatch so synthesis receives a complete, intentional evidence set.
2. Read the local [synthesizer role](references/synthesizer.md), then follow
   the local [runtime dispatch contract](references/dispatch.md) with
   deterministic logical task name `synthesize`. Give it absolute paths to the role,
   `AGENTS.md`, `WORKFLOW.md`, INTENT.md, RESEARCH.md, every evidence file, the
   template, and the required output `.project/research/SYNTHESIS.md`.
3. Validate SYNTHESIS.md. Require one decision block for every genuinely open
   choice in INTENT.md and the evidence, including stack and architecture
   shape plus build-vs-buy when open. A choice already settled by an intent
   constraint or the existing codebase belongs under `## Settled` as one line
   citing the settling source — never a full block with an invented
   runner-up. Require Decision, Runner-up, Evidence, and
   Confidence in every decision block. Require `## For the planner` with wave-1
   blockers, walking skeleton, and pitfall-to-task guidance.
4. If structural validation fails, redispatch one complete corrected brief
   under logical task name `synthesize`, following the runtime dispatch
   contract, and validate again. If it still fails, set STATE.md to
   `phase: synthesize`, `status: blocked`, append the failures to its log, and
   stop.
5. Present the decision list and every `NEEDS-USER` item. Use an interactive
   user-input tool when available; otherwise ask in chat and wait. Present
   each item's options with the evidence-preferred option first, marked
   `(recommended)` and justified in one line; a pure values call with no
   evidence either way carries no recommendation, stated as such. For each
   answer, append the ruling under `## User rulings`, revise every affected
   decision so it reflects the ruling, and only then remove its tag.
6. Re-run the structural gate. When it passes with no unresolved user items,
   set STATE.md to `phase: synthesize`, `status: done`, append the transition
   to its log. When routed by an active `$gsd-path`, return control to that
   router. When invoked directly, stop and tell the user to explicitly invoke
   `$gsd-path` or `$gsd-path-plan`; do not invoke an explicit-only sibling skill
   yourself.

## Rules

- Make commitments, not option lists. Name the runner-up and why it lost
  when a real alternative was weighed; never invent one.
- Cite evidence by file and finding heading for every decision.
- Route low-confidence decisions to wave 1 for verification. Reject uncited
  decisions.
- Resolve evidence conflicts or escalate a true values decision; never average.
