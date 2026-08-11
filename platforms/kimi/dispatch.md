# Kimi agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Kimi's `Agent` tool with `subagent_type: coder` for every child. Every
  GSD Path child must write its declared artifact, and `coder` is the only
  type with file-editing tools; never use `explore` or `plan` children for
  artifact-producing work. The linked role brief supplies the read-only
  boundary for auditors and reviewers.
- Supply the deterministic logical task name as the Agent `description`:
  `inspect_codebase`, `inspect_docs`, `docs_audit`,
  `research_<dimension>`, `decide`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Keep the returned agent ID for each logical task name. For a correction,
  retry, post-patch review, repeated audit, or later milestone in the same
  conversation, resume that agent through the `resume` parameter and send
  the entire new self-contained brief. If it is still running a different
  brief, wait for it; never create a colliding logical target.
- Resolve the phase's linked role brief to an absolute path. Include that
  path in the prompt and require the child to read it before acting.
- Do not override the model. Do not ask Kimi to create a worktree: GSD Path
  supplies the exact repository or linked-worktree root in the brief, and
  the child must work only there.
- Give every child a self-contained prompt with absolute input, template,
  and output paths plus its bounded responsibility. A coder prompt also
  names its isolated linked-worktree root; no child may infer the primary
  worktree.
- Launch independent `Agent` calls concurrently in one block, up to the
  available limit. Batch any remainder without combining briefs, and collect
  every result before applying the phase gate. Do not leave children running
  after collection.
- If the `Agent` tool or the `coder` child type is unavailable, stop and
  report the missing capability. Do not silently collapse an independence
  boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
