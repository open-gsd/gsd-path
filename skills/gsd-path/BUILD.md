---
name: gsd-path-build
description: Execute or resume an approved GSD Path plan with isolated task worktrees, deterministic commits, and independent wave review. Use only when the user explicitly invokes $gsd-path-build or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Build Orchestrator

Orchestrate coders, task landing, and reviewers from the main conversation.
Never write product code in the orchestrator.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions and branch binding

- Require `pipeline: gsd-path/v2` in `.project/STATE.md`, an approved
  `.project/plan/PLAN.md`, and valid task files in `.project/tasks/`. A missing
  or different pipeline marker returns to `$gsd-path` for ownership checking.
  Legal entry is `plan/done`, `build/active|blocked`, or transition recovery
  from `build/done`; any later phase or an incomplete predecessor blocks
  rather than rewinding state. A concrete STATE.archive during `build/*`
  marks an interrupted milestone-abandon transaction: resume the Milestone
  abandon procedure below before any recovery or dispatch. `build/done` is never a normal execution state:
  re-prove all wave gates at current HEAD, then finish the
  committed transition to `ship/active`. Project Verify waits for ship.
- Read the local [coder role](references/coder.md),
  [reviewer role](references/reviewer.md), [dispatch contract](references/dispatch.md),
  [task template](templates/task.md),
  [wave-review template](templates/wave-review.md), and
  [wave-panel template](templates/wave-panel.md). Resolve them to absolute
  paths before briefing agents. Resolve `scripts/review_panel.py` when
  PLAN.md Config names a review panel. Resolve `scripts/check_handoffs.py`
  for Intent coverage. Resolve `scripts/isolation.py` for task isolation,
  recovery, verify sidecars, and task landing; do not invent
  `git worktree add`, `--detach`, commit, or cherry-pick commands.
- There is no board file. Task frontmatter is the only task-state record;
  when a report or question needs a wave summary, render it inline from the
  task files and wave reviews. Record escalations and plan defects in the
  STATE.md log.
- Require a Git worktree with no unrelated changes. Roadmap and plan
  approval checkpoints normally leave `.project/` fully committed; expected
  uncommitted `.project/` planning artifacts may remain only through initial
  branch binding when a checkpoint was deferred (a `Kind: new-github`
  transaction or no Git repository at approval time). On an approved patch
  re-entry, the exact review findings, appended
  plan/tasks, approval state, and no other changes are also expected; the build
  orchestrator commits them with the `build/active` transition before a layer
  base. Append-only `.project/discuss/DIALOGUE.md` and `ANSWERS.md` records are
  also expected bookkeeping: verify that their diff only appends complete
  records, then include them in the next normal orchestrator bookkeeping commit
  before establishing a layer base. Never discard, stash, or absorb another
  change.
- Before recovery or dispatch and again before each layer/wave gate, scan
  ANSWERS.md for pending required follow-ups under AGENTS.md. Apply an answer
  addressed to build only through PLAN/task bookkeeping that is legal in
  the current build state and append its disposition receipt. If it changes an
  approved upstream contract or names another owner, set `build/blocked`, link
  ANSWERS.md and the target artifact, and ask the user; never establish a new
  layer base from stale inputs.
- Fetch the configured remote and resolve its default ref and exact SHA without
  checking out, pulling, or updating the local default branch. When
  `STATE.branch` is set, bind that recorded branch — never whatever clean
  unmerged non-default branch happens to be current: require the current
  symbolic branch to equal it. Ignore ship and integrate commits for older
  milestones inherited from main. Find only a ship subject whose M00N matches
  STATE.branch (including its legacy sequence form). If one exists and is not
  an ancestor of the resolved remote-default SHA, this milestone's integration
  is incomplete: stop and return to `$gsd-path`, which routes to ship, not
  build. If that current-milestone ship is on the default without its matching
  `integrate:` commit, block as externally polluted. A newly prebound branch
  whose HEAD equals the resolved remote-default SHA is valid. When
  `STATE.branch` is null and neither archive nor shipped history exists,
  bind a `gsd-path/M00N` branch at that remote-default SHA: the active
  ROADMAP.md entry id when one exists, otherwise one plus the maximum
  existing archive prefix, otherwise M001. Use the current clean unmerged
  non-default branch only when it already has that exact name. The bound
  branch must not equal the remote default. A mismatch or a branch owned by
  another worktree blocks; never silently rebind it. A null branch after
  shipped history is an incomplete router handoff and returns to `$gsd-path`.
