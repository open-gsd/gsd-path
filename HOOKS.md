# HOOKS.md — Deterministic Guard Hooks

Optional enforcement for pipeline invariants prompt contracts cannot guarantee:

- committed `.project/archive/` trees stay read-only after ship
- destructive Git operations do not erase recovery state, untracked evidence,
  or protected refs
- direct product-file writes do not bypass a routed non-build phase
- a milestone branch with its canonical ship commit accepts no further edits or commits,
  even if STATE is later rewritten; writes are checked against the target worktree

Closed branches still allow read-only Git inspection (`status`, `log`, `diff`, plain
`cat-file` reads of one object, branch and worktree listing) and the router handoff helpers, including
`git fetch origin`, SHA resolution, and next-base selection. Branch switching remains
router-owned. The [ship contract](skills/gsd-path-ship/SKILL.md) owns integration
conflict handling and published-validation recovery.

`cat-file` options are restricted by `CLOSED_LISTING_GIT_OPTIONS` in
[`scripts/guard_hook.py`](scripts/guard_hook.py); filter and text-conversion forms
are blocked because they can execute external commands.

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
npx @opengsd/gsd-path --claude --project /path/to/repo --hooks
# or from clone:
node scripts/install.mjs --claude --project /path/to/repo --hooks
```

For a project that already has `AGENTS.md` and `WORKFLOW.md`, initialize only
the guards and keep those contracts unchanged (use `--update --project` to
refresh the `AGENTS.md` block):

```bash
npx @opengsd/gsd-path --hooks-init --claude --project /path/to/repo
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
| `.gsd-path/guard_hook.py` | Pre-tool-use guard (stdin JSON → exit 2 + denial JSON; runtime resolution failures exit 2 with stderr) |
| `.gsd-path/git_guard.py` | Commit and publication validator |
| `.gsd-path/runtime.json` | Tracked selected runtime version and digest |
| `~/.gsd-path/runtimes/<digest>/` | Immutable external pipeline helpers and guards |
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
Python interpreter that the installer probes at install time: `python3` first,
then `python`, then the `py -3` launcher (plain `python3` usually does not
exist on Windows). If none runs, hook installation stops before writing
instead of pinning a missing interpreter. The `sh` hook scripts themselves need
a POSIX shell, which Git for Windows provides. Claude Code runs Windows hook
commands in Git Bash, so wrapped Core hooks are bash-quoted and their original
command runs through Git Bash, not cmd.exe.

### Updating after package upgrade

