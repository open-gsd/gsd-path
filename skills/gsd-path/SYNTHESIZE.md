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
`.project/intent/INTENT.md` and all four standard evidence files:
`evidence-domain.md`, `evidence-stack.md`, `evidence-pitfalls.md`, and
`evidence-similar.md`. Include every additional `evidence-*.md` file present.
If a standard file is missing or invalid, route to `$gsd-path-research`.

## Process

1. Read the local [synthesis template](templates/synthesis.md) and
   resolve it to an absolute path.
2. Read the local [synthesizer role](references/synthesizer.md), then follow
   the shared [Codex dispatch contract](references/dispatch.md) with built-in
   `agent_type: default`, `fork_turns: "none"`, and deterministic
   `task_name: synthesize`. Give it absolute paths to the role,
   INTENT.md, every evidence file, the template, and the required output
   `.project/research/SYNTHESIS.md`.
3. Validate SYNTHESIS.md. Require one decision block for every open choice in
   INTENT.md and the evidence, including stack and architecture shape plus
   build-vs-buy where applicable. Require Decision, Runner-up, Evidence, and
   Confidence in every block. Require `## For the planner` with wave-1
   blockers, walking skeleton, and pitfall-to-task guidance.
4. If structural validation fails, send one specific corrective follow-up to
   the same agent and validate again. If it still fails, set STATE.md to
   `phase: synthesize`, `status: blocked`, append the failures to its log, and
   stop.
5. Present the decision list and every `NEEDS-USER` item. Use an interactive
   user-input tool when available; otherwise ask in chat and wait. For each
   answer, append the ruling under `## User rulings`, revise every affected
   decision so it reflects the ruling, and only then remove its tag.
6. Re-run the structural gate. When it passes with no unresolved user items,
   set STATE.md to `phase: synthesize`, `status: done`, append the transition
   to its log. When routed by an active `$gsd-path`, return control to that
   router. When invoked directly, stop and tell the user to explicitly invoke
   `$gsd-path` or `$gsd-path-plan`; do not invoke an explicit-only sibling skill
   yourself.

## Rules

- Make commitments, not option lists. Name the runner-up and why it lost.
- Cite evidence by file and finding heading for every decision.
- Route low-confidence decisions to wave 1 for verification. Reject uncited
  decisions.
- Resolve evidence conflicts or escalate a true values decision; never average.
