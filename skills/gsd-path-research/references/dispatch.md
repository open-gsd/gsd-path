# Shared Agent Skills dispatch

Apply this contract whenever a GSD Path skill delegates work from the shared
`~/.agents/skills` bundle. Inspect the advertised child-agent tool schema and
use exactly one matching branch:

- A `spawn_agent` tool exposing `task_name`, `agent_type`, and `fork_turns` is
  Codex. Use `fork_turns: "none"`; coders use the built-in `worker` type and
  every other role uses `default`. Reuse a completed logical target with
  `followup_task`. For Codex reasoning effort, use `high` for the portable
  `heavy` tier and `low` for the portable `light` tier; leave reasoning effort
  unset for the session-default tier, and never pass `heavy` or `light` as a
  literal Codex value.
- A `spawn_agent` tool without those Codex fields is Zed. Spawn one isolated,
  full-capability child per brief. Zed children are not resumable, so retries
  use a fresh child and a complete prompt.
- An `invoke_subagent` tool advertising `TypeName`, `Workspace`, and `Role` is
  Antigravity. Use `TypeName: self`, the exact supplied root as `Workspace`,
  and the logical task name as `Role`. Keep the returned child ID and use
  `send_message` for follow-up work when available; otherwise start a fresh
  child with the complete prompt.
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
  create another worktree. Encode task dependencies explicitly; launch
  independent children concurrently up to the host's advertised
  concurrent-subagent capacity.

For every branch:

- Supply the deterministic logical task name: `inspect_codebase`,
  `inspect_docs`, `docs_audit`, `research_<dimension>`, `decide`, `roadmap`,
  `plan`,
  `plan_patch`, `build_<task_id>`, `review_wave_<wave>_cycle_<cycle>`
  (a `deep` wave review appends the lens suffix `_contract` or
  `_adversarial`; an optional review panel uses
  `review_wave_<wave>_cycle_<cycle>_panel_<family>`; an optional finding
  skeptic uses `review_wave_<wave>_cycle_<cycle>_skeptic_<criterion_locator>`),
  `review_plan_panel_<family>`,
  `review_final`, or `review_gap_<number>`. Normalize variable parts to
  lowercase ASCII and replace non-alphanumeric runs with one underscore.
  Never add a random suffix or collide with a running logical target.
- Resolve the phase's linked role brief to an absolute path, include it in the
  prompt, and require the child to read it before acting. The role brief
  supplies the read-only boundary for auditors and reviewers.
- Tier hints: use the portable `heavy` tier for `plan`, `plan_patch`, `decide`,
  and `roadmap`, the portable `light` tier for `inspect_docs` and `docs_audit`,
  and the session-default tier for every other role. Apply the Codex mapping
  above when its schema advertises reasoning-effort selection. On every other
  host, use only an exact native equivalent advertised by that host; otherwise
  do not override the model or reasoning effort. The only exception is a
  review-panel child: when the host advertises model selection, pass the exact
  slug returned by `scripts/review_panel.py resolve` for that family. Never
  override the model on the canonical reviewer, planner, coder, or any other
  role.
  Host isolation: none. The child's working directory is the exact absolute
  root GSD Path supplied; a host SHA checkout or extra worktree is a contract
  failure. Never ask the host to create a worktree. Give the child the exact
  repository or linked-worktree root supplied by GSD Path.
- Send a self-contained prompt with absolute input, template, and output paths
  plus the child's bounded responsibility. Every brief also names the absolute
  `AGENTS.md` and `WORKFLOW.md` paths (or explicitly says they are absent), the
  next phase that consumes the output, the gate it must satisfy, and the
  terminal result it must return. A coder prompt also names its isolated
  linked-worktree root; no child may infer the primary worktree.
- The parent is the sole dispatcher and lifecycle owner. If the runtime exposes
  structured Run/Task/Dispatch orchestration, bind one Run, create one Task per
  independent brief with explicit dependencies, inject the brief, and wait for
  every `worker_done`, `escalation`, or question before applying the gate.
  Verify the task and dispatch records before reporting the work as
  orchestrated. On runtimes without that layer, use the host adapter's
  equivalent and preserve the same logical name, completion state,
  timeout/cancellation, and cleanup rules; never silently delegate again from a
  child.
- When the structured layer exposes a blocking ask/reply channel, route a
  coder's `NEEDS-ORCHESTRATOR` question through it as a live question with
  the worker held alive for the reply, instead of block-and-redispatch. The
  answer is still appended to the task Log as
  `Orchestrator answer:` so the portable on-disk record stays complete, and a
  timed-out or unavailable channel falls back to the portable block path.
- A child that receives a disposable worktree stages its assigned artifact
  under that root. The parent validates it and atomically transfers it to the
  canonical project path before removing the exact disposable root. A child
  never writes a disposable-review output directly into the primary worktree.
- Launch independent briefs concurrently up to the advertised child capacity,
  batch any remainder without combining briefs, and collect every result
  before applying the phase gate. Do not leave an active child, logical task, or
  temporary worktree after collection; a timeout or cancellation is a blocked
  result, not a silent success.
- If the tool schema is ambiguous or the required full-capability child is
  unavailable, stop and report the missing capability. Do not guess the host
  or silently collapse an independence boundary into the main context.
