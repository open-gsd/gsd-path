# Recovery execution

Owner ruling: "authorized". Scope: RECOVERY.md proposal and current chat authorization.
Observed completed native output before this invocation: 40113 across five parent invocations and five children. Earlier overruns remain historical; no token limit now applies.
Snapshot: all six SHA-256 entries verified; live EXECUTION.md and LESSONS.md matched preserved copies; fixture.bundle passed git bundle verify.
Only those two unrelated working-tree edits were restored: EXECUTION.md to HEAD bytes; LESSONS.md removed because absent at HEAD. Original contents remain in verified external snapshot.
Failure: attempted router-bundle scripts/pipeline_undo.py --help, exit 2 (file absent). Canonical diagnose returned stuck with the known archive and unowned-path findings. Correct undo bundle located at .agents/skills/gsd-path-undo/scripts/pipeline_undo.py.


## New undo blocker

Canonical pipeline_undo.py preview returned status preview, apply null, target.kind null, and blocked reason:
archive undo cannot prove archive ownership: FINAL.md requires one completed Reviewed HEAD: field

Checked archived review/FINAL.md: identical Reviewed HEAD fields at lines 3 and 96, both a927cba5994b5550ef02347468c6dd0459f2ecfb. The second occurs in the Recorded project Verify section. Earlier check_handoffs.py final accepted this artifact, while archive parsing rejects it.
No undo apply, bookkeeping correction commit, archive edit, installed-source edit, product check, or publication occurred.
Canonical diagnose repeated this blocked undo reason. The already-approved restorations are complete; snapshots and original hashes are unchanged.
A new owner exception is needed to correct the malformed uncommitted archive review metadata, or a canonical recovery that can handle it. This is outside the authorized EXECUTION.md/LESSONS.md restoration. Preserve the original malformed artifact in prepared-project.tar.gz.

## Combined metadata authorization
Owner reply: authorized. Applied exactly FINAL.proposed.md and STATE.proposed.md after byte equality with preserved originals. Removed log lines remain in STATE.original.md and metadata-recovery.patch. Observed output before this invocation: 43572; no current token limit. All prior failures and rulings remain external.


## Undo and bookkeeping correction completed

Canonical preview admitted uncommitted-archive at a927cba5994b5550ef02347468c6dd0459f2ecfb. Canonical apply returned applied with HEAD unchanged and STATE ship/active, archive null. No history rewrite occurred.
Canonical isolation checkpoint created a60a3ec88fb0ec8dacf75526a47120392a448295, deleting .project/EXECUTION.md and adding .project/build/RECOVERY.md. Diff of count.py, test_count.py, .agents and .gsd-path from the prior HEAD was empty.
At the new HEAD, verify-landed returned T001 proven-landed. Project verify-lookup returned hit:false, reuse:false. Per canonical exact-HEAD contract, new isolated Project Verify ran once and passed: 3 tests in 0.308s, OK. Old evidence was not relabeled. Gap artifact was canonically collected and sidecar retired. Native review_final resumed with a full new brief and actual CLI walkthrough requirement.


## Completed recovery and shipment

Fresh native review_final passed all SC1–SC6 at a60a3ec88fb0ec8dacf75526a47120392a448295 with one Reviewed HEAD field. Canonical collection and retirement passed; check_handoffs.py final passed; no pending discussion.
Canonical prepare, render-manifest, and preflight passed for .project/archive/001-widget-counter.
record-shipment returned shipped/done. The exact .project-only ship commit is c3195a67d43eb08e0c359975c83ec20a3bc23cf4; archive validate passed.
Canonical direct integrate and validate-integrated passed. Landing: c8065c3e69c244454198f1226b668f8ded9c4e46. Annotated tag: milestone/001-widget-counter, tag object 236dd4cf86dafec1770af3a13273ad4a10eb0f17, peeled target the landing merge.
Only approved local origin /Users/jeremymcspadden/orca/evaluations/gsd-path-e2e-50718f8/path/origin.git was used. Live fully qualified remote refs confirmed main at landing, gsd-path/M001 at ship commit, and matching annotated tag.
Git short-ref inspection emitted warning: refname origin/main is ambiguous. Follow-up fully qualified refs/remotes/origin/main and exact ls-remote refs proved the result without that ambiguity. No ref repair was attempted.
Final git status --porcelain was empty. Worktree list contained only the primary on gsd-path/M001 at the ship commit. Installed .agents and .gsd-path content matched fixture commit 607cdb15cd5e24b00318a60fa5ff2899c04d35b9 with no untracked changes there. No next milestone was started.
Original external snapshots, hashes, owner rulings, old reviews, failures and usage remain preserved. Last evaluator-supplied completed output before this invocation: 43572. Current invocation and resumed child usage are not exposed here and are not estimated.
