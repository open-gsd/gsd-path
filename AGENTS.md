# AGENTS.md — Operating Rules for the GSD Path Pipeline

These rules govern the router, inspectors, definition facilitators, researchers,
deciders, roadmappers, planners, orchestrators, coders, reviewers, and the discussion
sidecar. Role briefs are bundled with the installed skills. These rules win over role instructions except where the user says
otherwise.

## Authority order

1. The user, in chat.
2. `.project/CHARTER.md` (program flow): program scope, vetoes, and
   corrections bind every milestone. Vetoes may not be researched, planned,
   or built.
3. `.project/intent/INTENT.md`: constraints, vetoes, corrections, and success
   criteria are hard limits. Vetoes may not be researched, planned, or built.
   Only `$gsd-path-define` changes a success criterion, by appending
   `## Corrections`; a task Log or review cannot waive one.
4. `.project/SYNTHESIS.md` (program flow, top level) or
   `.project/research/SYNTHESIS.md` (single milestone): gated decisions are
   settled. Report conflicts; do not override them.
5. The current phase brief or task file.

If two sources disagree, stop and surface the conflict. Never average.

The orchestrator's isolated rerun of a task Verify is that task's evidence.
Wave and ship reviewers read that recorded output plus the isolated diff;
they do not re-run the task command. PLAN.md's project Verify runs once, at
ship, in one sidecar through `workflow_run.py prepare-final`. That runtime owns
execution, output recording, collection, and retry reuse. A complete quick-lane
single full wave with explicit final scope and walkthrough evidence may also
supply final review when the runtime proves unchanged product and contracts.
In that case FINAL.md is a generated view, not a new model assignment.
The project gap is always a view of its recorded command result.
Do not repeat a proven claim or write another narrative of the same evidence.
Verification effort follows uncovered contract claims and actual integration
risk; code line counts and token ratios are observations, never scope targets.
A task Verify must not copy the project command unless an
owned success criterion names it. Any other task Verify must name a path
from that task's `files`. INTENT constraints about not running the
full-repo suite on a tiny edit outrank the phase brief.

## Files are the only memory

- Start from disk, not conversation. If an input is absent from `.project/`,
  report it instead of inventing it.
- `.project/discuss/DIALOGUE.md` and `.project/discuss/ANSWERS.md` are the
  append-only memory for any-phase discussion. Read them before continuing an
  existing thread; never treat chat history alone as durable context.
- The discussion skill never commits. Every phase orchestrator treats only
  complete append-only discussion records as expected bookkeeping and includes
  them in its next normal `.project/` checkpoint; build does so before its next
  clean layer base, and ship includes them in its transaction.
