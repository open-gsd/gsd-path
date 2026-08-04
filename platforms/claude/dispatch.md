# Claude Code agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Claude Code's `Agent` tool with `subagent_type: general-purpose`. Every
  GSD Path child must be able to write its declared artifact, so do not use the
  one-shot `Explore` or `Plan` agents. The linked role brief supplies the
  read-only boundary for auditors and reviewers.
- Supply the deterministic logical task name as the Agent `description`:
  `onboard_codebase`, `onboard_docs`, `docs_audit`,
  `research_<dimension>`, `synthesize`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Keep the returned agent ID when the host advertises a resume facility. For a
  correction, retry, post-patch review, repeated audit, or later milestone,
  resume that child when supported; otherwise start a fresh `general-purpose`
  child. Always send the entire new self-contained brief. If a child with the
  same logical task name is still running, wait for it rather than dispatching
  a colliding target.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the agent to read it before acting.
- Do not override the model. Do not ask Claude Code to create another
  worktree: GSD Path supplies the exact repository or linked-worktree root in
  the brief, and the child must work only there.
- Give every child a self-contained prompt with absolute input, template, and
  output paths plus its bounded responsibility. A coder prompt also names its
  isolated linked-worktree root; no child may infer the primary worktree.
- Launch independent Agent calls concurrently up to the available limit, using
  background execution when exposed by the host. Batch any remainder and
  collect every result before applying the phase gate.
- If the `Agent` tool or full-capability `general-purpose` agent is unavailable,
  stop and report the missing capability. Do not silently collapse an
  independence boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