- When `.project/REPOSITORY.md` records `Kind: new-github`, parse its required
  fixed fields and verify the current root is the recorded linked primary
  worktree and the recorded default checkout stays clean on the remote
  default. Its local default ref may lag origin as integrations advance the
  remote default — that lag is not a violation, and the checkout is never
  entered or updated. The artifact's `GSD Path branch` is the first bound
  branch (`gsd-path/M001`); after a shipped milestone STATE.branch may be a
  later `gsd-path/M00N` created at the then-current remote-default SHA. Adopt
  the proven worktree and default checkout; do not parse STATE log prose or
  create another primary worktree.
- Persist the branch in STATE.md. On entry from `plan/done`, set STATE to
  `build/active`, append `build started`, and commit that transition with the
  expected initial `.project/` artifacts before dispatch. From then on, every
  dispatch round starts from a clean primary worktree and exact full `HEAD`
  SHA. Every orchestrator bookkeeping commit uses subject `build: <what
  changed>` plus a body that starts with `Why: <one sentence>` and may add
  `Wave:`, `Tasks:`, and `Base:` field lines. Task landing still goes
  through `isolation.py land`; do not invent those commit messages.

## Wave loop

For each `## Wave N` in PLAN.md order (a wave's tasks are the task files whose
`wave` equals N):

1. **Recover before dispatch.** Run `python3 <absolute isolation.py> recover
   --repo <absolute primary>`. It is read-only and proves every `done` task's
   landing commit from its exact stamped base (first-parent scan for
   `<task-id>: <task title>`, body `Task:`/`Files:`, the base task's declared
   path allow-list from the task file at that base, exact landing metadata,
   append-only task-file body, and
   patch equality with a retained task branch). Pending and `in-progress`
   tasks bypass landing-history proof and report retained resume state or
   `none`; failed and blocked tasks with retained isolation report
   `reconcile`. Act only on its verdicts;
   do not re-derive them in prose, rerun Verify on a proven commit, use an
   unanchored log grep, infer a SHA from `done`, or reset unknown work.
   - `recovered`: the task is landed (`land` already stamped `status: done`
     and `base`). Retire a still-present task worktree with `isolation.py
     retire` only when the report shows it present, clean, and on the task
     branch. If only `task_branch` remains, finish its proven interrupted
     retirement with `retire --branch <task_branch> --force --landed-commit
     <commit>`; both absent is valid.
   - `resume`: continue from the returned `base`, `task_branch`, and worktree
     (the primary itself when no task branch exists); when the report shows
     the worktree absent, return the task to `pending` only when ownership is
     clear.
   - `reconcile`: do not resume implementation. Preserve the returned isolate
     evidence and follow the failed/blocked reconciliation in step 2.
   - `block`: set `build/blocked` with the returned reason and stop.
   - `none`: take no recovery action for that task.

