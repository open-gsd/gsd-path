# Build recovery handoffs — work record

## Contract

Implement and publish a PR for the two blocked-build return paths:

- intent correction: Build → Define → applicable evidence/decision gates → Plan approval → Build;
- structural plan repair: Build → Plan approval → Build.

Preserve landed work and proof, settle running tasks before changing contracts,
reject unauthorized state transitions, and prevent stale approvals or review
evidence from authorizing changed work. Keep integration repair, abandonment,
deployment, and hotfix policy outside this PR.

## Result

- Added guarded recovery from `build/blocked` to Define corrections or Plan repair.
- Recovery records a committed base and requires settled tasks and dispatch records.
- Reapproval preserves landed task bytes and landing proof. Pending tasks may be
  replaced. Integration settings and milestone identity stay locked.
- Old reviews move to a verified backup. Approval atomically restores reviews only
  for unchanged contracts. Changed work uses new dispatch records after Build resumes.
- Both installers and generated skill bundles contain the recovery runtime.
- No new dependencies. Canonical resources are the edit source; generated copies
  were refreshed with `scripts/sync_skill_resources.py` without warnings.

## Verification

| Check | Evidence |
| --- | --- |
| Initial regression RED | Both blocked-build return transitions failed as illegal before implementation. |
| State and Build regression | 120 tests passed. |
| Recovery, isolation, dispatch driver and dispatch contracts | 204 tests passed. |
| Final recovery suite | 16 tests passed, including source, router bundle, Python and Node runtime closure. |
| Installer and resource sync | 8 Python checks passed; 2 Node update/refresh checks passed. |
| Sabotage | All 11 injected defects failed the selected tests; the restored snapshot passed. |
| Review follow-up | A stale collected record remains outside the resumed Build record directory. The test passes on current code and fails when the directory falls back after recovery. |

Sabotage covered transition routes, landed task preservation, dispatch record
isolation, integration lock, review backup integrity, partial review restoration,
approved task inventory, Python and Node runtime closure, active task ownership,
and mandatory approval checkpoints. It ran in a disposable snapshot.

## Independent review disposition

Claude Fable 5.1 completed a read-only implementation review. Its sole finding
claimed that the dispatch directory returns to the original location after
`build started`. The current implementation selects the latest recovery record
regardless of its active flag. The resumed-Build regression rejects this finding;
injecting the claimed faulty condition makes that regression fail. No source fix
was needed for the finding.

## Publication

Run the configured no-mistakes pipeline on the committed feature branch and
monitor the PR through green CI. This work does not change integration repair,
abandonment, deployment, or hotfix policy.
