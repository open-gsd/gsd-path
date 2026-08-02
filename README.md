# GSD Path

A disk-backed project pipeline for AI coding agents. It supports Codex, Claude
Code, Grok, OpenCode, GitHub Copilot CLI, Qwen Code, Antigravity CLI, Cursor,
Zed, and Kiro. It turns a raw idea into shipped code through six gated phases.
Each phase writes a fixed artifact that the next phase reads, so a fresh task
can resume from `.project/` alone.

New here? Read [GUIDE.md](GUIDE.md) for the install-to-ship walkthrough.

## The flow

```text
gsd-path  (router: detects project state, then runs the next phase)
  |
  |-- 0. gsd-path-onboard     brownfield scan + audit  -> research/evidence-codebase.md
  |                                                   research/DOCS-AUDIT.md
  |-- 1. gsd-path-grill       interactive intent       -> intent/INTENT.md
  |-- 2. gsd-path-research    4 evidence researchers   -> research/evidence-*.md
  |-- 3. gsd-path-synthesize  evidence to decisions    -> research/SYNTHESIS.md
  |-- 4. gsd-path-plan        waves and task contracts -> plan/PLAN.md + tasks/T*.md
  |-- 5. gsd-path-build       parallel coder agents    -> code, commits, BOARD.md
  `-- 6. gsd-path-review      wave and final gates     -> review/*.md
```

Invoke the router as `$gsd-path` in Codex and `/gsd-path` in Claude Code, Grok,
OpenCode v2, GitHub Copilot CLI, Qwen Code, Antigravity CLI, Cursor, Zed, or
Kiro. In stable OpenCode, explicitly ask it to load and use the `gsd-path`
skill. The shared Codex/Zed bundle keeps its installed skill text
syntax-neutral while each host UI exposes its own invocation form. The router
reports the current state and continues the pipeline. Invoke a phase skill
directly, such as `$gsd-path-plan` or `/gsd-path-plan`, when you intentionally
want that phase. A direct phase run stops at its handoff; explicitly invoke the
router or named next phase to continue. Only an active router may auto-advance
through its bundled phase contracts.
All nine skills request explicit-only invocation, so generic requests such as
"continue the project" do not inject this pipeline accidentally. Codex,
Claude Code, Grok, OpenCode v2, GitHub Copilot CLI, Qwen Code, Cursor, and Zed
enforce that request in host metadata. Stable OpenCode, Antigravity CLI, and
Kiro do not expose a documented hard explicit-only gate; their limitations are
documented under Install.
The router carries synchronized copies of all eight phase contracts, so an
explicit router invocation can auto-advance without relying on hidden phase skills
being present in the ordinary catalog.

With no `.project/STATE.md`, the router detects the project kind before
asking anything. Existing code or docs → brownfield: `gsd-path-onboard` maps
the codebase and audits every Markdown doc against reality, presents ground
truth, then the grill asks only delta questions. Empty directory →
greenfield: straight to the grill. `gsd-path-docs-audit` also runs standalone
at the safe pre-build checkpoints documented by that skill.

## Agent execution

The grill and build orchestrator run in the main task. Researchers,
synthesizer, planner, coders, and reviewers use a host-specific dispatch
adapter installed with each skill bundle:

| Host | Child-agent API | Built-in child |
| --- | --- | --- |
| Codex | collaboration | `default` / `worker` |
| Claude Code | `Agent` | `general-purpose` |
| Grok | `spawn_subagent` | `general-purpose` |
| OpenCode | `Task` or v2 `subagent` | `general` |
| GitHub Copilot CLI | `task` | `general-purpose` |
| Qwen Code | `agent` | `general-purpose` |
| Antigravity CLI | `invoke_subagent` | `self` |
| Cursor | `Task` | installed `gsd-path` custom subagent |
| Zed | `spawn_agent` | isolated full-capability child |
| Kiro | subagent facility | default general-purpose child |

No manual custom-agent registration is required; the installer supplies
Cursor's required `gsd-path` child. Independent briefs run in parallel up to
the available child capacity; larger fan-outs run in batches.
Dependencies run in layers. A spawned agent has isolated context, so every
brief names its input paths, output path, acceptance contract, and allowed
scope. Durable context belongs in `.project/`, not chat history.

### Platform adapters

`platforms/` is build-time compatibility source for the installer, not a set
of skills users invoke directly. It keeps the shared workflow independent of
each host's child-agent tool names and schemas.

- `platforms/<host>/dispatch.md` maps GSD Path delegation onto that host's
  child API, including isolation, concurrency, retry, and resume behavior.
- `platforms/shared-agents/dispatch.md` safely selects among Codex, Zed, Grok,
  OpenCode, Cursor, and Copilot when they discover `~/.agents/skills`.
- `platforms/cursor/agent.md` defines the full-capability `gsd-path` child that
  Cursor requires; the installer places it beside Cursor's installed skills.

The installer stages the canonical skills, replaces each staged
`references/dispatch.md` with the selected adapter, and applies host-specific
invocation metadata. It does not install the `platforms/` directory wholesale.

## Handoff contract

```text
.project/
  STATE.md                    pipeline owner, phase, branch, archive transaction
  intent/INTENT.md            approved intent, constraints, and vetoes
  research/
    evidence-codebase.md      brownfield ground truth (onboard)
    DOCS-AUDIT.md             doc-vs-code verdicts and remediation queue
    evidence-domain.md        domain rules and prior art
    evidence-stack.md         stack choices and tradeoffs
    evidence-pitfalls.md      risks and failure modes
    evidence-similar.md       comparable projects
    SYNTHESIS.md              fully gated decisions and planner brief
  plan/PLAN.md                waves, dependency graph, project verify
  tasks/T###-slug.md          task contract, clean base, state, exact commit
  BOARD.md                    build and escalation summary
  review/wave-N.cycleC.md     wave review verdicts
  review/final-gap-N.md       cross-wave gap verdicts
  review/FINAL.md             success-criteria audit (`met` / `not-met` / `unverifiable`)
  archive/<NNN>-<slug>/       shipped milestones, moved here at ship (read-only)
```

Shipping archives the milestone: every artifact above (except `STATE.md`)
moves into a numbered `archive/` directory with a MANIFEST.md, so the next
milestone starts clean instead of overwriting history.

## Install

The dependency-free installer validates the synchronized package before it
writes anything. Preview an all-host install, then apply it:

```bash
node scripts/install.mjs --all --dry-run
node scripts/install.mjs --all
```

Install only selected hosts by combining their flags:

```bash
node scripts/install.mjs --codex --claude --cursor
```

The installer needs Node 18.17+ and, when published to npm, also runs as
`npx gsd-path --all`. `scripts/install.py` is the equivalent Python
installer for global installs — identical validation, transactions, and
results; the `--local` mode and interactive output below are Node-only.

### Global or per-project

The default is a global install into each host's user-level skills root
(table below). Add `--local` to instead install into the current project's
documented per-host skill directories:

```bash
node scripts/install.mjs --all --local
```

| Host | Project skills root |
| --- | --- |
| Codex, Zed | `.agents/skills` (one shared bundle) |
| Claude Code | `.claude/skills` |
| Grok | `.grok/skills` |
| OpenCode | `.opencode/skills` |
| GitHub Copilot CLI | `.github/skills` |
| Qwen Code | `.qwen/skills` |
| Cursor | `.cursor/skills` (+ subagent at `.cursor/agents/gsd-path.md`) |
| Kiro | `.kiro/skills` |

Antigravity also reads the project `.agents/skills` directory; when Codex or
Zed is selected alongside it, the installer skips Antigravity's own bundle
and notes that the shared one covers the path. `--local` never touches the
legacy `~/.codex` migration. Per-target `--<target>-root` overrides win over
both modes.

### Updating

`--update` refreshes existing installs in place. It detects which hosts
already have GSD Path skills — global roots by default, the current
project's roots with `--local` — and reruns the transactional install for
exactly those, leaving uninstalled hosts untouched. Each replaced copy
lands in that root's `disabled-gsd-skills` backup.

```bash
node scripts/install.mjs --update
node scripts/install.mjs --update --local
```

Running from npm, `npx gsd-path@latest --update` fetches and applies the
newest published version; from a clone, `git pull` first. Add target flags
to narrow the update, or `--dry-run` to preview it.

Installed routers also surface updates on their own: both installers stamp
the package version into `gsd-path/VERSION`, and the router's status report
runs the bundled `scripts/check_update.py` once per conversation. The check
compares the stamp against the npm registry with a 24-hour cache and a
3-second timeout, prints at most one notice line with the update command,
and stays silent on any failure (offline, unpublished, no stamp) so it can
never block routing.

| Flag | Native user skill root | Explicit invocation |
| --- | --- | --- |
| `--codex` | `~/.agents/skills` | `$gsd-path` |
| `--claude` | `${CLAUDE_CONFIG_DIR:-~/.claude}/skills` | `/gsd-path` |
| `--grok` | `${GROK_HOME:-~/.grok}/skills` | `/gsd-path` |
| `--opencode` | `${OPENCODE_CONFIG_DIR:-${XDG_CONFIG_HOME:-~/.config}/opencode}/skills` | `/gsd-path` on v2; request the skill on stable |
| `--copilot` | `${COPILOT_HOME:-~/.copilot}/skills` | `/gsd-path` |
| `--qwen` | `${QWEN_HOME:-~/.qwen}/skills` | `/gsd-path` |
| `--antigravity` | `~/.gemini/antigravity-cli/skills` | `/gsd-path` |
| `--cursor` | `~/.cursor/skills` | `/gsd-path` |
| `--zed` | `~/.agents/skills` | `/gsd-path` |
| `--kiro` | `${KIRO_HOME:-~/.kiro}/skills` | `/gsd-path` |

These defaults follow the current host documentation for
[Codex](https://learn.chatgpt.com/docs/build-skills),
[Claude Code](https://code.claude.com/docs/en/slash-commands),
[Grok](https://docs.x.ai/build/features/skills-plugins-marketplaces), and
[OpenCode](https://opencode.ai/docs/skills), plus the published guidance for
[GitHub Copilot CLI](https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-command-reference),
[Qwen Code](https://qwenlm.github.io/qwen-code-docs/en/users/features/skills/),
[Antigravity CLI](https://antigravity.google/docs/gcli-migration),
[Cursor](https://cursor.com/docs/skills.md),
[Zed](https://zed.dev/docs/ai/skills), and
[Kiro](https://kiro.dev/docs/cli/skills/).

Each physical target receives compatible dispatch and invocation metadata.
Existing `ogsd*` and `gsd-path*` entries move to a uniquely named recoverable
backup; unrelated skills are untouched. The Codex migration also backs up
copies under the former `${CODEX_HOME:-~/.codex}/skills` location. A
multi-host failure rolls every selected target back. Codex and Zed share
`~/.agents/skills`, so `--all` prepares and commits that physical root once
with their shared, syntax-neutral bundle instead of running two competing
transactions. Grok, OpenCode, Cursor, and Copilot may also discover that
compatibility root, so the shared bundle selects each host's documented child
schema at runtime; dedicated host roots still receive narrower adapters.

The Cursor target also installs a model-inheriting `gsd-path` subagent at
`~/.cursor/agents/gsd-path.md` (or beside an overridden Cursor skills root).
That file participates in the same backup and rollback transaction as the
Cursor skills.

Stable OpenCode discovers the installed skills through its `skill` tool but
does not document a slash command or hard explicit-only switch. Ask it to load
and use `gsd-path` explicitly. [OpenCode
v2](https://opencode.ai/v2/docs/skills) honors the installer's
`opencode/autoinvoke: "false"` metadata and exposes `/gsd-path`.
Antigravity CLI and Kiro expose `/gsd-path`, but neither documents a hard
host-level switch that prevents implicit skill selection. Treat explicit
invocation as an operating rule on those hosts. Codex, Claude Code, Grok,
OpenCode v2, GitHub Copilot CLI, Qwen Code, Cursor, and Zed enforce
explicit-only invocation with native metadata.

For a brand-new project, install the shared project contracts in the same
transaction:

```bash
node scripts/install.mjs --all --project /path/to/project
```

This writes `AGENTS.md` and `WORKFLOW.md`; when Claude is selected it also
writes `.claude/CLAUDE.md` that imports both. If any managed contract already
exists, the installer stops before changing any host. For an upgrade, review
and merge the new rules explicitly instead of overwriting project-specific
instructions. Pre-marker state is not auto-stamped as v1 because its branch,
worktree, and archive identity cannot be reconstructed safely.

Restart active host sessions if the new skills do not appear, then invoke the
router explicitly.

## Repository layout

- `skills/` — the nine canonical `gsd-path*` skills
- `platforms/` — installer-only host dispatch adapters and Cursor child definition
- `skills/gsd-path/templates/` — canonical artifact formats
- `skills/gsd-path/references/` — canonical role and dispatch contracts
- `scripts/install.mjs` — safe multi-host installer (Node, npm `gsd-path` bin)
- `scripts/install.py` — the same installer in Python
- `scripts/sync_skill_resources.py` — refreshes/checks phase resources and router contracts
- `scripts/archive_milestone.py` — prepares and validates the ship transaction
- `GUIDE.md` — install-to-ship how-to walkthrough
- `AGENTS.md` — shared operating rules to install in the project root
- `WORKFLOW.md` — phase-by-phase SOP to install in the project root
- `LICENSE` — MIT