2. **Prepare the ready set.** Reconcile failed and blocked tasks, then
   select pending tasks whose dependencies are `done`. Readiness is
   continuous, not layered: a task becomes selectable the moment its last
   dependency lands, even while unrelated tasks still run. A
   `NEEDS-ORCHESTRATOR` block stays unselectable until its
   `Orchestrator answer` is recorded in the task Log. A documented plan
   defect may be repaired against INTENT.md and SYNTHESIS.md and logged before
   a new clean base. A user ruling that changes a success criterion,
   constraint, or veto is not a plan defect: set `build/blocked`, do not
   rewrite the AC, and send `$gsd-path-define` to append INTENT.md
   `## Corrections` before plan re-gates. A task Log is not that record. One failed implementation gets one logged redispatch when
   its contract remains valid. Repeated failure, ambiguous ownership, a user
   ruling, or a dependency deadlock sets build state to `blocked` and stops.
   Concurrent tasks must have disjoint `files`; serialize overlapping fix
   tasks. A retry never reuses a rejected dirty worktree: first copy its
   validated append-only task Log delta into the primary task file, record the
   rejected diff's exact path set and hash, and commit the block bookkeeping.
   After confirming every old change is task-owned, retire that exact worktree
   with `python3 <absolute isolation.py> retire --repo <absolute primary>
   --worktree <path> --branch <task_branch> --force --task-file <task path>`,
   then create the retry. If retirement was interrupted after removing the
   worktree, rerun the same command; the recorded failed or blocked task and
   its exact base prove the remaining branch before deletion. Create the retry
   from the new clean primary HEAD. After
   resolving a recoverable `build/blocked` condition, set STATE back to
   `build/active`, log the resolution, and commit it before recording that new
   dispatch-round base.

3. **Isolate every task.** Commit pending bookkeeping, record clean `HEAD` as
   this dispatch round's base — tasks dispatched in the same round share it;
   a later round unlocked by fresh landings records the later HEAD — and
   lint every ready task's brief with the bundled
   `scripts/check_task_briefs.py --repo <absolute repo root> --base <recorded
   base>` and re-check Intent coverage with
   `python3 <absolute check_handoffs.py> plan --repo <absolute repo root>`
   before creating any worktree; a lint or coverage failure is a documented plan
   defect — repair it against INTENT.md and SYNTHESIS.md, then re-establish
   the base. Then isolate each ready task with
   `python3 <absolute isolation.py> isolate-task --repo <absolute primary>
   --base <recorded base> --task-id <id> --round-size <N>` where N is the
   number of tasks in this dispatch round. Serial (`N=1`) returns the primary
   worktree and `task_branch: null` — the coder works on the bound branch.
   Parallel (`N>=2`) creates a named `gsd-path-task/<id>` branch and linked
   worktree at that base; never a detached HEAD. Set frontmatter `base`,
   `worktree`, `task_branch`, `status: in-progress`, and `agent` from the
   helper's JSON in the task file **inside the isolated worktree** (the
   primary itself when serial). Do not commit this dispatch state: it lands
   inside the task's own commit, and `recover` derives it from the task
   branch and worktree meanwhile. The primary stays clean during a parallel
   round. Do not append a dispatch Log entry: the isolated task later appends
   at that location, and two parallel appends make the cherry-pick ambiguous. Reuse a retained worktree only when
   its recorded base, branch, and task agree exactly.

4. **Dispatch the round.** Following the local runtime dispatch contract,
   spawn one implementation-capable child per task with deterministic logical
   task name `build_<task_id>`.
   Its brief contains the absolute isolated-worktree root, coder role, task
   file, task template, and the absolute INTENT.md path in that worktree.
   Add no hidden implementation context; repair a
   defective task contract before establishing the round base. Run ready work
   up to capacity. Do not wait for the whole round before unlocking
   dependents: each task landing in step 5 re-opens step 2, and a newly ready
   task dispatches in a fresh round at the current clean HEAD while unrelated
   tasks still run. The wave advances to review only when every wave task is
   `done`.

