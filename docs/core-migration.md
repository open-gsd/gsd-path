# Core to Path migration evidence

Status: implemented as an interactive migration skill. Intent approval remains
with the user through Path's existing gates. No real user project was migrated
or published during implementation.

## Contract and entry points

User rulings:

> Import project context and unfinished work (recommended): preserve Core history and map remaining work through Path's gates.

> Claude Code and Codex (recommended): cover plugin installs and skill installs.

The entry point is `$gsd-path-migrate`. See [the user guide](../MIGRATE.md),
[the skill](../skills/gsd-path-migrate/SKILL.md), and the
[worked intake](core-migration-walkthrough.md).

## Requirement evidence

| Requirement | Implementation and checked evidence |
| --- | --- |
| Preserve Core context, plans and history | `migrate_core.py preview/prepare` captures all regular `.planning/` files, with exact bytes and hashes. Source remains unchanged. Empty input, links and unsafe destinations fail explicitly. Missing standard documents are reported in missing_inputs, so partial and quick-only projects can be preserved. |
| Detect lost or changed import evidence | `verify` checks the owned manifest and exact path/hash inventory. Tests reject missing, changed and extra evidence. This proves integrity against the manifest, not authenticity against someone who edits both. |
| Carry unfinished work through Path gates | The skill writes a source-linked IMPORT.md work map and preserves constraints, exclusions, history and unresolved questions. The worked fixture maps every requirement/plan outcome into proposed intent. Existing initialization enters `inspect/active`, with null milestone and branch; Core completion state is not copied. |
| Keep both plugins installed | Native Claude and Codex fixtures prove the Core plugin can be disabled in the target project while remaining installed and enabled in another project. Managed-policy overrides require a separate owner action. |
| Handle standalone hook conflicts | The hook inventory retains exact commands and locations. `core_hook_settings.py` plans one selected change, applies it only against expected bytes, and restores the exact original file. Unrelated settings remain intact; later edits block overwrite. |
| Retain Core behavior elsewhere | `core_hook_gate.py` skips Core only for explicitly selected project roots and descendants. Other or uncertain events execute the original command with its stdin, stdout, stderr and denial status preserved. Separate worktrees need explicit scope. |
| Retain Path protection | Executed both configured commands after Core cutover. Core returned zero in the target; the actual Path guard denied an archive write with exit 2 and `permissionDecision: deny`. |
| Installable workflow | Temporary Claude Code and Codex skill installations execute preparation, verification, hook gating, and settings plan/apply/restore from their installed copies. Package preview contains MIGRATE.md and the migration helpers. |
| Avoid stale workflow instructions | Skill and guide require review of AGENTS.md, CLAUDE.md and host bridges, preserving project rules and documenting Core-only routing changes before cutover. This is a review step, not automatic deletion. |

## Native fixture records

Core source inspected: `b811ea16fc4a044dc16b36af91d7cee9d5375727` in the local
Core checkout. Path baseline: `6ab1b6f7521107115d15c51f07a4541ef781becd`.
Core's context monitor can run without `.planning/`; its isolation guard targets
`gsd-executor`. Different project directories alone do not prove coexistence.

Claude Code 2.1.270: temporary configuration directory, local marketplace,
`core-fixture@migration-fixture` with a PreToolUse hook, and two project roots.
Native marketplace add/install succeeded. Plugin list initially returned
`enabled: true`. Native `plugin disable --scope local --json` returned
`outcome: ok`. List then returned false in the target and true in the other
project, with the same installed plugin path/version.

Codex CLI 0.154.0: isolated child-process configuration/cache, local marketplace,
skill-only fixture plugin and two trusted temporary Git repositories. Native
marketplace add and plugin add succeeded. Plugin list initially returned
`installed: true, enabled: true`. Target `.codex/config.toml` set
`[plugins."core-fixture@migration-fixture"] enabled = false`. Native list then
returned installed/disabled in the target and installed/enabled in the other
project. All commands exited zero. Fixture directories were removed afterward;
real user configuration was unchanged.

These runs prove native plugin scope behavior. The hook preservation test is
command replay, not a model-driven native tool session. The migration skill
therefore requires checks in each user's effective host environment before
claiming their cutover is complete. It does not claim that local settings can
override managed or workspace-enforced plugin policy.

Sources: [Claude plugin commands](https://code.claude.com/docs/en/plugins-reference),
[Codex configuration](https://learn.chatgpt.com/docs/config-file/config-reference),
[official marketplace format](https://raw.githubusercontent.com/openai/plugins/main/.agents/plugins/marketplace.json).

## Executable verification

- `python3 -B -m unittest discover -s tests -p test_migrate_core.py`: 10 pass.
- `python3 -B -m unittest discover -s tests -p 'test_core_hook*.py'`: 7 pass.
- `python3 -B -m unittest discover -s tests -p test_install.py`: 131 pass.
- `node --test tests/install.test.mjs`: 127 pass.
- `python3 -B -m unittest discover -s tests -p test_sync_skill_resources.py`: 6 pass.
- `python3 -B -m unittest discover -s tests -p test_skill_commands.py`: 1 pass.
- `python3 -B scripts/sync_skill_resources.py --check`: pass, 275 resources.
- `npm pack --dry-run --ignore-scripts --json`: migration guide and helpers included.
- `git diff --check`: pass.

RED runs showed absent history/bundle output, accepted unsafe inputs, empty hook
inventory, missing verifier behavior, missing installed helpers, absent settings
receipts, stale-edit acceptance, and missing pending-discussion support.
Implemented behavior passed after those failures.

Sabotage checks removed hashing/copying, disabled required-input, link and
containment checks, disconnected hook inventory, removed command/plugin entries,
skipped evidence/schema validation, disabled or broadened hook suppression,
disconnected settings wrappers, allowed stale overwrites, disabled restoration,
skipped installed writes, omitted the pending helper and package guide, and
rewired Path's guard to `exit 0`. Relevant checks caught each mutation. Original
code was restored and affected checks passed. Ponytail reviews retained standard
library operations, the existing installer and the existing Path gates.

## Operational limits

Stop Core and settings writers while preparing/applying: these helpers do not
coordinate transactions with a running Core process or external settings editor.
Keep rollback receipts private and installed helper paths stable. Review supplied
settings scopes and plugin registrations; an empty inventory is not a safety
verdict. Unsupported/malformed inputs and policy conflicts remain explicit
migration blockers. No implicit conversion of historical success into Path
approval is provided or intended.