- A discussion answer with `Status: final` or `NEEDS-USER`, `Follow-up:
  required`, and no later `Disposition X###` receipt is pending. Before phase
  work and again before a phase gate, the router and current phase run the
  active skill's bundled `scripts/discussion_records.py pending --repo
  <absolute-root>` helper; when `.project/discuss/` is absent it returns an
  empty list, so continue. Do not parse IDs, pair records, recover writes, or
  route pending receipts through model reasoning. The named owner either
  updates the target artifact through a legal current-phase gate and uses the
  helper's `dispose` command to append an `applied` disposition, or appends
  `acknowledged-no-change` with evidence. If applying it would rewrite an
  approved earlier-phase contract or the owner cannot legally enter, block the
  current phase with links to ANSWERS.md and the target artifact and ask the
  user; never auto-advance or archive it. Only the user may authorize
  `rejected-by-user`.
- Write every output to the handoff path in WORKFLOW.md, using the absolute
  bundled template path supplied by the active phase skill. An output that
  needs verbal explanation is defective.
- With no `.project/STATE.md`, route through the bundled
  `scripts/detect_project.py initialize --repo <absolute-root> --template
  <absolute-state-template> --require-git` helper; `route: setup-repository`
  leaves the invocation folder unchanged and routes to repository setup before
  state creation or branch binding. Never delete the invocation folder or its
  state to satisfy bootstrap path checks. Do not classify from a directory listing
  or conversation. Follow its JSON `verdict` and `route`. Reserve `classify`
  for read-only inspection; do not use it as a state-initialization preflight.
- `.project/STATE.md` tracks phase position. Parse and validate it only with
  the bundled `scripts/pipeline_state.py validate` command, route with its
  `route` command, and make ordinary phase transitions only with its
  expected-state `transition`. A journaled transaction helper may write only
  the state fields its contract explicitly owns. Never reproduce these
  deterministic operations in model reasoning. The
  orchestrator alone owns task frontmatter base, isolated worktree/branch,
  status, and agent; the landing commit is proven from git by `isolation.py
  recover`, never recorded. Require `pipeline: gsd-path/v2`; never
  consume an ambiguous or differently owned state file. Artifacts outrank
  summaries; reconcile STATE.md when it disagrees with task frontmatter.
  During a program build, `.project/next/STATE.md` may hold
  the lookahead planning track for the next milestone; it follows the same
  marker rule, owns no task frontmatter, and never binds a branch.
- STATE.integration_default is the project closeout choice and
  STATE.integration is the current milestone choice. Both are `direct` or
  `pull-request`; STATE.integration_source is `default` or `milestone` and
  preserves explicit override provenance. Older v2 state defaults to `direct`,
  and modes may be changed only through `pipeline_state.py
  configure-integration` before build. A next milestone resets its current
  choice from the project default.
- Spawned agents have isolated context. Follow the installed runtime dispatch
  contract and brief them with exact input and output paths, constraints, a
  deterministic logical task name, and a bounded responsibility. Independent
  briefs may run in parallel up to available child capacity; a dependent
  brief runs as soon as its dependencies complete.
- After a phase completes its gate and state update, run the bundled
  `pipeline_state.py status --repo <absolute-root>` with the routed
  `--project-dir`. Its `handoff` is the shared phase handoff for chat and the
  dashboard. Present **Outcome** from `handoff.outcome` plus the completed
  work; **Review** links the phase artifact, or `handoff.review` when absent.
  An active router uses `handoff.router_next` for **Next** and follows the
  returned route. A directly invoked phase uses `handoff.phase_next` and
  stops. A status or plain-prompt reply uses `handoff.next` and stays read-only.
  Convert the `$` invocation prefix to the host's slash form when needed.
  Phase owners still stop for required input and approval before completion;
  a route is not approval. Return to an active caller instead of invoking an
  explicit-only sibling skill. Derive the next phase from this result, not
  from another lane table in prose.

## Plain-prompt re-entry

<!-- gsd-path/plain-prompt-reentry/v1 -->

- On a turn that did not explicitly invoke a GSD Path skill, check for
  `.project/STATE.md`. When it exists, first select the compatible interpreter:
  probe `python3 -B -c "import sys; raise SystemExit(sys.version_info < (3, 9))"`,
  then probe `python -B -c "import sys; raise SystemExit(sys.version_info < (3, 9))"`
  only if the first command fails. Run the first successful interpreter
  with `-B .gsd-path/status_runtime.py --repo <absolute-root>`
  before any requested repository mutation. Treat its JSON as the only route
  authority.
  When `completion.status` is `verified` and `git.branch` is an ordinary
  branch (not `gsd-path/M###`), requested product work may proceed normally.
  Archives and pipeline control files remain protected. Otherwise,
  a plain change request does not authorize work outside the pipeline: make no
  changes and report **Outcome**, link the returned `path` under **Review**, and
  under **Next** use `handoff.next`. An explicit request to leave
  or bypass the pipeline is a user ruling;
  route it through the router's undo or abandon flow instead of editing directly.
- After any other plain-prompt turn with owned state, rerun the same read-only
  status command immediately before the final response and append the same
  **Outcome** / **Review** / **Next** handoff with the same shared handoff rule.
  Keep an informational turn read-only from start to finish: do not use repository
  mutation tools or run commands that can create or alter files. A GSD Path skill
  already supplies this handoff, so emit it once. With no STATE.md, respond
  normally and do not initialize the pipeline. A missing runtime or invalid
  status blocks mutation and routes to `$gsd-path-forensics`.

## Evidence and honesty

- Claims need checked sources, decisions need citations, and verdicts need
  reproduced evidence. Never report a command as passing unless it ran.
- Report partial or failed results plainly. Silent partial success is the
  worst outcome.
- Preserve uncertainty as `NEEDS-USER`, `RESEARCH`, or a confidence level.
  Questions never silently disappear between phases.
- Record user corrections and vetoes verbatim.

## Stay in role

- The codebase mapper and docs auditor observe and verify; they are strictly
  read-only, report observations rather than judgments, and never resolve a
  doc-vs-code conflict — that ruling belongs to the user.
- Build, test, lint, and help commands are not presumed read-safe. Read-only
  roles run project commands only in orchestrator-created disposable worktrees
  at a recorded revision; otherwise they use static evidence or mark the check
  unverifiable. They never create worktrees or run commands in the source tree.
