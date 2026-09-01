# gsd-path evaluation — 2026-09-01

Baseline: worktree `jeremymcs/ui-design-contracts` fast-forwarded to `main` (bc8b775). Working tree clean.
`npm run verify`: node `pass 129`, python `Ran 968 tests OK (skipped=2)`, sync check clean (137 resources). EXIT 0.

Method: four parallel audits (installer/platforms, core helpers, gate/guard helpers, skills/docs) plus a
workflow-level pass. "Reproduced" = the failure was triggered with a real command in a scratch repo.
Severity is by consequence to a running pipeline: **HIGH** = data loss or a stuck/undocumented dead-end,
**MED** = wrong result or silent degradation with a workaround, **LOW** = cleanup.

---

## 1. HIGH — fix first

### 1.1 Data loss in `isolation.py retire`
- `scripts/isolation.py:2582-2601` — non-forced `retire` deletes the task branch with `git branch -D` after only a worktree-cleanliness check. If `land` crashes between the stamp commit and the cherry-pick onto the primary, the task commit exists only on that branch; retire destroys it.
- `scripts/isolation.py:2473-2607` — `retire --force` with a worktree present ignores `--task-file/--landed-commit` proof. Build SKILL.md:177 documents `--force` as the retry-retirement command, so following the skill after an interrupted land deletes in-progress work.

**Why:** the pipeline's core promise (AGENTS.md "files are memory", recoverable handoffs) is broken by its own cleanup command. Fix: before `branch -D`, require that the branch tip is an ancestor of the primary (`git merge-base --is-ancestor`) or that `--landed-commit` matches; otherwise refuse and name the recovery command.

### 1.2 Skills instruct commands the helpers reject (reproduced dead-ends)
| Location | Instruction | Helper response |
|---|---|---|
| `skills/gsd-path-plan/SKILL.md:240-244` | deferred approval via `transition --set-status done` | "plan approval requires pipeline_state.py approve --kind plan" |
| `skills/gsd-path-plan/SKILL.md:384-386` | patch-mode approval, same call | same rejection; `approve` requires a git HEAD → no path to `plan/done` without git |
| `skills/gsd-path-roadmap/SKILL.md:196-200` | deferred roadmap approval | same rejection |
| `skills/gsd-path-roadmap/SKILL.md:167-171` | post-abandon `roadmap/active → inspect/active` | `CROSS_PHASE_TRANSITIONS` lacks the edge |

