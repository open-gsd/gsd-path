# Zed agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Zed's `spawn_agent` tool to create an isolated child. Every GSD Path
  child must be able to write its declared artifact; the linked role brief
  supplies the read-only boundary for auditors and reviewers.
- Supply the deterministic logical task name as the child description:
  `onboard_codebase`, `onboard_docs`, `docs_audit`,
  `research_<dimension>`, `synthesize`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Spawn a fresh isolated child for a correction, retry, post-patch review,
  repeated audit, or later milestone and send the entire new self-contained
  brief. Disk artifacts, not child chat history, remain the source of truth.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the child to read it before acting.
- Do not override the model. Set the child working directory to the exact
  repository or linked-worktree root supplied by GSD Path; do not ask Zed or
  the child to create another worktree.
- Give every child a self-contained prompt with absolute input, template, and
  output paths plus its bounded responsibility. A coder prompt also names its
  isolated linked-worktree root; no child may infer the primary worktree.
- Launch one isolated child per independent brief up to the available limit.
  Batch any remainder and collect every result before applying the phase gate.
- If `spawn_agent` or an isolated full-capability child is unavailable, stop
  and report the missing capability. Do not silently collapse an independence
  boundary into the main context.
