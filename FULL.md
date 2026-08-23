# GSD Path — Full Guide

Complete walkthrough from install to shipped milestone.

| Short path | [QUICK.md](QUICK.md) |
| Hub (install · use · understand · update) | [DOCS.md](DOCS.md) |
| Updating | [UPDATE.md](UPDATE.md) |

**Contents:** [What it is](#what-gsd-path-is) · [Installation](#installation) ·
[Starting a milestone](#starting-a-milestone) · [Phases](#phases-and-your-role) ·
[Shipping](#shipping) · [Resume](#resume-and-recovery) · [Troubleshooting](#troubleshooting)

**Related docs**

| Doc | Role |
| --- | --- |
| [DOCS.md](DOCS.md) | Hub + FAQ |
| [UPDATE.md](UPDATE.md) | Refresh skills and hooks |
| [README.md](README.md) | Reference tables |
| [WORKFLOW.md](WORKFLOW.md) | Agent phase SOP |
| [AGENTS.md](AGENTS.md) | Operating rules |
| [HOOKS.md](HOOKS.md) | Guard hooks |

---

## What GSD Path is

GSD Path turns an idea into shipped code through **gated phases**. Each phase
writes a fixed artifact under `.project/`; the next phase reads only from disk.
You can close your session at any point and a fresh session resumes exactly
where you left off.

You are the gate: nothing advances past intent, plan approval, or final review
without your approval.

### The pipeline

```text
gsd-path  (router: reads STATE.md, runs the next valid phase)
  |
  |-- 0. inspect      brownfield only — map code + audit docs
  |-- 1. define       interactive intent interview
  |-- 2. research     parallel evidence researchers
  |-- 3. decide       evidence → cited decisions
  |-- 3.5 roadmap     program flow: charter → milestone slicing
  |-- 4. plan         waves + task contracts
  |-- 5. build        parallel coders, serial task landing
  `-- 6. ship         verify + final approval → archive + merge to main
```

### Router vs phase skills

- **Router** (`gsd-path`): reports state and auto-advances through bundled phase
  contracts in one conversation when you want the full flow.
- **Phase skills** (`gsd-path-plan`, `/gsd-path-build`, …): run one phase and
  stop at its handoff. Invoke the router or the next phase explicitly to continue.
- **Discussion sidecar** (`gsd-path-discuss`, `/gsd-path-discuss`): can run at
  any non-shipped phase to answer a question, ground it in code and artifacts,
  use focused research when needed, and save the dialogue and answer without
  changing phase state.

All skills are **explicit-only** on most hosts — generic “continue the project”
does not inject the pipeline. On OpenCode stable, Antigravity CLI, and Kiro,
treat explicit invocation as an operating rule.

### Invocation by host

| Host | Router | Example phase |
| --- | --- | --- |
| Codex | `$gsd-path` | `$gsd-path-plan` |
| Claude Code, Grok, Copilot, Qwen, Cursor, Zed, Kiro, Kimi | `/gsd-path` | `/gsd-path-plan` |
| OpenCode v2 | `/gsd-path` | `/gsd-path-plan` |
| OpenCode stable | Ask to load `gsd-path` | Same |
| Antigravity CLI | `/gsd-path` | `/gsd-path-plan` |

---

## Installation

### Requirements

- **Node 18.17+** for `scripts/install.mjs` (recommended; also the npm `gsd-path` bin once the package is published to npm)
- **Python 3** optional — `scripts/install.py` mirrors global install validation and transactions (no `--local` UI)

### Global install (default)

Skills land in each host’s user-level skills root:

```bash
node scripts/install.mjs --all --dry-run   # preview
node scripts/install.mjs --all             # apply
```

Pick hosts:

```bash
node scripts/install.mjs --codex --claude --cursor
```

| Flag | Skills root |
| --- | --- |
| `--codex`, `--zed` | `~/.agents/skills` (shared bundle) |
| `--claude` | `~/.claude/skills` |
| `--grok` | `~/.grok/skills` |
| `--opencode` | OpenCode config `skills/` |
| `--copilot` | `~/.copilot/skills` |
| `--qwen` | `~/.qwen/skills` |
| `--antigravity` | `~/.gemini/antigravity-cli/skills` |
| `--cursor` | `~/.cursor/skills` + `~/.cursor/agents/gsd-path.md` |
| `--kiro` | `~/.kiro/skills` |
| `--kimi` | `~/.kimi-code/skills` |

Per-target overrides: `--cursor-root PATH`, etc.

### Project-local install

Install skills into the **current project’s** per-host directories:

```bash
cd /path/to/your/repo
node scripts/install.mjs --all --local
```

### Project contracts

Install shared rules into a repo (refuses if managed files already exist):

```bash
node scripts/install.mjs --all --project /path/to/project
```

Writes `AGENTS.md` and `WORKFLOW.md`; with Claude, also `.claude/CLAUDE.md`.
Merge upgrades manually — the installer will not overwrite existing contracts.

### Guard hooks (optional)

```bash
node scripts/install.mjs --claude --project /path/to/project --hooks
```

Installs `.gsd-path/` guard scripts, git `pre-commit` and `commit-msg` hooks,
and Claude PreToolUse wiring. See [HOOKS.md](HOOKS.md).

After upgrading the package:

```bash
node scripts/install.mjs --hooks-refresh --project /path/to/project
node scripts/install.mjs --hooks-refresh-full --project /path/to/project  # + settings/git hooks
```

### Updating skills

See [UPDATE.md](UPDATE.md) for the full updating guide. Quick reference:

```bash
node scripts/install.mjs --update              # global roots with existing install
node scripts/install.mjs --update --local      # current project only
npx gsd-path@latest --update                   # from npm, once published
```

Previous copies move to `disabled-gsd-skills` beside each root. The router may
also print a one-line update notice (24h cache, fail-silent).

### Safety

- Validates synchronized package before writing
- Backs up existing `gsd-path*` entries
- Rolls back **all** selected targets if any one fails
- Codex + Zed share one physical root — installed once with a shared bundle

Restart the host session after install if skills do not appear.

---

## Starting a milestone

Open your agent in the project directory. Invoke the router explicitly.

### Greenfield (empty or new milestone)

No `.project/STATE.md` in an existing empty checkout → **define** immediately.
For an explicit request to create a new GitHub repository, the router first
previews the repository and linked-worktree targets for approval as described
in [README.md](README.md#the-flow).

Define interviews across: problem, users, observable success, scope in,
scope out (vetoes), constraints, risks. It challenges contradictions, writes a
complete `.project/intent/INTENT.md` draft with the proposed `quick` or
`standard` lane, and links that draft alongside its **playback summary** before
asking for approval. For a multi-milestone program, define instead interviews
into `.project/CHARTER.md` (program mode); each milestone's INTENT.md is then
derived from the approved roadmap entry with `Lane: milestone` (milestone
mode).

Vetoes in INTENT.md are hard limits for every later phase.

### Brownfield (existing code or docs)

Router detects existing work → **inspect** first:

1. Codebase mapper — what actually exists (stack, architecture, surprises)
2. Docs auditor — every `.md` claim verified, stale, aspirational, or unverifiable

You get **ground truth on one screen** before any questions. Define then
asks only **deltas**: this milestone’s goal, what changes, what must not break.

Each doc-vs-code conflict gets your ruling: `fix-doc`, `fix-code`, or
`accept-drift`. Inspect writes nothing outside `.project/`.

### Quick lane

If scope fits ≤2 deliverable tasks in one wave with no open questions, define
may classify the milestone as `quick` — skipping research/decide with a
Settled-only SYNTHESIS and a single build wave. If the plan outgrows that,
the lane corrects to `standard` and reroutes through research.

---

## Phases and your role

After intent approval, the router walks phases and stops at gates.

| Phase | Output (under `.project/`) | Your role |
| --- | --- | --- |
| **Research** | `research/evidence-*.md` | Usually nothing |
| **Decide** | `research/SYNTHESIS.md` | Resolve `NEEDS-USER` at checkpoint |
| **Roadmap** (program) | `ROADMAP.md` | **Approve milestone slicing** |
| **Plan** | `plan/PLAN.md`, `tasks/T###-slug.md` | **Approve wave summary** |
| **Build** | code, commits | Escalations only |
| **Ship** | `review/wave-*.md`, `review/PLAN-PANEL.md`, `review/FINAL.md` | Approve patch waves if blocked and final shipping when green |

The discussion sidecar is available alongside every row above. It writes
`discuss/DIALOGUE.md` and `discuss/ANSWERS.md`; a `final` answer records context
but does not approve or advance a phase. A required follow-up blocks automatic
advancement until its named owner appends a disposition receipt.

### Research

Up to five parallel researchers — the four standard dimensions (domain,
stack, pitfalls, similar projects) plus an optional risk-driven custom
dimension.
Brownfield adds `evidence-codebase.md` from inspect as input. Dimensions with
nothing to answer are skipped and recorded in STATE.

### Decide

Turns evidence into cited decisions with runners-up. Unresolved values choices
surface as `NEEDS-USER` — never guessed.

### Plan

Reads INTENT + SYNTHESIS. Produces waves, dependency layers, and task contracts
(clean base SHA, allowed files, acceptance). **Wave 1** often spikes risk;
**wave 2** is the thinnest end-to-end slice. Build does not start without your
plan approval.

### Build

Orchestrator runs in the main task. A parallel dispatch round gives **coders**
isolated named-branch worktrees at one clean layer base; a serial round works
on the bound branch. Task landing is **serial**. Before
any worktree exists, the orchestrator lints every ready brief against the
recorded base with `check_task_briefs.py` and re-checks Intent coverage with
`check_handoffs.py plan`; a failure is a plan defect repaired
before the layer proceeds. Isolate, land, and retire go through
`isolation.py` — never a detached HEAD. Each coder reads INTENT.md and
preflights its brief first — every named
path exists at the base or is declared, owned success criteria exist in
INTENT.md, and the interface contract matches its
siblings verbatim — blocking immediately on a mismatch. Each
task gets one atomic commit; task frontmatter records its base and landed state,
and `isolation.py recover` proves the exact SHA from Git.
The orchestrator's isolated task Verify rerun is that task's evidence; wave
review reads it plus the isolated diff and does not re-run the command.
PLAN.md's project Verify runs once, at ship. A task Verify names a path
from `files` unless it is that allowed Project-verify copy.

### Ship

Wave reviews after each build wave check task criteria and the INTENT success
criteria that wave owns; final review audits every success criterion
(`met` / `not-met` / `unverifiable`) and cross-wave gaps. Each wave carries a
review depth — `full`, `verify-only` for low-risk waves, or sparingly `deep`
for irreversible or security-critical waves, where two independent reviewers
(contract and adversarial lenses) must both pass. Review findings are keyed by
their failed criterion and carried forward across cycles, so a criterion
failing again after its fix task means the fix failed, never a duplicate fix
task. Keep waves narrow enough for one reviewer context (≲12 tasks); split
wider work into more waves at plan time. Failed criteria become
**patch waves** — same build/review loop until the final gate passes.

---

## Shipping

Passing the final gate produces a final review surface. After you explicitly
approve **Archive and ship**, the archive transaction begins:

- Milestone artifacts move to `.project/archive/<NNN>-<slug>/`; `STATE.md`,
  `REPOSITORY.md`, `LESSONS.md`, and program artifacts (`CHARTER.md`,
  `ROADMAP.md`, top-level `SYNTHESIS.md`) remain active project metadata
- `MANIFEST.md` records contents and ship metadata
- One **ship commit** (subject `ship: M00N — <slug>`) touches only `.project/`
- Ship then merges `gsd-path/M00N` onto `main` (the remote default) and tags
  `milestone/<NNN>-<slug>`
- Archives are **read-only** — guard hooks enforce this if installed

After `validate-integrated` passes, the next milestone starts clean on a new
`gsd-path/M00N` cut from `origin/main`. Invoke the router again; brownfield
inspect runs against the now-shipped codebase. In program flow the router
instead pulls the next pending roadmap entry and resumes at define (milestone
mode); when every entry is shipped it reports the program complete against the
charter's success criteria.

Two program-flow refinements:

- **Lookahead** — while a milestone is in `build/active`, the router offers
  to plan the next dependency-ready milestone in parallel under
  `.project/next/` (define milestone mode → research for open questions →
  decide → plan, all under their normal gates). The track never touches
  active-path artifacts, never binds a branch, and advances only on your
  direction. At the milestone boundary the router promotes `next/` to the
  active paths in one commit (`router: promote lookahead milestone <slug>`)
  and routes by the promoted state — a fully planned track goes straight to
  build, after a promotion re-validation: task paths are diffed against the
  new HEAD from the approval checkpoint commit, and drifted tasks go back
  through plan gating and your re-approval before build starts.
- **Milestone abandon** — on your explicit ruling (review-cycle cap,
  invalidated decision, or direct request), the build orchestrator retires
  the task worktrees, runs the archive helper's `abandon` command to archive
  the partial artifacts without review gates, marks the roadmap entry
  `abandoned` (immutable), logs the ruling to LESSONS.md, and transitions to
  a roadmap re-slice. The abandoned code stays on the branch.

During build, a coder that hits an ambiguous (not defective) contract blocks
with `NEEDS-ORCHESTRATOR: <question>` in its task Log; the orchestrator
answers from the approved artifacts or asks you, records the answer in the
Log, and redispatches without consuming the task's one failure retry.

---

## Resume and recovery

Everything durable lives in `.project/`:

```text
.project/
  STATE.md                 phase, branch, archive transaction id
  REPOSITORY.md            persistent new-GitHub checkout/worktree binding
  CHARTER.md               program scope (program flow; persists)
  ROADMAP.md               milestone slicing (program flow; persists)
  SYNTHESIS.md             program decisions (program flow; persists)
  next/                    lookahead track artifacts (program flow; during build)
  intent/INTENT.md
  research/RESEARCH.md     dispatch manifest
  research/SYNTHESIS.md
  plan/PLAN.md
  tasks/T###-slug.md       base SHA, worktree, task branch, status
  review/…
  discuss/DIALOGUE.md       any-phase discussion transcript
  discuss/ANSWERS.md        durable discussion answers and decisions
  archive/<NNN>-slug>/     read-only shipped milestones
```

Full tree: [README.md](README.md#handoff-contract).

To resume: invoke the router. It reconciles STATE and task frontmatter,
reports position, and continues. **Do not hand-edit** task state or SHAs mid-pipeline.

If STATE and artifacts disagree, the router stops and asks rather than guessing.

---

## Standalone docs audit

`/gsd-path-docs-audit` runs between phases as a drift check. Findings get
verdicts and a remediation queue (`planned: no` until you fold them into a plan
or patch wave with approval). Never blocks the pipeline silently.

---

## Agent execution (how work is delegated)

Define and build orchestrators run in the main task. Researchers, deciders,
planners, coders, and reviewers use the host dispatch adapter installed with
your skills:

| Host | Child API | Notes |
| --- | --- | --- |
| Codex | collaboration | `default` / `worker` |
| Claude Code | `Agent` | `general-purpose` |
| Grok | `spawn_subagent` | |
| OpenCode | `Task` / v2 `subagent` | |
| Copilot CLI | `task` | |
| Qwen Code | `agent` | |
| Antigravity | `invoke_subagent` | |
| Cursor | `Task` | installed `gsd-path` subagent |
| Zed | `spawn_agent` | |
| Kiro | subagent facility | |
| Kimi | `Agent` | `coder` child type |

Independent briefs run in parallel up to child capacity; dependencies run in
layers. Every child brief names absolute input/output paths and bounded scope.

---

## Troubleshooting

| Symptom | What to do |
| --- | --- |
| Skills missing after install | Restart host session; [UPDATE.md](UPDATE.md) |
| Router blocked on branch | Check out `STATE.branch` or follow router instructions |
| Phase says precondition missing | Run the producing phase it names |
| Pipeline on unrelated work | Explicit invocation only — [DOCS.md](DOCS.md#faq) |
| Contradictory STATE / tasks | Re-invoke router; artifacts outrank chat |
| Archive tamper blocked | Expected with hooks — [HOOKS.md](HOOKS.md) |
| Upgrade skills or hooks | [UPDATE.md](UPDATE.md) |
| More help | [DOCS.md](DOCS.md#help) |

---

## Command reference

See [UPDATE.md](UPDATE.md) for updating. Install and hooks:

```bash
# Install
node scripts/install.mjs --all [--local] [--dry-run]
node scripts/install.mjs --claude --cursor --project /path/to/repo [--hooks]

# Update skills
node scripts/install.mjs --update [--local]

# Update hooks
node scripts/install.mjs --hooks-refresh --project /path/to/repo
node scripts/install.mjs --hooks-refresh-full --project /path/to/repo

# From npm (once the package is published to npm)
npx gsd-path --all
npx gsd-path@latest --update
```
