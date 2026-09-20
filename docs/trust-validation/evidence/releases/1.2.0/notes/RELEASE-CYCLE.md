# Release-cycle correction — pending 1.2.0

Owner directions: "i need to remove them from the evaluations. im not paying $100 everytime i want to release" (Qwen, Kiro, Zed); "we need to fix the release cycle, shouldnt bump versions until release is verified"; "1.2.0".

## Corrected behavior

- Publication consumes the prepared package version. The workflow no longer increments, commits, or pushes a version before verification. Manual retries use the same version.
- Local candidate preparation reuses a package version ahead of the last release tag unless `--from` explicitly selects a new base.
- Package and lockfile are restored locally to 1.2.0. npm still publishes 1.1.0; neither failed attempt produced 1.2.0 or 1.3.0.
- Release preparation and evidence validation exclude Qwen, Kiro, and Zed. Installer support and offline tests remain. The other eight hosts retain their receipt requirements.
- Tested-candidate receipts may survive changes confined to the specifically listed evaluation-policy files. Product/package/runtime changes still invalidate proof.

## Verification

`python3 -B -m unittest tests.test_trust_evidence`: 47 passed. New exclusion/preparation/policy tests were observed RED against the old implementation, then GREEN. Restoring the old validator and preparation script made them fail again; fixed files restored. Existing product-change rejection test passes.

`node --test tests/bump-version.test.mjs tests/release-gates.test.mjs tests/release-publish.test.mjs`: 20 passed. Regression tests first reproduced the unpublished 1.2→1.3 increment and pre-verification workflow mutation. Restored-original sabotage reproduced both failures; restored code passed.

`npm pack --dry-run --json --ignore-scripts`: package-version assertions failed on 1.3.0, passed on 1.2.0, failed when old metadata was restored temporarily, and passed after restoration. No tarball was published.

`node scripts/bump_version.mjs --bump auto --dry-run` reports pending 1.2.0 from the last release tag 1.1.0, without mutation. Resource synchronization check passes 459 resources; diff whitespace check passes.

Raw logs: `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.3.0-45466c4/` (`evaluation-policy-*.log`, `package-version-*.log`, `release-cycle-node-suite.log`).

## Evidence boundary

Earlier 1.3.0 receipts remain under their original version and candidate. They have not been relabeled as 1.2.0 proof. Codex retry 3 is preserved at its plan gate against the old candidate. No API-billed Qwen/Kiro/Zed run was restarted.

The historical workflow failures are [first attempt](https://github.com/open-gsd/gsd-path/actions/runs/35499912829) and [second attempt](https://github.com/open-gsd/gsd-path/actions/runs/35514030874). Both failed on missing host evidence after already pushing a version bump.
