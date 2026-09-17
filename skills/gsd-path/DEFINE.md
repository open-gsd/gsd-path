---
name: gsd-path-define
description: Define and approve project or milestone intent through an interview or milestone confirmation, writing .project/CHARTER.md or .project/intent/INTENT.md. Use only when the user explicitly invokes $gsd-path-define or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Define Phase

Turn a project idea or approved roadmap entry into an approved intent artifact.
Run this phase in the main conversation; never delegate its interview or
confirmation.

Primary modes: **standard** (single milestone, below), **program** (a
multi-milestone program — interview into `.project/CHARTER.md`), and
**milestone** (derive one milestone's INTENT.md from the approved roadmap; no
re-interview). Modifiers: **brownfield** when the track's
`research/evidence-codebase.md` exists, and **supplied-spec** when the user
hands in a PRD, issue, or design doc. Apply every matching modifier on top of
the primary mode.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before interview work and again before approval, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by define is resolved in INTENT.md, or the phase blocks.

## State ownership

If STATE.md exists, require `pipeline_state.py validate --repo <absolute root>
[--project-dir .project/next]` to pass; otherwise return to `$gsd-path` for
ownership checking. Legal existing-state
entry is `inspect/done` (transition to `define/active`; milestone mode when
ROADMAP.md exists), `roadmap/done`
(transition to `define/active`, milestone mode), or
`define/active|blocked`. When ROADMAP.md exists, a later milestone or
lookahead track at `define/active|blocked` also requires both current-track
inspection artifacts and a Log entry proving `inspect/done` for the same
milestone after its latest activation; otherwise route to inspect.
The sole later-phase exception is a blocked build entered through the
[build recovery contract](references/build-recovery.md). Follow its preparation
and corrections procedure when the runtime returns mode `corrections`; keep
the existing milestone identity and approval gate. Otherwise
`define/done` or any later phase blocks rather than overwriting approved
intent and leaving downstream artifacts stale. When an active router supplies
the lookahead track root `.project/next/`, require its STATE.md to be a regular
non-symlink file and evaluate this section against that track's state and
paths; see Lookahead mode. If STATE.md is missing, run the bundled
`python3 <absolute-bundled-script> initialize --repo <absolute-root>
--template <absolute-state-template>` helper (`scripts/detect_project.py`) and
follow its returned JSON `verdict` / `route`. This is the only no-state
boundary; do not run `classify` first or classify from a directory listing or
conversation. If the command exits nonzero, returns `error`, or returns
`wrote_state: false`, report the error and block without routing or claiming
STATE.md was written.
- `owned` — continue under the existing-state rules above.
- `orphan` — return to `$gsd-path` for orphaned-state recovery; existing
  evidence does not prove its pipeline version or phase and must not be reused
  or overwritten by inference.
- `brownfield` — the helper writes STATE.md at `inspect/active`; route to
  `$gsd-path-inspect` from this returned verdict.
- `greenfield` — require `wrote_state: true`, then continue with the helper's
  STATE.md at `define/active`. Do not create STATE.md yourself.

Enter from `inspect/done` or `roadmap/done` only with `pipeline_state.py
transition`: pass the exact expected phase/status/branch/archive values, event
`definition started`, and `--set-phase define --set-status active` (plus
`--project-dir .project/next` for lookahead). This helper is the only ordinary
STATE mutation; direct template writing is limited to the missing-state
greenfield initialization above.

The router's verified new-GitHub-repository transaction is the sole greenfield
exception: STATE.md already exists at `define/active`, `branch` is the approved
`gsd-path/M001` branch, and `.project/REPOSITORY.md` contains the
fixed-format remote, remote-default SHA, clean default checkout, branch, and
primary worktree. Verify that artifact and the current branch/worktree before
interviewing. The required classifier returns `owned` before signal scanning,
so the bootstrap README is not a brownfield signal. A missing or mismatched binding
returns to `$gsd-path`; never infer it from STATE log prose or repair it
inside define.

## Coverage checklist

Obtain a confident answer in every area before finishing:

1. **Problem** — what hurts, for whom, and how badly.
2. **Users** — who uses this, how many, how technical, and what they use now.
3. **Success** — what observable result makes the first release complete.
4. **Scope in** — the smallest version that achieves that result.
5. **Scope out** — explicit vetoes that downstream phases must not include.
6. **Constraints** — stack, deadline, budget, code, integrations, compliance.
7. **Risks** — the assumptions and unknowns research must investigate.
8. **Surfaces** — what a person opens, sees, or types into to get the
   result: screens, commands, endpoints. Record them on INTENT.md
   `Surfaces:` (`none` only when nobody touches this work directly), and
   give every named surface at least one success criterion observable
   there. A criterion satisfied by a passing test alone does not cover a
   surface.

## Program mode

When the user frames the work as a large multi-milestone program — or the
interview reveals scope that cannot ship as one milestone — interview against
the charter instead of the single-milestone checklist:

