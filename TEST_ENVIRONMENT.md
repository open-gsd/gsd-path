# GSD Path — Test Environment

One guide for running the full automated gate on a clean machine or in CI.
The product is a disk-backed pipeline (`.project/`, git worktrees, Python
helpers, Node installer). **No database or Docker services are required** for
the default offline suite.

## Prerequisites

| Tool | Minimum | CI pin | Notes |
| --- | --- | --- | --- |
| **Node.js** | 18.17 | 18 and 20 matrix | `node --test` installer/wizard suite |
| **npm** | ships with Node | latest on runner | lockfile install via `npm ci` |
| **Python** | 3.9 | 3.12 | stdlib `unittest` only for the core gate |
| **git** | any recent | ubuntu-latest default | worktree/isolation tests need git 2.30+ |

Optional for extended tiers:

| Tool | When |
| --- | --- |
| **swiftc** | macOS daemon tray build tests only (skipped when absent) |
| **Host CLIs** (`claude`, `codex`, …) | Live dogfood / release evaluation only |
| **API keys** | Live dogfood and host evaluation |

Check versions:

```bash
make check-prereqs
# or: bash scripts/check-test-prereqs.sh
```

## Bootstrap (first time)

```bash
git clone https://github.com/open-gsd/gsd-path.git
cd gsd-path
make install          # npm ci — respects package-lock.json
make verify           # full offline gate (same as CI)
```

Equivalent npm commands:

```bash
npm ci
npm run verify
```

Expected runtime on a typical laptop: Node smoke ~15s; full `verify` several
minutes (Python suite exercises git worktrees, installer paths, and full-cycle
disk contract).

## Test tiers

| Tier | Command | What it proves | Secrets |
| --- | --- | --- | --- |
| **Smoke** | `make test-smoke` / `npm test` | Node installer, wizard, package graph | none |
| **Integration** | `make test-integration` / `npm run test:python` | Python helpers, git isolation, full milestone disk contract | none |
| **Sync** | `make test-sync` | Generated per-skill copies match canonical sources | none |
| **Verify (CI)** | `make verify` / `npm run verify` | smoke + integration + sync | none |
| **Release** | `make verify-release` / `npm run verify:release` | verify + trust-evidence receipts | none |
| **Daemon** | `make test-daemon` | `gsd-path-daemon` package only | none |
| **E2E / dogfood** | `make test-e2e` | Live host against fixture repo | host CLI + API key |
| **UI** | see below | Daemon dashboard in Orca browser | `GSD_UI_TEST=1` |

### CI

| Workflow | When | Command |
| --- | --- | --- |
| [ci.yml](.github/workflows/ci.yml) | Every push and pull request | `npm run verify` (Node 18 + 20) and `npm run test:daemon` |
| [release-trust.yml](.github/workflows/release-trust.yml) | PR/push touching release evidence, host matrix summaries, `platforms/`, or host manifest; manual | `npm run verify:release` |
| [dogfood.yml](.github/workflows/dogfood.yml) | Weekly or manual | Live host smoke (`tests/dogfood.py`) |
| [release.yml](.github/workflows/release.yml) | Version tag `v*` or manual dispatch | `verify:release` → npm publish → GitHub Release |

No `.env` file is loaded for the offline CI jobs. Dogfood and release publish
need repository secrets (`ANTHROPIC_API_KEY` / `OPENAI_API_KEY` for dogfood;
`NPM_TOKEN` for release). Maintainer steps: [RELEASE.md](RELEASE.md).

## Environment variables

Copy [`.env.example`](.env.example) for opt-in tiers:

```bash
cp .env.example .env
# edit, then:
set -a && source .env && set +a
```

The offline gate ignores `.env`. Variables matter only for live host runs,
strict registry checks, or daemon UI acceptance.

## Fixtures

| Location | Use |
| --- | --- |
| [`fixtures/minimal-pipeline/`](fixtures/minimal-pipeline/) | Copy into a throwaway repo; define-phase `.project/` + intentional doc drift |
| [`tests/test_full_cycle.py`](tests/test_full_cycle.py) | Full milestone disk contract in unittest (no AI host) |
| [`tests/dogfood.py`](tests/dogfood.py) | Builds widget-counter fixture for live smoke |

See [`fixtures/README.md`](fixtures/README.md).

## Live / E2E (opt-in)

### Dogfood smoke

```bash
# Install host CLI and authenticate first, then:
export GSD_E2E_HOST=claude    # or codex
export ANTHROPIC_API_KEY=...  # claude
# export OPENAI_API_KEY=...   # codex
make test-e2e
```

Or directly:

```bash
python3 tests/dogfood.py --host claude --evidence /tmp/gsd-path-dogfood
```

### Release host evaluation

```bash
python3 -B tests/evaluate_host.py prepare --host claude --directory /tmp/eval --candidate .
# follow evaluate_host.py module docstring for run/child steps
```

### Daemon UI acceptance

```bash
GSD_UI_TEST=1 python3 -m unittest discover -s tests -p test_daemon_board_ui.py
```

### Strict live host registry

```bash
GSD_LIVE_HOSTS=1 npm run test:python -- -k test_host_registry
```

Fails if documented live-verified host CLIs are not on `PATH`.

## Daemon package

The progress daemon lives under [`daemon/`](daemon/). Core tests run via the
main Python suite (`test_daemon_*.py`). Manual install:

```bash
PYTHONPATH=daemon python3 -m gsd_daemon install --dry-run
```

Tray extras (`pystray`, `Pillow`) are optional; tests mock or skip when absent.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `node: command not found` or version &lt; 18.17 | Install Node 18.17+ (nvm/fnm/system) |
| `python3` missing or &lt; 3.9 | Install Python 3.9+; CI uses 3.12 |
| `git` errors in isolation tests | Ensure git ≥ 2.30; configure `user.name` / `user.email` for manual work |
| `sync_skill_resources.py --check` fails | Run `python3 scripts/sync_skill_resources.py` and commit generated copies |
| `npm ci` fails | Use the repo's `package-lock.json`; do not delete the lockfile |
| Tests hang with ResourceWarning subprocess | Usually transient; re-run. If persistent, check for orphaned `git`/`python` children |
| `test_implicit_invocation` skipped | Expected without `codex` on PATH |
| `test_daemon_board_ui` skipped | Set `GSD_UI_TEST=1` and Orca browser |
| Dogfood fails auth | Export the correct API key; confirm host CLI login |

## Suite inventory

Detailed per-file mapping: [`docs/trust-validation/automated-test-inventory.md`](docs/trust-validation/automated-test-inventory.md).

## What Jeremy must provision manually

| Item | Required for |
| --- | --- |
| Nothing | `make verify` / CI |
| `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` | Dogfood workflow / `make test-e2e` |
| Host CLI install + auth | Live dogfood and release evaluation |
| GitHub repo secrets (above keys) | Scheduled/manual dogfood workflow |
| Orca embedded browser | `GSD_UI_TEST` dashboard acceptance |
| `swiftc` (macOS) | Native tray app build during daemon install tests |
