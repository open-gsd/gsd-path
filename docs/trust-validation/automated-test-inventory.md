# GSD Path — Automated Test & CI Inventory

**Generated:** 2026-08-05; **inventory updated 2026-08-23**
**Repo:** `open-gsd/gsd-path` @ local workspace
**Complete local gate:** `npm run verify` (see [TEST_ENVIRONMENT.md](../../TEST_ENVIRONMENT.md))

## CI

See [RELEASE.md — CI tiers](../../RELEASE.md#ci-tiers) for the configured
GitHub Actions workflows, triggers, and gates, and
[Publishing](../../RELEASE.md#publishing) for release authentication.

## How to run

```bash
npm run verify
```

This runs the Node tests, all Python unittest modules, and the generated-resource
sync check. Node requires **≥18.17**. The Python suite has no third-party runtime
dependency.

The offline host runner checks are in `tests/test_host_*.py`; their registry
contract is documented in [tests/hosts/__init__.py](../../tests/hosts/__init__.py).
For the separate opt-in release-evidence driver, see the usage and limitations in
[tests/evaluate_host.py](../../tests/evaluate_host.py).

## Suite inventory

| File | Runner | Primary subject |
|------|--------|----------------|
| `tests/install.test.mjs` | `node --test` | `scripts/install.mjs` — paths, all targets, dry-run, rollback, `--local`, `--update`, hooks + refresh |
| `tests/package.test.mjs` | `node --test` | npm package manifest / packaging checks |
| `tests/wizard.test.mjs` | `node --test` | `scripts/wizard.mjs` — interactive installer arguments from a fake key stream |
| `tests/test_install.py` | unittest | `scripts/install.py` — Python installer (global/local install, update, dry-run, rollback, tiered hooks) |
| `tests/test_archive_milestone.py` | unittest | `scripts/archive_milestone.py` — prepare, derived manifest, validation, ship commit, resumable integration, carry-forward |
| `tests/test_bootstrap_repository.py` | unittest | `scripts/bootstrap_repository.py` — journaled creation/resume and unjournaled collision refusal |
| `tests/test_build_state.py` | unittest | `scripts/build_state.py` — dependency-ready task selection and landed-task reconciliation |
| `tests/test_check_docs_audit.py` | unittest | `scripts/check_docs_audit.py` — tracked/untracked Markdown inventory and docs-audit artifact gate |
| `tests/test_detect_project.py` | unittest | `scripts/detect_project.py` — owned/orphan/brownfield/greenfield classification and initialization; `scripts/promote_lookahead.py` — lookahead selection, snapshots, and contract comparison |
| `tests/test_dogfood.py` | unittest | `tests/dogfood.py` — every declared host has an automated or explicitly blocked manual evidence route |
| `tests/test_check_update.py` | unittest | `scripts/check_update.py` — version compare, cache, notice |
| `tests/test_discussion_records.py` | unittest | `scripts/discussion_records.py` — paired append, half-write recovery, pending records, dispositions |
| `tests/test_dispatch_contract.py` | unittest | runtime dispatch contract — host branches, model selection, and bounded child responsibilities |
| `tests/test_full_cycle.py` | unittest | one milestone through phase gates, task isolation, ship, integration, and next binding |
| `tests/test_guard_hook.py` | unittest | `scripts/guard_hook.py` — archive deny, git commands, path normalization, subprocess E2E |
| `tests/test_git_guard.py` | unittest | `scripts/git_guard.py` — immutable archive destinations, ship scope, canonical integration merge, hook E2E |
| `tests/test_handoffs.py` | unittest | `scripts/check_handoffs.py` — research, decide, roadmap, plan, wave, final-gap, and patch gates |
| `tests/test_implicit_invocation.py` | unittest | Codex CLI — router absent from ordinary skill catalog (**skips if `codex` not on PATH**) |
| `tests/test_isolation.py` | unittest | `scripts/isolation.py` — named worktrees, task landing, artifact collection, checkpoints, guarded retirement, CLI E2E |
| `tests/test_loop_run.py` | unittest | `scripts/loop_run.py` — atomic claims, recovery, admission limits, completion, and status |
| `tests/test_migrate_core.py` | unittest | `scripts/migrate_core.py` — Core bundle capture, manifest verification, hook inventory, and partial/quick-only trees |
| `tests/test_core_hook_gate.py` | unittest | `scripts/core_hook_gate.py` — scoped Core hook bypass for migrated projects |
| `tests/test_core_hook_settings.py` | unittest | `scripts/core_hook_settings.py` — receipt-based Core hook cutover and rollback |
| `tests/test_pipeline_git.py` | unittest | `scripts/pipeline_git.py` — canonical subjects, initial/next branch binding, and mutation refusal |
| `tests/test_pipeline_state.py` | unittest | `scripts/pipeline_state.py` — state validation, route decisions, status snapshot, transitions, and lookahead promotion recovery |
| `tests/test_pipeline_undo.py` | unittest | `scripts/pipeline_undo.py` — unpublished checkpoint, task, archive, and lookahead undo |
| `tests/test_pipeline_diagnose.py` | unittest | `scripts/pipeline_diagnose.py` — read-only stuck/unowned/ok diagnosis |
| `tests/test_review_panel.py` | unittest | `scripts/review_panel.py` — canonical panel resolution, validation, and merge parsing |
| `tests/test_router_contract.py` | unittest | executable route phase matrix, bundled phase contracts, and STATE template compatibility |
| `tests/test_sync_skill_resources.py` | unittest | generated resources, manifest-owned links, and dispatch branches |
| `tests/test_task_briefs.py` | unittest | task frontmatter, recorded bases, ownership, commit evidence, and verify scope |
| `tests/test_wizard_tty.py` | unittest | no-flag CLI opens the wizard on a real PTY and hands off to the installer |
| `tests/test_trust_evidence.py` | unittest | release receipts, candidate ancestry, pass fields, and receipt reuse under the [live-check scope](TRUST-VALIDATION-SPEC.md#live-check-scope) |
| `tests/dogfood.py` | script (`--host <declared-host>`) | **Live** host run: Claude/Codex have headless adapters; every other declared host routes explicitly to the manual full-evidence template instead of being silently omitted |

**Note:** `scripts/install.py` is covered by `tests/test_install.py`, including
project-local install and managed-install update behavior. The Node CLI remains
the interactive wizard and npm entry point.

## Coverage by trust dimension (journey order)

| Dimension | Automated signal | Strength |
|-----------|------------------|----------|
| **1. Install & update** | `install.test.mjs`, `test_install.py`, `test_check_update.py`, hook install/refresh tests | **Strong** for Node and Python local/update transactions |
| **1b. Core migration** | `test_migrate_core.py`, `test_core_hook_gate.py`, `test_core_hook_settings.py` | **Strong** for bundle capture, hook cutover receipts, and scoped bypass |
| **2. Invoke & route** | `test_detect_project.py`, `test_router_contract.py`, `test_pipeline_state.py`, `test_full_cycle.py`, `test_implicit_invocation.py` | **Partial** — classification, initialization, route, and transition decisions are deterministic; live host routing is covered only by dogfood |
| **3. Phase execution** | `test_full_cycle.py`, `test_handoffs.py`, `test_task_briefs.py` | **Strong** for the disk contract — phase outputs have executable gates |
| **4. Build orchestration** | `test_build_state.py`, `test_isolation.py`, `test_full_cycle.py` | **Partial** — readiness, recovery, and helper chain are proven; live child-agent dispatch is not automated |
| **5. Guards** | `test_guard_hook.py`, `test_git_guard.py`, hook installer tests | **Strong** |
| **6. Ship & archive** | `test_archive_milestone.py` | **Strong** |
| **7. Host dispatch** | Installer platform transforms; `test_sync_skill_resources` dispatch branches; `dogfood.py` | **Partial** — live top-level skill invocation proven for Claude; child spawn still manual evidence |
| **8. Docs fidelity** | Self-contained link checks in sync tests | **Partial** — no automated DOCS/README vs code audit |
| **9. Live dogfood** | `tests/dogfood.py` + `dogfood.yml`; evidence in `docs/trust-validation/evidence/` | **Partial** — Claude docs-audit + guards pass (2026-08-21); Codex wired, unrecorded; opt-in CI |

## What automation explicitly does NOT cover

- Full milestone run on any AI host (router → ship) — only the disk contract is automated (`test_full_cycle.py`)
- Live router execution of the deterministic recovery decisions
- Live orchestrator child-agent scheduling and parallel dispatch
- Live per-host runtime dispatch beyond recorded samples in the offline host tests
- Native guard wiring outside Claude, Codex, and Cursor
- Full live release receipts for every advertised host
- Networked `check_update` fetch (mocked in tests only)
- OpenCode v2, Kiro, Kimi implicit-invocation behavior (installer notes warnings; no tests)

## Installer targets exercised in tests

`install.test.mjs` / `test_install.py` exercise multi-target install including: codex, antigravity, and zed through one shared `.agents/skills` deployment; claude; cursor (+ subagent); grok; opencode; copilot; qwen; kiro; and kimi. Global vs `--local` project roots tested.
