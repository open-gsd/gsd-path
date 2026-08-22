# WORKFLOW.md — GSD Path Pipeline SOP

Idea to shipped code through a gated pipeline. The `gsd-path` router reads
`.project/STATE.md`, reports the current state, and invokes the next skill.
Every handoff is on disk; the any-phase discussion sidecar also records its
dialogue and answers on disk. AGENTS.md supplies the shared operating rules.

**Program flow.** When the work is a multi-milestone program, define runs in
program mode and writes `.project/CHARTER.md` (enduring scope and vetoes),
research and decide work at program scope, and the roadmap phase slices the
charter into `.project/ROADMAP.md` — milestone-granularity scope for every
milestone. Each milestone then runs define (milestone mode) → plan → build →
ship; the router advances to the next roadmap entry after every ship until the
program completes. While a milestone builds, the router may offer to plan the
next dependency-ready milestone in parallel under `.project/next/` (the
lookahead track); at the milestone boundary the router promotes it to the
active paths in one commit. An explicit user ruling can instead abandon a
building milestone: its partial artifacts archive without review gates, its
roadmap entry becomes immutable `abandoned`, and the roadmap re-slices the
remaining entries. CHARTER.md, ROADMAP.md, and the program `.project/SYNTHESIS.md`
persist across milestones and never archive. Without CHARTER.md the pipeline
is the single-milestone flow below.

## Agent and concurrency contract

Use the host-specific child-agent tool defined by the runtime dispatch contract
bundled in the `gsd-path` skill. Spawn independent work up to the available
child capacity and batch any remainder. Every spawned agent has isolated
context, so its brief must include the absolute role path, exact input paths,
one distinct output path, relevant constraints, the output contract, and the
deterministic logical task name defined by the dispatch contract. Do not rely
on conversation context.

Within a wave, readiness is continuous: a parallel dispatch round gives every
coder a distinct linked worktree at the clean primary HEAD recorded as its
task base; a serial round (one ready task) uses the bound branch in the
primary worktree. A dependent task dispatches in a fresh round as soon as its
dependencies land — never idling behind unrelated in-flight tasks. Task
landing stays serial, processing completions as they arrive. A same-wave task
never runs before its same-wave dependencies are done. Task verification
reconstructs the recorded base plus only that task patch; combined branch-tip
evidence does not count. The orchestrator calls `scripts/isolation.py` for
isolate, land, and retire; it never invents `git worktree add` or `--detach`.

The parent orchestrator owns dispatch and lifecycle. It binds one structured
run when the host provides one, creates one task per independent brief, waits
for terminal results, validates provenance, transfers staged artifacts from
disposable roots, and cleans up every child and temporary root before applying
a gate. Children never delegate another GSD Path child. A timeout or
cancellation is a blocked result, not a skipped result.

| Stage | Independent children | Scheduling | Parent hand-off |
| --- | --- | --- | --- |
| inspect | codebase mapper, docs auditor | two concurrent briefs | validate and transfer both artifacts |
| define | none | coordinator-led user gate | write approved INTENT.md (program mode: CHARTER.md) |
| research | assigned dimensions | concurrent up to capacity, then batches | validate RESEARCH.md and evidence |
| decide | one decider | serial | validate SYNTHESIS.md |
| roadmap | one roadmapper | serial; program flow only | validate ROADMAP.md |
| plan | one planner; zero in quick mode | serial | validate PLAN.md and task mapping |
| build | dependency-ready coders | parallel rounds, serial task landing | commit code and wave artifacts |
| ship | wave reviewer; final integration and gap reviewers | independent reviewers concurrent | verify, approve, archive, and ship |

Non-interactive phases auto-advance when their artifacts pass their gates.
User approval remains required at define, roadmap, plan, final-review patch
selection, and final shipping checkpoints. Decide auto-advances after its evidence gate
unless a `NEEDS-USER` decision remains.

Every user-facing checkpoint follows one handoff shape: **Outcome** states what
was produced or learned, **Review** links the primary canonical artifact by its
resolved absolute path, and **Next** asks the single required question or names
the next action. Supporting artifacts are summarized or linked only when they
help the decision. Write the artifact before asking, never present a bare
approval question, and after the answer relink the updated artifact before the
router continues or a direct invocation names its exact next skill.

### New GitHub repository creation

An explicit request to create a GitHub repository enters a pre-initialization
gate. Resolve and preview the GitHub owner/name, visibility, normal default
checkout, `gsd-path/M001` branch, and a distinct linked-worktree path.
Create no repository, checkout, worktree, pipeline state, journal, or preview
file until the user approves every target; present the pre-creation review
inline from the bootstrap helper's read-only `preview` result.

After approval, the bundled bootstrap helper writes an exact transaction
journal under the approved workspace before mutation. Its `create` command
creates or verifies the GitHub repository and bootstrap README, clones the
default branch, resolves its exact SHA, creates or adopts the approved GSD Path
branch and linked worktree at that SHA, then publishes STATE.md and a
fixed-format `.project/REPOSITORY.md` together with one same-filesystem
`.project/` directory rename. The default checkout remains clean,
and all pipeline artifacts live only in the linked worktree. A retry with the
same approved targets resumes from the first missing stage; any mismatch or
unowned collision blocks without deletion. The journal is removed only after
both artifacts are durable. Existing repositories do not pass through this
transaction.

