# Move from GSD Core to GSD Path

Use `gsd-path-migrate` to preserve an existing Core project's context and
unfinished work, review hook conflicts, then enter Path through inspect and
define. The first release covers Claude Code and Codex, with either plugin or
standalone skill installations.

Both products can stay installed. Migration changes which product governs the
selected project. Core history stays in `.planning/`; Path creates its own
`.project/` state through the normal router. Core phase positions and completed
plans do not become passed Path gates.

## Start

Install or update GSD Path using [the install guide](QUICK.md). In the Core
project, stop active Core work and invoke the migration skill:

```text
$gsd-path-migrate
```

On Claude Code, use the installed `gsd-path-migrate` slash command. Give the
skill the project path and whether Core came from a plugin or standalone skills.
The skill prepares an external bundle, so it does not dirty the source project
before Path's branch binding. Do not delete `.planning/` to suppress hooks.
Preserve any uncommitted work and reach a clean Git baseline using your normal
commit/stash workflow before binding. Migration does not discard pending edits.

The bundle contains an exact file copy, a hash manifest, and a reviewed
`IMPORT.md`. The import carries context, constraints, exclusions, decisions,
unfinished requirements and plan outcomes, with source references. Completed
summaries remain historical evidence. Contradictions and missing information
become explicit questions for you.

## Keep both installations

| Installation | Project cutover |
| --- | --- |
| Claude Code plugin | Disable the exact Core plugin identifier at local scope, then reload/restart and verify effective state. |
| Codex plugin | Set the exact Core plugin identifier's `enabled` value to `false` in trusted project configuration, then restart and verify effective state. |
| Standalone command hooks | Review each Core hook registration. Use the bundled settings helper to gate only that command for the migrated root. Other projects retain the original command. |

Claude example, using the identifier shown by `claude plugin list --json`:

```sh
claude plugin disable '<core-plugin>@<marketplace>' --scope local
```

Codex example in the project's `.codex/config.toml`, merging into any existing
table for that identifier rather than adding a duplicate:

```toml
[plugins."<core-plugin>@<marketplace>"]
enabled = false
```

Check with the host's native plugin list in both the migrated project and a
separate Core project. Managed/workspace policy may prevent local overrides;
the skill reports that conflict instead of claiming migration is safe.
These controls are documented in
[Claude's plugin reference](https://code.claude.com/docs/en/plugins-reference)
and [Codex's configuration reference](https://learn.chatgpt.com/docs/config-file/config-reference).

Plugin disabling does not remove separately installed hooks or skills. Review
user, project and local settings, status-line commands and inherited instruction
files. Preserve project-specific rules. Replace Core-only workflow routing with
Path's installed contracts; keep a copy and record every removed Core instruction
in the import. Continue using the explicit Path skill names in migrated projects.

## Review and rollback

The standalone settings helper prepares a private receipt before writing. It
records the exact selected command and original file bytes. After review, apply
the receipt; restore it to roll back. Changes made since the receipt was prepared
block application or restoration. With several changes to one settings file,
apply each before preparing the next and restore in reverse order. Close host
sessions and settings editors during these writes.

Keep both the installed helper path and its planning-time Python interpreter
available while hook settings reference them. Restore every receipt before
uninstalling/moving Path or deleting that interpreter or its virtual environment.
For symlink-managed settings, pass the resolved real file path to the helper;
it deliberately refuses symlink paths and files with multiple hard links. Each
separate migrated worktree needs its own scope. A missing or unclear event `cwd`
keeps the original Core hook active. Only Claude Code and Codex command-hook
protocols are covered; other hosts require separate verification.

Review `IMPORT.md` before handing it to `$gsd-path`. Path inspects the code,
checks the supplied evidence, and asks you to approve intent. Every remaining
Core outcome must appear in that intent or have an explicit disposition from
you. Keep the bundle available for the handoff. When inspect finishes, invoke
define with the absolute IMPORT.md path again, using the command saved in its
Handoff section. This is required in a fresh session too: the router does not
carry the external path into define automatically. Define records the source
path in its intent draft. The skill does not approve,
build, ship, or publish your project on your behalf.

Preparation and hook-command tests do not prove every installed host policy.
The skill requires effective-state and hook checks in your target environment
before declaring cutover complete.
