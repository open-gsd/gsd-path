---
name: gsd-path-ship
description: Verify a completed GSD Path milestone, manage evidence-backed patch decisions, request final shipping approval, and archive the validated result. Use only when the user explicitly invokes $gsd-path-ship or an active $gsd-path router or build orchestrator explicitly routes to this phase.
---

# GSD Path Ship Phase

Reuse proven review scope; dispatch reviewers for remaining claims. They never fix
product code.

Routing instructions below are caller handoffs under the AGENTS.md handoff
rule; never invoke an explicit-only sibling skill yourself.

Require `pipeline: gsd-path/v2` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Read the local
[reviewer role](references/reviewer.md) and
[dispatch contract](references/dispatch.md), resolve them to absolute paths,
and follow that runtime-specific dispatch contract. Resolve
`scripts/isolation.py` for verify sidecars; do not invent detached checkouts.
Resolve `scripts/build_state.py` for the landed-task proof and the verify
ledger.

This skill
verifies first and never archives or ships before explicit final approval.

Wave reviews are owned by the build orchestrator; this phase never runs them.

## Final mode

If STATE.md has a concrete `archive` path and phase is `ship` or `shipped`,
skip ordinary final-mode preconditions and resume **Archive transaction**
below. Also enter archive recovery when STATE is `ship/active`, `archive` is
null, and the only otherwise-unexpected path is the deterministic
`.project/.STATE.md.gsd-path-tmp`; `prepare` removes that interrupted temp
before safely persisting a transaction identity. Moved artifacts are
transaction state, not missing inputs. A concrete archive in any other phase
blocks without mutation. Otherwise, first scan ANSWERS.md for pending required
follow-ups under AGENTS.md. Apply an answer addressed to
`gsd-path-ship` only through current review
artifacts. Pass the record's exact stored owner to `dispose` so the disposition
receipt preserves that durable owner name; use `gsd-path-ship` for new records.
If it changes approved intent/plan or names another owner, keep
`ship/blocked`, link ANSWERS.md and the target artifact, and ask the user
before dispatch or ship. Every `ship/blocked` write and the step 7 log-only
event use `pipeline_state.py transition` with expected `ship/active` and the
exact current branch and archive values: blocking passes `--set-status
blocked`; the log-only event passes `--set-status active` and the event text,
so the position is unchanged. Then:

1. Require STATE `ship/active` produced and committed by the build
   orchestrator, `.project/intent/INTENT.md`,
   `.project/plan/PLAN.md`, all task files, all passing wave reviews, the bound
   build branch, and no product or unrelated changes. On retry, existing
   uncommitted assigned final-review outputs may remain. Resolve and record the
   exact full reviewed `HEAD` before dispatch, then prove every task landed
   through the runtime in step 3. Its landing check must return one
   `proven-landed` or `attested` entry per task; a task adopted after a rebase
   through `isolation.py adopt-rebase` reports `attested` with `provenance:
   owner-authorized-rebase` and needs its committed receipt
   `.project/build/rebase-adoption.json`. Keep bookkeeping in STATE.md
   and assigned artifacts; never create extra `.project/` execution reports. Reuse an output only when its
   `Reviewed HEAD` equals that SHA and the complete numbered gap-risk mapping
   still equals the freshly derived risk list. Regenerate the exact assigned
   output set when stale, removing only superseded `final-gap-N.md` files. A
   stale committed output may be replaced or removed only when Git and
   task logs prove it is the immediately preceding `ship/blocked` finding
   set, the approved patch tasks copied every finding verbatim, and those tasks
   are now done; otherwise it blocks. Git history preserves the superseded
   finding, while final review itself still creates no pre-ship commit.
2. Derive a stable numbered list of cross-wave integration risks from
   interfaces and flows that span waves. List only genuine risks that could
   plausibly fail; never pad the list. Include PLAN.md's project Verify as
   numbered risk 1. The orchestrator runs that command once in step 3 and
   writes its gap artifact; do not dispatch a gap reviewer for it. Resolve the local
   [final-review template](templates/final-review.md),
   [gap-review template](templates/gap-review.md), [patch-findings
   template](templates/patch-findings.md), and `scripts/check_handoffs.py`.
