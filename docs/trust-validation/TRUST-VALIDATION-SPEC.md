# GSD Path — Trust Validation Spec

**Status:** Active release contract
**Updated:** 2026-08-26
**Scope:** Every host declared in `scripts/skill-resources.json`
**Install path:** Node or Python installer from a clone; Node is the npm and
interactive entry point.

## Release contract

A release that changes pipeline contracts is trusted only when:

1. `npm run verify` passes.
2. Every declared host has one current full-milestone receipt and structured,
   tracked per-step evidence under `evidence/releases/<package-version>/`.
3. `npm run verify:release` accepts those receipts and proves that only trust
   evidence or its summaries changed after the tested candidate SHA.

`npm publish` runs this gate through the package's `prepublishOnly` lifecycle.
The release-trust workflow provides the same check on demand before publishing.

Missing credentials, an unavailable host, or a manual result marked partial or
unverifiable blocks release. It never becomes an implicit pass.

## Evidence layers

| Layer | What it proves | Gate |
|---|---|---|
| Unit and integration tests | Install, state routing, handoff validation, isolation, recovery, guards, archive, integration | `npm run verify` |
| Lightweight live smoke | Real host invocation and a bounded artifact | `.github/workflows/dogfood.yml` |
| Full live milestone | Real child dispatch, build, review, archive, merge, and tag on one host | release receipt |
| Release reconciliation | Every host passed at one candidate and later changes are evidence-only | `npm run verify:release` |

Simulated full-cycle tests are strong evidence for the deterministic disk and
Git contract. They do not replace real child-agent execution.

## Safety tiers

All hosts receive repository Git hooks when hooks are installed. Native
pre-action coverage is reported separately:

- `native-fail-closed` — the host blocks the tool before execution and Git
  hooks also pass.
- `native-limited` — a native hook exists but is fail-open or misses child
  tools; Git hooks pass.
- `git-only` — no validated native hook is installed; Git hooks pass.

Different safety tiers do not hide or waive the full-milestone requirement.
Each host's required tier is declared in `scripts/skill-resources.json`; a
receipt cannot claim a different tier. Current status is recorded in
[HOST-MATRIX.md](HOST-MATRIX.md).

## Open gaps

| Gap | Required closure |
|---|---|
| Full live milestone evidence is missing for advertised hosts | Record one passing current receipt per host |
| Native guards are installed automatically only for Claude, Codex, and Cursor | Add and validate host-native adapters where official APIs support them; otherwise retain an explicit lower tier |
| Not every host is available to the maintainer today | Keep the release gate blocked until access or maintainer-reviewed evidence exists |
| Live host APIs can change independently of this repo | Keep lightweight dogfood scheduled where credentials exist and re-record full evidence for pipeline-contract releases |

## Historical evidence

`TRUST-EVIDENCE.md` and dated files under `evidence/` are historical records.
Do not rewrite a past verdict. Add a new dated smoke result or versioned release
receipt when evidence changes.
