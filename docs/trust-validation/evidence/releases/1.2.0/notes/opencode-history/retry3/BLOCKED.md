# OpenCode retry3 — BLOCKED at receipt identity binding

Candidate: f36f24aed82ac0019d082c7e31b8a4342d8e03f1; package 1.2.0; OpenCode 1.18.25.
Fixture: /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry3/quick/repo
HEAD: 02242d3d7b901db917fad9d9b84c3e836a541853. Prepared archive: .project/archive/001-count-cli.
No ship commit, integration, passing receipt, or publication. No active native process.

## Exact blocker

The official manifest assembler exited 1:

```text
the task file records agent 'build_T001' but no completed child was dispatched under that label (no completed task child with description 'build_T001' in /Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry3). The host broke the dispatch contract; rerun its build so the dispatched label and the task agent field match. Do not override this: the receipt validator cross-checks them.
```

Actual activation used `--task-id T001 --agent build_T001`; task frontmatter retains `agent: build_T001`. Actual completed native Task description was `build_t001`, child ses_f3fe087a3ffeRMv71z3Lf4fNaj, parent ses_f3fe23686ffeaRmOn8iOCp4n0q. The raw native calls and completion metadata are retained in label-provenance.json. This is an exact identity mismatch, not a missing child.

## Instruction and evaluator provenance

- `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry3/quick/repo/.opencode/skills/gsd-path/references/build-native.md:199-201` instructs activation `--task-id <id> --agent build_<id>`; this task ID is T001. Line213 calls the logical name `build_<task_id>`.
- `/Users/jeremymcspadden/orca/evaluations/gsd-path-release-1.2.0-f36f24a/opencode-retry3/quick/repo/.opencode/skills/gsd-path/references/dispatch.md:14-22` requires Task description `build_<task_id>` and normalizes variable parts to lowercase ASCII.
- Native preparation returned an exact next activation command with `--agent build_T001`, paired with native Task description `build_t001`. Evaluator coder.txt carried that native handoff forward and explicitly required description build_t001. This evaluator involvement is preserved, not hidden.
- The assembler requires exact matching labels and refused this pairing. No validator changes, case-fold override, task metadata rewrite, archive edit, fabricated child, or replay was used.

Smallest fix direction: make the canonical activation/dispatch contract use one normalized logical identifier for both recorded task agent and native description, with an executable binding regression covering task ID T001. Keep strict actual-child matching. This is a proposal only; no candidate source or archived evidence was changed. Root owns the fix/ruling. Existing failed evidence must not be relabeled.

## Proven partial results

- Plan/intent approval, real native coder, isolated Verify9/9, canonical task landing d05823a88c8e2b7c12308299cdd2b48b4dc7a313.
- Native reviewer ses_f3fd83264ffebCndcU2m9NNya2 passed full Wave1, explicit final scope SC1–SC6, exact Surface `plain CLI`, real CLI walkthroughs, recorded Verify for SC6.
- Helper-owned collection, wave gate, build completion passed.
- First prepare-final reused the full-wave final review and ran project Verify9/9. Repeated same-HEAD prepare-final reused both. Ledger remained2entries/2646bytes/SHA256 e85f1cb045b167a390bcb73c23e5b364b4bb100cb2ad16c8eedae62d0bafb7ed. No review_final child.
- Independent evaluator product oracle6/6 PASS (product.json).
- Session totals (output+reasoning, recursively including native children):23419,11379,10368,7716,13802,11193,24796,16005. All under owner30000;4000 is warning. Raw source counters in all-native-usage.json.
- Prepared archive remains intact; official manifest failure happened before guard/trust-manifest creation. No candidate end-to-end pass is claimed.

## Next

STOP. Root stopped further full-fixture retries in response to the owner's cost and time constraint. Root will retain release as unapproved and decide the smallest identity-contract fix. No next native command is authorized by this checkpoint. Raw log paths and hashes are in blocked-provenance.json. Prior attempts remain intact.
