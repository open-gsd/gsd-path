---
name: gsd-path-build
description: Execute or resume an approved GSD Path plan with isolated task worktrees, deterministic commits, and independent wave review. Use only when the user explicitly invokes $gsd-path-build or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Build Orchestrator

Orchestrate coders, Git integration, and reviewers from the main conversation.
Never write product code in the orchestrator.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions and branch binding

- Require `pipeline: gsd-path/v1` in `.project/STATE.md`, an approved
  `.project/plan/PLAN.md`, and valid task files in `.project/tasks/`. A missing
  or different pipeline marker returns to `$gsd-path` for ownership checking.
  Legal entry is `plan/done`, `build/active|blocked`, or transition recovery
  from `build/done`; any later phase or an incomplete predecessor blocks
  rather than rewinding state. `build/done` is never a normal execution state:
  re-prove all wave gates and project Verify at current HEAD, then finish the
  committed transition to `review/active`.
- Read the local [coder role](references/coder.md),
  [reviewer role](references/reviewer.md), [dispatch contract](references/dispatch.md),
  [task template](templates/task.md), [board template](templates/board.md), and
  [wave-review template](templates/wave-review.md). Resolve them to absolute
  paths before briefing agents.
- Require a Git worktree with no unrelated changes. Expected uncommitted
  `.project/` planning artifacts may remain only through initial branch
  binding. On an approved patch re-entry, the exact review findings, appended
  plan/tasks, approval state, and no other changes are also expected; the build
  orchestrator commits them with the `build/active` transition before a layer
  base. Never discard, stash, or absorb another change.
- Fetch the configured remote and resolve its default ref and exact SHA without
  checking out, pulling, or updating the local default branch. When
  `STATE.branch` is null, bind either the current clean, unmerged non-default
  branch or a new unused `gsd-path/<project-slug>` branch created directly at
  that remote-default SHA. When `STATE.branch` is set, require the current
  symbolic branch to equal it. A mismatch, an already merged active branch, or
  a branch owned by another worktree blocks; never silently rebind it.
- Persist the branch in STATE.md. On entry from `plan/done`, set STATE to
  `build/active`, append `build started`, and commit that transition with the
  expected initial `.project/` artifacts before dispatch. From then on, every
  layer starts from a clean primary worktree and exact full `HEAD` SHA.

## Wave loop

For each wave in PLAN.md order:

1. **Recover before dispatch.** Reconcile task frontmatter over BOARD.md and
   inspect primary bookkeeping dirt plus every recorded task worktree and
   branch before selecting work. For an `in-progress` task with `commit: null`,
   use its recorded `base`, isolated worktree, and branch first. If integration
   may already have happened,
   inspect only first-parent commits in `base..STATE.branch` whose subject
   equals `<task-id>: <task title>`. A candidate must touch the task file, have
   no path outside `files` plus that task file, preserve the task contract with
   an append-only Log delta, and pass isolated Verify. The retained task branch
   or worktree must still prove the candidate's complete binary product patch
   and task-Log delta byte-for-byte equal the isolated source commit/diff.
   Exactly one proven candidate recovers its full SHA and `done` state; zero
   candidates resumes the retained isolated diff or returns it to `pending`
   only when ownership is clear; missing proof, multiple candidates, or any
   inconsistency blocks. For a task already carrying `status: done` and a full
   `commit`, prove that exact commit by the same subject, path, source-patch,
   Log-delta, and Verify checks. If its metadata is the sole uncommitted
   primary change, commit that bookkeeping; if the metadata is already in
   HEAD, leave it untouched. Then remove a still-present recorded worktree and
   branch only when both resolve to that proven task source and are clean. It
   is valid for both to be absent after earlier cleanup; one missing, a dirty
   worktree, or mismatched ownership blocks. Never use an unanchored log grep,
   infer a SHA from `done`, or reset unknown work.

2. **Prepare one dependency layer.** Reconcile failed and blocked tasks, then
   select pending tasks whose dependencies are `done`. A documented plan
   defect may be repaired against INTENT.md and SYNTHESIS.md and logged before
   a new clean base. One failed implementation gets one logged redispatch when
   its contract remains valid. Repeated failure, ambiguous ownership, a user
   ruling, or a dependency deadlock sets build state to `blocked` and stops.
   Concurrent tasks must have disjoint `files`; serialize overlapping fix
   tasks. A retry never reuses a rejected dirty worktree: first copy its
   validated append-only task Log delta into the primary task file, record the
   rejected diff's exact path set and hash, and commit the block bookkeeping.
   After confirming every old change is task-owned, remove that exact worktree
   and branch, then create the retry from the new clean primary HEAD. After
   resolving a recoverable `build/blocked` condition, set STATE back to
   `build/active`, log the resolution, and commit it before recording that new
   layer base.