5. **Verify and land serially as results arrive.** A coder returns only
   `ready` or `blocked`; it never owns frontmatter or Git. Process each
   completion when it lands — never wait for slower in-flight tasks first;
   when several results wait, land them in task-id order.

   - For `ready`, compare the complete worktree diff to `base`. Permit only
     declared `files` plus append-only Log changes in that task file. Include
     additions, deletions, renames, and binary changes; an unexpected path
     blocks before any product commit.
   - Run the task's Verify command in that isolated worktree. This rerun is the
     authoritative task evidence; a command run in the primary or a sibling
     worktree never counts. Append its exact result to the task Log.
   - Land with
     `python3 <absolute isolation.py> land --repo <absolute primary>
     --source <isolated worktree> --base <recorded base> --task-id <id>
     --title <task title> --task-file <task path> --allow-path <each declared
     file>`. Do not invent commit or cherry-pick commands. A non-zero exit is
     a typed failure: unexpected path, conflict, or empty diff. On conflict
     the helper aborts and leaves the primary clean on the bound branch.
     Never leave task landing in progress.
   - `land` stamps `status: done`, `base`, and null `worktree`/`task_branch`
     into the task frontmatter and records `Base:` in the commit body, so the
     product commit is the task's only commit; there is no `commit`
     frontmatter field — `recover` proves the SHA from git. Do not write a
     separate bookkeeping commit. Retire the isolate with
     `python3 <absolute isolation.py> retire --repo <absolute primary>
     --worktree <isolated worktree> [--branch <task_branch>]`. Serial rounds
     return `retired: false` and leave the bound branch untouched. Each
     completed task landing re-opens step 2: dispatch newly
     ready dependents in a fresh round at the current clean HEAD instead of
     idling behind unrelated in-flight tasks.
   - A block whose Log delta leads with `NEEDS-ORCHESTRATOR:` is a contract
     question, not a failure. When the approved artifacts (PLAN.md,
     INTENT.md, SYNTHESIS.md, and the Interface contracts of every involved
     task) pin exactly one answer, append `Orchestrator answer: <answer> —
     <artifact citation>` to the task Log, return the task to `pending`,
     commit the bookkeeping, and let a later layer redispatch it; a question
     redispatch never consumes the failed-implementation redispatch. When the
     runtime's structured layer exposes a blocking ask/reply channel, relay
     the answer through it with the worker held alive per the runtime
     dispatch contract instead of redispatching. When
     the artifacts admit more than one reading, ask the user through an
     interactive user-input tool when available, record the ruling verbatim
     as the answer, and repair the task contract as a documented plan defect
     when the ruling changes it — except a ruling that changes a success
     criterion, constraint, or veto, which follows the define-Corrections
     path above. A question block creates no product commit
     and preserves the isolated worktree under the same retirement rule.
   - A blocked report, invalid diff, or failed Verify creates no product
     commit. Validate and copy the isolated task's append-only Log delta once;
     it is the coder's sole block/implementation narrative. Add orchestrator
     evidence only for a distinct diff or Verify rejection, set the task
     `blocked` or `failed`, commit the bookkeeping, and apply the recovery
     rule. Preserve the isolated worktree unless and until the explicit clean
     retry-retirement procedure in step 2 owns and removes it.

