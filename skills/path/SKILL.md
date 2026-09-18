---
name: path
description: Inspect .project/STATE.md, report GSD Path progress, and run the next valid phase. Use only when the user explicitly invokes $path or $gsd-path. The status argument reports state without advancing. Do not infer this skill from generic project, next-step, or resume requests.
---

# GSD Path Router

Determine the current pipeline phase, report it briefly, and run the next valid
phase. Disk is the only phase memory.
Any text the user is expected to send back verbatim (a ruling, an approval
command, a reply) goes in its own fenced code block, never a blockquote or
inline prose, so it pastes cleanly.

When the project's `.gsd-path/runtime/` exists, resolve bundled helper paths
for `pipeline_state.py`, `pipeline_git.py`, `archive_milestone.py`,
`promote_lookahead.py`, `discussion_records.py`, and `pipeline_diagnose.py`
to that runtime. It is the guard-approved location on a closed milestone.
Use the skill bundle only when no project-local runtime exists.

## Status-only mode

When the invocation argument is exactly `status`, report and stop:

1. Run `python3 <absolute-bundled-pipeline-state.py> status --repo
   <absolute-root>`. Treat the JSON as the only status authority. Do not
   initialize STATE.md, bind a branch, or create a repository from this mode.
2. Present **Outcome** as `state.phase`/`state.status`, `route.action`,
   `next_skill`, and the pending-answer count. **Review** links the JSON
   `path` (STATE.md). **Next** names `next_skill` or the `route.reason` when
   `route.action` is `block`, without invoking either.
3. Do not run a phase contract, auto-advance, spawn agents, or apply undo.

`$gsd-path status` (Codex) and `/gsd-path status` (other hosts) are the only
router entry. The installed AGENTS.md re-entry contract may run the same
project-local status helper after a generic prompt, but it does not invoke this
router or advance a phase.

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
   Derive `gsd-path/M001` as the branch. The default checkout is
   `<resolved-workspace>/<repo-name>`; propose the distinct sibling
   `<resolved-workspace>/<repo-name>-gsd-path` as the linked worktree. When
   starting in an empty non-Git folder, propose that existing folder as the
   linked worktree with `--reuse-empty-worktree`, and a distinct absent default
   checkout beside it. Use the parent as workspace so the journal stays outside
   the worktree. Preserve the invocation folder and all its contents; never
   delete it or STATE.md to satisfy a preview. A nonempty folder requires a
   different target or an explicit recovery. The user
   may choose another workspace or worktree path before approval.
2. Resolve the bundled `scripts/bootstrap_repository.py` to an absolute path.
   Run its `preview` command with the exact owner, repository, visibility,
   workspace, default checkout, linked worktree, and optional description. The
   helper checks authentication, remote state, path parents, and any matching
   transaction journal without mutation. `mode: create` means every target is
   absent, except an explicitly approved empty linked-worktree directory;
   `mode: resume` means the exact approved journal exists and the helper
   can verify and adopt completed stages; `mode: complete` names an already
   initialized binding. Any ambiguity or unowned collision blocks.
3. Present **Outcome** as a repository-creation preview. Present **Review** with
   the proposed GitHub URL, visibility, default-checkout path, GSD Path branch,
   and linked-worktree path. Mark new targets not yet created and an existing
   empty worktree folder as reused in place. Present **Next** as one
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

Never apply this transaction to an existing repository. The router binds an
existing repository with `pipeline_git.py bind-initial`; build never creates or
selects a milestone branch.

## State ownership and initialization

1. When `.project/STATE.md` exists, run `python3
   <absolute-bundled-pipeline-state.py> validate --repo <absolute-root>`.
   Treat its typed JSON as the state; do not parse frontmatter or repair an
   invalid file through model reasoning. A validation failure blocks without
   mutation. In particular, never stamp the marker onto unowned state.
2. With no STATE.md, run the bundled
   `python3 <absolute-bundled-script> initialize --repo <absolute-root>
   --template <absolute-state-template> --require-git` helper
   (`scripts/detect_project.py`) before asking anything. Do not classify
   brownfield, greenfield, or orphaned `.project/` from a directory listing or
   conversation. Handle `route: setup-repository` before the write gate: the
   helper left the folder unchanged and wrote no state. Ask whether to create
   a new GitHub repository (recommended for an empty folder) or use an existing
   repository. A new-repository choice enters the preview transaction above;
   an existing-repository choice requires its path before continuing. Do not
   bind a branch or enter a phase yet. If the command exits nonzero, returns `error`, or returns
   `wrote_state: false`, report the error and block without routing or claiming
   STATE.md was written. Otherwise follow the JSON `verdict` / `route` exactly.
   `initialize` classifies and, for brownfield or greenfield, writes STATE.md
   through an anchored no-follow create — never create STATE.md yourself after
   classify. Leave that initial state untracked for `bind-initial`; its validated
   initial-state exception requires the index and every other path to stay clean.
   Do not insert a commit between initialization and binding:
   - `owned` — STATE.md exists; continue at step 1.
   - `orphan` (`route: recover-orphan`) — block without mutation. List the
     returned `orphan_paths` and ask for an explicit recovery, migration, or
     new location; existing evidence and archives do not prove a safe v2 phase.
   - `brownfield` (`route: inspect`) — the helper wrote STATE.md at
     `inspect/active`; report the returned `signals` and route to the bundled
     [inspect contract](INSPECT.md).
   - `greenfield` (`route: define`) — the helper wrote STATE.md at
     `define/active`; report that no brownfield signal fired, and route to
     the bundled [define contract](DEFINE.md).

