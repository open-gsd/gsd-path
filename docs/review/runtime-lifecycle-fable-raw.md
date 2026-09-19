Review complete. I did not execute any tests or commands; every finding below comes from reading the diff, the untracked store and test modules, and tracing callers.

**Verdict: not PASS.** One High, three Medium, and several Low findings, in priority order.

1. **High. Store validation counts `__pycache__` as corruption, and a documented skill command creates it.** `scripts/status_runtime.py:126` rejects any directory entry not in the manifest. `scripts/archive_milestone.py:25-50` imports siblings and never sets `dont_write_bytecode`, and `skills/gsd-path/SHIP.md:389-390` tells the agent to run it without `-B`. The guard permits that invocation because `-B` is optional at `scripts/guard_hook.py:1828`. Trigger: on a pinned project, run `python3 ~/.gsd-path/runtimes/<digest>/archive_milestone.py --help`. Observed: Python writes `<digest>/__pycache__/`, after which status, both guards, doctor, `--update --project`, and `--hooks-refresh` fail with "unexpected runtime files" for every project pinning that digest until `--runtime-restore`. Expected: read-only consumers keep working since the manifest files are unchanged. Fix: ignore `__pycache__` in the inventory check (compare regular files only) and add `-B` to SHIP.md.

2. **Medium. `atomic_config` uses text mode, so Windows gets CRLF translation.** `scripts/runtime_store.py:145`. After `--runtime-upgrade` the launcher bytes differ from the store copy, so doctor reports a stale launcher and `_project_runtime_matches` fails. After an interrupted migration, `recover_migration` compares on-disk bytes to the journal's LF `after` value and refuses with "would overwrite a changed file", blocking recovery. Not reproduced on this macOS host. It follows from `TextIOWrapper` semantics, and the module has explicit Windows branches. Fix: write encoded bytes through a binary handle.

3. **Medium. The SHIP.md recovery procedure depends on `--hooks-refresh` replacing the runtime.** `skills/gsd-path/SHIP.md:374-391`. For a pinned project, `refresh_hooks` returns the "selected runtime retained" note and changes nothing. Step 2's continue condition can never be met, and step 3 would execute the old pinned runtime rather than the fixed one. Fix: rewrite the step around `--runtime-upgrade` and `--runtime-path`.

4. **Medium. Migration of tracked legacy files pins the supplied package, not the retired bytes.** `scripts/runtime_store.py:237-243` only requires a clean index for tracked files, while untracked files must match source byte for byte. Trigger: tracked legacy runtime from version X, then `--runtime-migrate --source-root <version Y>`. Observed: the declaration pins Y and the diff shows only deletions plus a version string. Expected: the same byte comparison as the untracked branch, or an explicit old-versus-new report. Fix: apply one rule to both branches.

5. **Low. Restore rejects declarations with any extra key.** `scripts/runtime_store.py:81` compares whole dicts, while `scripts/status_runtime.py:84-95` tolerates extra keys. Status works, restore says "source does not match" with the correct package. Fix: compare version and digest only.

6. **Low. `--hooks-init` and `--hooks-refresh` now create contracts when absent.** `refresh_hooks` routes through `_apply_project`, whose destinations include AGENTS.md, WORKFLOW.md, and the Claude bridge (`scripts/install.py:1011-1025`, `1303-1316`). A bare repo plus `--hooks-init --claude` gains all three. UPDATE.md still says hooks-init preserves contracts. Fix: exclude contract and bridge destinations on the refresh path.

7. **Low. Migration journal identity mismatch across path spellings.** `scripts/runtime_store.py:154-155` keys the journal by the resolved path but line 165 compares the unresolved string. An interruption under `/tmp/x` followed by `/private/tmp/x` yields "invalid runtime migration journal" and blocks migration. Fix: store and compare the resolved path.

8. **Low. Dry-run refresh skips validation on the unpinned path.** `refresh_hooks` returns the two paths before `_validate_hooks_refresh` or `prepare(dry_run=True)`, so a dry run can succeed where the real run fails.

9. **Low. Upgrade and migration leave launchers and `runtime.json` at mode 0600** since `atomic_config` keeps the `mkstemp` mode. Git is unaffected. Other local users lose read access.

10. **Low. The legacy launcher still waits on `repo/.gsd-path-install-lock`** (`scripts/status_runtime.py:157`) while both installers now lock under `~/.gsd-path/install-locks`. That handshake is dead for un-migrated projects. Also `HOOKS.md:112` has an unbalanced parenthesis.

Verified as correct by tracing: guard launcher execution with the project identity preserved, `sys.path` ordering under `run_guard` (no runtime module imports the guard modules by name), store-only helper trust, restore identity enforcement, upgrade rollback, publication lock release, adapter wiring, and daemon classification of pinned projects.
