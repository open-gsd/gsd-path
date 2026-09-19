---
name: gsd-path-decide
description: Decide implementation direction from approved intent and complete research evidence, recording settled choices in SYNTHESIS.md. Use only when the user explicitly invokes $gsd-path-decide or an active $gsd-path router explicitly routes to this phase.
---

Before executing project helpers, read [runtime selection](references/runtime-selection.md).

# GSD Path Decide Phase

Dispatch one reasoning-intensive decider and validate its decision artifact.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before dispatch and again before completion, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by decide is resolved in SYNTHESIS.md, or the phase blocks.

## Preconditions

Require `pipeline_state.py validate --repo <absolute root> [--project-dir
.project/next]` to pass; otherwise return to `$gsd-path` for ownership
checking. Legal entry is `research/done` or `decide/active|blocked`. On
`research/done`, enter with `pipeline_state.py transition`, expected
phase/status `research/done`, exact branch and archive values, event `decision
synthesis started`, and set phase/status `decide/active` (plus the same
lookahead project dir); never edit STATE directly. `decide/done` or any later phase blocks rather
than replacing decisions beneath an existing plan. When an active router
supplies the lookahead track root `.project/next/`, evaluate these
preconditions against the track instead; see Lookahead mode. Require
`.project/intent/INTENT.md`, `.project/research/RESEARCH.md`, and every
`evidence-*.md` file named as `dispatched` there. In program flow (CHARTER.md
exists, no milestone INTENT yet) require `.project/CHARTER.md` in INTENT.md's
place. A standard file may be absent
only when the handoff manifest records that dimension as skipped; a missing or
invalid manifest or dispatched file routes to `$gsd-path-research`. Include
every additional `evidence-*.md` file present only when the manifest names it.

Output path: when `.project/CHARTER.md` exists and `.project/ROADMAP.md` does
not, this is program scope — the required output is `.project/SYNTHESIS.md`
at the `.project/` top level; it persists across milestones and never
archives. Otherwise the required output is `.project/research/SYNTHESIS.md`,
which archives with its milestone.

## Lookahead mode

Entered only when an active router supplies the lookahead track root
`.project/next/` while the active STATE.md is `build/active` in program
flow. Evaluate every state and artifact precondition against the track:
`.project/next/STATE.md` is the state file, and INTENT.md, RESEARCH.md, and
the evidence files are read from `.project/next/`. The output is always
milestone scope: `.project/next/research/SYNTHESIS.md` — the program
SYNTHESIS.md already exists at the active `.project/` top level and is
never rewritten here, so the program-scope output-path rule above does not
apply. Run the research hand-off validator with `--project-dir
.project/next`. Dispatch, gates, `NEEDS-USER` handling, and completion
rules are unchanged; never write an active-path artifact.

## Process

1. Read the local [synthesis template](templates/synthesis.md),
   `.project/research/RESEARCH.md`, and the bundled `scripts/check_handoffs.py`;
   resolve each to an absolute path. Run the research hand-off validator before
   dispatch so decide receives a complete, intentional evidence set.
2. Read the local [decider role](references/decider.md), then follow
   the local [runtime dispatch contract](references/dispatch.md) with
   deterministic logical task name `decide`. Give it absolute paths to the role,
   `AGENTS.md`, `WORKFLOW.md`, INTENT.md (or CHARTER.md in program flow),
   RESEARCH.md, every evidence file, the
   template, and the required output path from the Preconditions.
3. Validate SYNTHESIS.md with `python3 <absolute check_handoffs.py> decide
   --repo <absolute root> [--project-dir .project/next]`. Require one decision block for every genuinely open
   choice in INTENT.md and the evidence, including stack and architecture
   shape plus build-vs-buy when open. A choice already settled by an intent
   constraint or the existing codebase belongs under `## Settled` as one line
   citing the settling source — never a full block with an invented
   runner-up. Require Decision, Runner-up, Evidence, and
   Confidence in every decision block. Require `## For the planner` with wave-1
   blockers, walking skeleton, and pitfall-to-task guidance.
4. If structural validation fails, redispatch one complete corrected brief
   under logical task name `decide`, following the runtime dispatch
   contract, and validate again. If it still fails, use
   `pipeline_state.py transition` with expected `decide/active`, exact branch
   and archive values, `--set-status blocked`, and an event naming the failed
   synthesis gate, and
   present **Outcome** with the failed gate, **Review** linking SYNTHESIS.md or
   STATE.md when it is missing, and **Next** naming the one correction or user
   decision required; then stop.
5. Present the decision-list outcome and a Markdown link to the resolved
   absolute SYNTHESIS.md output path before every `NEEDS-USER`
   item. Use an interactive user-input tool when available; otherwise ask in
   chat and wait. Present
   each item's options with the evidence-preferred option first, marked
   `(recommended)` and justified in one line; a pure values call with no
   evidence either way carries no recommendation, stated as such. For each
   answer, append the ruling under `## User rulings`, revise every affected
   decision so it reflects the ruling, and only then remove its tag.
6. Re-run the structural gate. When it passes with no unresolved user items,
   use `pipeline_state.py transition` with expected `decide/active`, exact
   branch and archive values, `--set-phase decide --set-status done`, and an
   event naming the validated synthesis path. Include `--project-dir
   .project/next` in lookahead and require returned `decide/done`. Confirm the
   settled outcome, link SYNTHESIS.md again, and use the executable phase
   handoff in AGENTS.md.

## Rules

- Make commitments, not option lists. Name the runner-up and why it lost
  when a real alternative was weighed; never invent one.
- Cite evidence by file and finding heading for every decision.
- Route low-confidence decisions to wave 1 for verification. Reject uncited
  decisions.
- Resolve evidence conflicts or escalate a true values decision; never average.