## Integration choice

New state starts with `integration_default: direct`, `integration: direct`, and
`integration_source: default`.
When the user asks to change closeout behavior before build, use the state
helper; never edit these fields by hand:

```text
python3 <absolute-bundled-pipeline-state.py> configure-integration \
  --repo <absolute-root> \
  --scope <default-or-milestone> \
  --mode <direct-or-pull-request>
```

`default` changes the project setting and changes the current milestone only
when it has no override. `milestone` changes only the current milestone.
`integration_source` records that distinction even when both modes match.
Configure the project default only on the active `.project` track. A lookahead
track may receive only its own milestone override through `--project-dir
.project/next`; promotion requires its project default to still match the
active track.
The current value resets from the project default at the next milestone.
Both settings lock when build starts. A lookahead STATE inherits the active
project's `integration_default` and uses it for `integration`.

## Transaction recovery first

For a helper failure, use the diagnostic in the sibling bundle:
`../gsd-path-forensics/scripts/pipeline_diagnose.py diagnose --repo <absolute-root>`.
Resolve that path relative to this skill's directory.

Run `pipeline_state.py route` before any phase contract. A
`resume-undo` result means a helper-owned undo transaction was interrupted;
invoke `$gsd-path-undo` and apply the returned exact kind and expected HEAD.
Never enter phase work while this recovery remains. A
`resume-shipment` result means the ROADMAP/STATE shipment record was
interrupted; rerun `pipeline_state.py record-shipment` with the returned exact
archive and event, require its typed `recorded` result, then rerun `route`.
The journal owns recovery even when one or both files already contain their
shipped values. A `resume-checkpoint` result means a plan or roadmap approval journal exists;
run `pipeline_state.py resume-checkpoint --repo <absolute-root>`, require its
typed `approved` result and current commit, then rerun `route`. The journal
owns recovery even when STATE or ROADMAP.md already contains the approved
values. Never repeat those edits or call a phase while recovery remains.
A `resume-promotion` result means a promotion journal exists; rerun
`promote-next` with the returned milestone, branch, base, and landing SHAs. The
journal owns recovery even if STATE already contains some promoted values.
Never route a phase while that result remains.

For a branch mismatch, `route` normally returns `block`. Its only recoverable
result is `resume-next-handoff`: state is `shipped/done` on the returned
previous bound branch, and the durable journal proves the current branch and
HEAD match its prepared, switched, or retired stage. Promotion-journal recovery
returns `resume-promotion` earlier instead. Rerun `bind-next` immediately with
the returned typed branch, previous branch, ship, remote-default, base, and
landing fields. Do not rerun the old-branch archive or integration validators
in this recovery path: they passed before the journal was created and cannot
run after the switch. `bind-next` rechecks the live remote refs, exact SHAs,
integration ancestry, cleanliness, and journal ownership before continuing.
After it returns, continue the state transition or lookahead promotion below.
Do not reconstruct this classification from Git output or Log prose.
When the route returns `allow_remote_absent: true`, also pass
`--allow-missing-previous`; this is valid only because a merged PR may have
auto-deleted the published bound branch.

Before ordinary routing, inspect `STATE.archive`.

- A concrete archive path is an in-progress or completed ship transaction.
  If state is `shipped/done`, run the bundled
  `python3 <absolute-bundled-script> validate --repo <root>`. When it returns
  the same archive path and exact ship SHA, run the bundled
  `python3 <absolute-bundled-script> validate-integrated --repo <root> --slug <slug>`
  with the shipped milestone slug from STATE.milestone and origin network
  access available for PR-mode live publication checks. Report shipped only
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

Run the bundled state router instead of evaluating the state table in model
reasoning:

```text
python3 <absolute-bundled-pipeline-state.py> route \
  --repo <absolute-root> \
  --project-dir <.project or .project/next>
```