6. **Review the wave.** The build orchestrator owns wave reviews; ship never
   runs them. Only after every wave task is done, read the wave's
   `Review depth` from PLAN.md (default `full`).
   - `full`: spawn one independent reviewer using deterministic logical task
     name `review_wave_<wave>_cycle_<cycle>`. Supply every task path, its
     recorded base and proven landing commit, the reviewer role, and
     wave-review template, and the absolute INTENT.md path.
     Create and supply one verify sidecar with
     `python3 <absolute isolation.py> isolate-verify --repo <absolute primary>
     --base <recorded review base> --name wave-<N>-cycle-<C>`. Brief the
     recorded isolated Verify output per task (the Log entry the
     orchestrator appended at landing). The reviewer must not re-run that
     command or PLAN.md's project Verify. The reviewer
     stages `.project/review/wave-N.cycleC.md` there; the
     orchestrator validates it, atomically copies it to the primary canonical
     path, and only then retires that sidecar with `retire`.
   - `deep`: spawn two independent reviewers in parallel, each with a fresh
     isolated context and its own verify sidecar from `isolate-verify` at the
     recorded review base (`--name wave-<N>-cycle-<C>-contract` and
     `wave-<N>-cycle-<C>-adversarial`). Supply both every task path, its recorded base and commit,
     the reviewer role, the wave-review template, and the absolute INTENT.md
     path. The contract lens —
     logical task name `review_wave_<wave>_cycle_<cycle>_contract` — does the
     full review: apply each task's `commit^..commit` product patch to the
     recorded base, check the recorded Verify plus the isolated diff, and
     check every acceptance criterion,
     owned INTENT success criterion, and interface contract. The adversarial
     lens — logical task name
     `review_wave_<wave>_cycle_<cycle>_adversarial` — tries to kill the work:
     security holes, unhandled edge cases, failure modes, data-loss and
     concurrency risks, and missing error handling. Each stages its own file
     in its own worktree — `.project/review/wave-N.cycleC.contract.md` and
     `.project/review/wave-N.cycleC.adversarial.md`; the orchestrator validates
     each, atomically copies both to their primary canonical paths, and only
     then retires those sidecars. The wave passes only when both lenses
     return `pass`; any `blocked` lens blocks the wave, and both files'
     findings feed the fix-task batching in step 7.
   - `verify-only`: spawn no reviewer. The orchestrator writes
     `.project/review/wave-N.cycleC.md` itself from evidence it already
     holds — per task, the isolated Verify rerun and the declared-files diff
     check — recording `Depth: verify-only`. It checks each acceptance
     criterion and each INTENT success criterion owned by the wave's tasks
     against that evidence and the diff; anything it cannot
     confirm from them is a finding, not a pass. Never spawn a review panel
     at `verify-only`.
   - After the canonical inherit reviewer (or orchestrator-written
     `verify-only` file) is collected, run the optional review panel only
     for `full` and `deep`. Inspect advertised model slugs and run
     `python3 <absolute review_panel.py> resolve --plan <absolute PLAN.md>
     --intent <absolute INTENT.md> --advertised <comma slugs>
     --parent-slug <current model slug when known>` and `--charter
     <absolute .project/CHARTER.md>` when that file exists. `off` or
     `skipped` continues with no panel. Exit 2 / `error`
     blocks the wave. `ready` spawns one child per selected family with
     logical task name `review_wave_<wave>_cycle_<cycle>_panel_<family>`,
     the reviewer role in wave-panel mode, the wave-panel template, and the
     exact helper-returned model slug when the host advertises model
     selection. On `deep`, each panel brief is the adversarial lens only.
     Never override the model on the canonical reviewer. Each child stages
     its family file in its own verify sidecar from `isolate-verify`
     (`--name wave-<N>-cycle-<C>-panel-<family>`); the parent validates
     those files and runs `python3 <absolute review_panel.py> merge --kind
     wave --wave <N> --cycle <C> --inputs <family files> --output
     <absolute .project/review/wave-N.cycleC.panel.md> --mode
     <detected|named>`. The inherit reviewer remains the only Wave verdict.
     Do not average panel findings into that verdict or auto-create fix
     tasks from preference findings.
   - After the canonical inherit reviewer file (and each deep lens file) is
     on the primary path, run
     `python3 <absolute check_handoffs.py> wave --repo <absolute primary>
     --review <canonical wave-review path>`. A non-zero exit is a blocked
     wave, not a pass, including `verify-only`. Do not advance on helper
     failure.