3. Run `python3 <absolute workflow_run.py> prepare-final --repo
   <absolute primary> --expected-head <HEAD>` from this skill's bundled scripts.
   This owns pending-discussion and landing checks, project Verify isolation,
   execution, output recording, collection, cleanup, and final-review reuse.
   Keep its JSON receipt; do not reconstruct those operations in shell calls.
   Exact stdout/stderr live once in `.project/build/verify-ledger.jsonl`;
   `final-gap-1.md` is the generated view referencing that entry. Re-entry at
   the same command and commit reuses the execution, including a failed one,
   and finishes interrupted collection without running the command again.
   Missing legacy output requires evidence reconciliation, not a blind rerun.
   Any non-zero result stops this step; preserve its stderr and diagnose through
   the bundled forensics contract. Do not launch reviewers while project Verify
   is failing. Record the command failure in STATE.md and link its gap evidence.

   Read the final step's `result.final`. `reused: true` means FINAL.md already
   proves final scope: do not dispatch `review_final` or rewrite it. For a
   quick lane with one full wave, reuse requires a committed review explicitly
   covering final scope, every success criterion and required walkthrough,
   and unchanged product and approved contracts. The helper generates FINAL.md
   as a view of that proof. Multiple waves, deep/verify-only reviews, missing
   evidence, or changed inputs require fresh final review. Existing valid final
   evidence at the current HEAD is also reused on retry.

4. For each numbered risk other than project Verify without a reusable output,
   dispatch one reviewer through the shared capacity-aware contract at the
   exact reviewed HEAD. Use logical task name `review_gap_<number>` and assign only
   `.project/review/final-gap-N.md`. Before each dispatch, create its distinct
   sidecar with `python3 <absolute isolation.py> isolate-verify --repo
   <absolute primary> --base <HEAD> --name review-gap-<number>` and supply the
   returned path.
   Review commands and staged outputs run only there, never in the primary
   worktree. For every returned artifact, substitute its returned worktree,
   branch, and assigned `.project/review/...` path into `python3 <absolute isolation.py> collect-artifact --repo <primary>
   --source <worktree> --base <HEAD> --branch <branch> --source-path <assigned path>
   --destination-path <assigned path>`. If replacing an admitted stale output,
   include `--expected-destination <its recorded SHA-256>`. Require returned
   fields to match, then run `python3 <absolute isolation.py> retire --repo
   <primary> --worktree <worktree> --branch <branch>`. The helper must observe only
   the assigned artifact in each sidecar. Model-written copies into the
   primary do not count as collection.
   After every gap artifact is present, reuse a valid FINAL.md admitted by
   step 3 or create a fresh sidecar with `isolate-verify --name review-final`
   and dispatch the integration reviewer under logical task name
   `review_final`, assigning only
   `.project/review/FINAL.md`. Its complete brief includes the exact recorded
   project Verify ledger entry, every collected gap verdict so Overall verdict is
   consistent with them, and PLAN.md's `## Surface contract` when INTENT.md
   names surfaces — that reviewer performs each Walkthrough and records the
   surface and what it showed on every criterion the contract lists. Collect FINAL.md and retire its sidecar through the
   same helper flow.
5. Only after `final-gap-1.md` and every dispatched reviewer artifact have
   been collected and all review sidecars retired, validate every artifact.
   Every success criterion is `met`, `not-met`, or
   `unverifiable` with checked evidence; every gap is `pass` or `blocked` with
   checked evidence. Every output must record the same exact full reviewed
   HEAD, and each numbered gap heading and Risk value must match its dispatch
   risk. Run
   `python3 <absolute check_handoffs.py> final --repo <absolute repo root>`
   before any archive question: FINAL.md needs one `### SCn — ...` block per
   INTENT success criterion, `Overall verdict: pass` requires every
   verdict `met` with a non-`none` Check or Reference, and every criterion
   listed in PLAN.md's Surface contract requires a matching `Surface` field
   and a non-`none` Check. A non-zero exit is
   `ship/blocked`; never rerun project Verify to repair the evidence.
