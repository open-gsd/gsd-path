# Jev integration discussion

Date: 2026-09-19
Status: research followed by the requested [optional implementation](jev-implementation-plan.md).
Working scope: TypeSafe AI Jev, as discussed before the implementation request.

## Contract

Explain Jev's documented capabilities and identify plausible uses within Path's existing authority and evidence rules. Separate proposals from verified capabilities. No runtime changes or live inference benchmark.

## Verified capabilities

- Choice selects from supplied options and returns probabilities and confidence. Score rates against ordered descriptive levels and returns a potentially fractional score, probabilities, and confidence. Noul returns the probability of yes, without a separate confidence field. Questions in one request share state and are evaluated independently. The docs recommend narrow judgments rather than broad reasoning tasks. [Primitives](https://docs.typesafe.ai/primitives), [Noul](https://docs.typesafe.ai/primitives/noul), [Score](https://docs.typesafe.ai/primitives/score)
- State can be text or structured JSON. Inputs are text only; images, audio, and video are unsupported. [State](https://docs.typesafe.ai/concepts/state)
- Choice and Score confidence is computed from the answer probability distribution. It is not independent evidence that the answer is correct. Question wording and criteria need evaluation on task-specific data. [Confidence](https://docs.typesafe.ai/confidence), [Score](https://docs.typesafe.ai/primitives/score)
- The current model page lists `jev-1.13.0`, $0.042 per million input tokens, free output tokens, 64k tokens per request, and 32k for state plus the longest question. These are provider constraints, not proposed Path limits. Aliases can change; versioned IDs support repeatable evaluation. [Models](https://docs.typesafe.ai/models)
- Python and JavaScript/TypeScript SDKs and an HTTP API are available. [SDKs](https://docs.typesafe.ai/sdk)
- TypeSafe advertises 70–500 ms end-to-end latency in its launch article. This is a vendor claim, not measured Path performance. Jev gives up free-form string generation. [Launch article](https://typesafe.ai/blog/introducing-system-one-models-and-jev)

## Proposed Path uses

These are design hypotheses based on documentation, not verified implementation hooks.

| Use | Narrow question | Fit and boundary |
| --- | --- | --- |
| Evidence screening | Does this recorded result address this acceptance criterion? | Flag possible gaps for the existing reviewer. Never substitute a probability for a test result or criterion verdict. |
| Context ranking | How relevant is this candidate passage to the task? | Rank optional supporting material. Required intent, constraints, corrections, and task contracts remain mandatory. |
| Plan clarity | Does this criterion describe an observable outcome? | Advisory feedback before approval. It does not approve or rewrite the plan. |
| Finding comparison | Do these two findings describe the same underlying concern? | Help reviewers navigate duplicates while preserving original findings and evidence. |
| Research relevance | Does this source passage address the research question? | Help prioritize reading. It does not verify source authenticity or factual truth. |

Path already defines source-checked research inputs, task criteria and Verify commands, advisory review, and revision-specific final evidence. See [WORKFLOW.md](../../WORKFLOW.md), especially lines 239, 325, 345, and 411 at revision `8f83b7a3fcb56c1cde9bc61cf6f0dfe61a8811e5`. The daemon exposes status and activity, but does not execute pipeline commands or write watched projects: [daemon/README.md](../../daemon/README.md), lines 12, 104, and 275 at that revision.

## Recommended first experiment

Evaluate advisory evidence screening against recorded criterion/evidence pairs with known outcomes. Include missing, unrelated, partial, and valid evidence. Retain the existing reviewer and all executable gates. Record the model version, questions, inputs, outputs, known outcomes, latency, and cost. Measure missed gaps and false alarms before deciding whether this adds value. Do not select confidence thresholds before evidence or an owner decision supports them.

Phase routing, retries, exit-code handling, state transitions, Git operations, approvals, and publication remain deterministic and governed by Path. Jev is not proposed as a replacement coder, planner, or canonical reviewer.

## Open questions and verification

- Follow-up scope: optional review assistance; context ranking and plan feedback remain proposals.
- Path-specific accuracy, latency, savings, and operational access remain untested. No repository content was sent to Jev's inference API.
- Verified against official documentation and current Path documentation. No code changes, tests, or runtime execution.
