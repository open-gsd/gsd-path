---
name: gsd-path
description: Inspect .project/STATE.md, report GSD Path progress, and run the next valid phase. Use only when the user explicitly invokes $gsd-path; do not infer it from generic project, status, next-step, or resume requests.
---

# GSD Path Router

Determine the current pipeline phase, report it briefly, and run the next valid
phase. Disk is the only phase memory.

## Bundled phase execution

All phase skills are explicit-only, so their catalog entries may be absent
while this router is active. Before executing a route, read its bundled
contract fully and follow it in the same conversation:

- [inspect](INSPECT.md)
- [define](DEFINE.md)
- [research](RESEARCH.md)
- [decide](DECIDE.md)
- [roadmap](ROADMAP.md)
- [plan](PLAN.md)
- [build](BUILD.md)
- [ship](SHIP.md)
- [docs audit](DOCS-AUDIT.md)

These synchronized files are the same contracts used by direct `$gsd-path-*`
invocations. Do not depend on another skill being implicitly injected. When a
phase contract says to return to or invoke the router, resume this file's
routing loop.

## New GitHub repository creation

Enter this transaction only when the user explicitly asks to create a new
GitHub repository and no owned `.project/STATE.md` is active for that request.

1. Resolve the repository name and normalized project slug. Obtain the GitHub
   owner, one supported visibility (`public`, `private`, or `internal`), and a
   local workspace when absent; do not infer account ownership or visibility.
   Derive `gsd-path/<project-slug>` as the branch. The default checkout is
   `<resolved-workspace>/<repo-name>`; propose the distinct sibling
   `<resolved-workspace>/<repo-name>-gsd-path` as the linked worktree. The user
   may choose another workspace or worktree path before approval.
2. Resolve the bundled `scripts/bootstrap_repository.py` to an absolute path.
   Run its `preview` command with the exact owner, repository, visibility,
   workspace, default checkout, linked worktree, and optional description. The
   helper checks authentication, remote state, path parents, and any matching
   transaction journal without mutation. `mode: create` means every target is
   absent; `mode: resume` means the exact approved journal exists and the helper
   can verify and adopt completed stages; `mode: complete` names an already
   initialized binding. Any ambiguity or unowned collision blocks.
3. Present **Outcome** as a repository-creation preview. Present **Review** with
   the proposed GitHub URL, visibility, default-checkout path, GSD Path branch,
   and linked-worktree path, all marked not yet created. Present **Next** as one
   choice: `Create repository and worktree (recommended)` for `mode: create`, or
   `Resume verified repository transaction (recommended)` for `mode: resume`,
   followed by `Change details` and `Cancel`. Present this review inline; do not
   create a preview file or journal before approval. For `mode: complete`, do
   not ask to create again: link the existing REPOSITORY.md, rebase to the
   returned worktree, and continue normal routing.
4. Only after approval, run the helper's `create` command with those same exact
   arguments plus the resolved bundled `templates/state.md` and
   `templates/repository.md` paths. The helper first persists the approved
   journal, then creates or verifies the remote, clone, remote-default SHA,
   branch, and linked worktree one stage at a time. It writes STATE.md at
   `define/active` with the branch bound and writes fixed-format REPOSITORY.md;
   only then does it remove the journal. It never pushes, deletes, force-reuses,
   or adopts a target that does not match the journal.
5. On failure, present **Outcome** with the failed stage, **Review** with the
   approved targets and journal path returned or reported by the helper, and
   **Next** offering an explicit verified resume first. Rerun `preview` before
   retrying; never substitute manual cleanup or a second transaction.
6. On success, rebase the project root to the returned linked worktree. Treat
   its verified bootstrap README as greenfield. Continue with the bundled define
   contract; it reads REPOSITORY.md and records the binding under INTENT.md's
   Constraints.

Never apply this transaction to an existing repository. Ordinary existing-repo
runs keep the build contract's current branch-binding behavior.

## State ownership and initialization

1. Read `.project/STATE.md` when present. Require
   `pipeline: gsd-path/v2`. A different non-null marker belongs to another
   pipeline and blocks. A state file without the marker also blocks without
   mutation: its `branch`, `archive`, task `base`, `worktree`, and
   `task_branch` semantics cannot be inferred safely from unowned artifacts.
   Report the missing marker and ask for an explicit recovery or a new
   milestone; never stamp the marker onto unowned state.
2. With no STATE.md, inspect `.project/` before project detection. If it
   contains any file or directory, treat it as orphaned active pipeline
   artifacts or foreign state and block without mutation. List the paths and
   ask for an explicit recovery, migration, or new location; existing evidence
   and archives do not prove a safe v2 phase. Otherwise detect before asking
   anything. Exclude `.git`,
   `node_modules`, build output, vendored trees, and `.project/archive/`, then
   look for a package/build manifest, recognizable source layout, relevant Git
   history, or substantive system documentation.
   - Any signal is brownfield: create STATE.md from the local
     [state template](templates/state.md) with deterministic project slug,
     `pipeline: gsd-path/v2`, `phase: inspect`, `status: active`,
     `milestone: null`, `branch: null`, and `archive: null`; report the signal and route to
     the bundled [inspect contract](INSPECT.md).
   - No signal is greenfield: initialize the same template with
     `phase: define`, `milestone: null`, report that no brownfield signal fired, and route to
     the bundled [define contract](DEFINE.md).