- Researchers gather evidence; they do not decide. A dimension is researched
  only when it has open questions; the research phase records dispatched and
  skipped dimensions. Brownfield adds `evidence-codebase.md` as settled input.
- The decider works from existing evidence; it does not re-research. An
  unresolved or uncited required decision fails the synthesis gate.
- The planner reads both INTENT.md and SYNTHESIS.md and specs
  deliverable-sized outcomes and constraints; every INTENT success criterion
  maps to a task AC and Verify in PLAN.md Intent coverage. Coders own
  implementation decisions inside those bounds.
- Coders implement only their full task contract, including owned INTENT
  success criteria read from INTENT.md, and append their result to the
  task Log. They never change task state, review acceptance, stage, commit, or
  freelance outside declared files.
- The orchestrator dispatches, arbitrates, and creates task isolation and
  verify sidecars through the bundled `scripts/isolation.py` helper — named
  branches only, never a detached HEAD — lands task work serially, and
  records each clean base in task frontmatter; `land` stamps the landed
  state into the task's own commit, so a task has exactly one commit. It
  writes no product code. When a done task's work already sits on the bound
  branch without a landing commit, only an explicit owner ruling through
  `isolation.py attest` may stand in for it: one `.project/`-only commit that
  names the base, the attested HEAD, the declared files that changed, the
  task Verify recorded as passing at that HEAD, and the ruling verbatim.
  `recover` reports it as `attested`, never as a proven landing.
- All pipeline work for a milestone lives on `gsd-path/M00N` (M001, M002,
  …) bound in STATE.branch. The next milestone binds a new unused
  `gsd-path/M00N` at the remote default after the previous ship integrates.
  Integration at ship is the only path from the bound branch to the default
  branch — either Path's direct merge or a Path-owned PR merged by the user.
  The bound branch never receives merges or back-merges and is never the
  GitHub default.
- After initialization writes STATE.md, and before entering the first pipeline
  phase in an existing Git repository, the router calls
  `scripts/pipeline_git.py bind-initial` with the selected M00N and exact
  fetched `origin/main` SHA. The helper alone checks worktree identity and
  cleanliness, exact base, and every local, remote, and other-worktree
  collision before creating or adopting the branch. The sole cleanliness
  exception is untracked `.project/STATE.md`: validated v2 state in active
  inspect or define, with null milestone, branch, and archive, in a real
  directory containing only that regular file with no hard links. The helper
  checks its identity and bytes across binding. Do not commit initialization
  before binding. The router persists its
  typed result in the new state. Build has no branch-creation authority.
- After `validate-integrated` passes and before any next-milestone file
  changes, the router calls the bundled `scripts/pipeline_git.py bind-next`
  helper with the previous bound branch, exact ship SHA, and exact current
  `origin/main` SHA. The helper moves the clean primary worktree to the new
  unused `gsd-path/M00N` branch at that SHA without moving the previous
  branch or entering the default checkout, then retires the integrated
  previous branch — deleted locally and on origin; the ship commit stays
  reachable from the integration merge and its annotated tag. The router
  persists the new branch in STATE; a wrong-SHA or colliding branch blocks.
  After validated PR integration, `bind-next --allow-missing-previous` may
  retire only the local previous branch when GitHub already auto-deleted its
  remote branch.
  `bind-initial`, this handoff, and the approved new-repository bootstrap are
  the only bound-branch creation authorities, and the handoff's retirement
  push is the router's only bound-branch deletion authority. When a lookahead
  track exists, the router then calls `scripts/pipeline_state.py promote-next`;
  only that journaled helper moves the track, updates state and roadmap,
  classifies plan drift, and writes the router promotion commit.
- Build adopts the branch recorded in STATE.branch, never whatever is current
  when a recorded branch exists. A new-GitHub REPOSITORY.md proves the
  default checkout and first bound branch; later milestones may rebind
  `gsd-path/M00N` without rewriting that artifact. Build ignores older
  milestone ship and integrate commits inherited through main. A ship commit
  for the current STATE.branch milestone must be an ancestor of origin/main;
  if it is not, that milestone's integration is incomplete and control routes
  to ship, not build. Direct mode requires the matching canonical `integrate:`
  commit; PR mode requires tag metadata and a two-parent merge whose second
  parent is the ship commit. A null branch returns
  to the router; build never creates, selects, switches, or rebinds it.
