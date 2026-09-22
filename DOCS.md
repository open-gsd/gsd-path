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
2. **Project contracts** (optional) — `AGENTS.md`, `WORKFLOW.md`, and the
   tracked runtime declaration and stable status/guard launchers; runtime code
   lives outside the checkout under `~/.gsd-path/runtimes/`

### Decision tree

```text
Where should skills live?
├─ My machine, many repos     → global:  install.mjs --all
└─ This repo only (team pin)  → local:   install.mjs --all --local  (from repo root)

Will this repo run the pipeline?
├─ yes → add --project "$(pwd)"  (contracts + plain-prompt re-entry runtime)
└─ no  → skills only

Want archive / destructive-git enforcement?
└─ add --hooks with --project  → see HOOKS.md
```

### Commands

**Clone** (this repository — primary path):

```bash
node scripts/install.mjs --all --dry-run   # preview — safe to run anytime
node scripts/install.mjs --all             # apply
```

**npm** (no clone required):

```bash
npx @opengsd/gsd-path --all --dry-run
npx @opengsd/gsd-path --all
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

**Requirements:** Node 18.17+. Project installs also require Python 3.9+ as
`python3` or `python`. **Always** restart the agent session after install.

**Host flags** are derived from `scripts/skill-resources.json`. Run
`node scripts/install.mjs --help` for the current `--<host>` list.

Full roots and invocation table: [README.md](README.md#install-summary).

**Python installer:** `scripts/install.py` supports global and `--local`
installs plus `--update`. The Node CLI remains the interactive wizard and npm
entry point.
Help: `node scripts/install.mjs --help`

---

## Using

### Invoke the router (daily driver)

Work **in the project directory**. Invoke **explicitly**:

Use the [router and phase invocation table](README.md#install-summary) for your host.

The router reads `.project/STATE.md`, reports phase, runs the next valid step.
Vague chat such as “continue the project” does **not** run it. In a project
with an owned `.project/STATE.md`, such a prompt answers read-only with the
current handoff and the next skill to invoke; it never advances a phase.

### Skills (optional)

Run one phase only; stops at handoff:

| Skill | Invoke (slash hosts) | Purpose |
| --- | --- | --- |
| `path` | `/path` | Router short name (same skill as `/gsd-path`) |
| `gsd-path` | `/gsd-path` | Router — default (`/gsd-path status` reports without advancing) |
| `gsd-path-discuss` | `/gsd-path-discuss` | Any-phase discussion and durable answers |
| `gsd-path-inspect` | `/gsd-path-inspect` | Brownfield scan only |
| `gsd-path-define` | `/gsd-path-define` | Intent definition only |
| `gsd-path-research` | `/gsd-path-research` | Evidence gathering |
| `gsd-path-decide` | `/gsd-path-decide` | Decisions |
| `gsd-path-roadmap` | `/gsd-path-roadmap` | Program milestone slicing |
| `gsd-path-plan` | `/gsd-path-plan` | Waves + tasks |
| `gsd-path-build` | `/gsd-path-build` | Parallel build |
| `gsd-path-ship` | `/gsd-path-ship` | Review + ship gate |
| `gsd-path-docs-audit` | `/gsd-path-docs-audit` | Standalone doc drift check |
| `gsd-path-loop` | `/gsd-path-loop` | Bounded loop runner driven by a LOOP.md spec |
| `gsd-path-forensics` | `/gsd-path-forensics` | Read-only stuck-pipeline diagnosis |
| `gsd-path-migrate` | `/gsd-path-migrate` | Import GSD Core context and review hook coexistence |
| `gsd-path-undo` | `/gsd-path-undo` | Helper-owned undo of unpublished pipeline work |

Codex: use `$` instead of `/` (e.g. `$gsd-path-plan`).

### Discuss at any phase

Invoke `/gsd-path-discuss` (or `$gsd-path-discuss` in Codex) whenever you need
to question a decision, inspect progress, challenge an assumption, or resolve
an open issue without advancing the pipeline. The skill reads the current
phase artifacts and relevant code, pushes back with evidence when needed, and
uses focused research for unresolved external or technical questions. It
appends the verbatim dialogue to `.project/discuss/DIALOGUE.md` and the
answer/decision record to `.project/discuss/ANSWERS.md`; it never edits phase
state or bypasses a gate.

### Gates (what you approve)

| Phase | You do |
| --- | --- |
| Define | Answer gaps or review milestone derivation; approve intent playback |
| Decide | Resolve `NEEDS-USER` decisions |
| Roadmap | **Approve milestone slicing** (program flow) |
| Plan | **Approve wave summary** before any code is written |
| Build | Usually nothing — escalations only |
| Ship | Approve patch waves if blocked and approve final shipping when green |

### Cheat sheet

```text
No state, greenfield verdict    → router → define (first milestone)
No state, brownfield verdict    → router → inspect → define
No state, orphan verdict        → router → block for recovery
Huge multi-milestone program    → router → define (program mode: charter →
                                  research → decide → roadmap → milestone loop)
