# Repair closure decision

Outcome: the controlled defect is fixed, but the native workflow cannot consistently accept the repair. No additional product defect is open.

## Checked evidence

- Original task T001 landed at `5bef9657402966e64cc4592a9e0f76d4aea1ea6d` with the evaluator-inserted conversion defect. Native tests passed; both deep reviewers reproduced precision loss and overflow. Four native skeptics upheld the actual findings.
- One complete repair task T002 landed at `29ff777b5da05b8310c510d38d514a5e4f824492`. It changed one product line and added 25 test lines, preserving existing coverage. New regressions were observed failing before the fix, passing after it, failing under deliberate restoration of the defect, and passing after restoration. Authoritative verification passed eight tests with the existing interpreter-dependent skip unchanged.
- The external [precision oracle](/Users/jeremymcspadden/orca/evaluations/gsd-path-review-fault-8ecdb9b-20260905/reviews/fault-evidence/repaired-oracle.json) now prints the exact supplied integer.
- Cycle 3 [contract reviewer](/Users/jeremymcspadden/orca/evaluations/gsd-path-review-fault-8ecdb9b-20260905/reviews/repo/.project/review/wave-1.cycle3.contract.md) confirms all product failures repaired but returns blocked: the isolated task rule binds its verdict to the original faulty T001 patch.
- Cycle 3 [adversarial reviewer](/Users/jeremymcspadden/orca/evaluations/gsd-path-review-fault-8ecdb9b-20260905/reviews/repo/.project/review/wave-1.cycle3.adversarial.md) confirms the same repair and returns pass: it reads build step 7 as allowing the proven fix task to close the earlier findings.
- Canonical grouping returned blocked and cap_reached, without structural-format errors. No further reviewer, skeptic, product repair or shipment is authorized by this result.

## Conflict

The build contract permits complete fix tasks in an appended wave. The reviewer contract requires each verdict to use the original task's recorded base plus only its immutable landing patch. It does not explicitly say how a later proven repair changes the product used for acceptance of the earlier failed criterion. Rechecking the immutable faulty patch can therefore block forever after a correct repair.

Cycle 1 also consumed a review cycle because completed malformed reports require a new cycle. Those original reports and failed receipts remain preserved. Neither history nor a cap may be rewritten to erase that overhead.

## Recommended ruling and implementation scope

Allow an explicitly linked, proven repair task to close the earlier criterion in a new review record. Preserve the original failure and landing as historical evidence. Do not accept an arbitrary combined branch tip or unrelated later changes.

Implementation after approval:

1. Define the legal repair evidence chain in canonical build/reviewer instructions and required task data. Resolve it with deterministic helper logic using exact task bases, proven landing commits, declared files, and the recorded finding-to-repair link.
2. Verify the repair in its own isolation. The later review assesses the original unchanged criterion using the proven affected repair evidence. Reuse unchanged authoritative command evidence; run only a necessary uncovered check. Reject missing, unrelated or unproven repairs.
3. Add executable regressions proving legitimate repaired closure and rejection of invalid repair evidence. Observe failure before the fix, success afterward, and sensitivity to removing the checks. Sync generated resources.
4. Continue this preserved native case only under the owner's explicit replacement of the exhausted cycle cap. Do not manufacture a new numeric cap. Stop when repaired closure is proven, or when another required owner decision blocks progress.

The owner approved this rule change and the scoped continuation below; implementation still requires native closure proof. It does not authorize editing old reviews, waiving product criteria, another product change, GitHub actions, or changing the other pending guard/loop/panel decisions.

Alternative: keep this native patch-path result blocked and end this case with the product repair verified but workflow closure unproven.

## Why a decision is required

The supplied AGENTS.md requires stopping at the review-cycle cap and surfacing conflicting sources. The pinned build contract requires escalation at the cap. The current plan defines max_review_cycles as 3; the helper reports it exhausted. General full-run authorization did not change that exact policy.


## Owner approval

Owner message, verbatim:

```text
approve yoir lean
```

Accepted as approval of the pending proposed repair-closure rule and continuation beyond this case's exhausted cap. The replacement stop rule is the proposed one: stop when repaired closure is proven, or when another required owner decision blocks progress. No numeric cap is invented or silently edited, and prior cycle counts remain historical facts. Other guard, loop, panel and external GitHub decisions are unchanged.

Implemented scope: `review_findings.py repair-evidence` validates one carried finding batch against canonical original/repair landings, exact carried criteria and observations, source-task dependencies, declared files, unchanged prior reports, product ancestry and a reusable passing Verify. It emits read-only evidence for the new review. Canonical build/reviewer instructions explicitly permit that isolated repair evidence to satisfy the original unchanged criteria. Existing task data is sufficient; no old task, report or verdict needs editing.
