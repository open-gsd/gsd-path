# GSD Path

A disk-backed project pipeline for AI coding agents. It turns a raw idea into
shipped code through gated phases — inspect, define, research, decide, plan,
build, and ship — with every handoff written to `.project/` so any session
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

Ten canonical explicit-only skills plus four deprecated aliases are installed.
Invoke the **router** by default; use phase skills for one step only, or use the
discussion sidecar to talk through a question at any non-shipped phase.

| Skill | Role |
| --- | --- |
| `gsd-path` | Router — detects state, runs next phase |
| `gsd-path-discuss` | Any-phase discussion with durable dialogue and answers |
| `gsd-path-inspect` | Brownfield codebase map + doc audit |
| `gsd-path-define` | Intent interview |
| `gsd-path-research` | Parallel evidence researchers |
| `gsd-path-decide` | Evidence → decisions |
| `gsd-path-plan` | Waves and task contracts |
| `gsd-path-build` | Parallel coders + integration |
| `gsd-path-ship` | Verify, approve, archive, and ship |
| `gsd-path-docs-audit` | Standalone doc-vs-code drift check |

Codex: `$gsd-path`, `$gsd-path-plan`, … · Other hosts: `/gsd-path`, `/gsd-path-plan`, …

## The flow

```text
gsd-path  (router)
  |
  |-- 0. inspect      brownfield  -> evidence-codebase.md, DOCS-AUDIT.md
  |-- 1. define       intent      -> intent/INTENT.md
  |-- 2. research     evidence    -> RESEARCH.md, evidence-*.md
  |-- 3. decide       decisions   -> research/SYNTHESIS.md
  |-- 4. plan         tasks       -> plan/PLAN.md, tasks/T*.md
  |-- 5. build        code        -> commits, BOARD.md
  `-- 6. ship         verify      -> review/*.md -> archive/
```

At any non-shipped phase, `/gsd-path-discuss` (or `$gsd-path-discuss` in
Codex) records the conversation in `.project/discuss/` without advancing or
editing the phase handoff. Required decisions carry a named owner and remain
pending until that phase records how it applied them; the router will not
advance past an unresolved required follow-up.

Invoke the router explicitly. It does not run on generic “continue the project”
prompts. Phase skills stop at their handoff; invoke the router again to continue.
The discussion sidecar is the exception: it can be invoked at any non-shipped
phase and returns only a durable conversation record.

**Brownfield** (existing code/docs) → inspect then define. **Greenfield** → define.
**Quick lane** (tiny scope) may skip research/decide — see [FULL.md](FULL.md).

Deprecated compatibility aliases remain for existing invocations; removing
them requires a separately approved breaking change:
`onboard → inspect`, `grill → define`, `synthesize → decide`, and
`review → ship`. Persisted v1 STATE phase tokens do not change, so active
projects resume without migration.

For an explicit new-GitHub request, the router previews the owner, visibility,
default checkout, `gsd-path/<project>` branch, and sibling linked worktree. A
journaled helper performs the approved creation and safely resumes a matching
partial remote/clone/worktree transaction; the default checkout stays clean.

## Handoff contract

```text
.project/
  STATE.md                    phase, branch, archive transaction
  REPOSITORY.md               persistent new-GitHub checkout/worktree binding
  intent/INTENT.md            goal, vetoes, constraints
  research/
    evidence-codebase.md      brownfield ground truth (inspect)
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
  discuss/DIALOGUE.md         any-phase dialogue transcript
  discuss/ANSWERS.md          durable discussion answers and decisions
  archive/<NNN>-<slug>/       shipped milestones (read-only after ship)
```

Shipping moves milestone artifacts into `archive/` with a MANIFEST. `STATE.md`,
`REPOSITORY.md`, and `LESSONS.md` remain active project metadata.

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

Something off? `node scripts/install.mjs --doctor [--project PATH]` — read-only
health check of installs, guard hooks, and pipeline state.

## Agent execution

Define and build orchestrators run in the main task. Researchers, deciders,
planners, coders, and reviewers delegate via host-specific adapters. See
[FULL.md — Agent execution](FULL.md#agent-execution-how-work-is-delegated) for
the authoritative host API table and delegation rules.

`platforms/` is installer-only — not user-invoked skills.

## Repository layout

| Path | Purpose |
| --- | --- |
| `DOCS.md` | Documentation hub |
| `QUICK.md` | Quick start |
| `FULL.md` | Full guide |
| `UPDATE.md` | Updating |
| `HOOKS.md` | Guard hooks |
| `skills/` | Ten canonical `gsd-path*` skills plus four deprecated aliases |
| `platforms/` | Host dispatch adapters |
| `scripts/install.mjs` | Installer (npm `gsd-path` bin) |
| `scripts/install.py` | Python installer |
| `AGENTS.md` | Operating rules (installed to projects) |
| `WORKFLOW.md` | Phase SOP (installed to projects) |
| `LICENSE` | MIT |
