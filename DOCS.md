# GSD Path — Documentation Hub

Everything to **install**, **use**, **understand**, and **update** GSD Path.

```text
README.md          project overview + reference tables
    │
DOCS.md (here)     four journeys in one place
    ├── QUICK.md       first run checklist (~5 min)
    ├── FULL.md        install → ship, all phases
    ├── UPDATE.md      refresh skills, hooks, contracts
    ├── HOOKS.md       optional archive/git guards
    └── WORKFLOW.md    agent SOP (installed into your repo)
```

## Pick your path

| I want to… | Read |
| --- | --- |
| Install and run today | [QUICK.md](QUICK.md) |
| See install / use / update in one page | Stay on this file ↓ |
| Deep walkthrough every phase | [FULL.md](FULL.md) |
| Upgrade after `git pull` or npm | [UPDATE.md](UPDATE.md) |
| Reference tables (hosts, artifacts, flags) | [README.md](README.md) |
| Optional guard hooks | [HOOKS.md](HOOKS.md) |
| What agents execute per phase | [WORKFLOW.md](WORKFLOW.md) |

### By situation

| You are… | Do this |
| --- | --- |
| **New** — never installed | [QUICK.md](QUICK.md) checklist |
| **New repo** — skills already global | `install.mjs --all --project "$(pwd)"` → invoke router |
| **Returning** — mid-milestone | Invoke router in project; read [Using](#using) |
| **Upgrading** — new gsd-path version | [UPDATE.md](UPDATE.md) |
| **Team** — pin skills in repo | `--local` install; see [Installing](#installing) |
| **Shipping broke** — archive commit blocked | [HOOKS.md](HOOKS.md) (expected with hooks) |

---

## Installing

GSD Path has two install layers:

1. **Skills** — router + phase skills for your AI host(s)
2. **Project contracts** (optional) — `AGENTS.md` and `WORKFLOW.md` in the repo

### Decision tree

```text
Where should skills live?
├─ My machine, many repos     → global:  install.mjs --all
└─ This repo only (team pin)  → local:   install.mjs --all --local  (from repo root)

Will this repo run the pipeline?
├─ yes → add --project "$(pwd)"  (AGENTS.md + WORKFLOW.md)
└─ no  → skills only

Want archive / destructive-git enforcement?
└─ add --hooks with --project  → see HOOKS.md
```

### Commands

**Clone** (this repository):

```bash
node scripts/install.mjs --all --dry-run   # preview — safe to run anytime
node scripts/install.mjs --all             # apply
```

**npm** (no clone):

```bash
npx gsd-path --all --dry-run
npx gsd-path --all
```

**New repo** (skills + project rules):

```bash
cd /path/to/your/repo
node scripts/install.mjs --all --project "$(pwd)"
```

**Optional hooks** (with Claude example):

```bash
node scripts/install.mjs --claude --project "$(pwd)" --hooks
```

**Requirements:** Node 18.17+. **Always** restart the agent session after install.

**Host flags** (instead of `--all`): `--codex`, `--claude`, `--cursor`, `--zed`,
`--grok`, `--opencode`, `--copilot`, `--qwen`, `--antigravity`, `--kiro`, `--kimi`.

Full roots and invocation table: [README.md](README.md#install-summary).

**Python installer:** `scripts/install.py` — same global install; no `--local` UI.
Help: `node scripts/install.mjs --help`

---

## Using

### Invoke the router (daily driver)

Work **in the project directory**. Invoke **explicitly**:

| Host | Router |
| --- | --- |
| Codex | `$gsd-path` |
| Claude, Cursor, Zed, Grok, Copilot, Qwen, Kiro, Kimi, Antigravity | `/gsd-path` |
| OpenCode v2 | `/gsd-path` |
| OpenCode stable | Ask to *load and use the gsd-path skill* |

The router reads `.project/STATE.md`, reports phase, runs the next valid step.
It does **not** run on “continue the project” or similar vague chat.

### Phase skills (optional)

Run one phase only; stops at handoff:

| Skill | Invoke (slash hosts) | Purpose |
| --- | --- | --- |
| `gsd-path` | `/gsd-path` | Router — default |
| `gsd-path-onboard` | `/gsd-path-onboard` | Brownfield scan only |
| `gsd-path-grill` | `/gsd-path-grill` | Intent interview only |
| `gsd-path-research` | `/gsd-path-research` | Evidence gathering |
| `gsd-path-synthesize` | `/gsd-path-synthesize` | Decisions |
| `gsd-path-plan` | `/gsd-path-plan` | Waves + tasks |
| `gsd-path-build` | `/gsd-path-build` | Parallel build |
| `gsd-path-review` | `/gsd-path-review` | Review + ship gate |
| `gsd-path-docs-audit` | `/gsd-path-docs-audit` | Standalone doc drift check |

Codex: use `$` instead of `/` (e.g. `$gsd-path-plan`).

### Gates (what you approve)

| Phase | You do |
| --- | --- |
| Grill | Answer questions; approve intent playback |
| Synthesize | Resolve `NEEDS-USER` decisions |
| Plan | **Approve wave summary** before any code is written |
| Build | Usually nothing — escalations only |
| Review | Approve patch waves if review blocks shipping |

### Cheat sheet

```text
Empty repo, new milestone       → router → grill
Existing code, new milestone    → router → onboard → grill
Already mid-pipeline            → router (continues)
Doc drift between phases        → /gsd-path-docs-audit
Closed laptop, came back        → router (reads .project/)
```

Details: [FULL.md](FULL.md) (phases, shipping, troubleshooting).

---

## Understanding

### Mental model

1. **Disk is memory** — `.project/` files are the only phase memory.
2. **You gate progress** — intent, plan approval, final review.
3. **Router orchestrates** — one skill picks the next phase.
4. **Children do bounded work** — researchers/coders/reviewers in isolated agent contexts.
5. **Ship freezes history** — archives under `.project/archive/` are read-only.

### Pipeline

```text
onboard (brownfield only)
  → grill → research → synthesize → plan
  → build (parallel coders, serial merge)
  → review → ship (archive)
```

**Quick lane:** ≤2 tasks, one wave, no open questions — may skip research/synthesize
([FULL.md](FULL.md)).

### Key artifacts

| Path | Role |
| --- | --- |
| `STATE.md` | Phase, branch, milestone, archive id |
| `intent/INTENT.md` | Goal, vetoes, constraints |
| `research/RESEARCH.md` | Which dimensions were researched / skipped |
| `research/SYNTHESIS.md` | Decisions for planner |
| `plan/PLAN.md` | Waves and dependencies |
| `tasks/T###-slug.md` | One coder contract (base SHA, scope) |
| `BOARD.md` | Build status |
| `review/FINAL.md` | Ship gate verdicts |
| `review/PATCH-FINDINGS.md` | Evidence for patch waves (when review blocks) |
| `archive/<NNN>-slug/` | Shipped milestone — do not edit |

Full tree: [README.md](README.md#handoff-contract).

### Router vs phase skill

| | Router | Phase skill |
| --- | --- | --- |
| Default? | Yes | Only when you want one step |
| Auto-advance? | Yes (bundled contracts) | No — stops at handoff |

---

## Updating

| What | How |
| --- | --- |
| Global skills | `node scripts/install.mjs --update` |
| Project-local skills | `node scripts/install.mjs --update --local` |
| From npm | `npx gsd-path@latest --update` |
| Guard scripts | `node scripts/install.mjs --hooks-refresh --project PATH` |
| `AGENTS.md` / `WORKFLOW.md` | Manual merge — installer refuses overwrite |

Full guide: **[UPDATE.md](UPDATE.md)**. Router may print a one-line npm update notice.

---

## FAQ

**Does it run automatically when I ask the agent to build something?**
No. Invoke `$gsd-path` or `/gsd-path` explicitly. Skills are explicit-only on most hosts.

**I installed but nothing shows up in the agent.**
Restart the host session. Confirm with `ls ~/.claude/skills/gsd-path` (or your host root).

**Can I use only Cursor, not every host?**
Yes: `node scripts/install.mjs --cursor` (add other flags as needed).

**Will install overwrite my `AGENTS.md`?**
No, if it already exists. Merge template updates manually ([UPDATE.md](UPDATE.md)).

**Where is pipeline state?**
`.project/` in your repo — not chat history.

**How do I undo a skill update?**
Restore from `disabled-gsd-skills` beside the skills root ([UPDATE.md](UPDATE.md)).

**Brownfield vs greenfield?**
Brownfield = existing code/docs → onboard first. Greenfield = empty → grill first.

---

## Help

| Problem | See |
| --- | --- |
| Install / update errors | `--dry-run` first; [UPDATE.md](UPDATE.md) |
| Router won’t start | Explicit invocation; check `STATE.md` |
| Phase blocked | [FULL.md](FULL.md) troubleshooting |
| Archive commit blocked | [HOOKS.md](HOOKS.md) |
| Installer flags | `node scripts/install.mjs --help` |
