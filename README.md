# GSD Path

A disk-backed project pipeline for AI coding agents. It turns a raw idea into
shipped code through gated phases — interview, research, decisions, plan, parallel
build, review, ship — with every handoff written to `.project/` so any session
can resume from disk alone.

**Supported hosts:** Codex, Claude Code, Grok, OpenCode, GitHub Copilot CLI,
Qwen Code, Antigravity CLI, Cursor, Zed, Kiro, and Kimi Code.

## Documentation

**Start at [DOCS.md](DOCS.md)** — install, use, understand, and update in one hub.

| Guide | Use when |
| --- | --- |
| **[DOCS.md](DOCS.md)** | Full map + FAQ (recommended) |
| **[QUICK.md](QUICK.md)** | First run checklist (~5 min) |
| **[FULL.md](FULL.md)** | Complete install-to-ship walkthrough |
| **[UPDATE.md](UPDATE.md)** | Refresh skills, hooks, or contracts |
| [WORKFLOW.md](WORKFLOW.md) | Phase-by-phase agent SOP |
| [HOOKS.md](HOOKS.md) | Optional archive/git guard hooks |
| [GUIDE.md](GUIDE.md) | Pointer to the guides above |

```bash
# New user
node scripts/install.mjs --all --dry-run && node scripts/install.mjs --all
cd your-repo && node scripts/install.mjs --all --project "$(pwd)"
# In agent: $gsd-path (Codex) or /gsd-path (most hosts)

# Already installed
node scripts/install.mjs --update
```

npm: `npx gsd-path --all` · Help: `node scripts/install.mjs --help`

## Skills

Nine explicit-only skills. Invoke the **router** by default; use phase skills for
one step only.

| Skill | Role |
| --- | --- |
| `gsd-path` | Router — detects state, runs next phase |
| `gsd-path-onboard` | Brownfield codebase map + doc audit |
| `gsd-path-grill` | Intent interview |
| `gsd-path-research` | Parallel evidence researchers |
| `gsd-path-synthesize` | Evidence → decisions |
| `gsd-path-plan` | Waves and task contracts |
| `gsd-path-build` | Parallel coders + integration |
| `gsd-path-review` | Wave and final review → ship |
| `gsd-path-docs-audit` | Standalone doc-vs-code drift check |

Codex: `$gsd-path`, `$gsd-path-plan`, … · Other hosts: `/gsd-path`, `/gsd-path-plan`, …

## The flow

```text
gsd-path  (router)
  |
  |-- 0. onboard      brownfield  -> evidence-codebase.md, DOCS-AUDIT.md
  |-- 1. grill        intent      -> intent/INTENT.md
  |-- 2. research     evidence    -> RESEARCH.md, evidence-*.md
  |-- 3. synthesize   decisions   -> research/SYNTHESIS.md
  |-- 4. plan         tasks       -> plan/PLAN.md, tasks/T*.md
  |-- 5. build        code        -> commits, BOARD.md
  `-- 6. review       gates       -> review/*.md -> ship -> archive/
```

Invoke the router explicitly. It does not run on generic “continue the project”
prompts. Phase skills stop at their handoff; invoke the router again to continue.

**Brownfield** (existing code/docs) → onboard then grill. **Greenfield** → grill.
**Quick lane** (tiny scope) may skip research/synthesize — see [FULL.md](FULL.md).

## Handoff contract

```text
.project/
  STATE.md                    phase, branch, archive transaction
  intent/INTENT.md            goal, vetoes, constraints
  research/
    evidence-codebase.md      brownfield ground truth (onboard)
    DOCS-AUDIT.md             doc verdicts + remediation queue
    RESEARCH.md               dispatch manifest (dimensions researched/skipped)
    evidence-domain.md        domain evidence
    evidence-stack.md         stack evidence
    evidence-pitfalls.md      pitfalls evidence
    evidence-similar.md       similar projects evidence
    SYNTHESIS.md              gated decisions
  plan/PLAN.md                waves, dependencies, verify
  tasks/T###-slug.md          task contract, base SHA, commit
  BOARD.md                    build summary
  review/wave-N.cycleC.md     wave review
  review/final-gap-N.md       gap review
  review/FINAL.md             success-criteria audit
  review/PATCH-FINDINGS.md    patch-wave findings (when review blocks)
  archive/<NNN>-<slug>/       shipped milestones (read-only after ship)
```

Shipping moves artifacts (except active `STATE.md`) into `archive/` with a MANIFEST.

## Install (summary)

Node 18.17+. Validates package, backs up existing skills, rolls back on failure.
**Always** `--dry-run` first when unsure.

```bash
node scripts/install.mjs --all --dry-run
node scripts/install.mjs --all
node scripts/install.mjs --claude --cursor
node scripts/install.mjs --all --local
node scripts/install.mjs --all --project /path/to/project
node scripts/install.mjs --update
```

| Flag | User skills root | Invoke |
| --- | --- | --- |
| `--codex`, `--zed` | `~/.agents/skills` | `$gsd-path` / `/gsd-path` |
| `--claude` | `~/.claude/skills` | `/gsd-path` |
| `--cursor` | `~/.cursor/skills` (+ subagent) | `/gsd-path` |
| `--grok` | `~/.grok/skills` | `/gsd-path` |
| `--opencode` | OpenCode config `skills/` | `/gsd-path` (v2) |
| `--copilot` | `~/.copilot/skills` | `/gsd-path` |
| `--qwen` | `~/.qwen/skills` | `/gsd-path` |
| `--antigravity` | Antigravity skills dir | `/gsd-path` |
| `--kiro` | `~/.kiro/skills` | `/gsd-path` |
| `--kimi` | `~/.kimi-code/skills` | `/gsd-path` |

`scripts/install.py` — global install in Python. See [FULL.md](FULL.md) and
[UPDATE.md](UPDATE.md) for `--hooks`, `--hooks-refresh`, `--local`, and host notes.

Optional **`--hooks`** with `--project` — [HOOKS.md](HOOKS.md).

## Agent execution

Grill and build orchestrator run in the main task. Researchers, synthesizer,
planner, coders, and reviewers delegate via host-specific adapters:

| Host | Child-agent API |
| --- | --- |
| Codex | collaboration |
| Claude Code | `Agent` |
| Grok | `spawn_subagent` |
| OpenCode | `Task` / v2 `subagent` |
| GitHub Copilot CLI | `task` |
| Qwen Code | `agent` |
| Antigravity CLI | `invoke_subagent` |
| Cursor | `Task` (`gsd-path` subagent) |
| Zed | `spawn_agent` |
| Kiro | subagent facility |

Parallel work up to child capacity; same-wave dependencies in layers. Context
on disk in `.project/`, not chat.

`platforms/` is installer-only — not user-invoked skills.

## Repository layout

| Path | Purpose |
| --- | --- |
| `DOCS.md` | Documentation hub |
| `QUICK.md` | Quick start |
| `FULL.md` | Full guide |
| `UPDATE.md` | Updating |
| `HOOKS.md` | Guard hooks |
| `skills/` | Nine `gsd-path*` skills |
| `platforms/` | Host dispatch adapters |
| `scripts/install.mjs` | Installer (npm `gsd-path` bin) |
| `scripts/install.py` | Python installer |
| `AGENTS.md` | Operating rules (installed to projects) |
| `WORKFLOW.md` | Phase SOP (installed to projects) |
| `LICENSE` | MIT |
