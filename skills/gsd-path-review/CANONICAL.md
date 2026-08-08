---
name: gsd-path-ship
description: Verify a completed GSD Path milestone, manage evidence-backed patch decisions, request final shipping approval, and archive the validated result. Use only when the user explicitly invokes $gsd-path-ship or an active $gsd-path router or build orchestrator explicitly routes to this phase.
---

# GSD Path Ship Phase

Dispatch independent reviewers. They inspect and report; they never fix
product code.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

Require `pipeline: gsd-path/v1` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Read the local
[reviewer role](references/reviewer.md) and
[dispatch contract](references/dispatch.md), resolve them to absolute paths,
and follow that runtime-specific dispatch contract.

`review` is the persisted v1 state token for this canonical ship phase. The
skill verifies first and never archives or ships before explicit final approval.

## Wave mode

1. Require STATE `build/active`, a wave number, and review cycle 1 unless the
   caller supplies C. Any other phase blocks rather than rewinding state.
2. Resolve the local [wave-review template](templates/wave-review.md) and
   require the reviewer to stage its output inside the supplied disposable root
   at `.project/review/wave-N.cycleC.md`.
3. Spawn one reviewer with deterministic logical task name
   `review_wave_<wave>_cycle_<cycle>`, mode `wave`, the wave and
   cycle, exact repository root, and every task-file path in the wave. Each
   task must carry valid full `base` and `commit` SHAs. Before dispatch, the
   orchestrator creates one disposable detached worktree at each task base and
   supplies its exact path; it removes those exact worktrees after collection.
4. Require `.project/review/wave-N.cycleC.md` with a task verdict for every
   input and an overall `pass` or `blocked`. The reviewer reconstructs and
   verifies each task alone at its recorded base. The orchestrator validates the
   staged file, atomically copies it to the primary `.project/review/` path,
   and only then removes the exact disposable root. A blocked reviewer supplies
   work orders; it does not edit code.

## Final mode

If STATE.md has a concrete `archive` path and phase is `review` or `shipped`,
skip ordinary final-mode preconditions and resume **Archive transaction**
below. Also enter archive recovery when STATE is `review/active`, `archive` is
null, and the only otherwise-unexpected path is the deterministic
`.project/.STATE.md.gsd-path-tmp`; `prepare` removes that interrupted temp
before safely persisting a transaction identity. Moved artifacts are
transaction state, not missing inputs. A concrete archive in any other phase
blocks without mutation. Otherwise, first scan ANSWERS.md for pending required
follow-ups under AGENTS.md. Apply an answer addressed to review only through
current review artifacts and append its disposition receipt. If it changes
approved intent/plan or names another owner, keep `review/blocked`, link
ANSWERS.md and the target artifact, and ask the user before dispatch or ship.
Then:

1. Require STATE `review/active` produced and committed by the build
   orchestrator, `.project/intent/INTENT.md`,
   `.project/plan/PLAN.md`, all task files, all passing wave reviews, the bound
   build branch, and no product or unrelated changes. On retry, existing
   uncommitted assigned final-review outputs may remain. Resolve and record the
   exact full reviewed `HEAD` before dispatch. Reuse an output only when its
   `Reviewed HEAD` equals that SHA and the complete numbered gap-risk mapping
   still equals the freshly derived risk list. Regenerate the exact assigned
   output set when stale, removing only superseded `final-gap-N.md` files. A
   stale committed output may be replaced or removed only when Git and
   task logs prove it is the immediately preceding `review/blocked` finding
   set, the approved patch tasks copied every finding verbatim, and those tasks
   are now done; otherwise it blocks. Git history preserves the superseded
   finding, while final review itself still creates no pre-ship commit.
2. Derive a stable numbered list of cross-wave integration risks from
   interfaces and flows that span waves. List only genuine risks that could
   plausibly fail; never pad the list — a small milestone may carry only the
   project-Verify risk. Always include PLAN.md's project
   Verify command as a numbered risk so a failure has a reviewer-owned gap
   artifact with reproduced evidence and fix direction. Resolve the local
   [final-review template](templates/final-review.md),
   [gap-review template](templates/gap-review.md), [patch-findings
   template](templates/patch-findings.md), and `scripts/check_handoffs.py`.
3. Dispatch through the shared capacity-aware contract at the exact reviewed
   HEAD:
   - one integration reviewer with logical task name `review_final`, writing only
     `.project/review/FINAL.md`;
   - one reviewer per numbered risk with logical task name
     `review_gap_<number>`, each
     writing only `.project/review/final-gap-N.md`.
   Before dispatch, the orchestrator creates a distinct disposable detached
   worktree at exact reviewed HEAD for each reviewer and supplies its path.
   Review commands and staged outputs run only there, never in the primary
   worktree; the orchestrator validates and atomically copies each assigned
   output to its canonical primary path before removing only those exact
   worktrees after collection.
4. Validate every artifact. Every success criterion is `met`, `not-met`, or
   `unverifiable` with checked evidence; every gap is `pass` or `blocked` with
   checked evidence. Every output must record the same exact full reviewed
   HEAD, and each numbered gap heading and Risk value must match its dispatch
   risk. Re-run PLAN.md's project Verify in a fresh disposable detached
   worktree at that same exact HEAD.
