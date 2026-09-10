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

The current installer also registers `.git/hooks/pre-push`; it was not part
of this historical run. See [HOOKS.md](../../HOOKS.md) for current guard rules.

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
| Build orchestration | All 11 | **PASS** | §Release evidence — every receipt carries a native child spawn and an isolated Task Verify |
| Full milestone ship | All 11 | **PASS** | §Release evidence — eleven passing receipts on candidate 091d279 |

---

## Posture updates (after evidence)

| Dimension | Prior | After manual runs |
|-----------|-------|-------------------|
| Host dispatch (all eleven hosts) | Prove first | **Met** (2026-09-09) — each receipt binds a real child spawned through that host's declared child API; the 2026-08-11 reconciliation applied to the earlier top-level CLI runs, which these receipts supersede |
| Live dogfood (Cursor slice) | Prove first | **Partial met** — router read + a `generalPurpose` child; contract's `gsd-path` subagent unavailable; not full UI `/gsd-path` session |
| Guards (Claude) | Use with checks | **OK to use** — deny/allow reproduced in test repo |
| Guards (Codex/Cursor pre-tool-use) | Use with checks | unchanged — git hooks proven; pre-tool-use not wired |
| Build orchestration | Prove first | **Met** — every one of the eleven receipts binds a completed native child to the landed task commit |
| CI | Prove first | **Automated** — `.github/workflows/ci.yml` now runs Node, Python, and resource-sync checks; this was not part of the 2026-08-05 manual run |

---

## Release evidence (2026-09-09)

Every one of the eleven supported hosts holds a passing full-milestone receipt
on the frozen candidate `091d27927a2c0c2ecc55ce386fb2232556da6336`. Each receipt
records a real run on a fresh fixture: the router reaching `shipped`, a native
child spawned through that host's own child API and bound to the landed task
commit, an isolated Task Verify, a full-wave review, the archive transaction,
the single `.project`-only ship commit, integration to a local origin, and the
Git-hook guard result. `scripts/check_trust_evidence.py` validates all eleven
against that candidate, and the accompanying `fixture.bundle` carries the
history each claim is checked against.

Guard tiers: Claude Code and Cursor install a fail-closed project hook, and both
receipts include a native guard probe in which the host's own tooling refused an
edit to a committed archive file while an ordinary shell command was allowed.
The other nine hosts are declared git-only, so the Git hooks carry enforcement
and `native_guard` reads `not-applicable`.

Owner gates were answered by the session evaluator and are recorded verbatim in
each evaluation directory. Six hosts honored every gate unaided; Cursor, GitHub
Copilot CLI, Qwen Code, and Kimi Code required a hard-stop prompt addendum after
self-approving a gate, which is recorded in their receipts. Host-specific
setup and behaviour notes live in [HOST-MATRIX.md](HOST-MATRIX.md).

Publication remains a separate owner decision. These receipts establish that
the pipeline runs end to end on every supported host; they do not by themselves
authorize a version tag, a registry publish, or a visibility change.
