# Claude evidence limits

Release receipt validated by frozen-candidate _validate_receipt through release_receipt.py, exit0; external widget oracle passes. Integration limited to local bare origin.

Separate quick-scenario checkpoint missing: same-HEAD prepare-final repeat was not executed before archive prepare. SHIP.md32–38 requires concrete archive transactions to skip ordinary final mode; no archive/state rewrite was attempted. Do not claim repeat reuse passed.

# Native build observations

Full raw evidence is in quick/run-*/events.jsonl. Native reviewer artifact was copied without content edits; both hashes fe540f9a2118e9f04cf17cbb5a65a9f02baf167d3271c340c7d30dfdc77c91f8.
Native parent attempted sidecar retirement, got `worktree is dirty; pass --force only from the retry-retirement path`; inspected dirty untracked review output, removed copied sidecar review directory, and canonical retirement then passed. Parent did not run required diagnosis immediately.
Wave gate first failed `wave review must be the canonical path .project/review/wave-1.cycle1.md`; corrected path passed. No immediate diagnosis.
Evaluator ran pinned gsd-path-forensics/scripts/pipeline_diagnose.py diagnose on root request after observing these negatives: exit0, status ok, all seven probes true. Only finding dirty-worktree severity info, uncommitted .project/build/verify-ledger.jsonl at HEAD24fe04d0ec9504d5fc1f1c340a3ec9300dd4a845, ship/active. No blocking finding. This late diagnosis does not erase missed native immediate diagnoses.

Ship native guard refusals preserved in claude-negative-events.json, including git remote -v classified as closed-milestone mutation. Canonical literal ship commands passed. No guard bypass or reviewer verdict rewrite.

Native whole-turn output counts 8704,12419,1525 in initial session;28514 in fresh build session;12350 in fresh ship session. No per-child output attribution available. Per-task compliance is unverified; observed native session totals remain below30000.
