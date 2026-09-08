# HOOKS.md — Deterministic Guard Hooks

Optional enforcement for pipeline invariants prompt contracts cannot guarantee:

- committed `.project/archive/` trees stay read-only after ship
- destructive Git operations do not erase recovery state, untracked evidence,
  or protected refs
- direct product-file writes do not bypass a routed non-build phase

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

For a project that already has `AGENTS.md` and `WORKFLOW.md`, initialize only
the guards and keep those contracts unchanged:

```bash
npx gsd-path --hooks-init --claude --project /path/to/repo
```

`--hooks` requires `--project`. Valid existing native settings for explicitly
selected Claude, Codex, or Cursor hosts are merged, preserving unrelated
settings and hooks. Other target files are refused if they already exist.

`--hooks-init` also requires `--project` plus at least one host flag or `--all`.
It creates the managed guard scripts, merges selected native settings, and
installs Git hooks without reading or writing existing project contracts.
Native configs for unselected hosts are ignored.

| File | Purpose |
| --- | --- |
| `.gsd-path/guard_hook.py` | Pre-tool-use guard (stdin JSON → exit 2 + denial JSON) |
| `.gsd-path/git_guard.py` | Commit and publication validator |
| `.gsd-path/runtime/` | Canonical read-only state validation and routing used for plain-prompt re-entry |
| `.git/hooks/pre-commit` | Runs `git_guard.py` before commit |
| `.git/hooks/commit-msg` | Runs `git_guard.py` with commit message |
| `.git/hooks/pre-push` | Runs `git_guard.py` on every pushed ref update |
| `.claude/settings.json` | Claude PreToolUse wiring (`claude` target) |
| `.codex/hooks.json` | Codex PreToolUse wiring (`codex` target) |
| `.cursor/hooks.json` | Cursor fail-closed preToolUse wiring (`cursor` target) |

Git hooks are written to the repository's **effective** hooks directory,
resolved with `git rev-parse --git-path hooks`. That honors `core.hooksPath`
setups (Husky and friends) and linked worktrees (where `.git` is a file).
Every selected host requires an initialized repository with a resolvable hooks
directory; otherwise installation stops before writing.

Git hooks work for **any** agent that commits. Native guard wiring denies a tool
call when its event is malformed or the guard cannot validate it.