## Transaction recovery first

Before ordinary routing, inspect `STATE.archive`.

- A concrete archive path is an in-progress or completed ship transaction.
  If state is `shipped/done`, run the bundled
  `python3 <absolute-bundled-script> validate --repo <root>`. When it returns
  the same archive path and exact ship SHA, run the bundled
  `python3 <absolute-bundled-script> validate-integrated --repo <root> --slug <slug>`
  with the shipped milestone slug from STATE.milestone. Report shipped only
  when both pass.
  When archive validation passes but integration is pending, invoke the
  bundled [ship contract](SHIP.md) to complete integration; never report
  shipped or advance to the next milestone while integration is pending.
- If validation fails, or state is still `ship`, invoke
  the bundled [ship contract](SHIP.md) in final archive-recovery mode. It bypasses moved
  final-review inputs, reuses the persisted path, and completes or validates
  the transaction. Never select another sequence number.
- A concrete archive path with phase `build` is an interrupted
  milestone-abandon transaction. Invoke the bundled [build
  contract](BUILD.md), which reruns the archive helper's `abandon` command
  and completes the abandon commit. Never select another sequence number.
- A concrete archive path in any phase other than `ship`, `shipped`, or
  `build` is inconsistent and blocks without moving anything.
- `shipped` with `archive: null` is invalid and unrecoverable because no
  transaction identity exists. Block and ask the user how to proceed;
  never guess an archive number or move artifacts.

Before ordinary phase routing, also inspect `.project/discuss/ANSWERS.md` when
present by running the bundled `scripts/discussion_records.py pending --repo
<absolute-root>` helper. Apply the returned pending-answer contract in
AGENTS.md and use its `dispose` command for receipts. Never auto-advance a
required follow-up without its disposition receipt; when the named owner cannot
legally enter from current state, link ANSWERS.md and the target artifact and
ask the user how to reconcile the upstream change.

## Normal routing

Report normal progress in three labeled lines: **Outcome** names the phase and
completed work, **Review** links the newest canonical artifact using its
resolved absolute path when one exists, and **Next** names the action the
router is taking or the single action required from the user. If DOCS-AUDIT.md
has `planned: no` rulings, add one alignment-queue line and offer once to route
them through the bundled [plan contract](PLAN.md); declining does not block.

Once per conversation, before the status report, run the bundled update check
`python3 <skill-dir>/scripts/check_update.py`. It is cached, offline-safe, and
prints either nothing or one notice line; append that line verbatim to the
report. Ignore any failure and never block or retry — the check is advisory
and must not delay routing.

| State | Next action |
| --- | --- |
| `inspect`, not done | bundled [inspect contract](INSPECT.md) |
| `inspect`, done | bundled [define contract](DEFINE.md), brownfield mode |
| `define`, not done | bundled [define contract](DEFINE.md) |
| `define`, done, no INTENT.md (program charter approved) | bundled [research contract](RESEARCH.md), program scope |
| `define`, done, INTENT `Lane: standard` (or no Lane line) | bundled [research contract](RESEARCH.md) |
| `define`, done, INTENT `Lane: quick` | bundled [plan contract](PLAN.md), quick mode |
| `define`, done, INTENT `Lane: milestone`, active roadmap entry has open questions | bundled [research contract](RESEARCH.md), milestone scope |
| `define`, done, INTENT `Lane: milestone`, no open questions | bundled [plan contract](PLAN.md) |
| `research`, not done | bundled [research contract](RESEARCH.md) |
| `research`, done | bundled [decide contract](DECIDE.md) |
| `decide`, not done | bundled [decide contract](DECIDE.md) |
| `decide`, done, CHARTER.md exists, no ROADMAP.md | bundled [roadmap contract](ROADMAP.md) |
| `decide`, done, ROADMAP.md exists | bundled [plan contract](PLAN.md) |
| `decide`, done, no CHARTER.md | bundled [plan contract](PLAN.md) |
| `roadmap`, not done | bundled [roadmap contract](ROADMAP.md) |
| `roadmap`, done | bundled [define contract](DEFINE.md), milestone mode |
| `plan`, not done | bundled [plan contract](PLAN.md) |
| `plan`, done | bundled [build contract](BUILD.md); approval already authorizes execution |
| `build`, active or blocked | bundled [build contract](BUILD.md), recovery mode |
| `build`, done | bundled [build contract](BUILD.md) transition recovery, then ship |
| `ship`, active | bundled [ship contract](SHIP.md), final mode |
| `ship`, blocked with valid finding sources | bundled [plan contract](PLAN.md), patch mode |
| `ship`, blocked without a valid finding source or with conflicting evidence | stop at its `NEEDS-USER` item |
| `shipped`, validated archive and completed integration | report archive path, exact ship SHA, and integration merge SHA; stop |