## Phase 0 — Inspect (`gsd-path-inspect`)

**Input:** an existing codebase with no `.project/STATE.md`, or owned v2 state
at `inspect/active|blocked`. **Output:**
`.project/research/evidence-codebase.md` and
`.project/research/DOCS-AUDIT.md`.

The router detects brownfield before asking anything: a package manifest,
source layout, git history, or substantive docs means existing project.
Detection routes here; a truly empty directory skips to define.

Before either agent writes `.project/`, freeze a sorted Markdown inventory
that excludes `.project/**` and all vendored/generated trees. Two read-only
agents then run in parallel. The codebase mapper establishes what
actually exists: stack, entry points, architecture, conventions, maturity,
recent activity, load-bearing surprises, and open questions only the user
can settle. The docs auditor inventories every `.md`, extracts testable
claims (commands, features, structure, status, config, integrations),
verifies each against the code by the cheapest sufficient method, and
issues verdicts — `verified`, `stale`, `aspirational`, `unverifiable` —
with recorded evidence, plus a remediation queue classified `fix-doc`,
`fix-code`, or `NEEDS-USER`. The auditor uses the frozen inventory verbatim in
alignment-false mode, so neither agent's output can enter the scan.

Build, test, lint, and help commands run only in orchestrator-created,
agent-specific disposable worktrees at a recorded clean revision. If one is
not available, agents use static evidence or record `unverifiable`; they never
run project commands in the source worktree.

The orchestrator presents ground truth in one screen — what the project is,
what demonstrably works, where docs and code disagree — then enters the
define in brownfield mode. Inspect changes nothing outside `.project/`.

**Gate:** both artifacts match their templates; every claim has a verdict and
every claimless doc appears once in the descriptive list, together covering
the frozen inventory exactly; ground truth was presented before any question
was asked.

## Phase 1 — Define (`gsd-path-define`)

**Input:** a raw idea — or, brownfield, the inspection artifacts. **Output:**
`.project/intent/INTENT.md`; program mode instead writes `.project/CHARTER.md`
and defers INTENT.md to per-milestone derivation (milestone mode, `Lane:
milestone`).

Brownfield mode inverts the opening: present ground truth first, then
interview only on deltas — this milestone's goal, what must change, what
must not break (recorded as vetoes). Established facts are stated for
correction, never asked. Every doc-vs-code conflict from the audit gets a
user ruling (`fix-doc`, `fix-code`, or `accept-drift`) recorded verbatim in
both INTENT.md and DOCS-AUDIT.md's durable User rulings table. Actionable rows
start at `planned: no`; accepted
`fix-code` items become scope. The codebase map fills INTENT.md's
`## Current state` so downstream phases inherit ground truth.

Cover the problem, users, observable success, scope in, scope out, constraints,
and risks. Chase contradictions and challenge the core assumption. Record
vetoes and corrections verbatim. Unresolved items remain tagged `RESEARCH` or
`NEEDS-USER`. A user-supplied document (PRD, issue, design doc) is read
first and presented as settled coverage for correction; the interview covers
only its gaps and contradictions.

At approval define classifies the milestone lane in INTENT.md: `quick`
when scope fits at most two deliverable-sized tasks in one wave with no open
questions and no cross-wave risk; otherwise `standard`. Milestone mode — a
program milestone derived from an approved roadmap entry — records `Lane:
milestone` instead: research and decide run only when the roadmap entry lists
open questions, and planning writes a Settled-only milestone SYNTHESIS.md from
the program synthesis before dispatching the planner. The quick lane skips
research and decide — planning enters directly from `define/done`, writes
a Settled-only SYNTHESIS.md and a single wave (verify-only review depth
permitted, at most two tasks) without a planner agent, and the rest of the
pipeline runs unchanged. A quick plan that outgrows those bounds corrects the
lane to `standard` and reroutes through research.

**Gate:** the user receives the playback summary, lane, and absolute-path
Markdown link to INTENT.md before approving it.

## Phase 2 — Research (`gsd-path-research`)

**Input:** INTENT.md. **Output:** `research/RESEARCH.md` plus one evidence
file per dispatched dimension, drawn from the four standard dimensions:

- `research/evidence-domain.md`
- `research/evidence-stack.md`
- `research/evidence-pitfalls.md`
- `research/evidence-similar.md`

Brownfield: `research/evidence-codebase.md` from inspect counts as a
fifth standard input downstream — researchers read it so recommendations
fit the code that exists (the stack researcher weighs migration cost, the
pitfalls researcher checks which traps are already sprung).

