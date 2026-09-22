# Project runtime lifecycle

Status: implemented and verified locally; changes are uncommitted.

## Approved contract

A project keeps its selected runtime until an explicit upgrade. Runtime versions
live under `~/.gsd-path/runtimes/<content-digest>/`. The tracked
`.gsd-path/runtime.json` records the package version and digest. Fresh clones and
named worktrees inherit that declaration and the stable launchers. Missing or
invalid runtime versions stop with an exact-version restore action; status and
guards never install, download, or select another version.

Existing projects use an explicit, reviewable migration. The migration removes
legacy runtime implementations, writes the declaration and stable launchers, and
leaves the Git index unchanged for review. For current migration safety and
backup behavior, see [Project runtime versions](../DOCS.md#project-runtime-versions).
Its external journal supports interruption recovery and refuses to overwrite
later edits. No live consuming project was migrated by this change.

## Implementation

- `scripts/runtime_store.py` owns publication, restoration, selection, upgrade,
  migration, and recovery. Publication stages complete, hashed bundles outside
  the checkout. OS-owned publication locks release on process exit.
- `scripts/status_runtime.py` resolves and validates the declared bundle without
  writes. Stable project guard launchers execute its verified guards while
  preserving the project's identity and helper trust restrictions.
- Python owns project installation and doctor behavior. Node delegates these
  operations and retains its host-only installer. Both entry points use the same
  external installer lock identity. The unused Node project implementation was
  removed; its duplicate project tests are covered by the Python owner. Node
  retains adapter, real CLI, and cross-language ownership tests.
- Explicit upgrade updates the declaration and compatible status launcher. A
  failed declaration write restores the prior launcher; old runtime versions
  remain available for other projects and branches.
- Every phase skill links the shared runtime-selection rule. Helpers listed in
  the selected runtime manifest use that runtime; other skill resources remain
  bundled with the installed skill.
- The daemon reports the declared runtime version and includes the declaration
  in an explicit project uninstall plan. Shared runtime versions are retained.

## Commands

```sh
gsd-path --runtime-migrate --project /absolute/project --dry-run
gsd-path --runtime-migrate --project /absolute/project
gsd-path --runtime-upgrade --project /absolute/project
gsd-path --runtime-restore --project /absolute/project --source-root /matching/package
```

Migration and upgrade produce reviewable configuration changes. Ordinary status,
guard execution, and exact restoration do not produce checkout changes. An ignore
rule does not replace migration of already tracked generated files.

## Verification

Final results: 169 focused Python tests passed; 62 Node installer and packaging
tests passed. Resource synchronization checked 388 generated resources with no
drift. `git diff --check` passed. The restored implementation passed after all
fault injections. These are focused gates, not a full-repository test run.

Focused Python gate:

```sh
python3 -B -m unittest tests.test_runtime_lifecycle tests.test_install tests.test_sync_skill_resources tests.test_skill_commands tests.test_daemon_plugin.DetectionTests tests.test_daemon_plugin.UninstallPlanTests
```

Node entry points and packaging:

```sh
node --test --test-reporter=tap tests/install.test.mjs tests/package.test.mjs
python3 -B scripts/sync_skill_resources.py --check
git diff --check
```

Observed RED results included missing declaration on the previous installation
layout, Node/Python admitting simultaneous ownership of one install target, and
an active project's doctor refusing status after a bootstrap-changing upgrade.
The matching tests passed after the fixes.

Fault injection independently removed each of these protections and produced the
expected assertion failure before restoring the source:

| Removed protection | Observed failure |
| --- | --- |
| Explicit upgrade changes the selection | Declaration remained unchanged |
| Restore requires the exact source identity | Wrong source was accepted |
| Migration removes generated implementation | Legacy runtime could not be retired |
| Guard helpers must belong to the selected runtime | An identical foreign helper was allowed |
| Status stays read-only | Named worktrees acquired an untracked output file |
| Daemon reports the selected version | Reported version became null |
| Explicit upgrade refreshes a changed bootstrap | Active project status validation was blocked |
| Failed upgrade restores the prior launcher | Launcher bytes changed despite failed upgrade |

The lifecycle tests execute real status and Git guards in named task, verify,
and integration checkouts, then require empty Git status. They also exercise
missing/corrupt runtime restoration, process-exit migration recovery, publication
lock release after process exit, native helper trust, and failed-upgrade rollback.

An extra project-classification rule was rejected: the existing classifier already
handles the declaration correctly, so the new rule had no observable effect.

## Fable review fixes — 2026-09-19

All six accepted findings are fixed. Runtime helpers prevent incidental bytecode
writes; configuration writes preserve exact bytes; migration resumes across path
aliases; restoration accepts declaration annotations; hook previews check guard
ownership; and ship recovery explicitly upgrades and resolves its trust runtime.
See [review findings and resolution evidence](review/runtime-lifecycle-fable.md).

The fix gate passed 151 Python tests and 56 Node installer tests. The documented
upgrade recipe passed separately. Each of six fault injections triggered its
matching regression; all 19 lifecycle tests passed after restoring the source.
Resource synchronization checked 388 resources. Windows newline translation was
emulated; no native Windows execution or full-repository suite was run.

## Remaining scope

This work owns runtime code, launch wiring, and lifecycle state. Project-local
skill copies, retained skill backups, and mixed host/user configuration are the
separate architecture workstream identified during design. Required `.project/`
evidence remains visible. No claim is made that all plugin installation output is
now invisible to Git. The full repository suite and Windows execution were not run.
