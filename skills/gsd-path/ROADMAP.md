---
name: gsd-path-roadmap
description: Slice an approved GSD Path program charter into a dependency-ordered roadmap of independently shippable milestones. Use only when the user explicitly invokes $gsd-path-roadmap or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Roadmap Phase

Dispatch one roadmapper, gate its roadmap, and obtain the single approval that
authorizes milestone planning. Rolling-wave: the roadmap scopes every
milestone; waves and tasks belong to `$gsd-path-plan`.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

Before dispatch and again before approval, run the bundled
`scripts/discussion_records.py pending --repo <absolute-root>`; when
`.project/discuss/ANSWERS.md` is absent, continue. Resolve a reported
required follow-up owned by roadmap in ROADMAP.md and record its disposition
with the helper's `dispose` command; otherwise block with links to ANSWERS.md
and the target artifact rather than approving stale scope.

## Preconditions

Require `pipeline_state.py validate --repo <absolute root>` to pass; otherwise
return to `$gsd-path` for ownership checking. Legal entry is
`decide/done` with an existing `.project/CHARTER.md` and no `.project/ROADMAP.md`
yet, `roadmap/active|blocked`, or a
milestone-boundary re-slice: `inspect/active` or `define/active` with no
approved INTENT.md for the next milestone and a user request to re-scope the
remaining `pending` entries,
or `roadmap/active` with STATE.milestone null and an `abandoned` entry in
ROADMAP.md (the post-abandon re-slice the build orchestrator hands off).
Enter from `decide/done` only with `pipeline_state.py transition`, exact
expected phase/status/milestone/branch/archive fields, event `roadmap started`,
and `--set-phase roadmap --set-status active`; never edit STATE directly. In a
milestone-boundary re-slice, preserve the entering `inspect/active` or
`define/active` state throughout the re-slice.
Any later phase blocks; mid-milestone
re-scope is never legal — finish or ship the active milestone first. A
`decide/done` state with ROADMAP.md already present is milestone-scope decide;
route to `$gsd-path-plan`, never regenerate the roadmap beneath it. Absent
CHARTER.md, this is not a program: route to `$gsd-path`, which continues the
single-milestone flow at plan. Before dispatching every re-slice, run the
bundled `scripts/promote_lookahead.py snapshot-roadmap --roadmap
.project/ROADMAP.md --snapshot .project/ROADMAP.before-reslice.md` helper.
Create the baseline once and retain it through every revision; an `existing`
result is recovery evidence and must never be replaced from the current
candidate. When `.project/next/` holds a lookahead track, also save its
milestone slug. Do not ask for the keep/discard ruling until the candidate
roadmap has been generated and passed its gate.

Require `.project/CHARTER.md` and `.project/SYNTHESIS.md` (program scope) with
a non-empty `## Decisions` or `## Settled` section and no unresolved
`NEEDS-USER` items before dispatch. Route to the producing phase when a
precondition fails.

## Process

1. Read the local [roadmap template](templates/roadmap.md) and resolve it to an
   absolute path.
2. Read the local [roadmapper role](references/roadmapper.md), then follow the
   local [runtime dispatch contract](references/dispatch.md) with deterministic
   logical task name `roadmap` and a `heavy` tier hint. Give it absolute role,
   `AGENTS.md`, `WORKFLOW.md`, CHARTER.md, SYNTHESIS.md, every dispatched
   evidence file named in `.project/research/RESEARCH.md` — after milestone
   archival has moved the active research directory, name the read-only
   archived manifest and evidence copies under their
   `.project/archive/<NNN>-<slug>/research/` paths
   instead — template, and output
   paths, including `.project/LESSONS.md` when it exists. On a re-slice, also
   give `.project/ROADMAP.before-reslice.md` with the instruction to preserve
   `shipped` entries byte-for-byte except Status/Archive/Integrated fields and
   to never modify `abandoned` entries at all. For a milestone-boundary
   re-slice, also preserve the existing `active` entry byte-for-byte; only
   `pending` entries are in scope.
   The output is exactly `.project/ROADMAP.md` — no other location is
   canonical.
3. Gate ROADMAP.md:
   First run `python3 <absolute check_handoffs.py> roadmap --repo <absolute
   root>`; its structural result is required in addition to the semantic
   checks below.
   - Every CHARTER.md `Full scope: in` item maps to at least one milestone,
     and every milestone traces back to charter scope.
   - Every milestone entry has Goal, Depends on, Status, Archive, Scope in/out,
     Success criteria, Risks, and Open questions fields; ids are unique and
     ordered.
   - Dependencies reference earlier milestone ids and form an acyclic graph.
   - M001 is the thinnest end-to-end skeleton that burns the riskiest
     synthesis decisions.
   - Rolling-wave: no waves, tasks, or file lists anywhere in the roadmap.
   - No scope-out veto appears in any milestone; every synthesis decision is
     honored by at least one milestone's scope.
   - On a re-slice, `shipped` entries differ from
     `.project/ROADMAP.before-reslice.md` only in Status/Archive/Integrated;
     `abandoned` entries are byte-for-byte identical.
   - On a milestone-boundary re-slice, the prior `active` entry is byte-for-byte
     identical to `.project/ROADMAP.before-reslice.md`.
4. Redispatch one complete corrected brief under logical task name `roadmap`,
   following the runtime dispatch contract and including all gate failures.
   Allow one revision round. If it still fails, keep the entering
   `inspect/active` or `define/active` state for a milestone-boundary re-slice
   and use `pipeline_state.py transition` with that complete state as both the
   expected and retained state and an event naming the failed roadmap gate.
   Otherwise use the helper with expected `roadmap/active`, exact milestone,
   branch, and archive values, `--set-status blocked`, and the same event. Then
   present **Outcome** with the failed gate, **Review** linking the resolved
   absolute ROADMAP.md path (or STATE.md when ROADMAP.md is missing), and
   **Next** naming the one correction or user decision required. Stop.