Already mid-pipeline            → router (continues)
Doc drift between phases        → /gsd-path-docs-audit
Moving from GSD Core            → /gsd-path-migrate (see MIGRATE.md)
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
inspect (brownfield only)
  → define → research → decide → plan
  → build (parallel coders, serial task landing)
  → ship (verify, archive, and integrate with main)

Program flow inserts roadmap between decide and plan: define
(program mode) writes CHARTER.md, roadmap slices it into ROADMAP.md,
and each later milestone loops inspect → define (milestone + brownfield) →
research and decide when the roadmap entry has open questions → plan → build
→ ship. The first milestone after roadmap approval still starts at define
(milestone mode), then follows the same open-question branch; inspect already
ran at program start when the tree was brownfield.
During build, the next milestone can be planned in parallel under
`.project/next/` (lookahead); a building milestone can be abandoned on an
explicit ruling, archiving partial work and re-slicing the roadmap.
```

Build mechanics: task briefs are linted against the base tree before
dispatch and coders preflight them on arrival; dispatch streams (a
dependent starts when its deps land); wave review depth is `full`,
`verify-only`, or `deep` (writer and evidence rules live in the canonical
[build contract](skills/gsd-path-build/SKILL.md)); coder contract questions
route through `NEEDS-ORCHESTRATOR` instead of guesses.

**Quick lane:** ≤2 tasks, one wave, no open questions — may skip research/decide
([FULL.md](FULL.md)).

### Worktree locations

The primary worktree stays in the folder you opened. Serial task work stays
there too. New parallel task worktrees, verify sidecars, and integration
worktrees share this managed layout:

```text
~/.gsd-path/projects/<repository-id>/<workspace-id>/{task,verify,integrate}/<name>
```

Set `GSD_PATH_WORKTREE_ROOT` to another absolute directory before the first
helper-owned allocation in a workspace. The root must be outside the project's
own worktrees; an unrelated repository tracking your home folder is allowed.
Repository and workspace IDs are full SHA-256 hashes of the
resolved Git common directory and primary path, so separate clones and
primary folders do not share a location.

The first allocation pins the workspace location in
`<git-common-dir>/gsd-path/workspaces/<workspace-id>.json`. Later environment
changes do not move it. Existing sibling worktrees remain at their original
paths and retain the same recovery and cleanup checks. These folders contain
active work and evidence; they are not a disposable cache. Relocation needs
a separate migration; do not edit placement records or move folders manually.

New repository setup can also use an explicitly approved managed primary
path through the existing `--worktree` option. Its parent must already exist
for the read-only preview. An approved empty invocation folder is still
reused in place. This choice does not move the default checkout.

In the dashboard's **Watched folders**, add the managed root explicitly;
watching its home-directory parent does not traverse hidden `.gsd-path`.
Discovery follows Git's registered bound branches back to the primary and
applies exclusions there, so task and verify copies do not displace it.

### Key artifacts

| Path | Role |
| --- | --- |
| `STATE.md` | Phase, branch, milestone, archive id |
| `REPOSITORY.md` | Persistent new-GitHub checkout/worktree binding |
| `CHARTER.md` | Program scope and vetoes (program flow; never archives) |
| `ROADMAP.md` | Milestone slicing (program flow; never archives) |
| `SYNTHESIS.md` | Program decisions at top level (program flow; never archives) |
| `next/` | Lookahead track: next milestone's artifacts during build (program flow) |
| `intent/INTENT.md` | Goal, vetoes, constraints |
| `research/RESEARCH.md` | Which dimensions were researched / skipped |
| `research/SYNTHESIS.md` | Decisions for planner |
| `plan/PLAN.md` | Waves and dependencies |
| `tasks/T###-slug.md` | One coder contract (base SHA, scope) |
| `review/PLAN-PANEL.md` | Optional cross-model plan review |
| `review/wave-N.cycleC.panel.md` | Optional cross-model wave review |
| `review/FINAL.md` | Ship gate verdicts |
| `review/PATCH-FINDINGS.md` | Evidence for patch waves (when review blocks) |
| `discuss/DIALOGUE.md` | Any-phase discussion transcript |
| `discuss/ANSWERS.md` | Durable answers, pending owners, and disposition receipts |
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
| From npm | `npx @opengsd/gsd-path@latest --update` |
| Guard scripts | `node scripts/install.mjs --hooks-refresh --project PATH` |
| `AGENTS.md` / `WORKFLOW.md` | Manual merge — installer refuses overwrite |
| Health check | `node scripts/install.mjs --doctor [--project PATH]` — read-only; flags missing/stale skills, hook drift, and bad pipeline state |

Full guide: **[UPDATE.md](UPDATE.md)**. Router may print a one-line npm update notice.

---

## FAQ

**Does it run automatically when I ask the agent to build something?**
No. Invoke `$gsd-path` or `/gsd-path` explicitly. Skills are explicit-only on most hosts.
In a project with an owned `.project/STATE.md`, a plain prompt reports the
current phase and next skill read-only instead of building.

