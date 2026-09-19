# Independent model-selection review

Reviewer: Claude Fable (`claude-fable-5-1`), requested by the owner.
Mode: read-only source review; no tests run by the reviewer.

## Disposition

| Finding | Reproduction and resolution |
|---|---|
| Pinned choices ignore differing explicit input | Reproduced with an explicit task model changed after an earlier selection. Resolution now blocks and directs to explicit reassignment. |
| Reassignment changes provenance for untouched fields | Reproduced: changing only model made default inherited effort explicit and invalidated a valid command. Unchanged sources are now preserved in native and CLI reassignment. |
| Panel choices lack per-assignment CLI scope | Reproduced the missing scope. Added `--model-overrides` mapping logical names to individual choices; tested both the targeted and untargeted families. Rejecting a common model that violates another selected family's constraint remains intentional. |
| Legacy `{model}` remains in capability-based commands | Reproduced with a mixed placeholder command. Capability-based dispatch now rejects the legacy placeholder before launch. |

All four follow-up regression tests failed on the reviewed implementation.
Each corresponding fix was then sabotaged, detected by its regression test,
and restored. Raw reproduction output is
`/tmp/gsd-model-selection-review/reproductions.log`; mutation evidence is
`/tmp/gsd-model-selection-review/sabotage.json`.

The reviewer has not performed a second review of the corrections. Corrections
are supported by reproduced cases, focused executable checks, and sabotage.

## Budget receipt

The CLI reported 19,946 output tokens, including 13,008 thinking tokens. This
exceeded the owner's 4,000-token per-task budget despite the prompt's explicit
budget instruction. The overrun is preserved. No second full review was run.

## Original review

**Verdict:** the core wiring holds up. Native and CLI paths consume one resolver, the round preflight blocks before isolation, task `model`/`effort` fields survive `check_task_briefs` and are frozen by `isolation._immutable_frontmatter` at landing, panel rosters persist per-family selections, and the installed adapters resolve the `model-policy.md` link because every skill that receives `references/dispatch.md` also receives `references/model-policy.md`. I found four concrete gaps. I did not run any tests.

**Findings**

1. **Pinned selection silently discards a differing explicit override.** `scripts/model_policy.py:78-86` ignores `overrides` entirely when `previous` is set; `scripts/dispatch_driver.py:259-266` only compares dispatch flags against the task file, never against the pinned selection. Scenario: attempt 1 of T001 pins `model=small` from `roles.coder`; a plan patch legally adds `model: large` to T001; the redispatch in `Round.dispatch_ready` (line 770) launches with `small` and records `sources.model = roles.coder`. Same shape for `panel --model X` when `roster.json` already exists. Required: validate explicit settings before launch and report the rejected setting; hard task constraints cannot be waived by precedence. Fix: in the `previous` branch, raise `PolicyError` naming the field when any explicit override differs from `previous['selected']`, directing to `reassign-model`.

2. **Reassignment rewrites provenance and can make a previously valid command block.** `scripts/dispatch_driver.py:1786-1788` and `scripts/model_policy.py:207` pass `dict(old['selected'], **changes)` as overrides, so every field becomes source `task`. Scenario: policy `{"roles":{"coder":{"model":"small"}}}`, child command has only `{model_args}` (legal: effort was default `inherit`). Run `reassign-model --model large`, then `round`. `command_args` at `scripts/model_policy.py:157-159` now sees effort explicit with no `{effort_args}` slot and blocks. History also records the untouched effort as a task override. Fix: pass only `changes` as overrides and copy the old `sources` for unchanged fields.

3. **A role-level or `--model` panel choice cannot satisfy a multi-family roster.** `scripts/dispatch_driver.py:277-286` applies one `review_panel` model to every family; `Panel.run` (lines 1339-1351) then fails `validate_panel` for any family whose slug family differs. Scenario: roster `[gpt, claude]` with `roles.review_panel.model = gpt-new`, or `panel --model gpt-new`. The panel is unrunnable rather than configurable, and the doc claim "keep each panel family a distinct assignment" has no CLI input to back it. Fix direction: reject `model` for the `review_panel` role and for the `panel` action's `--model` in `load_policy`/`selected_command` with a clear reason, or key panel model settings by family.

4. **Leftover `{model}` placeholder passes through literally when capabilities are supplied.** `scripts/dispatch_driver.py:1343-1345` and `1371-1373` substitute `{model}` only without `--model-capabilities`. Scenario: `--child-command 'codex -m {model} {model_args}'` with capabilities; the child receives `-m {model} --model gpt-new`, and the conflict check at `scripts/model_policy.py:149-154` cannot see `-m`. Required: an opaque command must not contradict the explicit choice. Fix: in `selected_command`, block when capabilities are present and any argv element still contains `{model}`.

**Uncertainty:** finding 1's plan-patch scenario assumes a task file edit reaches the retained worktree copy before redispatch; if the legal path always retires the isolate, the `panel --model` variant still reproduces.
