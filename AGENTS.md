# AGENTS.md — Operating Rules for the GSD Path Pipeline

These rules govern the router, inspectors, definition facilitators, researchers,
deciders, planners, orchestrators, coders, reviewers, and the discussion
sidecar. Role briefs are bundled with the installed skills. These rules win over role instructions except where the user says
otherwise.

## Authority order

1. The user, in chat.
2. `.project/intent/INTENT.md`: constraints, vetoes, and corrections are hard
   limits. Vetoes may not be researched, planned, or built.
3. `.project/research/SYNTHESIS.md`: gated decisions are settled. Report
   conflicts; do not override them.
4. The current phase brief or task file.

If two sources disagree, stop and surface the conflict. Never average.

## Files are the only memory

- Start from disk, not conversation. If an input is absent from `.project/`,
  report it instead of inventing it.
- `.project/discuss/DIALOGUE.md` and `.project/discuss/ANSWERS.md` are the
  append-only memory for any-phase discussion. Read them before continuing an
  existing thread; never treat chat history alone as durable context.
- The discussion skill never commits. Every phase orchestrator treats only
  complete append-only discussion records as expected bookkeeping and includes
  them in its next normal `.project/` checkpoint; build does so before its next
  clean layer base, and review includes them in the ship transaction.
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
  frontmatter base, isolated worktree/branch, status, agent, and exact commit SHA. Require
  `pipeline: gsd-path/v1`; never consume an ambiguous or differently owned
  state file. Artifacts outrank summaries; reconcile STATE.md or BOARD.md when
  they disagree.
- Spawned agents have isolated context. Follow the installed runtime dispatch
  contract and brief them with exact input and output paths, constraints, a
  deterministic logical task name, and a bounded responsibility. Independent
  briefs may run in parallel up to available child capacity; dependencies run
  in layers.

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
  deliverable-sized outcomes and constraints; coders own implementation
  decisions inside them.
- Coders implement only their full task contract and append their result to the
  task Log. They never change task state, review acceptance, stage, commit, or
  freelance outside declared files.
- The orchestrator dispatches, arbitrates, creates isolated task and
  verification worktrees, commits task work serially, and records each clean
  base and exact full commit SHA in task frontmatter. It writes no product code.
- The ship phase makes exactly one commit — the ship commit recording
  STATE.md, the final-review artifacts, and the archive. Every other commit
  belongs to the orchestrator.
- Reviewers verify and block; they never fix. A block names the criterion,
  observed result, evidence location, and concrete fix direction.
- The discussion sidecar may run during any non-shipped phase. It grounds
  answers in code and phase artifacts, may perform focused research when
  needed, and writes only its discussion artifacts; it never changes phase
  state or bypasses a phase gate.
- During an uncommitted archive transaction, discussion writes a complete
  active copy that extends the archived pair. Review reruns `prepare`; the
  helper validates the prefix and atomically reconciles both files. Discussion
  never edits an archive directly or writes after shipment.
- Fix tasks use the complete task template, not an abbreviated finding.

## Gates

- Same-wave dependencies execute in dependency layers; only ready tasks run.
- Parallel coders use distinct linked worktrees at one clean layer base. Task
  and reviewer Verify run against that base plus only the task patch; evidence
  from a shared worktree or combined branch tip does not count.
- A wave advances only after every task and the wave review pass.
- Final review blocks on any `not-met`, `unverifiable`, or blocked gap verdict.
- STATE.md becomes `shipped` only when every final verdict and the project
  verify pass.
- Shipping archives the milestone: artifacts move to
  `.project/archive/<NNN>-<slug>/` with a manifest, and the ship phase
  records the ship commit (STATE.md, final reviews, archive) as its single
  commit. Archives are read-only —
  no agent may modify or delete them — and a new milestone may not begin
  while an un-archived shipped milestone's artifacts sit in the active paths.
- STATE.archive is the crash-recovery transaction id. It is persisted before
  moves and never recomputed. Keep review active until the prepared archive,
  canonical contents, carry-forward, and manifest pass the bundled precommit
  validator; report shipped only after the exact `.project/`-only ship commit
  passes the postcommit validator.

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
  `gsd-path/<project-slug>` branch, and linked primary-worktree path. Before the
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
- The router has one narrow exception to build's branch ownership: during an
  approved new-repository transaction, it may create the GSD Path branch and
  linked primary worktree at the verified remote-default SHA and persist that
  branch in STATE.md and REPOSITORY.md. Build must verify and adopt that exact
  binding from REPOSITORY.md, never a free-form log. Task branches and task
  worktrees remain exclusively build-orchestrator owned.
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

Handle everything else autonomously and record it in the task log, BOARD.md,
or STATE.md.

## Style

- Write fixed-format data for the next agent, without pleasantries.
- Write short, plain-English outcomes for the user.
- Keep agent final messages to paths, statuses, verdicts, and evidence.

## Distribution layout

| Path | Purpose |
|------|---------|
| `skills/` | Ten canonical `gsd-path*` skills plus four deprecated aliases |
| `skills/gsd-path/templates/` | Required artifact formats |
| `skills/gsd-path/references/` | Agent role and dispatch contracts |
| `WORKFLOW.md` | Phase-by-phase SOP |