**I installed but nothing shows up in the agent.**
Restart the host session. Confirm with `ls ~/.claude/skills/gsd-path` (or your host root).

**Can I use only Cursor, not every host?**
Yes: `node scripts/install.mjs --cursor` (add other flags as needed).

**Will install overwrite my `AGENTS.md`?**
No — if managed project files already exist, a plain install refuses and installs
nothing for that project. Use `--update --project PATH` to refresh skills and the
managed `.gsd-path/` runtime while keeping your contracts; merge project
contract updates manually ([UPDATE.md](UPDATE.md)).

**Where is pipeline state?**
`.project/` in your repo — not chat history.

**How do I undo a skill update?**
Restore from `disabled-gsd-skills` beside the skills root ([UPDATE.md](UPDATE.md)).

**How do I see status without advancing?**
`$gsd-path status` (or `/gsd-path status`). It reports the helper-owned state
snapshot and stops.

**The pipeline is stuck. Do I invent git commands?**
No. `$gsd-path-forensics` is read-only diagnosis. `$gsd-path-undo` previews
then applies helper-owned undo of unpublished work. Neither force-pushes.

**Moving from GSD Core?**
Invoke `$gsd-path-migrate` (Claude Code and Codex first release). It prepares
an external import bundle, reviews hook coexistence, and hands off to the Path
router through inspect and define. See **[MIGRATE.md](MIGRATE.md)**.

**Brownfield vs greenfield?**
After the [startup prerequisites](README.md#the-flow) are met, the router
classifies the project before it creates STATE.md for a brownfield or
greenfield verdict. The exact initializer invocation belongs to the
[phase workflow](WORKFLOW.md#phase-0--inspect-gsd-path-inspect). A recognized
manifest or source file, qualifying tracked Git file, or qualifying Markdown
document with a body is brownfield and routes to inspect. A title-only README,
`LICENSE`/`COPYING`, `.gitignore`, or content only in ignored trees such as
`node_modules` does not count. Neither do managed GSD Path files or verified
GSD Path skill bundles: a `gsd-path*` or `ogsd*` bundle is verified under a
supported installer skill root or when it contains `SKILL.md`; a similarly
named source directory still counts normally. Those scaffold-only trees stay
greenfield and route to define. Other `.project/` content without STATE.md is
orphaned and blocks for recovery. An owned state, including the new-GitHub
bootstrap state, routes by STATE.md after classification without running the
initializer. After a milestone ships, the next one inspects again.

---

## Help

| Problem | See |
| --- | --- |
| Install / update errors | `--dry-run` first; [UPDATE.md](UPDATE.md) |
| Router won’t start | Explicit invocation; check `STATE.md` |
| Phase blocked | [FULL.md](FULL.md) troubleshooting |
| Archive commit blocked | [HOOKS.md](HOOKS.md) |
| Installer flags | `node scripts/install.mjs --help` |

[Workflow runner and observed token budgets](RUNTIME.md) documents canonical gate receipts, serial verification preparation, and host budget limits.


## Project runtime versions

`.gsd-path/runtime.json` pins an exact runtime by package version and content
digest. The runtime is stored under `~/.gsd-path/runtimes/<digest>/`; generated
implementation files are not copied into project worktrees. Track the declaration
and stable `.gsd-path` launchers as project configuration. Task isolation, Verify
sidecars and Integration checkouts inherit this configuration through Git.

Skill/plugin updates and `--hooks-refresh` retain the selected runtime. Use
`gsd-path --runtime-upgrade --project /absolute/project` to explicitly select
the supplied package's runtime and its compatible status launcher. Review those
configuration changes before committing them. Existing versions remain available
for other projects and branches.

A new machine needs the selected runtime installed before status and guards can
run. `gsd-path --runtime-restore --project /absolute/project --source-root
/path/to/matching/package` restores that exact version without changing project
files. The supplied package must match both the version and digest; custom source
builds may share a release version while having different digests. No command
silently substitutes a newer runtime, and status/guards never install or download.

For an old `.gsd-path/runtime/`, run `gsd-path --runtime-migrate --project
/absolute/project --dry-run`, then the same command without `--dry-run` and review
the Git diff. Migration removes the generated files from the checkout and writes
the declaration and stable wiring. It does not stage or commit. Resolve local
edits to tracked runtime files or unknown files first. Untracked managed files
may differ from the supplied package: migration saves their original bytes under
`~/.gsd-path/runtime-migrations/backups/` and prints the backup directory for
review. Interrupted migration is recovered by the same explicit command; its
journal lives outside the checkout.

To migrate and then update skills and project wiring in one invocation, follow
[Legacy project runtime](UPDATE.md#legacy-project-runtime) for wizard consent,
unattended commands, dry-run scope, and recovery after an update failure.

An ignore rule alone cannot migrate tracked runtime files. This runtime lifecycle
covers runtime code and launch wiring; project-local skill copies, retained skill
backups, and mixed user/host settings remain separately owned installation output.
