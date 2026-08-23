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
ship, in one sidecar. A task Verify must not copy that command unless an
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
  <absolute-root>` helper; do not parse IDs, pair records, recover writes, or
  route pending receipts through model reasoning. The named owner either
  updates the target artifact through a legal current-phase gate and uses the
  helper's `dispose` command to append an `applied` disposition, or appends
  `acknowledged-no-change` with evidence. If applying it would rewrite an
  approved earlier-phase contract or the owner cannot legally enter, block the
  current phase and ask the user; never auto-advance or archive it. Only the
  user may authorize `rejected-by-user`.
- Write every output to the handoff path in WORKFLOW.md, using the absolute
  bundled template path supplied by the active phase skill. An output that
  needs verbal explanation is defective.
- `.project/STATE.md` tracks phase position. The orchestrator alone owns task
  frontmatter base, isolated worktree/branch, status, and agent; the landing
  commit is proven from git by `isolation.py recover`, never recorded. Require
  `pipeline: gsd-path/v2`; never consume an ambiguous or differently owned
  state file. Artifacts outrank summaries; reconcile STATE.md when it
  disagrees with task frontmatter. During a program build, `.project/next/STATE.md` may hold
  the lookahead planning track for the next milestone; it follows the same
  marker rule, owns no task frontmatter, and never binds a branch.
- Spawned agents have isolated context. Follow the installed runtime dispatch
  contract and brief them with exact input and output paths, constraints, a
  deterministic logical task name, and a bounded responsibility. Independent
  briefs may run in parallel up to available child capacity; a dependent
  brief runs as soon as its dependencies complete.

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
  writes no product code.
- All pipeline work for a milestone lives on `gsd-path/M00N` (M001, M002,
  …) bound in STATE.branch. The next milestone binds a new unused
  `gsd-path/M00N` at the remote default after the previous ship integrates.
  Integration at ship is the only path from the bound branch to the default
  branch — the bound branch never receives merges or back-merges, is never
  the GitHub default, and nothing else merges, pushes, or tags on its behalf.
- After `validate-integrated` passes and before any next-milestone file
  changes, the router calls the bundled `scripts/pipeline_git.py bind-next`
  helper with the previous bound branch, exact ship SHA, and exact current
  `origin/main` SHA. The helper moves the clean primary worktree to the new
  unused `gsd-path/M00N` branch at that SHA without moving the previous
  branch or entering the default checkout, then retires the integrated
  previous branch — deleted locally and on origin; the ship commit stays
  reachable from the integration merge and its annotated tag. The router
  persists the new branch in STATE; a wrong-SHA or colliding branch blocks.
  This handoff and the approved new-repository bootstrap are the router's
  only bound-branch creation authority, and the handoff's retirement push is
  the router's only bound-branch deletion authority.
- Build adopts the branch recorded in STATE.branch, never whatever is current
  when a recorded branch exists. A new-GitHub REPOSITORY.md proves the
  default checkout and first bound branch; later milestones may rebind
  `gsd-path/M00N` without rewriting that artifact. Build ignores older
  milestone ship and integrate commits inherited through main. A ship commit
  for the current STATE.branch milestone must be an ancestor of origin/main;
  if it is not, that milestone's integration is incomplete and control routes
  to ship, not build. A current-milestone ship on main without its matching
  `integrate:` commit is externally polluted and blocks.
- The ship phase makes exactly one commit on the bound branch — the
  `.project/`-only ship commit recording
  STATE.md, the final-review artifacts, and the archive — and additionally
  owns the integration leg: one `--no-ff` merge onto `main` with subject
  `integrate: M00N — merge gsd-path/M00N into main`, one annotated
  `milestone/<NNN>-<slug>` tag, and the pushes.
  The roadmap and
  plan phases each make exactly one approval checkpoint commit
  (`.project/`-only, deferred to the build transition commit during a
  new-repository transaction or before Git exists). The router makes one
  bookkeeping commit when promoting a lookahead track at a milestone
  boundary. Every other commit belongs to the orchestrator.
- Reviewers verify and block; they never fix. A block names the criterion,
  observed result, evidence location, and concrete fix direction. An optional
  review panel is advisory: the inherit reviewer remains the only wave
  pass/fail, and panel findings never average or auto-replan. Same-model
  agreement is not independent verification: matching verdicts from one
  model family count as a single evidence path. Independence comes from
  re-run commands, reconstructed patches, different sources, or a
  different model family. Resolve panel
  membership with the bundled `scripts/review_panel.py` helper; do not invent
  model families or slugs. Create task isolation and verify sidecars with the
  bundled `scripts/isolation.py` helper; do not invent `git worktree add` or
  `--detach`.
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
  integration merge commit, its tag, and its ancestry on origin/main —
  while integration is pending the router routes back to ship instead of
  reporting shipped or starting the next milestone.

## Asking the user

- Ask through an interactive user-input tool when the runtime provides one;
  otherwise ask concise numbered questions in chat and stop for the reply.
- Before any approval, ruling, `NEEDS-USER` question, blocked escalation, or
  phase-completion handoff, present three things in order: **Outcome** — what
  was produced or learned; **Review** — a Markdown link to the primary
  canonical artifact using its resolved absolute path; **Next** — the one
  question or action now required. If the host cannot render local links, print
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
  inline **Review** surface and mark them not yet created. Do not write a
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
  the default checkout, reuse an existing branch or path, move an existing
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

| Path | Purpose |
|------|---------|
| `plugin.json` | Agent Plugins manifest (`agent-plugins.org` 1.0.0 schema) |
| `skills/` | Twelve canonical `gsd-path*` skills |
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

## Agent skills

### Issue tracker

Issues live as local markdown files under `.scratch/<feature>/`. See `docs/agents/issue-tracker.md`.

### Triage labels

Default vocabulary: `needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context: `CONTEXT.md` and `docs/adr/` at the repo root. See `docs/agents/domain.md`.
