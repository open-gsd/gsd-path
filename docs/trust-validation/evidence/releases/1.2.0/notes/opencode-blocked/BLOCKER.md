# OpenCode1.2.0 — invalid final recovery

Task landed39123c646064abfd26128c68574591cb29e64a47; isolated12tests passed. Full-wave review passed its wave gate, but prepare-final rejected duplicate Reviewed HEAD fields and explicitly returned next:review-final. Native parent instead corrected the closed wave through a fresh child and made a build checkpoint during ship. That checkpoint captured runtime-owned final-gap-1.md despite the explicit instruction to leave generated views runtime-owned. Evaluator stopped the process before another recovery attempt.

No passing release receipt is assembled from this attempt. Current HEAD `19d4e6b6dce91fdde3d2013dd797bef3e5ba53c5`. Actual native session `ses_f405ee759ffeY83udTuOkCnfAS`. Raw run `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode/quick/run-20260920T162319358960Z`. Canonical read-only diagnosis: final-diagnose.json and final-diagnose.stderr.

Native last message, verbatim:

The checkpoint swept the runtime-owned `final-gap-1.md` into the commit — that breaks `_reusable_wave`'s changed-path check (final-gap-1.md isn't in its bookkeeping allowlist) and violates the runtime-owned-outputs constraint. Inspecting the checkpoint helper's CLI for a path-scoped commit before anything else.