1. **Vision** — the program's end state and why it matters.
2. **Full scope in** — every capability area the program will deliver.
3. **Vetoes** — what no milestone may include.
4. **Constraints** — program-level stack, budget, deadline, integrations.
5. **Program success criteria** — observable when the last milestone ships.
6. **Review panel** — optional durable default (`off` | `detected` | named
   families). Default `off`. This value persists on CHARTER.md; later
   milestone INTENT files copy it and may override.

Read the local [charter template](templates/charter.md), write the approval
draft to `.project/CHARTER.md` including `Review panel:` (default `off`;
never invent `detected` or a named list), and run the same playback-approval
loop as the standard Process. On approval, retain the reviewed
`Review panel:` value on CHARTER.md, run `pipeline_state.py transition` with
expected `define/active`, milestone/branch/archive all at their exact current
values, event `program charter approved`, and `--set-phase define --set-status
done`; require milestone to remain null. Report that research (program
scope) is next. Research, decide, and the roadmap phase slice the program;
per-milestone INTENT.md files come later, in milestone mode. Do not write
INTENT.md in program mode.

## Milestone mode

Legal entry: `roadmap/done` only for the first milestone after initial roadmap
approval, or `inspect/done` when `.project/ROADMAP.md` exists. Recovery from
`define/active|blocked` follows the current inspection-evidence requirement in
State ownership. There is no re-interview of charter or roadmap scope:
1. Read the applicable track STATE.md, `.project/CHARTER.md`, and
   `.project/ROADMAP.md`. Select the entry whose slug matches `STATE.milestone`.
   Require exactly one match. In ordinary milestone mode,
   require that entry to be `active`; in lookahead mode, require it to be
   `pending`. A missing, duplicate, or wrong-status match blocks: record the
   failure in the applicable STATE.md and return to the router. When
   brownfield, also read the track's
   `research/evidence-codebase.md` and `research/DOCS-AUDIT.md` first.
2. Draft INTENT.md from the resolved entry: Summary from its Goal, Scope
   in/out and Success criteria from the entry, Constraints inherited from the charter,
   Risks and Open questions from the entry (tagged `RESEARCH`/`NEEDS-USER`),
   `Lane: milestone`, `Surfaces:` copied verbatim from the entry, and
   `Review panel:` copied from CHARTER.md (default
   `off` when CHARTER omits it). The confirmation may override the copied
   panel value; do not invent `detected` or a named list. When brownfield,
   fill `## Current state` from the map, record doc-vs-code rulings as in
   Brownfield mode, and add protected existing behavior under Scope out.
   Write Ground truth paths from the track root: `.project` normally, or
   `.project/next` in Lookahead mode — never the building milestone's
   active `research/` paths.
3. Present one confirmation, not an interview: playback the derivation (and
   brownfield ground truth when present), link the resolved absolute INTENT.md
   path, and ask approve or adjust. A requested change that contradicts the
   charter or the resolved roadmap entry is a scope change — this phase never
   edits the roadmap; surface it to the user for a `$gsd-path-roadmap` re-slice
   at the next milestone boundary.
4. On approval, finalize per the Output contract, setting `milestone` to the
   resolved entry's slug. The router continues with milestone-scoped research
   when the entry lists open questions, otherwise planning.

## Lookahead mode

Entered only when an active router supplies the lookahead track root
`.project/next/` while the active STATE.md is `build/active` in program
flow. Evaluate every state and artifact precondition in this contract
against the track — `.project/next/STATE.md` is the state file and
INTENT.md is `.project/next/intent/INTENT.md` — never against active-path
artifacts. This is milestone mode run against the track, with two
differences:

- Read CHARTER.md and ROADMAP.md from their active `.project/` paths, but
  resolve the milestone only from `.project/next/STATE.md` as described above;
  never use the building milestone's `active` entry and never create or modify
  any active-path artifact.
- Never mark the lookahead milestone's roadmap entry `active`; the router
  does that at promotion.

All other milestone-mode rules apply unchanged. Brownfield evidence for
this track is `.project/next/research/evidence-codebase.md`.

## Supplied-spec mode

When the user supplies a document at entry — a PRD, issue, or design doc —
read it fully before the first question and map it against the coverage
checklist. Present what the document settles per checklist area for
correction — stated, not asked, exactly like brownfield ground truth — then
interview only the gaps and contradictions. Note the source document path in
INTENT.md's Summary. A supplied spec composes with brownfield mode: ground
truth first, then the spec, then delta questions only.

## Brownfield mode

When the track's `research/evidence-codebase.md` exists (inspect already
ran), read it and the matching `research/DOCS-AUDIT.md` before the first
question. The rules change for every primary mode:

- Established facts are not questions. Never ask what the stack is or what
  the code does — the map answers that. State it and let the user correct.
- Standard and program interviews cover only deltas: what should change, what
  must not break, and — standard — the goal of THIS milestone against the
  code that already exists. Program interviews still use the charter
  checklist, but skip any area the map already settled.