Dispatch a researcher only for a dimension with something to answer — an
assigned `RESEARCH` question, an unsettled choice, or an intent risk. Skip the
rest and record each skip with its reason in the STATE.md log; never spawn a
researcher to fill a file. Run dispatched researchers with separate briefs and
output paths, batching when runtime capacity is lower than the dispatched
count. An optional fifth dimension may supplement at least one dispatched
standard dimension but never replaces the standard set. RESEARCH.md records
every standard dimension exactly once as dispatched or skipped, every question
assignment, and the exact evidence path. Every finding needs a checked source,
confidence, and a tie-back to INTENT.md.

**Gate:** RESEARCH.md records every standard dimension exactly once, every
dispatched file exists, matches the evidence template, contains at least one
finding, and answers its assigned `RESEARCH` questions; every skipped
dimension is recorded with its reason. One failed agent may be respawned once.

## Phase 3 — Decide (`gsd-path-decide`)

**Input:** INTENT.md and every dispatched evidence file. **Output:**
`.project/research/SYNTHESIS.md`.

The decider turns evidence into commitments. Each genuinely open decision
names the selection, runner-up and why it lost, cited evidence, and
confidence. A choice already settled by an intent constraint or the existing
codebase is one line under Settled citing the settling source — never a full
block with an invented runner-up.
Conflicts are ruled on or escalated; unanswered intent questions remain
visible. `## For the planner` identifies wave-one blockers, the walking
skeleton, and pitfall-to-task guidance.

**Gate:** all required decision areas are resolved and cited — as a decision
block or a Settled line naming its source; all evidence
files were considered; the planner brief is complete; and every `NEEDS-USER`
item has a recorded user ruling. Any missing, optional, or unresolved decision
blocks advancement.

## Phase 3.5 — Roadmap (`gsd-path-roadmap`)

Program flow only — requires `.project/CHARTER.md` and a program
`.project/SYNTHESIS.md`. **Input:** charter, program synthesis, and the
dispatched evidence set. **Output:** `.project/ROADMAP.md`.

The roadmapper slices the charter's full scope into the fewest
dependency-ordered, independently shippable milestones. M001 is the thinnest
end-to-end skeleton that burns the riskiest decisions. Rolling-wave: entries
carry goal, dependencies, scope in/out, success criteria, risks, and open
questions — never waves, tasks, or file lists. Charter scope coverage is
total: every `Full scope: in` item maps to a milestone, and silent scope cuts
are forbidden (`NEEDS-USER` instead). A non-empty `Open questions` entry
inserts milestone-scoped research and decide before that milestone's
planning. An approved roadmap may be re-sliced only at a milestone boundary;
`shipped` entries are immutable except Status/Archive/Integrated.

**Gate:** total charter coverage, unique ordered ids, acyclic earlier-id
dependencies, complete entry fields, no task-level detail, no vetoed scope —
and the user approves the milestone list. Approval transitions STATE to
`roadmap/done`, marks the first `pending` entry `active`, and is
checkpointed as a `.project/`-only Git commit (deferred to build's
transition commit during a new-repository transaction or before Git
exists).

## Phase 4 — Plan (`gsd-path-plan`)

**Input:** both `.project/intent/INTENT.md` and
`.project/research/SYNTHESIS.md`, plus relevant existing code. **Output:**
`.project/plan/PLAN.md` and one full task file per task in `.project/tasks/`.

Order work by risk and dependency:

1. Wave one burns down assumptions that could invalidate the plan.
2. Wave two delivers the thinnest running end-to-end slice.
3. Later waves add features, then polish.

Tasks are deliverable-sized: each is the largest coherent vertical slice —
feature plus its tests and wiring — one agent run can complete, split only
when file scopes, dependencies, or capacity force it. Every task contains
inlined context, real paths, approach constraints, an interface contract
naming the exact shapes exchanged with other tasks (`None` when
independent), an Intent coverage section, observable acceptance criteria, a
meaningful `verify` command,
declared files, deps, and
orchestrator-owned `base`/`worktree`/`task_branch`/`commit` fields initialized
to null. PLAN.md Intent coverage maps every INTENT.md success criterion to a
task AC; that task's Verify must fail if the SC is skipped.
`scripts/check_handoffs.py plan` gates the table and requires each mapped
AC to contain the INTENT criterion verbatim. `decide` copies each SC into
SYNTHESIS Settled; `wave` and `final` reject reviews that omit or restate
them. Acceptance criteria,
owned SCs, and Verify are the contract; the coder owns
implementation decisions inside the stated constraints. The planner reads
`.project/LESSONS.md` when present and assigns each wave a `Review depth` —
`full`, `verify-only` for low-risk waves, or sparingly `deep` for
irreversible or security-critical waves; wave 1 and any wave touching
authentication, payments, data migration, or concurrency stays `full` or
`deep`. PLAN.md Config may name an optional `review_panel` (`off` by
default, or `detected` / a named family list). In program flow CHARTER.md
holds the durable default; each milestone INTENT copies it and may
override. After the structural gate
and before approval, the planner runs `scripts/review_panel.py` against
advertised host model slugs and may write `.project/review/PLAN-PANEL.md`.
The panel is advisory: it never averages findings or replaces user
approval. Quick lane stays `off`.
Same-wave tasks may depend on each other only when their file scopes do not
overlap; the build executes those tasks in dependency layers. No two tasks
that can run concurrently may share a file.

