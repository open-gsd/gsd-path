# Dispatch model policy

Before native dispatch, run the bundled `scripts/model_policy.py`. CLI dispatch
uses the same resolver inside `dispatch_driver.py`. The helper owns model and
effort decisions; apply its output instead of choosing again in prose.

## Project choices

Use `<repo>/.project/model-policy.json`, including when the active track is
`.project/next`. Configuration is project-owned. It is not phase status.
No file is required to retain existing behavior.

```json
{
  "roles": {"coder": {"model": "inherit"}},
  "hosts": {"codex": {"plan": {"effort": "high"}}}
}
```

Values are exact advertised model/effort strings or `inherit`. This example
illustrates configuration; it is not a cost-saving preset. Set concrete models
only from the current host's advertised choices. Host-specific role settings
override common role settings. Task settings override both, independently for
model and effort; omitted fields retain the next applicable value. Explicit
`inherit` removes that field's override. There are no automatic fallbacks.

Role keys are `coder`, `reviewer` (wave, final, and gap review), `review_panel`,
`skeptic`, `inspect_codebase`, `inspect_docs`, `docs_audit`, `research`, `decide`,
`roadmap`, `plan`, and `plan_patch`. Use the logical task name as the assignment,
not as the role. Keep each panel family and review lens a distinct assignment.

The helper retains heavy effort hints for plan, plan_patch, decide, and roadmap;
light hints for inspect_docs and docs_audit; otherwise effort inherits. Codex
maps these hints to high/low. Other hosts use only advertised equivalents.
Hints are conditional; unsupported explicit settings stop the affected child.

Coders may have scalar `model:` and `effort:` fields in their task frontmatter.
These are part of the approved task contract. Pass the task file with `--task`.
For other roles, pass assignment-specific `--model` or `--effort` when the owner
explicitly overrides the role choice. Coder settings do not affect reviewers.

## Advertised capabilities

Capture the current child tool's schema and advertised choices in a JSON file
outside the product tree. For each supported control, provide its native field,
allowed values, and, for CLI dispatch, its documented argument template. Omit
unsupported controls. The values below are fixture examples, not a host catalog:

```json
{
  "host": "codex",
  "model": {"field": "model", "values": ["example-model"],
            "args": ["--model", "{value}"]},
  "effort": {"field": "reasoning_effort", "values": ["low", "high"],
             "args": ["-c", "model_reasoning_effort={value}"]}
}
```

`effort_hints` may map heavy/light to exact advertised equivalents. Supply
`inherited_model` only when the host exposes its identity. Never infer models,
fields, or CLI flags from a host name. Every existing host uses this contract,
including hosts with no model or effort controls. Their explicit unsupported
settings block; their default inheritance remains usable.

## Native lifecycle

Resolve the bundled helper to an absolute path. Use one record under the Git
common directory's `gsd-path/model-selection/` directory per assignment. Scope
the path and `--scope` to the milestone, active/lookahead track, and review cycle
where applicable; later work must not reuse an earlier record.

```text
python3 -B <helper> resolve --repo <primary> --scope <milestone/track/cycle> --assignment <logical-name> --role <role> --record <absolute-record> --capabilities <advertised-json>
```

Only `status: ready` authorizes launch. Apply `selection.native` exactly to
the advertised child tool, preserving the host adapter's other controls and
GSD Path task isolation. The recorded selection applies to a fresh child too.
If an existing child is still active, reattach or send its continuation;
resolving again does not authorize launching a second copy. When a host cannot
change model/effort on a resumed child, a changed selection requires a fresh
child after terminal completion of the earlier one.

After terminal completion, release the assignment with `release` using the
same identity arguments and `--terminal-result <host-completion-evidence>`.
To change the selection, use `reassign` with the same identity, current
capabilities, explicit model/effort changes, and `--ruling <verbatim-owner-ruling>`.
It requires an inactive assignment and preserves prior selection history.
Resolve again before starting the replacement. A project-policy edit alone
does not change an existing selection. Task-contract edits still require their
legal pipeline path.

For panel children, first resolve membership with `review_panel.py resolve`,
passing `--parent-slug` when known and repeating `--exclude-family` for every
known parent and canonical-reviewer family (including all deep review lenses).
Apply these exclusions before persisting membership. Detected membership skips
excluded families; explicitly named conflicts block. Pass its selected model through `--panel-model`, and pass `--panel-family` plus
`--exclude-family` for known parent and
canonical-reviewer families. Persist and reuse the panel roster. Policy cannot
waive family independence or change canonical review authority. A changed
panel roster requires a new legal review assignment.

Requested controls are durable evidence. When the host hides the inherited
model identity, exact effective-model continuity across fresh children remains
unproven; report that limitation rather than asserting an identity.

## CLI lifecycle

Pass `--model-capabilities <advertised-json>` to the driver. Commands use whole
argument slots `{model_args}` and `{effort_args}`; the resolver expands these
to argument arrays. They are not shell substitutions. Remove fixed model and
effort flags when using these slots; conflicting controls block dispatch.
Commands with explicit policy choices must expose the corresponding slots,
including when an explicit choice is `inherit`. Unconfigured legacy commands
without a capability file retain their existing behavior.
An existing legacy assignment with no recorded selection keeps its saved
command across retries, even if project policy or capabilities are later added.
It cannot use `reassign-model`; model controls require a new explicit assignment.

Review and skeptic commands accept `--model` and `--effort` for that assignment.
For distinct panel families or review lenses, pass `--model-overrides <json>`:
a mapping from exact logical assignment names to model/effort objects. Each
entry applies only to its named assignment; conflicting explicit inputs block.
A common panel model must satisfy every selected family, so use these scoped
overrides when families need different models. Family checks remain mandatory.
Coders read their task overrides. Panels with capabilities use the argument
slots; legacy panel commands may retain their existing `{model}` placeholder.

The driver persists selection before launch and retains it on retry. Use
`dispatch_driver.py reassign-model --repo <primary> --task-id <logical-name>
--model-capabilities <advertised-json> --model <slug> --ruling <owner-ruling>`
for an inactive unfinished assignment. Finished work and pinned panel rosters
require a new legal assignment. Earlier attempt evidence is retained.

Compare total cost only with observed usage and outcomes, including retries.
These controls do not establish cost savings, pricing, or quality rankings.
