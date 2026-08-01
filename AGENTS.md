# AGENTS.md — Operating Rules for the GSD Path Pipeline

These rules govern the router, onboarding scanners, grill, researchers,
synthesizer, planner, orchestrator, coders, and reviewers. Role briefs are bundled with the installed
skills. These rules win over role instructions except where the user says
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
- Write every output to the handoff path in WORKFLOW.md, using the absolute
  bundled template path supplied by the active phase skill. An output that
  needs verbal explanation is defective.
- `.project/STATE.md` tracks phase position. The orchestrator alone owns task
  frontmatter base, isolated worktree/branch, status, agent, and exact commit SHA. Require
  `pipeline: gsd-path/v1`; never consume an ambiguous or differently owned
  state file. Artifacts outrank summaries; reconcile STATE.md or BOARD.md when
  they disagree.
- Spawned agents have isolated context. Brief them with exact input and output
  paths, constraints, a deterministic `task_name`, explicit built-in agent
  type, `fork_turns: "none"`, and a bounded responsibility. Independent briefs
  may run in parallel up to available child capacity; dependencies run in
  layers.

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
- Researchers gather evidence; they do not decide. All four standard evidence
  files are required; brownfield adds `evidence-codebase.md` as settled input.
- The synthesizer decides from existing evidence; it does not re-research. An
  unresolved or uncited required decision fails the synthesis gate.
- The planner reads both INTENT.md and SYNTHESIS.md and leaves no judgment call
  open in a task file.
- Coders implement only their full task contract and append their result to the
  task Log. They never change task state, review acceptance, stage, commit, or
  freelance outside declared files.
- The orchestrator dispatches, arbitrates, creates isolated task and
  verification worktrees, commits task work serially, and records each clean
  base and exact full commit SHA in task frontmatter. It writes no product code.
- The review phase makes exactly one commit — the ship commit recording
  STATE.md, the final-review artifacts, and the archive. Every other commit
  belongs to the orchestrator.
- Reviewers verify and block; they never fix. A block names the criterion,
  observed result, evidence location, and concrete fix direction.
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
  `.project/archive/<NNN>-<slug>/` with a manifest, and the review phase
  records the ship commit (STATE.md, final reviews, archive) as its single
  commit. Archives are read-only —
  no agent may modify or delete them — and a new milestone may not begin
  while an un-archived shipped milestone's artifacts sit in the active paths.
- STATE.archive is the crash-recovery transaction id. It is persisted before
  moves and never recomputed. Keep review active until the prepared archive,
  canonical contents, carry-forward, and manifest pass the bundled precommit
  validator; report shipped only after the exact `.project/`-only ship commit
  passes the postcommit validator.

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
| `skills/` | Nine `$gsd-path*` skills |
| `skills/gsd-path/templates/` | Required artifact formats |
| `skills/gsd-path/references/` | Agent role and dispatch contracts |
| `WORKFLOW.md` | Phase-by-phase SOP |
