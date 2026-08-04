# Codex agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use the Codex collaboration tool with an explicit built-in `agent_type` and
  `fork_turns: "none"`. Coders use `worker`; every other role uses `default`.
- Supply a deterministic `task_name`: `onboard_codebase`, `onboard_docs`,
  `docs_audit`, `research_<dimension>`, `synthesize`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix. Before spawning, inspect existing agents: if that exact target was
  used earlier in this durable conversation, reuse it with `followup_task` and
  send the entire new self-contained brief, for corrections, retries,
  post-patch reviews, repeated audits, and later milestones alike. If it is
  still running a different brief, wait; never create a colliding alias.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the message and require the agent to read it before acting.
- Do not override the model or reasoning effort.
- Give the agent a self-contained brief with absolute input, template, and
  output paths plus its bounded responsibility. A coder brief also names its
  isolated linked-worktree root; no agent may infer the primary worktree.
- Spawn independent agents up to the available child capacity. If briefs
  outnumber slots, dispatch them in batches without combining briefs. Collect
  every result before applying the phase gate.
- If collaboration tooling or the required built-in agent type is unavailable,
  stop and report the missing capability. Do not silently collapse an
  independence boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
