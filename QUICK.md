# GSD Path — Quick Start

**~5 minutes to installed and running.**

| More | Doc |
| --- | --- |
| Hub (install · use · understand · update) | [DOCS.md](DOCS.md) |
| Full walkthrough | [FULL.md](FULL.md) |
| Upgrading | [UPDATE.md](UPDATE.md) |

## What you get

One router skill drives a gated pipeline: inspect → define → research → decide →
plan → build → ship. Every handoff lives in `.project/` so any session can resume from disk.

**Hosts:** Codex, Claude Code, Grok, OpenCode, Copilot CLI, Qwen, Antigravity,
Cursor, Zed, Kiro, Kimi Code.

---

## Checklist

```text
[ ] 1. Install skills (step 1)
[ ] 2. Install project rules in your repo (step 2) — skip if repo already has AGENTS.md
[ ] 3. Restart agent session
[ ] 4. Open repo in agent; invoke router (step 3)
[ ] 5. Approve gates as they appear (step 4)
```

---

## 1. Install skills

**Node 18.17+. Project installs in step 2 also require Python 3.9+.** Preview
first (never writes files):

```bash
# From a clone of this repository (primary path)
node scripts/install.mjs --all --dry-run
node scripts/install.mjs --all

# From npm, no clone required
npx @opengsd/gsd-path --all --dry-run
npx @opengsd/gsd-path --all
```

Only hosts you use:

```bash
node scripts/install.mjs --claude --cursor
```

Team pins skills in the repo? See [DOCS.md — Installing](DOCS.md#installing) (`--local`).

---

## 2. Install project rules

From your repo:

```bash
cd /path/to/your/repo
node scripts/install.mjs --all --project "$(pwd)"
```

Installs `AGENTS.md`, `WORKFLOW.md`, and `.gsd-path/runtime/`
(+ `.claude/CLAUDE.md` if Claude is selected).
If those managed files already exist, a plain install **refuses and installs
nothing** — use `--update --project PATH` to refresh skills and `.gsd-path/`
while keeping your contracts, and merge project-contract changes by hand
([UPDATE.md](UPDATE.md)).

**Optional** archive/git guards:

```bash
node scripts/install.mjs --claude --project "$(pwd)" --hooks
```

[HOOKS.md](HOOKS.md)

---

## 3. Invoke the router

In the **project directory**, type explicitly:

Use the [router and phase invocation table](README.md#install-summary) for your host.

For plain prompts such as “continue the project,” see the
[invocation and handoff rules](README.md#the-flow).

**One phase only?** e.g. `/gsd-path-plan` — see skill table in [DOCS.md](DOCS.md#using).
Need to talk through a question without advancing? Use `/gsd-path-discuss`;
Codex invokes it as `$gsd-path-discuss`.

---

## 4. Approve gates

| When | You |
| --- | --- |
| Define | Answer; approve playback |
| Decide | Resolve `NEEDS-USER` |
| Plan | **Approve wave summary** before build |
| Build | Escalations only |
| Ship | Approve patch waves if blocked; approve archive and ship when green |

---

## 5. Resume

Invoke the router again. Don’t hand-edit `.project/` mid-run.

---

## Later

```bash
node scripts/install.mjs --update                           # refresh skills
node scripts/install.mjs --update --project "$(pwd)"        # refresh .gsd-path/; keeps contracts
node scripts/install.mjs --hooks-refresh --project "$(pwd)"  # guard scripts
```

[UPDATE.md](UPDATE.md)

---

## Phase map

```text
inspect (brownfield) → define → research → decide → plan → build → ship
```

Artifacts: [README.md](README.md#handoff-contract)

---

## Quick troubleshooting

| Issue | Fix |
| --- | --- |
| Skills missing | Restart agent session |
| Router idle or plain prompt only reports status | Use `$gsd-path` or `/gsd-path` explicitly |
| Install failed | Read error; try `--dry-run` |
| Need more detail | [DOCS.md](DOCS.md) or [FULL.md](FULL.md) |
