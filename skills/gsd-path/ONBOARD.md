---
name: gsd-path-onboard
description: Scan an existing codebase and its documentation before any project questions are asked. Use only when the user explicitly invokes $gsd-path-onboard or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Onboarding Phase

Establish ground truth about an existing project before the grill session.
Detect, scan, and audit first; recommend and question only after the
evidence is on disk. Never grill a user about a codebase the pipeline has
not read.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions

An existing project: source files, git history, or substantive docs. If the
directory is effectively empty, skip onboarding — route to `$gsd-path-grill`.
If `.project/STATE.md` exists, require `pipeline: gsd-path/v1`; a missing or
different marker returns to `$gsd-path` for ownership checking. Legal entry is
`onboard/active|blocked`; `onboard/done` routes to grill, and any later phase
stops. If STATE.md is absent but `.project/` already contains any artifact,
return to `$gsd-path` for orphaned-state recovery instead of initializing or
overwriting it. Re-running onboarding would overwrite established context.

## Process

1. Before creating or changing `.project/` Markdown, freeze the sorted set of
   in-scope repository Markdown paths. Exclude `.project/**`, `.git`, vendored
   and generated trees, `node_modules`, and build output. Then create
   `.project/STATE.md` from the local [state template](templates/state.md) if
   missing. Set `project` to the normalized working-directory basename,
   `milestone: null`, `pipeline: gsd-path/v1`, `phase: onboard`,
   `status: active`, `branch: null`, and `archive: null`; no template
   placeholder may remain.
2. Dispatch two independent agents in parallel, following the local
   [runtime dispatch contract](references/dispatch.md) and its deterministic
   task-name rules:
   - **Codebase mapper** — role
     [codebase-mapper](references/codebase-mapper.md), template
     [codebase](templates/codebase.md), output
     `.project/research/evidence-codebase.md`, task name `onboard_codebase`.
   - **Docs auditor** — role
     [docs-auditor](references/docs-auditor.md), template
     [docs-audit](templates/docs-audit.md), output
     `.project/research/DOCS-AUDIT.md`, task name `onboard_docs`.
   Give each the absolute repo root and exclusion rule. Give the auditor the
   exact frozen inventory and `alignment mode: false`; it audits only that
   list and never rediscovers paths. Pass an existing DOCS-AUDIT.md separately
   as carry-forward input so its `## User rulings` and `planned` values remain
   verbatim. When Git has a resolvable HEAD and no non-`.project` worktree
   changes, the orchestrator creates a separate disposable detached worktree at
   that exact HEAD for each agent and includes its path and revision for
   project commands; expected new pipeline artifacts do not make product code
   dirty. Otherwise no project command may run. The orchestrator removes only
   those exact worktrees after collecting both agents.
3. Gate both artifacts against their templates: the codebase evidence needs
   a filled `## Map` plus at least three findings; the docs audit's document
   path set must equal the frozen inventory exactly and every path needs a
   verdict. Redispatch one complete corrected brief under the same logical task
   name, following the runtime dispatch contract, then set `status: blocked`
   and stop if it still fails.
4. Present the ground truth to the user, at most one screen:
   - what the project is (stack, architecture, entry points, maturity);
   - what demonstrably works (verified claims, passing verifies);
   - drift: what the docs claim that the code contradicts, and what exists
     with no documentation at all;
   - the mapper's open questions about apparent intent.
5. Set STATE.md to `phase: onboard`, `status: done`, log the transition,
   and identify `$gsd-path-grill` as next. When this phase was routed by an
   active `$gsd-path`, return control to that router so its bundled grill
   contract runs in brownfield mode. When invoked directly, stop and tell the
   user to explicitly invoke `$gsd-path` or `$gsd-path-grill`; do not invoke an
   explicit-only sibling skill yourself.

## Rules

- Scanning is read-only. Onboarding changes nothing outside `.project/`.
- Project commands run only in agent-specific disposable verification
  worktrees at a recorded clean revision; otherwise checks use static evidence
  or are `unverifiable`. They never run in the source worktree.
- Report reality, not judgment: "tests exist but 3 fail" — never "test
  hygiene is poor". The user may know exactly why those 3 fail.
- Doc-vs-code conflicts are surfaced, never auto-resolved; whether the doc
  or the code is wrong is the user's ruling, captured during the grill.
- Onboarding evidence feeds the whole pipeline: researchers treat
  `evidence-codebase.md` as a fifth standard dimension when it exists, the
  planner must match its conventions, and reviewers may cite it.
