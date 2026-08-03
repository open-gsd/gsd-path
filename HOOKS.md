# HOOKS.md — Deterministic Guard Hooks

The pipeline's prompt contracts state two invariants no instruction can
actually enforce: committed `.project/archive/` trees are read-only, and
destructive git commands (`reset --hard`, `clean -f`, force pushes,
`branch -D`) break build recovery. `--hooks` backs both with code.

## Install

```bash
npx gsd-path --claude --project /path/to/repo --hooks
```

`--hooks` requires `--project` and writes, refusing any file that already
exists:

| File | Purpose |
| --- | --- |
| `.gsd-path/guard_hook.py` | Cross-host pre-tool-use guard (stdin JSON in, exit 2 + denial JSON out) |
| `.gsd-path/git_guard.py` | Commit validator: archive immutability + `ship:` commit purity |
| `.git/hooks/commit-msg` | Shim invoking `git_guard.py` (only when the project is a git repo) |
| `.claude/settings.json` | Claude Code PreToolUse wiring (only with the `claude` target) |

The git hook is the universal floor — it works regardless of which agent
made the change. Both guards fail open: a crash or unparseable input
never blocks the host or the commit.

## What gets blocked

`guard_hook.py` denies a tool call when:

- a write-capable tool (edit/write/patch/create/delete) targets a path
  under `.project/archive/`;
- a shell command runs `git reset --hard`, `git clean -f`, a force push,
  or `git branch -D`; or
- a shell command removes, moves, or redirects output into
  `.project/archive/`.

`git_guard.py` blocks a commit that modifies, deletes, or renames away a
tracked path under `.project/archive/`, or a `ship: ...` commit staging
paths outside `.project/`. Adding files to an archive stays allowed —
that is how the ship transaction works.

## Other hosts

The guard speaks the common hook protocol — JSON event on stdin, exit
code 2 or a denial JSON to block — which every supported host except Zed
understands. Only Claude Code wiring is installed automatically; wire the
rest by registering `python3 .gsd-path/guard_hook.py` as a
pre-tool-use hook in the host's own config:

| Host | Where to register | Docs |
| --- | --- | --- |
| Codex CLI | `.codex/hooks.json` or `[hooks]` in `config.toml`, event `PreToolUse` | <https://developers.openai.com/codex/hooks> |
| Copilot CLI | `.github/hooks/*.json`, event `preToolUse` | <https://docs.github.com/en/copilot/concepts/agents/hooks> |
| Grok CLI | reads `.claude/settings.json` hooks natively — covered by the Claude wiring | <https://docs.x.ai/build/features/hooks> |
| Qwen Code | `hooks` key in `.qwen/settings.json`, event `PreToolUse` | <https://qwenlm.github.io/qwen-code-docs/en/users/features/hooks/> |
| Kimi CLI | `[[hooks]]` in `~/.kimi-code/config.toml` (global only), event `PreToolUse` | <https://moonshotai.github.io/kimi-code/en/customization/hooks.html> |
| Cursor | `.cursor/hooks.json`, event `preToolUse` | <https://cursor.com/docs/hooks> |
| Kiro CLI | `hooks` field of the agent config, event `preToolUse` | <https://kiro.dev/docs/cli/hooks/> |
| Antigravity | `.agents/hooks.json`, event `PreToolUse` | <https://antigravity.google/docs/hooks> |
| OpenCode | needs a small JS plugin calling the guard from `tool.execute.before` | <https://opencode.ai/docs/plugins/> |
| Zed | no hook system; the `commit-msg` git hook is the only layer | — |

Caveats: Grok and Kimi are fail-open on hook errors by design; Copilot,
Kimi, Kiro, and Antigravity do not document whether hooks intercept
subagent tool calls, so treat their coverage as orchestrator-level only.
