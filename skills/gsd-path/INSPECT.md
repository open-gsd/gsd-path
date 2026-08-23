---
name: gsd-path-inspect
description: Inspect an existing codebase and its documentation to establish brownfield ground truth before intent is defined. Use only when the user explicitly invokes $gsd-path-inspect or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Inspect Phase

Establish ground truth about an existing project before intent is defined.
Detect, scan, and audit first; recommend and question only after the evidence
is on disk. Never question a user about a codebase the pipeline has not read.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

Before phase work and again before completion, run the bundled
`scripts/discussion_records.py pending --repo <absolute-root>`; when
`.project/discuss/ANSWERS.md` is absent, continue. Resolve a reported
required follow-up owned by inspect through its legal artifact gate and
record its disposition with the helper's `dispose` command; otherwise block
with links to ANSWERS.md and the target artifact rather than advancing stale
input.

## Preconditions

If STATE.md is missing, run the bundled
`python3 <absolute-bundled-script> classify --repo <absolute-root>` helper
(`scripts/detect_project.py`) and follow its JSON `verdict` / `route`. Do not
classify from a directory listing or conversation.
- `owned` — continue under the existing-state rules below.
- `orphan` — return to `$gsd-path` for orphaned-state recovery instead of
  initializing or overwriting it.
- `greenfield` — skip inspection; route to `$gsd-path-define`.
- `brownfield` — continue; create STATE.md in Process step 1 if missing.
If `.project/STATE.md` exists, require `pipeline: gsd-path/v2`; a missing or
different marker returns to `$gsd-path` for ownership checking. Legal entry is
`inspect/active|blocked`; `inspect/done` routes to define, and any later phase
stops. When an existing state records a bound branch (single-milestone restart
or program next-milestone), require the current symbolic branch to match and
preserve both `branch` and `milestone`. Do not re-enter `inspect/done` in the
same milestone; a later milestone's `inspect/active` is a new scan.

## Process

1. Before creating or changing `.project/` Markdown, freeze the sorted set of
   in-scope repository Markdown paths. Exclude `.project/**`, `.git`, vendored
   and generated trees, `node_modules`, and build output. Then create
   `.project/STATE.md` from the local [state template](templates/state.md) if
   missing. Set `project` to the normalized working-directory basename,
   `milestone: null`, `pipeline: gsd-path/v2`, `phase: inspect`,
   `status: active`, `branch: null`, and `archive: null` only for a newly
   created state; no template placeholder may remain. Preserve an existing
   router-bound branch and milestone.
2. Dispatch two independent agents in parallel, following the local
   [runtime dispatch contract](references/dispatch.md) and its deterministic
   task-name rules:
   - **Codebase mapper** — role
     [codebase-mapper](references/codebase-mapper.md), template
     [codebase](templates/codebase.md), output
     `.project/research/evidence-codebase.md` (`.project/next/research/` in
     Lookahead mode), task name `inspect_codebase`.
   - **Docs auditor** — role
     [docs-auditor](references/docs-auditor.md), template
     [docs-audit](templates/docs-audit.md), output
     `.project/research/DOCS-AUDIT.md` (same next/ prefix in Lookahead mode),
     task name `inspect_docs`.
   Give each the absolute repo root and exclusion rule. Give the auditor the
   exact frozen inventory and `alignment mode: false`; it audits only that
   list and never rediscovers paths. The frozen inventory travels inside the
   dispatch brief; never persist it as a `.project/` sidecar file. Pass an existing DOCS-AUDIT.md separately
   as carry-forward input so its `## User rulings` and `planned` values remain
   verbatim. When Git has a resolvable HEAD and no non-`.project` worktree
   changes, the orchestrator creates a verify sidecar for each agent with
   `python3 <absolute isolation.py> isolate-verify --repo <absolute primary>
   --base <HEAD> --name inspect-codebase` and `--name inspect-docs`, and
   includes its path and revision for project commands; expected new pipeline
   artifacts do not make product code dirty. Each agent stages its assigned
   output under that sidecar; the orchestrator validates and atomically
   transfers both files to the primary `.project/` paths (the track's
   `.project/next/` paths in Lookahead mode) before retiring only
   those sidecars with `isolation.py retire`. Otherwise no
   project command may run.
3. Gate both artifacts against their templates: the codebase evidence needs
   a filled `## Map` plus findings as observed — no quota, but an empty
   findings section must say why; the docs audit must pass the bundled
   `python3 <absolute check_docs_audit.py> --repo <absolute root> --inventory <frozen inventory file>`
   (disjoint `## Doc:` sections and `## Descriptive docs` equal to the frozen
   inventory, every claim a valid verdict with evidence, Summary counts and
   remediation queue consistent). Redispatch one complete corrected brief under the same logical task
   name, following the runtime dispatch contract, then set `status: blocked`
   if it still fails. Present **Outcome** with the failed gate, **Review**
   linking each malformed output that exists or STATE.md when an output is
   missing, and **Next** naming the one correction or user decision required;
   then stop.
4. Present the ground truth to the user, brief — a summary, not a dump:
   - what the project is (stack, architecture, entry points, maturity);
   - what demonstrably works (verified claims, passing verifies);
   - drift: what the docs claim that the code contradicts, and what exists
     with no documentation at all;
   - the mapper's open questions about apparent intent.
   Lead with the outcome, then provide absolute-path Markdown links to
   `.project/research/evidence-codebase.md` and
     `.project/research/DOCS-AUDIT.md`, then state that define is next.
5. Set STATE.md to `phase: inspect`, `status: done`, log the transition,
   and identify `$gsd-path-define` as next. When this phase was routed by an
   active `$gsd-path`, return control to that router so its bundled define
   contract runs in brownfield mode (and milestone mode when ROADMAP.md
   exists). When invoked directly, stop and tell the
   user to explicitly invoke `$gsd-path`, which routes to define; do not invoke
   an explicit-only sibling skill yourself.

## Lookahead mode

Entered only when an active router supplies the lookahead track root
`.project/next/` while the active STATE.md is `build/active` in program
flow. Evaluate every state and artifact precondition against the track:
`.project/next/STATE.md` is the state file and the outputs are
`.project/next/research/evidence-codebase.md` and
`.project/next/research/DOCS-AUDIT.md`. Freeze the inventory from the
repository root as usual. Carry forward the active
`.project/research/DOCS-AUDIT.md` when it exists so its `## User rulings`
and `planned` values remain verbatim; otherwise carry forward a track-local
audit if present. Never write an active-path artifact.

## Rules

- Scanning is read-only. Inspection changes nothing outside `.project/`.
- Project commands run only in agent-specific disposable verification
  worktrees at a recorded clean revision; otherwise checks use static evidence
  or are `unverifiable`. They never run in the source worktree.
- Report reality, not judgment: "tests exist but 3 fail" — never "test
  hygiene is poor". The user may know exactly why those 3 fail.
- Doc-vs-code conflicts are surfaced, never auto-resolved; whether the doc
  or the code is wrong is the user's ruling, captured while defining intent.
- Inspection evidence feeds the whole pipeline: researchers treat
  `evidence-codebase.md` as a fifth standard dimension when it exists, the
  planner must match its conventions, and reviewers may cite it.
