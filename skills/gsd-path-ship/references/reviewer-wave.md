## Wave mode

Use task acceptance criteria and the INTENT.md success criteria owned by
tasks in this wave as the rubric. For each task:

1. Read the task file's `base` and the landing commit SHA the orchestrator
   supplied in your brief (it comes from `isolation.py land`/`recover`).
   Never infer either SHA from task ids, branch position, or nearby history.
2. Fail a missing, malformed, or invalid SHA. Inspect the commit with
   `git show --format=fuller --stat --patch <commit> --`.
3. Select the inspection mode your brief supplies and record it — never
   improvise a third:
   - **Reconstructed product** (default): the brief supplies a verify
     sidecar at `base`. In it, apply only the complete binary patch from
     `commit^..commit` for the task's declared product files and inspect
     the diff. Use the orchestrator's recorded isolated Verify output in
     that task's Log as the Verify evidence.
   - **Immutable patch**: the brief supplies one later combined checkout
     with report-write authority only. Inspect the immutable objects
     directly — `git show`/`git diff` on the recorded commits — and prove
     the identity before judging: (a) the landing commit's parent
     `commit^` equals the task file's recorded `base` (or the patch's
     resulting blobs at `base` equal the landing commit's blobs for the
     declared files), and (b) any file judged from the combined checkout
     has its blob there equal to the landing commit's blob at that path.
     Without both identities the review blocks: a mismatch means the
     supplied checkout is not the reviewed product.
   In both modes: do not re-run the task Verify command or PLAN.md's
   project Verify; re-run a command only when the recorded output plus
   the diff cannot check the criterion. Never use the primary worktree
   or branch tip as task evidence. Do not create or remove Git worktrees
   yourself.
4. Mark `pass` or `fail`. Before the evidence separator (` — `), name the
   criterion (see Review file format below): copy the complete task
   acceptance or interface criterion verbatim, or — on a `pass` line only —
   cite the criterion by its stable id in the task's numbered acceptance or
   interface list (`T012/AC3`, `T012/IF2`) together with the evidence. A
   `fail` line always copies the criterion verbatim: finding grouping binds
   that text to the task. Give the observed result, `file:line`, and
   concrete fix direction for each failure.

A Log entry `orchestrator regression Verify of <task id> retired: superseded
by <task id>` is not evidence: judge the superseding task's acceptance
criteria. The same applies to the entry `orchestrator regression Verify of
<fix task id>: part of <task id> retired: superseded by <task id>`.

Then check each INTENT.md success criterion owned by a task in this wave
against that same isolated product. In each `### SCn —` heading, copy the
complete criterion text from INTENT.md `## Success criteria` (see Review
file format below). Write the headings in ascending SC id order (SC2 before
SC4), and separate the id from the text with an em dash (—). Mark `pass`
or `fail` with evidence; a failed owned SC blocks the wave. Omit the Intent coverage section when no task in the wave owns
an SC. When INTENT.md `## Edge coverage` or `## Prohibitions` has rows for
an owned SC, judge it against those rulings too: cite each `held-out` edge
id with its held-out test's recorded output and each `judgment` prohibition
id with what you observed. A missing held-out result or a violated ruling
fails the SC.

Allow changed paths only in the task's `files` plus its assigned task file.
Within the task file, allow orchestrator-owned `base`, `worktree`,
`task_branch`, `status`, and `agent` fields — and, on a member task,
`member_base` — plus append-only Log entries; block contract-body changes
in the task commit. `base` names the task's starting commit in the
coordinator repository; `member_base` names the starting commit in the
member repository from which the member task branch and isolate were
created. Warn on disabled tests
or Verify commands that cannot fail unless either defeats a criterion. Set the
wave verdict to `pass` only when every task passes and every owned INTENT
success criterion for the wave passes.

For cycle greater than 1, read the previous review, re-check every failure,
and regression-check affected passes. State when the same criterion fails for
a different reason. Use only the wave-review template.

### Review file format

`scripts/check_handoffs.py wave` rejects a review file that breaks one of
these rules, and `scripts/review_findings.py` cannot group a failure whose
criterion text does not match. Apply the rules before you write the file.

- **Section order.** Put the `## T### —` sections in task id order (T001
  before T002). The order of the PLAN.md wave table does not apply. A `pass`
  review has one section for each task of the wave.
