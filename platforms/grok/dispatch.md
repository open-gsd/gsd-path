# Grok agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Grok's `spawn_subagent` tool with `subagent_type: general-purpose` and
  `capability_mode: all`. Every GSD Path child must be able to write its
  declared artifact; the linked role brief supplies the read-only boundary for
  auditors and reviewers.
- Supply the deterministic logical task name as the subagent `description`:
  `inspect_codebase`, `inspect_docs`, `docs_audit`,
  `research_<dimension>`, `decide`, `roadmap`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>` (a `deep` wave review
  appends the lens suffix `_contract` or `_adversarial`; an optional review
  panel uses `review_wave_<wave>_cycle_<cycle>_panel_<family>`),
  `review_plan_panel_<family>`,
  `review_final`, or
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
- Tier hints: when the host advertises model or reasoning-effort selection,
  request `heavy` for `plan`, `plan_patch`, `decide`, and `roadmap`, and
  `light` for `inspect_docs` and `docs_audit`; when it offers no such
  selection, do not override the model except on a review-panel child, which receives the exact slug from `scripts/review_panel.py resolve`. Set `cwd` to the exact root supplied
  by GSD Path and use `isolation: none`; the pipeline already owns any
  required linked worktree. Host isolation: none.
- Give every subagent a self-contained prompt with absolute input, template,
  and output paths plus its bounded responsibility. A coder prompt also names
  its isolated linked-worktree root; no child may infer the primary worktree.
- Launch independent subagents with `background: true` up to the available
  limit. Batch any remainder, wait with `wait_commands_or_subagents`, and
  collect every result before applying the phase gate.
- When the host exposes a blocking ask/reply channel, route a coder's
  `NEEDS-ORCHESTRATOR` question through it as a live question with the worker
  held alive for the reply, instead of block-and-redispatch. Append the
  answer to the task Log as `Orchestrator answer:` so the portable on-disk
  record stays complete; a timed-out or unavailable channel falls back to
  the portable block path.
- A child that receives a disposable worktree stages its assigned artifact
  under that root. The parent validates it and atomically transfers it to
  the canonical project path before removing the exact disposable root. A
  child never writes a disposable-review output directly into the primary
  worktree.
- If `spawn_subagent` or the `general-purpose` type is unavailable, stop and
  report the missing capability. Do not silently collapse an independence
  boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