Codex [project hooks](https://learn.chatgpt.com/docs/hooks) are installed but do
not run until Codex trusts the project `.codex/` layer and the exact hook
definition. Open `/hooks` in Codex, review both, and trust them. Until that
manual activation is complete, Codex's guaranteed manifest tier is `git-only`;
changing the hook requires review again.

**Windows / interpreter caveat:** hooks and native host settings invoke a
Python interpreter that the installer probes at install time — `python3` first,
then `python` (plain `python3` usually does not exist on Windows). If neither
runs, hook installation stops before writing instead of pinning a missing
interpreter. The `sh` hook scripts themselves need a POSIX shell (Git for
Windows provides one).

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
a clone or move. A full refresh requires the same working interpreter and
resolved Git hooks directory as the initial install.

See [UPDATE.md](UPDATE.md).

## What gets blocked

**`guard_hook.py`** (pre-tool-use):

- non-read tool actions targeting archived paths or an existing ancestor of
  the archive tree; shell operands count an ancestor only for deletion or move
  commands
- `git reset --hard`, destructive `git clean` modes, force pushes (including
  `+` refspecs), destructive branch or ref deletion, `git branch -m`,
  `git worktree remove --force`, `git stash drop`/`clear`, and whole-tree
  `git checkout -- .`/`git restore .`
- shell writes (redirections, `tee`, `cp`, `mv`, `rm`, `sed -i`, ...) that
  target a routing control (`.git`, `.project/STATE.md`, `.project/next`,
  `.gsd-path`) while `.project/STATE.md` exists
- shell commands that reference the archive unless the whole command is a
  recognized standalone read or a single-command invocation of the bundled
  `pipeline_state.py` / `archive_milestone.py` helper whose entry script and every
  Python sibling with a guard-owned runtime counterpart are byte-identical to
  those copies, with no extra Python sibling shadowing an import in either
  helper's transitive runtime import closure; supplied tool working directories
  are authoritative, and cwd is used only when none are supplied
- deletion or move commands outside a single simple segment, including command
  chains, pipes, newlines, grouping, directory changes, and command substitution
- deletion or move commands with any argument outside the literal-path character
  set: ASCII letters, digits, `.`, `_`, `-`, and `/` (plus a drive prefix and
  backslashes on Windows). One matching pair of surrounding quotes is allowed;
  spaces, parameters, wildcards, braces, and tilde paths are denied even when
  quoted. This also applies to `find -delete` and supported destructive aliases
- destructive Git commands nested in supported shell and command wrappers
- archive glob/brace expansions and execution-capable read options such as
  `rg --pre`
- direct write, edit, and patch tool calls that target product files while the
  deterministic route is outside build

Read tools (`Read`, `Grep`, `View`, …) may still open archive paths.

A working directory is archive context only when it is inside an archive.
Merely containing `.project/archive/` does not put the repository root in
archive context: `echo guard-probe`, `python3 -m unittest`, and the archive
helper with `--repo <root>` remain allowed by the archive guard. Deleting an
archive ancestor, such as `rm -rf .project`, remains blocked. A simple command
such as `rm -rf scratch` passes the archive check; other guard rules still apply.

**`git_guard.py`** (pre-commit + commit-msg + pre-push):

- modifies, deletes, or renames away tracked archive paths
- `ship:` commits (case-insensitive) staging paths outside `.project/`
- on unshipped pipeline lineage (the committed `STATE.md` names a bound
  `gsd-path/M###` branch that is not `shipped/done`, and HEAD descends from
  it — the bound branch itself, `gsd-path-task/` branches, sidecars, and any
  branch cut from them): commits staging paths outside `.project/` (or the
  guard's own `.gsd-path/` and native hook settings) unless the phase is
  `build` and they are landing commits as `isolation.py land` writes them —
  subject `<task id>: <task title>` matching the task file at `Base:`, a full
  base SHA HEAD descends from, the staged task file, only that task's declared
  `files:`, and a `Files:` list of exactly the staged paths. Outside build the
  reviewed HEAD is frozen; product fixes reopen through the patch plan
- pushes (to any remote) that move a `gsd-path/M###` ref anywhere but its
  strict ship commit, or delete it while it holds anything else; and pushes of
  any other ref whose commit carries a `STATE.md` that still owes a ship commit
  (names a bound branch, not `shipped/done`). The ship state's `branch` must
  match every bound name in the local and remote refs. Malformed pre-push
  records and failed object inspection block the push; a present commit
  without `STATE.md` passes on an ordinary ref. An absent bound ref passes
  deletion. The authorized publisher is `archive_milestone.py integrate`;
  the hook checks ref updates, not which client initiated them
- **allows** adding files to archive (ship transaction)

These local hooks cover pushes made by plain Git and clients that invoke
Git with hooks enabled. Creating a PR from an already published ref does not
run the pre-push hook. A branch cut from `main` carrying `shipped/done` passes;
if `main` instead carries an unshipped bound state, pushes of branches carrying
that state remain blocked until the milestone records are repaired through the
pipeline.

## GitHub-side gate

The guards above stop agents on the developer machine. A person can still
merge a pull request from a bound branch in the GitHub UI. To surface that on
the pull request, add a job to the consumer repository's pull-request workflow
that fails unless a `gsd-path/M*` head is the ship commit at `shipped/done`:

```yaml
  gsd-path-ship-gate:
    if: startsWith(github.head_ref, 'gsd-path/M')
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
      - run: |
          gsd_phase=$(sed -n 's/^phase: *\([a-z]*\).*/\1/p' .project/STATE.md | head -1)
          gsd_status=$(sed -n 's/^status: *\([a-z]*\).*/\1/p' .project/STATE.md | head -1)
          state="$gsd_phase/$gsd_status"
          subject=$(git log -1 --format=%s)
          case "$subject" in "ship: M"*) ship=1 ;; *) ship=0 ;; esac
          [ "$state" = shipped/done ] && [ "$ship" = 1 ] && exit 0
          echo "::error::gsd-path: head is $state with subject '$subject'; a gsd-path/M* branch reaches main only through archive_milestone.py integrate"
          exit 1
```

The job is advisory until branch protection or a ruleset requires it, which
GitHub offers on public repositories and paid plans.

## Wire other hosts

Claude, Codex, and Cursor wiring is installed automatically when that target is
selected. The installer does **not** install a native guard for any other host,
even where the host has a pre-tool-use API: those hosts are `git-only` in the
manifest and stay `git-only` after manual wiring, because the installer neither
writes nor verifies that wiring. To add it yourself, register
`python3 .gsd-path/guard_hook.py` as a pre-tool-use hook:

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

**Caveats:** The hook cannot prove which skill initiated a shell command or a
build-phase edit, so AGENTS.md owns those re-entry cases. Grok and Kimi
fail-open on hook errors by design. Copilot, Kimi, Kiro, and Antigravity may
not intercept subagent tools — treat coverage as orchestrator-level.

## Troubleshooting

| Symptom | Likely cause |
| --- | --- |
| Commit blocked on archive edit | Expected — ship adds to archive; edits after ship are forbidden |
| `ship:` commit blocked with `app.py` staged | Ship commits may only touch `.project/` |
| Tool denied editing archive | Pre-tool guard — use active paths, not archive |
| Hook not running in Cursor | Run `--hooks-refresh-full --cursor --project /path/to/repo` |
| `--hooks-refresh` rejects an unmanaged guard | Move the foreign guard aside, then rerun refresh; use `--hooks-init` if guards are wanted |
| `--hooks-refresh` rejects an unmanaged runtime file | Back up or merge that file, move it aside, then rerun refresh |

More: [DOCS.md](DOCS.md#help) · [UPDATE.md](UPDATE.md)