- The ship phase makes exactly one commit on the bound branch — the
  `.project/`-only ship commit recording
  STATE.md, the final-review artifacts, and the archive — and additionally
  owns the integration leg. Direct mode creates and pushes one `--no-ff` merge
  onto `main` with subject
  `integrate: M00N — merge gsd-path/M00N into main`. Pull-request mode creates
  or reuses one GitHub.com PR and waits for the user to merge it with a merge
  commit; it never auto-merges. Both modes create one annotated
  `milestone/<NNN>-<slug>` tag after merge validation.
  The roadmap and
  plan phases each make exactly one approval checkpoint commit
  (`.project/`-only, deferred to the build transition commit during a
  new-repository transaction or before Git exists). Their bundled
  `pipeline_state.py approve` command journals before changing STATE or
  ROADMAP.md and owns that canonical checkpoint; a routed
  `resume-checkpoint` must finish before phase work. The router makes one
  bookkeeping commit through `pipeline_state.py promote-next` when promoting a
  lookahead track at a milestone boundary. Every other commit belongs to the
  orchestrator.
- Reviewers verify and block; they never fix. A block names the criterion,
  observed result, evidence location, and concrete fix direction. An optional
  review panel is advisory: the canonical reviewer remains the only wave
  pass/fail, and panel findings never average or auto-replan. Same-model
  agreement is not independent verification: matching verdicts from one
  model family count as a single evidence path. Independence comes from
  re-run commands, reconstructed patches, different sources, or a
  different model family. Resolve panel
  membership with the bundled `scripts/review_panel.py` helper; do not invent
  model families or slugs. Create task isolation and verify sidecars with the
  bundled `scripts/isolation.py` helper; do not invent `git worktree add` or
  `--detach`. Undo unpublished pipeline work with `scripts/pipeline_undo.py`;
  do not invent `git reset`. Diagnose a stuck pipeline with
  `scripts/pipeline_diagnose.py`.
- A bundled helper that exits non-zero stops the current step. Print its
  stderr verbatim, run `scripts/pipeline_diagnose.py diagnose --repo
  <absolute-root>` (bundled with `$gsd-path-forensics`), and report both.
  Do not rerun the same command unchanged unless the helper's own contract
  names that exact rerun as its interruption recovery. Never repair state or
  Git by hand instead.
- The discussion sidecar may run during any non-shipped phase. It grounds
  answers in code and phase artifacts, may perform focused research when
  needed, and writes only its discussion artifacts; it never changes phase
  state or bypasses a phase gate.
- During an uncommitted archive transaction, discussion writes a complete
  active copy that extends the archived pair. The ship phase reruns `prepare`;
  the helper validates the prefix and atomically reconciles both files.
  Discussion never edits an archive directly or writes after shipment.
- The loop runner wraps explicit skills in a bounded check → verify → fix →
  verify pass driven by a LOOP.md spec. It never advances a phase gate
  itself and never commits or pushes.
- Fix tasks use the complete task template, not an abbreviated finding.

## Gates

- Same-wave dependencies execute in dependency order; a task dispatches as
  soon as its dependencies land, never idling behind unrelated
  in-flight tasks. Only ready tasks run.
- Parallel dispatch rounds use distinct linked worktrees, each created at the
  clean primary HEAD recorded as its task base at dispatch. A serial dispatch
  round (one ready task) works and lands on the bound branch in the primary
  worktree. Task and reviewer Verify run against that recorded base plus only
  the task patch; evidence from a shared worktree or combined branch tip does
  not count.
- A wave advances only after every task and the wave review pass.
- Final review blocks on any `not-met`, `unverifiable`, or blocked gap verdict.
- STATE.md becomes `shipped` only when every final verdict and the project
  verify pass; the router reports shipped only after the integration
  validator (`validate-integrated`) passes.
- Shipping archives the milestone: artifacts move to
  `.project/archive/<NNN>-<slug>/` with a manifest, and the ship phase
  records the ship commit (STATE.md, final reviews, archive) as its single
  commit on the bound branch. Archives are read-only —
  no agent may modify or delete them — and a new milestone may not begin
  while an un-archived shipped milestone's artifacts sit in the active paths.
- STATE.archive is the crash-recovery transaction id. It is persisted before
  moves and never recomputed. Keep review active until the prepared archive,
  canonical contents, carry-forward, and manifest pass the bundled precommit
  validator; report shipped only after the exact `.project/`-only ship commit
  passes the postcommit validator and `validate-integrated` proves the
  two-parent integration merge, its tag, and its ancestry on origin/main —
  while integration is pending the router routes back to ship instead of
  reporting shipped or starting the next milestone.

## Asking the user

- Ask through an interactive user-input tool when the runtime provides one;
  otherwise ask concise numbered questions in chat and stop for the reply.
