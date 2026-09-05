# Proposed recovery — awaiting owner ruling

Outcome: product, isolated task verification, wave review, project verification, and final review passed. Shipping stopped because parent-created .project/EXECUTION.md is outside the archive contract.

Preservation complete: prepared-project.tar.gz contains the full uncommitted .project tree. EXECUTION.md and LESSONS.md are copied separately. working-tree.patch records tracked changes. fixture.bundle preserves all refs and passed git bundle verify. sha256.json records the preserved files.

Proposed exception: restore only the already-preserved unrelated .project/EXECUTION.md and .project/LESSONS.md changes to their current committed contents so the canonical pipeline_undo.py preview/apply can prove and undo the uncommitted archive. No archive is edited manually and no Git history is rewritten manually. Then make a separate bookkeeping commit removing the misplaced execution record, whose complete contents remain in the external evidence. Resume only with canonical state/gate/isolation/archive helpers. Reconcile evidence to the changed bookkeeping HEAD through supported contracts; do not invent a passing review or repeat product checks without a new evidence requirement. Preserve all additional failures.

No installed plugin source changes, public remote actions, or new milestone are authorized. Owner removed token limits for this test. This recovery remains pending explicit owner ruling on the Git/bookkeeping exception.

## Owner ruling

Owner reply: "authorized". The proposed bookkeeping recovery is authorized. Continue the same E2E through local integration.

## Combined metadata ruling

Owner reply: "authorized", approving metadata-recovery.patch (duplicate FINAL field and four preserved STATE event lines). Continue the already approved bookkeeping recovery and shipping.
