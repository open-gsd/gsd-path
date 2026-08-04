# GitHub Copilot CLI agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Copilot CLI's `task` tool with the built-in `general-purpose` agent.
  Every GSD Path child must be able to write its declared artifact; the linked
  role brief supplies the read-only boundary for auditors and reviewers.
- Supply the deterministic logical task name as the task description:
  `onboard_codebase`, `onboard_docs`, `docs_audit`,
  `research_<dimension>`, `synthesize`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Keep the returned agent ID for each logical task name. For a correction,
  retry, post-patch review, repeated audit, or later milestone, use
  `write_agent` when that child remains available for follow-up and send the
  entire new self-contained brief. Otherwise start a fresh `general-purpose`
  task with that brief. If the child is still running a different brief, wait;
  never create a colliding logical target.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the child to read it before acting.
- Do not override the model or ask Copilot to create another worktree. GSD
  Path supplies the exact repository or linked-worktree root, and the child
  must work only there.
- Give every child a self-contained prompt with absolute input, template, and
  output paths plus its bounded responsibility. A coder prompt also names its
  isolated linked-worktree root; no child may infer the primary worktree.
- Launch one `task` call per independent brief in parallel up to the available
  concurrency limit. Batch any remainder and collect every result before
  applying the phase gate.
- If `task` or the full-capability `general-purpose` agent is unavailable, stop
  and report the missing capability. Do not silently collapse an independence
  boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
