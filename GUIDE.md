# GSD Path — How-To Guide

A practical walkthrough of using GSD Path from install to shipped milestone.
This is the "what you type and what you'll be asked" companion to
[README.md](README.md) (reference) and [WORKFLOW.md](WORKFLOW.md) (the
phase-by-phase contract agents follow).

## What it is, in one paragraph

GSD Path turns an idea into shipped code through gated phases: interview →
research → decisions → plan → parallel build → review → ship. Every phase
writes a fixed artifact under `.project/` in your repo, and every phase reads
only from disk — so you can close your session at any point and a fresh
session resumes exactly where you left off. You are the gate: nothing advances
past intent, plan, or review without your approval.

## 1. Install

From this repo (Node 18.17+; a Python equivalent lives at
`scripts/install.py`):

```bash
node scripts/install.mjs --all --dry-run
```

Review the preview, then apply:

```bash
node scripts/install.mjs --all
```

Or pick only the hosts you use:

```bash
node scripts/install.mjs --claude --codex
```

That installs globally (each host's user-level skills root). To install
into just one project instead, run from that project's directory with
`--local` — skills land in the per-host project directories
(`.claude/skills`, `.agents/skills`, `.cursor/skills`, …):

```bash
node scripts/install.mjs --all --local
```

To upgrade later, `--update` finds every root that already has the skills
and refreshes it in place (previous copies are kept in a
`disabled-gsd-skills` backup beside each root):

```bash
node scripts/install.mjs --update
```

Supported flags: `--codex`, `--claude`, `--grok`, `--opencode`, `--copilot`,
`--qwen`, `--antigravity`, `--cursor`, `--zed`, `--kiro`, `--kimi`. The installer
validates the package before writing, backs up any existing `gsd-path*` or
`ogsd*` skills, and rolls every selected host back if any one fails. Restart
your agent session afterward if the skills don't show up.

Starting a brand-new project? Install the shared project rules into it in the
same transaction:

```bash
node scripts/install.mjs --all --project /path/to/project
```

That writes `AGENTS.md` and `WORKFLOW.md` into the project (plus
`.claude/CLAUDE.md` when Claude is selected). It refuses to overwrite existing
managed files — merge upgrades by hand.

## 2. Start

Open your agent in the project directory and invoke the router explicitly:

- Codex: `$gsd-path`
- Claude Code, Grok, OpenCode v2, Copilot CLI, Qwen Code, Antigravity CLI,
  Cursor, Zed, Kiro: `/gsd-path`
- Stable OpenCode: ask it to "load and use the gsd-path skill"

The router never triggers on its own — saying "continue the project" without
the explicit invocation does nothing. It reads `.project/STATE.md` (if any),
reports where you are, and runs the next phase. That's the whole interface:
**invoke the router, answer its questions, approve its gates.** You can also
invoke a phase skill directly (e.g. `/gsd-path-plan`) when you deliberately
want just that phase; a direct run stops at its handoff instead of
auto-advancing.

### Greenfield (empty directory)

The router goes straight to the **grill** — an interview in the main chat.
Expect pointed questions across seven areas: the problem, the users, what
observable result means "done", smallest scope in, explicit scope out
(vetoes), constraints, and risks. It will chase contradictions and challenge
your core assumption; that's the job. It ends with a playback summary you
approve, producing `.project/intent/INTENT.md`. Vetoes recorded there are hard
limits for every later phase.

### Brownfield (existing code or docs)

The router detects existing work and runs **onboarding first**: two read-only
agents map what the code actually is and audit every Markdown doc against
reality (each claim gets a verdict — `verified`, `stale`, `aspirational`,
`unverifiable`). You then get ground truth on one screen before being asked
anything, and the grill only asks about deltas: this milestone's goal, what
changes, what must not break. Each doc-vs-code conflict gets your ruling —
`fix-doc`, `fix-code`, or `accept-drift`. Onboarding writes nothing outside
`.project/`.

## 3. Let the pipeline run

After intent is approved, the next phases are mostly autonomous; the router
walks them in order and stops at each gate:

| Phase | What happens | What you do |
| --- | --- | --- |
| Research | 4 parallel researchers gather evidence (domain, stack, pitfalls, similar projects) | Nothing, usually |
| Synthesize | Evidence becomes cited decisions with runners-up | Rule on anything marked `NEEDS-USER` |
| Plan | Work split into waves of task contracts; wave 1 burns down risky assumptions, wave 2 is the thinnest end-to-end slice | **Approve the wave summary** |
| Build | Parallel coders in isolated git worktrees, one task each, verified and integrated serially with atomic commits | Answer escalations, if any |
| Review | Per-wave reviews, then a final audit of every success criterion (`met` / `not-met` / `unverifiable`) plus cross-wave gap checks | Approve any patch wave the review demands |

Failed review findings don't get hand-waved: they become a user-approved
patch wave that goes back through the same build/review loop until the final
gate passes.

## 4. Ship

Passing the final gate triggers the archive automatically: everything except
`STATE.md` moves to `.project/archive/<NNN>-<slug>/` with a MANIFEST.md, in a
validated single ship commit. Archives are read-only history. The next
milestone starts clean — invoke the router again and it onboards against the
now-existing code.

## 5. Resume, anytime

Everything lives in `.project/` (see the handoff contract in
[README.md](README.md#handoff-contract)). To resume after a crash, a context
wipe, or a week away: invoke the router. It reads STATE.md, reconciles any
half-finished build state deterministically, and reports what's next. Never
edit `.project/` files by hand mid-pipeline — task frontmatter and recorded
SHAs are how recovery works.

## 6. Standalone docs audit

`gsd-path-docs-audit` (`/gsd-path-docs-audit`) also runs on its own between
phases as a drift check: does the project still do what its documents say?
It ends with a ruling walk over the findings; actionable rulings queue up
(`planned: no`) and the planner offers to absorb them — per item, with your
approval — either folded into the next plan or as a patch wave. The queue
never blocks the pipeline and never enters a plan unseen.

## Troubleshooting

- **Skills don't appear after install** — restart the host session.
- **Router says the branch is blocked/merged** — the build binds to one
  branch; check out the recorded `STATE.branch` or let the router report the
  mismatch and follow its instruction. Don't force it.
- **A phase says a precondition is missing** — it will route you to the phase
  that produces it; run that.
- **The pipeline injected itself into unrelated work** — it shouldn't: all
  skills are explicit-only. On hosts without a hard explicit-only switch
  (stable OpenCode, Antigravity CLI, Kiro), treat explicit invocation as an
  operating rule.
- **Something looks contradictory** (STATE vs BOARD vs task files) — artifacts
  and task frontmatter outrank summaries; the router reconciles on next
  invocation. If it can't, it stops and asks rather than guessing.
