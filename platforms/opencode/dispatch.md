# OpenCode agent dispatch

Apply this contract whenever a GSD Path skill delegates work:

- On current OpenCode, use the `Task` tool with the built-in `general`
  subagent. If the installed OpenCode v2 host exposes the renamed `subagent`
  tool instead, use that tool with the built-in `general` agent and its
  advertised schema. Every GSD Path child must be able to write its declared
  artifact; the linked role brief supplies the read-only boundary for auditors
  and reviewers.
- Supply the deterministic logical task name as the child description:
  `inspect_codebase`, `inspect_docs`, `docs_audit`,
  `research_<dimension>`, `decide`, `roadmap`, `plan`, `plan_patch`,
  `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>` (a `deep` wave review
  appends the lens suffix `_contract` or `_adversarial`; an optional review
  panel uses `review_wave_<wave>_cycle_<cycle>_panel_<family>`; an
  optional finding skeptic uses
  `review_wave_<wave>_cycle_<cycle>_skeptic_<criterion_locator>`),
  `review_plan_panel_<family>`,
  `review_final`, or
  `review_gap_<number>`. Normalize variable parts to lowercase ASCII and
  replace non-alphanumeric runs with one underscore. Never add a random
  suffix.
- Reuse a returned child-session ID when the host exposes a resume parameter.
  Otherwise start a fresh `general` child for a correction, retry, post-patch
  review, repeated audit, or later milestone and send the entire new
  self-contained prompt. Disk artifacts, not child chat history, remain the
  source of truth.
- Resolve the phase's linked role brief to an absolute path. Include that path
  in the prompt and require the child to read it before acting.
- Model selection: before every child launch or continuation, follow
  [the model-policy contract](model-policy.md) and apply its recorded
  native arguments. It owns defaults, project settings, task overrides,
  capability failures, and reassignment. Host isolation: none. Use the exact GSD Path supplied root; create no extra checkout.
- Give every child a self-contained prompt with
  absolute repository, input, template, and output paths plus its bounded
  responsibility. A coder prompt also names its isolated linked-worktree root;
  no child may infer the primary worktree.
- Launch one child call per independent brief in the same turn up to the
  available limit. Batch any remainder and collect every result before
  applying the phase gate.
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
- If neither supported child tool nor the full-capability `general` subagent is
  available, stop and report the missing capability. Do not silently collapse
  an independence boundary into the main context.

## Parent lifecycle

The parent owns lifecycle: wait for terminal completion, enforce timeout and
cancellation, transfer staged outputs from disposable roots, clean up every
child and temporary root before the phase gate, and never let a child delegate
another GSD Path child. A timeout or cancellation is a blocked result.