5. On a re-slice with a saved lookahead track, run the bundled
   `scripts/promote_lookahead.py compare-entry --before
   .project/ROADMAP.before-reslice.md --after .project/ROADMAP.md --milestone
   <lookahead-slug>` helper now. When STATE.milestone is set, append
   `--active-milestone <STATE.milestone>`; when it is unset, omit that option.
   It compares every plan-binding part of the entry while ignoring only
   Status, Archive, and Integrated, and requires that entry to remain the
   candidate roadmap's first dependency-ready milestone. When it returns
   `status: unchanged`, ask
   the user to choose
   `Keep the unchanged lookahead track (recommended)` or `Discard and
   regenerate the lookahead track`. When it returns `status: changed`, offer
   `Discard and regenerate the lookahead track (recommended)` or `Request
   roadmap changes`; keeping the stale track is not valid. Apply the ruling
   and record the helper result and ruling with `pipeline_state.py transition`,
   expecting and retaining the complete entering state with event `lookahead
   re-slice ruling: <ruling>`; never append it directly. Retain the baseline
   through any requested roadmap revisions and the final approval decision.
6. On a post-abandon re-slice, first run the bundled
   `scripts/promote_lookahead.py select-next --roadmap .project/ROADMAP.md`
   helper against the gated candidate. When it returns `status: complete`,
   report program completion against CHARTER.md's program success criteria and
   stop without offering a pending-milestone approval. When it returns
   `status: selected`, use only its exact milestone in the approval and
   transition below. A `status: none` result blocks without mutation.
   Show every milestone id, goal, and dependency summary as the outcome. Link
   the resolved absolute `.project/ROADMAP.md` path, then ask one explicit next
   question. For a milestone-boundary re-slice, list `Approve roadmap and
   resume the active milestone (recommended)` first. For a post-abandon
   re-slice, list
   `Approve roadmap and inspect <selected-milestone> (recommended)` first.
   Otherwise list `Approve roadmap and start the first
   pending milestone (recommended)` first. In every case, list `Request
   changes` as the alternative. If the user requests changes,
   retain the entering state for a milestone-boundary re-slice; otherwise keep
   `phase: roadmap`, `status: active`. Retain the baseline, revise, and re-gate
   against that same baseline.
7. On approval in an established repository, record the exact full current
   HEAD before changing ROADMAP.md or STATE.md. For a milestone-boundary
   re-slice, keep its matching roadmap entry `active`, use `pipeline_state.py
   transition` to record `program roadmap re-slice approved` while expecting
   and retaining the complete entering `inspect/active` or `define/active`
   state, then checkpoint the pending `.project/` artifacts with:

   ```text
   python3 <absolute isolation.py> checkpoint \
     --repo <absolute root> --expected-head <recorded full HEAD> \
     --subject "roadmap: program roadmap approved" \
     --body "Why: approved roadmap checkpoint" \
     --allow-path .project
   ```

   On a post-abandon re-slice, mark only the helper-selected pending entry
   `active`, use `pipeline_state.py transition` with the complete current
   `roadmap/active` state as expected to set `phase: inspect`, `status: active`,
   `milestone` to the selected slug, preserve the bound branch, and set
   `archive: null`, with an event naming the abandoned predecessor. Then use
   the same `isolation.py checkpoint` command above. For a first roadmap
   approval, run:

   ```text
   python3 <absolute pipeline_state.py> approve \
     --repo <absolute root> --kind roadmap \
     --milestone <selected first pending slug> \
     --expected-head <recorded full HEAD>
   ```

   The helper journals before mutation, proves the selected entry is pending
   and no entry is already active, marks it active, changes STATE from
   `roadmap/active` to `roadmap/done` with that milestone and event `program
   roadmap approved`, and checkpoints all pending `.project/` artifacts with
   the canonical roadmap subject and body. Require its typed result to report
   `schema: gsd-path/state-checkpoint/v1`, `status: approved`, `kind: roadmap`,
   `project_dir: .project`, `state.status: done`, the selected milestone, and
   the returned current commit. Rerun the same command after interruption; the
   matching journal owns recovery.

   For every re-slice, remove `.project/ROADMAP.before-reslice.md` only after
   the state transition succeeds and before the checkpoint. Retain it through
   every requested revision and failed approval attempt.

   Defer either checkpoint only when the directory is not yet a Git repository
   or `.project/REPOSITORY.md` records `Kind: new-github`. For a normal
   approval, mark the selected entry active and use `pipeline_state.py
   transition` with the complete current state as expected, `--set-status done
   --set-milestone <selected slug>`, and event `program roadmap approved`; for
   a milestone-boundary re-slice, use the retaining transition above; for a
   post-abandon re-slice, use its transition above. The build transition
   commit owns the pending artifacts. Confirm approval and link ROADMAP.md again. For
   a milestone-boundary re-slice, state that the preserved inspect or define
   phase resumes; for a post-abandon re-slice, state that inspect is next;
   otherwise state that define (milestone mode) is next. Do not
   add another approval gate. When routed by an active `$gsd-path`, return
   control to that router so it routes the resulting state; never name define
   as next when inspect was preserved or selected. When invoked directly, stop
   and tell the user to explicitly invoke `$gsd-path`, which routes the same
   result; do not invoke an explicit-only sibling skill yourself.

## Rules

- Cover the charter exactly: no unmapped scope, no unscoped milestones.
- Milestone granularity only; never drift into waves, tasks, or file scopes.
- Every milestone must be shippable on its own stated dependencies.
- Surface scope cuts as `NEEDS-USER`; never drop charter scope silently.
