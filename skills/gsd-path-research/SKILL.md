---
name: gsd-path-research
description: Dispatch parallel researchers and collect cited GSD Path evidence about domain, stack, pitfalls, and comparable products. Use only when the user explicitly invokes $gsd-path-research or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Research Phase

Dispatch independent researchers and gate their evidence. Keep synthesis out
of this phase. The durable output is a research dispatch manifest plus one
evidence file per dispatched dimension.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before dispatch and again before completion, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by research is resolved through its evidence handoff, or
the phase blocks.

## Preconditions

Require `pipeline_state.py validate --repo <absolute root> [--project-dir
.project/next]` to pass; otherwise return to `$gsd-path` for ownership
checking. Legal entry is `define/done` or `research/active|blocked`. On
`define/done`, enter with `pipeline_state.py transition`, expected phase/status
`define/done`, exact branch and archive values, event `research started`, and
set phase/status `research/active` (plus the same `--project-dir` in
lookahead); never edit STATE directly. `research/done`
`research/done` or any later phase blocks rather than replacing settled
evidence beneath downstream artifacts. When an active router supplies the
lookahead track root `.project/next/`, evaluate these preconditions against
the track instead; see Lookahead mode. Require
`.project/intent/INTENT.md` — or, in program flow, `.project/CHARTER.md` when
the router dispatched program-scope research before any milestone INTENT
exists. If neither exists, stop and route to
`$gsd-path-define`. Confirm live search or web-reading capability before
dispatch; if unavailable, block rather than allowing memory-based citations.

Program scope: when working from CHARTER.md, dimensions decompose the full
charter scope, not one milestone. Add program dimensions such as
`domain-decomposition` (capability areas and their boundaries) and
`capability-map` (what exists vs. what must be built) as custom dimensions
alongside the standard set, so the roadmap phase inherits a complete scope
map. The manifest's `Intent:` line names `.project/CHARTER.md` in this flow.

## Lookahead mode

Entered only when an active router supplies the lookahead track root
`.project/next/` while the active STATE.md is `build/active` in program
flow. Evaluate every state and artifact precondition against the track:
`.project/next/STATE.md` is the state file, INTENT.md is
`.project/next/intent/INTENT.md`, and the manifest and evidence files live
under `.project/next/research/`. Program-level inputs (CHARTER.md,
ROADMAP.md, top-level SYNTHESIS.md) are read from their active `.project/`
paths. Brownfield input is the track's
`.project/next/research/evidence-codebase.md` after lookahead inspect;
do not substitute the building milestone's map. Archived evidence from
earlier milestones uses the same archived-manifest rule as the roadmap
phase. Validate the handoff with
`python3 <absolute check_handoffs.py> research --repo <absolute repo root>
--project-dir .project/next`. Dispatch, gates, and completion rules are
unchanged; never write an active-path artifact.

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

1. Read INTENT.md — or CHARTER.md in program flow. Extract constraints,
   vetoes, risks, and `RESEARCH`
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
   dimension when a slot opens. A pending corrected redispatch takes the slot
   before any queued not-yet-dispatched dimension. Keep all briefs independent.
   A custom fifth dimension supplements at least one dispatched standard
   dimension; it never replaces the standard set.

   In brownfield work, require stack research to weigh migration cost and
   pitfalls research to check which failure modes already exist in the mapped
   codebase.

3. If a risk needs a distinct dimension, add one researcher, up to five total
   (project policy).
   Derive its filename deterministically as `evidence-<dimension-slug>.md`:
   lowercase the label, replace non-alphanumeric runs with one hyphen, and
   trim hyphens. Append `-2` only if it collides with an existing dimension.
4. Validate each dispatched evidence file as its researcher returns. Require
   at least one `## Finding` — a documented `no reliable source found` null
   result recorded as a finding satisfies this gate, with the searches that
   came up empty noted as its evidence — require Claim, Source, Confidence,
   and Why it matters fields for every finding, and require an answer for
   every question assigned to that dimension. For a missing or invalid file,
   redispatch one complete corrected brief under the same logical task name,
   following the runtime dispatch contract, as soon as a child slot allows —
   never held until the remaining dimensions settle.
5. After every dimension settles — validated, or its one corrected
   redispatch collected — confirm every extracted `RESEARCH` question was
   assigned to a dispatched dimension. Then run:

   `python3 <absolute check_handoffs.py> research --repo <absolute repo root>`

   The manifest is the source of truth for dispatched and skipped dimensions;
   the STATE log records only a human-readable summary.
   If any expected file still fails after its one corrected redispatch,
   run `pipeline_state.py transition` with
   expected `research/active`, exact branch and archive values,
   `--set-status blocked`, and an event listing the failed evidence gate; then
   present **Outcome** with the
   failed gate, **Review** linking RESEARCH.md or STATE.md when the manifest is
   missing, and **Next** naming the one correction or user decision required.
   Stop; never advance with partial research.
6. When all dispatched files and `RESEARCH.md` pass, run
   `pipeline_state.py transition` with expected `research/active`, exact
   branch and archive values, `--set-phase research --set-status done`, and
   an event naming the manifest path, dispatched dimensions, skipped
   dimensions, and question count. Include `--project-dir .project/next` for
   lookahead. Require the returned state to be `research/done`. Report the
   outcome, link the resolved absolute `RESEARCH.md` path,
   summarize the dispatched evidence files, and name the decide phase as next.
   The decide phase reads the manifest; it must not infer dispatch state from
   a glob or free-form log. When routed by an active
   `$gsd-path`, return control to that router. When invoked directly, stop and
   tell the user to explicitly invoke `$gsd-path`, which routes to decide; do
   not invoke an explicit-only sibling skill yourself.

## Rules

- Require evidence, not opinion: every claim needs a source actually checked
  and a one-line tie-back to this project's intent.
- Record conflicting sources rather than resolving them here.
- Preserve dead ends and explicit `no reliable source found` answers.
- Do not summarize the evidence; `$gsd-path-decide` owns that work.