**Gate:** both required inputs exist; deps resolve without cycles and each one
carries named data or a named prerequisite effect; layer and
file-scope rules hold; criteria and verifies can fail meaningfully; every
INTENT success criterion is in the Intent coverage table; tasks are
deliverable-sized with no unforced splits; INTENT and SYNTHESIS are honored;
and the user approves the wave summary. Approval is checkpointed the same
way — a `.project/`-only commit carrying the approved PLAN.md, task set, and
STATE transition — so planning artifacts never sit uncommitted until build
(the same deferral exceptions apply; patch-mode approvals are committed by
build's re-entry transition instead).

## Phase 5 — Build (`gsd-path-build`)

**Input:** the approved plan and tasks. **Output:** committed code,
`.project/BOARD.md`, updated task files, and wave reviews.

At first entry, fetch and resolve the remote default SHA without checking out
or updating the local default branch. Bind the branch recorded in STATE.branch
(and REPOSITORY.md when present) — never whatever is current when a recorded
branch exists. Validate the binding: the current symbolic branch must equal
STATE.branch, and a mismatch blocks. Ignore older milestone ship and integrate
commits inherited through main. A ship for STATE.branch's M00N, if any, must
be an ancestor of origin/main and have its matching integrate commit there;
otherwise control routes to ship or blocks as externally polluted. A newly
prebound branch at the exact remote-default SHA is valid. A fresh initial
branch with no shipped archive or current-milestone ship follows the original
rule: use the current clean unmerged non-default `gsd-path/M00N` branch, or
create `gsd-path/M00N` directly at the remote-default SHA. The bound branch
must not be the remote default. A null branch after shipped history returns to
the router for its incomplete milestone handoff. The initial binding commit
changes `plan/done` to
`build/active` before any task dispatch. Recovering a resolved `build/blocked`
state likewise commits `build/active` before a new dispatch-round base.

For each wave:

1. **Establish a clean round base.** Reconcile task state, commit pending
   bookkeeping, select dependency-ready tasks with disjoint files, and record
   exact HEAD in every ready task's `base` field. Readiness is continuous: a
   task becomes ready the moment its dependencies land, and each new
   dispatch round records the then-current clean HEAD.
2. **Isolate and dispatch.** Lint every ready task's brief at the recorded
   base with `check_task_briefs.py` and re-check Intent coverage with
   `check_handoffs.py plan`; a failure is a plan defect repaired
   before any worktree exists. Isolate each ready task with `isolation.py
   isolate-task` at that round's base (`--round-size` is the ready-set size).
   Serial rounds return the primary worktree and `task_branch: null`. Parallel
   rounds create a named `gsd-path-task/<id>` branch — never a detached HEAD.
   Record the helper's path and branch, mark the task
   in-progress in orchestrator-owned frontmatter without appending its Log,
   commit dispatch bookkeeping, then send one `worker` to each worktree with
   deterministic `build_<task_id>` identity. The coder brief includes
   INTENT.md; owned success criteria are part of done.
3. **Verify and land serially.** Process each result as it arrives —
   when several wait, in task-id order — never idling behind slower in-flight
   tasks. For each ready result,
   compare its complete base diff against declared files plus append-only task
   Log changes and re-run Verify inside that isolated worktree. Land with
   `isolation.py land`; do not invent commit or cherry-pick commands. Capture
   the returned primary full SHA, and commit that SHA plus
   `done` state before any later Git operation. A conflict, unexpected path,
   or failed Verify creates no product commit and blocks or fails the task with
   exact evidence. Every completed task landing re-opens step 1 for newly
   ready dependents.
4. **Recover deterministically.** For an in-progress/null-commit task, inspect
   its retained worktree first. If task landing may have occurred, search only
   first-parent commits in `base..STATE.branch` for exact subject equality,
   required task path, a body whose `Task:` field names that task file and whose
   sorted `Files:` list matches the changed paths, append-only Log change,
   allowed path set, and passing isolated Verify. Its binary patch and Log delta
   must equal the retained source commit/diff byte-for-byte. Exactly one proven
   candidate is recoverable; missing proof or ambiguity blocks. Never use loose
   grep or reset unknown work. A `done` task with a recorded SHA is also
   reconciled: prove that exact landing and its isolated source, commit sole
   pending bookkeeping when necessary, then retire a retained clean worktree
   with `isolation.py retire` only when both still belong to that task.
   Already-absent resources mean cleanup completed; partial or mismatched
   cleanup blocks.
5. **Review the wave.** At `Review depth: full`, the reviewer receives task
   `base` and `commit`, INTENT.md, plus
   orchestrator-created verify sidecars. For each task it applies only
   `commit^..commit` product-file patch to the recorded base, re-runs Verify,
   and checks every acceptance criterion and each INTENT success criterion
   owned by the wave. Paths outside declared files plus the assigned
   task file block; that task file may change only orchestrator fields and its
   append-only Log. At `verify-only`, no reviewer is spawned: the
   orchestrator writes the wave-review file from its own isolated Verify and
   diff evidence, and anything it cannot confirm from that evidence is a
   finding. At `deep`, two independent reviewers with fresh contexts and
   separate disposable worktrees run in parallel at the review base: the
   contract lens (`full`'s checks) staging `wave-N.cycleC.contract.md` and the
   adversarial lens (security, edge cases, failure modes, data loss) staging
   `wave-N.cycleC.adversarial.md`; both must pass, and any blocked lens blocks
   the wave with both files' findings feeding fix tasks. When PLAN.md enables
   `review_panel`, `full` and `deep` waves also spawn family-specific panel
   children (deep: adversarial lens only) and merge them into
   `wave-N.cycleC.panel.md`. The inherit reviewer remains the only Wave
   verdict; actionable panel findings (high + written criterion) require a
   user ruling before advance. A wave review is a
   single reader of the whole wave's diffs (two at `deep`), so keep waves
   narrow enough for one reviewer context (≲12 tasks) and split wider work
   into more waves at plan time.
6. **Fix and re-review.** Batch findings into complete fix tasks — one per
   disjoint file scope, not one per finding — add every fix task to the current
   or next PLAN wave and create its complete task file before dispatch, then
   execute them through the same isolated loop. Findings are keyed by their
   failed criterion and carried forward across cycles: a criterion failing
   again after its fix task ran is evidence the fix failed, never a new
   finding or a duplicate fix task. Stop for a user ruling at the
   configured cycle cap.
7. **Advance.** Only a passing wave permits the next. Commit review artifacts
   and BOARD/STATE bookkeeping at the boundary.

Coders never change orchestrator frontmatter, stage, or commit. They stay in
their assigned linked worktrees and declared files. A coder's first act is a
preflight: every path the brief names must exist at the base or be declared
in `files`, and the interface contract must match its siblings verbatim —
mismatches block immediately instead of mid-run. Task frontmatter and exact
base/commit SHAs outrank BOARD.md when resuming. A coder facing an ambiguous
contract — rather than a defective one — blocks with `NEEDS-ORCHESTRATOR:
<question>` in its task Log; the orchestrator answers from the approved
artifacts or asks the user, records the answer in the Log, and redispatches
without consuming the task's one failure retry.

For an unlanded attempt, the coder's append-only task Log delta is copied
to the primary exactly once; the orchestrator adds only distinct diff/Verify
rejection evidence. Before one allowed retry, record the rejected path set and
diff hash, prove the old dirty worktree is wholly task-owned, remove that exact
worktree and branch, and create a fresh retry from the newly committed primary
HEAD. Never redispatch a dirty failed worktree against divergent task history.

**Gate:** every wave and project Verify pass; the build orchestrator commits
the transition directly to `ship/active`, leaving a clean primary worktree.

**Milestone abandon (program flow).** On an explicit user ruling — at the
review-cycle cap, a decision invalidation, or a direct request — the
orchestrator retires the recorded task worktrees, runs the archive helper's
`abandon` command to archive the partial artifacts without review gates,
marks the roadmap entry `abandoned`, logs the ruling verbatim to LESSONS.md,
and commits the transition to `roadmap/active` for a re-slice. Abandoned
roadmap entries are immutable; the abandoned code stays on the branch until
the next integration, when it reaches the default branch as inert history,
and the re-slice plans around it.

**Lookahead (program flow).** While a milestone builds, the router may offer
to plan the next dependency-ready milestone in parallel under
`.project/next/`: define (milestone mode), research for the entry's open
questions, decide, and plan run there under their normal gates, reading
program artifacts from their active paths. The track never writes an
active-path artifact, never binds a branch, and advances only on explicit
user direction. At the milestone boundary the router promotes `next/` to
the active paths in one bookkeeping commit and routes by the promoted state.
After integration validation and before that promotion, the router uses the
bundled `pipeline_git.py bind-next` helper to move the clean primary worktree
from the shipped branch to the new unused `gsd-path/M00N` branch at the exact
current `origin/main` SHA; the helper also retires the integrated previous
branch locally and on origin. STATE.branch records the new branch, so the
promotion commit is the first commit on it. The same handoff precedes a normal
next-milestone define or single-milestone inspect. Promotion re-validates a
completed lookahead plan's task paths against the new HEAD (diff since the
approval checkpoint commit); drifted tasks return to `plan/active` for
re-gating and re-approval before build.

## Phase 6 — Ship (`gsd-path-ship`)

### Final review (`gsd-path-ship final`)

**Input:** INTENT.md success criteria and the running system. **Output:**
`.project/review/FINAL.md`, one distinct `.project/review/final-gap-N.md` per
cross-wave risk, and (when blocked) `.project/review/PATCH-FINDINGS.md`.

Run an integration reviewer and independent gap reviewers through the shared
capacity-aware dispatch contract. The integration reviewer marks each success
criterion `met`, `not-met`, or `unverifiable` with checked evidence. Each gap
reviewer records `pass` or `blocked` for its assigned end-to-end or cross-wave
risk; PLAN.md's project Verify is always one numbered risk. List only genuine
risks that could plausibly fail — a small milestone may carry only the
project-Verify risk; never pad the list. The orchestrator
creates one disposable worktree at exact reviewed HEAD
per reviewer; project commands never run in the primary worktree. Every final
artifact records that full reviewed HEAD. The parent validates and atomically
transfers each staged reviewer output to the canonical `.project/review/` path
before removing its exact disposable root. Retry may reuse an uncommitted output
only when its SHA and complete numbered risk mapping still match. Stale
uncommitted assigned outputs are regenerated. A prior blocked output committed
by the patch build may be replaced only when its findings were copied verbatim
into approved, now-done patch tasks; otherwise a stale committed output blocks.

**Gate:** `not-met`, `unverifiable`, or any blocked gap blocks shipment. Turn
the findings into a user-approved patch wave via `gsd-path-plan` patch mode and
return through the build/review loop. Passing the final gate leaves STATE.md at
`ship/active` while the archive transaction runs; `shipped/done` is written
only after the archive and manifest validate.

A missing or malformed reviewer output gets one corrective follow-up, then a
`NEEDS-USER` block rather than a fabricated patch. The orchestrator's project
Verify and its mandatory gap review must agree; repeat both once on conflict,
then surface the conflicting evidence. Only valid evidenced FINAL/gap findings
enter PATCH-FINDINGS.md and patch planning, and the build orchestrator commits
that finding set with the approved patch artifacts before executing the new
wave.

### Archive transaction

**Input:** the shipped milestone's `.project/` artifacts. **Output:**
`.project/archive/<NNN>-<milestone-slug>/` with a MANIFEST.md.

STATE.archive is a write-ahead transaction id. The bundled Python archive helper
chooses one plus the maximum numeric prefix, persists the exact target before
creating or moving, and reuses it on every retry. Shipping moves — never
deletes — every supporting document into that numbered archive: `intent/`,
`research/`, `plan/`, `tasks/`, `review/`, optional `discuss/`, and `BOARD.md`.
REPOSITORY.md, LESSONS.md, and the program artifacts (CHARTER.md,
ROADMAP.md, top-level SYNTHESIS.md) remain active project metadata; a program
ship also marks the milestone's roadmap entry `Status: shipped` with its
archive pointer inside the ship commit. MANIFEST.md is
written by same-directory temporary file plus atomic rename and lists actual
archive contents, ship date, final verdicts, wave/task/cycle counts, and
carried-forward items. A precommit helper gate validates canonical files, the
active-root allowlist, metadata, success rows, counts, and exact contents before
STATE may become shipped.

The helper rejects a CLI slug that does not match STATE.milestone, fake or
symlinked Markdown artifacts, dirty older archives, and any target already in
HEAD. Manifest criteria must match FINAL.md, cycle counts come from contiguous
real wave-review files, every final artifact names the reviewed HEAD, and Notes
must be completed. A committed target is immutable and routes only to
validation.

One exception: a DOCS-AUDIT.md with pending `planned: no` rulings is copied
atomically back into a recreated `research/` so the alignment queue survives;
the archived original keeps full history. Active and archived research may
coexist only for that byte-identical carry-forward.

Archives become read-only when committed. No phase may modify a committed
archive; the next milestone's inspection may read it. A retry with a persisted
archive path bypasses missing active review preconditions and resumes that
same transaction. The router validates every shipped state before reporting
or starting new work. An exact `.STATE.md.gsd-path-tmp` left before the
write-ahead rename is removed only by `prepare`. A crash after STATE becomes
`shipped/done` but before commit may run `prepare` and preflight only while the
target is absent from HEAD, then creates the single ship commit without
rewriting the transition.

If discussion resumes after `prepare` but before the ship commit, it copies the
archived pair back to active storage and appends there. A repeated `prepare`
accepts only a complete, valid active pair whose bytes extend both archived
files, atomically replaces the archived records, removes the active copy, and
forces manifest regeneration. Divergence or an incomplete pair blocks.

The ship phase closes the milestone with exactly one commit on the bound
branch: the shipped STATE.md, the final-review artifacts, and the archive
move with its MANIFEST.md, staged from `.project/` only, subject
`ship: M00N — <milestone-slug>` and a body naming `Archive:` and
`Reviewed-HEAD:`. Every other commit on the bound branch
belongs to the build orchestrator. The commit must contain only `.project/`
paths. There is no untracked-project fallback. Every pipeline commit —
task land, build bookkeeping, plan/roadmap/router checkpoints, ship, and
integrate — carries its defined subject plus a field body (`Task:`/`Files:`,
`Why:`, `Archive:`, or the integrate fields).

### Integration

After the postcommit validator passes, ship performs integration — the only
path from the bound branch to the default branch. The bound branch never
receives merges or back-merges, and the default checkout is never entered;
the local default branch ref may lag origin, which is harmless because
binding resolves remote SHAs. Ship runs `refresh-origin` (fetch, refresh
`origin/HEAD`, mirror published milestone tags), resolves the remote-default
name and SHA, and requires the name to be exactly `main` and different from
the bound branch. It then creates a
temporary named worktree (`gsd-path-integrate/M00N`) at the remote-default
SHA and merges the ship commit with `--no-ff` under the subject
`integrate: M00N — merge gsd-path/M00N into main` (never
`ship:` — the guard restricts those subjects to `.project/`-only paths).
When the default has no commits the ship commit lacks
(`git merge-base --is-ancestor <remote-default-sha> <ship-commit>`), the merge
is trivial; when the default has diverged, ship still attempts the merge and
lets Git decide — a conflict-free merge proceeds, and any conflict aborts the
merge, removes the temporary worktree, blocks, and escalates to the user.
Ship never auto-resolves a diverged default's conflicts. It
pushes in order the merge to `main`, the bound branch, and an
annotated tag `milestone/<NNN>-<slug>` pointing at the merge commit, and
removes the temporary worktree. Ship leaves the primary worktree and
STATE.branch on the shipped `gsd-path/M00N`; the router owns the later branch
handoff. NNN always comes from the persisted
STATE.archive sequence — never recomputed.

Integration is pending from the ship commit until a commit with a recognized
integration subject exists whose second parent is the ship commit and which is
an ancestor of origin/main. The ship commit itself is the
crash-recovery transaction id, discoverable via `find_ship_commit`; no new
STATE field. Resume is idempotent: merge only if the ship commit is not yet
an ancestor of origin/main, tag only if absent, and retry pushes freely.
The router must not report shipped or start the next milestone while
integration is pending — it routes back to ship. Once validation passes, the
router binds the next milestone branch, when one remains, before any
next-milestone file change.

**Gate:** the bundled validator proves the committed shipped state, complete
archive and manifest, valid carry-forward, clean worktree, the newest commit
with a recognized ship subject in HEAD history, `.project/`-only paths in that
commit, and no `.project` change after it; the bundled `validate-integrated`
command then proves the matching integration merge commit, its
`milestone/<NNN>-<slug>` tag, and the merge on origin/main before the router
reports shipped or starts a new milestone. The ship contract owns accepted
historical subject forms; new commits use the canonical forms above.
`integrate:` subjects in HEAD history are expected; the
no-`.project`-change-after-ship drift rule lives on the gsd-path branch, which
receives no further `.project` commits before the next milestone. Product
commits after shipping do not disturb a validated shipment.

## Standing process — Discussion (`gsd-path-discuss`)

Runs as an explicit sidecar from any active non-shipped phase: inspect,
define, research, decide, roadmap, plan, build, or ship. It does not
advance the pipeline, own STATE.md, or edit a phase handoff. A shipped
milestone is archived and must not be reopened for discussion; start a new
milestone first.

**Input:** the current user question, `AGENTS.md`, `WORKFLOW.md`,
`.project/STATE.md`, the existing `.project/discuss/` records, and the
phase-specific artifacts and code needed to answer it. **Output:**
`.project/discuss/DIALOGUE.md` and `.project/discuss/ANSWERS.md`.

The discussion skill never commits. The current phase orchestrator verifies
that each change is append-only and includes it in the next normal `.project/`
checkpoint. During build this happens before the next clean layer base; during
ship the records move into the archive and enter the single ship commit.

The discussion skill reads intent vetoes, settled synthesis decisions, and
current plan/task contracts as governing constraints. It checks the smallest
relevant code paths, callers, tests, and artifacts, distinguishes fact from
inference, and pushes back on unsupported premises with cited reasoning. It
records the user's corrections, vetoes, decisions, evidence, confidence,
unresolved `RESEARCH`/`NEEDS-USER` items, and the phase owner for follow-up.

Use existing research evidence first. If a current external fact, unfamiliar
library behavior, or unresolved risk requires more evidence, perform focused
research and record its query, sources, and confidence. Do not launch the full
research phase from an arbitrary phase: its STATE transition and RESEARCH.md
handoff belong to the router and research skill. If the answer needs formal
milestone evidence, leave a tagged follow-up for that owner.

Append one verbatim user turn and assistant answer to DIALOGUE.md, plus one
self-contained answer record to ANSWERS.md, before returning the response.
The bundled deterministic helper locks STATE, validates or recovers the pair,
allocates IDs and lineage, journals the paired publication, reports pending
receipts, and appends dispositions; the model supplies only the grounded
semantic fields.
Every record carries stable `T###` thread identity, `D###`/`A###` linkage, and
supersession. Mark a bounded resolved answer `final`; use `working` only for an
explicitly provisional turn. A required formal follow-up remains pending until
the named owner appends a `Disposition X###` receipt. The router and every phase
scan pending receipts before work and before advancement; they apply the answer
through a legal gate or block visibly rather than continuing from stale input.
A final discussion answer is durable context, not approval by itself.

**Gate:** the two append-only records exist, include the current phase/status,
and contain the evidence, research status, confidence, unresolved items, and
next owner needed to resume without chat history.

## Standing process — Docs audit (`gsd-path-docs-audit`)

Runs inside inspection and standalone only at a stable pre-build phase boundary
or `ship/blocked` with no active task. It requires owned v2 STATE and blocks
during build, active review, or shipped history. Answers one question with
evidence: does the project do what its documents say?

Inventory every `.md` → extract testable claims → verify each by the
cheapest sufficient method (run the command, read the code, run the test,
check history) → verdict with recorded evidence → remediation queue. With
`.project/` present it also audits the pipeline against itself: done tasks
must have their commit SHA and a passing Verify, SYNTHESIS decisions must
match the code's actual shape, BOARD/STATE must agree with task
frontmatter. Useful mid-project as a drift check before a milestone review.
The auditor never edits anything.

**Audit-to-plan path.** Standalone runs end with a ruling walk: the user
rules `fix-code`, `fix-doc`, or `accept-drift` on each queue item, recorded
verbatim in DOCS-AUDIT.md (`accept-drift` suppresses the item in future
audits). Actionable rulings are queued, not executed: each sits in
DOCS-AUDIT.md marked `planned: no` until the user is ready. The audit
offers alignment once at close; after that, the `gsd-path` router mentions the queue in
its status line and `gsd-path-plan` offers — per item, before any planning —
to absorb queued rulings: folded into a normal plan as ordinary tasks, or
appended via **patch mode** as one gated wave on the approved PLAN.md (one
full task per finding, evidence inlined, `fix-doc` tasks verified by
re-running the audit's claim check). Absorbed rulings get their task id in
the queue row; declined ones stay queued and are offered again. The queue
never blocks the pipeline and never enters a plan wholesale unseen. Builds
from patch waves run the normal review-gate loop. A shipped milestone never
reopens because its plan is archived; start and inspect a new milestone, then
offer carried-forward rulings during its normal planning. Final review's
evidenced `not-met` criteria and blocked gaps travel the same patch-mode road,
with their exact ordered source-file and row list.

## Handoff contract

```text
.project/
  STATE.md                   pipeline owner, phase, branch, archive transaction, log
  REPOSITORY.md              persistent new-GitHub checkout/worktree binding
  LESSONS.md                 cross-milestone lessons; appended at ship, read by the planner
  CHARTER.md                 program scope and vetoes (program flow); never archives
  ROADMAP.md                 milestone slicing (program flow); never archives
  SYNTHESIS.md               program decisions at top level (program flow); never archives
  next/                      lookahead track: next milestone's STATE.md and phase
                             artifacts while the active milestone builds (program flow)
  intent/INTENT.md           approved intent and hard constraints
  research/evidence-codebase.md   brownfield ground truth (inspect)
  research/DOCS-AUDIT.md     doc-vs-code verdicts and remediation queue
  research/RESEARCH.md       research dispatch/question/output manifest
  research/evidence-*.md     four required evidence dimensions
  research/SYNTHESIS.md      decision artifact; authoritative after decide gate
  plan/PLAN.md               waves, config, and project verify
  tasks/T###-slug.md         full contract, clean base SHA, status, exact commit SHA
  BOARD.md                   wave and escalation summary
  review/wave-N.cycleC.md    per-wave verdicts
  review/wave-N.cycleC.panel.md  optional cross-model wave panel
  review/PLAN-PANEL.md       optional cross-model plan panel
  review/final-gap-N.md      cross-wave gap verdicts
  review/FINAL.md            success-criteria verdicts
  review/PATCH-FINDINGS.md   ordered evidenced findings for patch planning
  discuss/DIALOGUE.md        append-only any-phase discussion transcript
  discuss/ANSWERS.md         append-only discussion answers and decisions
  archive/<NNN>-<slug>/      read-only shipped milestones, each with MANIFEST.md
```

At ship, everything except `STATE.md`, `REPOSITORY.md`, `LESSONS.md`, `archive/`, `next/`, and
the program artifacts (`CHARTER.md`, `ROADMAP.md`, top-level `SYNTHESIS.md`)
moves into the numbered archive; active paths above describe the current milestone
only, including the discussion records. The ship step appends one lesson line per repeat-offender criterion and
BOARD escalation to LESSONS.md before committing.

Artifact formats are bundled with the installed `gsd-path` skill. Each phase
resolves and passes their absolute paths. A missing or malformed artifact
fails its phase gate.

## Error handling

- Missing precondition: route to the phase that produces it.
- Missing or empty agent output: respawn once, then surface the failure.
- Conflicting sources of truth: stop and report; never average.
- Cycle cap, threatened veto, or checkpoint `NEEDS-USER`: ask the user —
  through an interactive user-input tool when available, with the
  recommended option listed first and justified in one line, alongside the
  real alternatives.
- Otherwise handle the problem, record it on disk, and continue.
