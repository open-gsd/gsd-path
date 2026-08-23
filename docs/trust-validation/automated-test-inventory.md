# GSD Path — Automated Test & CI Inventory

**Generated:** 2026-08-05; **inventory updated 2026-08-23**
**Repo:** `open-gsd/gsd-path` @ local workspace
**Complete local gate:** `npm run verify`

## CI

| Item | Status |
|------|--------|
| `.github/workflows/ci.yml` | **Present** — runs Node and Python suites plus resource synchronization on pushes and pull requests |
| Pre-merge gate | **Configured in repo** through GitHub Actions |

## How to run

```bash
npm run verify
```

This runs the Node tests, all Python unittest modules, and the generated-resource
sync check. Node requires **≥18.17**. The Python suite has no third-party runtime
dependency.

## Suite inventory

| File | Runner | Primary subject |
|------|--------|----------------|
| `tests/install.test.mjs` | `node --test` | `scripts/install.mjs` — paths, all targets, dry-run, rollback, `--local`, `--update`, hooks + refresh |
| `tests/package.test.mjs` | `node --test` | npm package manifest / packaging checks |
| `tests/wizard.test.mjs` | `node --test` | `scripts/wizard.mjs` — interactive installer arguments from a fake key stream |
| `tests/test_install.py` | unittest | `scripts/install.py` — Python installer (global install, dry-run, rollback, hooks) |
| `tests/test_archive_milestone.py` | unittest | `scripts/archive_milestone.py` — prepare, derived manifest, validation, ship commit, resumable integration, carry-forward |
| `tests/test_bootstrap_repository.py` | unittest | `scripts/bootstrap_repository.py` — journaled creation/resume and unjournaled collision refusal |
| `tests/test_build_state.py` | unittest | `scripts/build_state.py` — dependency-ready task selection and landed-task reconciliation |
| `tests/test_check_docs_audit.py` | unittest | `scripts/check_docs_audit.py` — tracked/untracked Markdown inventory and docs-audit artifact gate |
| `tests/test_detect_project.py` | unittest | `scripts/detect_project.py` — owned/orphan/brownfield/greenfield classification and initialization; `scripts/promote_lookahead.py` — promotion and recovery |
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
| `tests/test_pipeline_git.py` | unittest | `scripts/pipeline_git.py` — canonical subjects, initial/next branch binding, and mutation refusal |
| `tests/test_pipeline_state.py` | unittest | `scripts/pipeline_state.py` — state validation, route decisions, transitions, and lookahead promotion recovery |
| `tests/test_review_panel.py` | unittest | `scripts/review_panel.py` — canonical panel resolution, validation, and merge parsing |
| `tests/test_router_contract.py` | unittest | executable route phase matrix, bundled phase contracts, and STATE template compatibility |
| `tests/test_sync_skill_resources.py` | unittest | generated resources, manifest-owned links, and dispatch branches |
| `tests/test_task_briefs.py` | unittest | task frontmatter, recorded bases, ownership, commit evidence, and verify scope |
| `tests/test_wizard_tty.py` | unittest | no-flag CLI opens the wizard on a real PTY and hands off to the installer |
| `tests/dogfood.py` | script (`--host claude\|codex`) | **Live** host run: local install, headless `/gsd-path-docs-audit`, `check_docs_audit.py` gate, guard deny/allow; writes an evidence record. `.github/workflows/dogfood.yml` runs it on dispatch/weekly with API secrets |

**Note:** `scripts/install.py` is covered by `tests/test_install.py`. The
remaining parity gap is that `install.py` has no `--local` or
`--update` flags — those flows are Node-only.

## Coverage by trust dimension (journey order)

| Dimension | Automated signal | Strength |
|-----------|------------------|----------|
| **1. Install & update** | `install.test.mjs`, `test_install.py`, `test_check_update.py`, hook install/refresh tests | **Strong** for both installers; `--local`/`--update` flows remain Node-only |
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
- Per-host runtime dispatch (Cursor Task, Claude subagents, etc.) beyond install artifacts
- `scripts/install.py` parity for `--local` / `--update` (Node-only flags; the rest of `install.py` is covered by `test_install.py`)
- Non-Claude guard hook wiring (only Claude settings + git hooks tested via installer)
- Networked `check_update` fetch (mocked in tests only)
- OpenCode v2, Kiro, Kimi implicit-invocation behavior (installer notes warnings; no tests)

## Installer targets exercised in tests

`install.test.mjs` / `test_install.py` exercise multi-target install including: codex, zed (shared root), claude, cursor (+ subagent), grok, opencode, copilot, qwen, kiro, kimi. Antigravity shares codex/zed `.agents/skills` (skipped duplicate install). Global vs `--local` project roots tested.
