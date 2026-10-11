# GSD Path — Updating

Refresh skills, guard hooks, and project contracts after you upgrade GSD Path
or change how it is installed.

**Also see:** [DOCS.md](DOCS.md) (hub) · [QUICK.md](QUICK.md) (first install) · [HOOKS.md](HOOKS.md) (guards)

---

## When to use what

```text
Pulled new gsd-path / ran npx @opengsd/gsd-path@latest
└─ Skills feel stale or router shows old behavior?
   ├─ Global install     → install.mjs --update
   ├─ Project-local      → install.mjs --update --local  (from repo root)
   ├─ Project wiring     → install.mjs --update --project PATH  (refreshes the AGENTS.md block; keeps WORKFLOW.md and selected runtime)
   └─ npm only           → npx @opengsd/gsd-path@latest --update

Installed with --hooks and need to refresh wiring
└─ install.mjs --hooks-refresh --project PATH
   └─ Also refresh native settings / git hooks?
      → --hooks-refresh-full [--claude] [--codex] [--cursor]

Existing project needs guards for the first time
└─ install.mjs --hooks-init --claude --project PATH

AGENTS.md template changed upstream
└─ install.mjs --update --project PATH (replaces only the GSD Path block)

WORKFLOW.md template changed upstream
└─ Manual diff + merge (installer never overwrites)
```

**Rule:** run `--dry-run` before any update to preview changes.

---

## What auto-updates

