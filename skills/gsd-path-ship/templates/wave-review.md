# Review — wave <N>, cycle <C>

<!-- Written by the reviewer role in wave mode. File: wave-N.cycleC.md —
     deep reviews use wave-N.cycleC.contract.md and
     wave-N.cycleC.adversarial.md instead. Keep validated fields on their
     own lines: Cycle holds only the number
     (C > 1 means re-review after fixes; see previous cycle file). -->

<!-- For quick single-full-wave final scope, include these two metadata lines
     with actual values, otherwise omit them:
Reviewed HEAD: <full review commit SHA>
Review scope: final
     In each surface SC block keep the mandatory `- ✅` / `- ❌` evidence line
     (the wave gate requires it). Also include Surface, Check, and Observed
     fields using the final-review format. Surface holds exactly the surface name
     from PLAN.md's Surface contract; put walkthrough detail in Check and Observed.
     The `- ✅` line may summarize Observed; do not omit it. -->

Wave verdict: <pass | blocked — blocked if any task fails>
Cycle: <C>
Depth: <full | deep | verify-only — verify-only is orchestrator-written from
        its isolated Verify evidence; no independent reviewer ran>
Lens: <contract | adversarial — deep reviews only; leave this value empty or omit the line
       otherwise>
Tasks reviewed: <count>

## T001 — <title>: <pass | fail>

<!-- Task sections go in task id order (T001 before T002), not in the order
     of the PLAN.md wave table. The heading title is the exact `title:` of
     the task file. An evidence line starts with `- ✅ ` (pass) or `- ❌ `
     (fail). A section needs one or more lines with the marker of its own
     verdict, so a failed task needs a `- ❌ ` criterion line.
     On a `- ✅ ` line, name the criterion either by copying every word of
     the acceptance/interface criterion before the em dash (join wrapped
     lines and sub-bullets with spaces; the `- ` markers of sub-bullets are
     optional) or by citing its stable id in the task's numbered list
     (`T001/AC1`, `T001/IF2`) together with the evidence. A `- ❌ ` line
     always copies the criterion verbatim: review_findings.py groups
     findings by that text.
     Write literal markup and code in backticks inside a sentence: text
     such as <b> outside backticks reads as an unfilled placeholder. -->
- ✅ <criterion> — <evidence: verify output / file:line checked>
- ❌ <criterion> — found: <what exists instead, file:line>
  fix: <concrete direction a coder can execute without re-investigating>

Warnings (non-blocking):
- <weakened test / unfailable verify / none>

Contract violations (blocking):
- ❌ <task changed path outside its files list> — <evidence and fix direction>

<!-- Repeat per task. -->

## Intent coverage

<!-- One heading per INTENT.md success criterion owned by a task in this
     wave, ending `: pass` or `: fail`, in ascending SC id order (SC2
     before SC4), with an em dash (—) after the id. `scripts/check_handoffs.py
     wave --review <this file>` gates the SC ids, their order, and
     verdicts. Omit this section when no task in the wave owns an SC.
     Copy every word of the criterion from INTENT.md `## Success criteria`:
     join indented continuation lines and sub-bullets with a single space
     (the `- ` markers of sub-bullets are optional). The gate compares every
     other word: no paraphrase, no dropped sub-bullet.
     Each SC block needs an evidence line with the marker of its own
     verdict: `- ✅ ` (pass) or `- ❌ ` (fail). -->

### SC1 — <criterion from INTENT.md>: <pass | fail>
- ✅ <evidence: verify output / file:line checked>
- ❌ <criterion> — found: <what exists instead, file:line>
  fix: <concrete direction a coder can execute without re-investigating>
<!-- Quick-lane final scope (Review scope: final): add after the evidence line:
- **Surface**: <surface name from PLAN.md>
- **Check**: `<walkthrough command>`
- **Observed**: <what was seen> -->

## Fixed since last cycle

<!-- C > 1 only: previously failed criteria now confirmed fixed (re-checked,
     not assumed), and any regressions the fixes introduced. -->
- <criterion> — confirmed fixed / regressed: <evidence>

## Summary for orchestrator

- blocked findings: <failed criteria grouped by disjoint file scope; the
  orchestrator applies the configured skeptic or fix-task path>
- repeat offenders: <criteria failing across cycles — possible plan defect>
- warnings worth a human eye: <...or none>
