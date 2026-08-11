# Kiro agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- Use Kiro's subagent facility with the default general-purpose subagent.
  Every GSD Path child must be able to write its declared artifact; the linked
  role brief supplies the read-only boundary for auditors and reviewers.
- Supply the deterministic logical task name as the task description:
  `inspect_codebase`, `inspect_docs`, `docs_audit`,
  `research_<dimension>`, `decide`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`, `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Start a fresh general-purpose child for a correction, retry, post-patch
  review, repeated audit, or later milestone and send the entire new
  self-contained brief. Disk artifacts remain the source of truth.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the subagent to read it before acting.
- Do not override the model. Set the child working directory to the exact
  repository or linked-worktree root supplied by GSD Path; do not ask Kiro or
  the child to create another worktree.
- Give every child a self-contained prompt with absolute input, template, and
  output paths plus its bounded responsibility. A coder prompt also names its
  isolated linked-worktree root; no child may infer the primary worktree.
- Encode task dependencies explicitly. Launch independent ready tasks in
  parallel, with no more than four subagents at once; batch any remainder and
  collect every result before applying the phase gate.
- If the subagent facility or the default general-purpose subagent is
  unavailable, stop and report the missing capability. Do not silently
  collapse an independence boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