Follow its `route.action`, `phase`, and `mode` fields exactly. `run-phase`
selects the matching bundled phase contract, `validate-integrated` enters the
shipped validator, `wait` leaves an approved lookahead track ready for
promotion, `resume-next-handoff` resumes the verified `bind-next` transaction,
`resume-checkpoint` runs the approval recovery command above,
`resume-shipment` runs the shipment recovery command above,
`resume-promotion` reruns the returned `promote-next` transaction, and
`resume-undo` invokes `$gsd-path-undo` with the returned kind and expected HEAD,
`block` stops with the returned reason. `bind-initial`
means initialization is complete and phase work must wait for the initial
router binding: resolve the exact fetched `origin/main` SHA, call `bind-initial` as
above with `route.branch`, then persist its returned branch with
`pipeline_state.py transition` using the route result's `state` phase and status plus its
null branch and archive as expected fields. Set `--set-branch` to the helper's
returned branch and use the exact required event:
`--event "router bound initial milestone"`. Rerun `route`; never route from a
remembered or hand-parsed state.

Every ordinary state change not already owned by the journaled approval,
promotion, archive, or branch helpers uses `pipeline_state.py transition` with
expected phase, status, branch, and archive, an expected value for every
field it changes, the changed fields, and one `--event`.
It compares the expected state, validates the result, appends the fixed-format
Log line, and atomically replaces STATE.md. A mismatch blocks; never perform a
read-edit-write substitute.

```text
python3 <absolute-bundled-pipeline-state.py> transition \
  --repo <absolute-root> \
  --expect-phase plan --expect-status done \
  --expect-branch <STATE.branch> --expect-archive null \
  --set-phase build --set-status active \
  --event "build started"
```

Report normal progress in three labeled lines: **Outcome** names the phase and
completed work, **Review** links the newest canonical artifact using its
resolved absolute path when one exists, and **Next** names the action the
router is taking or the single action required from the user. Resolve the
routed track root first: `.project/` for the active track or `.project/next/`
for lookahead. If that track root's `research/DOCS-AUDIT.md` has `planned: no`
rulings, add one alignment-queue line and offer once to route them through the
bundled [plan contract](PLAN.md); declining does not block.

Once per conversation, before the status report, run the bundled update check
`python3 <skill-dir>/scripts/check_update.py`. It is cached, offline-safe, and
prints either nothing or one notice line; append that line verbatim to the
report. Ignore any failure and never block or retry — the check is advisory
and must not delay routing.

Auto-advance after a non-interactive phase completes unless blocked or waiting
on `NEEDS-USER`. Planning owns the single build-approval gate; never ask a
second time. One user-driven exception to normal routing: at a program milestone
boundary — `inspect/active` or `define/active` with no approved INTENT.md for
the next milestone — a user request to re-scope the remaining `pending`
entries routes to the bundled [roadmap contract](ROADMAP.md) in re-slice mode.

## Lookahead planning (program flow)

Before creating, reading, routing, or writing `.project/next/`, rerun the
bundled project classifier and require `verdict: owned`. For a new track,
require `next/` to be absent under non-following metadata, create it as a real
directory, then classify again before writing STATE.md. For a resumed track,
require `next/` to be a real directory and `next/STATE.md` to be a regular
non-symlink file. A symlink, special file, vanished path, metadata error, or
non-`owned` verdict blocks as orphan recovery. Repeat this check immediately
before every lookahead phase dispatch and before promotion.

While STATE is `build/active`, run the bundled deterministic selector before
offering lookahead planning:

```text
python3 <absolute-bundled-promote-lookahead.py> select-next \
  --roadmap <absolute-.project/ROADMAP.md> \
  --active-milestone <STATE.milestone>
```

Offer once per milestone only when it returns `status: selected`; its first
roadmap-ordered `pending` entry has dependencies that are all `shipped` or the
active milestone. On acceptance, create `.project/next/STATE.md` from the local [state
template](templates/state.md) with `pipeline: gsd-path/v2`, `phase:
inspect`, `status: active`, the selector's exact returned `milestone` slug as
`milestone`, `branch: null`, and `archive: null`. Copy the active project's
`integration_default` into both integration mode fields and set
`integration_source: default`. Then follow the bundled
phase contracts in their Lookahead mode — inspect, define (milestone +
brownfield), research (only when the entry lists open questions), decide, and
plan — rooted at `.project/next/`.
Declining does not block; offer again only at the next milestone's build.

- The build track always takes routing precedence: the lookahead track
  advances only on explicit user direction, never by auto-advance.
- The lookahead track never touches active-path artifacts, never marks its
  roadmap entry `active`, never binds a branch, and never dispatches build
  agents. Its approval checkpoints commit `.project/` in full, `next/`
  included.
- Route the track with `pipeline_state.py route --project-dir .project/next`,
  passing the track root to every bundled phase contract.
- A roadmap re-slice while `.project/next/` exists follows the keep/discard
  ruling in the roadmap contract before the track continues.

