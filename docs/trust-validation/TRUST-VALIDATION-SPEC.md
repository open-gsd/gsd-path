# GSD Path — Trust Validation Spec

**Status:** Active release contract
**Updated:** 2026-09-20
**Scope:** Release evaluation hosts selected from `scripts/skill-resources.json`
**Install path:** Node or Python installer from a clone; Node is the npm and
interactive entry point.

## Release contract

Every release is trusted only when:

1. `npm run verify` passes.
2. Every evaluation host has validated full-milestone evidence. Receipts keep
   their original package version and candidate SHA under
   `evidence/releases/<original-package-version>/`. Each host must identify a
   distinct run, landing commit, ship commit, and integration commit.
3. `npm run verify:release` validates those receipts and compares each tested
   candidate with HEAD. Reuse is allowed when that host's workflow inputs are
   unchanged under the classification below. Installer tooling is verified by
   offline tests instead of repeating agent workflows. Missing, invalid, or stale evidence
   requires a fresh run. A current-version receipt takes precedence; a failed
   current receipt cannot be hidden by an older pass.

### Live-check scope

Release evaluations cover Codex, Claude, Grok, OpenCode, Copilot, Antigravity,
Cursor, and Kimi. Qwen, Kiro, and Zed are excluded at the maintainer's request
because their live runs require API credits. Their installer support and
offline contract tests remain. Exclusion is not a live-test pass; historical
receipts and failed attempts remain unchanged. The preparation script uses the
same host selection as the validator and does not prepare these three hosts.

`scripts/check_trust_evidence.py --plan` reports `required_runs`, reasons,
accepted receipt paths, original versions, and original candidate SHAs. The
preparation script prepares only those required hosts. It never launches a
host or spends model credits itself.

Each receipt candidate must be a proven ancestor of HEAD. The comparison below
is applied separately to each candidate, so evidence from independent host
runs can be combined. Missing history cannot prove reuse. The nearest prior
release tag remains an informational change summary, not a substitute for a
validated receipt. No tag alone exempts a host with missing evidence.

| Changed files | Required live checks |
|---|---|
| `platforms/<declared-host>/` | That host if included in release evaluations; multiple host changes combine |
| `scripts/install.mjs`, `scripts/install.py`, `scripts/wizard.mjs`, `scripts/runtime_store.py` | None; offline installer lifecycle, migration, rollback, runtime pinning, and installed-guard tests apply |
| Shared adapters, skills, runtime scripts, `AGENTS.md`, `WORKFLOW.md`, or unclassified paths | Every release evaluation host |
| `docs/`, other root Markdown, `tests/`, `.github/`, `daemon/` | None |
| `scripts/bump_version.mjs`, `scripts/update_release_docs.mjs`, `scripts/prepare_release_evidence.sh`, `scripts/check_trust_evidence.py` | None; automated verification still applies |
| `package.json`, `package-lock.json` | None only when changes are limited to the top-level version and lockfile root-package version; otherwise every release evaluation host |

Added and deleted paths count, including both sides of renames. No old receipt
is relabeled as current evidence. Required receipts retain all existing
candidate, native-child, task, review, archive, integration, and guard checks.

Installer tooling runs during installation, update, and migration; a complete
agent milestone does not replace tests of those operations. This category does
not exempt the files it installs: changes to skills, host adapters, guard
implementations, runtime payloads, the host manifest, or package contents still
use their own live-check classification. Mixed changes combine requirements.
`npm run verify` remains required and includes the installer and guard suites.

Release 1.2.0 includes shared pipeline changes, so all eight evaluation hosts
need evidence that covers those changes. Subsequent documentation, version-only,
and release-policy changes can reuse it. Never rewrite a receipt's candidate
SHA or package version to claim a fresh run.

A full matrix is manual: `bash scripts/prepare_release_evidence.sh --full`
prepares every evaluation host, regardless of reusable receipts. To require
receipts filed under the current version, validate with
`python3 -B scripts/check_trust_evidence.py --repo . --full`.

Local `npm publish` runs the release gate through `prepublishOnly`. The release
workflow runs the gate explicitly once, then publishes with `--ignore-scripts`
to avoid running the same complete verification a second time. The
release-trust workflow also provides the gate on demand.

Missing credentials, an unavailable required host, or required evidence marked
partial or unverifiable blocks release. It never becomes an implicit pass.

## Evidence layers

| Layer | What it proves | Gate |
|---|---|---|
| Unit and integration tests | Install, state routing, handoff validation, isolation, recovery, guards, archive, integration | `npm run verify` |
| Lightweight live smoke | Real host invocation and a bounded artifact | `.github/workflows/dogfood.yml` |
| Full live milestone | Real child dispatch, build, review, archive, merge, and tag on one host | release receipt |
| Release reconciliation | Every evaluation host has validated evidence reusable under [Live-check scope](#live-check-scope) | `npm run verify:release` |

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
| Required evidence is missing, invalid, or stale | Record a passing receipt for each host in the validator's `required_runs`; see [Live-check scope](#live-check-scope) |
| Native guards are installed automatically only for Claude, Codex, and Cursor; Codex requires manual project and hook trust | Activate and validate Codex through `/hooks`; add host-native adapters where official APIs support them, otherwise retain an explicit lower tier |
| A required host is unavailable to the maintainer | Keep the release gate blocked until access or maintainer-reviewed evidence exists |
| Live host APIs can change independently of this repo | Keep lightweight dogfood scheduled where credentials exist and re-record full evidence for pipeline-contract releases |

## Historical evidence

`TRUST-EVIDENCE.md` and dated files under `evidence/` are historical records.
Do not rewrite a past verdict. Add a new dated smoke result or versioned release
receipt when evidence changes.
