# GSD Path — Release

This document describes the automated CI and release cycles for the source
repository. Consumer projects use GSD Path through install/update flows
documented in [DOCS.md](DOCS.md); this file is for maintainers.

## CI tiers

| Workflow | Trigger | Gate | Purpose |
| --- | --- | --- | --- |
| [CI](.github/workflows/ci.yml) | Every push to `main` and every pull request | `npm run verify` on Node 18 and 20; `npm run test:daemon` | Offline disk contract, installer, guards, archive, and daemon package |
| [Release trust](.github/workflows/release-trust.yml) | PR/push touching trust evidence, platforms, or host manifest; manual dispatch | `npm run verify:release` | Block contract or evidence drift before merge |
| [Dogfood](.github/workflows/dogfood.yml) | Weekly schedule or manual dispatch | Live host smoke | Opt-in live host invocation (requires API secrets) |
| [Release](.github/workflows/release.yml) | Version tag `v*` or manual dispatch | `npm run verify:release`, then npm publish + GitHub Release | Ship a trusted version to npm |

Local equivalents:

```bash
make verify           # same offline gate as CI
make verify-release   # same trust gate as release-trust / release
make test-daemon      # daemon-only subset
```

See [TEST_ENVIRONMENT.md](TEST_ENVIRONMENT.md) for prerequisites and troubleshooting.

## Release contract

A version is releasable only when:

1. `npm run verify` passes (automated in CI on every PR).
2. Every host declared in `scripts/skill-resources.json` has a current
   full-milestone receipt under
   `docs/trust-validation/evidence/releases/<version>/`.
3. `npm run verify:release` proves that only trust evidence or its summaries
   changed after the tested candidate SHA.

The package's `prepublishOnly` script runs `verify:release`, so a local
`npm publish` cannot bypass the gate.

Details: [docs/trust-validation/TRUST-VALIDATION-SPEC.md](docs/trust-validation/TRUST-VALIDATION-SPEC.md).

## Recording trust evidence

Before bumping `package.json` or publishing:

1. Freeze a clean candidate on `main`:

   ```bash
   bash scripts/prepare_release_evidence.sh --candidate .
   ```

2. Run each host harness from the prepared directories (see
   [HOST-MATRIX.md](docs/trust-validation/HOST-MATRIX.md)).

3. Validate the full set locally:

   ```bash
   npm run verify:release
   ```

4. Commit receipts and merge. The **Release trust** workflow re-runs the same
   gate on the pull request.

## Publishing

### Prerequisites

- Repository secret `NPM_TOKEN` — npm Automation token with publish access for
  the `gsd-path` package.
- `package.json` `version` matches the release you are shipping.
- `npm run verify:release` passes on the release commit.

### Option A — tag push (recommended)

```bash
# On the release commit after evidence is merged:
git tag -a v1.0.1 -m "Release v1.0.1"
git push origin v1.0.1
```

The [Release](.github/workflows/release.yml) workflow runs `verify:release`,
publishes to npm, and creates a GitHub Release for the tag.

### Option B — manual dispatch

1. Open **Actions → Release → Run workflow** on the release commit.
2. Enter the semver version (for example `1.0.1`).
3. The workflow creates and pushes `v1.0.1`, which starts the publish job
   (`verify:release` → npm → GitHub Release).

### After publish

Consumers can install from npm:

```bash
npx gsd-path@latest --update
```

Update notices use `scripts/check_update.py`; until a version is on the registry,
the helper stays silent (see [UPDATE.md](UPDATE.md)).

## What CI does not automate

- Full live milestone runs on every host — recorded manually per release;
  validated by `verify:release`.
- npm publish on every merge — only the Release workflow publishes, and only
  after the trust gate passes.
- Consumer-repository ship gates — see [HOOKS.md](HOOKS.md) for an optional
  `gsd-path-ship-gate` job template.