## Next milestone

Start only from a ship transaction that passes the bundled validator and the
bundled integration check (`validate-integrated`); pending integration routes
back to ship, never here. Preserve the previous archive path, ship SHA,
integration SHA, and build branch in the state Log. Before fetching or binding
the next program branch, fetch origin and resolve the exact current
`origin/main` SHA. For a program roadmap, resolve the branch from that exact
fetched commit through the bundled helper. With a saved lookahead track, run:

```text
python3 <absolute-bundled-promote-lookahead.py> select-base \
  --repo <absolute-primary-root> \
  --base <exact-origin-main-sha> \
  --remote-default origin/main \
  --lookahead
```

Without a saved lookahead track, run:

```text
python3 <absolute-bundled-promote-lookahead.py> select-base \
  --repo <absolute-primary-root> \
  --base <exact-origin-main-sha> \
  --remote-default origin/main
```

When the helper returns `status: complete`, report program completion and stop;
this means every roadmap entry is terminal (`shipped` or `abandoned`). Otherwise
require `status: selected`, require its returned `base` to equal the exact
fetched SHA, and use its exact returned `branch`; a mismatch or `status: none`
blocks before branch mutation. For a single-milestone restart, use one plus the
maximum archive prefix. Then run:

```text
python3 <absolute-bundled-pipeline-git.py> bind-next \
  --repo <absolute-primary-root> \
  --branch <selected-branch> \
  --previous-branch <STATE.branch> \
  --ship <exact-ship-sha> \
  --remote-default origin/main \
  --base <exact-origin-main-sha> \
  --landing <validate-integrated-landing-sha>
```

Add `--allow-missing-previous` when `validate-integrated` returned
`mode: pull-request` and `origin/<STATE.branch>` is absent. GitHub may delete
that head branch after merge; the local branch and exact ship SHA still bind
the handoff. The helper independently verifies the published pull-request
milestone tag and merge topology before accepting the missing branch.

The helper requires the previous branch, while it still exists locally, to
remain at the ship SHA, proves the ship commit is integrated into the exact
base, rejects local or remote branch collisions,
and switches the clean primary worktree without tracking main. It then
retires the integrated previous branch — deleted locally and on origin; the
ship commit stays reachable from the integration merge and its tag. Repeating the
same command while the new branch is current at the unchanged base is the
only idempotent recovery, and it completes any retirement left unfinished by
a crash. Record the returned branch and base in the state
Log, then:

- **Program** (ROADMAP.md exists): while `pending` entries remain, first
  promote any lookahead track. When `.project/next/STATE.md` exists, move
  nothing by hand. Run:

  ```text
  python3 <absolute-bundled-pipeline-state.py> promote-next \
    --repo <absolute-primary-root> \
    --milestone <next-slug> \
    --branch gsd-path/M00N \
    --base <exact-current-origin-main-sha> \
    --landing <exact-milestone-merge-sha>
  ```

  The helper journals before mutation, verifies or resumes each documented
  `intent`, `research`, `plan`, `tasks`, and `review` move, including the
  lookahead PLAN-PANEL artifact or skipped receipt, updates STATE.md and
  ROADMAP.md, stages the residual lookahead track in its recovery path outside
  `.project/`,
  classifies plan drift, removes `next/`, and writes the exact router
  promotion commit. Rerun the same command after interruption; any request or
  filesystem drift blocks. Route from its returned state and `drift` result.
  With no lookahead track, mark the selected entry `active` in ROADMAP.md and
  fill the previously shipped entry's `Integrated:` field with the landing
  merge SHA.
  Then call `pipeline_state.py transition`, expecting the complete
  `shipped/done` state including its previous branch and archive, and set
  `phase: inspect`, `status: active`, `milestone` to the selected pending slug,
  `branch: gsd-path/M00N`, and `archive: null`. The event records the returned
  base and integration SHA. Route to the bundled [inspect contract](INSPECT.md)
  so the changed codebase is rescanned before milestone define. When every
  entry is terminal (`shipped` or `abandoned`),
  report the program complete against CHARTER.md's program success criteria
  and stop.
- **Single milestone** (no ROADMAP.md): use the same guarded transition from
  the complete previous `shipped/done` state to `phase: inspect`, `status:
  active`, `milestone: null`, `branch: gsd-path/M00N`, and `archive: null`.
  Record the returned base and integration SHA in its event.
  The project is now brownfield, so inspect rescans current code and docs.

`promote-next` returns `drift.class: clean` for a promoted `plan/done` only
when no existing declared task path changed after the matching exact plan
approval checkpoint. `changed` and `unverifiable` reopen the promoted state as
`plan/active` and record the task ids or reason. Earlier-phase tracks return
`not-applicable`. Do not recompute or override this classification.

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
