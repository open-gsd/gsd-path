# Model-selection policy discussion

Status: implemented and verified; independent Claude Fable review findings addressed.

## Selected direction

The owner selected:

> Model-selection policy (recommended): give model and effort choices one owner across host adapters.

The outcome is an agreed policy for sub-agent model and reasoning-effort
selection. Prove the design by tracing its choices through existing dispatch
paths and naming the verification needed for changed behavior.

## Current evidence

- `platforms/shared-agents/dispatch.md:7-13,68-77`: role-based effort hints;
  canonical roles inherit their model; optional panel children may override it.
- `platforms/claude/dispatch.md:30-33`: repeated role hints expressed through
  host-dependent selection rules.
- `scripts/dispatch_driver.py:254-269`: CLI dispatch records an owner-supplied
  command; panel model substitution appears at `1273-1281`.
- `scripts/review_panel.py:183-189,255`: panel selection ranks advertised
  model names; that order is not measured task suitability.
- `tests/evaluate_codex.py:109-114`: the existing workflow comparison requires
  identical model and reasoning settings between its arms.
- `scripts/dispatch_driver.py:202-216,253-278,559-573`: a live attempt uses its
  saved command, but a new attempt takes the current owner command.
- `scripts/dispatch_driver.py:1217-1222,1259-1278`: panel continuation uses a
  saved roster with model slugs and checks the recorded revision.

## Settled decisions

### Q1 — Optimization goal

Owner answer:

> Reduce total cost, preserve quality (recommended)

Compare the cost of completing the task contract, including retries and failed
verification attempts. Lower cost does not waive task quality or proof gates.

### Q2 — Model authority

Owner answer:

> Every role, including canonical reviewers (recommended)

Explicit policy choices may select a different model for every sub-agent role.
Inheritance remains the default. Model choice does not change review authority.
This authorizes designing a replacement for the current canonical-role
inheritance restriction; the owner subsequently approved implementation.

### Q3 — Host scope

Owner answer:

> All existing host adapters (recommended)

The policy covers every existing host adapter and uses only controls the host
advertises.

### Q4 — Selection rules

Owner answer:

> Per-role choices plus explicit task overrides (recommended)

Choose the model and reasoning effort from explicit role settings, with
explicit task overrides. Do not infer a task complexity score.

### Q5 — Policy location

Owner answer:

> Project configuration (recommended)

Keep choices in project-owned configuration shared across agents and hosts.
Unconfigured roles inherit. Personal defaults are outside the selected scope.

### Q6 — Unsupported choices

Owner answer:

> Stop the affected dispatch (recommended)

If a host cannot honor an explicit model or effort choice, stop that dispatch
with a clear reason. Do not substitute another choice. An unconfigured role
continues to use inheritance.

### Q7 — Unconfigured effort

Owner answer:

> Preserve existing effort hints (recommended)

Unconfigured roles retain their current portable effort hints and host
translations. Their models continue to inherit by default. Existing hints
remain conditional on host support; explicit unsupported settings stop dispatch.

### Q8 — Initial model assignments

Owner answer:

> Policy controls; explicit project assignments (recommended)

The first version supplies policy controls and accepts explicit project
assignments. It does not ship cost-saving presets or run live model comparisons.

### Q9 — Policy changes during work

Owner answer:

> Keep the choice until explicit reassignment (recommended)

Persist each assignment's selected model and effort across resumes and retries.
Project policy edits affect new assignments. An explicit reassignment records
a new selection without rewriting the earlier attempt's evidence.

## Proposed implementation contract

The following mechanics implement the decisions above and were approved by the owner. File formats and helper commands must follow existing project
conventions; they are not additional product choices.

### Selection and precedence

- One deterministic model-selection module owns role defaults, explicit
  settings, capability validation, and the reason for each result.
- Keep project configuration separate from phase status. Allow host-specific
  role settings because native model and effort identifiers differ by host.
- Resolve model and effort independently: explicit task setting, then project
  role setting, then existing default behavior. An explicit inherit value
  clears an override for that field; omission keeps the next applicable value.
- An override belongs to the named assignment. A coder override does not
  silently alter its reviewer or a later task.
- Task overrides use the existing task contract. Overrides for non-coder
  assignments use their explicit dispatch input and recorded assignment.
- Hard task constraints and review-family requirements remain mandatory;
  selection precedence cannot waive them.

### Module and adapters

