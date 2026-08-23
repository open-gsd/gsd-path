# GSD Path — Automated Test & CI Inventory

**Generated:** 2026-08-05; **inventory updated 2026-08-23**
**Repo:** `open-gsd/gsd-path` @ local workspace
**Suites:** `npm test`; `python3 -m unittest discover -s tests`

## CI

| Item | Status |
|------|--------|
| `.github/workflows/ci.yml` | **Present** — runs Node and Python suites plus resource synchronization on pushes and pull requests |
| Pre-merge gate | **Configured in repo** through GitHub Actions |

## How to run

```bash
npm test
python3 -m unittest discover -s tests -v
```

Node requires **≥18.17**. Python 3 with no extra deps for unittest modules.

## Suite inventory

| File | Runner | Primary subject |
|------|--------|----------------|
| `tests/install.test.mjs` | `node --test` | `scripts/install.mjs` — paths, all targets, dry-run, rollback, `--local`, `--update`, hooks + refresh |
| `tests/package.test.mjs` | `node --test` | npm package manifest / packaging checks |
| `tests/test_install.py` | unittest | `scripts/install.py` — Python installer (global install, dry-run, rollback, hooks) |
| `tests/test_archive_milestone.py` | unittest | `scripts/archive_milestone.py` — prepare, preflight, validate, ship commit, carry-forward |
| `tests/test_guard_hook.py` | unittest | `scripts/guard_hook.py` — archive deny, git commands, path normalization, subprocess E2E |
| `tests/test_handoffs.py` | unittest | `scripts/check_handoffs.py` — research, plan Intent coverage, wave/final SC verdicts, and patch-findings |
| `tests/test_isolation.py` | unittest | `scripts/isolation.py` — named task/verify checkouts, serial vs parallel landing, retire |
| `tests/test_git_guard.py` | unittest | `scripts/git_guard.py` — violations matrix, pre-commit/commit-msg E2E |
| `tests/test_bootstrap_repository.py` | unittest | `scripts/bootstrap_repository.py` — new-GitHub journaled creation/resume |
| `tests/test_detect_project.py` | unittest | `scripts/detect_project.py` — owned/orphan/brownfield/greenfield classify; `scripts/promote_lookahead.py` — promotion and recovery |
| `tests/test_discussion_records.py` | unittest | `scripts/discussion_records.py` — discuss dialogue/answers records |
| `tests/test_check_update.py` | unittest | `scripts/check_update.py` — version compare, cache, notice |
| `tests/test_sync_skill_resources.py` | unittest | `scripts/sync_skill_resources.py` — generated resources, explicit-only links, dispatch branches |
| `tests/test_implicit_invocation.py` | unittest | Codex CLI — router absent from ordinary skill catalog (**skips if `codex` not on PATH**) |
| `tests/wizard.test.mjs` | `node --test` | `scripts/wizard.mjs` — interactive installer flow driven by a fake key stream → argv |
| `tests/test_wizard_tty.py` | unittest | `gsd-path` with no flags on a real pty opens the wizard and hands off to the installer (dry run, quit) |
| `tests/test_router_contract.py` | unittest | `skills/gsd-path/SKILL.md` state table — every phase routed in-progress and done, every contract file exists, STATE template tokens match |
| `tests/test_check_docs_audit.py` | unittest | `scripts/check_docs_audit.py` — docs-audit artifact gate (inventory equality, verdicts + evidence, summary counts, remediation queue) |
| `tests/test_full_cycle.py` | unittest | One milestone define → research → decide → plan → build → ship → integrate → bind-next on disk, every gate script and git hook run in order |
| `tests/dogfood.py` | script (`--host claude\|codex`) | **Live** host run: local install, headless `/gsd-path-docs-audit`, `check_docs_audit.py` gate, guard deny/allow; writes an evidence record. `.github/workflows/dogfood.yml` runs it on dispatch/weekly with API secrets |

**Note:** `scripts/install.py` is covered by `tests/test_install.py`. The
remaining parity gap is that `install.py` has no `--local` or
`--update` flags — those flows are Node-only.

## Coverage by trust dimension (journey order)

| Dimension | Automated signal | Strength |
|-----------|------------------|----------|
| **1. Install & update** | `install.test.mjs`, `test_install.py`, `test_check_update.py`, hook install/refresh tests | **Strong** for both installers; `--local`/`--update` flows remain Node-only |
| **2. Invoke & route** | `test_detect_project.py`, `test_router_contract.py`, `test_full_cycle.py` (STATE transitions), `test_implicit_invocation.py` | **Partial** — classification, state table, and transitions proven; live routing by a host only via dogfood |
| **3. Phase execution** | `test_full_cycle.py`, `test_handoffs.py`, `test_task_briefs.py` | **Strong** for the disk contract — every phase's output passes the next phase's gate |
| **4. Build orchestration** | `test_isolation.py`, `test_full_cycle.py` (isolate → land → verify → review) | **Partial** — helper chain proven; no live wave scheduling |
| **5. Guards** | `test_guard_hook.py`, `test_git_guard.py`, hook installer tests | **Strong** |
| **6. Ship & archive** | `test_archive_milestone.py` | **Strong** |
| **7. Host dispatch** | Installer platform transforms; `test_sync_skill_resources` dispatch branches; `dogfood.py` | **Partial** — live top-level skill invocation proven for Claude; child spawn still manual evidence |
| **8. Docs fidelity** | Self-contained link checks in sync tests | **Partial** — no automated DOCS/README vs code audit |
| **9. Live dogfood** | `tests/dogfood.py` + `dogfood.yml`; evidence in `docs/trust-validation/evidence/` | **Partial** — Claude docs-audit + guards pass (2026-08-21); Codex wired, unrecorded; opt-in CI |

## What automation explicitly does NOT cover

- Full milestone run on any AI host (router → ship) — only the disk contract is automated (`test_full_cycle.py`)
- Router archive/branch recovery branches (`STATE.archive` paths) beyond the state table
- Orchestrator build phase (wave scheduling, parallel coder dispatch)
- Per-host runtime dispatch (Cursor Task, Claude subagents, etc.) beyond install artifacts
- `scripts/install.py` parity for `--local` / `--update` (Node-only flags; the rest of `install.py` is covered by `test_install.py`)
- Non-Claude guard hook wiring (only Claude settings + git hooks tested via installer)
- Networked `check_update` fetch (mocked in tests only)
- OpenCode v2, Kiro, Kimi implicit-invocation behavior (installer notes warnings; no tests)

## Installer targets exercised in tests

`install.test.mjs` / `test_install.py` exercise multi-target install including: codex, zed (shared root), claude, cursor (+ subagent), grok, opencode, copilot, qwen, kiro, kimi. Antigravity shares codex/zed `.agents/skills` (skipped duplicate install). Global vs `--local` project roots tested.
