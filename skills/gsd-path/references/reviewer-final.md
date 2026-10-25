## Final integration mode

Use only final-review.md. Treat INTENT.md success criteria as the rubric.
To locate each task's authoritative accepted evidence instead of joining
task Logs, ledger rows, and gap artifacts by hand, run
`python3 <absolute build_state.py> evidence-manifest --repo
<absolute primary> --project-dir .project --head <reviewed HEAD>`:
it classifies every task as `ledger`, `log-only`, `rejected`,
`superseded`, or `missing` and names the receipt, and reports the member
project Verify as `gap-embedded` only from a passing `final-gap-1.md` at
the reviewed HEAD — a
`log-only` task is accepted through its retained isolated-Verify Log, and
an absent ledger row is explained, never treated as data loss.
Each `### SCn —` heading must have every word of the criterion in INTENT.md
`## Success criteria`: join indented continuation lines and sub-bullets
with a single space. You can keep or remove the `- ` markers of the
sub-bullets; the gate compares every other word. Exercise the running
system and record `met`, `not-met`, or
`unverifiable` with checked command output or a precise file reference.
When PLAN.md carries
a `## Surface contract`, every criterion it lists under a surface is checked
by performing that surface's Walkthrough from its Entry in the supplied
sidecar: `Surface` names that surface, Check names what was performed,
Observed records what the surface actually showed at each state, and a missing
or unreachable surface is `not-met`. A surface criterion is never `met` on
internal test output alone. Run project commands only in the supplied verify
sidecar at the exact reviewed HEAD. Do not
re-run PLAN.md's project Verify; cite the orchestrator's recorded
project-verify sidecar output. `pass`
requires every criterion to be `met`.

When INTENT.md `## Edge coverage` or `## Prohibitions` tags a criterion with a
`held-out` edge or a `judgment` prohibition, grade that criterion on cited
evidence for every tag (see the [spec-reach probes](spec-probes.md)). Name
each id in Check, Observed, or Reference with its evidence: the held-out
test's recorded passing output from the PLAN.md `## Held-out checks` test, or
the observed behavior judged against the prohibition's Detail. When a tag's
evidence is missing, did not run, or cannot be judged, record `unverifiable`
with `Finding: insufficient spec evidence: <id> <what is missing>` and a Fix
direction naming the check to add or run. Never mark such a criterion `met`
on inference or on code that merely looks right; the ship gate refuses a
`met` verdict that does not cite every tag. Grade untagged criteria as usual:
the trigger is the INTENT.md tag, never your own doubt.

## Final gap mode

Use only gap-review.md. Check the one cross-wave risk in the brief against the
running system in the supplied verify sidecar at the exact reviewed HEAD.
Record evidence and `pass` or `blocked`; an unverified risk is blocked.
