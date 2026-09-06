# Repair closure decision

Outcome: implemented and natively verified. Both cycle-4 reviewers accepted the proven repair under the approved rule; canonical grouping reports no findings or blockers. Recorded Verify was reused and 25 prior artifacts were preserved. [Native proof](/Users/jeremymcspadden/orca/evaluations/gsd-path-review-fault-8ecdb9b-20260905/reviews/repair-closure-capture.md). The evidence below preserves the original conflict and decision.

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

The owner approved this rule change and the scoped continuation below; native closure proof is now recorded below. It does not authorize editing old reviews, waiving product criteria, another product change, GitHub actions, or changing the other pending guard/loop/panel decisions.

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


## Verified implementation

Source commit `00ff7737eddc06d6a569b821d0f7d44a6f94e96a`. Regression command `python3 -B -m unittest tests.test_review_repairs.RepairEvidenceTests.test_proven_repair_resolves_to_its_isolated_product_without_reverification` failed before implementation and passed after it. The missing-evidence test failed when the Verify guard was disabled, then passed after restoration. `python3 -B -m unittest tests.test_review_findings tests.test_review_repairs` passed 18 tests. Sync passed for 199 resources. Global Codex and Claude installs include this fix; doctor passed.

Native checkpoint `4364694ac76148c48f6c66fee4a44377256e3378`: both cycle-4 lenses pass, no finding groups/blockers/pending skeptics. No settled product command rerun, new product edit or prior report edit. This closes the approved linked repair case; it does not claim a separate wave-2 verdict or full milestone shipment. Broader evaluation prerequisites remain separate.