3. **Isolate every task.** Commit pending bookkeeping, record clean `HEAD` as
   the layer base, and create one distinct linked worktree and deterministic
   temporary branch from that base for each ready task. Set frontmatter `base`,
   `worktree`, `task_branch`, `status: in-progress`, and `agent`, then commit
   that dispatch bookkeeping in the primary worktree. Do not append a dispatch
   Log entry: the isolated task later appends at that location, and two parallel
   appends make the cherry-pick ambiguous. Reuse a retained worktree only when
   its recorded base, branch, and task agree exactly.

4. **Dispatch the layer.** Following the local runtime dispatch contract,
   spawn one implementation-capable child per task with deterministic logical
   task name `build_<task_id>`.
   Its brief contains the absolute isolated-worktree root, coder role, task
   file, and task template. Add no hidden implementation context; repair a
   defective task contract before establishing the layer base. Run ready work
   up to capacity and collect the entire layer before unlocking dependents.

5. **Verify and integrate serially in task-id order.** A coder returns only
   `ready` or `blocked`; it never owns frontmatter or Git.

   - For `ready`, compare the complete worktree diff to `base`. Permit only
     declared `files` plus append-only Log changes in that task file. Include
     additions, deletions, renames, and binary changes; an unexpected path
     blocks before any product commit.
   - Run the task's Verify command in that isolated worktree. This rerun is the
     authoritative task evidence; a command run in the primary or a sibling
     worktree never counts. Append its exact result to the task Log.
   - In the isolated worktree, stage only changed declared files plus its task
     file and commit with exact subject `<task-id>: <task title>`. Then
     cherry-pick that source commit onto the clean primary branch. A conflict
     blocks; never blend sibling implementations to resolve it.
   - If cherry-pick conflicts, immediately abort that exact cherry-pick and
     confirm the primary branch returned clean; then block with the conflict
     evidence. Never leave an integration operation in progress.
   - Capture the resulting primary full SHA. Before any later Git operation,
     write it to `commit`, mark the task `done`, and commit that task's
     bookkeeping. Only then remove the exact linked worktree and temporary
     branch.
   - A blocked report, invalid diff, or failed Verify creates no product
     commit. Validate and copy the isolated task's append-only Log delta once;
     it is the coder's sole block/implementation narrative. Add orchestrator
     evidence only for a distinct diff or Verify rejection, set the task
     `blocked` or `failed`, commit the bookkeeping, and apply the recovery
     rule. Preserve the isolated worktree unless and until the explicit clean
     retry-retirement procedure in step 2 owns and removes it.

6. **Review the wave.** Only after every wave task is done, read the wave's
   `Review depth` from PLAN.md (default `full`).
   - `full`: spawn one independent reviewer using deterministic logical task
     name `review_wave_<wave>_cycle_<cycle>`. Supply every task path, its
     recorded base and commit, the reviewer role, and wave-review template.
     The reviewer reconstructs each task alone in a disposable worktree and
     writes `.project/review/wave-N.cycleC.md`.
   - `verify-only`: spawn no reviewer. The orchestrator writes
     `.project/review/wave-N.cycleC.md` itself from evidence it already
     holds — per task, the isolated Verify rerun and the declared-files diff
     check — recording `Depth: verify-only`. It checks each acceptance
     criterion against that evidence and the diff; anything it cannot
     confirm from them is a finding, not a pass.

7. **Fix or advance.** A valid `pass` advances. On `blocked`, read
   `max_review_cycles` from PLAN.md (default 3). Before the cap, batch the
   findings into complete fix tasks from the task template — one task per
   disjoint file scope, not one per finding — each carrying its findings'
   failed criteria and observed evidence verbatim, and run them through the
   same isolated layer loop. At the cap, record all attempts in BOARD.md and
   STATE.md and ask the user — through an interactive user-input tool when
   available — whether to relax the criterion, redirect the approach, or
   raise the cap, listing the orchestrator's recommended option first marked
   `(recommended)` with a one-line reason drawn from the review evidence.
   Never choose silently. On pass, commit the review artifact, BOARD.md, STATE.md, and wave
   bookkeeping, then report `wave N/M done, C review cycle(s)`.

## Completion

After every wave passes, create a disposable detached worktree at exact HEAD
and run PLAN.md's project Verify there. On success, append `build done; final
review pending`, set STATE.md directly to `phase: review`, `status: active`,
and commit that transition as the build orchestrator's final bookkeeping. This
keeps the primary worktree clean and avoids a separate review-phase transition
commit. Report waves, exact task commits, fixed findings, and remaining risk.
On failure, set build state to `blocked`, record the exact output, and do not
claim success. Remove only the disposable worktree created for this check. If
a crash leaves `build/done`, finish and commit this transition before returning
to the router.
