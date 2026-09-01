---
name: gsd-path-discuss
description: Hold an explicit, evidence-grounded discussion about an active GSD Path milestone from any phase, preserve the verbatim dialogue and answer records under .project/discuss/, use local code and existing artifacts before focused research, challenge unsupported assumptions, and identify the phase owner for follow-up. Use only when the user explicitly invokes $gsd-path-discuss or /gsd-path-discuss to ask questions, explore a decision, request a progress explanation, or close a discussion without advancing the pipeline.
---

# GSD Path Discussion

Use this skill as an interruptible sidecar to the active GSD Path pipeline. Keep
the conversation in the main user thread, ground claims in the repository and
the current phase artifacts, and save the exchange before returning the answer.

An instruction to route to another phase is a caller handoff, not permission to trigger an explicit-only skill. Return control to the active router or tell the
user which phase owns the follow-up; do not invoke a sibling phase implicitly.

## Preconditions and ownership

1. Resolve the project root from the working directory. Read `AGENTS.md`,
   `WORKFLOW.md`, and `.project/STATE.md` before answering.
2. Require a real `.project/STATE.md` whose frontmatter contains
   `pipeline: gsd-path/v2`. If it is missing, foreign, malformed, or a
   symlink, stop and tell the user to invoke `$gsd-path` for ownership recovery.
   Do not create state merely to hold a discussion.
3. Accept any active milestone phase except `shipped`: inspect,
   define, research, decide, roadmap, plan, build, or ship. Use the
   state status currently recorded on disk. A shipped milestone is archived and must not be
   reopened by this sidecar; start a new milestone first.
4. Resolve the bundled `scripts/discussion_records.py`,
   [dialogue template](templates/dialogue.md), and
   [answers template](templates/answers.md) to absolute paths. Run its `prepare`
   command with the absolute repository and template paths before reading any
   records. This deterministic helper validates STATE ownership, locks STATE,
   recovers interrupted paired appends, restores an uncommitted review archive
   without editing it, creates the exact record pair when absent, and fails on
   stale or malformed state. Do not reproduce those operations manually.
5. Read only the helper-returned absolute DIALOGUE.md and ANSWERS.md paths.
6. Do not change `STATE.md`, phase status, `INTENT.md`, `SYNTHESIS.md`,
   `PLAN.md`, task frontmatter, review verdicts, or archive
   contents. Discussion can propose a change and name its owner; the owning
   phase must apply it through its normal gate.

The helper serializes writers and rechecks STATE immediately before a paired
publication. Never commit the records: the current phase orchestrator is their
checkpoint owner and includes them as append-only bookkeeping in its next
normal `.project/` checkpoint. The answer's named next owner separately owns
the target artifact and disposition receipt.

## Grounding and pushback

Use the authority order from `AGENTS.md`:

- Treat the user's current words as the question, but treat intent vetoes and
  recorded corrections as hard constraints.
- Treat settled synthesis decisions and the current plan/task contract as
  governing phase inputs. Surface a conflict; never average sources or quietly
  override a gate.
- Inspect the relevant implementation, callers, tests, and phase artifacts.
  Use search to locate evidence, then read the code or run an allowed,
  meaningful check before claiming behavior. Cite exact repository paths and
  line numbers when practical. Never describe an unrun command as passing.
- Separate observed fact, inference, recommendation, and user decision. If the
  premise is weak, push back plainly with the evidence and explain the smallest
  safer alternative.

Read only the phase-specific inputs needed for the question:

| Phase | Start with |
| --- | --- |
| inspect | codebase map and docs audit |
| define | intent and inspection evidence |
| research | intent, research manifest, and relevant evidence |
| decide | intent, evidence, and synthesis |
| roadmap | charter, program synthesis, and the roadmap |
| `plan` | intent, synthesis, plan, and affected task contracts |
| `build` | intent, synthesis, plan, task frontmatter/logs, wave reviews, and STATE log |
| ship | intent, plan, task frontmatter, STATE log, and relevant review artifacts |

Then inspect the code that can prove or disprove the claim. Do not reread the
whole repository when a focused path set answers the question.

## Focused research