**Why:** WORKFLOW.md:298-302,363-367 describes deferred approvals as plain transitions; AGENTS.md:210-213 says journaled `approve`. Code implements only the AGENTS version. Every branch above is an agent loop that ends with "helper exited non-zero" and no next step (see 2.9). Fix: pick the AGENTS semantics, rewrite the four skill passages to call `approve`, add the abandon edge (or route abandon through `archive_milestone.py abandon`'s own transition), and add one test per passage that executes the documented command verbatim.

### 1.3 Roadmap-done routing contradiction
`skills/gsd-path-roadmap/SKILL.md:208-209` says roadmap/done routes to define; `pipeline_state.route_state` agrees; `WORKFLOW.md:381-384` says inspect-first. Two of three authorities agree — update WORKFLOW.md.

### 1.4 `pipeline_state.py` lookahead reads the wrong milestone
`scripts/pipeline_state.py:1165, 689-716` — at `define/done` for a lane milestone in `.project/next`, the router reads open questions from the *active* roadmap entry (Status: active), not the lookahead milestone's. Result: M002 research is skipped because M001 has no open questions.
Fix: select by `state.milestone` when `project_dir` is the lookahead dir. Test gap: no lookahead route test at define/done.

### 1.5 Plan drift check demotes approved plans
`scripts/pipeline_state.py:3087, 3263 → 2612-2625 → 2382-2398` — `_classify_plan_drift` looks for the approval checkpoint from `base`, not `landing`. When `base != landing` (normal after any land) it returns `unverifiable` and demotes `plan/done` to `plan/active`. Fix: find the checkpoint from landing, diff checkpoint..base.

### 1.6 `git_guard.py` blocks the first commit
`scripts/git_guard.py:113-124, 436-461` — `git ls-tree HEAD` on an unborn HEAD raises; with hooks installed the initial commit is impossible (reproduced). Also hard-codes `main` (`:340-375`). Fix: treat unborn HEAD as an empty tree (`git hash-object -t tree /dev/null`), read the default branch from `init.defaultBranch`/`origin/HEAD`.

### 1.7 `guard_hook.py` denies ordinary shell with no reason
`scripts/guard_hook.py:1301-1355, 963-1047` — any Bash containing `$(…)`, a newline, `for/while/if`, `export`, `set`, `source`, a heredoc, `xargs`, or `find -exec` is denied with "could not validate the tool request". No token is named, so the agent cannot rewrite the command; the practical outcome is the agent disables the guard.
Fix: name the offending construct in the denial; allow constructs that touch no protected path. Related MED: `:703-740` re-entry gate does not cover Bash writes (`echo > file`, `sed -i`); `:1157-1236` destructive table misses `worktree remove --force`, `stash drop|clear`, `checkout -- .`, `restore .`, `branch -m`.

### 1.8 `check_handoffs.py` truncates values at `#`
`scripts/check_handoffs.py:96-138` — frontmatter regex treats `#` as a comment start inside quoted values: `title: "Fix #123 regression"` → `"Fix"` → false wave-gate title mismatch. Any task named after an issue number fails the gate. Fix: use the `_frontmatter`/`_strip_yaml_comment` pair already in `check_task_briefs.py` (see 3.4).

### 1.9 Installer breaks on existing projects
- `scripts/install.mjs:3004-3013, 1186-1191`, `scripts/install.py:1012-1022`, `scripts/wizard.mjs:145-159` — `--update --project PATH` on an existing project always fails ("project contract already exists: …/AGENTS.md") and rolls back the whole update. The wizard generates exactly that argv.
- `scripts/install.mjs:1115-1125` — `nativeSettingsMergers` has codex+cursor only; `mergedClaudeSettings` (`:1460`) is used by refresh only. `--hooks --claude` refuses any project with a pre-existing `.claude/settings.json`. Verified in both installers. Fix: register `[".claude/settings.json", mergedClaudeSettings]`.

### 1.10 Windows is advertised but cannot run
`scripts/detect_project.py:211-219, 1409-1443` requires `fcntl` while `install.py` installs Windows hooks. Either drop Windows from the host matrix/README or replace the lock with `msvcrt`/portalocker-style fallback.

---

## 2. MED — wrong result or silent degradation

2.1 `pipeline_state.py:1719-1760` — `record_shipment` journal uses `date.today()`; a resume on the next calendar day mismatches and refuses. Use the shipment's recorded timestamp.
2.2 `pipeline_state.py:949-950` — dirty worktree plus an outstanding bind-next journal makes `route`/`status` raise. Read-only commands must not fail on journals.
2.3 `pipeline_state.py:3020-3022` — `promote-next` rerun after completion errors "project directory must be real" instead of reporting already-promoted (idempotency contract from AGENTS.md).
2.4 `pipeline_state.py` duplicates bind-next journal validation from `pipeline_git.py:685-723`.
2.5 `isolation.py:1155-1158` — parallel `land` refuses on any primary dirt including permitted `.project/discuss` appends, and names no path. Whitelist the discuss dir; print the offending paths.
2.6 `archive_milestone.py:2045-2056` — `prepare` persists `STATE.archive` and creates dirs before input validation; a failed prepare leaves STATE stuck (patch-mode return then illegal). Validate first, write last.
2.7 `archive_milestone.py:2958-2961` — `validate()` requires HEAD == ship commit; contradicts WORKFLOW "product commits after shipping do not disturb a validated shipment". The drift check at `:3073-3077` is dead and `tests/…:2677` pins the wrong behavior. Decide which is the contract; delete the loser.
2.8 `archive_milestone.py:3419-3425, 4046-4072` — merge-conflict stderr is discarded; the agent sees "integration failed" with no file list.
2.9 No skill says what to do when a helper exits non-zero. Combined with 1.2 this is the main source of loops. Add one rule in AGENTS.md: "helper non-zero → stop, print stderr verbatim, do not retry the same command".
2.10 `templates/plan.md:10-28` — Config keys `max_review_cycles`, `wave_budget`, `finding_skeptics` are read by no script (only `review_panel` reads config). A typo silently disables the feature. Either validate them in `check_task_briefs`/`pipeline_state validate` or remove them.
2.11 `--update` refreshes skill roots only; `.gsd-path/runtime` in projects goes stale silently (only `--hooks-refresh*` refreshes it). README:64-66 presents `--update` as complete.
2.12 Two full installers (`install.mjs` 3059 lines "Node port of install.py", `install.py` 2855) with no parity test; error wording already diverged. Retire one or add a golden-output parity test.
2.13 CI runs `pytest` on Node 20 only; `npm run verify` (unittest + node + sync) is what contributors run; `engines` says >=18.17. `check_trust_evidence.py` runs only on manual dispatch. Make CI = `npm run verify` on a Node 18/20 matrix.
2.14 `platforms/antigravity/dispatch.md` is dead (`install.mjs:2386-2392, :273` always uses the shared-agents profile).
2.15 `check_handoffs.py:201-207, 456-460` — any `<`/`>` in a handoff is rejected as a placeholder (breaks generics, HTML, comparison text). Use the `archive_milestone.contains_placeholder` predicate.
2.16 `check_task_briefs.py:170-178` — backticked URL routes (`/api/users`) flagged as missing paths.
2.17 `skills/gsd-path-ship/SKILL.md:145, 163-164` — names no helper for the log-only write; `transition` requires a `--set-*`, so the instruction cannot be executed.
2.18 `skills/gsd-path-plan/SKILL.md:205-206` garbled sentence; `skills/gsd-path-build/SKILL.md:345` "`off` or `off`" (second should be `skipped`).
2.19 Repeated text: the "caller handoff" paragraph is verbatim in 9 skills; the `discussion_records.py pending` preamble (~30 lines) in 10. Skills total 26,243 words. Move both to AGENTS.md (already loaded) and reference them.

---

## 3. LOW — cleanup

3.1 Dead code: `pipeline_git.py` `next_milestone_number:163`, `active_roadmap_milestone_id:174`, `pipeline_commit_body:154`, `legacy_*_subject:98-103`; `guard_hook.py:363-380`; `archive_milestone.py` `require_command_success` == `require_git_success`, `abandon_locked` duplicates `prepare_locked`.
3.2 `archive_milestone.py` accepts manifest `## Notes - none` as content.
3.3 Package `files` ships repo-only `check_trust_evidence.py` and `sync_skill_resources.py`; `docs/` is not shipped but README links `docs/trust-validation/HOST-MATRIX.md`; helpers are duplicated 5× in the tarball (archive_milestone.py alone 176 KB × 5).
3.4 Cross-script duplication: git runner ×4-6, atomic tmp-write ×4, frontmatter parser ×8 with three incompatible semantics (root cause of 1.8 and 2.15), `BOUND_BRANCH_RE`/`PIPELINE_MARKER` ×2, worktree-list parsing ×3, ls-remote ×3. One `scripts/_common.py` (`run_git`, `atomic_write`, `parse_frontmatter`, `contains_placeholder`, protected-path table) removes all of these; the sync manifest already copies scripts per skill so one extra file costs nothing.
3.5 `loop_run.py:64-96` `parse_spec` matches keys anywhere in the file; `skip_when` runs under `check`.
3.6 `pipeline_diagnose.py` no-`.project` case should print the `initialize` command.
3.7 `review_panel.py:375-394` conflict count is noise.
3.8 Skill `description` frontmatter names only the Codex `$gsd-path-X` form (12/14); other hosts' invocations differ.
3.9 `guard_hook`/`git_guard` error messages give no fix direction (several sites); `check_handoffs` Reviewed-HEAD error likewise.
3.10 Copilot, Qwen, Antigravity, Kiro, Kimi have PreToolUse APIs (HOOKS.md:132-138) but are `guard_tier: git-only` with no wiring. Either wire them or drop the "native guard" claim from the host matrix for those rows.
3.11 PR41 leftovers still open: detect_project frontmatter leniency, `.git` symlink handling, roadmap `--active-milestone` when unset (`gsd-path-roadmap/SKILL.md:119` now says omit — verify helper agrees), duplicate-key parsers in promote lookahead, all-terminal roadmap stall.

---

## 4. Workflow gaps and additions

### 4.1 `build_state.py` is dead — wire it or delete it
`scripts/build_state.py` (748 lines: `ready`, `reconcile`, `verify-landed`) is bundled into gsd-path, gsd-path-build and gsd-path-ship per `skill-resources.json`, tested by `tests/test_build_state.py`, and referenced by **nothing** — no SKILL.md, WORKFLOW, AGENTS, platform file, or script. Build step 2 (ready-set selection) and the post-land reconciliation are done in model prose instead, which AGENTS.md forbids ("never reproduce deterministic operations in model reasoning"). Recommendation: make build step 2 call `build_state.py ready` and the land step call `reconcile`; if the helper's contract is stale, delete it and its tests.

### 4.2 Build step 7 is a state machine written in prose
`skills/gsd-path-build/SKILL.md` step 7 (~110 lines) has the model track the skeptic set, the refuted set, carry-forward across cycles, fix-batching and the cycle cap. This is the most complex deterministic bookkeeping in the pipeline and the one place with no helper. Add `review_findings.py` (or extend `review_panel.py`) that reads the lens/skeptic files and emits: surviving findings, refuted findings, fix-task groups, and whether the cycle cap is reached. The skill then shrinks to "run it, act on the output". This also makes 2.10 real (the config keys get a reader).

### 4.3 Verification cost is the measured time sink and nothing addresses it
The 08-22 path-fixes audit (memory) measured ~47% of wall time in redundant full-suite reruns and parallel-load timeouts, ~8% in `.project` bookkeeping. Nothing in the plan template, build or ship skill lets a plan declare a suite as heavy or reuse a passing run. Additions, both derived from that measurement:
- PLAN Config: `verify` entries carry a `reuse: same-base` flag — a verify-only wave or review that runs on the same base commit as an already-recorded pass reads the recorded result instead of rerunning.
- PLAN Config: heavy suites (declared by the plan author) run serialized; light suites may run in parallel. No default values; the plan author declares per suite.
`build_state.py verify-landed` already records per-HEAD verification — it is the natural place to keep the "passed at commit X" ledger.

### 4.4 One error rule for helpers (see 2.9)
Every skill assumes helpers succeed. Add to AGENTS.md: on non-zero exit, stop, print stderr, check `pipeline_diagnose.py`, do not retry unchanged. Add to every helper: error messages end with the command that fixes the state (isolation, git_guard, guard_hook, check_handoffs, archive_milestone are the current offenders).

### 4.5 Shared helper module (see 3.4)
`scripts/_common.py` with `run_git`, `atomic_write`, `parse_frontmatter` (one YAML-comment-aware semantics), `contains_placeholder`, and the protected-path table used by both guards. Removes three incompatible frontmatter parsers and the guard-table drift.

### 4.6 Split the two largest helpers
`archive_milestone.py` (4426 lines) → `discussion_validate.py` + `integration.py`; `pipeline_state.py` (3636) → `state_checkpoint.py` + `state_promote.py`. Justification: 1.4, 1.5, 2.1-2.4 all live in the promote/checkpoint half and are invisible in a 3.6k-line file; the package ships each file 5×.

### 4.7 Executable documentation tests
Every dead-end in 1.2 was a command written in a skill that the helper rejects. Add a test that extracts fenced `python3 …` commands from every SKILL.md, substitutes fixture paths, and runs them against a scratch project in the state the skill says it is in. Cheap to build once; it would have caught all four plus 2.17.

### 4.8 Installer: parity test or retire `install.py` (2.12), `--update` that refreshes runtime (2.11), Claude settings merger (1.9)
Single-installer is the lazy answer: the Node installer is the npm bin entry; `install.py` exists for hosts without Node, which every listed host already requires for its own CLI.

### 4.9 CI equals the local gate (2.13)
`npm run verify` on Node 18 + 20, `check_trust_evidence.py` on every PR that touches `platforms/` or `docs/trust-validation/`.

### 4.10 Test gaps to close alongside the fixes
retire with an unlanded commit (1.1); land with only discuss-dir dirt (2.5); lookahead route at define/done (1.4); drift check with base≠landing (1.5); next-day shipment resume (2.1); failed prepare leaves STATE untouched (2.6); conflict output names files (2.8); unborn-HEAD commit with hooks (1.6); `#` in frontmatter title (1.8); `--update` on an existing project and `--hooks --claude` with existing settings (1.9); each documented deferred-approval command (1.2).

---

## 5. Not changed / rejected

- Version is 1.0.0 with no CHANGELOG — noted, not a finding; no release contract exists to break.
- Skill length (26k words) is a cost, not a defect; 2.19 and 4.2 reduce it as side effects. No separate "shorten skills" work item.
- Guard coverage for Kiro/Kimi/etc. (3.10) is a product decision, not a bug — listed for the matrix claim only.