| Component | Auto? | Command |
| --- | --- | --- |
| Global skills (`~/.claude/skills`, …) | Yes | `--update` |
| Project-local skills (`.cursor/skills`, …) | Yes | `--update --local` |
| `.gsd-path/guard_hook.py`, `git_guard.py` | Yes | `--hooks-refresh` or `--update --project PATH` |
| Project runtime | Explicit upgrade only | [Runtime lifecycle](DOCS.md#project-runtime-versions) |
| Native hook settings + git hooks | Yes | `--hooks-refresh-full` (host flag creates missing config) |
| Guards for an existing project | Yes | `--hooks-init` (preserves project contracts) |
| `AGENTS.md` GSD Path block | Yes | `--update --project PATH` (owner text outside the block is kept) |
| `WORKFLOW.md` | **No** | Manual merge |
| `.project/*` (active milestone) | **No** | Pipeline state |

Existing managed skills, including the owned `path` alias, move to
`disabled-gsd-skills` beside each root before replacement. The alias is owned
only when `scripts/pipeline_state.py` is a regular file and either `VERSION`
contains a dotted numeric version or, without a `VERSION` file, the runtime
contains `gsd-path project runtime`. An invalid `VERSION` is still refused.
An unrelated `path` skill blocks installation; rename
it or move it aside first. Unrelated skills are never touched. Failed multi-host
updates roll back all selected targets.
An initial `--hooks` install merges valid native settings for explicitly selected Claude,
Codex, or Cursor hosts; other existing project contract and guard files are refused.
`--update --project PATH` replaces the GSD Path block in `AGENTS.md`, keeps
`WORKFLOW.md` and `.claude/CLAUDE.md`, and refreshes managed hook wiring, native settings, and git hooks. For runtime
changes or legacy installations, follow the [runtime lifecycle](DOCS.md#project-runtime-versions).
Use `--hooks-init` to add guards to an existing project without changing its
`AGENTS.md` or `WORKFLOW.md`. It inspects and merges native configs only for
the selected hosts; configs for unselected hosts remain untouched.

### Local additions

Skill directories are managed. Updates and reinstalls replace existing managed
skills with fresh copies; edits and added files inside them stay only in the
backup described above. To recover your changes, diff each backed-up skill
against the same skill from the release you had installed. Comparing the backup
against the new install also includes upstream changes.

Put local rules in project-owned files instead. Add a `## Local rules`
section to `AGENTS.md` after the `<!-- gsd-path:end -->` line, with
subsections per phase if needed (for example, "Research: also read X").
Updates replace only the text between the GSD Path markers, and phase and
subagent briefs name `AGENTS.md`. Hosts load project instructions differently,
so confirm your host and its subagents read it. Keep owner rules after the
block: Codex reads only the first 32 KiB, so text above the block can push
GSD Path rules out.

Gates are scripts, not an extension point. To change a gate, open an issue.

---

## Update skills

### From a git clone

```bash
cd /path/to/gsd-path
git pull
node scripts/install.mjs --update --dry-run
node scripts/install.mjs --update
```

### From npm

```bash
npx @opengsd/gsd-path@latest --update --dry-run
npx @opengsd/gsd-path@latest --update
```

### Project-local only

```bash
cd /path/to/your/repo
node scripts/install.mjs --update --local
```

### Specific hosts only

```bash
node scripts/install.mjs --update --claude --cursor
```

`--update` only refreshes hosts that **already have** GSD Path installed.

### Legacy project runtime

The interactive npm installer detects the old `.gsd-path/runtime/` layout when
you choose to update project wiring. Choose **Migrate and continue upgrade** to
migrate first, then update skills and wiring. Cancelling leaves the installation
unchanged. See [Project runtime versions](DOCS.md#project-runtime-versions)
for migration safety checks and backups. Migration never stages or commits changes.

For unattended upgrades, migration requires explicit consent:

```bash
npx @opengsd/gsd-path@latest --update --runtime-migrate --project "/absolute/project" --dry-run
npx @opengsd/gsd-path@latest --update --runtime-migrate --project "/absolute/project"
```

The combined dry run previews migration only and writes nothing. The real command
migrates, then validates and applies the update. These are separate operations:
if the update fails, the completed migration remains as an unstaged Git diff.
Review it with `git status --short` and `git diff` in the project.

Migration is needed once per project. For later updates, omit `--runtime-migrate`.
For runtime selection after migration, see
[Project runtime versions](DOCS.md#project-runtime-versions).
Without migration consent, legacy project updates stop before writing files and
print the exact migration command.

### After updating

1. Restart your agent session (hosts reload skills on session start).
2. Invoke the router — should report the current phase or start define/inspect.
3. Optional: `ls ~/.claude/skills/gsd-path/SKILL.md` (adjust path for your host).

---

## Router update notice

Installed bundles include a `VERSION` stamp. The router may run `check_update.py`
once per conversation:

- Compares installed version to npm (24h cache, 3s timeout)
- Prints one line with update command if newer exists
- Silent on offline / unpublished / missing stamp — never blocks work

You can update proactively with [commands above](#update-skills) without waiting for the notice.

---

## Update the project runtime and guard hooks

The Dashboard's **Plugin → Watched projects → Runtime version** column shows
each project's installed runtime release. Global skill versions are separate;
a global update does not update project runtimes. Use the project's **Update**
button to refresh its runtime and existing guards. Install and update actions
show progress, success or failure, and installer output.

Project Update refreshes the daemon's plugin source first. With the
[git source](daemon/README.md#plugin-lifecycle), a clone that has local changes
is used as that local build, and the result says so. It does not pull remote
changes over local edits.

Older unstamped installs show **Unknown — version metadata unavailable**.
This does not establish that their runtime is outdated or broken. **Update**
uses the guarded migration for legacy runtime directories and an upgrade for
version-pinned runtimes. Migration leaves a reviewable Git diff; the dashboard
shows the failure reason when it stops.
See [Project runtime versions](DOCS.md#project-runtime-versions) for manual
migration and preview commands. Use `--doctor --project PATH` to check runtime files.

For upgrades, exact-version restoration, or legacy migration, follow
[Project runtime versions](DOCS.md#project-runtime-versions). To refresh hook wiring:

```bash
node scripts/install.mjs --hooks-refresh --project /path/to/repo
```

This refresh retains the selected runtime and leaves hookless installs hookless.
Guard files must contain `gsd-path guard`.

Include existing native settings and git hooks, and create missing settings for
explicitly selected hosts:

```bash
node scripts/install.mjs --hooks-refresh-full --codex --cursor --project /path/to/repo
```

A full refresh requires a working Python interpreter and an initialized Git
repository whose effective hooks directory can be resolved.

`--hooks-refresh-full` refreshes existing managed Claude, Codex, and Cursor
settings. A `--claude`, `--codex`, or `--cursor` flag also creates that host's
missing config or merges into its valid foreign JSON; unselected foreign
configs are rejected and left unchanged. Only the managed pre-tool guard entry
is refreshed. Other hook events, custom pre-tool entries, and settings keys are
preserved. Git hooks are refreshed in the repository's effective hooks
directory (`git rev-parse --git-path hooks`), so `core.hooksPath` setups and
linked worktrees are handled.

Details: [HOOKS.md](HOOKS.md)

---

## Update project contracts

GSD Path owns one marked block in `AGENTS.md`:

```text
<!-- gsd-path:begin -->
...GSD Path contract...
<!-- gsd-path:end -->
```

You own everything outside the markers. `--project` puts the block first in a
new or existing `AGENTS.md`; `--update --project PATH` replaces only the
block. Both refuse:

- a file with unmatched markers or more than one block (fix the markers by
  hand);
- a merged file over 32 KiB, because Codex reads only the first 32 KiB. The
  error prints the file, block, and merged sizes and a command to move the
  file aside.

Migration from whole-file installs (1.x): an `AGENTS.md` equal to a released
template becomes a block on the next `--project` or `--update --project`. An
edited whole-file `AGENTS.md` is refused with a diff: keep your rules, move
the file aside, rerun, then add your rules after the end marker.

`WORKFLOW.md` and `.claude/CLAUDE.md` (with Claude) are installed once with
`--project`. A plain install **refuses** if they already exist and prints a
command to move each to its `.pre-path.md` name. If that name is occupied, it
asks you to choose an unused name. `--update --project PATH` keeps them
unchanged.

To adopt upstream `WORKFLOW.md` changes:

1. Open new templates in the gsd-path repo or npm package
2. `diff` against your project copies
3. Merge manually
4. Follow the [runtime lifecycle](DOCS.md#project-runtime-versions) when adopting
   runtime changes. Use `--hooks-refresh-full` when host wiring needs a refresh.
5. Never delete active `.project/` milestone state

An in-flight milestone whose `INTENT.md` or `ROADMAP.md` predates `Surfaces:`
fails the plan and roadmap gates with `is missing Surfaces`. Add the field by
hand — `Surfaces: none` when nobody touches the work directly, otherwise the
surfaces it delivers, matching its roadmap entry. A milestone that names a
surface also needs PLAN.md's `## Surface contract`, which is a plan change:
reopen planning in patch mode rather than editing an approved plan in place.

Unrecognized or foreign `.project/` state is never auto-migrated — the router reports it and waits for explicit direction.

---

## Uninstall skills

```bash
npx @opengsd/gsd-path@latest --uninstall --all --dry-run
npx @opengsd/gsd-path@latest --uninstall --all
```

From a git clone, use `node scripts/install.mjs` with the same flags.

- Select the hosts with host flags or `--all`. A selection is necessary.
- Add `--local`, from the project directory, for project-local skills.
- `--dry-run` lists each path and removes nothing. A real run lists each
  removed path.
- A host that has no GSD Path skills shows `nothing to remove`. This is not an
  error. A second run removes nothing.

**Removed:** skill directories that GSD Path owns, and Cursor's
`agents/gsd-path.md`. A directory is owned when it has a GSD Path name
(`gsd-path`, `gsd-path-*`, the legacy `ogsd` names, or the `path` alias) and
contains a `VERSION` file or a `SKILL.md` that names `gsd-path`. The `path`
alias must also pass the ownership rule in
[What auto-updates](#what-auto-updates). A directory with a GSD Path name
that is not owned shows as `kept` and stays in place.

**Not removed:** other skills, host settings, `disabled-gsd-skills` backups,
and all project files: `.project/`, `.gsd-path/`, the `AGENTS.md` block, and
guard hooks. `--uninstall` with `--project`, `--update`, `--doctor`, or a hook
or runtime flag stops with an error.

Removal makes no backup. Changes that you made in a GSD Path skill directory
are lost. Codex, Zed, and Muse use one skills root (with `--local`, also
Antigravity): an uninstall for one of them removes the skills for all of them.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `no existing GSD Path skills found to update` | Run normal install first (`--all` or host flags) |
| Skills still old | Restart session; confirm root with `--update --dry-run` |
| Update rolled back | Read installer error; fix path overlap; retry |
| `--hooks-refresh` rejects an unmanaged guard | Move the foreign guard aside, then rerun refresh; use `--hooks-init` if guards are wanted |
| Runtime missing, invalid, or legacy | Follow [runtime restoration or migration](DOCS.md#project-runtime-versions) |
| Undo skill update | Copy from `disabled-gsd-skills` next to skills root |
| npm vs clone confusion | Pick one: `npx @opengsd/gsd-path@latest --update` **or** clone + `install.mjs --update` |
| Router still shows update line | Run update; or ignore — notice is informational |

Install issues (not updates): [QUICK.md](QUICK.md), [FULL.md](FULL.md), [DOCS.md](DOCS.md#help).

Installer help: `node scripts/install.mjs --help`
