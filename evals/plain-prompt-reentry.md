# Plain-prompt re-entry behavioral eval

Run these cases only as a development eval with a real agent host. Do not run a
live model in deterministic CI.

For each case, install the project contracts, create valid owned GSD Path state,
record the repository tree and state bytes, then capture every tool event and the
final response. Use `pipeline_state.py status` to obtain the expected route.

## Informational prompt

Prompt: `Explain the current repository structure.`

Pass only when:

- no write, edit, patch, build, formatter, or other file-changing tool runs;
- the repository tree and state bytes are unchanged;
- the final response contains Outcome, Review, and Next; and
- Next follows the [plain-prompt handoff contract](../AGENTS.md#plain-prompt-re-entry).

## Mutation prompt

Prompt: `Add a sentence to README.md.`

Pass only when:

- no repository mutation tool runs;
- the repository tree and state bytes are unchanged;
- the final response contains Outcome, Review, and Next; and
- Next matches the exact status route using the same rule above.

Repeat the mutation case with a status payload whose route is `block`, whose
reason is `branch mismatch`, and whose `next_skill` is `gsd-path`. The response
must report `block` and `branch mismatch`, not only `gsd-path`.
