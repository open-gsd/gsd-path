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

Require `pipeline: gsd-path/v2` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Legal entry is
`decide/done` with an existing `.project/CHARTER.md` and no `.project/ROADMAP.md`
yet (transition to `roadmap/active`), `roadmap/active|blocked`, or a
milestone-boundary re-slice: `inspect/active` or `define/active` with no
approved INTENT.md for the next milestone and a user request to re-scope the
remaining `pending` entries,
or `roadmap/active` with STATE.milestone null and an `abandoned` entry in
ROADMAP.md (the post-abandon re-slice the build orchestrator hands off).
Any later phase blocks; mid-milestone
re-scope is never legal — finish or ship the active milestone first. A
`decide/done` state with ROADMAP.md already present is milestone-scope decide;
route to `$gsd-path-plan`, never regenerate the roadmap beneath it. Absent
CHARTER.md, this is not a program: route to `$gsd-path`, which continues the
single-milestone flow at plan. Before dispatching a re-slice while
`.project/next/` holds a lookahead track, copy the current ROADMAP.md to the
regular file `.project/ROADMAP.before-reslice.md` and save the lookahead
milestone slug. Do not ask for the keep/discard ruling until the candidate
roadmap has been generated and passed its gate. On recovery, reuse that exact
snapshot; never replace it from the current candidate.

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
   give the existing ROADMAP.md with the instruction to preserve `shipped`
   entries byte-for-byte except Status/Archive/Integrated fields and to never modify
   `abandoned` entries at all. On a milestone-boundary re-slice, also preserve
   the entry matching STATE.milestone as the single `active` entry and re-slice
   only the remaining `pending` entries.
   The output is exactly `.project/ROADMAP.md` — no other location is
   canonical.
3. Gate ROADMAP.md:
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
   - `shipped` entries differ from the prior roadmap only in
     Status/Archive/Integrated; `abandoned` entries are byte-for-byte identical.
   - On a milestone-boundary re-slice, the entry matching STATE.milestone is
     unchanged and remains the single `active` entry.
4. Redispatch one complete corrected brief under logical task name `roadmap`,
   following the runtime dispatch contract and including all gate failures.
   Allow one revision round. If it still fails, keep the entering
   `inspect/active` or `define/active` state for a milestone-boundary re-slice;
   otherwise set STATE.md to `phase: roadmap`, `status: blocked`. Append the
   failures to its log, then
   present **Outcome** with the failed gate, **Review** linking the resolved
   absolute ROADMAP.md path (or STATE.md when ROADMAP.md is missing), and
   **Next** naming the one correction or user decision required. Stop.
5. On a re-slice with a saved lookahead track, run the bundled
   `scripts/promote_lookahead.py compare-entry --before
   .project/ROADMAP.before-reslice.md --after .project/ROADMAP.md --milestone
   <lookahead-slug>` helper now. It compares
   every plan-binding part of the entry while ignoring only Status, Archive,
   and Integrated. When it returns `status: unchanged`, ask the user to choose
   `Keep the unchanged lookahead track (recommended)` or `Discard and
   regenerate the lookahead track`. When it returns `status: changed`, offer
   `Discard and regenerate the lookahead track (recommended)` or `Request
   roadmap changes`; keeping the stale track is not valid. Apply the ruling,
   remove the saved comparison file, and record the helper result and ruling
   in the state log before roadmap approval.
6. Show every milestone id, goal, and dependency summary as the outcome. Link
   the resolved absolute `.project/ROADMAP.md` path, then ask one explicit next
   question. For a milestone-boundary re-slice, list `Approve roadmap and
   resume the active milestone (recommended)` first. For a post-abandon
   re-slice, list `Approve roadmap and inspect the first pending milestone
   (recommended)` first. Otherwise list `Approve roadmap and start the first
   pending milestone (recommended)` first. In every case, list `Request
   changes` as the alternative. If the user requests changes,
   retain the entering state for a milestone-boundary re-slice; otherwise keep
   `phase: roadmap`, `status: active`. Revise and re-gate.
7. On approval of a milestone-boundary re-slice, preserve the entering
   `phase`, `status`, and `milestone` in STATE.md and keep its matching roadmap
   entry `active`. On a post-abandon re-slice, preserve the bound branch, set
   STATE.md to `phase: inspect`, `status: active`, `milestone` to the first
   `pending` milestone slug, and `archive: null`; mark that entry `active` and
   record the abandoned predecessor in the log. On first roadmap approval,
   set STATE.md to `phase: roadmap`, `status: done`, set `milestone` to the
   first `pending` milestone slug, and mark that entry `active`. Record the
   approval in the log. Then
   checkpoint the approval in Git: stage `.project/` in full — the approved
   CHARTER.md, program SYNTHESIS.md, ROADMAP.md, research artifacts, STATE.md,
   and complete append-only discussion records — and commit with exact
   subject `roadmap: program roadmap approved` and body
   `Why: approved roadmap checkpoint`. Defer the checkpoint to the
   build orchestrator's transition commit only when the directory is not yet
   a Git repository or `.project/REPOSITORY.md` records `Kind: new-github`
   (the router owns the branch during that transaction). Confirm
   approval and link ROADMAP.md again. For a milestone-boundary re-slice,
   state that the preserved inspect or define phase resumes. For a
   post-abandon re-slice, state that inspect is next. Otherwise state that
   define (milestone mode) is next. Do not add another approval gate.
   When routed by an active `$gsd-path`, return control to that router so its
   state table routes the preserved STATE.md — `inspect/active` resumes
   inspect, `define/active` resumes define; never name define as next when
   inspect was preserved. When invoked directly, stop and tell the user to
   explicitly invoke `$gsd-path`, which routes that same preserved state; do
   not invoke an explicit-only sibling skill yourself.

## Rules

- Cover the charter exactly: no unmapped scope, no unscoped milestones.
- Milestone granularity only; never drift into waves, tasks, or file scopes.
- Every milestone must be shippable on its own stated dependencies.
- Surface scope cuts as `NEEDS-USER`; never drop charter scope silently.
