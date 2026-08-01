---
name: gsd-path-research
description: Dispatch parallel researchers and collect cited GSD Path evidence about domain, stack, pitfalls, and comparable products. Use only when the user explicitly invokes $gsd-path-research or an active $gsd-path router explicitly routes to this phase.
---

# GSD Path Research Phase

Dispatch independent researchers and gate their evidence. Keep synthesis out
of this phase.

Any instruction below to route, return, or invoke another GSD Path phase is a
caller handoff, not permission to trigger an explicit-only skill. If an active
router or orchestrator supplied this contract, return control to it. On a
direct invocation, report the exact next skill and stop until the user
explicitly invokes it.

## Preconditions

Require `pipeline: gsd-path/v1` in `.project/STATE.md`; a missing or different
marker returns to `$gsd-path` for ownership checking. Legal entry is
`grill/done` (transition to `research/active`) or `research/active|blocked`;
`research/done` or any later phase blocks rather than replacing settled
evidence beneath downstream artifacts. Require
`.project/intent/INTENT.md`. If it is missing, stop and route to
`$gsd-path-grill`. Confirm live search or web-reading capability before
dispatch; if unavailable, block rather than allowing memory-based citations.

## Dispatch contract

Read the local [researcher role](references/researcher.md), then follow the
shared [Codex dispatch contract](references/dispatch.md) with built-in
`agent_type: default` and `fork_turns: "none"`. Resolve the local
[evidence template](templates/evidence.md) to an absolute path and
include it, the absolute role and INTENT.md paths, the dimension, assigned
questions, deterministic `task_name: research_<dimension>`, and exact output
path in every brief. When `evidence-codebase.md` exists, include its absolute
path in every brief as settled brownfield input.

## Process

1. Read INTENT.md. Extract constraints, vetoes, risks, and `RESEARCH`
   questions. Assign every research question to at least one dimension and
   record that assignment before dispatch; no question may remain unassigned.
2. Spawn the four standard dimensions:

   | Dimension | Output file | Focus |
   | --- | --- | --- |
   | domain | `evidence-domain.md` | prior art, domain rules, terminology, practitioner expectations |
   | stack | `evidence-stack.md` | two or three viable stacks against the constraints |
   | pitfalls | `evidence-pitfalls.md` | security, scale, reliability, and UX failure modes |
   | similar | `evidence-similar.md` | comparable products and reusable lessons |

   Dispatch up to the available child capacity, then dispatch each remaining
   dimension when a slot opens. Keep all four briefs independent.

   In brownfield work, require stack research to weigh migration cost and
   pitfalls research to check which failure modes already exist in the mapped
   codebase.

3. If a risk needs a distinct dimension, add one researcher, up to five total.
   Derive its filename deterministically as `evidence-<dimension-slug>.md`:
   lowercase the label, replace non-alphanumeric runs with one hyphen, and
   trim hyphens. Append `-2` only if it collides with an existing dimension.
4. Validate every expected evidence file after all agents finish. Confirm
   every extracted `RESEARCH` question was assigned and answered. Require at
   least one `## Finding`, and require Claim, Source, Confidence, and Why it
   matters fields for every finding.
5. Send one corrective follow-up to an agent whose file is missing or invalid.
   If any expected file still fails, set STATE.md to `phase: research`,
   `status: blocked`, list the failures in the log, and stop. Never advance
   with partial research.
6. When all expected files pass, set STATE.md to `phase: research`,
   `status: done`, and append the transition log. When routed by an active
   `$gsd-path`, return control to that router. When invoked directly, stop and
   tell the user to explicitly invoke `$gsd-path` or `$gsd-path-synthesize`;
   do not invoke an explicit-only sibling skill yourself.

## Rules

- Require evidence, not opinion: every claim needs a source actually checked
  and a one-line tie-back to this project's intent.
- Record conflicting sources rather than resolving them here.
- Preserve dead ends and explicit `no reliable source found` answers.
- Do not summarize the evidence; `$gsd-path-synthesize` owns that work.