6. Redispatch one complete corrected brief for a missing or invalid reviewer
   artifact under the same logical task name, following the runtime dispatch
   contract. Before dispatch, record the invalid destination's exact SHA-256.
   Give the retry a fresh verify sidecar, collect its corrected artifact with
   the same `collect-artifact` command plus
   `--expected-destination <recorded SHA-256>`, retire the sidecar, and rerun
   the final handoff gate. If it remains invalid, set `ship/blocked` with
   the exact contract failure and a `NEEDS-USER` dispatch-failure entry. Present
   **Outcome** with the invalid output, **Review** linking that output or
   STATE.md when it is missing, and **Next** naming the required correction;
   then stop and do not invent a patch finding. A `not-met`,
   `unverifiable`, or blocked gap with valid evidence sets `ship/blocked`,
   writes `.project/review/PATCH-FINDINGS.md` from the patch-findings template,
   and runs `python3 <absolute check_handoffs.py> patch --repo <absolute repo
   root>`. Present the blocked outcome, link the resolved absolute
   PATCH-FINDINGS.md path, and state that patch planning is next. The manifest
   contains exactly those FINAL.md and gap rows. When routed by an active
   `$gsd-path`, return control so its bundled plan contract opens patch mode.
   When invoked directly, stop and tell the user to explicitly invoke
   `$gsd-path`, which routes those sources to plan patch mode; do not invoke an
   explicit-only sibling skill yourself. Ship never writes tasks or PLAN.md.
   The patch build commits this prior finding set with the approved patch
   artifacts before execution.
7. Only when every criterion is `met`, every gap passes, project Verify passes,
   and no required discussion follow-up is pending, keep STATE.md at `phase:
   ship`, `status: active`, append `final gate passed; shipping approval
   pending`. Present **Outcome** with the final verdict, **Review** linking the
   resolved absolute FINAL.md path and summarizing the gap artifacts, and
   **Next** asking whether to `Archive and ship (recommended)` or `Stop for
   review`. The recommendation is grounded in the passing gates. Begin the
   transaction below only after approval; declining leaves review active and
   makes no archive mutation. Do not mark or report `shipped` yet.

## Archive transaction

Resolve bundled `scripts/archive_milestone.py` and `scripts/pipeline_state.py`
to absolute paths and invoke them with `python3`; the files need not be
executable. The archive helper is the sole MANIFEST.md and integration writer.
The persisted `STATE.archive` field is the transaction identity.

1. Normally require STATE `ship/active`, the bound build branch, and no
   non-`.project` change. The sole crash-recovery exception is
   `shipped/done` with a concrete target that is absent from HEAD; this is an
   uncommitted transaction and resumes without rewinding STATE. On every
   initial run or retry, run:
   `python3 <absolute archive_milestone.py> prepare --repo <root> --slug
   <STATE.milestone>`.
   The helper strict-loads STATE.md, requires its canonical `gsd-path/M00N`
   branch with `N >= 1` to equal the next collision-free archive sequence,
   rejects any `000-*` archive entry, and writes the exact
   `.project/archive/<NNN>-<slug>` path atomically to STATE.md before moving
   anything, and then moves the active milestone. On every retry run
   the same command; it reuses STATE.archive and never recomputes N.
2. The helper requires exactly one of each active or archived top-level
   artifact, permits active and archived `research/` together only for the
   byte-identical pending DOCS-AUDIT carry-forward, and recreates its parent
   before an atomic copy. Any other collision or missing artifact blocks.
   For a non-off PLAN review-panel policy it also requires exactly one plan
   resolution artifact: `review/PLAN-PANEL.md` for `ready`, or the exact
   helper JSON in `review/PLAN-PANEL.skipped.json` for `skipped`. Each full or
   deep wave cycle likewise requires exactly one merged `.panel.md` artifact
   or exact `.panel.skipped.json` receipt. Configuration alone never proves
   that a panel was ready or skipped.