- **Section heading.** Write `## T### — <title>: pass` or `: fail`, where
  `<title>` is the exact `title:` value of the task file.
- **Evidence lines.** An evidence line starts with `- ✅ ` for pass or
  `- ❌ ` for fail. Each task section and each `### SCn —` block needs one
  or more lines with the marker of its own verdict. A failed task needs a
  `- ❌ ` criterion line, also when other text describes the failure.
- **Criterion text.** In a `### SCn —` heading and on every `- ❌ ` fail
  line, copy every word of the criterion. Join wrapped lines and
  sub-bullets with one space. You can keep or remove the `- ` markers of
  the sub-bullets. A changed, added, removed or moved word does not
  match. On a `- ✅ ` pass line, name the criterion either by copying it
  verbatim or by citing its stable id in the task's numbered acceptance
  or interface list (`T001/AC1`, `T001/IF2`) together with the evidence;
  the wave gate does not compare pass-line criterion text.
- **Angle brackets.** Text such as `<b>` or `<path>` outside backticks reads
  as an unfilled template placeholder and is rejected. Write literal markup
  and code in backticks inside a sentence, for example: the output has
  `<b>hello</b>`.

### Re-review after a proven repair

When the brief supplies a `review_findings.py repair-evidence` receipt, use
its isolated repair product for the linked original criteria, including owned
INTENT criteria. The original faulty landing and earlier verdicts remain
historical evidence; they do not force the later verdict to remain failed.
Reconstruct the receipt's repair `base` plus only its `commit^..commit` patch
for `files` inside the supplied sidecar. For a member repair (the receipt
names `member`), use `member_base` and `member_commit` in that member's
repository. `earlier_repairs` are linked repairs of the same findings that
are already in the repair base. When the receipt has `later_repairs`, linked
repairs changed the same files after this repair: apply their patches in
order too. Read the repair task's recorded
Verify, or with `later_repairs` that of the last one, which is the receipt's
`verification`; inspect the patch against the original unchanged contract, and reuse
settled checks. Check unaffected criteria from their prior evidence plus the
repair diff for regressions. Cite the receipt, repair landing and task Log in
the new review. A receipt proves provenance, not acceptance: judge whether the
repair actually satisfies the criterion. A missing or rejected receipt blocks
using that repair; the parent resolves it, or briefs this review in full at
the current HEAD without a receipt, rather than creating another product fix
for the unchanged historical failure.

## Final scope in a quick full wave

When explicitly briefed with final scope, record `Review scope: final` and the
full supplied review HEAD in the wave artifact. Check all INTENT success criteria
and PLAN's Surface contract against the completed isolated product. Each surface
criterion's Intent coverage block includes `- **Surface**:`, `- **Check**:`, and
`- **Observed**:` with the walked states and actual result. `Surface` holds
exactly the surface name from PLAN's Surface contract; walkthrough detail belongs
in Check and Observed. Reuse recorded task
output if it proves that exact walkthrough; run only a missing check. Cite
every `held-out` edge and `judgment` prohibition id of each criterion in its
evidence; shipping derives FINAL.md from these records, and an uncited id
sends the milestone to a dispatched final review instead. Final-scope
coverage shares this wave artifact; do not write a second report. Shipping's
runtime checks freshness and derives the final view from these records.

## Deep review lenses

A `deep` wave spawns two independent reviewers in parallel, each with a fresh
context and its own isolated workspace at the recorded review base (a verify
sidecar in reconstructed mode, or the supplied combined checkout in immutable
mode). Every Wave mode rule above applies to both lenses.

- **Contract** — logical task name
  `review_wave_<wave>_cycle_<cycle>_contract`; stages
  `.project/review/wave-N.cycleC.contract.md`. This is the full wave review:
  patches applied to the recorded base, recorded Verify plus diff, every
  acceptance criterion and interface contract checked. Record `Lens:
  contract`.
- **Adversarial** — logical task name
  `review_wave_<wave>_cycle_<cycle>_adversarial`; stages
  `.project/review/wave-N.cycleC.adversarial.md`. Try to kill the work:
  security holes, unhandled edge cases, failure modes, data-loss and
  concurrency risks, missing error handling. Record `Lens: adversarial`.

The wave passes only when both lenses return `pass`; any `blocked` lens
blocks the wave.
