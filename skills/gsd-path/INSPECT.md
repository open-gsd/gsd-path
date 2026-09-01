---
name: gsd-path-inspect
description: Inspect an existing codebase and its documentation to establish brownfield ground truth before intent is defined. Use only when the user explicitly invokes $gsd-path-inspect or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Inspect Phase

Establish ground truth about an existing project before intent is defined.
Detect, scan, and audit first; recommend and question only after the evidence
is on disk. Never question a user about a codebase the pipeline has not read.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Before phase work and again before completion, apply the AGENTS.md
pending-answer rule with the bundled `scripts/discussion_records.py`; a
follow-up owned by inspect is resolved through its artifact gate, or the
phase blocks.

## Preconditions

If STATE.md is missing, run the bundled
`python3 <absolute-bundled-script> initialize --repo <absolute-root>
--template <absolute-state-template>` helper (`scripts/detect_project.py`) and
follow its returned JSON `verdict` / `route`. This is the only no-state
boundary; do not run `classify` first or classify from a directory listing or
conversation. If the command exits nonzero, returns `error`, or returns
`wrote_state: false`, report the error and block without routing or claiming
STATE.md was written.
- `owned` — continue under the existing-state rules below.
- `orphan` — return to `$gsd-path` for orphaned-state recovery instead of
  initializing or overwriting it.
- `greenfield` — the helper writes STATE.md at `define/active`; skip inspection
  and route to `$gsd-path-define` from this returned verdict.
- `brownfield` — require `wrote_state: true`, then continue with the helper's
  STATE.md at `inspect/active`.
If `.project/STATE.md` exists, run `python3 <absolute pipeline_state.py>
validate --repo <absolute root> [--project-dir .project/next]`; a non-zero
result returns to `$gsd-path` for ownership checking. Legal entry is
`inspect/active|blocked`; `inspect/done` routes to define, and any later phase
stops. When an active router supplies `.project/next/`, require its STATE.md
to be a regular non-symlink file and apply these rules to that track state.
When an existing state records a bound branch (single-milestone restart
or program next-milestone), require the current symbolic branch to match and
preserve both `branch` and `milestone`. Do not re-enter `inspect/done` in the
same milestone; a later milestone's `inspect/active` is a new scan.

## Process

1. Before creating or changing `.project/` Markdown, freeze the helper's exact
   stdout from `python3 <absolute check_docs_audit.py> --repo <absolute root>
   --emit-inventory` in a temporary file. Do not rediscover or edit that
   inventory. If STATE.md is now missing, restart Preconditions and route from
   the new `initialize` result; never continue from an ignored result. Record
   the SHA-256 of each existing assigned destination and preserve the existing
   DOCS-AUDIT.md in a temporary prior-audit file. Preserve an existing
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
   artifacts do not make product code dirty. Each agent writes only its
   assigned output under that sidecar and keeps it there for the gates in step
   3. Otherwise no
   project command may run.
3. Gate both artifacts against their templates: the codebase evidence needs
   a filled `## Map` plus findings as observed — no quota, but an empty
   findings section must say why; the docs audit must pass the bundled
   `python3 <absolute check_docs_audit.py> --repo <docs sidecar> --audit
   <track-relative DOCS-AUDIT.md> --inventory <frozen inventory file>`, where
   the audit path is `.project/research/DOCS-AUDIT.md` normally and
   `.project/next/research/DOCS-AUDIT.md` in Lookahead mode; add
   `--prior-audit <temporary prior-audit file>` when one was preserved
   (disjoint `## Doc:` sections and `## Descriptive docs` equal to the frozen
   inventory, every claim a valid verdict with evidence, Summary counts and
   remediation queue consistent). After each artifact passes, collect it with
   `python3 <absolute isolation.py> collect-artifact --repo <absolute primary>
   --source <returned worktree> --base <recorded HEAD> --branch <returned
   branch> --source-path <assigned track-relative path> --destination-path
   <assigned track-relative path>`, adding `--expected-destination <recorded
   prior SHA-256>` when that destination existed. Require the returned base,
   branch, source, and destination to match. Only then retire with `python3
   <absolute isolation.py> retire --repo <absolute primary> --worktree
   <returned worktree> --branch <returned branch>` without `--force`.
   Redispatch one complete corrected brief under the same logical task
   name, following the runtime dispatch contract. If it still fails, run
   `pipeline_state.py transition` with expected `inspect/active`, the exact
   current branch and archive values, `--set-status blocked`, and an event
   naming the failed artifact gate. Present **Outcome** with the failed gate, **Review**
   linking each malformed output that exists or STATE.md when an output is
   missing, and **Next** naming the one correction or user decision required;
   then stop.
4. Present the ground truth to the user, brief — a summary, not a dump:
   - what the project is (stack, architecture, entry points, maturity);
   - what demonstrably works (verified claims, passing verifies);
   - drift: what the docs claim that the code contradicts, and what exists
     with no documentation at all;
   - the mapper's open questions about apparent intent.
   Lead with the outcome, then provide absolute-path Markdown links to the
   track's `research/evidence-codebase.md` and `research/DOCS-AUDIT.md`
   (`.project/research/` normally, `.project/next/research/` in Lookahead
   mode), then state that define is next.
5. Run `python3 <absolute pipeline_state.py> transition --repo <absolute root>
   [--project-dir .project/next]
   --event "inspection artifacts passed" --expect-phase inspect --expect-status
   active --expect-milestone <current milestone or null> --expect-branch
   <current branch or null> --expect-archive <current archive or null>
   --set-phase inspect --set-status done`. This helper is the only ordinary
   STATE mutation; require its returned state to be `inspect/done`.
   Identify `$gsd-path-define` as next. When this phase was routed by an
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
