# GSD Path — Documentation vs Code Gap Catalog

**Generated:** 2026-08-05 (wayfinder: Catalog documentation vs code gaps)  
**Primary sources:** live repo read + commands; reconciled with `.project/research/DOCS-AUDIT.md` (2026-08-02) and `evidence-codebase.md`.

## Executive summary

| Category | Count | Trust impact |
|----------|-------|----------------|
| **Stale doc** (wording drift, fix-doc) | 2 active | Low–Medium |
| **Code–doc mismatch** (behavior differs) | 4 | Medium–High |
| **Aspirational** (not yet true) | 1 | Medium |
| **Unverifiable** (needs live host) | 10 | High for host dispatch |
| **Resolved since Aug 02 audit** | 5 | — |

The pipeline **skill contracts and sync manifest** align with code (82 resource pairs pass `--check`). Worst trust gaps are **live host adapter proof**, **no CI**, and **Node vs Python installer split**.

## Commands run (2026-08-05; counts updated 2026-08-11)

| Command | Result |
|---------|--------|
| `python3 scripts/sync_skill_resources.py --check` | exit 0, `{"resources": 82}` |
| `GET https://registry.npmjs.org/gsd-path` | HTTP **404** (not published) |
| `npm test` + `python3 -m unittest discover -s tests` | 53 + 178 tests (see test inventory) |

## Resolved since DOCS-AUDIT (2026-08-02)

| Prior remediation # | Item | Status |
|---------------------|------|--------|
| 1 | GUIDE.md Start invocation list omitted Kimi | **Resolved** — `GUIDE.md` is now a pointer hub only |
| 2 | README opening supported-hosts omitted Kimi | **Fixed** — README.md:8-9 lists Kimi Code |
| 3 | README "six gated phases" | **Fixed** — README uses Phase 0–6 flow diagram |
| 7 | WORKFLOW "six gated phases" | **Fixed** — WORKFLOW.md opens with "gated pipeline" + Phase 0–7 sections |
| — | `package.json files` omitted README/DOCS | **Fixed** — README, DOCS, QUICK, FULL, UPDATE, HOOKS now in `files` |

## Active stale / doc drift (fix-doc)

| # | Location | Claim / gap | Evidence | Suggested severity |
|---|----------|-------------|----------|-------------------|
| D1 | README.md Agent execution table | Kimi dispatch documented in install table (`--kimi`) but **missing from Child-agent API table** (rows end at Kiro) | README.md:117-128 vs 140-151; `platforms/kimi/dispatch.md` specifies `Agent` + `coder` | **Low** (fix-doc) |
| D2 | DOCS-AUDIT.md remediation queue | Rows 1–7 still list Kimi/six-phase drift as open | Stale relative to current README/WORKFLOW; audit artifact not refreshed | **Informational** (meta) |

## Code–doc mismatches (behavior)

| # | Topic | Docs say | Code does | Evidence | Suggested severity |
|---|-------|----------|-----------|----------|-------------------|
| C1 | **Installer parity** | DOCS/README: Python installer mirrors global install; Node has `--local`/`--update` | `install.py` has no `--local` or `--update`; project skill roots are Node-only | `install.mjs --help` vs `install.py --help`; evidence-codebase.md Finding | **Medium** — use with checks |
| C2 | **npm package contents** | `npx gsd-path` as install path in README/DOCS | `package.json files` omits `scripts/install.py`, `LICENSE`; bin is Node only | package.json:10-28 | **Medium** |
| C3 | **npm publication** | README/UPDATE imply `npx gsd-path` / registry update | Package not on npm (404) | registry HTTP 404; DOCS-AUDIT aspirational | **Medium** — prove first for npx path |
| C4 | **Test surface in package.json** | Implied "run tests" for quality | `"test"` script runs **only** `tests/*.test.mjs`; Python suite separate | package.json:33-35; 178 Python tests not in npm script | **Medium** |
| C5 | **CI** | None claimed | No `.github/` workflows | no CI directory | **High** for regression trust |
| C6 | **Guard hooks on non-Claude hosts** | HOOKS.md: only Claude auto-wired; manual for others | Installer tests cover Claude settings + git hooks; no auto Codex/Cursor hook install | HOOKS.md:72-86; install tests | **High** if relying on guards off-Claude |

## Aspirational

| # | Claim | Evidence |
|---|-------|----------|
| A1 | `npx gsd-path@latest --update` fetches published package | npm registry 404; `check_update.py` handles unpublished silently |

## Unverifiable — NEEDS-USER / live host (10)

Static dispatch contracts are **verified** (files exist, installer copies them). **Live child-agent API** is unverifiable without a session on each host:

| Host | Dispatch file | Live claim | Evidence |
|------|---------------|------------|----------|
| Antigravity | `platforms/antigravity/dispatch.md` | `invoke_subagent` works at runtime | DOCS-AUDIT unverifiable |
| Claude | `platforms/claude/dispatch.md` | `Agent` tool/schema | same |
| Codex | `platforms/shared-agents/dispatch.md` (Codex installs the shared-agents profile) | collaboration worker | same; implicit test only when `codex` CLI present |
| Copilot | `platforms/copilot/dispatch.md` | `task` tool | same |
| Grok | `platforms/grok/dispatch.md` | `spawn_subagent` | same |
| Kimi | `platforms/kimi/dispatch.md` | `Agent` + `coder` | same |
| Kiro | `platforms/kiro/dispatch.md` | subagent facility | same |
| OpenCode | `platforms/opencode/dispatch.md` | Task / v2 subagent | same |
| Qwen | `platforms/qwen/dispatch.md` | `agent` tool | same |
| Zed | `platforms/shared-agents/dispatch.md` (Zed installs the shared-agents profile) | `spawn_agent` | same |
| Cursor | `platforms/cursor/dispatch.md` | Task + `gsd-path` subagent | same + installer copies `platforms/cursor/agent.md` |

**Suggested severity:** **High** per host you actually use until dogfood confirms spawn works.

## Verified alignments (high confidence)

- Eleven `gsd-path*` skills; phase contracts byte-synced (`sync --check` → 82 resources).
- `HOOKS.md` matches `guard_hook.py` / `git_guard.py` (archive path-first, cp/tee/checkout, case-insensitive `ship:`).
- `WORKFLOW.md` phase SOP matches skill contracts (handoffs, archive script, explicit-only router).
- Multi-host install targets in code match README install table (11 targets + shared codex/zed profile).
- Brownfield onboard artifacts (`DOCS-AUDIT.md`, `evidence-codebase.md`) are **pipeline outputs**, not user docs — counts in Aug 02 audit are historical snapshots.

## Not doc gaps (out of catalog scope)

- Router phase routing logic — no doc contradiction; **no automated proof** (see test inventory).
- Full milestone dogfood — process gap, not doc-vs-code.
