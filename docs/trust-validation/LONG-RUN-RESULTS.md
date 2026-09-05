# Long-run findings — in progress

The native run has found and repaired real sources of wasted verification work.
It has not yet proved every feature or overall workflow efficiency.

## Verified behavior

| Feature groups | Native result | Evidence |
|---|---|---|
| Inspect | Pass: actual mapper and docs auditor in isolated sidecars | [Program inspection](/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-fixed-20260905/program/repo/.project/archive/001-storage/research/evidence-codebase.md) |
| Define, research, decide, plan, build, ship | Pass in the greenfield case, including actual research, integration and an external counter oracle | [Greenfield receipts](/Users/jeremymcspadden/orca/evaluations/gsd-path-greenfield-repair-20260905/reviews.jsonl) |
| Roadmap, abandon | Pass: partial archive, retained product history and pending-roadmap reslice | [Preservation proof](/Users/jeremymcspadden/orca/evaluations/gsd-path-repair-replays-20260905/abandon/evidence/m002-reslice-approval-v8aadxrg/preservation.json) |
| Review | Pass: two native deep lenses and final review, then local integration | [Review receipts](/Users/jeremymcspadden/orca/evaluations/gsd-path-review-replay-58dc14d/reviews.jsonl) |
| Lean verification | Pass: quick final reuses the full-wave review; unchanged-HEAD repeat adds no execution or ledger entry | [Reuse proof](/Users/jeremymcspadden/orca/evaluations/gsd-path-remaining-20260905/quick/agent-evidence/same-head-reuse.json) |
| Discuss | Pass: append-only required answer, legal owner disposition, unchanged product/state; repaired future-owner route blocks | [Positive receipt](/Users/jeremymcspadden/orca/evaluations/gsd-path-discussion-positive-20260905/reviews.jsonl) |
| Docs audit | Pass: native stale claim reproduced without code/docs edits | [Audit receipt](/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-fixed-20260905/reviews.jsonl) |
| Undo, forensics | Pass: exact unpublished task undo and read-only diagnosis; no native interruption claim | [Recovery receipts](/Users/jeremymcspadden/orca/evaluations/gsd-path-remaining-20260905/reviews.jsonl) |
| Lookahead | Partial: both plans approved during build, clean M002 promotion captured; changed M003 promotion still pending | [Actual captures](/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-fixed-20260905/program/captures.jsonl) |
| Install | Global Codex and Claude updated, 14 skills each; doctor healthy. Native model proof is not required for installation | [Installer receipt](/Users/jeremymcspadden/orca/evaluations/gsd-path-global-update-5ed6518/doctor.json) |

## Open results

| Feature | Actual limit on the claim |
|---|---|
| Guards | Failed three real disposable-file edits, including explicit trust and hook enablement. Cause unresolved; owner continuation requested after the supplied three-round fuse. |
| Panels | No independent advertised model family. Same-family lenses do not prove cross-model panel behavior. |
| Skeptics, patch | No natural blocked finding. These paths remain unexercised; no reviewer finding was fabricated. |
| Loop | Owner-set max_iterations and wall_clock remain unanswered. Overall testing is unlimited; template examples are not owner values. |
| Bootstrap, PR integration | Exact private GitHub target approval remains pending; accepted PR integration also requires the owner to merge with a merge commit. No external repository or PR created. |

## Work footprint

These are observations, not targets or pass/fail ratios. Artifact size is not generation effort; measured shell categories are partial and include bookkeeping.

| Completed case | Product lines | Test lines | Canonical pipeline artifact lines | Native parent run time |
|---|---:|---:|---:|---:|
| Quick | 12 | 67 | 600 | 25.6 minutes |
| Greenfield | 18 | 76 | 702 | 39.7 minutes |

The quick run dispatched two inspectors, one coder and one wave reviewer; no final reviewer. Its reuse worked, but the total workflow footprint remains large relative to the product change. There is no measured before/after basis for a token-savings or optimality claim.

[Quick measurements](/Users/jeremymcspadden/orca/evaluations/gsd-path-remaining-20260905/quick/native-work-footprint.json) · [Greenfield measurements](/Users/jeremymcspadden/orca/evaluations/gsd-path-greenfield-repair-20260905/greenfield/native-work-footprint.json)

M002 reporting produced 66 product lines and 256 test lines. Recorded coder intervals total 5.3 minutes after removing provider overlap; its wave and final reviewer intervals total 5.5 minutes. These exclude orchestrator, approval, source-repair and ship time. The project Verify ran once and passed 15 tests in 4.855 seconds. This separates review work from test execution without inventing a target ratio. [M002 measurements](/Users/jeremymcspadden/orca/evaluations/gsd-path-longrun-fixed-20260905/program/m2-work-footprint.json)

## Source fixes and proof

Fixes cover managed-runtime greenfield detection, legal settled-research skips, premature decision/state advancement, pending discussion routing, surface/interface parsing, archive compatibility, supplied planning inputs and repeated build plan gates. Initial failed native runs remain preserved. Focused regressions were observed RED, GREEN and sensitive to sabotage; details and exact source commits are in [execution status](LONG-RUN-STATUS.md).

The latest shared check at da9522c passed 1,025 Python tests with two platform skips, all 133 Node tests and resource sync. The later 5ed6518 build-progress gate fix passed 101 focused tests. Running fixtures use several pinned revisions and explicit repair overrides: this is not one-revision end-to-end certification.
