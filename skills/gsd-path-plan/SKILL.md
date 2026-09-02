---
name: gsd-path-plan
description: Create and validate dependency-ordered GSD Path build waves and complete task contracts. Use only when the user explicitly invokes $gsd-path-plan or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Planning Phase

Dispatch one planner, gate its artifacts, and obtain the single approval that
authorizes the build.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before planning and again before approval, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by planning is resolved in PLAN.md or its tasks, or the
phase blocks.

## Preconditions

Require `pipeline: gsd-path/v2` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Normal-mode legal entry
is `decide/done` (transition to `plan/active`) or `plan/active|blocked`;
quick mode additionally enters from `define/done` when INTENT.md records
`Lane: quick`, and milestone mode enters from `define/done` when INTENT.md
records `Lane: milestone` (see Quick mode and Milestone mode below).
Before dispatch, enter from `decide/done` or `define/done` with
`pipeline_state.py transition`, the complete current state as expected,
`--set-phase plan --set-status active`, and event `planning started`. Resume
`plan/blocked` through the same helper with event `planning resumed`. Require
the returned track state to be `plan/active`; never edit STATE directly.
Any later phase blocks instead of replacing an approved plan. Patch mode is
the only reopen exception: require an approved plan, no in-progress task, and
state `plan/done` or `ship/blocked`; any other state blocks. `build/done` is
reserved exclusively for the build orchestrator's transition recovery and
must return there instead of reopening planning. When an active router
supplies the lookahead track root `.project/next/`, evaluate these
preconditions against the track instead; see Lookahead mode.
Require `.project/intent/INTENT.md`. Normal mode also requires
`.project/research/SYNTHESIS.md`; quick mode may enter without it because this
phase creates the Settled-only synthesis before gating. Milestone mode instead
requires the program `.project/SYNTHESIS.md` at the `.project/` top level plus
`.project/ROADMAP.md` with an entry matching the track STATE's `milestone`.
Require that entry to be `active` normally and `pending` in Lookahead mode.
Require a non-empty `## Decisions` or `## Settled` section and no unresolved
`NEEDS-USER` items before dispatching the planner. Route to the producing phase when a
precondition fails.

## Alignment queue check

Before planning, read `research/DOCS-AUDIT.md` from the supplied track root:
`.project/research/DOCS-AUDIT.md` normally or
`.project/next/research/DOCS-AUDIT.md` in Lookahead mode. An absent
track-local audit means an empty alignment queue. If queued rulings marked
`planned: no` exist, offer once to include them:

- **Normal planning** — accepted items fold into the plan as ordinary
  tasks in dependency order (evidence inlined, `fix-doc` verifies re-run
  the audit's claim check), and their queue rows get the task id.
- **Patch mode** — accepted items join the patch wave alongside the
  invoking findings.

Declined items stay `planned: no` and will be offered again next time. The
user picks per item or "all"/"none" — a stale backlog must never sneak into
a plan wholesale without the user seeing the list. Offer through an
interactive user-input tool when available, marking the planner's
recommended choice per item `(recommended)` with a one-line reason (age,
severity, or fit with this milestone's scope).

## Process

Set `<track>` to `.project` for normal work and `.project/next` when the
router supplied lookahead mode. Every per-milestone path below, including
review-panel evidence, is rooted there. Program inputs remain at `.project/`
as stated in Lookahead mode.

1. Read the local [plan template](templates/plan.md), [task template](templates/task.md),
   [plan-panel template](templates/plan-panel.md), `scripts/check_handoffs.py`,
   and `scripts/review_panel.py`; resolve them to absolute paths.
2. Read the local [planner role](references/planner.md), then follow the
   local [runtime dispatch contract](references/dispatch.md) with deterministic
   logical task name `plan`. Give it absolute role, `AGENTS.md`, `WORKFLOW.md`,
   input, template, and output paths, including `.project/LESSONS.md` when it
   exists. Whenever INTENT.md records `Lane: milestone` — any entry point —
   also include `.project/CHARTER.md`, `.project/ROADMAP.md`, the top-level
   program `.project/SYNTHESIS.md`, and the resolved
   milestone entry slug. In
   final-review patch mode also include
   `.project/review/PATCH-FINDINGS.md` and every source artifact it names; in
   docs-audit patch mode include the selected `DOCS-AUDIT.md` rows and user
   rulings.
   The outputs are exactly `<track>/plan/PLAN.md` and one task
   file per task at `<track>/tasks/T###-slug.md` — no other location is
   canonical, and `.project/PLAN.md` is never written.
3. Gate PLAN.md and every task file:
   - Require unique task ids, and require every task's `wave` to name a
     `## Wave N` heading in PLAN.md. PLAN.md carries no task table.
   - Require task frontmatter fields `id`, `title`, `wave`, `deps`, `status`,
     `agent`, `base`, `worktree`, `task_branch`, and `files`; require
     initial `status: pending`, `agent: null`, `base: null`,
     `worktree: null`, and `task_branch: null` values.
   - Require every dependency id to exist, forbid later-wave dependencies,
     detect cycles, and forbid file overlap between planned tasks in the same
     wave. Same-wave dependency chains are allowed only when their files do
     not overlap; the build executes them in dependency layers.
   - Reject a declared dependency that carries neither data nor a prerequisite
     effect. A `deps` edge is valid only when the dependent consumes a symbol,
     signature, schema, endpoint, file format, or path named in that
     dependency's Interface contract, the two tasks' `files` overlap, or
     PLAN.md's Dependency notes name the exact landed effect the dependent
     requires — a removal, a migration, a cutover — and how a reviewer sees it.
     Judge each edge separately when a task lists several deps. Anything else
     is narrative order, not a dependency: drop that edge and place both tasks
     by the wave-order rules.
   - Require non-empty Context and Approach, observable Acceptance criteria,
     a Verify command that can fail when this task is skipped, that names a
     path from that task's `files`, and that is not PLAN.md's project Verify
     unless an owned SC names that command, an Intent coverage
     section (`- None` or owned SCn ids), and Log sections.
   - Require an Interface contract section in every task: `None` for
     independent tasks; when tasks exchange a symbol, schema, endpoint, file
     format, or path, exact shared shapes with identical text in every
     involved task.
   - Require deliverable-sized tasks naming real paths that match the existing
     codebase: each task is the largest coherent vertical slice — feature plus
     its tests and wiring — one agent run can complete. Reject a plan that
     splits one deliverable across tasks when no file-scope, dependency, or
     capacity conflict forces the split.
   - Require a `Review depth` value (`full`, `deep`, or `verify-only`) on
     every wave. Wave 1 and any wave touching authentication, authorization,
     payments, data migration, or concurrency requires `full` or `deep`;
     quick-lane single waves may use `verify-only`. The planner assigns `deep`
     sparingly to waves where a wrong merge is irreversible or
     security-critical.
   - When INTENT.md `Surfaces:` is not `none`, require a PLAN.md
     `## Surface contract` block per named surface with its Criteria, Entry,
     States, Walkthrough, and the task that delivers it. Those criteria must be
     among the SCn ids that task owns in its Intent coverage, and their Verify
     must exercise the surface a person uses — a rendered page, a real
     command's output — not an internal unit test.
     Require the surface to land in the same wave as the capability behind
     it, never in a later polish wave.
   - Prove every intent constraint and synthesis decision is covered, that no
     scope-out veto appears in a task, and that `Project verify` is a real,
     non-placeholder command in PLAN.md.
   - Run `python3 <absolute check_handoffs.py> plan --repo <absolute repo
     root>` and `--project-dir .project/next` when the router supplied the
     lookahead track. A non-zero exit is a gate failure: every INTENT.md
     success criterion must appear in PLAN.md Intent coverage mapped to a
     real task AC, and each task's Intent coverage section must match that
     table. A task Verify that copies Project verify fails unless an owned
     SC names that command. Any other task Verify must name a path from
     that task's `files`.
   - Run `python3 <absolute review_panel.py> validate-plan --plan <absolute
     PLAN.md> --intent <absolute INTENT.md>` and `--charter <absolute
     .project/CHARTER.md>` when that file exists. A non-zero exit is a gate
     failure. Quick mode requires `review_panel: off`.
4. Redispatch one complete corrected brief under logical task name `plan`,
   following the runtime dispatch contract and including all gate failures.
   Allow one revision round. If it still fails, use `pipeline_state.py
   transition` with the exact current phase, status, milestone, branch, and
   archive as expected fields, `--set-phase plan --set-status blocked`, and a
   one-line event naming the failed plan gates. Require returned
   `plan/blocked`, then
   present **Outcome** with the failed gate, **Review** linking the resolved
   absolute PLAN.md path (or STATE.md when PLAN.md is missing), and **Next**
   naming the one correction or user decision required. Stop.
5. Show the wave number, goal, and task count for every wave as the outcome.
   Link the resolved absolute `<track>/plan/PLAN.md` path and summarize the
   linked `<track>/tasks/` task set. Then run the optional review panel
   before the approval question:
   - Inspect the host child-agent schema for advertised model slugs. Do not
     guess slugs. Pass them to `python3 <absolute review_panel.py> resolve
     --plan <absolute <track>/plan/PLAN.md> --intent <absolute
     <track>/intent/INTENT.md> --advertised
     <comma slugs> --parent-slug <current model slug when known>` and
     `--charter <absolute .project/CHARTER.md>` when that file exists.
   - `status: off` — skip the panel and remove any stale
     `<track>/review/PLAN-PANEL.md` or `PLAN-PANEL.skipped.json`. The approval
     question may include
     `Approve with review panel (detected)` as an alternative; if chosen,
     write `review_panel: detected` into PLAN.md Config, re-run resolve, and
     continue this step.
   - `status: skipped` — remove any stale
     `<track>/review/PLAN-PANEL.md`, persist the exact JSON stdout from
     `resolve` at `<track>/review/PLAN-PANEL.skipped.json`, then use
     `pipeline_state.py transition` against `<track>` with the exact current
     state as both expected and resulting phase/status and event `plan review
     panel skipped: <helper reason>`. Require the returned unchanged
     `plan/active` position and continue without a panel. Do not treat
     this as a gate failure or infer enablement again from Config.
   - `status: error` or exit 2 — use the same guarded transition to set
     `plan/blocked` with an event naming the helper error, link PLAN.md, and stop.
     A named family that is not advertised is an assertion failure.
   - `status: ready` — for each selected family, spawn one independent child
     with logical task name `review_plan_panel_<family>`, the reviewer role
     in plan-panel mode, the plan-panel template, and the exact helper-returned
     model slug when the host advertises model selection. Never override the
     model on the planner. Each child stages its family file under a
     disposable root; the parent validates and copies those files, removes
     any stale `<track>/review/PLAN-PANEL.skipped.json`, then runs
     `python3 <absolute review_panel.py> merge --kind plan --inputs <family
     files> --output <absolute <track>/review/PLAN-PANEL.md> --mode
     <detected|named>`. Do not average findings or auto-replan.
   Before asking for approval, require exactly one panel artifact for non-off
   Config: `PLAN-PANEL.md` for `ready`, or `PLAN-PANEL.skipped.json` for
   `skipped`. Off Config requires neither. A mismatch blocks approval.
   Ask one explicit next question: whether to approve this plan and start the
   build. When PLAN-PANEL.md has `Actionable: 0` or the panel did not run,
   list `Approve and start build (recommended)` first, with `Request changes`
   as the alternative. When `Actionable` is greater than 0, list `Address
   panel findings first (recommended)` first, then `Approve and start build`,
   then `Request changes`. Link the applicable `<track>/review/PLAN-PANEL.md`
   or skipped receipt. If the user
   requests changes, keep `phase: plan`, `status: active`, revise, and re-gate.
6. On approval in an established repository, record the exact full current
   HEAD before changing approval metadata, then run:

   ```text
   python3 <absolute pipeline_state.py> approve \
     --repo <absolute root> --kind plan \
     --project-dir <.project or .project/next> \
     --expected-head <recorded full HEAD>
   ```

   The helper journals before mutation, changes the track STATE from
   `plan/active` to `plan/done` with event `plan approved`, validates that the
   active worktree is on its bound branch, and checkpoints all pending
   `.project/` artifacts with the canonical plan subject and body. Require its
   typed result to report `schema: gsd-path/state-checkpoint/v1`, `status:
   approved`, `kind: plan`, the requested `project_dir`, `state.status: done`,
   and the returned current commit. Rerun the same command after interruption;
   the matching journal owns recovery.

   Defer that checkpoint only when the directory is not yet a Git repository
   or `.project/REPOSITORY.md` records `Kind: new-github`. In that case run
   the same `approve` command with `--defer-checkpoint` instead of
   `--expected-head`; the helper journals the `plan approved` transition and
   the build transition commit owns the pending artifacts. Patch-mode
   approvals run `approve --repo <absolute root> --kind plan --patch`
   (event `patch plan approved`) without a plan checkpoint because build's
   patch re-entry commits the artifacts with its `build/active` transition.
   `pipeline_state.py transition` never approves a plan. Confirm approval,
   link PLAN.md again, and state that
   build starts next. Do not add another approval gate. When routed by an
   active `$gsd-path`, return control to that router so its bundled build
   contract starts. When invoked directly, stop and tell the user to explicitly
   invoke `$gsd-path`, which routes to build; do not invoke an explicit-only
   sibling skill yourself.

## Ordering rules

- Put plan-invalidating assumptions in wave 1.
- Produce the thinnest runnable end-to-end slice in wave 2.
- Order later features by dependency, then polish.

## Quick mode

Legal entry: `define/done` where INTENT.md records `Lane: quick` (transition
to `plan/active`, logging that research and decide were skipped for the
quick lane). Quick mode dispatches no planner agent — the orchestrator writes
the artifacts directly:

1. Write `.project/research/SYNTHESIS.md` containing only `## Settled` lines
   citing INTENT.md constraints (and, brownfield, `evidence-codebase.md`)
   plus a minimal `## For the planner` naming the walking skeleton. No
   invented decisions or runner-ups.
2. Write `.project/plan/PLAN.md` with exactly one wave — `Review depth:
   verify-only` permitted — and at most two deliverable-sized task files
   (project policy),
   honoring every task-contract rule above and `.project/LESSONS.md` when it
   exists. Write `review_panel: off` and `finding_skeptics: off` regardless
   of INTENT.md.
3. Gate exactly as step 3 above and use the same outcome, Review link, and
   single approval question as normal mode.
   A quick plan that cannot satisfy the gates — more than two tasks, an open
   choice, a cross-wave risk — corrects INTENT.md's `Lane:` to `standard`,
   tells the user why, and returns to the standard pipeline at `define/done`.

## Milestone mode

Legal entry: `define/done` where INTENT.md records `Lane: milestone`
(transition to `plan/active`). Program decisions are already settled, so this
mode first writes the milestone's own synthesis — the archive requires
`research/SYNTHESIS.md` for every milestone, and it records exactly which
program decisions the milestone plan was built against:

1. Require the program `.project/SYNTHESIS.md`, `.project/CHARTER.md`, and
   `.project/ROADMAP.md` with an entry matching the track STATE's `milestone`;
   it must be `active` normally and `pending` in Lookahead mode.
2. Write `.project/research/SYNTHESIS.md` containing only `## Settled` lines
   citing the program SYNTHESIS decisions, charter constraints, and the
   resolved roadmap entry's success criteria, plus a minimal `## For the planner`
   naming the milestone's walking skeleton. No invented decisions or
   runner-ups.
3. Dispatch the planner per the standard contract (the brief includes
   CHARTER.md, ROADMAP.md, and the resolved entry slug), then gate and approve
   exactly as normal mode.

## Lookahead mode

Entered only when an active router supplies the lookahead track root
`.project/next/` while the active STATE.md is `build/active` in program
flow. Milestone-mode rules apply with every per-milestone path rooted at
`.project/next/`: the state file is `next/STATE.md`, INTENT.md is
`next/intent/INTENT.md`, the milestone synthesis is
`next/research/SYNTHESIS.md` (written here, per milestone mode), and the
outputs are `next/plan/PLAN.md` and `next/tasks/T###-slug.md`. Program
inputs — CHARTER.md, ROADMAP.md, the top-level SYNTHESIS.md, LESSONS.md —
are read from their active `.project/` paths. Lookahead-only differences:

- Resolve the roadmap entry only from `.project/next/STATE.md`'s `milestone`,
  require that exact entry to remain `pending`, and never substitute the
  building milestone's `active` entry.

- Task paths gate against the codebase at current HEAD while the active
  milestone is still building. Where the building milestone's approved
  PLAN.md declares paths the lookahead tasks will touch, name that overlap
  in the task Context; the router's promotion and the build's normal
  plan-defect repair absorb drift.
- The approval checkpoint commit stages `.project/` in full, which includes
  `next/`; the deferral exceptions are unchanged. Its panel evidence is
  `.project/next/review/PLAN-PANEL.md` or
  `.project/next/review/PLAN-PANEL.skipped.json`, never an active-path copy.
- Patch mode is never legal in lookahead: there is no running build of the
  lookahead milestone to patch. Route any such request to the active
  milestone's build track.
- A promoted lookahead plan re-enters this phase as `plan/active` when the
  router's promotion re-validation flags drifted task paths. Re-gate every
  flagged task against current HEAD — repair contracts through documented
  plan-defect repair or one planner redispatch under logical task name
  `plan` — present the delta, and re-run the step 5-6 approval before
  build.

Never write an active-path artifact in this mode.

## Patch mode

Turn verified findings into one appended wave instead of replanning.
Invoked by `$gsd-path-docs-audit` (remediation rulings) or `$gsd-path-ship final`
(`not-met` criteria); the invoker names the exact ordered list of one or more
findings source files and rows.

**Preconditions.** An existing approved `.project/plan/PLAN.md`. For a
final-review patch, require a valid `.project/review/PATCH-FINDINGS.md` and the
source artifacts named there. For a docs-audit patch, require the selected
`DOCS-AUDIT.md` rows and their recorded user rulings instead. Each selected
item must carry evidence. No `.project/plan/PLAN.md` → decline and route to
the normal pipeline (this includes an archived ship, whose plan moved into
`.project/archive/`); unruled audit findings → send them back for rulings
first.

**Process.**

1. Use `pipeline_state.py transition` with the complete `plan/done` or
   `ship/blocked` state as expected, set `phase: plan`, `status: active`, and
   event `patch plan reopened`. Require returned `plan/active`. A shipped
   milestone cannot reopen because its plan is
   archived; start a new milestone instead.
2. In final-review patch mode, run `python3 <absolute check_handoffs.py> patch
   --repo <absolute repo root>`. In docs-audit patch mode, use the selected
   `DOCS-AUDIT.md` rows and rulings as the source hand-off. Dispatch the planner
   per the standard contract with deterministic logical task name `plan_patch`,
   adding: the applicable hand-off path, its exact ordered findings, source
   paths and selected rows, the existing PLAN.md and task files, and the instruction to
   append wave W+1 (highest existing wave + 1) without modifying completed
   waves or existing tasks. One task per accepted finding, carrying the
   finding's evidence verbatim in its Context; `fix-doc` findings are tasks
   too — their Verify re-runs the audit's claim check so the corrected doc
   is proven, not assumed. A patch task that repairs an SC finding lists that
   SCn in its Intent coverage and adds a coverage row; other patch tasks
   write `- None`. Do not edit existing coverage rows or existing task Owns.
   Cross-finding dependencies stay inside the patch
   wave, split into further waves only if file scopes force it.
3. Gate exactly as in step 3 above, scoped to the new tasks plus one extra
   check: patch tasks must not touch a scope-out veto or contradict a
   SYNTHESIS decision — a finding that requires either goes back to the
   user, not into the wave.
4. Show the patch wave outcome (finding → task mapping), link the resolved
   absolute PLAN.md and task set, and ask the same two-option approval question.
   On approval, relink the approved plan, run `python3 <absolute
   pipeline_state.py> approve --repo <absolute root> --kind plan --patch`
   (it records `plan/done` with event `patch plan approved` and no
   checkpoint), then use the same provenance rule as normal
   mode: an active router
   resumes its bundled build contract, while a direct invocation stops and
   tells the user to explicitly invoke `$gsd-path` or `$gsd-path-build`. The
   build runs the new wave through the normal dispatch and review-gate loop
   before final review runs again.
