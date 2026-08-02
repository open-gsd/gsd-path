---
name: gsd-path-plan
description: Create and validate dependency-ordered GSD Path build waves and complete task contracts. Use only when the user explicitly invokes $gsd-path-plan or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Planning Phase

Dispatch one planner, gate its artifacts, and obtain the single approval that
authorizes the build.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions

Require `pipeline: gsd-path/v1` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Normal-mode legal entry
is `synthesize/done` (transition to `plan/active`) or `plan/active|blocked`;
quick mode additionally enters from `grill/done` when INTENT.md records
`Lane: quick` (see Quick mode below).
Any later phase blocks instead of replacing an approved plan. Patch mode is
the only reopen exception: require an approved plan, no in-progress task, and
state `plan/done` or `review/blocked`; any other state blocks. `build/done` is
reserved exclusively for the build orchestrator's transition recovery and
must return there instead of reopening planning.
Require both
`.project/intent/INTENT.md` and
`.project/research/SYNTHESIS.md`. Require a non-empty `## Decisions` or
`## Settled` section and no unresolved `NEEDS-USER` items. Route to the producing phase when a
precondition fails.

## Alignment queue check

Before planning (either mode), read `.project/research/DOCS-AUDIT.md` for
rulings marked `planned: no`. If any exist, offer once to include them:

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

1. Read the local [plan template](templates/plan.md) and
   [task template](templates/task.md); resolve both to absolute paths.
2. Read the local [planner role](references/planner.md), then follow the
   local [runtime dispatch contract](references/dispatch.md) with deterministic
   logical task name `plan`. Give it absolute role, input, template, and output paths,
   including `.project/LESSONS.md` when it exists.
   The outputs are exactly `.project/plan/PLAN.md` and one task
   file per task at `.project/tasks/T###-slug.md` — no other location is
   canonical, and `.project/PLAN.md` is never written.
3. Gate PLAN.md and every task file:
   - Map every PLAN table row to exactly one task file and every task file to
     exactly one row. Require unique ids and matching wave numbers.
   - Require task frontmatter fields `id`, `title`, `wave`, `deps`, `status`,
     `agent`, `commit`, `base`, `worktree`, `task_branch`, and `files`; require
     initial `status: pending`, `agent: null`, `commit: null`, `base: null`,
     `worktree: null`, and `task_branch: null` values.
   - Require every dependency id to exist, forbid later-wave dependencies,
     detect cycles, and forbid file overlap between planned tasks in the same
     wave. Same-wave dependency chains are allowed only when their files do
     not overlap; the build executes them in dependency layers.
   - Require non-empty Context and Approach, observable Acceptance criteria,
     a Verify command that can fail when work is skipped, and Log sections.
   - Require deliverable-sized tasks naming real paths that match the existing
     codebase: each task is the largest coherent vertical slice — feature plus
     its tests and wiring — one agent run can complete. Reject a plan that
     splits one deliverable across tasks when no file-scope, dependency, or
     capacity conflict forces the split.
   - Require a `Review depth` value (`full` or `verify-only`) on every wave.
     Wave 1 and any wave touching authentication, authorization, payments,
     data migration, or concurrency requires `full`; quick-lane single waves
     may use `verify-only`.
   - Prove every intent constraint and synthesis decision is covered, and that
     no scope-out veto appears in a task.
4. Redispatch one complete corrected brief under logical task name `plan`,
   following the runtime dispatch contract and including all gate failures.
   Allow one revision round. If it still fails, set STATE.md to
   `phase: plan`, `status: blocked`, append the failures to its log, surface
   them, and stop.
5. Show the wave number, goal, and task count for every wave. Ask one explicit
   question: whether to approve this plan and start the build. If the user
   requests changes, keep `phase: plan`, `status: active`, revise, and re-gate.
6. On approval, set STATE.md to `phase: plan`, `status: done`, record the
   approval in the log. Do not add another approval gate. When routed by an
   active `$gsd-path`, return control to that router so its bundled build
   contract starts. When invoked directly, stop and tell the user to explicitly
   invoke `$gsd-path` or `$gsd-path-build`; do not invoke an explicit-only
   sibling skill yourself.

## Ordering rules

- Put plan-invalidating assumptions in wave 1.
- Produce the thinnest runnable end-to-end slice in wave 2.
- Order later features by dependency, then polish.

## Quick mode

Legal entry: `grill/done` where INTENT.md records `Lane: quick` (transition
to `plan/active`, logging that research and synthesize were skipped for the
quick lane). Quick mode dispatches no planner agent — the orchestrator writes
the artifacts directly:

1. Write `.project/research/SYNTHESIS.md` containing only `## Settled` lines
   citing INTENT.md constraints (and, brownfield, `evidence-codebase.md`)
   plus a minimal `## For the planner` naming the walking skeleton. No
   invented decisions or runner-ups.
2. Write `.project/plan/PLAN.md` with exactly one wave — `Review depth:
   verify-only` permitted — and at most two deliverable-sized task files,
   honoring every task-contract rule above and `.project/LESSONS.md` when it
   exists.
3. Gate exactly as step 3 above and ask the same single approval question.
   A quick plan that cannot satisfy the gates — more than two tasks, an open
   choice, a cross-wave risk — corrects INTENT.md's `Lane:` to `standard`,
   tells the user why, and returns to the standard pipeline at `grill/done`.

## Patch mode

Turn verified findings into one appended wave instead of replanning.
Invoked by `$gsd-path-docs-audit` (remediation rulings) or `$gsd-path-review final`
(`not-met` criteria); the invoker names the exact ordered list of one or more
findings source files and rows.

**Preconditions.** An existing approved `.project/plan/PLAN.md`, and findings sources
whose selected items carry evidence plus — for audit findings — a recorded user
ruling. No `.project/plan/PLAN.md` → decline and route to the normal pipeline
(this includes an archived ship, whose plan moved into `.project/archive/`);
unruled findings → send them back for rulings first.

**Process.**

1. Set STATE.md `phase: plan`, `status: active` and note the patch reopening in
   the state log. A shipped milestone cannot reopen because its plan is
   archived; start a new milestone instead.
2. Dispatch the planner per the standard contract with deterministic logical
   task name `plan_patch`, adding: the findings
   source paths and selected rows, the existing PLAN.md and task files, and the instruction to
   append wave W+1 (highest existing wave + 1) without modifying completed
   waves or existing tasks. One task per accepted finding, carrying the
   finding's evidence verbatim in its Context; `fix-doc` findings are tasks
   too — their Verify re-runs the audit's claim check so the corrected doc
   is proven, not assumed. Cross-finding dependencies stay inside the patch
   wave, split into further waves only if file scopes force it.
3. Gate exactly as in step 3 above, scoped to the new tasks plus one extra
   check: patch tasks must not touch a scope-out veto or contradict a
   SYNTHESIS decision — a finding that requires either goes back to the
   user, not into the wave.
4. Show the patch wave summary (finding → task mapping) and ask one
   approval question. On approval, mark `phase: plan`, `status: done`, log
   it, and use the same provenance rule as normal mode: an active router
   resumes its bundled build contract, while a direct invocation stops and
   tells the user to explicitly invoke `$gsd-path` or `$gsd-path-build`. The
   build runs the new wave through the normal dispatch and review-gate loop
   before final review runs again.