```bash
npx @opengsd/gsd-path --hooks-refresh --project /path/to/repo
npx @opengsd/gsd-path --hooks-refresh-full --project /path/to/repo   # + settings/git hooks
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

- direct product edits outside the routed build phase while milestone work
  remains unfinished. After integration is verified, ordinary branches allow
  product edits, including a dirty product worktree. The proof still checks
  the shipped archive, canonical integration merge, annotated published tag,
  and default-branch ancestry. Missing proof keeps protection active. Closed
  milestone branches, archives, and pipeline control files remain protected.
- non-read tool actions targeting archived paths or an existing ancestor of
  the archive tree; shell operands count an ancestor only for deletion or move
  commands
- `git reset --hard`, destructive `git clean` modes, force pushes (including
  `+` refspecs), destructive branch or ref deletion, `git branch -m`,
  `git worktree remove --force`, `git stash drop`/`clear`, and whole-tree
  `git checkout -- .`/`git restore .`
- shell writes (redirections, `tee`, `cp`, `mv`, `rm`, `sed -i`, ...) that
  target a routing control (`.git`, `.project/STATE.md`, `.project/next`,
  `.gsd-path`) while `.project/STATE.md` exists, or target a product file
  outside the routed build phase (same rule as direct file-edit tools)
- repeated assignments to the same shell variable within one command; split
  these into separate tool calls so write targets can be resolved
- copies whose destinations, including nested recursive-copy entries, resolve
  into closed worktrees. Copy sources remain read-only inputs; ordinary safe
  recursive copies are allowed. Supported variables are expanded before
  destinations are derived, including contents-copy forms ending in `/.` or
  `/`. Both lexical entries and resolved targets are checked. Unresolved copy
  operands, unreadable source trees, directory sources that are symlinks, and
  source trees containing directory symlinks are denied; use literal directory
  paths and copy directory links separately
- shell commands that reference the archive unless the whole command is a
  recognized standalone read, a pipeline in which each segment is a recognized
  read, or a single-command invocation of the bundled
  `pipeline_state.py` / `archive_milestone.py` helper, resolved to a regular file
  inside the verified runtime selected by `.gsd-path/runtime.json` (legacy projects use `.gsd-path/runtime/` beside `guard_hook.py`
  in the repository layout), using exactly `python` or `python3` with optional
  `-B`; non-empty supplied tool working directories are authoritative. Empty
  strings, including list items, are treated as absent: nested payloads inherit
  their parent context, with the process cwd used when no directory is supplied.
  The helper exception refuses chains, pipes,
  wrappers, substitutions, redirections, and any newline, carriage return, or
  backslash in the command text. The parsed script path must contain no `$`,
  backticks, glob characters (`*`, `?`, `[`, `]`), braces, or `..` path components,
  and must not start with `~`. Quoted spaces in paths and quoted punctuation
  within arguments, such as the shipment event's semicolon, are allowed
- deletion or move commands outside a single simple segment, including command
  chains, pipes, newlines, grouping, directory changes, and command substitution
- deletion or move commands with any argument outside the literal-path character
  set: ASCII letters, digits, `.`, `_`, `-`, `/`, and ASCII spaces inside one
  shell unit (plus a drive prefix and backslashes on Windows). One matching
  pair of surrounding quotes is allowed; parameters, wildcards, braces, and
  tilde paths are denied even when quoted. This also applies to
  `find -delete` and supported destructive aliases
- destructive Git commands nested in supported shell and command wrappers
- Git arguments that contain a shell parameter. Only plain `$name` and
  `${name}` expansions pass, and only inside plain double-quoted spans of
  read-only subcommands (`status`, `log`, `diff`, `show`, and the other
  inspection commands) that the guard parses directly, such as
  `git log --format="$t %H"` or `git show "HEAD:$f"`, because only double
  quoting prevents word-splitting into options. A parameter outside double
  quotes (`$x`, `HEAD:$f`, `--format=$x`, `"a b"$x`) is denied because its
  expansion can split into a write option such as `--output`. Every other
  parameter form (`${=x}`, `${(z)x}`, `${x:-y}`, `$x[@]`, `$1`, `$@`, `$*`,
  `$#`, and the unbraced zsh flags `$=x`, `$~x`, `$^x`, `$+x`) is denied even
  inside double quotes, because it can expand to more than one word; a
  backslash-escaped marker (`"\$t"`) is likewise denied, because the shell
  executes the literal text while the argument still shows the bare marker.
  The same four zsh flags are denied in a `git -C` directory. A literal `$`
  that starts no expansion (a regex anchor such as `--grep='fix$'`) passes.
  A `-c`/`--config` key whose value git executes as a program —
  `core.fsmonitor`, editors and pagers, `core.sshCommand`,
  `core.askPass`, `filter.*` clean/smudge/process, `diff.*`
  textconv/external/command, `merge.*` drivers, `core.gitProxy`,
  `remote.*` uploadpack/receivepack, `gpg.program` and `gpg.*.program`, `credential.helper` and
  `credential.*.helper`, each `pager.<cmd>` key — is denied with a literal
  value as with a parameter, because git runs it during an otherwise
  read-only subcommand. A disabling form of such a key passes: the bare key,
  an empty value, or `false`. A `--config-env` form is always denied, because
  its value comes from the environment. A key through which git loads code —
  `core.hooksPath`, `include.path`, `includeIf.*.path`, `url.*.insteadOf`,
  `url.*.pushInsteadOf` — is denied with each value. `git config` is denied
  when it sets one of these keys; to read or unset the key stays allowed.
  A redirection at the end of a read (`git config <key> 2>/dev/null`) is not
  a value. A separate digit before a redirection (`5 >/dev/null`), a word of two
  or more digits (`12>/dev/null`) and a quoted operator are values, so they
  make a set.
  Each `git config` argument must be a plain literal word, bare or in one
  pair of quotes: a backslash, mixed quotes, an unquoted glob (`*`, `?`, `[`),
  an unquoted brace list or range (`{a,b}`, `{1..3}`) or a line continuation
  in the word or one that joins it to the next word is denied, because the shell can make a different
  argument list from it.
  An unquoted word that starts with `#` among the `git config` arguments
  is denied, because the shell reads it and the words after it as a comment.
  The git subcommand word must be a plain literal word in each git command:
  `git {config,...}` and a subcommand split by a line continuation are denied.
  A program that runs the command in its arguments (`nice`, `nohup`,
  `timeout`, `sudo`, `watch`, `time`, `env`, `stdbuf`, `setsid`) is
  unwrapped: the guard skips the options of the program and checks the
  command that it runs, so `nice git -c core.fsmonitor=/abs/h.sh status` is
  denied by the git rule and `sudo apt install git` passes. A runner
  option that writes, edits or enters a file or directory by itself is
  denied (`time -o`, `sudo -e`, `sudo -D`, `sudo -R`, `watch -s`). The
  `timeout` duration and the `watch` interval must be literal numbers, and
  each runner option word must be a literal word; only a separate option
  value can be a parameter in double quotes (`sudo -u "$USER" ls`). A short
  option word is read as getopt reads it, so the attached value in
  `sudo -upostgres psql` is not taken as more options. With an archive working directory a command runner is not
  unwrapped and is denied as an unknown program. Other command
  runners (`doas`, `ionice`, `noglob`) are not unwrapped, and `watch` with
  the command in one quoted word is not checked.
  Each git global option word, and the value word of `-c`, `-C`,
  `--git-dir`, `--work-tree`, `--namespace` and `--config-env`, must resolve
  to one word: a backslash, an unquoted glob or an unquoted brace list or
  range in it is denied (`git -c {core.fsmonitor=/abs/h.sh,status}`,
  `git -{p,c} core.fsmonitor=/abs/h.sh status`). A parameter in such a value
  is denied also when no subcommand follows (`git -c $x`). Plain quoted parts
  pass (`git -c user.name='A B' log`).
  `git config` section renames and removals (`--rename-section`,
  `--remove-section`) and `--edit` are denied, because a rename can move a
  key into an executed section and `--edit` starts an editor.
  Command substitution output, a parameter that starts an
  argument, and a parameter in the value of an option that git writes to or
  runs as a command (`--output`, `--upload-pack`, `--receive-pack`, `--exec`,
  `-c`, `--config-env`, or a `<transport>::<address>` remote) are denied in
  every form. These option names match by prefix (`--upload-pa`, `--exe`),
  because git accepts abbreviated long options; in archive context the same
  prefix match applies to `--output`, `--ext-diff`, and `--textconv`. The
  exact read-only option `--text` is not an abbreviation and stays allowed. Any
  other quoting construct in the command (`$'...'`, `$"..."`, quotes inside `${...}`, quotes or
  backslashes in a comment, here-documents and here-strings) disables the
  exception, so every parameter in a git argument of that command is denied.
  The exception applies only to commands the guard parses directly, never
  inside wrapped shell strings (`eval`, `bash -c`, `sh -c`, PowerShell or
  `cmd` command strings), where the outer shell expands the parameter first
