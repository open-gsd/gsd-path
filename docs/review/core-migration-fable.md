# Core migration review

Reviewer: Claude Fable 5.1 (`claude-fable-5-1`), high effort.
Read-only native CLI review of the uncommitted implementation.

Review complete. I read AGENTS.md, all fourteen changed files, the three generated script copies, and the installer, router, define, and guard seams. No blocking defect in the helper code itself. There are two medium contract gaps, one medium evidence gap, and several low items. Verified defects and missing evidence are labeled separately.

## Verified against the code

- **Generated copies match.** The three scripts under `skills/gsd-path-migrate/scripts/` are line-for-line identical to their canonical sources, and the bundled discussion helper has the same line count as canonical. This agrees with the recorded sync check.
- **Installer picks up the skill from the manifest.** Skill names come from `scripts/skill-resources.json`, source validation requires the directory set to match, and the per-target root flags used by the new install test exist at `scripts/install.py:2849`.
- **A Path reinstall preserves a gated Core entry.** Managed-hook detection matches only commands that run `guard_hook.py` (`scripts/install.py:1450-1460`), so the rewritten Core command is treated as unrelated and merged through.
- **Settings helper ordering and rollback are correct.** Apply and restore compare exact bytes, refuse later edits, are idempotent, and multi-receipt restore in the wrong order blocks rather than clobbers. Receipt is created exclusively with owner-only mode.
- **Gate fails safe.** Bad JSON, null, relative, or prefix-collision cwd all fall through to the original command with stdin, stdout, stderr, and exit or signal status preserved.
- **Bundle safety holds.** Output inside the source, symlinks in the source, changed inputs during capture, and a pre-existing output all block, and a partial bundle is removed on failure.

## Findings

**1. Medium, contract gap (verified by reading): the IMPORT.md handoff has no on-disk anchor in the target project.**
`skills/gsd-path-migrate/SKILL.md:113-119` hands the bundle path to the router in chat. The router (`skills/gsd-path/SKILL.md:110-132`) routes a brownfield repo to inspect and then define with no mechanism for carrying a supplied document, and define's supplied-spec mode (`skills/gsd-path-define/SKILL.md:178-186`) triggers only when "the user supplies a document at entry". Inspect and define often run in separate sessions, and AGENTS.md lines 44 to 48 say chat history is not durable memory. The walkthrough stops at `inspect/active`, so "carry unfinished work through Path gates" is unproven past inspection. Smallest fix: in the Handoff section and MIGRATE.md, tell the user to re-supply the absolute IMPORT.md path when define is invoked, and extend the walkthrough with one define-entry step that shows it consumed.

**2. Medium, unproven on real inputs: the required-file rule may refuse legitimate Core projects.**
`scripts/migrate_core.py:66-68` hard-fails unless PROJECT.md, STATE.md, and ROADMAP.md all exist, with no override. The only evidence is a fixture that has all three. A Core project paused before roadmap creation, or one that only used quick tasks, would be blocked from preservation entirely, which contradicts the "preserve Core context" claim. I could not verify Core's layouts offline, so this is missing evidence rather than a proven defect. Smallest fix: require only PROJECT.md, report the other standard files as `absent` in the manifest so IMPORT.md records them as open questions, and add a test for a Core tree without ROADMAP.md.

**3. Medium, missing evidence: Codex standalone hook gating depends on `cwd` in the Codex hook payload.**
`scripts/core_hook_gate.py:19-21` only suppresses Core when the event carries an absolute `cwd`. Nothing in the repo proves Codex sends one. Path's own guard derives its root from its file location (`HOOKS.md:94`), and the recorded Codex fixture was skill-only (`docs/core-migration.md:47-48`). The gate fails safe, so the risk is that on Codex the Core hook keeps running in the migrated project and cutover silently never happens. Smallest fix: record one real Codex hook event showing `cwd`, or mark Codex standalone hook gating as unverified in MIGRATE.md and SKILL.md.

