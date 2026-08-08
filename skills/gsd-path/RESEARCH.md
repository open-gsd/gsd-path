---
name: gsd-path-research
description: Dispatch parallel researchers and collect cited GSD Path evidence about domain, stack, pitfalls, and comparable products. Use only when the user explicitly invokes $gsd-path-research or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Research Phase

Dispatch independent researchers and gate their evidence. Keep synthesis out
of this phase. The durable output is a research dispatch manifest plus one
evidence file per dispatched dimension.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

Before dispatch and again before completion, apply AGENTS.md's pending
discussion-answer contract. Resolve an answer owned by research through its
evidence handoff and append a disposition receipt; otherwise block with links
to ANSWERS.md and the target artifact rather than advancing stale evidence.

## Preconditions

Require `pipeline: gsd-path/v1` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Legal entry is
`grill/done` (transition to `research/active`) or `research/active|blocked`;
`research/done` or any later phase blocks rather than replacing settled
evidence beneath downstream artifacts. Require
`.project/intent/INTENT.md`. If it is missing, stop and route to
`$gsd-path-grill`. Confirm live search or web-reading capability before
dispatch; if unavailable, block rather than allowing memory-based citations.

## Dispatch contract

Read the local [researcher role](references/researcher.md), then follow the
local [runtime dispatch contract](references/dispatch.md). Resolve the local
[evidence template](templates/evidence.md), research-handoff template
(`templates/research-handoff.md`), and `scripts/check_handoffs.py` to absolute
paths. Include the role, `AGENTS.md`, `WORKFLOW.md`, INTENT.md, manifest,
dimension, assigned questions, deterministic logical task name
`research_<dimension>`, and exact output path in every brief. When
`evidence-codebase.md` exists, include its absolute path in every brief as
settled brownfield input.

## Process

1. Read INTENT.md. Extract constraints, vetoes, risks, and `RESEARCH`
   questions. Create `.project/research/RESEARCH.md` from the local handoff
   template before dispatch. Record every standard dimension exactly once as
   `dispatched` or `skipped` with a reason, and assign every research question
   to at least one dispatched dimension. No question may remain unassigned.
2. Decide which standard dimensions have work: dispatch a dimension only when
   it has at least one assigned question, an unsettled choice (for example, no
   stack decision yet), or an intent risk to investigate. Skip a dimension
   with nothing to answer — never spawn a researcher to fill a file — and
   record every skipped dimension with its reason in `RESEARCH.md`. The
   standard dimensions:

   | Dimension | Output file | Focus |
   | --- | --- | --- |
   | domain | `evidence-domain.md` | prior art, domain rules, terminology, practitioner expectations |
   | stack | `evidence-stack.md` | two or three viable stacks against the constraints |
   | pitfalls | `evidence-pitfalls.md` | security, scale, reliability, and UX failure modes |
   | similar | `evidence-similar.md` | comparable products and reusable lessons |

   Dispatch up to the available child capacity, then dispatch each remaining
   dimension when a slot opens. Keep all briefs independent. A custom fifth
   dimension supplements at least one dispatched standard dimension; it never
   replaces the standard set.

   In brownfield work, require stack research to weigh migration cost and
   pitfalls research to check which failure modes already exist in the mapped
   codebase.

3. If a risk needs a distinct dimension, add one researcher, up to five total.
   Derive its filename deterministically as `evidence-<dimension-slug>.md`:
   lowercase the label, replace non-alphanumeric runs with one hyphen, and
   trim hyphens. Append `-2` only if it collides with an existing dimension.
4. Validate every dispatched evidence file after all agents finish. Confirm
   every extracted `RESEARCH` question was assigned and answered. Require at
   least one `## Finding`, and require Claim, Source, Confidence, and Why it
   matters fields for every finding. Then run:

   `python3 <absolute check_handoffs.py> research --repo <absolute repo root>`

   The manifest is the source of truth for dispatched and skipped dimensions;
   the STATE log records only a human-readable summary.
5. Redispatch one complete corrected brief under the same logical task name for
   each missing or invalid file, following the runtime dispatch contract. If
   any expected file still fails, set STATE.md to `phase: research`, `status:
   blocked`, list the failures in the log, then present **Outcome** with the
   failed gate, **Review** linking RESEARCH.md or STATE.md when the manifest is
   missing, and **Next** naming the one correction or user decision required.
   Stop; never advance with partial research.
6. When all dispatched files and `RESEARCH.md` pass, set STATE.md to
   `phase: research`, `status: done`, and append a transition log naming the
   manifest path, dispatched dimensions, skipped dimensions, and question
   count. Report the outcome, link the resolved absolute `RESEARCH.md` path,
   summarize the dispatched evidence files, and name synthesis as next.
   Synthesis reads the manifest; it must not infer dispatch state from a glob
   or free-form log. When routed by an active
   `$gsd-path`, return control to that router. When invoked directly, stop and
   tell the user to explicitly invoke `$gsd-path` or `$gsd-path-synthesize`;
   do not invoke an explicit-only sibling skill yourself.

## Rules

- Require evidence, not opinion: every claim needs a source actually checked
  and a one-line tie-back to this project's intent.
- Record conflicting sources rather than resolving them here.
- Preserve dead ends and explicit `no reliable source found` answers.
- Do not summarize the evidence; `$gsd-path-synthesize` owns that work.