- archive glob/brace expansions and execution-capable read options such as
  `rg --pre`
- direct write, edit, and patch tool calls targeting `.project/STATE.md`,
  `.project/next/STATE.md`, their protected parent directories, or `.gsd-path/`;
  product-file calls also require the deterministic build route, including
  helper-proven parallel task worktrees

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
- while committed `STATE.md` names unfinished milestone work, including
  `shipped/done` without verified integration: commits staging paths outside `.project/` (or the
  guard's own `.gsd-path/` and native hook settings) unless the phase is
  `build` and they are landing commits as `isolation.py land` writes them —
  subject `<task id>: <task title>` matching the task file at `Base:`, a full
  base SHA HEAD descends from, the staged task file, only that task's declared
  `files:`, and a `Files:` list of exactly the staged paths. Outside build the
  reviewed HEAD is frozen; product fixes reopen through the patch plan.
  The validated integration merge is allowed to complete before publication
  proof exists; an ordinary commit with an integration subject is not exempt
- deleting the recorded branch or switching to another branch while carrying
  unfinished state does not release product commit protection
- pushes (to any remote) that move a `gsd-path/M###` ref anywhere but its
  strict ship commit, or delete it while it holds anything else; and pushes of
  any other ref whose commit carries a `STATE.md` that still owes a ship commit
  (names a bound branch, not `shipped/done`). The ship state's `branch` must
  match every bound name in the local and remote refs. Malformed pre-push
  records and failed object inspection block the push; a present commit
  without `STATE.md` passes on an ordinary ref. An absent bound ref passes
  deletion. The authorized publisher is `archive_milestone.py integrate`;
  the hook checks ref updates, not which client initiated them
- **allows** adding files to archive during the ship transaction, before the
  branch closes

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
| Muse Code | no GSD Path hook integration — git hooks only | — |

**Caveats:** The hook cannot prove which skill initiated a build-phase edit
when the routed build phase is already active. Shell product writes use the
same phase gate as file-edit tools; AGENTS.md still owns plain-prompt re-entry
when no `.project/STATE.md` exists. Grok and Kimi
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
| Runtime missing, invalid, or legacy | Follow [runtime restoration or migration](DOCS.md#project-runtime-versions) |

More: [DOCS.md](DOCS.md#help) · [UPDATE.md](UPDATE.md)
