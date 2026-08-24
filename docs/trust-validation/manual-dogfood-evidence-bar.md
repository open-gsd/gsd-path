# GSD Path — Manual & Dogfood Evidence Bar

**Generated:** 2026-08-05 (workstream: Define manual and dogfood evidence bar)
**Hosts in scope:** Codex, Claude, Cursor ([#7](https://github.com/open-gsd/gsd-path/issues/7))

## Evidence recording rule

Every manual run records: **date, host, commands invoked, pass/fail, artifact paths, spawn API/tool used, and command output or screenshot path**. No assertion without artifact.

---

## Cursor — pipeline slice (full dogfood)

**Install:**

```bash
node scripts/install.mjs --cursor --project /path/to/test-repo --hooks
```

**Required steps:**

1. Explicit `/gsd-path` — router reads/creates `STATE.md` with `pipeline: gsd-path/v2` and routes to a valid phase.
2. **One successful child spawn** — e.g. `/gsd-path-docs-audit` or brownfield onboard read-only child.
3. **Valid handoff on disk** — phase output matches template (e.g. `.project/research/DOCS-AUDIT.md` or `.project/intent/INTENT.md`).
4. Record spawn tool (`Task` + `gsd-path` subagent), paths, verdict.

**Not required for spec closure:** full ship/archive, multi-wave build, review cycles.

---

## Codex — dispatch smoke

```bash
node scripts/install.mjs --codex --project /path/to/test-repo
```

1. Invoke `$gsd-path-docs-audit` (or router → docs audit).
2. Child completes; `.project/research/DOCS-AUDIT.md` exists with verdict table.
3. Record collaboration spawn API, pass/fail.

**Optional:** if `codex` CLI on PATH, confirm router absent from ordinary skill catalog on generic prompt (mirrors `test_implicit_invocation.py`).

---

## Claude — dispatch smoke + guards

```bash
node scripts/install.mjs --claude --project /path/to/test-repo --hooks
```

**Dispatch (same as Codex):**

1. `/gsd-path-docs-audit` → `DOCS-AUDIT.md` on disk.
2. Record `Agent` spawn, pass/fail.

**Guards (required for Claude “proved” posture):**

| Check | Pass |
|-------|------|
| Files exist | `.gsd-path/guard_hook.py`, `.gsd-path/git_guard.py`, `.claude/settings.json`, git hooks |
| Deny | Write to `.project/archive/…` blocked (guard hook or pre-commit) |
| Allow | Read archive OR commit outside archive succeeds |

---

## Codex + Cursor — git hook bar

Without requiring pre-tool-use wiring:

1. Stage modification inside `.project/archive/<existing>/`.
2. `git commit` → **pre-commit** blocks.

If `guard_hook.py` manually wired: one archive-path deny test counts as bonus evidence.

---

## Explicitly deferred (prove-first in spec, not this bar)

| Area | Posture |
|------|---------|
| **Build orchestration** | Prove first — optional follow-on: one task, one worktree, one orchestrator commit |
| **Full milestone to ship** | Not required for trust spec closure |
| **CI regression** | Covered separately by `.github/workflows/ci.yml` |
| **Out-of-scope hosts** | No manual runs |

## Fail criteria

- Dispatch contract failure / child not found → host **not trusted** for dispatch until fixed.
- Spawn succeeds but artifact missing or empty verdict table → **partial**, not trusted.
- Claude hooks missing or deny test passes when it should fail → guards **not proved**.