7. **Fix or advance.** A valid canonical `pass` advances unless an
   actionable review-panel finding is waiting for a user ruling. On `blocked`, read
   `max_review_cycles` from PLAN.md (default 3). Before the cap, batch the
   findings into complete fix tasks from the task template — one task per
   disjoint file scope, not one per finding — each carrying its findings'
   failed criteria and observed evidence verbatim. Identify every finding by
   its failed criterion and carry still-open findings forward across cycles
   instead of rediscovering them: a criterion that fails again after its fix
   task ran is evidence the fix failed, never a new finding, and a re-review
   never spawns a duplicate fix task for a finding already carried. Write
   each fix task to `.project/tasks/` with `wave` set to the current wave or
   a newly appended `## Wave N` heading in PLAN.md before dispatch. Run them
   through the same isolated layer loop. At the cap, record all attempts in the STATE.md
   log and ask the user — through an interactive user-input tool when
   available — after linking the resolved absolute blocking wave review,
   whether to redirect the approach, raise the cap, or send define to amend
   INTENT.md `## Corrections` — never rewrite an AC from a Log waiver — or,
   in program flow (ROADMAP.md exists), to abandon the
   milestone under the Milestone abandon procedure — listing the
   orchestrator's recommended option first marked
   `(recommended)` with a one-line reason drawn from the review evidence.
   Never choose silently. When the canonical verdict is `pass` and
   `wave-N.cycleC.panel.md` reports `Actionable` greater than 0, do not
   advance silently: present **Outcome** with the canonical pass plus the
   actionable count, **Review** linking the panel file, and **Next** listing
   `Open fix tasks from panel findings (recommended)` first, then `Advance
   and keep panel findings as warnings`. Preference-only panel warnings do
   not block advance. On pass, commit the review artifact, the panel file
   when present, STATE.md, and wave bookkeeping, then report `wave N/M done, C review cycle(s)`.

## Completion

After every wave passes, append `build done; final review pending`, set
STATE.md directly to `phase: ship`, `status: active`, and commit that
transition as the build orchestrator's final bookkeeping. Do not run
PLAN.md's project Verify here — ship runs it once. This
keeps the primary worktree clean and avoids a separate review-phase transition
commit. Report waves, exact task commits, fixed findings, and remaining risk.
 Link the resolved absolute final wave review as the review surface and state
 that ship is next. Do not merge to the default branch, tag, mark `shipped`, or
 integrate; ship owns FINAL.md, project Verify, and those steps. When invoked
 directly, stop and tell the user to explicitly
 invoke `$gsd-path`, which routes to ship; do not invoke an explicit-only sibling
 skill yourself.
 If
 a crash leaves `build/done`, finish and commit this transition before returning
to the router.

## Milestone abandon (program flow only)

Abandon the active milestone only on an explicit user ruling — from the
review-cycle-cap escalation, a decision invalidation, or a direct request.
Require `.project/ROADMAP.md`; a single-milestone project has no abandon
path — stop and let the user decide how to restart.

1. Retire every recorded task worktree and branch with `isolation.py retire`
   after confirming ownership, recording each discarded uncommitted diff's
   exact path set and hash in the STATE.md log. Never discard work the
   recorded metadata cannot own.
2. Run the bundled `scripts/archive_milestone.py abandon --repo <absolute
   repo root> --slug <milestone slug> --reason <user ruling, verbatim>`.
   The helper archives the partial artifacts without review gates and
   persists the transaction id in STATE.archive before moving anything.
   Rerun it to resume an interrupted transaction; never select another
   sequence number.
3. Mark the milestone's ROADMAP.md entry `Status: abandoned` with its
   `Archive:` path, append the ruling and its reason to `.project/LESSONS.md`,
   and set STATE.md to `phase: roadmap`, `status: active`, `milestone:
   null`, `archive: null`, logging the abandoned archive path and the
   ruling verbatim.
4. Commit the abandon bookkeeping — archive moves, ROADMAP.md, LESSONS.md,
   STATE.md — with exact subject `build: abandon milestone <slug>` and body
   `Why: <user ruling, verbatim>`. A crash
   before this commit leaves STATE.archive set under `build/*`; recovery
   resumes from step 2.
5. Return to the router, which routes `roadmap/active` to the roadmap
   contract in re-slice mode. The abandoned code stays on the build branch
   until the next milestone's integration, then reaches the default branch as
   inert history; the re-slice plans around it. Never revert product commits
   yourself.