Use existing `.project/research/` evidence first. If the question depends on a
current external fact, an unfamiliar library behavior, or an unresolved intent
risk, perform focused research during the discussion when the required search
or source-reading capability is available. Record the query/scope, checked
sources, and confidence in the answer record.

Do not launch the full `$gsd-path-research` phase from this sidecar. That phase
owns a legal state transition and a gated `RESEARCH.md` handoff; invoking it
from an arbitrary phase would bypass the pipeline contract. If the result must
become formal milestone evidence, record a `[RESEARCH]` follow-up and name
`gsd-path-research` as the next owner. If research is unavailable, mark the
answer `NEEDS-USER` or `unverifiable` instead of filling the gap from memory.

## Discussion loop

For each invocation:

1. Identify the current phase/status and discussion thread. Run the helper's
   `threads` command to list existing thread ids, topics, and statuses; do not
   parse DIALOGUE.md for them. Reuse a stable thread id
   (`T###`) when the user is continuing a topic; request `new` for a
   distinct topic and let the helper allocate its id. Classify the
   request as a fact check, diagnosis, decision, challenge, progress question,
   or follow-up request.
2. Gather the smallest sufficient local evidence, then focused research only
   when needed. Record conflicts and uncertainty before forming a conclusion.
3. Answer in the main conversation. State the conclusion first, then the
   reasoning, evidence, pushback or alternatives, confidence, and the phase
   owner for any action. When a formal follow-up is required, tell the user to
   invoke `$gsd-path`; the router will route the pending answer to that owner.
   Do not leave the user with only an owner name or direct phase command. Ask
   only the next question required to resolve the user's decision; use the
   host's interactive input facility when available.
4. Before returning, provide the semantic turn fields to the helper's `append`
   command as one JSON object via `--input`, passing the same absolute template
   paths as `prepare`. The object requires these non-empty fields:
   `topic`, `user`, `assistant`,
   `question`, `status`, `thread_status`, `conclusion`, `reasoning`,
   `evidence`, `research`, `confidence`, `unresolved`, `next_owner`,
   `target_artifact`, and `follow_up`. `thread` is optional: pass an existing
   `T###` id to continue a thread, or omit it (or pass `new`) to let the
   helper allocate the next thread id. An optional `date` field overrides the
   record date (`YYYY-MM-DD`). Every listed field except `user` and
   `assistant` must be a single line; the helper rejects an incomplete payload
   and names every missing or multi-line field in one error. The helper allocates D/A ids,
   reply and supersession links, records the current phase/status, and publishes
   DIALOGUE.md and ANSWERS.md as a recoverable pair. Preserve the user's message
   and returned assistant answer verbatim in `user` and `assistant`.
5. Use `working` only when the answer is explicitly
   provisional or asks another question, `NEEDS-USER` when a human choice or
   missing evidence blocks it, and `final` when it resolves the bounded question
   or the user accepts/closes the thread. Set `Follow-up: required` only when a
   named phase must update the named target artifact; otherwise use `none`. A
   final answer record is durable context, not approval to advance a phase.

If the user corrects a fact, sets a veto, or makes a decision, preserve the
words verbatim in both the dialogue and answer records and identify which
formal artifact the owning phase must update. Such a record uses `Follow-up:
required`; it remains pending until the owner appends a fixed-format
`Disposition X###` receipt. The discussion sidecar never writes its own
disposition. After a helper failure, do not claim the dialogue or answer was
saved; the next `prepare` recovers an interrupted paired publication before
accepting another turn.

## Output contract

Every completed turn leaves these project-local artifacts:

- `.project/discuss/DIALOGUE.md` — append-only transcript of the exchange.
- `.project/discuss/ANSWERS.md` — append-only answer and decision records,
  with final answers clearly marked `final`.

Keep answer records concise but self-contained: question, phase/status,
conclusion, reasoning or pushback, evidence/citations, research used or why it
was not needed, confidence, unresolved tags, next owner, target artifact, and
follow-up state. Do not duplicate a formal phase handoff or silently edit one
on the user's behalf. End the user response with **Outcome**, Markdown
**Review** links to the resolved absolute DIALOGUE.md and ANSWERS.md paths. For
a required follow-up, **Next** names the pending owner and tells the user to
invoke `$gsd-path`; otherwise it gives the next discussion question or says
that no action is required.