Auto-advance after a non-interactive phase completes unless blocked or waiting
on `NEEDS-USER`. Planning owns the single build-approval gate; never ask a
second time. One user-driven exception to the table: at a program milestone
boundary — `define/active` with no approved INTENT.md for the next milestone —
a user request to re-scope the remaining `pending` entries routes to the
bundled [roadmap contract](ROADMAP.md) in re-slice mode.

## Lookahead planning (program flow)

While STATE is `build/active` and `.project/ROADMAP.md` has a `pending`
entry whose dependencies are all `shipped` or the active milestone, offer
once per milestone to plan that next milestone in parallel with the build.
On acceptance, create `.project/next/STATE.md` from the local [state
template](templates/state.md) with `pipeline: gsd-path/v2`, `phase:
define`, `status: active`, the next dependency-ready `pending` slug as
`milestone`, `branch: null`, and `archive: null`, then follow the bundled
phase contracts in their Lookahead mode — define, research (only when the
entry lists open questions), decide, and plan — rooted at `.project/next/`.
Declining does not block; offer again only at the next milestone's build.

- The build track always takes routing precedence: the lookahead track
  advances only on explicit user direction, never by auto-advance.
- The lookahead track never touches active-path artifacts, never marks its
  roadmap entry `active`, never binds a branch, and never dispatches build
  agents. Its approval checkpoints commit `.project/` in full, `next/`
  included.
- Route the track by `.project/next/STATE.md` through the same state table,
  passing the track root to every bundled phase contract.
- A roadmap re-slice while `.project/next/` exists follows the keep/discard
  ruling in the roadmap contract before the track continues.

## Next milestone

Start only from a ship transaction that passes the bundled validator and the
bundled integration check (`validate-integrated`); pending integration routes
back to ship, never here. Preserve
the previous archive path, ship SHA, and build branch in the state Log, then:

- **Program** (ROADMAP.md exists): while `pending` entries remain, first
  promote any lookahead track. When `.project/next/STATE.md` exists, move
  whichever of `next/intent/`, `next/research/`, `next/plan/`, and
  `next/tasks/` exist to their active `.project/` paths (promotion is
  idempotent — resume an interrupted promotion by moving what remains),
  copy the track's `phase`, `status`, and `milestone` into STATE.md with
  `branch: null` and `archive: null`, mark that entry `active` in
  ROADMAP.md, fill the previously shipped entry's `Integrated:` field with
  the merge SHA of the just-completed `integrate: <NNN>-<slug>` commit,
  remove `.project/next/`, and commit the promotion with exact
  subject `router: promote lookahead milestone <slug>` — the router's only
  bookkeeping commit outside the new-repository transaction. Then route by
  the promoted state (a promoted `plan/done` goes straight to the bundled
  build contract, subject to the re-validation below). With no lookahead
  track, reset
  `phase: define`, `status: active`, `milestone` to the next dependency-ready
  `pending` slug, `branch: null`, and `archive: null`; mark that entry
  `active` in ROADMAP.md, fill the previously shipped entry's `Integrated:`
  field with the merge SHA of the just-completed `integrate: <NNN>-<slug>`
  commit, and route to the bundled [define
  contract](DEFINE.md) in milestone mode. When every entry is `shipped`,
  report the program complete against CHARTER.md's program success criteria
  and stop.
- **Single milestone** (no ROADMAP.md): reset `phase: inspect`,
  `status: active`, `milestone: null`, `branch: null`, and `archive: null`.
  The project is now brownfield, so inspect rescans current code and docs.

Re-validate a promoted `plan/done` before routing to build: diff
`--name-only` from the track's approval checkpoint commit (exact subject
`plan: build plan approved`) to HEAD and intersect the result with every
promoted task's declared `files` that exist in the repository. An empty
intersection promotes as `plan/done`. A non-empty intersection — or a
missing checkpoint commit, where drift cannot be measured — promotes as
`plan/active` with the flagged task ids (or the skip reason) in the state
log, and the bundled plan contract re-gates and re-approves the flagged
tasks against current HEAD before build. Tracks promoted at an earlier
phase skip this check.

Committed archives are read-only. CHARTER.md, ROADMAP.md, program
SYNTHESIS.md, and LESSONS.md stay active across milestones; they ship inside
the ship commit but never archive.

## Rules

- Never skip or weaken a phase gate. A build request without an approved plan
  routes through the missing producers.
- Update phase, status, and Log at every transition.
- Artifacts outrank summary state. Repair a stale pointer only when ownership
  and the producing phase are unambiguous; otherwise surface the conflict.
- Stop on a hard constraint, unresolved user ruling, or conflicting source of
  truth. Never choose a user value silently.