3. Append milestone lessons to `.project/LESSONS.md` (create it when
   missing): one line per repeat-offender criterion across this milestone's
   wave reviews and one per escalation in the STATE.md log, formatted
   `- <NNN>-<slug> — <lesson>`. Skip the file entirely when there are none.
   LESSONS.md stays in the active root across milestones — it ships inside
   the ship commit but never archives — and the planner reads it. The same
   persistence applies to program artifacts when present: CHARTER.md,
   ROADMAP.md, and a top-level program SYNTHESIS.md ship in the commit but
   never archive.
   Then run `python3 <absolute archive_milestone.py> render-manifest --repo
   <root>`. The helper derives final verdicts, wave/task/cycle counts,
   carry-forward count, and the exact archive inventory, then atomically
   replaces MANIFEST.md through its deterministic same-directory temporary.
   Never render or edit the manifest directly. `prepare` removes that exact
   temporary after a crash. If the target exists in HEAD, `prepare` and
   `render-manifest` refuse mutation and the only valid action is `validate`.
4. Run `python3 <absolute archive_milestone.py> preflight --repo <root>` while
   STATE is `ship/active`, or while it is `shipped/done` in the uncommitted
   crash window above. It validates Git root/branch, current target absence from
   HEAD, immutable older archives, canonical real files, exact active-root
   allowlist and carry-forward, reviewed revision, manifest metadata and
   criteria against FINAL.md, exact ordered PLAN wave task/title rows with
   non-placeholder evidence for every task and owned success criterion, actual
   cycle counts, completed Notes, and the exact file inventory. Immediately
   before this command, recheck for an active
   `discuss/` copy created after prepare; if present, rerun `prepare`, regenerate
   MANIFEST.md by rerunning `render-manifest`, and only then preflight. Do not
   commit when it fails. A failure over a missing or non-canonical review
   artifact is never repaired by writing, splitting, or renaming a review
   file after the fact; report it and let the user rule — a new review cycle
   at the current HEAD is the only artifact-producing remedy. The archive helper independently binds every FINAL.md
   `SCn` heading id and normalized text to the archived INTENT.md; a renamed or
   easier criterion blocks even if the earlier handoff gate was bypassed.
5. Only after preflight passes, record shipment through the journaled helper;
   for a program it atomically replaces both ROADMAP.md and STATE.md, setting
   the current entry to `Status: shipped` with the exact `Archive:` pointer:

   ```bash
   python3 <absolute pipeline_state.py> record-shipment \
     --repo <root> \
     --archive <STATE.archive> \
     --event "archive preflight passed; shipment recorded"
   ```

   Require the returned state to be `shipped/done` with the unchanged branch
   and archive. When this was the last pending roadmap entry, use the event
   `archive preflight passed; shipment recorded; program complete` instead.
   When CHARTER.md and ROADMAP.md are both absent, this same command preserves
   the single-milestone flow and updates STATE.md only.
   Retry this exact command after interruption; it resumes its journal and is
   idempotent after completion. Stage only
   `.project/` paths, inspect the staged path list against the transaction and
   create the ship phase's one commit with exact subject
   `ship: M00N — <milestone-slug>` and body
   `Archive: .project/archive/<NNN>-<slug>` plus
   `Reviewed-HEAD: <reviewed SHA>`. M00N and NNN come from STATE.archive.
   There is no untracked-project exception and no product or older-archive
   path may enter this commit.
6. Immediately run `python3 <absolute archive_milestone.py> validate --repo
   <root>`. It requires the committed shipped state, exact archive and
   manifest, valid carry-forward, no active milestone artifacts, a clean
   worktree, exactly one current-milestone commit with the canonical ship
   subject and body in first-parent history, only `.project/` paths in that
   commit, and bound-worktree HEAD exactly equal to that ship commit. Any
   later product or `.project/` commit blocks validation. A passing validate completes the
   archive transaction; record its returned archive path and full commit
   SHA, and link the archived MANIFEST.md as the final review surface. The
   milestone is not shipped until integration below passes.
