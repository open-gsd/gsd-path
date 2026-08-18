# GSD Path — Automated Evidence × Trust Criteria Map

**Generated:** 2026-08-05 (wayfinder: Map automated evidence to trust criteria)  
**Schema:** [Define trust criteria dimensions and severity rubric](https://github.com/open-gsd/gsd-path/issues/4)  
**Inputs:** test inventory (#5), doc gaps (#6), host scope (#7 — Codex, Claude, Cursor in scope)

**Automation only** — live dogfood rows are `unverifiable` here; manual bar is ticket #9.

## Per-dimension summary (automation signal)

| Dimension | Criteria with automation | Worst gap | Draft posture |
|-----------|--------------------------|-----------|---------------|
| 1 Install & update | 9 met, 1 partial, 1 unmet | `install.py` lacks `--local`/`--update`; npm unpublished | **Use with checks** |
| 2 Invoke & route | 1 partial, 4 unmet | No STATE/router/recovery tests | **Prove first** |
| 3 Phase execution | 2 met, 2 unmet | Handoffs only; no full phase SOP tests | **Prove first** |
| 4 Build orchestration | 0 met, 3 unmet | No worktree/wave tests | **Prove first** |
| 5 Guards | 6 met, 2 partial | Codex/Cursor pre-tool-use not auto-installed | **Use with checks** (Claude **OK** via tests) |
| 6 Ship & archive | 5 met | — | **OK to use** (automation) |
| 7 Host dispatch | 4 met static, 3 unverifiable live | Live spawn on Codex/Claude/Cursor | **Prove first** |
| 8 Docs fidelity | 4 met, 1 partial | No automated doc audit runner | **Use with checks** |
| 9 Live dogfood | 0 met | No automation | **Prove first** (manual #9) |

## Evidence table (automated criteria)

| Criterion | Dimension | Evidence | Status | Severity | Posture |
|-----------|-----------|----------|--------|----------|---------|
| `install.mjs` dry-run makes no writes | Install & update | `tests/install.test.mjs` | met | — | OK |
| Multi-target install + rollback on failure | Install & update | `install.test.mjs`, `test_install.py` | met | — | OK |
| `--local` project install for codex/claude/cursor | Install & update | `install.test.mjs` (all targets) | met | — | OK |
| `--update` refreshes detected local installs | Install & update | `install.test.mjs` | met | — | OK |
| Stale `sync --check` blocks install | Install & update | `install.test.mjs`, `test_install.py` | met | — | OK |
| Hooks install (scripts, Claude settings, git hooks) | Install & update | `install.test.mjs`, `test_install.py` | met | — | OK |
| Hooks refresh paths | Install & update | `install.test.mjs` | met | — | OK |
| `check_update.py` version compare + cache | Install & update | `test_check_update.py` | met | — | OK |
| `scripts/install.py` matches Node `--local`/`--update` | Install & update | `tests/test_install.py`; `install.py --help` has no `--local`/`--update` | partial | Medium | Use with checks |
| `npx gsd-path` published on npm | Install & update | registry 404 | unmet | Medium | Prove first |
| CI runs test suites on push/PR | Install & update | `.github/workflows/ci.yml` | met | — | OK |
| Codex router absent from ordinary catalog | Invoke & route | `test_implicit_invocation.py` (skips w/o CLI) | partial | High | Prove first |
| Router reads `STATE.md` v1 and routes phases | Invoke & route | none | unmet | High | Prove first |
| `STATE.archive` recovery + validate | Invoke & route | none | unmet | High | Prove first |
| Explicit-only router description in skills | Invoke & route | `test_sync_skill_resources.py` | met | — | OK |
| Research handoff validates dispatch + dimensions | Phase execution | `test_handoffs.py` | met | — | OK |
| Patch-findings validates sources + reviewed head | Phase execution | `test_handoffs.py` | met | — | OK |
| Full WORKFLOW phase contracts executable | Phase execution | none | unmet | High | Prove first |
| Orchestrator worktree isolation per task | Build orchestration | none | unmet | High | Prove first |
| Parallel wave / serial task landing commits | Build orchestration | none | unmet | High | Prove first |
| Coder does not commit (contract) | Build orchestration | none (static docs only) | unmet | Medium | Prove first |
| `guard_hook.py` denies archive paths (path-first) | Guards | `test_guard_hook.py` | met | — | OK |
| `guard_hook.py` denies destructive git + cp/tee/checkout | Guards | `test_guard_hook.py` | met | — | OK |
| `git_guard.py` blocks archive tamper + ship purity | Guards | `test_git_guard.py` | met | — | OK |
| pre-commit / commit-msg E2E | Guards | `test_git_guard.py` | met | — | OK |
| Installer deploys Claude PreToolUse wiring | Guards | `install.test.mjs` | met | — | OK (Claude) |
| HOOKS.md matches guard script behavior | Guards | code read + tests | met | — | OK |
| Codex/Cursor pre-tool-use auto-installed | Guards | HOOKS.md; installer tests | partial | Medium | Use with checks |
| `archive_milestone.py` prepare/preflight/validate | Ship & archive | `test_archive_milestone.py` | met | — | OK |
| Ship commit `.project/` only + case-insensitive `ship:` | Ship & archive | `test_git_guard.py`, archive tests | met | — | OK |
| Carry-forward + manifest integrity | Ship & archive | `test_archive_milestone.py` | met | — | OK |
| Install stages `platforms/*/dispatch.md` for in-scope hosts | Host dispatch | installer tests | met | — | OK |
| Cursor `gsd-path` subagent file installed | Host dispatch | `install.test.mjs` | met | — | OK |
| Shared dispatch runtime branches unambiguous | Host dispatch | `test_sync_skill_resources.py` | met | — | OK |
| Live Codex collaboration child spawn | Host dispatch | none (static only) | unverifiable | High | Prove first |
| Live Claude `Agent` child spawn | Host dispatch | none | unverifiable | High | Prove first |
| Live Cursor `Task` + gsd-path subagent | Host dispatch | none | unverifiable | High | Prove first |
| `sync --check` keeps declared resources byte-identical | Docs fidelity | command + `test_sync_skill_resources.py` | met | — | OK |
| Phase skills self-contained links (explicit-only) | Docs fidelity | `test_sync_skill_resources.py` | met | — | OK |
| Automated DOCS/README claim audit | Docs fidelity | none in CI | unmet | Medium | Use with checks |
| FULL child-agent API table vs install table (Kimi row) | Docs fidelity | FULL.md | met | — | OK |
| Full milestone on Cursor | Live dogfood | none | unverifiable | High | Prove first |
| Dispatch smoke Codex + Claude | Live dogfood | none | unverifiable | High | Prove first |

## What automation alone cannot close

These require [**Define manual and dogfood evidence bar**](https://github.com/open-gsd/gsd-path/issues/9) + live runs:

- Cursor milestone dogfood depth
- Codex/Claude/Cursor dispatch smoke outcomes
- Codex implicit invocation when CLI absent in CI
- Codex/Cursor guard pre-tool-use if you wire hooks manually

## Rows ready for “Rely now” (automation only, in-scope hosts)

- Node installer dry-run/apply/rollback/update/hooks refresh
- Guard scripts + git hooks logic (Claude wiring via installer)
- Archive milestone validators
- Handoff validators (`check_handoffs.py`)
- Skill resource sync integrity
- Static dispatch artifacts + Cursor subagent file on install
