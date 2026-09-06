# Initial binding fix: live Codex rerun

Date: 2026-09-04, America/Chicago.

## Outcome

The initialization blocker is fixed. Plugin candidate
`d1faa129eda69d6d0ba9e2d1e754993595c1c004` successfully executed the actual local
initialize → bind → transition sequence. The Path run then reached a separate
research gate/state conflict before implementation. It did not deliver a milestone.

The evaluator resume fix is `00795b0`. Its launcher passes sandbox and added-directory
options before the `resume` subcommand. The plugin installation stayed pinned to
`d1faa12`; no installed plugin files were repaired during evaluation.

## Verification

- Initial regression: the old binding helper failed with `error: primary worktree is not clean`.
- Corrected helper: all 20 binding and full-cycle tests passed. The bootstrap test
  proves unchanged state bytes, unchanged HEAD, already-bound interruption recovery,
  and the expected-state binding transition without a commit.
- Bypassing admission validation made all nine rejection cases fail. Validation
  was restored. A separate test rejects identical-content file replacement during switch.
- Resume regression: the child process received no sandbox option. After correction,
  all four evaluator tests passed. Removing the resume options again failed the
  regression; source was restored. The live host confirmed `danger-full-access`.
- Simplification review kept one shared admission helper and one unconditional
  launcher option list. Generated resources were synced: 181 resources, no warnings.

## Observed live results

Both arms started from product commit `cf297a7f214c129a94a72665d5c7458407406cff`,
using Codex CLI 0.153.4, gpt-6-astra, high reasoning. Prompts explicitly selected
the local Path bundle and the same test-writer/Simplify skills.

| Arm | Agent elapsed | Independent product checks | Delivery |
| --- | ---: | --- | --- |
| Direct | 102.241 s | All six pass | Clean product commit `b3b382c5692c998b89a63f98b4eddd763ee8f735` |
| Path | 631.627 s | Fail: product unchanged | `decide/blocked`, no implementation or ship |

Path delivery elapsed, including time between resumptions, was 841.983 s. Its
agent elapsed includes a 43.378 s read-only resume attempt caused by the launcher
bug. Recorded requested settings therefore do not prove equal effective permissions
for every attempt. This is a failed delivery experiment, not a completed throughput
comparison. Activity categories are partial caller-declared measurements, not an
exclusive accounting of coding versus verification. Raw host usage is retained;
no complete child-token accounting or token-budget compliance is claimed.

Host session records confirm native `inspect_codebase`, `inspect_docs`, and
`research_pitfalls` dispatches. The intent approval was explicitly attributed to
the parent evaluator under the authorized fixture run, not represented as a new
human approval. No final milestone receipt was fabricated.

## Remaining blocker

The research gate exited 1 with this output:

```text
handoff validation failed: .project/research/evidence-pitfalls.md Questions assigned must be 'none'
```

The agent's command batch nevertheless marked research done and entered decide.
The agent acknowledged the failure, ran the canonical diagnostic, and used an
expected-state transition to record `decide/blocked`. No decider was dispatched.
The diagnostic returned `status: ok`, reporting only uncommitted project files;
that result did not validate the research handoff. The fixture remains intact at
the state/evidence conflict and requires the pipeline's explicit recovery ruling.

The next repair needs to prevent a failed research gate from authorizing a phase
advance. Correcting the evidence metadata alone would not close that failure mode.
This rerun provides no proof that Path is optimized for this small CLI task.

## Evidence

- [Machine comparison](codex-initial-binding-rerun.json)
- [Native dispatch and effective sandbox records](codex-initial-binding-native.json)
- [Raw run directory](/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-d1faa12)
- [Blocked state and failure log](/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-d1faa12/path/repo/.project/STATE.md)
- [Research evidence](/Users/jeremymcspadden/orca/evaluations/gsd-path-astra-d1faa12/path/repo/.project/research/evidence-pitfalls.md)
- [Original Git research](../../../research-initial-binding-git.md)