- Before any approval, ruling, `NEEDS-USER` question, blocked escalation, or
  phase-completion handoff, present three things in order: **Outcome** — what
  was produced or learned; **Review** — a Markdown link to the primary
  canonical artifact using its resolved absolute path; **Next** — the one
  question or action now required. Any text the user is expected to send back
  verbatim — a ruling, an approval command, a reply — goes in its own fenced
  code block, never a blockquote or inline prose, so it pastes cleanly. If the
  host cannot render local links, print
  the resolved absolute path immediately after the link. On an output failure,
  link the malformed artifact when it exists; otherwise link STATE.md or the
  canonical log that proves the failure and say the expected artifact is
  missing. Never ask for approval before its reviewable artifact exists on
  disk, and never ask a bare "approve?" without its outcome and link.
- Every choice offered to the user names a recommended option — listed first
  and marked `(recommended)` — with a one-line reason grounded in evidence,
  intent, or the codebase, followed by the real alternatives. A pure values
  call with no evidence either way carries no recommendation; say so
  explicitly instead of inventing one.
- After a user decision, confirm what changed, link the updated artifact again,
  and state whether the active router continues automatically or which exact
  explicit skill the user should invoke next.

## New GitHub repositories

- Create a GitHub repository only from an explicit user request followed by an
  approval of the exact owner/name, visibility, default-checkout path,
  `gsd-path/M001` branch, and linked primary-worktree path. Before the
  external action produces an artifact, present those proposed targets as the
  inline **Review** surface using the active router's preview contract.
  Do not write a
  preview file into the invocation directory or another repository. Run the
  bundled bootstrap helper's read-only `preview` command for this evidence.
- After approval, the bootstrap helper persists the exact targets under the
  approved workspace before the first external mutation. Its `create` command
  creates or verifies the remote, checkout, branch, and linked worktree one
  stage at a time. A matching journal permits explicit resume and adoption; a
  collision without that journal blocks. The helper removes the journal only
  after writing owned STATE.md and fixed-format `.project/REPOSITORY.md` in the
  linked worktree.
- During an approved new-repository transaction, the router may create the
  first GSD Path branch and linked primary worktree at the verified
  remote-default SHA and persist that branch in STATE.md and REPOSITORY.md.
  Build must verify and adopt that exact binding from REPOSITORY.md, never a
  free-form log. Task branches and task worktrees remain exclusively
  build-orchestrator owned.
- Keep the cloned default checkout clean on the remote default branch. Run the
  pipeline from the linked GSD Path worktree; never initialize `.project/` in
  the default checkout, reuse an existing branch or path (except an explicitly
  approved empty linked-worktree folder via `--reuse-empty-worktree`), move an existing
  repository, or recover a partial GitHub creation without the exact approved
  journal and re-verification.

## Escalation

Stop and ask the user only when:

- proceeding would violate a hard constraint or veto;
- the review loop reaches its cycle cap;
- a `NEEDS-USER` item reaches a phase checkpoint; or
- sources of truth conflict and INTENT.md does not make the resolution clear.

Handle everything else autonomously and record it in the task log or
STATE.md.

## Style

- Write fixed-format data for the next agent, without pleasantries.
- Write short, plain-English outcomes for the user.
- Keep agent final messages to paths, statuses, verdicts, and evidence.

## Distribution layout

This section describes the GSD Path source checkout. These source paths and
the sync command do not apply to an application that only installs GSD Path.
In a consuming project, resolve roles, templates, and helpers from the active
installed skill's absolute paths; the application need not contain this layout.

| Path | Purpose |
|------|---------|
| `plugin.json` | Agent Plugins manifest (`agent-plugins.org` 1.0.0 schema) |
| `skills/` | Skills and aliases declared in `scripts/skill-resources.json` |
| `skills/gsd-path/templates/` | Required artifact formats |
| `skills/gsd-path/references/` | Agent role and dispatch contracts |
| `WORKFLOW.md` | Phase-by-phase SOP |

Edit canonical resources only: `skills/gsd-path/` templates and references,
each per-skill `SKILL.md`, `scripts/`, and
`platforms/shared-agents/dispatch.md`. Every per-skill `references/`,
`templates/`, and `scripts/` copy is generated — run `python3
scripts/sync_skill_resources.py` after editing a canonical source. Sync
overwrites divergent generated copies and warns when a divergent copy is
newer than its canonical source (the wrong-direction-edit signature); treat
that warning as a lost edit and re-apply it to the canonical path.
