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

- [onboard](ONBOARD.md)
- [grill](GRILL.md)
- [research](RESEARCH.md)
- [synthesize](SYNTHESIZE.md)
- [plan](PLAN.md)
- [build](BUILD.md)
- [review](REVIEW.md)
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
   `grill/active` with the branch bound and writes fixed-format REPOSITORY.md;
   only then does it remove the journal. It never pushes, deletes, force-reuses,
   or adopts a target that does not match the journal.
5. On failure, present **Outcome** with the failed stage, **Review** with the
   approved targets and journal path returned or reported by the helper, and
   **Next** offering an explicit verified resume first. Rerun `preview` before
   retrying; never substitute manual cleanup or a second transaction.
6. On success, rebase the project root to the returned linked worktree. Treat
   its verified bootstrap README as greenfield. Continue with the bundled grill
   contract; it reads REPOSITORY.md and records the binding under INTENT.md's
   Constraints.

Never apply this transaction to an existing repository. Ordinary existing-repo
runs keep the build contract's current branch-binding behavior.

## State ownership and initialization

1. Read `.project/STATE.md` when present. Require
   `pipeline: gsd-path/v1`. A different non-null marker belongs to another
   pipeline and blocks. A pre-marker state also blocks without mutation: v1
   requires `branch`, `archive`, task `base`, `worktree`, and `task_branch`
   semantics that cannot be inferred safely from older artifacts. Report the
   missing schema fields and ask for an explicit migration or a new milestone;
   never stamp v1 onto legacy `ogsd` or pre-v1 GSD Path state.
2. With no STATE.md, inspect `.project/` before project detection. If it
   contains any file or directory, treat it as orphaned active pipeline
   artifacts or foreign state and block without mutation. List the paths and
   ask for an explicit recovery, migration, or new location; existing evidence
   and archives do not prove a safe v1 phase. Otherwise detect before asking
   anything. Exclude `.git`,
   `node_modules`, build output, vendored trees, and `.project/archive/`, then
   look for a package/build manifest, recognizable source layout, relevant Git
   history, or substantive system documentation.
   - Any signal is brownfield: create STATE.md from the local
     [state template](templates/state.md) with deterministic project slug,
     `pipeline: gsd-path/v1`, `phase: onboard`, `status: active`,
     `milestone: null`, `branch: null`, and `archive: null`; report the signal and route to
     the bundled [onboard contract](ONBOARD.md).
   - No signal is greenfield: initialize the same template with
     `phase: grill`, `milestone: null`, report that no brownfield signal fired, and route to
     the bundled [grill contract](GRILL.md).

## Transaction recovery first

Before ordinary routing, inspect `STATE.archive`.

- A concrete archive path is an in-progress or completed ship transaction.
  If state is `shipped/done`, run the bundled
  `python3 <absolute-bundled-script> validate --repo <root>`. Report shipped
  only when it returns the same archive path and exact ship SHA.
- If validation fails, or state is still `review`, invoke
  the bundled [review contract](REVIEW.md) in final archive-recovery mode. It bypasses moved
  final-review inputs, reuses the persisted path, and completes or validates
  the transaction. Never select another sequence number.
- A concrete archive path in any phase other than `review` or `shipped` is
  inconsistent and blocks without moving anything.
- In v1, `shipped` with `archive: null` is invalid and unrecoverable because no
  transaction identity exists. Block and request explicit pre-v1 migration;
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
| `onboard`, not done | bundled [onboard contract](ONBOARD.md) |
| `onboard`, done | bundled [grill contract](GRILL.md), brownfield mode |
| `grill`, not done | bundled [grill contract](GRILL.md) |
| `grill`, done, INTENT `Lane: standard` (or no Lane line) | bundled [research contract](RESEARCH.md) |
| `grill`, done, INTENT `Lane: quick` | bundled [plan contract](PLAN.md), quick mode |
| `research`, not done | bundled [research contract](RESEARCH.md) |
| `research`, done | bundled [synthesis contract](SYNTHESIZE.md) |
| `synthesize`, not done | bundled [synthesis contract](SYNTHESIZE.md) |
| `synthesize`, done | bundled [plan contract](PLAN.md) |
| `plan`, not done | bundled [plan contract](PLAN.md) |
| `plan`, done | bundled [build contract](BUILD.md); approval already authorizes execution |
| `build`, active or blocked | bundled [build contract](BUILD.md), recovery mode |
| `build`, done | bundled [build contract](BUILD.md) transition recovery, then review |
| `review`, active | bundled [review contract](REVIEW.md), final mode |
| `review`, blocked with valid finding sources | bundled [plan contract](PLAN.md), patch mode |
| `review`, blocked without a valid finding source or with conflicting evidence | stop at its `NEEDS-USER` item |
| `shipped`, validated archive | report archive path and exact ship SHA; stop |

Auto-advance after a non-interactive phase completes unless blocked or waiting
on `NEEDS-USER`. Planning owns the single build-approval gate; never ask a
second time.

## Next milestone

Start only from a ship transaction that passes the bundled validator. Preserve
the previous archive path, ship SHA, and build branch in the state Log, then
reset `phase: onboard`, `status: active`, `milestone: null`, `branch: null`, and
`archive: null`.
The project is now brownfield, so onboarding rescans current code and docs.
Committed archives are read-only.

## Rules

- Never skip or weaken a phase gate. A build request without an approved plan
  routes through the missing producers.
- Update phase, status, and Log at every transition.
- Artifacts outrank summary state. Repair a stale pointer only when ownership
  and the producing phase are unambiguous; otherwise surface the conflict.
- Stop on a hard constraint, unresolved user ruling, or conflicting source of
  truth. Never choose a user value silently.
