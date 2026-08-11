# GSD Path — Automated Test & CI Inventory

**Generated:** 2026-08-05; **inventory updated 2026-08-11**
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
| `tests/test_handoffs.py` | unittest | `scripts/check_handoffs.py` — research handoff + patch-findings validation |
| `tests/test_task_briefs.py` | unittest | `scripts/check_task_briefs.py` — task-brief lint against the base tree |
| `tests/test_git_guard.py` | unittest | `scripts/git_guard.py` — violations matrix, pre-commit/commit-msg E2E |
| `tests/test_bootstrap_repository.py` | unittest | `scripts/bootstrap_repository.py` — new-GitHub journaled creation/resume |
| `tests/test_discussion_records.py` | unittest | `scripts/discussion_records.py` — discuss dialogue/answers records |
| `tests/test_check_update.py` | unittest | `scripts/check_update.py` — version compare, cache, notice |
| `tests/test_sync_skill_resources.py` | unittest | `scripts/sync_skill_resources.py` — generated resources, explicit-only links, dispatch branches |
| `tests/test_implicit_invocation.py` | unittest | Codex CLI — router absent from ordinary skill catalog (**skips if `codex` not on PATH**) |

**Note:** `scripts/install.py` is covered by `tests/test_install.py`. The
remaining parity gap is that `install.py` has no `--local` or
`--update` flags — those flows are Node-only.

## Coverage by trust dimension (journey order)

| Dimension | Automated signal | Strength |
|-----------|------------------|----------|
| **1. Install & update** | `install.test.mjs`, `test_install.py`, `test_check_update.py`, hook install/refresh tests | **Strong** for both installers; `--local`/`--update` flows remain Node-only |
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
- `scripts/install.py` parity for `--local` / `--update` (Node-only flags; the rest of `install.py` is covered by `test_install.py`)
- Non-Claude guard hook wiring (only Claude settings + git hooks tested via installer)
- Networked `check_update` fetch (mocked in tests only)
- OpenCode v2, Kiro, Kimi implicit-invocation behavior (installer notes warnings; no tests)

## Installer targets exercised in tests

`install.test.mjs` / `test_install.py` exercise multi-target install including: codex, zed (shared root), claude, cursor (+ subagent), grok, opencode, copilot, qwen, kiro, kimi. Antigravity shares codex/zed `.agents/skills` (skipped duplicate install). Global vs `--local` project roots tested.
