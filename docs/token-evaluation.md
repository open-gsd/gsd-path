# Token usage evaluation

## Verdict

Prompt loading is more selective, and the optimized candidate completed a real
delivery within the owner's session budget. The workflow still spends much more
on inspection, planning, orchestration, and review than on coding for this small
task. It is not universally optimized.

Owner decision: **4,000 output tokens is a warning threshold; 30,000 remains the
session limit for future optimization work.** The historical run's stricter
policy and overruns remain recorded.

## Completed native run

Candidate: `9f13dc0`. Model: `gpt-6-astra`, high reasoning. Task: add JSON output
and useful errors to a small Python CLI, preserving plain output and adding
tests. Quick lane, full review, no optional panel, local direct integration.

| Actor | Output tokens |
|---|---:|
| Inspection and intent parent | 4,289 |
| Code inspector | 2,441 |
| Docs inspector | 1,481 |
| Planning parent | 4,002 |
| Coder, including its tests | 2,943 |
| Full reviewer | 3,040 |
| Final reviewer | 4,367 |
| Build parent | 5,543 |
| Ship parent | 899 |
| **Total** | **29,005** |

The coder accounts for **10.1%** of output. The remaining **26,062 tokens**
belong to the other actors; this is an actor split, not a claim that all their
work was unnecessary. Some coder output also covers testing and its task log.

All six external CLI acceptance checks passed. Canonical archive and integration
returned merge `60f63fe16fe454b4c42248f894f6c9708bf7f3ca` and tag
`milestone/001-widget-counter`. Publication was confined to the disposable
evaluation's local origin.

## What improved

- Build loads the driver path first and loads native fallback procedures only
  when needed. Reviewer modes have separate instructions.
- Generated coder context preserves constraints, corrections, and owned
  criteria. Unfamiliar formats retain full intent rather than dropping rules.
- Inspectors receive isolated contexts and exact assignment paths. The docs
  auditor excludes installed tooling internals while still detecting real
  product documentation drift.
- Existing helpers now handle inspection preparation and completion, reducing
  commands and bookkeeping assembled by the parent.
- Cumulative resume counters are charged as deltas, so earlier output is not
  counted twice.

Static build entry instructions fell from **17,637 to 4,399 tokens** with
conditional host-counter instructions included. The initial driver core alone
is 2,333. These are file-load measurements, not whole-session savings.

Observed output before coding fell from **21,877** in the earlier attempt to
**12,213** in this run. The earlier attempt stopped before delivery; this one
completed. These are individual runs of different candidates, not an isolated
causal experiment or a general performance guarantee.

## Remaining overhead and limits

- A trailing period on a surface name prevented reuse of the passing wave
  review and triggered the 4,367-token final reviewer. The comma/state conversion
  fix is verified; label handling still has this limitation.
- Codex reported shortening the global skill catalog to fit its description
  budget. That host-wide context remains separate from this skill's file loads.
- The retained direct-coding baseline completed the same fixture in 3,347 output
  tokens. The pipeline run used about 8.7 times as much, including its required
  inspection, approval, review, archive, and integration workflow.
- Output tokens measure generated work. They do not measure unique prompt
  content, repeated input, or cached input. Native-trial totals exclude this
  optimization conversation and fixture setup.

The evidence supports using 4k to flag expensive tasks and judging total cost
through completed delivery. Increasing every task allowance would hide the
remaining overhead.

## Evidence

- [Counters, event paths, acceptance and integration](token-context-round7.json)
- [Implementation and verification history](token-context-work.md)
- [Static prompt measurements](token-context-metrics.json)
