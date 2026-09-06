# Intent — Widget counter CLI

Lane: quick
Lane reason: One coherent CLI deliverable and its real-CLI tests fit one wave, with no open research or cross-wave integration risk.
Review panel: off
Finding skeptics: off
Surfaces: count.py CLI

## Summary

Extend the existing Python widget counter for command-line users and JSON consumers. Preserve default and signed integer text output, add JSON output with the flag before or after the optional count, and make invalid input fail with useful stderr. Deliver real-CLI regression tests without new dependencies. Evaluate the pinned pipeline through one full-wave review, final-review reuse, canonical integration, and the requested external checks, stopping at the named capture checkpoints and owner gates.

## Problem

The existing script only reads its first argument. A leading --json causes a traceback; a trailing --json is ignored. Invalid text exposes an unhandled exception, and no product tests exist.

## Users

Command-line users and automation consuming widget counts. This feature evaluation uses the existing local fixture; no user population or deployment scope is assumed.

## Success criteria

1. Running `python3 count.py` prints exactly `0 widgets` followed by a newline. A signed integer argument prints that integer count followed by ` widgets` and a newline, including zero, positive, and negative values.
2. `--json` alone, before a signed integer count, or after that count prints exactly one JSON object with only the `widgets` key and an integer value equal to the count; omitted count defaults to zero. Successful runs exit zero and emit no stderr.
3. Invalid input fails with a nonzero exit and a useful diagnostic on stderr, without success output or an unhandled traceback. Non-integer counts, unknown options, and extra positional arguments are invalid.
4. Standard-library real-CLI tests invoke count.py as a subprocess and check exit status, stdout, stderr, JSON shape and integer type, default count, signed counts, both flag placements, and invalid input. Tests must detect missing requested behavior.

## Scope: in

- Argument handling and text/JSON output in count.py.
- Real-CLI regression tests covering the criteria above.
- One full build wave with explicit final scope and required surface walkthrough evidence.

## Scope: out (vetoes)

- "No new dependencies; add real-CLI tests."
- "This is a feature evaluation, not an update of the plugin."
- "Do not change installed skills or hand-repair pipeline state."
- "Do not read evaluator tests or other scenario workspaces."
- "Do not attempt destructive operations in the product repository."
- Do not break existing default and signed integer text output.

## Constraints

- "Use ONLY the pinned local skill at /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/quick/repo/.agents/skills/gsd-path/SKILL.md and its sibling bundles."
- "Use real native children and canonical helpers."
- "No testing token/time limit is set. Do not invent limits, approvals or receipts."
- "Stop at reviewable owner gates."
- "Remote actions are limited to the existing local origin; any GitHub action needs separate explicit owner approval of its target."
- "Use quick lane, one full wave, no panel."
- Keep Python standard-library compatibility with the observed local Python 3.9.6 runtime.
- Bound branch: gsd-path/M001; initial base: 18c315c8da5e1b382a8efc016db2d4050e9cb0b2; local origin: /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/quick/origin.git.
- Measure shell implementation, verification, and review work through `python3 /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/plugin/tests/evaluate_codex.py activity --arm /Users/jeremymcspadden/orca/evaluations/gsd-path-finish-line-4295d75/quick --category <implementation|verification|review> -- <command>`. The wrapper starts in the primary repo; select each sidecar cwd explicitly.

Required evaluation sequence, verbatim:

1. Prove explicit final scope and required walkthroughs in the full-wave review.
2. Observe prepare-final reusing that review without review_final dispatch. Capture final-ready.
3. Before shipping, repeat prepare-final at the same HEAD and confirm receipt reuse without another execution or ledger entry.
4. Archive and integrate through canonical gates; capture integrated. Run the external counter oracle.
5. In an evaluator-owned disposable guard fixture, demonstrate a forbidden operation refused by the actual host guard before execution and an allowed read succeeding. Keep the hook event and unchanged target hash. Do not attempt destructive operations in the product repository. Hosts without runtime enforcement must remain unverifiable for native guards.

"At each named checkpoint, stop and identify the canonical artifacts for capture."

## Current state (brownfield only)

- **What exists**: A three-line Python script using sys, int conversion, and direct formatted output. No product tests, dependency manifest, CI configuration, or CONTRIBUTING.md were found. README contains only a fixture title.
- **Must not break**: Default zero and signed integer text output.
- **Doc-vs-code rulings**: None required; the gated audit has no remediation queue.
- **Ground truth**: `.project/research/evidence-codebase.md`, `.project/research/DOCS-AUDIT.md`.

## Risks

- Argument parsing must preserve negative counts while recognizing the JSON flag in both positions; real CLI tests and recorded walkthroughs prove this.
- Native guard enforcement has not been demonstrated. A helper refusal alone cannot prove a host guard. Report unverifiable if runtime enforcement is unavailable.

## Open questions

- None for the requested product scope. Evaluation checkpoint evidence remains to be produced; it is not claimed by this draft.

## Corrections

- None.