- Milestone mode still does not re-interview; it still collects the rulings
  below before confirmation.
- Work through the mapper's `## Open questions for define` and the
  audit's `NEEDS-USER` remediation rows — each doc-vs-code conflict gets a
  ruling (`fix-doc`, `fix-code`, or `accept-drift`) recorded verbatim in
  INTENT.md and appended to DOCS-AUDIT.md's `## User rulings` table.
  `fix-doc` and `fix-code` rows receive `planned: no`; `accept-drift` receives
  `planned: n/a (accept-drift)`. Never leave the durable alignment queue only
  in INTENT.md. Program mode records those rulings on CHARTER.md Constraints
  or Corrections and still writes the DOCS-AUDIT.md table.
- Existing behavior the user wants preserved is recorded under Scope out as
  a veto ("do not break X"); accepted `fix-code` items become scope.
- Fill INTENT.md's `## Current state` from the codebase map so downstream
  phases inherit ground truth without re-scanning. Set Ground truth to the
  track's `research/evidence-codebase.md` and `research/DOCS-AUDIT.md`
  (`.project/next/research/` in Lookahead mode). Omit that section for
  greenfield. Do not add it to CHARTER.md.

## Process

1. Open in this order, then stop for the reply:
   - **Brownfield (any primary):** present the one-screen ground truth from
     inspect before any question.
   - **Standard, no brownfield:** ask for a one-paragraph idea if missing.
   - **Program, no brownfield:** ask for the program vision if missing.
   - **Milestone:** do not ask for an idea; continue at Milestone mode
     (ground truth already presented when brownfield).
   - **Supplied spec:** after the opening above, present settled coverage
     for correction, then interview only its gaps.
   - **Standard + brownfield:** after ground truth, ask what this milestone
     should achieve against the code that exists.
2. For standard and program modes, ask small rounds of questions aimed at the
   weakest checklist areas that the opening did not already settle. Never ask
   a fact the map, audit, or supplied spec already answered. Use an
   interactive user-input tool when available. Otherwise ask concise numbered
   questions in chat and stop for the reply. Keep each round small enough to
   answer in one reply. When a question offers options, list the recommended
   one first marked `(recommended)` with a one-line reason; leave open
   questions open. Milestone mode skips this step; collect brownfield rulings
   if brownfield, then use the Milestone mode confirmation.
3. Surface contradictions immediately and ask the user to choose. Never
   average incompatible answers.
4. In standard and program modes, challenge the largest remaining assumption
   at least once: ask what happens if it is false. Do not challenge a fact
   the brownfield map already established. Milestone mode skips this step.
5. Stop when coverage is complete or the user says `enough`. Record remaining
   uncertainty under `## Open questions` with `RESEARCH` or `NEEDS-USER`.
6. Classify the proposed milestone lane before writing the approval draft.
   Milestone mode keeps `Lane: milestone` and skips this classification.
   Program mode writes CHARTER.md instead of INTENT.md. Otherwise choose
   `quick` when scope fits at most two deliverable-sized tasks (project
   policy) in one wave with
   no `RESEARCH` or `NEEDS-USER` items and no cross-wave integration risk;
   otherwise `standard`. Read the local [intent template](templates/intent.md),
   write that proposed lane and the complete draft to
   `.project/intent/INTENT.md`, then ask for approval. Present an
   **Outcome** playback of the Summary and proposed lane, a **Review** Markdown
   link to the resolved absolute INTENT.md path, and one **Next** approval
   question with approve first as `(recommended)` only when the evidence
   supports it. Record corrections verbatim under `## Corrections`, update the
   file, and present the new link before asking again. When STATE records a new
   new-GitHub REPOSITORY.md binding, include its remote, default checkout, GSD
   Path branch, and primary worktree under `## Constraints`. Recompute and write
   the lane after every correction before relinking the file.

## Output contract

At approval, retain the already reviewed `Lane:` value and its one-line reason.
Retain `Review panel:` as reviewed: the CHARTER copy or the user's override
in milestone/lookahead mode, the CHARTER value in program mode, or `off`
when the user did not choose a panel and no CHARTER default exists.

After approval, finalize `.project/intent/INTENT.md` and run
`pipeline_state.py transition` with expected `define/active`, the exact
current milestone/branch/archive values, event `milestone intent approved`,
`--set-phase define --set-status done --set-milestone <milestone slug>`, and
`--project-dir .project/next` in lookahead. Require returned `define/done` and
the exact milestone. Confirm the approved outcome and link INTENT.md again.
Use the executable phase handoff in AGENTS.md for the next action.

## Rules

- Trace every question to a checklist gap; omit curiosity questions.
- In brownfield mode, state mapped facts for correction; never re-ask them.
- Treat solution-shaped problems as hypotheses and uncover the underlying pain.
- Preserve vetoes and corrections verbatim.
- Wrap up when every coverage-checklist area is answered or the user signals
  done, and tag remaining gaps.
