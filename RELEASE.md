# GSD Path — Release

This document describes the automated CI and release cycles for the source
repository. Consumer projects use GSD Path through install/update flows
documented in [DOCS.md](DOCS.md); this file is for maintainers.

## CI tiers

| Workflow | Trigger | Gate | Purpose |
| --- | --- | --- | --- |
| [CI](.github/workflows/ci.yml) | Every push to `main` and every pull request | `npm run verify` on Node 18 and 20; `npm run test:daemon` | Offline disk contract, installer, guards, archive, and daemon package |
| [Release trust](.github/workflows/release-trust.yml) | Every pull request and push to `main`; manual dispatch | PR/push: trust validator tests; manual: `npm run verify:release` | Test the proof validator during development; validate frozen-candidate receipts on demand |
| [Dogfood](.github/workflows/dogfood.yml) | Weekly schedule or manual dispatch | Live host smoke | Opt-in live host invocation (requires API secrets) |
| [Release](.github/workflows/release.yml) | Version tag `v*` or manual dispatch | `npm run verify:release`, update `CHANGELOG.md` + README release section, `npm pack --dry-run`, npm publish with provenance + GitHub Release | Ship a trusted version to npm |

Local equivalents:

```bash
make verify           # same offline gate as CI
make verify-release   # frozen-candidate gate: manual release-trust / release
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

Set the intended package name and version in `package.json` and
`package-lock.json` before freezing the candidate. Changes to either invalidate
existing candidate proof.
Before publishing:

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

4. Commit receipts and merge. Run **Actions → Release trust evidence → Run
   workflow** on the frozen candidate with its receipts to re-run the strict
   gate before publication.

Ordinary PRs and `main` pushes run automated verification, including the trust
validator tests, without requiring refreshed release receipts. The
`verify-release-evidence` check name remains active on every PR. Product and
host contract changes can therefore merge before the next candidate is frozen.
Passing PR checks does not establish release trust: all eleven hosts must have
current candidate proof before either publication path can pass `verify:release`.

## Publishing

### Prerequisites

- For automated releases, an npm Trusted Publisher connection for GitHub
  owner `open-gsd`, repository `gsd-path`, workflow `release.yml`, with direct
  `npm publish` allowed. Leave environment blank; this workflow uses none.
  No `NPM_TOKEN` secret is needed.
- `package.json` `version` matches the release you are shipping.
- `npm run verify:release` passes on the release commit.

### First npm publication

The npm package is `@opengsd/gsd-path`; `gsd-path` remains the executable name.
The GitHub repository is `open-gsd/gsd-path` (a different namespace).
The unscoped `gsd-path@1.0.0` was published by mistake. Do not delete or
deprecate it, or configure its Trusted Publisher connection, without a separate
owner decision. Configure publishing only for the scoped package below.

The first corrected publication is prepared separately from the previously
verified `v1.0.0` tag. That tag's evidence does not cover the package identity
change. Any exception to frozen-candidate evidence requires explicit owner
approval; the existing release gates remain in force.

The GitHub release and npm package are separate. If the npm package does not
exist yet, publish the verified release checkout interactively first:

```bash
npm login --registry=https://registry.npmjs.org
npm whoami --registry=https://registry.npmjs.org
npm publish --access public --registry=https://registry.npmjs.org
```

Complete npm's browser login and publishing authentication when prompted.
The publish command runs `prepublishOnly`; do not bypass the evidence gate.
Do not push the release tag until this first publication is complete, since
automated publishing needs the package's Trusted Publisher connection first.
Create the first version's GitHub release separately after confirming npm
publication; do not rerun automated publishing for an already published version.

Then open the package's npm settings and add the Trusted Publisher connection
described above. Future releases use GitHub OIDC on hosted runners. The workflow
uses Node 24, which supplies an npm CLI supporting trusted publishing.
See [npm's setup guide](https://docs.npmjs.com/trusted-publishers/).

### Option A — tag push (recommended)

```bash
# On the release commit after evidence is merged:
git tag -a v1.0.1 -m "Release v1.0.1"
git push origin v1.0.1
```

The [Release](.github/workflows/release.yml) workflow runs `verify:release`,
refreshes `CHANGELOG.md` and the README release section from git history,
dry-runs `npm pack`, publishes to npm with provenance, syncs the release docs
back to `main`, and creates a GitHub Release for the tag.

### Option B — manual dispatch

1. Open **Actions → Release → Run workflow** on the release commit.
2. Enter the semver version (for example `1.0.1`).
3. The same job verifies the release, creates `v1.0.1`, publishes to npm,
   and creates the GitHub Release. It does not depend on a bot-created tag
   triggering another workflow. An existing tag must point to this commit.

Both triggers reject an unscoped or wrong-owner package name and require the
requested version to match `package.json`; the workflow never changes the
frozen package version. Publish runs are serialized across tags and manual
dispatches.

### Release notes automation

`scripts/update_release_docs.mjs` categorizes commits since the previous
`v*` tag and updates:

- `CHANGELOG.md` — Keep a Changelog format, prepended per release
- `README.md` — the `<!-- release-docs -->` block with the latest npm version
  and recent highlights

Preview locally before tagging:

```bash
node scripts/update_release_docs.mjs --version 1.2.0 --dry-run
```

The Release workflow runs the same updater before publish, includes the docs in
the npm tarball, and commits any changes back to `main` after publication.

### After publish

Consumers can follow the [npm install instructions](README.md) or the
[npm update instructions](UPDATE.md#from-npm).

Update notices use `scripts/check_update.py`; until a version is on the registry,
the helper stays silent (see [UPDATE.md](UPDATE.md)).

## What CI does not automate

- Full live milestone runs on every host — recorded manually per release;
  validated by `verify:release`.
- npm publish on every merge — automated publishing uses the Release workflow
  after the trust gate passes; see [First npm publication](#first-npm-publication)
  for the initial manual publish.
- Consumer-repository ship gates — see [HOOKS.md](HOOKS.md) for an optional
  `gsd-path-ship-gate` job template.
