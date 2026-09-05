# Long-run execution status

Objective (owner): run the entire long run. fix as needed.

The goal remains active until every scenario has real evidence or an exact
external prerequisite is resolved. Do not replace live evidence with helper tests.
No testing time or token limit was set by the owner.

## Current position

- Source branch: jeremymcs/astra-eval; no merged PR found for this branch.
- First candidate: cb45afc401b706457f9e91e313b986659c9a42dd.
- First evidence: /Users/jeremymcspadden/orca/evaluations/gsd-path-features-cb45afc.
- First shared run: 1,014 Python methods; 1,002 pass, 10 fail/error, 2 platform
  skips. Node 133 pass; resource sync passes.
- Fixed: Node installer missing check_task_briefs.py; invalid undo/diagnostic
  plan fixtures; lean helper package import identity under polluted sys.path.
  Focused gate: 45 tests pass. Three fault reintroductions each fail; restored
  package/undo checks and sync pass. Receipt: first evidence/fix-sabotage.json.
- No native scenario has started yet. Prepare a new pinned candidate after the
  focused fixes pass. Keep the first candidate's failure receipt unchanged.

## Run decisions

- Routine local fixture approvals will be reviewed by the evaluator under the
  owner's instruction to run the entire suite, and labeled evaluator decisions.
- Existing local bare origins are authorized for fixture shipping.
- GitHub bootstrap/PR targets still need exact target preview and approval.
  No new external target has been approved. No PR merge is delegated.
- Every lookahead capture must occur at its real checkpoint; missed observations
  cannot be reconstructed later. Keep native thread IDs and run handles here.
- Reuse command evidence at unchanged inputs; fixes justify only affected checks.

## Remaining work

- Verify and commit the fixes; prepare the new pinned run and record its path.
- Run shared checks and all ten native scenarios from FEATURE-EVALUATION.md.
- Exercise both lookahead promotion outcomes, real dependency dispatch, review
  branches, sidecars, recovery, abandonment, external integration and guards.
- Review per-feature receipts, product oracles and implementation/review spins.
- Final audit must account for all 24 feature groups, platform skips, missing
  native prerequisites and recorded failures. Do not mark the goal complete
  while a required feature remains untested or unverifiable.

## Pending exact external approval

Read-only bootstrap preview returned mode=create for private
jeremymcs/gsd-path-longrun-20260905, default checkout
/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-20260905 and linked
/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-20260905-gsd-path,
branch gsd-path/M001. Async target approval requested; not yet received.
