# Grok agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Grok's `spawn_subagent` tool with `subagent_type: general-purpose` and
  `capability_mode: all`. Every GSD Path child must be able to write its
  declared artifact; the linked role brief supplies the read-only boundary for
  auditors and reviewers.
- Supply the deterministic logical task name as the subagent `description`:
  `onboard_codebase`, `onboard_docs`, `docs_audit`,
  `research_<dimension>`, `synthesize`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Keep the returned subagent ID for each logical task name. For a correction,
  retry, post-patch review, repeated audit, or later milestone in the same
  conversation, call `spawn_subagent` with `resume_from` and the entire new
  self-contained prompt. If it is still running a different brief, wait for
  it; never create a colliding logical target.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the subagent to read it before acting.
- Do not override the model or reasoning effort. Set `cwd` to the exact root
  supplied by GSD Path and use `isolation: none`; the pipeline already owns any
  required linked worktree.
- Give every subagent a self-contained prompt with absolute input, template,
  and output paths plus its bounded responsibility. A coder prompt also names
  its isolated linked-worktree root; no child may infer the primary worktree.
- Launch independent subagents with `background: true` up to the available
  limit. Batch any remainder, wait with `wait_commands_or_subagents`, and
  collect every result before applying the phase gate.
- If `spawn_subagent` or the `general-purpose` type is unavailable, stop and
  report the missing capability. Do not silently collapse an independence
  boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
