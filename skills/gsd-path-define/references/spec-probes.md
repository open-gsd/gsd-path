# Spec-reach probes

Define runs two probes over the success criteria before approval: the edge
probe (what each criterion must do at its edges) and the prohibition probe
(what each criterion must never silently become). Both leave a table in
INTENT.md. Plan, build review, and final review read those tables; the
`check_handoffs.py intent`, `plan`, and `final` gates enforce them.

## Why define owns this

A reviewer can only check what the intent states. An edge nobody wrote down
is never checked: final review covers exactly the INTENT success criteria,
and a reviewer passes any reasonable reading of an ambiguous one. Model
reviewers are also confidently wrong on exactly these gaps. On three tasks
whose correct behavior the spec left unstated, LLM verifier verdicts caught
the defect 0 times in 12 while a held-out test caught all three; in a larger
replication, stating the surfaced edge in the spec raised the verifier's
catch rate to 98% ([Verifier Reach Is Spec Reach](https://github.com/davesienkowski/verifier-reach-is-spec-reach)).
A smarter reviewer does not close that gap; a wider intent does. The user is
present at define, so define is where the edge gets its ruling.

## Edge probe

Walk every success criterion:

1. Name the data shapes the criterion handles, then raise only the
   categories those shapes reach:

   | Shape | Categories |
   |-------|------------|
   | numeric range, dates, money, counts | boundary, precision |
   | list, set, rows, intervals | adjacency, empty, ordering |
   | text, names, identifiers | empty, encoding |
   | state that persists or repeats | idempotency, concurrency |
   | files, network, processes | concurrency |

2. For each raised category, write one concrete candidate edge and the
   ruling you recommend:

   | Category | Probe question |
   |----------|----------------|
   | boundary | What happens exactly at each minimum, maximum, or threshold, and one step either side? |
   | adjacency | When two items are equal or just touch, do they merge, collide, or stay separate? |
   | empty | What is the result for empty, single-item, or missing input? |
   | encoding | Whose length or equality applies: bytes, code points, grapheme clusters, normalized form, case? |
   | ordering | When items compare equal, is output order specified and stable? |
   | precision | Where can rounding, overflow, or truncation happen, and which rule applies? |
   | idempotency | What happens when this runs twice on the same input? |
   | concurrency | If interrupted or run in parallel, what is guaranteed? |

3. Ask the user in one small round, all criteria together, recommended
   ruling first. Never rule on an edge's behavior yourself: the correct
   answer is exactly what the criteria did not say, so a guess here is the
   defect this probe exists to prevent. Under pre-approval, an edge whose
   behavior the user has not stated is still a required answer: stop and
   ask instead of ruling.

4. Record each ruling as one row:
   - `criterion SCn` when the answer is observable where the user sees the
     work. Add or amend that success criterion (define owns criteria), then
     point the row at it. An existing criterion that already states the
     edge may be named directly.
   - `held-out` when the answer is a precise rule or a set of examples that
     belongs in a test rather than a user-facing criterion (a normalization
     form, a rounding rule, an inclusive bound on an internal API). Write the
     ruling or the user's examples verbatim in Detail. The plan must schedule
     a named test that pins it.
   - `dismissed` when the edge cannot occur for this criterion. Detail says
     why ("input is a closed enum"). "Not important" is not a reason.

Every criterion gets at least one row. A criterion with no data shape gets
one row with category `none`, dismissed with its reason.

## Prohibition probe

Walk every success criterion with one adversarial question: what could this
silently become that the user would not want, although nothing in INTENT.md
forbids it? Generate candidates privately, then keep only values, safety,
privacy, fairness, and transparency items: "must not email unsubscribed
users", "must not store raw card numbers in logs", "must not use guilt
wording". Drop routine engineering items (mutating input, throwing on empty
input, leaking handles); those are edges or ordinary review. Do not mint
generic security or compliance canon (injection, path traversal, data
retention law); record a real compliance need under Constraints instead.
Expect two or three kept items for work people touch, and often none for
internals.

Present the kept items with a recommended ruling and record each as a row:

- `criterion SCn` when a test or command can check it. State it as a
  success criterion and point the row at it.
- `judgment` when it is real but not mechanically checkable. Detail says
  what the final reviewer looks for.
- `dismissed` when the user rules it out. Detail records the reason.

Work that affects no person directly records a single row instead, and no
other: `| N1 | all | none | dismissed | <why no person is affected> |`.

## Absence criteria

A criterion that claims absence ("X does not exist", "no X anywhere",
"never Y"), including one written from a prohibition, has no end until it
says where to look. Each review can look somewhere new, so the build loops
to the cycle cap. Every absence criterion states:

- the search space: the files, surfaces, or artifacts to check;
- the check: the command or observation that covers that space;
- the absent result: the output that counts as absent.

When one is missing, propose a bounded form in the same question round as
the edges, recommended form first, and amend the criterion after the user
rules. Do not choose the search space yourself: a narrower space is a scope
ruling. Under pre-approval, an unbounded absence criterion is a required
answer: stop and ask.

## INTENT.md tables

```markdown
## Edge coverage

| Edge | Criterion | Category | Disposition | Detail |
|------|-----------|----------|-------------|--------|
| E1 | SC1 | boundary | criterion SC4 | |
| E2 | SC1 | empty | dismissed | the command always receives at least one file |
| E3 | SC2 | encoding | held-out | names compare by NFC code points, case-sensitive |

## Prohibitions

| Prohibition | Criterion | Must not | Disposition | Detail |
|-------------|-----------|----------|-------------|--------|
| N1 | SC2 | send a reminder to an unsubscribed user | criterion SC5 | |
| N2 | SC2 | use guilt or shame wording | judgment | reminder copy is neutral and states only the due item |
```

Ids are contiguous from `E1` and `N1`. Detail is required for every row that
is not `criterion SCn`. The headings are exact: `## Edge coverage` and
`## Prohibitions`. An INTENT.md without them predates the probes and is not
rechecked; a near-miss heading fails the gate rather than switching it off.

## Downstream

- **Plan.** Every `held-out` edge gets one PLAN.md `## Held-out checks` row
  naming the task that owns the edge's criterion and the test file (a
  `path::test_name` node id is fine). That file is listed in the task's
  `files`, the task's Verify runs it, and the task's Acceptance criteria
  state the edge id and its ruling. A `criterion SCn` row needs nothing extra: SCn is
  already covered like any criterion. A `judgment` prohibition belongs in
  the owning task's Approach so the coder knows the line.
- **Review.** A row pins the reading of its criterion. A reviewer does not
  pass a reading that contradicts a ruling in either table, and cites each
  held-out edge and judgment prohibition id with its evidence. An absence
  criterion is judged over its stated search space only.
- **Final review.** A criterion that carries a held-out edge or a judgment
  prohibition is `met` only when its Check, Observed, or Reference cites
  every such id with the evidence: the held-out test's recorded passing
  output, or the observed behavior judged against Detail. When that
  evidence is missing, did not run, or cannot be judged, record
  `unverifiable` with `Finding: insufficient spec evidence: <id> ...`;
  never `met` on inference. The trigger is the tag, not reviewer doubt:
  criteria without a tag are graded as usual and never abstained.

## What the gates can and cannot prove

`check_handoffs.py intent` (before approval and again when define records
approval), `plan`, and `final` prove the tables are complete, every held-out
edge has a scheduled test, and every tagged `met` cites its tags. They cannot
prove who made a ruling or that a cited result says what the verdict claims.
Those stay with the define conversation and the reviewer's recorded evidence.
