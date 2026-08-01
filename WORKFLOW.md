# WORKFLOW.md — GSD Path Pipeline SOP

Idea to shipped code in six gated phases. The `gsd-path` router reads
`.project/STATE.md`, reports the current state, and invokes the next skill.
Every handoff is on disk; AGENTS.md supplies the shared operating rules.

## Agent and concurrency contract

Use the host-specific child-agent tool defined by the runtime dispatch contract
bundled in the `gsd-path` skill. Spawn independent work up to the available
child capacity and batch any remainder. Every spawned agent has isolated
context, so its brief must include the absolute role path, exact input paths,
one distinct output path, relevant constraints, the output contract, and the
deterministic logical task name defined by the dispatch contract. Do not rely
on conversation context.

Within a wave, compute dependency layers. Every parallel coder receives a
distinct linked worktree at one clean layer-base SHA. Collect and integrate
the layer serially, then unlock the next layer. A same-wave task never runs
before its same-wave dependencies are done. Task verification reconstructs
the layer base plus only that task patch; combined branch-tip evidence does
not count.

## Phase 0 — Onboard (`gsd-path-onboard`, brownfield only)

**Input:** an existing codebase with no `.project/STATE.md`. **Output:**
`.project/research/evidence-codebase.md` and
`.project/research/DOCS-AUDIT.md`.

The router detects brownfield before asking anything: a package manifest,
source layout, git history, or substantive docs means existing project.
Detection routes here; a truly empty directory skips to the grill.

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
grill in brownfield mode. Onboarding changes nothing outside `.project/`.

**Gate:** both artifacts match their templates; every inventoried doc has a
verdict; ground truth was presented before any question was asked.

## Phase 1 — Grill (`gsd-path-grill`)

**Input:** a raw idea — or, brownfield, the onboarding artifacts. **Output:**
`.project/intent/INTENT.md`.

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
`NEEDS-USER`.

**Gate:** the user approves the playback summary.

## Phase 2 — Research (`gsd-path-research`)

**Input:** INTENT.md. **Output:** the four standard evidence files:

- `research/evidence-domain.md`
- `research/evidence-stack.md`
- `research/evidence-pitfalls.md`
- `research/evidence-similar.md`

Brownfield: `research/evidence-codebase.md` from onboarding counts as a
fifth standard input downstream — researchers read it so recommendations
fit the code that exists (the stack researcher weighs migration cost, the
pitfalls researcher checks which traps are already sprung).

Run all four researchers with separate briefs and output paths, batching when
runtime capacity is lower than four children. An optional fifth dimension may
supplement them but never replaces one. Every finding needs a checked source,
confidence, and a tie-back to INTENT.md.

**Gate:** all four standard files exist, match the evidence template, contain
at least one finding, and answer their assigned `RESEARCH` questions. One
failed agent may be respawned once.

## Phase 3 — Synthesize (`gsd-path-synthesize`)

**Input:** INTENT.md and all four standard evidence files. **Output:**
`.project/research/SYNTHESIS.md`.

The synthesizer turns evidence into commitments. Each applicable decision
names the selection, runner-up and why it lost, cited evidence, and confidence.
Conflicts are ruled on or escalated; unanswered intent questions remain
visible. `## For the planner` identifies wave-one blockers, the walking
skeleton, and pitfall-to-task guidance.

**Gate:** all required decision areas are resolved and cited; all evidence
files were considered; the planner brief is complete; and every `NEEDS-USER`
item has a recorded user ruling. Any missing, optional, or unresolved decision
blocks advancement.

## Phase 4 — Plan (`gsd-path-plan`)

**Input:** both `.project/intent/INTENT.md` and
`.project/research/SYNTHESIS.md`, plus relevant existing code. **Output:**
`.project/plan/PLAN.md` and one full task file per task in `.project/tasks/`.

Order work by risk and dependency:

1. Wave one burns down assumptions that could invalidate the plan.
2. Wave two delivers the thinnest running end-to-end slice.
3. Later waves add features, then polish.

Every task contains inlined context, real paths, concrete steps, observable
acceptance criteria, a meaningful `verify` command, declared files, deps, and
orchestrator-owned `base`/`worktree`/`task_branch`/`commit` fields initialized
to null.
Same-wave tasks may depend on each other only when their file scopes do not
overlap; the build executes those tasks in dependency layers. No two tasks
that can run concurrently may share a file.

**Gate:** both required inputs exist; deps resolve without cycles; layer and
file-scope rules hold; criteria and verifies can fail meaningfully; task size
is bounded; INTENT and SYNTHESIS are honored; and the user approves the wave
summary.

