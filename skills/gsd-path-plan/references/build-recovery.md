# Return a blocked build to its contract owner

Use this contract only for an active milestone at `build/blocked`: a documented
structural plan defect, or an explicit user ruling that changes approved intent.
It does not reopen ship, archived milestones, or lookahead. Build owns entry;
Define owns intent corrections; Plan owns the replacement task inventory and
approval. Routing remains a caller handoff under AGENTS.md.

## Build: checkpoint and enter

1. Record the finding or verbatim user ruling in STATE through its helper.
   Stop dispatch. Use the normal recovery and retirement procedures until
   every task is either unstarted `pending` with null dispatch metadata or
   proven `done`. Preserve owned uncommitted work before any retirement.
   Settle reviewers and their sidecars too. Dispatch records must have no pending
   cleanup; records with reviewer `worktree` and `branch` ownership must also
   record `cleanup_complete`. A `blocked` or `collected` outcome alone does not
   prove retirement. Records that never owned a reviewer sidecar do not require
   that retirement receipt. Use the existing dispatch retirement procedures;
   recovery does not retire sidecars itself. Never infer that a timed-out child
   stopped. Checkpoint the blocked state and artifacts using the Build
   bookkeeping contract; the primary must be clean.
2. Run `pipeline_state.py transition` with the complete current state expected,
   `--set-status active`, and the matching target and event:

   | Cause | Target | Exact event |
   | --- | --- | --- |
   | User changes a criterion, constraint, or veto | `--set-phase define` | `build intent corrections requested` |
   | Task inventory, dependency, or wave repair | `--set-phase plan` | `build plan repair requested` |

   The helper records the committed recovery base in STATE atomically. Do not
   author or edit that record. Milestone, branch, integration settings, and
   landed task contracts remain fixed throughout recovery.
3. Return to the router or name the selected explicit skill. The route names
   `corrections` for Define and `build-repair` for Plan. Other blocked-build
   failures continue through ordinary Build recovery.

## Define and Plan: prepare before editing

Run the bundled `pipeline_state.py prepare-build-recovery --repo <absolute-root>`
before changing any recovery artifact. This repeatable operation preserves the
old review directory under `plan/build-recovery-<base>/review` and starts a fresh
active review directory. STATE's recorded base owns an interrupted move; rerun
this command to finish it. The helper validates the preserved bytes against Git.
Do not remove, rewrite, or use the preserved reviews as current approval.

**Define corrections.** Read the existing intent and governing program artifacts.
Interview only the requested change; append the user's words under
`## Corrections`, revise the affected intent, and present the delta for approval.
Keep the milestone identity. Reclassify the lane using the normal lane rules.
After approval, use the normal `define/active → define/done` transition and route
from the approved lane. Standard intent goes through Research and Decide again;
quick and milestone intent use their existing evidence gates. A program charter
or roadmap conflict still requires its legal owner gate; this path cannot waive it.

**Plan build-repair.** Read the corrected intent, current synthesis, existing plan,
task files, and recovery base. Use the normal planner, lint, panel, and approval
gates. Repair the remaining task inventory as needed, including split, rename,
dependency, or wave changes. Keep IDs ordered and contiguous. Preserve every
landed task file byte-for-byte, including its recorded base and proof. Any new
work to satisfy a corrected criterion belongs in new pending tasks, not rewritten
landed contracts. A plan-only recovery must not change approved intent.

## Approve and return to Build

Use normal `pipeline_state.py approve --kind plan --expected-head <HEAD>`.
Neither `--patch` nor `--defer-checkpoint` is legal for recovery. The helper
checks landed-task preservation and restored intent ownership, restores review
evidence only for unchanged contracts, and creates the normal journaled plan
checkpoint. A failed approval leaves recovery open.

Return through `plan/done → build/active` with event `build started`. The dispatch
driver uses a separate record directory for this recovery base, while retaining
the milestone budget ledger. Resume only from the new approved task inventory.
Unchanged wave evidence remains usable; changed waves need review in the new
record directory. Retained task Verify receipts remain historical evidence for
their original task and base, never proof for a changed task. Final review still
requires current-HEAD evidence before shipment.