7. Integrate only after the postcommit `validate` passes, with the recorded
   ship commit and exact reviewed HEAD unchanged. Run `python3 <absolute
   archive_milestone.py> integrate --repo <root> --slug <STATE.milestone>`.
   This helper validates the ship commit, fetches origin, requires remote
   default `main`, and follows the locked `STATE.integration` mode:

   - `direct` owns the resumable merge transaction. It creates the canonical
     named integration worktree, performs the hook-verified `--no-ff` merge,
     refuses to resolve conflicts, creates the annotated milestone tag, pushes
     main then the bound branch then the tag, and removes its worktree and
     branch. Before publishing the bound branch it reads the live origin ref:
     absence is created with an absent-ref lease, the exact ship commit is an
     idempotent success, and every other value blocks. If origin/main advances
     after the local merge but rejects the push, a retry may discard and
     rebuild only the unpublished canonical merge and tag under the helper's
     existing recovery checks.
   - `pull-request` requires `gh` authentication for GitHub.com and a
     GitHub.com origin. It publishes the exact ship commit, reuses only the
     single PR from origin's bound branch at that commit or creates one with
     the canonical integration title and body plus the GSD Path credit footer.
     Any competing PR to `main` at the ship commit blocks. While the eligible
     PR is open, the helper returns `status: awaiting-merge`. Present
     **Outcome**, link
     the returned PR as **Review**, and state in **Next** that the user must
     merge it with GitHub's merge-commit method. Stop this ship invocation;
     Path never enables auto-merge or merges the PR. On rerun after a human
     GitHub user merges it, the helper requires the PR head to remain the ship
     commit and its landing to be a two-parent merge with that ship commit as
     second parent on `origin/main` first-parent history. It then writes and
     pushes the annotated milestone tag containing the PR URL, ship SHA, and
     landing SHA. A closed unmerged PR, squash, rebase, merge queue, moved
     head, duplicate PR, or non-GitHub.com origin blocks. The remote bound
     branch may be absent after a valid merge because GitHub may auto-delete it.

   A passing run returns the same proof exposed by `validate-integrated`.
   A non-zero result blocks; rerun the exact `integrate` command to resume a
   safe partial transaction instead of repairing refs or Git state manually.
   For a later validation recheck with origin network access, run
   `python3 <absolute archive_milestone.py> validate-integrated --repo <root>
   --slug <STATE.milestone>`; PR mode fetches and refreshes `origin/main` and
   mirrored milestone-tag refs, then revalidates the PR identity, state, merge
   provenance, and live branch and tag publication.
   Report shipped only when the integration result passes.
   Leave the primary worktree and STATE.branch on the shipped
   `gsd-path/M00N` at the ship commit. The router owns the later handoff to a
   new milestone branch after this gate.
8. If a crash occurs before STATE's atomic rename, discard only the exact
   deterministic state temp through `prepare`. If it occurs after STATE becomes
   `shipped/done` but before commit, run `prepare` and `preflight` under the
   explicit uncommitted exception, then create the one ship commit. Resume the
   named transaction even when active final-review inputs have moved. If the
   target exists in HEAD, validate it rather than running `prepare` or creating
   another commit. Any inconsistent committed transaction blocks; never
   mutate a committed archive.
   The fourth crash window is integration. Its transaction id is the ship
   commit, and partial merge, tag, push, and cleanup states are resumed only by
   rerunning `integrate`; it reuses NNN from STATE.archive. While integration
   is pending, never report shipped or start the next milestone; route back to
   ship.

Legacy ship and integration subjects may be ignored only while scanning older
milestones. They never satisfy the current milestone transaction. Current
validation requires exactly one canonical ship commit. Direct integration
also requires the canonical integration subject and body; PR integration uses
the exact PR metadata, annotated tag metadata, and merge topology instead.

## Rules

- Judge written expectations only: INTENT.md criteria in final mode, walked
  through PLAN.md's Surface contract for every criterion covering a surface.
- Require criterion, observed result, exact file or command evidence, and fix
  direction for every failure.
- Warn on ambiguity, but do not invent stronger requirements.
- Never count `unverifiable`, an unreviewed risk, or an unvalidated archive as
  shipped.
- Never merge or back-merge into the bound branch; ship's integration is its
  only path to the default branch. Never enter the default checkout; its
  local default branch ref may lag origin.