**4. Low, verified: the rewritten Core hook couples every project to the planning-time interpreter and Path's install directory.**
`scripts/core_hook_settings.py:47-51` bakes `sys.executable` and the absolute path of the installed gate. If the plan ran from a venv or temporary interpreter, or Path is later uninstalled or its skills directory moved, the Core hook errors in all projects, not just the migrated one. MIGRATE.md line 77 mentions path stability but not the interpreter or uninstall. Smallest fix: have `plan` refuse when `sys.executable` is not a stable system or user interpreter, and add one line telling users to `restore` every receipt before uninstalling Path.

**5. Low, verified: symlinked settings files are refused.**
`scripts/core_hook_settings.py:16-19` requires a regular file with one link via `lstat`, and `scripts/migrate_core.py:15` refuses symlinks too. Dotfile-managed `~/.claude/settings.json` is commonly a symlink. The error is explicit, so no data risk, but the user gets no guidance. Smallest fix: document passing the resolved real path, or resolve in `plan` and store the resolved path in the receipt.

**6. Low, test gap: the documented-commands test does not cover this skill.**
`tests/test_skill_commands.py:16` matches `python3 <absolute helper.py>` phrasing. The migrate skill uses `python3 -B <skill>/scripts/...`, so the "1 pass" evidence never parsed its commands. I checked by reading that every documented subcommand and flag matches argparse, so this is coverage, not a defect. Smallest fix: adopt the existing placeholder phrasing in SKILL.md.

**7. Low, missing evidence: Path branch binding with `.planning/` present is unexercised.**
`bind-initial` needs a clean worktree apart from untracked STATE.md. Core projects often have uncommitted `.planning/` updates. SKILL.md step 1 says stop Core work but not commit or stash `.planning/`. Smallest fix: one sentence in step 1.

## Completion claims I challenge

- "Carry unfinished work through Path gates" is proven only to `inspect/active`. Nothing shows define reading IMPORT.md or the work map surviving to approved intent.
- "Handle standalone hook conflicts" is proven for Claude Code by command replay only. For Codex it rests on an unrecorded payload assumption.
- `hooks_verified` is a permanent `false` in both manifest and verify output with no path to `true`. That is honest, but it means the machine record never captures the host evidence the skill requires, only IMPORT.md prose does.

Everything else in the helpers, tests, packaging, and docs matched the stated contract on the inputs I could reason about.

## Owner dispositions

1. Applied the proposed explicit define re-entry: IMPORT.md now stores a separate
   define command with its absolute path, the guide requires re-supplying it,
   and the walkthrough shows define consuming the source and recording its path
   in the intent draft. No automatic cross-session transport is claimed.
2. Confirmed on Core source: new-project writes/commits PROJECT.md before it
   creates ROADMAP.md and STATE.md. Preparation now accepts any nonempty Core
   evidence tree and lists absent standard documents as missing_inputs. The
   quick-only public-command test failed before the fix, passes afterward and
   caught restoration of the required-PROJECT behavior.
3. Located recorded native Codex payloads at
   docs/trust-validation/evidence/releases/1.0.0/codex-quick-4295d75/guard/traced-hook-payloads.log.
   They carry absolute cwd. A new test replays those captured event shapes in
   both project scopes; changing the field lookup broke it as expected.
4. Documented interpreter stability and restoration before uninstalling/moving
   Path or removing the interpreter/venv. An invented stable-interpreter
   whitelist was rejected: keeping a deliberately selected interpreter is valid.
5. Documented passing the resolved real settings path. Link refusal stays intact.
6. No test-parser change: the migration-specific installed-command tests execute
   the actual documented helper operations. The existing one-test command scan
   is supplementary evidence, not claimed as coverage of migration syntax.
7. Documented preserving pending work and reaching a clean Git baseline before
   binding. The walkthrough still honestly claims initialization only, not a
   performed branch bind or approval.

The permanent hooks_verified=false means bundle integrity alone never attests
runtime cutover; host-specific evidence belongs to the reviewed IMPORT.md.
Normal user intent approval remains part of the product flow, not an
implementation-time approval asserted by this review.