The model-selection module's interface accepts the assignment, applicable
settings, and advertised host capabilities. It returns a validated selection
with provenance or a clear blocked result. It does not dispatch work itself.

Native and CLI adapters translate the validated result to supported host
controls. They do not duplicate selection policy. An opaque CLI command must
not bypass or contradict an explicit choice; block when the adapter cannot
apply and establish that choice. Do not rewrite arbitrary command strings by
guessing their syntax.

The panel module continues to own membership and review authority. Explicit
model choices must satisfy its family rules; unconfigured panels retain their
existing selection behavior. Validate independence using known model identities,
including the canonical reviewer when it has an explicit different model.

This seam is real: both native and CLI dispatch consume the same selection.
Depth comes from removing policy knowledge from callers. A configuration file
that leaves the choices duplicated in adapter prose does not meet the contract.

### Dispatch and persistence

- Validate explicit settings before launching the affected child. Report the
  assignment, rejected setting, host capability mismatch, and setting source.
- Persist selected controls and their sources with the assignment before
  launch. Record the effective model identity when the host exposes it.
- Keep the selection attached to the existing assignment identity across
  retries, interruptions, and resumes. Scope identities to their milestone,
  track, and review cycle where applicable so later work cannot reuse stale
  choices merely because its logical role name matches.
- A policy edit does not alter a live or resumable assignment. Reassignment
  requires explicit owner direction and a record linking old and new choices.
  It must not create a second child while the earlier child remains active.
- Reassignment does not authorize changes to an approved task contract;
  contract changes still use the existing legal pipeline path.
- If a resumed host cannot honor the recorded explicit selection, stop that
  dispatch. Do not switch to an available substitute.
- Distinguish pinning requested controls from proving the effective model.
  Some hosts hide the inherited model identity. Record that limitation and
  do not claim an exact model match across fresh children without evidence.

### Change scope and proof

| Area | Required result | Verification |
|---|---|---|
| Shared selection module | Deterministic precedence and provenance; inherited defaults preserved | Exercise the selection interface with role choices, partial task overrides, explicit inheritance, and invalid settings |
| Existing host adapters | Every installed adapter consumes the same policy; uses advertised controls only | Enumerate hosts from the installation manifest and check emitted native arguments or CLI arguments against supported and unsupported capability fixtures |
| Dispatch persistence | Policy edits do not change existing assignments; explicit reassignment retains history | Resume and retry with changed configuration, including inherited settings and unavailable recorded choices |
| Task contracts | Overrides are validated and cannot be edited by a coder during landing | Extend task-parser and immutable-contract coverage; retain recovery evidence checks |
| Review panels | Canonical authority, family independence, and saved roster remain valid | Preserve existing roster tests; test explicit choices that conflict with family requirements |
| Distribution | Canonical helper, templates, and dispatch instructions reach every applicable skill | Update resource declarations, generate copies, and run synchronization checks |

Use executable adapter fixtures for hosts unavailable during implementation;
report those as fixture coverage, not live host verification. Run focused
checks for changed contracts, then the repository's required delivery gates.
Do not claim cost reduction from successful policy resolution alone.

### Compatibility and limits of the outcome

With no project configuration or task overrides, preserve current model
inheritance, effort hints, and optional panel behavior. No model ranking,
pricing catalog, automatic fallback, task complexity classifier, personal
configuration, or automatic budget-driven reassignment is part of this version.

Existing parser evidence: `scripts/check_handoffs.py:125-167` accepts scalar
frontmatter additions; `scripts/isolation.py:795-796,1310-1327` protects
non-lifecycle task fields. `scripts/build_recovery.py:226-259` compares task
bytes before reusing review evidence. These contracts must survive the change.

## Next action

Owner confirmation: "Matches—proceed with implementation (recommended)".
Executable verification and the requested independent Claude Fable review are
recorded in [verification](model-selection-verification.md) and
[review dispositions](model-selection-review.md). There are no unanswered policy questions
from Q1 through Q9; exact effective-model visibility remains host-dependent.

The selected policy controls are not evidence of cost savings by themselves.

## Constraints retained

- Selection must use advertised host capabilities.
- Routing and selection rules belong in deterministic code.
- Task isolation, verification, and review authority remain intact.
- No model ranking, savings claim, new limit, or default has been approved.

## Evidence status

The architecture review used source inspection. Its HTML report was opened
and checked in Orca. No live model comparison or product tests were run.
