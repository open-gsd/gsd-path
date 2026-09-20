# GSD Path — Trust Validation Spec

**Status:** Active release contract
**Updated:** 2026-09-20
**Scope:** Release evaluation hosts selected from `scripts/skill-resources.json`
**Install path:** Node or Python installer from a clone; Node is the npm and
interactive entry point.

## Release contract

Every release is trusted only when:

1. `npm run verify` passes.
2. Every affected host has one current full-milestone receipt and structured,
   tracked per-step evidence under `evidence/releases/<package-version>/`.
   Each receipt must identify a distinct host run, landing commit, ship commit,
   and integration commit.
3. `npm run verify:release` determines the affected hosts, accepts required
   receipts, and proves that only trust evidence, its summaries, or the
   release-evaluation policy files listed below changed
   after their tested candidate SHA. With no affected hosts, automated checks
   suffice; the validator reports an empty host list, not a live-test pass.

### Live-check scope

Release evaluations cover Codex, Claude, Grok, OpenCode, Copilot, Antigravity,
Cursor, and Kimi. Qwen, Kiro, and Zed are excluded at the maintainer's request
because their live runs require API credits. Their installer support and
offline contract tests remain. Exclusion is not a live-test pass; historical
receipts and failed attempts remain unchanged. The preparation script uses the
same host selection as the validator and does not prepare these three hosts.

`scripts/check_trust_evidence.py` compares HEAD with the nearest reachable
`v<semver>` tag, excluding the current package version's tag. This prevents a
new release tag from hiding its own changes. Without a prior tag or with
shallow history, every release evaluation host requires evidence.

| Changed files | Required live checks |
|---|---|
| `platforms/<declared-host>/` | That host if included in release evaluations; multiple host changes combine |
| Shared adapters, skills, runtime scripts, `AGENTS.md`, `WORKFLOW.md`, or unclassified paths | Every release evaluation host |
| `docs/`, other root Markdown, `tests/`, `.github/`, `daemon/` | None |
| `scripts/bump_version.mjs`, `scripts/update_release_docs.mjs`, `scripts/prepare_release_evidence.sh`, `scripts/check_trust_evidence.py` | None; automated verification still applies |
| `package.json`, `package-lock.json` | None only when changes are limited to the top-level version and lockfile root-package version; otherwise every release evaluation host |

Added and deleted paths count, including both sides of renames. No old receipt
is relabeled as current evidence. Required receipts retain all existing
candidate, native-child, task, review, archive, integration, and guard checks.

Release 1.2.0 includes shared pipeline changes, so all eight release evaluation
hosts require current live evidence.

Changing evaluation policy does not change the installed candidate being
tested. The following files may change after the candidate without discarding
its receipts: `scripts/check_trust_evidence.py`,
`scripts/prepare_release_evidence.sh`, `tests/test_trust_evidence.py`, this
specification, and `RELEASE.md`. Automated verification still applies. Runtime,
installer, dispatch, skill, package, and other product changes still invalidate
the candidate proof. No receipt candidate SHA may be rewritten to bypass this.

`npm publish` runs this gate through the package's `prepublishOnly` lifecycle.
The release-trust workflow provides the same check on demand before publishing.

Missing credentials, an unavailable required host, or required evidence marked
partial or unverifiable blocks release. It never becomes an implicit pass.

## Evidence layers

| Layer | What it proves | Gate |
|---|---|---|
| Unit and integration tests | Install, state routing, handoff validation, isolation, recovery, guards, archive, integration | `npm run verify` |
| Lightweight live smoke | Real host invocation and a bounded artifact | `.github/workflows/dogfood.yml` |
| Full live milestone | Real child dispatch, build, review, archive, merge, and tag on one host | release receipt |
| Release reconciliation | Affected hosts passed at one candidate and later changes are evidence-only | `npm run verify:release` |

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
receipt cannot claim a different tier. The same manifest declares the child
APIs that can prove real dispatch for each host. Current status is recorded in
[HOST-MATRIX.md](HOST-MATRIX.md).

## Open gaps

| Gap | Required closure |
|---|---|
| Full live milestone evidence is missing for affected hosts | Record one passing current receipt per affected host |
| Native guards are installed automatically only for Claude, Codex, and Cursor; Codex requires manual project and hook trust | Activate and validate Codex through `/hooks`; add host-native adapters where official APIs support them, otherwise retain an explicit lower tier |
| A required host is unavailable to the maintainer | Keep the release gate blocked until access or maintainer-reviewed evidence exists |
| Live host APIs can change independently of this repo | Keep lightweight dogfood scheduled where credentials exist and re-record full evidence for pipeline-contract releases |

## Historical evidence

`TRUST-EVIDENCE.md` and dated files under `evidence/` are historical records.
Do not rewrite a past verdict. Add a new dated smoke result or versioned release
receipt when evidence changes.
