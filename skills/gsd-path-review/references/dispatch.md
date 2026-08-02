# Shared Agent Skills dispatch

Apply this contract whenever a GSD Path skill delegates work from the shared
`~/.agents/skills` bundle. Inspect the advertised child-agent tool schema and
use exactly one matching branch:

- A `spawn_agent` tool exposing `task_name`, `agent_type`, and `fork_turns` is
  Codex. Use `fork_turns: "none"`; coders use the built-in `worker` type and
  every other role uses `default`. Reuse a completed logical target with
  `followup_task`.
- A `spawn_agent` tool without those Codex fields is Zed. Spawn one isolated,
  full-capability child per brief. Zed children are not resumable, so retries
  use a fresh child and a complete prompt.
- A `spawn_subagent` tool advertising the `general-purpose` type is Grok. Use
  `subagent_type: general-purpose`, `capability_mode: all`, the exact supplied
  root as `cwd`, `isolation: none`, and `background: true`. Supply the logical
  task name as `description`, keep the returned ID, and use `resume_from` with
  the complete new prompt for later work. Wait for a colliding active child and
  collect results with `wait_commands_or_subagents`.
- A `Task` tool advertising the custom `gsd-path` subagent is Cursor. Use that
  model-inheriting, full-capability child. Resume it by returned agent ID when
  available; otherwise retry with a fresh child and a complete prompt.
- A `Task` tool advertising the built-in `general` subagent is OpenCode. Use
  that child; if an installed OpenCode v2 host exposes the renamed `subagent`
  tool instead, use its advertised schema with the built-in `general` agent.
  Supply the logical task name as the child description. Reuse a returned
  child-session ID only when the host advertises a resume parameter; otherwise
  use a fresh `general` child and the complete prompt.
- A `task` tool advertising the `general-purpose` child is GitHub Copilot CLI.
  Use that child. Keep its returned ID for follow-up while the host exposes
  it; otherwise retry with a fresh child and a complete prompt.
- An `invoke_sub_agent` tool with a `general-purpose` subagent is Kiro. Use
  that child for every role; there is no worker/default type split. Start a
  fresh general-purpose child for every correction, retry, post-patch review,
  repeated audit, or later milestone — Kiro subagents are not resumable and
  disk artifacts are the source of truth. Supply the logical task name as the
  task description. Set the child working directory to the exact repository or
  linked-worktree root supplied by GSD Path; do not ask Kiro or the child to
  create another worktree. Encode task dependencies explicitly; launch no more
  than four subagents at once.

For every branch:

- Supply the deterministic logical task name: `onboard_codebase`,
  `onboard_docs`, `docs_audit`, `research_<dimension>`, `synthesize`, `plan`,
  `plan_patch`, `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`,
  `review_final`, or `review_gap_<number>`. Normalize variable parts to
  lowercase ASCII and replace non-alphanumeric runs with one underscore.
  Never add a random suffix or collide with a running logical target.
- Resolve the phase's linked role brief to an absolute path, include it in the
  prompt, and require the child to read it before acting. The role brief
  supplies the read-only boundary for auditors and reviewers.
- Tier hints: when the host advertises model or reasoning-effort selection,
  request `heavy` for `plan`, `plan_patch`, and `synthesize`, `light` for
  `onboard_docs` and `docs_audit`, and the session default for every other
  role. When the host offers no such selection, do not override the model.
  Never ask the host to create a worktree. Give the child the exact
  repository or linked-worktree root supplied by GSD Path.
- Send a self-contained prompt with absolute input, template, and output paths
  plus the child's bounded responsibility. A coder prompt also names its
  isolated linked-worktree root; no child may infer the primary worktree.
- Launch independent briefs concurrently up to the advertised child capacity,
  batch any remainder without combining briefs, and collect every result
  before applying the phase gate.
- If the tool schema is ambiguous or the required full-capability child is
  unavailable, stop and report the missing capability. Do not guess the host
  or silently collapse an independence boundary into the main context.
