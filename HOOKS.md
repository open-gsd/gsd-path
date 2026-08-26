# HOOKS.md — Deterministic Guard Hooks

Optional enforcement for two pipeline invariants prompt contracts cannot guarantee:

- committed `.project/archive/` trees stay read-only after ship
- destructive git commands (`reset --hard`, `clean -f`, force push, `branch -D`)
  do not break build recovery

**Docs:** [DOCS.md](DOCS.md) (hub) · [UPDATE.md](UPDATE.md) (refresh hooks) · [QUICK.md](QUICK.md) (first install with `--hooks`)

## When to install

| Situation | Recommendation |
| --- | --- |
| New repo running GSD Path with shipped archives | **Recommended** with `--project --hooks` |
| Solo experiment / no ship yet | Optional |
| Zed-only workflow | Git hooks still help; no pre-tool-use layer |
| Already shipped milestones you must not corrupt | **Recommended** |

Hooks are **opt-in** — add `--hooks` to a `--project` install. They do not replace
careful review; they block common accidental violations.

## Install

```bash
npx gsd-path --claude --project /path/to/repo --hooks
# or from clone:
node scripts/install.mjs --claude --project /path/to/repo --hooks
```

`--hooks` requires `--project`. Valid existing native settings for explicitly
selected Codex or Cursor hosts are merged, preserving unrelated settings and
hooks. Other target files are refused if they already exist:

| File | Purpose |
| --- | --- |
| `.gsd-path/guard_hook.py` | Pre-tool-use guard (stdin JSON → exit 2 + denial JSON) |
| `.gsd-path/git_guard.py` | Staged-path + ship-subject validator |
| `.git/hooks/pre-commit` | Runs `git_guard.py` before commit |
| `.git/hooks/commit-msg` | Runs `git_guard.py` with commit message |
| `.claude/settings.json` | Claude PreToolUse wiring (`claude` target) |
| `.codex/hooks.json` | Codex PreToolUse wiring (`codex` target) |
| `.cursor/hooks.json` | Cursor fail-closed preToolUse wiring (`cursor` target) |

Git hooks are written to the repository's **effective** hooks directory,
resolved with `git rev-parse --git-path hooks`. That honors `core.hooksPath`
setups (Husky and friends) and linked worktrees (where `.git` is a file). Only
when git itself is not runnable does the installer fall back to a plain
`.git/hooks` directory; if neither works, it reports that git hooks were
skipped instead of dropping them silently.

Git hooks work for **any** agent that commits. Native guard wiring denies a tool
call when its event is malformed or the guard cannot validate it.

**Windows / interpreter caveat:** hooks and native host settings invoke a
Python interpreter that the installer probes at install time — `python3` first,
then `python` (plain `python3` usually does not exist on Windows). If neither
runs, hook install is skipped with a warning rather than wiring an interpreter
that would make every commit fail. The `sh` hook scripts themselves need a
POSIX shell (Git for Windows provides one).

### Updating after package upgrade

```bash
npx gsd-path --hooks-refresh --project /path/to/repo
npx gsd-path --hooks-refresh-full --project /path/to/repo   # + settings/git hooks
```

`--hooks-refresh-full` refreshes existing managed `.claude/settings.json`,
`.codex/hooks.json`, and `.cursor/hooks.json`. Add `--claude`, `--codex`, or
`--cursor` to create a missing config or merge the guard into that selected
host's valid existing JSON. Unselected foreign configs are not changed. The
merge replaces only managed guard entries and preserves unrelated entries,
hook events, and settings. Codex resolves the guard from the Git root; Cursor
runs its project hook from the project root, so both configs remain valid after
a clone or move.

See [UPDATE.md](UPDATE.md).

## What gets blocked

**`guard_hook.py`** (pre-tool-use):

- non-read tools targeting paths under `.project/archive/` (including `..` paths)
- `git reset --hard`, `git clean -f`, force push, `git branch -D`
- `cp`, `tee`, `git checkout`/`restore` into archive
- `rm`, `mv`, redirects into archive

Read tools (`Read`, `Grep`, `View`, …) may still open archive paths.

**`git_guard.py`** (pre-commit + commit-msg):

- modifies, deletes, or renames away tracked archive paths
- `ship:` commits (case-insensitive) staging paths outside `.project/`
- **allows** adding files to archive (ship transaction)

## Wire other hosts

Claude, Codex, and Cursor wiring is installed automatically when that target is
selected. Register `python3 .gsd-path/guard_hook.py` as a pre-tool-use hook on
the remaining hosts:

| Host | Where | Docs |
| --- | --- | --- |
| Copilot CLI | `.github/hooks/*.json` `preToolUse` | [Copilot hooks](https://docs.github.com/en/copilot/concepts/agents/hooks) |
| Grok | reads `.claude/settings.json` — covered if Claude wiring installed | [Grok hooks](https://docs.x.ai/build/features/hooks) |
| Qwen Code | `.qwen/settings.json` `PreToolUse` | [Qwen hooks](https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/) |
| Kimi CLI | `~/.kimi-code/config.toml` `PreToolUse` | [Kimi hooks](https://moonshotai.github.io/kimi-code/en/customization/hooks.html) |
| Kiro CLI | agent config `preToolUse` | [Kiro hooks](https://kiro.dev/docs/cli/hooks/) |
| Antigravity | `.agents/hooks.json` `PreToolUse` | [Antigravity hooks](https://antigravity.google/docs/hooks) |
| OpenCode | JS plugin `tool.execute.before` | [OpenCode plugins](https://opencode.ai/docs/plugins/) |
| Zed | no hook API — git hooks only | — |

**Caveats:** Grok and Kimi fail-open on hook errors by design. Copilot, Kimi,
Kiro, and Antigravity may not intercept subagent tools — treat coverage as
orchestrator-level.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Commit blocked on archive edit | Expected — ship adds to archive; edits after ship are forbidden |
| `ship:` commit blocked with `app.py` staged | Ship commits may only touch `.project/` |
| Tool denied editing archive | Pre-tool guard — use active paths, not archive |
| Hook not running in Cursor | Run `--hooks-refresh-full --cursor --project /path/to/repo` |
| `--hooks-refresh` rejected | Scripts not from prior `--hooks` install |

More: [DOCS.md](DOCS.md#help) · [UPDATE.md](UPDATE.md)
