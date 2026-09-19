# Runtime lifecycle: Fable review

Date: 2026-09-19. Reviewer: `claude-fable-5-1`, confirmed by the CLI response.
Scope: the uncommitted runtime lifecycle implementation and its approved design.
Reviewed base: `fd2ca9234c6332652c09e274300c6ea14c1143c2` plus the captured working-tree changes.

**Current status: all six accepted findings fixed and verified.** See the
resolution evidence below. Fable has not re-reviewed the fixes.

**Original review verdict: changes required.**
Fable performed a static, read-only review. The parent then ran the focused
reproductions below in disposable projects with an isolated HOME. Product files
were unchanged throughout; their recorded hashes still match the review input.
No fixes, commits, pushes, or live-project migrations were performed in this review.

## Accepted findings

1. **P1 — A helper invocation can invalidate the shared runtime.**
   `scripts/status_runtime.py:126` rejects a generated `__pycache__` directory.
   With ordinary adjacent bytecode caching, running `archive_milestone.py --help`
   without `-B` succeeds, creates that directory, and makes subsequent runtime
   resolution exit 2 with `unexpected runtime files`. Every project selecting
   that digest is affected. The SHIP recovery examples omit `-B`.
   Reproduced using `python3 -X pycache_prefix= <runtime>/archive_milestone.py --help`:
   this selects ordinary adjacent caching because this machine's Apple Python
   defaults to an external cache and therefore masks the failure.
   Fix direction: prevent incidental bytecode writes at helper entry points and
   correct the documented commands. Do not weaken manifest trust without checking
   how Python loads cached bytecode.

2. **P2 — Windows newline translation conflicts with byte-exact recovery.**
   `scripts/runtime_store.py:145` writes text through `os.fdopen(..., "w")`.
   Emulating Windows text translation produced CRLF where the source and migration
   journal record LF. This can make a launcher fail byte comparison or make
   interrupted migration reject its own output as a later user edit.
   Verified under Windows newline emulation, **not on a native Windows machine**.
   Fix direction: write encoded bytes in binary mode.

3. **P2 — Ship recovery still relies on implicit runtime refresh.**
   `skills/gsd-path-ship/SKILL.md` and generated `skills/gsd-path/SHIP.md:374-391`
   say to refresh a disposable trust anchor, then use the fixed runtime.
   Reproduced `refresh_hooks` retaining the existing pin and returning only the
   explicit-upgrade note. The documented preview condition cannot be met.
   Fix direction: explicitly upgrade the disposable trust project, resolve its
   selected runtime, and invoke helpers with `-B`. Edit the canonical ship skill.

4. **P2 — An interrupted migration cannot resume through an equivalent path.**
   `scripts/runtime_store.py:154-165` hashes the resolved project path for journal
   lookup but compares a literal project string inside the journal.
   Reproduced process exit after writing the declaration under `/tmp/...`, then
   resumed through `/private/tmp/...`. The CLI exited 1 with
   `invalid runtime migration journal`, although both paths name the same project.
   Fix direction: canonicalize project identity consistently when recording and
   validating the journal.

5. **P3 — Validated declarations can be rejected by exact restoration.**
   `scripts/status_runtime.py` accepts an extra declaration key, while
   `scripts/runtime_store.py:81` compares the entire declaration dictionary.
   Reproduced successful resolution after adding a `comment` field, followed by
   restore rejecting the correct package as `source does not match`.
   Fix direction: use the same identity-field validation for lookup and restore.

6. **P3 — Hook initialization dry-run omits ownership validation.**
   `scripts/install.py:1749-1752` returns preview paths before the unpinned
   initialization path validates guard ownership.
   Reproduced a successful preview with an unmanaged `.gsd-path/guard_hook.py`;
   the real operation correctly refused that same input. No foreign file was
   overwritten. Fix direction: run the same non-writing validation before preview.

## Other Fable observations

- Migration can select a supplied package different from tracked legacy bytes.
  This follows the reviewed migration's initial version selection; preserving an
  unpinned legacy version was not an approved requirement. Not accepted as a blocker.
- Hook initialization creates missing contracts and the Claude bridge. Confirmed,
  but it does not overwrite existing contracts; no breach of the stated
  preserve-existing-contracts guarantee was reproduced.
- Mode 0600 restricts other local users. Shared multi-user runtime access was not
  part of the approved user-level storage contract. No scope expansion proposed.
- The legacy launcher's old lock lookup no longer matches new installer locks.
  New installers refuse legacy refresh and require migration, so the claimed
  old refresh handshake failure was not established for the supported path.
  The cited HOOKS.md parenthesis is balanced in the reviewed file.

## Evidence

- [Raw review](runtime-lifecycle-fable-raw.md)
- [Reproduction results](runtime-lifecycle-fable-reproductions.json)
- [Approved implementation contract](../runtime-lifecycle-work.md)

The earlier passing suites remain useful evidence, but they did not cover these
failures. This review does not replace the focused regression checks needed after
fixes.

## Resolution evidence — 2026-09-19

| Finding | Fix | Regression evidence |
| --- | --- | --- |
| P1 bytecode writes | All 20 runtime helpers disable bytecode writes before local imports; manifest validation stays strict. | Execute every helper without `-B` using ordinary adjacent caching, then require no cache, successful runtime resolution, and clean Git status. |
| P2 newline translation | Atomic configuration writes use UTF-8 bytes in binary mode. | Emulated Windows text translation cannot change written bytes. Native Windows was not run. |
| P2 ship recovery | Canonical recovery commands explicitly upgrade, resolve the selected runtime, and invoke recovery with `-B`; generated resources are synchronized. | Execute the documented preview, upgrade, and resolver commands against a disposable project with a different source digest. |
| P2 path aliases | Migration records the resolved project path and compares resolved journal identity. | Interrupt migration through a symlink alias, then resume through the canonical path. |
| P3 declaration annotations | Restoration compares runtime identity fields without rejecting extra declaration keys. | Restore the exact source while preserving the annotated declaration bytes. |
| P3 preview validation | Unpinned hook preview performs the same ownership validation as apply. | Both preview and apply refuse a foreign guard without changing it or creating a declaration. |

Verification completed:

```sh
python3 -B -m unittest tests.test_runtime_lifecycle tests.test_install
# 151 tests passed
node --test --test-reporter=tap tests/install.test.mjs
# 56 tests passed
python3 -B -m unittest tests.test_runtime_lifecycle.RuntimeLifecycleTests.test_refresh_keeps_pin_and_upgrade_is_explicit
# Documented command recipe passed after strengthening this test
python3 -B -m unittest tests.test_runtime_lifecycle
# 19 tests passed after fault injection and source restoration
python3 -B scripts/sync_skill_resources.py --check
# 388 resources checked
git diff --check
```

The new regressions failed before implementation. Six separate fault injections
then removed bytecode suppression, binary writes, canonical path comparison,
identity-only restoration comparison, preview ownership validation, and the
documented explicit upgrade. Each matching test failed for the expected defect.
The mutation harness suppressed only the generated-resource drift check, so
the behavioral failure could run; all modified source bytes were restored before
the final lifecycle and normal resource checks.

Changes remain uncommitted. No installed plugin or live project was migrated.
