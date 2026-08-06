# GSD Path — Automated Test & CI Inventory

**Generated:** 2026-08-05 (wayfinder ticket: Inventory automated test and CI evidence)  
**Repo:** `open-gsd/gsd-path` @ local workspace  
**Runs:** `npm test` → 36 pass; `python3 -m unittest discover -s tests` → 107 pass

## CI

| Item | Status |
|------|--------|
| `.github/workflows/` | **Absent** — no GitHub Actions (or other) CI in repo |
| Pre-merge gate | **None in repo** — trust depends on local/ manual runs |

## How to run

```bash
npm test
python3 -m unittest discover -s tests -v
```

Node requires **≥18.17**. Python 3 with no extra deps for unittest modules.

## Suite inventory

| File | Runner | Tests | Primary subject |
|------|--------|-------|----------------|
| `tests/install.test.mjs` | `node --test` | 36 | `scripts/install.mjs` — paths, all targets, dry-run, rollback, `--local`, `--update`, hooks + refresh |
| `tests/test_install.py` | unittest | 35 | Parallel Python coverage of installer (subset of mjs; no `hooks_refresh_full` test) |
| `tests/test_archive_milestone.py` | unittest | 33 | `scripts/archive_milestone.py` — prepare, preflight, validate, ship commit, carry-forward |
| `tests/test_guard_hook.py` | unittest | 14 | `scripts/guard_hook.py` — archive deny, git commands, path normalization, subprocess E2E |
| `tests/test_git_guard.py` | unittest | 9 | `scripts/git_guard.py` — violations matrix, pre-commit/commit-msg E2E |
| `tests/test_handoffs.py` | unittest | 7 | `scripts/check_handoffs.py` — research handoff + patch-findings validation |
| `tests/test_check_update.py` | unittest | 5 | `scripts/check_update.py` — version compare, cache, notice |
| `tests/test_sync_skill_resources.py` | unittest | 3 | `scripts/sync_skill_resources.py` — generated resources, explicit-only links, dispatch branches |
| `tests/test_implicit_invocation.py` | unittest | 1 | Codex CLI — router absent from ordinary skill catalog (**skips if `codex` not on PATH**) |

**Note:** `scripts/install.py` has **no dedicated test module**; docs state Node installer is canonical for `--local` / `--update`.

## Coverage by trust dimension (journey order)

| Dimension | Automated signal | Strength |
|-----------|------------------|----------|
| **1. Install & update** | `install.test.mjs`, `test_install.py`, `test_check_update.py`, hook install/refresh tests | **Strong** for Node installer; Python installer untested |
| **2. Invoke & route** | `test_implicit_invocation.py` only (Codex-only, optional) | **Weak** — no STATE.md routing, recovery, or router contract tests |
| **3. Phase execution** | `test_handoffs.py` | **Partial** — handoff validator only, not full phase SOP |
| **4. Build orchestration** | — | **None** — no worktree / task isolation / wave tests |
| **5. Guards** | `test_guard_hook.py`, `test_git_guard.py`, hook installer tests | **Strong** |
| **6. Ship & archive** | `test_archive_milestone.py` | **Strong** |
| **7. Host dispatch** | Installer platform transforms; `test_sync_skill_resources` dispatch branches | **Partial** — no live subagent/Task spawn on any host |
| **8. Docs fidelity** | Self-contained link checks in sync tests | **Partial** — no automated DOCS/README vs code audit |
| **9. Live dogfood** | — | **None** |

## What automation explicitly does NOT cover

- Full milestone run on any AI host (router → ship)
- Router routing logic (`skills/gsd-path/SKILL.md` phase selection, `STATE.archive` recovery)
- Orchestrator build phase (worktrees, parallel coders, task commits)
- Per-host runtime dispatch (Cursor Task, Claude subagents, etc.) beyond install artifacts
- `scripts/install.py` behavior parity with Node
- Non-Claude guard hook wiring (only Claude settings + git hooks tested via installer)
- CI regression on push/PR
- Networked `check_update` fetch (mocked in tests only)
- OpenCode v2, Kiro, Kimi implicit-invocation behavior (installer notes warnings; no tests)

## Installer targets exercised in tests

`install.test.mjs` / `test_install.py` exercise multi-target install including: codex, zed (shared root), claude, cursor (+ subagent), grok, opencode, copilot, qwen, kiro, kimi. Antigravity shares codex/zed `.agents/skills` (skipped duplicate install). Global vs `--local` project roots tested.