## Phase 5 — Build (`gsd-path-build`)

**Input:** the approved plan and tasks. **Output:** committed code,
`.project/BOARD.md`, updated task files, and wave reviews.

At first entry, fetch and resolve the remote default SHA without checking out
or updating the local default branch. Bind STATE.branch once: use the current
clean unmerged non-default branch, or create `gsd-path/<slug>` directly at the
remote-default SHA. Resume requires that exact symbolic branch; a mismatch or
merged active branch blocks. The initial binding commit changes `plan/done` to
`build/active` before any task dispatch. Recovering a resolved `build/blocked`
state likewise commits `build/active` before a new layer base.

For each wave:

1. **Establish a clean layer base.** Reconcile task state, commit pending
   bookkeeping, select dependency-ready tasks with disjoint files, and record
   exact HEAD in every ready task's `base` field.
2. **Isolate and dispatch.** Create one linked worktree and temporary branch
   per task at that same base. Record its path and branch, mark the task
   in-progress in orchestrator-owned frontmatter without appending its Log,
   commit dispatch bookkeeping, then send one `worker` to each worktree with
   deterministic `build_<task_id>` identity.
3. **Verify and integrate serially.** For each ready result in task-id order,
   compare its complete base diff against declared files plus append-only task
   Log changes and re-run Verify inside that isolated worktree. Commit there
   with exact subject `<id>: <title>`, cherry-pick onto the clean primary
   branch, capture the resulting primary full SHA, and commit that SHA plus
   `done` state before any later Git operation. A conflict, unexpected path,
   or failed Verify creates no product commit and blocks or fails the task with
   exact evidence.
4. **Recover deterministically.** For an in-progress/null-commit task, inspect
   its retained worktree first. If integration may have occurred, search only
   first-parent commits in `base..STATE.branch` for exact subject equality,
   required task path, append-only Log change, allowed path set, and passing
   isolated Verify. Its binary patch and Log delta must equal the retained
   source commit/diff byte-for-byte. Exactly one proven candidate is
   recoverable; missing proof or ambiguity blocks. Never use loose grep or
   reset unknown work. A `done` task with a recorded SHA is also reconciled:
   prove that exact integration and its isolated source, commit sole pending
   bookkeeping when necessary, then remove a retained clean worktree and
   branch only when both still belong to that task. Already-absent resources
   mean cleanup completed; partial or mismatched cleanup blocks.
5. **Review the wave.** The reviewer receives task `base` and `commit` plus
   orchestrator-created disposable worktrees. For each task it applies only
   `commit^..commit` product-file patch to the recorded base, re-runs Verify,
   and checks every criterion. Paths outside declared files plus the assigned
   task file block; that task file may change only orchestrator fields and its
   append-only Log.
6. **Fix and re-review.** Create one complete fix task per finding and execute
   it through the same isolated loop. Stop for a user ruling at the configured
   cycle cap.
7. **Advance.** Only a passing wave permits the next. Commit review artifacts
   and BOARD/STATE bookkeeping at the boundary.

Coders never change orchestrator frontmatter, stage, or commit. They stay in
their assigned linked worktrees and declared files. Task frontmatter and exact
base/commit SHAs outrank BOARD.md when resuming.

For a non-integrated attempt, the coder's append-only task Log delta is copied
to the primary exactly once; the orchestrator adds only distinct diff/Verify
rejection evidence. Before one allowed retry, record the rejected path set and
diff hash, prove the old dirty worktree is wholly task-owned, remove that exact
worktree and branch, and create a fresh retry from the newly committed primary
HEAD. Never redispatch a dirty failed worktree against divergent task history.

**Gate:** every wave and project Verify pass; the build orchestrator commits
the transition directly to `review/active`, leaving a clean primary worktree.

## Phase 6 — Final review (`gsd-path-review final`)

**Input:** INTENT.md success criteria and the running system. **Output:**
`.project/review/FINAL.md` plus one distinct
`.project/review/final-gap-N.md` per cross-wave risk.

Run an integration reviewer and independent gap reviewers through the shared
capacity-aware dispatch contract. The integration reviewer marks each success
criterion `met`, `not-met`, or `unverifiable` with checked evidence. Each gap
reviewer records `pass` or `blocked` for its assigned end-to-end or cross-wave
risk; PLAN.md's project Verify is always one numbered risk. The orchestrator
creates one disposable worktree at exact reviewed HEAD
per reviewer; project commands never run in the primary worktree. Every final
artifact records that full reviewed HEAD. Retry may reuse an uncommitted output
only when its SHA and complete numbered risk mapping still match. Stale
uncommitted assigned outputs are regenerated. A prior blocked output committed
by the patch build may be replaced only when its findings were copied verbatim
into approved, now-done patch tasks; otherwise a stale committed output blocks.

