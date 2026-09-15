# Token context work

## Contract

Reduce irrelevant instructions and model-managed bookkeeping without weakening
approved constraints, task isolation, review, or publication gates.

- Load build procedures and reviewer modes only when their branch applies.
- Generate coder intent context from approved files, preserving constraints,
  vetoes, corrections, source identity, and owned success criteria. Ambiguous
  input retains full intent; it must never silently lose a requirement.
- Use the existing deterministic driver for supported operations; preserve a
  native-tool path when no owner-supplied child command exists.
- Verify generated context and installed resource loading, measure before/after
  instruction size, and exercise a completed delivery before claiming runtime
  token savings.

## Baseline

Clean evaluation branch `jeremymcs/token-eval`, HEAD and live origin/main
`ca1152d69e0a8e57bdbb9ddaae00708823587e5c`; no merged PR for this branch and
no active `.project/STATE.md`. No CONTRIBUTING.md exists at this revision.

Measured with o200k_base: build plus required role/template reads 17,637 tokens;
coder role, task template, and repository AGENTS.md 7,098 tokens, before task,
intent, product source, or host context. Historical runs are evidence of prior
overhead, not a measurement of this change.

## Implementation

- Build loads the driver path first. Native dispatch/recovery and abandon are
  separate procedures. Optional review templates are loaded only on their branch.
- Reviewer modes have separate procedures with common authority and evidence rules.
- Coder briefs contain a deterministic intent view with source/task hashes. All
  non-criterion text stays verbatim, including unknown sections. Owned criteria
  and explicit SC references in task/global text are retained. Unfamiliar criteria
  formatting retains full intent. Invalid ownership fails before dispatch.
- Native coders use the existing `finish` runtime after returning; both dispatch
  paths use `complete`. This removes manual verification/landing and completion
  sequences without introducing a new orchestration engine.
- Canonical resources were synchronized into standalone skills and the alias.

## Evidence

- RED: `python3 -B -m unittest tests.test_task_context.TaskContextTests.test_dispatch_supplies_context_without_a_second_intent_read`
  failed because the existing dispatch supplied only the intent path, with no
  required criterion or global rule in the brief.
- GREEN: `python3 -B -m unittest tests.test_task_context tests.test_dispatch_contract tests.test_skill_commands tests.test_sync_skill_resources`
  passed 14 tests. This exercises generated output, ambiguous-format fallback,
  explicit cross-criterion references, invalid ownership, standalone bundled
  execution, resource synchronization, and disclosed command/name contracts.
- `python3 -B -m unittest tests.test_dispatch_driver` passed 65 tests, including
  isolated serial/parallel coding, native finish, collection, retry, and completion.
- `python3 -B -m unittest tests.test_router_contract tests.test_lean_verification`
  passed 15 tests, including final-review reuse and project verification evidence.
- Sabotage: patched `scripts.dispatch_driver.task_context.render` in a disposable
  Python process to return full intent. The dispatch contract test failed because
  it received the unrelated SC2. The patch was restored on context-manager exit.
- `python3 -B scripts/sync_skill_resources.py` completed with no divergence warnings.
- Ponytail review: reused the existing driver and handoff parser; no dependency,
  new tracking ledger, or model-based routing was added.

## Measured prompt load

See [machine counts](token-context-metrics.json). Build's initial driver path fell
from 17,637 to 2,333 o200k_base tokens. Native-path parent instructions total 12,091.
Coder fixed instructions, including repository AGENTS.md, fell from 7,098 to 6,519.
The intent view's hashes/header add input; savings depend on how many unrelated
criteria can be omitted. Small/all-owned intents may not shrink. These counts
exclude tool output, host context, caching, and model behavior.

## Open work

Fresh native fixture execution and token accounting remain pending. No runtime
token saving or whole-pipeline completion improvement is claimed from static counts.
