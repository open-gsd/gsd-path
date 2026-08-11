# GSD Path — Updating

Refresh skills, guard hooks, and project contracts after you upgrade GSD Path
or change how it is installed.

**Also see:** [DOCS.md](DOCS.md) (hub) · [QUICK.md](QUICK.md) (first install) · [HOOKS.md](HOOKS.md) (guards)

---

## When to use what

```text
Pulled new gsd-path / ran npx gsd-path@latest
└─ Skills feel stale or router shows old behavior?
   ├─ Global install     → install.mjs --update
   ├─ Project-local      → install.mjs --update --local  (from repo root)
   └─ npm only           → npx gsd-path@latest --update

Installed with --hooks and upgraded guard scripts
└─ install.mjs --hooks-refresh --project PATH
   └─ Also refresh Claude settings / git hooks?
      → --hooks-refresh-full

AGENTS.md or WORKFLOW.md template changed upstream
└─ Manual diff + merge (installer never overwrites)
```

**Rule:** run `--dry-run` before any update to preview changes.

---

## What auto-updates

| Component | Auto? | Command |
| --- | --- | --- |
| Global skills (`~/.claude/skills`, …) | Yes | `--update` |
| Project-local skills (`.cursor/skills`, …) | Yes | `--update --local` |
| `.gsd-path/guard_hook.py`, `git_guard.py` | Yes | `--hooks-refresh` |
| Claude hook settings + git hooks | Yes | `--hooks-refresh-full` |
| `AGENTS.md`, `WORKFLOW.md` | **No** | Manual merge |
| `.project/*` (active milestone) | **No** | Pipeline state |

Existing `gsd-path*` skills move to `disabled-gsd-skills` beside each root before replace.
Unrelated skills are never touched. Failed multi-host updates roll back all selected targets.

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
npx gsd-path@latest --update --dry-run
npx gsd-path@latest --update
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

## Update guard hooks

If you used `--hooks` on install:

```bash
node scripts/install.mjs --hooks-refresh --project /path/to/repo
```

Overwrites managed `.gsd-path/*.py` (must contain `gsd-path guard` marker).

Include Claude settings and git hooks:

```bash
node scripts/install.mjs --hooks-refresh-full --project /path/to/repo
```

Details: [HOOKS.md](HOOKS.md)

---

## Update project contracts

`AGENTS.md` and `WORKFLOW.md` are installed once with `--project`. The installer
**refuses** if they already exist.

To adopt upstream template changes:

1. Open new templates in the gsd-path repo or npm package
2. `diff` against your project copies
3. Merge manually
4. Never delete active `.project/` milestone state

Unrecognized or foreign `.project/` state is never auto-migrated — the router reports it and waits for explicit direction.

---

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `no existing GSD Path skills found to update` | Run normal install first (`--all` or host flags) |
| Skills still old | Restart session; confirm root with `--update --dry-run` |
| Update rolled back | Read installer error; fix path overlap; retry |
| `--hooks-refresh` rejected | Files must be from prior `--hooks` install |
| Undo skill update | Copy from `disabled-gsd-skills` next to skills root |
| npm vs clone confusion | Pick one: `npx gsd-path@latest --update` **or** clone + `install.mjs --update` |
| Router still shows update line | Run update; or ignore — notice is informational |

Install issues (not updates): [QUICK.md](QUICK.md), [FULL.md](FULL.md), [DOCS.md](DOCS.md#help).

Installer help: `node scripts/install.mjs --help`