**Gate:** `not-met`, `unverifiable`, or any blocked gap blocks shipment. Turn
the findings into a user-approved patch wave via `gsd-path-plan` patch mode and
return through the build/review loop. Passing the final gate leaves STATE.md at
`review/active` while the archive transaction runs; `shipped/done` is written
only after the archive and manifest validate.

A missing or malformed reviewer output gets one corrective follow-up, then a
`NEEDS-USER` block rather than a fabricated patch. The orchestrator's project
Verify and its mandatory gap review must agree; repeat both once on conflict,
then surface the conflicting evidence. Only valid evidenced FINAL/gap findings
enter patch planning, and the build orchestrator commits that finding set with
the approved patch artifacts before executing the new wave.

## Phase 7 — Archive (automatic at ship)

**Input:** the shipped milestone's `.project/` artifacts. **Output:**
`.project/archive/<NNN>-<milestone-slug>/` with a MANIFEST.md.

STATE.archive is a write-ahead transaction id. The bundled Python archive helper
chooses one plus the maximum numeric prefix, persists the exact target before
creating or moving, and reuses it on every retry. Shipping moves — never
deletes — every supporting document into that numbered archive: `intent/`,
`research/`, `plan/`, `tasks/`, `review/`, and `BOARD.md`. MANIFEST.md is
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
archive; the next milestone's onboarding may read it. A retry with a persisted
archive path bypasses missing active review preconditions and resumes that
same transaction. The router validates every shipped state before reporting
or starting new work. An exact `.STATE.md.gsd-path-tmp` left before the
write-ahead rename is removed only by `prepare`. A crash after STATE becomes
`shipped/done` but before commit may run `prepare` and preflight only while the
target is absent from HEAD, then creates the single ship commit without
rewriting the transition.

The review phase closes the milestone with its only commit: the shipped
STATE.md, the final-review artifacts, and the archive move with its
MANIFEST.md, staged from `.project/` only, subject
`ship: <NNN>-<milestone-slug>`. Every other commit belongs to the build
orchestrator. The commit must contain only `.project/` paths. There is no
untracked-project fallback.

**Gate:** the bundled validator proves the committed shipped state, complete
archive and manifest, valid carry-forward, clean worktree, exact ship subject,
and `.project/`-only commit before the router reports shipped or starts a new
milestone.

## Standing process — Docs audit (`gsd-path-docs-audit`)

Runs inside onboarding and standalone only at a stable pre-build phase boundary
or `review/blocked` with no active task. It requires owned v1 STATE and blocks
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
reopens because its plan is archived; start and onboard a new milestone, then
offer carried-forward rulings during its normal planning. Final review's
evidenced `not-met` criteria and blocked gaps travel the same patch-mode road,
with their exact ordered source-file and row list.

## Handoff contract

```text
.project/
  STATE.md                   pipeline owner, phase, branch, archive transaction, log
  intent/INTENT.md           approved intent and hard constraints
  research/evidence-codebase.md   brownfield ground truth (onboard)
  research/DOCS-AUDIT.md     doc-vs-code verdicts and remediation queue
  research/evidence-*.md     four required evidence dimensions
  research/SYNTHESIS.md      settled, fully gated decisions
  plan/PLAN.md               waves, config, and project verify
  tasks/T###-slug.md         full contract, clean base SHA, status, exact commit SHA
  BOARD.md                   wave and escalation summary
  review/wave-N.cycleC.md    per-wave verdicts
  review/final-gap-N.md      cross-wave gap verdicts
  review/FINAL.md            success-criteria verdicts
  archive/<NNN>-<slug>/      read-only shipped milestones, each with MANIFEST.md
```

At ship, everything except `STATE.md` and `archive/` moves into the numbered
archive; active paths above describe the current milestone only.

Artifact formats are bundled with the installed `gsd-path` skill. Each phase
resolves and passes their absolute paths. A missing or malformed artifact
fails its phase gate.

## Error handling

- Missing precondition: route to the phase that produces it.
- Missing or empty agent output: respawn once, then surface the failure.
- Conflicting sources of truth: stop and report; never average.
- Cycle cap, threatened veto, or checkpoint `NEEDS-USER`: ask the user.
- Otherwise handle the problem, record it on disk, and continue.
