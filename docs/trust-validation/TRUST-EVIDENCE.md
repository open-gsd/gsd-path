# GSD Path — Trust Evidence Log

**Date:** 2026-08-05 (reconciled 2026-08-11 — dispatch-smoke rows downgraded; see notes)  
**Executor:** Cursor agent session (automated + CLI where noted)  
**Test repo:** `/tmp/gsd-trust-evidence-25642`  
**Source repo:** `/Users/jeremymcspadden/github/open-gsd/gsd-path`

---

## 1. Install (Codex, Claude, Cursor)

**Command** (from test repo cwd):

```bash
cd /tmp/gsd-trust-evidence-25642
node /Users/jeremymcspadden/github/open-gsd/gsd-path/scripts/install.mjs \
  --codex --claude --cursor --local --project "$(pwd)" --hooks
```

**Result:** PASS

- codex → `.agents/skills` (9 skills at the time of this run)
- claude → `.claude/skills` (9 skills at the time of this run)
- cursor → `.cursor/skills` + `.cursor/agents/gsd-path.md`
- project → `AGENTS.md`, `WORKFLOW.md`, `.claude/CLAUDE.md`, `.gsd-path/*`, Claude settings, git hooks

**Note:** `--local` requires cwd = project root; `--project` path alone does not relocate local skill roots.

---

## 2. Claude guards (deny / allow)

**Files present:** `.gsd-path/guard_hook.py`, `.gsd-path/git_guard.py`, `.claude/settings.json`, `.git/hooks/pre-commit`, `.git/hooks/commit-msg`

### Deny — `guard_hook.py` (stdin)

```bash
echo '{"tool_name":"Edit","tool_input":{"file_path":".project/archive/001-test/MANIFEST.md","content":"bad"}}' \
  | python3 .gsd-path/guard_hook.py
```

**Result:** PASS — exit code 2, JSON `permissionDecision: deny`

### Deny — pre-commit archive tamper

Staged modification to committed `.project/archive/001-test/MANIFEST.md`

**Result:** PASS — `gsd-path guard blocked the commit: committed archives are read-only`

### Allow — commit outside archive

```bash
git commit -m "chore: outside archive"  # notes.txt only
```

**Result:** PASS — commit `d126508` succeeded

---

## 3. Codex — implicit invocation

```bash
cd /Users/jeremymcspadden/github/open-gsd/gsd-path
python3 -m unittest tests.test_implicit_invocation.ImplicitInvocationTests.test_router_is_absent_from_ordinary_codex_skill_catalog -v
```

**Result:** PASS — ok in 2.6s

---

## 4. Dispatch smoke — Codex

```bash
cd /tmp/gsd-trust-evidence-25642
codex exec --skip-git-repo-check \
  "Write .../DOCS-AUDIT-codex.md minimal audit of README.md ..."
```

**Result:** UNVERIFIABLE (downgraded 2026-08-11; originally recorded PASS) —
the command exercised the top-level `codex exec` CLI, not a child-agent spawn
through the dispatch contract, so it does not evidence child dispatch.  
**Artifact:** `.project/research/DOCS-AUDIT-codex.md` (verdict table, aspirational claim on missing install.mjs)  
**Spawn API:** Codex `exec` non-interactive (top-level CLI, no child spawn)

---

## 5. Dispatch smoke — Claude Code

```bash
cd /tmp/gsd-trust-evidence-25642
claude -p --dangerously-skip-permissions \
  "Write .../DOCS-AUDIT-claude.md ..."
```

**Result:** UNVERIFIABLE (downgraded 2026-08-11; originally recorded PASS) —
the command exercised the top-level `claude -p` CLI, not the `Agent` tool
child spawn the dispatch contract requires, so it does not evidence child
dispatch.  
**Artifact:** `.project/research/DOCS-AUDIT-claude.md` (verdict summary, unverifiable under README-only scope)  
**Spawn API:** Claude Code `-p` (print mode; top-level CLI, no child spawn)

---

## 6. Cursor — pipeline slice

### 6a Router read (STATE → next action)

**STATE:** `phase: grill`, `status: done`, `pipeline: gsd-path/v1` (pipeline id at the time of this run; current pipeline is `gsd-path/v2` and the `grill` phase no longer exists)  
**Router table** (`skills/gsd-path/SKILL.md`): → bundled **research** contract (standard lane default)

**Result:** PASS — routing logic applied from installed router skill; no mutation errors on STATE

### 6b Child spawn (docs audit)

**Method:** Cursor `Task` subagent (`generalPurpose`) — native `subagent_type: gsd-path` **not available** in Cursor Task API enum (2026-08-05).

**Result:** PARTIAL (reconciled 2026-08-11; originally "PASS with caveat") —
a child wrote the audit artifact, but via the generic `generalPurpose`
subagent, not the contract's `gsd-path` subagent type, which the same run
recorded as unavailable. The dispatch contract itself remains unverified on
Cursor.  
**Artifact:** `.project/research/DOCS-AUDIT.md` (full template: summary counts, claim row, remediation queue)  
**Spawn API:** Cursor Task → `generalPurpose` (project `.cursor/agents/gsd-path.md` exists but not used via Task enum)

### 6c Handoff on disk

**Result:** PASS — `DOCS-AUDIT.md` valid structure at canonical path

---

## 7. Automated suite (re-run)

```bash
cd /Users/jeremymcspadden/github/open-gsd/gsd-path
npm test && python3 -m unittest discover -s tests -q
```

**Result:** PASS — 36 Node + 107 Python (2026-08-05 run; see
`automated-test-inventory.md` for the current suite inventory)

---

## Summary vs manual bar

| Bar item | Host | Status | Evidence |
|--------|------|--------|----------|
| Install + hooks | All 3 | **PASS** | §1 |
| Guard deny/allow | Claude (+ git hooks all) | **PASS** | §2 |
| Dispatch smoke | Codex | **UNVERIFIABLE** | §4 (top-level CLI run; no child spawn — downgraded 2026-08-11) |
| Dispatch smoke | Claude | **UNVERIFIABLE** | §5 (top-level CLI run; no child spawn — downgraded 2026-08-11) |
| Pipeline slice | Cursor | **PARTIAL** | §6 (Task API lacks `gsd-path` subagent type; child ran as `generalPurpose`) |
| Codex implicit catalog | Codex | **PASS** | §3 |
| Build orchestration | — | **NOT RUN** | deferred per spec |
| Full milestone ship | — | **NOT RUN** | deferred per spec |

---

## Posture updates (after evidence)

| Dimension | Prior | After manual runs |
|-----------|-------|-------------------|
| Host dispatch (Codex, Claude, Cursor) | Prove first | **Still prove first** (reconciled 2026-08-11) — recorded runs were top-level CLI invocations, not child-agent spawns through the dispatch contract |
| Live dogfood (Cursor slice) | Prove first | **Partial met** — router read + a `generalPurpose` child; contract's `gsd-path` subagent unavailable; not full UI `/gsd-path` session |
| Guards (Claude) | Use with checks | **OK to use** — deny/allow reproduced in test repo |
| Guards (Codex/Cursor pre-tool-use) | Use with checks | unchanged — git hooks proven; pre-tool-use not wired |
| Build orchestration | Prove first | unchanged — not run |
| CI | Prove first | **Automated** — `.github/workflows/ci.yml` now runs Node, Python, and resource-sync checks; this was not part of the 2026-08-05 manual run |
