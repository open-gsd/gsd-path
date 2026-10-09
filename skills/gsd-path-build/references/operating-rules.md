# Operating rules for phase work

These rules extend the project `AGENTS.md` block. Every GSD Path skill
bundles this file; spawned agents follow their role brief instead.

## Files and state

- `.project/discuss/DIALOGUE.md` and `.project/discuss/ANSWERS.md` are the
  append-only memory for any-phase discussion. Read them before continuing an
  existing thread; never treat chat history alone as durable context.
- The discussion skill never commits. Every phase orchestrator treats only
  complete append-only discussion records as expected bookkeeping and includes
  them in its next normal `.project/` checkpoint; build does so before its next
  clean layer base, and ship includes them in its transaction.
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
  STATE.integration is the current milestone choice. Both are `direct`,
  `pull-request`, or `external-landing`; STATE.integration_source is `default` or `milestone` and
  preserves explicit override provenance. Older v2 state defaults to `direct`,
  and modes may be changed only through `pipeline_state.py
  configure-integration` before build. A next milestone resets its current
  choice from the project default.
- Spawned agents have isolated context. Follow the installed runtime dispatch
  contract and brief them with exact input and output paths, constraints, a
  deterministic logical task name, and a bounded responsibility. Independent
  briefs may run in parallel up to available child capacity; a dependent
  brief runs as soon as its dependencies complete.

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