5. Redispatch one complete corrected brief for a missing or invalid reviewer
   artifact under the same logical task name, following the runtime dispatch
   contract. If it remains invalid, set `review/blocked` with
   the exact contract failure and a `NEEDS-USER` dispatch-failure entry. Present
   **Outcome** with the invalid output, **Review** linking that output or
   STATE.md when it is missing, and **Next** naming the required correction;
   then stop and do not invent a patch finding. A
   failed orchestrator Verify must agree with the mandatory project-Verify gap
   review; repeat both once on disagreement, then block and surface the
   conflicting evidence as `NEEDS-USER` instead of planning from it. A `not-met`,
   `unverifiable`, or blocked gap with valid evidence sets `review/blocked`,
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
6. Only when every criterion is `met`, every gap passes, project Verify passes,
   and no required discussion follow-up is pending, keep STATE.md at `phase:
   review`, `status: active`, append `final gate passed; shipping approval
   pending`. Present **Outcome** with the final verdict, **Review** linking the
   resolved absolute FINAL.md path and summarizing the gap artifacts, and
   **Next** asking whether to `Archive and ship (recommended)` or `Stop for
   review`. The recommendation is grounded in the passing gates. Begin the
   transaction below only after approval; declining leaves review active and
   makes no archive mutation. Do not mark or report `shipped` yet.

## Archive transaction

Use the local [archive-manifest template](templates/archive-manifest.md) and
resolve bundled `scripts/archive_milestone.py` to an absolute path. Invoke it
with `python3`; the file need not be executable. The persisted `STATE.archive`
field is the transaction identity.

1. Normally require STATE `review/active`, the bound build branch, and no
   non-`.project` change. The sole crash-recovery exception is
   `shipped/done` with a concrete target that is absent from HEAD; this is an
   uncommitted transaction and resumes without rewinding STATE. On every
   initial run or retry, run:
   `python3 <absolute-script> prepare --repo <root> --slug <STATE.milestone>`.
   The helper chooses one plus the maximum existing numeric prefix, writes the
   exact `.project/archive/<NNN>-<slug>` path atomically to STATE.md before
   moving anything, and then moves the active milestone. On every retry run
   the same command; it reuses STATE.archive and never recomputes N.
2. The helper requires exactly one of each active or archived top-level
   artifact, permits active and archived `research/` together only for the
   byte-identical pending DOCS-AUDIT carry-forward, and recreates its parent
   before an atomic copy. Any other collision or missing artifact blocks.
3. Append milestone lessons to `.project/LESSONS.md` (create it when
   missing): one line per repeat-offender criterion across this milestone's
   wave reviews and one per BOARD.md escalation, formatted
   `- <NNN>-<slug> — <lesson>`. Skip the file entirely when there are none.
   LESSONS.md stays in the active root across milestones — it ships inside
   the ship commit but never archives — and the planner reads it.
   Then render MANIFEST.md from the template using actual archive contents, final
   verdicts, wave/task/cycle counts, and carry-forward count. Write it through
   the deterministic same-directory path `.MANIFEST.md.gsd-path-tmp`, then
   atomically rename it to MANIFEST.md. `prepare` removes that exact temporary
   after a crash. A pre-existing uncommitted manifest may be replaced only
   while resuming this named transaction. If the target exists in HEAD,
   `prepare` must refuse all mutation and the only valid action is `validate`.
4. Run `python3 <absolute-script> preflight --repo <root>` while STATE is
   `review/active`, or while it is `shipped/done` in the uncommitted crash
   window above. It validates Git root/branch, current target absence from
   HEAD, immutable older archives, canonical real files, exact active-root
   allowlist and carry-forward, reviewed revision, manifest metadata and
   criteria against FINAL.md, actual cycle counts, completed Notes, and the
   exact file inventory. Immediately before this command, recheck for an active
   `discuss/` copy created after prepare; if present, rerun `prepare`, regenerate
   MANIFEST.md from the reconciled archive, and only then preflight. Do not
   commit when it fails.
5. Set STATE.md to `phase: shipped`, `status: done` and append the archive path
   only after preflight passes. Stage only
   `.project/` paths, inspect the staged path list against the transaction and
   create the ship phase's one commit with exact subject
   `ship: <NNN>-<milestone-slug>`. When recovery already has `shipped/done`, do
   not append or rewrite the transition again. There is no untracked-project
   exception and no product or older-archive path may enter this commit.
6. Immediately run `python3 <absolute-script> validate --repo <root>`. It requires
   the committed shipped state, exact archive and manifest, valid carry-forward,
   no active milestone artifacts, a clean worktree, the newest commit with exact
   subject `ship: <NNN>-<milestone-slug>` in HEAD history, only `.project/`
   paths in that commit, and no `.project` change after it. The ship commit
   need not be HEAD: later product commits do not disturb a validated
   shipment. Report shipped only when this
   command passes, including its returned archive path and full commit SHA.
   Link the archived MANIFEST.md as the final review surface.
7. If a crash occurs before STATE's atomic rename, discard only the exact
   deterministic state temp through `prepare`. If it occurs after STATE becomes
   `shipped/done` but before commit, run `prepare` and `preflight` under the
   explicit uncommitted exception, then create the one ship commit. Resume the
   named transaction even when active final-review inputs have moved. If the
   target exists in HEAD, validate it rather than running `prepare` or creating
   another commit. Any inconsistent committed transaction blocks; never
   mutate a committed archive.

## Rules

- Judge written expectations only: task criteria in wave mode and INTENT.md
  criteria in final mode.
- Require criterion, observed result, exact file or command evidence, and fix
  direction for every failure.
- Warn on ambiguity, but do not invent stronger requirements.
- Never count `unverifiable`, an unreviewed risk, or an unvalidated archive as
  shipped.
