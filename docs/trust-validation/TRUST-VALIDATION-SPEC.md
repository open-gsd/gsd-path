# GSD Path — Trust Validation Spec (draft)

**Status:** Signed off (posture card accepted); **manual evidence recorded** 2026-08-05 — see `TRUST-EVIDENCE.md`  
**Generated:** 2026-08-05  
**Signed off:** 2026-08-05 — Jeremy McSpadden — as-is; proceed to manual evidence bar before trusting live pipeline  
**Scope:** Codex, Claude Code, Cursor ([host scope decision](https://github.com/open-gsd/gsd-path/issues/7))  
**Install path:** Clone + `node scripts/install.mjs` ([host scope decision](https://github.com/open-gsd/gsd-path/issues/7))

Supporting assets (local clone):

- `docs/trust-validation/automated-test-inventory.md`
- `docs/trust-validation/doc-vs-code-gaps.md`
- `docs/trust-validation/evidence-mapping.md`
- `docs/trust-validation/manual-dogfood-evidence-bar.md`

**Important:** Automated suites and **manual dogfood** (2026-08-05) are
recorded in `TRUST-EVIDENCE.md`. Build wave and full ship still not executed.
The 2026-08-05 dispatch-smoke runs were later reclassified as top-level CLI
checks, not child-spawn proof — see the 2026-08-11 reconciliation in
`TRUST-EVIDENCE.md`.

---

## 1. Per-dimension summary

| Dimension | Worst open gap | Severity | Posture today |
|-----------|----------------|----------|---------------|
| Install & update | `install.py` lacks `--local`/`--update`; npm unpublished | Medium | **Use with checks** |
| Invoke & route | No automated STATE/router/recovery tests | High | **Prove first** |
| Phase execution | Handoffs tested; full SOP not automated | High | **Prove first** |
| Build orchestration | No automated or manual proof in this effort | High | **Prove first** |
| Guards | Claude guards manually proven; Codex/Cursor pre-tool-use manual | Low | **OK to use** (Claude hooks); **Use with checks** (Codex/Cursor pre-tool-use) |
| Ship & archive | — | — | **OK to use** (validators) |
| Host dispatch | Child-agent spawn unverified — 2026-08-05 smoke runs exercised the top-level CLI only | High | **Prove first** |
| Docs fidelity | No automated docs claim audit | Medium | **Use with checks** |
| Live dogfood | Cursor slice done; build/ship not run | Medium | **Use with checks** |

---

## 2. Use posture card

### Rely now (automation-backed)

Use these **without** waiting on manual dogfood — still run `npm test` + Python unittest before upgrades:

- **Ship & archive validators** — `scripts/archive_milestone.py`, `git_guard.py` ship-commit rules
- **Guard script logic** — `guard_hook.py` / `git_guard.py` unit + subprocess tests
- **Node installer** — dry-run, apply, rollback, `--local`, `--update`, hooks install/refresh (`install.test.mjs` + `test_install.py`)
- **Handoff validator** — `scripts/check_handoffs.py` (research, plan coverage, wave/final SC verdicts, patch-findings)
- **Skill sync integrity** — `sync_skill_resources.py --check`
- **Static dispatch artifacts** — installer stages `platforms/*/dispatch.md` + Cursor `gsd-path` subagent file

### Prove first (before trusting end-to-end pipeline)

Complete manual bar (`docs/trust-validation/manual-dogfood-evidence-bar.md`) and attach evidence:

| Item | Hosts | Bar |
|------|-------|-----|
| Pipeline slice | **Cursor** | `/gsd-path` routes + one child spawn + handoff on disk |
| Dispatch smoke | **Codex, Claude** | One docs-audit spawn + `DOCS-AUDIT.md` |
| Router / STATE / recovery | **Cursor** (proxy for pipeline) | Covered by pipeline slice |
| Live child APIs | **Codex, Claude, Cursor** | Spawn success recorded per host |
| CI regression | — | GitHub Actions runs Node, Python, and resource-sync checks on pull requests |
| `npx gsd-path` | — | Wait for npm publish or record clone path only |
| **Build orchestration** | — | Optional follow-on: one task, one worktree, one orchestrator commit |

### Do not use (until fixed or proven)

Nothing is **Blocker**-grade on disk today if you:

- Use **clone + `install.mjs`**, not unpublished `npx`
- Do not rely on **`install.py`** for `--local` / `--update`
- Do not assume **parallel build / worktrees** work without dogfood
- Do not assume **dispatch** works until smoke tests pass

If manual guard deny tests **fail** on Claude after `--hooks`, treat **guards as do not use** until fixed.

### Your acceptance (optional)

Record explicit acceptance here if you rely on something despite a High gap:

| Gap accepted? | Rationale | Date |
|---------------|-----------|------|
| None | Sign-off accepts **posture labels**, not waiving High gaps — manual bar still required for prove-first items | 2026-08-05 |

---

## 3. Gap register (sorted by severity)

| Sev | ID | Gap | Evidence | Fix / proof direction |
|-----|-----|-----|----------|----------------------|
| **High** | G2 | Router/STATE/recovery untested | No test files | Cursor pipeline slice + future router tests |
| **High** | G3 | Full phase SOP untested | Only `test_handoffs.py` | Pipeline slice + phase dogfood |
| **High** | G4 | Build orchestration unproven | No tests; deferred from bar | One-task build wave dogfood |
| **High** | G5 | Live dispatch unproven (Codex, Claude, Cursor) | Static install only | Docs-audit spawn per host |
| **High** | G6 | Live dogfood not recorded | Checklist only | Run manual bar |
| **Medium** | G7 | `install.py` ≠ Node `--local`/`--update` | `install.py --help` | Use Node for project installs |
| **Medium** | G8 | npm package unpublished (404) | registry check | Publish or document clone-only |
| **Medium** | G9 | `npm test` omits Python suite | `package.json` scripts | Run both suites manually |
| **Medium** | G10 | Codex/Cursor pre-tool-use not auto-installed | HOOKS.md | Wire manually or accept git-hook-only |
| **Medium** | G11 | No automated doc-audit runner in CI | doc gaps catalog | Onboard/docs-audit or CI step |
| **Info** | G13 | Onboard DOCS-AUDIT remediation queue stale | `.project/research/DOCS-AUDIT.md` | Refresh on next onboard |

---

## 4. Evidence table (condensed)

Full automation map: `docs/trust-validation/evidence-mapping.md`

| Criterion | Dimension | Status | Posture |
|-----------|-----------|--------|---------|
| Node installer core paths | Install & update | met | OK |
| `install.py` parity | Install & update | partial (tested; no `--local`/`--update`) | Use with checks |
| npm publish | Install & update | unmet | Prove first |
| CI gate | Install & update | met | OK |
| Explicit-only skill links | Invoke & route | met | OK |
| STATE/router/recovery | Invoke & route | unmet | Prove first |
| Codex implicit catalog | Invoke & route | partial | Prove first |
| `check_handoffs.py` | Phase execution | met | OK |
| Full WORKFLOW execution | Phase execution | unmet | Prove first |
| Worktrees / parallel build | Build orchestration | unmet | Prove first |
| Guard scripts + git_guard | Guards | met | OK |
| Claude hook wiring (installer) | Guards | met | OK |
| Codex/Cursor pre-tool-use auto | Guards | partial | Use with checks |
| `archive_milestone.py` suite | Ship & archive | met | OK |
| Dispatch files on install | Host dispatch | met (static) | OK |
| Live spawn Codex/Claude/Cursor | Host dispatch | unverifiable | Prove first |
| Resource synchronization | Docs fidelity | met | OK |
| Cursor pipeline slice | Live dogfood | unverifiable | Prove first |
| Codex/Claude dispatch smoke | Live dogfood | unverifiable | Prove first |

---

## 5. What this spec does not claim

- Trust for Zed, Grok, OpenCode, Copilot, Qwen, Antigravity, Kiro, Kimi (out of scope)
- Full milestone-to-ship without running review/archive dogfood
- That manual checklist items passed — **run the bar and link evidence**
- Engineering fixes from the gap register (separate effort)

---

## 6. Recommended next actions (after spec sign-off)

1. Run manual dogfood bar; paste evidence into a `TRUST-EVIDENCE.md` or issue comment.
2. Re-run `npm test` && `python3 -m unittest discover -s tests` after any `git pull`.
3. Before relying on **build**: one trivial task through `gsd-path-build`.
4. Optional engineering: npm publish and the `install.py` parity decision.

---

## Workstream tracking

All planning tickets closed. Tracking issue: [Trust validation for GSD Path skill set](https://github.com/open-gsd/gsd-path/issues/3).
