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

The [Trust Validation Spec](docs/trust-validation/TRUST-VALIDATION-SPEC.md#release-contract)
owns the release gate, live-check scope, and receipt requirements.

## Recording trust evidence

Keep the intended version in `package.json` and `package-lock.json` while
verification runs. A failed attempt keeps that version for its retry. The
publication workflow never increments or pushes a package version. A version-only
change does not invalidate live evidence; package identity, dependencies, and
other package changes do.

1. From a clean checkout, inspect which hosts need new evidence:

   ```bash
   python3 -B scripts/check_trust_evidence.py --repo . --plan
   ```

   The report names accepted receipt paths and original candidates, plus
   `required_runs` and their reasons. It validates existing evidence without
   invoking any model. Historical receipts stay in their original directories.

2. Prepare and run only the missing or stale hosts:

   ```bash
   bash scripts/prepare_release_evidence.sh --candidate .
   ```

   Run the prepared harnesses as described in [HOST-MATRIX.md](docs/trust-validation/HOST-MATRIX.md).
   The [live-check scope](docs/trust-validation/TRUST-VALIDATION-SPEC.md#live-check-scope)
   defines host exclusions and when existing receipts can be reused.

3. Commit new receipts, then validate the clean checkout:

   ```bash
   npm run verify:release
   ```

   The publication workflow runs this gate once before tagging or publishing.
   Its publish step skips npm lifecycle scripts to avoid duplicating the gate.
   Local `npm publish` retains `prepublishOnly` verification.

A full matrix is an explicit manual action:

```bash
bash scripts/prepare_release_evidence.sh --candidate . --full
```

After those runs, `python3 -B scripts/check_trust_evidence.py --repo . --full`
requires receipts under the current package version. Routine releases use the
default affected checks. The **Release trust evidence** workflow is available
for an additional manual gate when needed; it is not an extra required rehearsal
before the publication workflow's identical gate.

Ordinary PRs and `main` pushes run automated verification, including the trust
validator tests, without requiring refreshed release receipts. The
`verify-release-evidence` check name remains active on every PR. Product and
host contract changes can therefore merge before the next candidate is frozen.
Passing PR checks does not establish release trust. Both publication paths
must pass the [release contract](#release-contract).

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
2. Leave **version** empty to use the prepared `package.json` version, or enter
   that same version explicitly. A mismatch fails without changing files.
3. The job verifies the frozen release and package before creating `vX.Y.Z`,
   publishing to npm, or syncing documentation to `main`. An existing tag must
   point to this commit. Failure before verification creates no version commit,
   push, tag, npm publication, or GitHub release.

Local candidate preparation uses these bump rules:

| Signal since previous tag | Next version |
| --- | --- |
| `BREAKING CHANGE` or `type!:` commit | major (`1.1.0` → `2.0.0`) |
| `feat:` commit | minor (`1.1.0` → `1.2.0`) |
| `fix:` / `perf:` commit | patch (`1.1.0` → `1.1.1`) |
| `--bump major` / `minor` / `patch` | selected increment when preparing a new version |

Preview locally:

```bash
node scripts/bump_version.mjs --bump auto --dry-run
npm run release:bump -- --dry-run
```

Apply a new candidate version locally with `npm run release:bump`. If the
package version is already ahead of the latest release tag, the helper reuses
that pending version, including on a retry; it does not compound an unpublished
bump. `--from` is an explicit override for intentionally preparing another
version. Neither the helper nor its preview pushes to `main`.

Tag pushes require `package.json` to match the tag before dispatch. Both
publication paths keep the verified package version unchanged through
`npm publish`. Publish runs are serialized across tags and manual dispatches.

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

- Full live milestone runs — record required receipts manually according to
  the [release contract](#release-contract).
- npm publish on every merge — automated publishing uses the Release workflow
  after the trust gate passes; see [First npm publication](#first-npm-publication)
  for the initial manual publish.
- Consumer-repository ship gates — see [HOOKS.md](HOOKS.md) for an optional
  `gsd-path-ship-gate` job template.
