# Codex delivery comparison

This evaluation compares GSD Path with a direct Codex implementation of the
same widget-counter requirements. It measures one fixture, not global
optimality. It is separate from the all-host release gate.

Commit the candidate first. Use a new evaluation directory outside the source
repository. Preparation makes separate local bare remotes and checkouts from
one product commit, then installs the candidate only in the Path arm.

```bash
python3 tests/evaluate_codex.py prepare --directory /absolute/evaluation --candidate /absolute/gsd-path
python3 tests/evaluate_codex.py run --arm /absolute/evaluation/direct --model MODEL --reasoning EFFORT --sandbox SANDBOX
python3 tests/evaluate_codex.py run --arm /absolute/evaluation/path --model MODEL --reasoning EFFORT --sandbox SANDBOX
python3 tests/evaluate_codex.py report --directory /absolute/evaluation
```

Use the same installed Codex version, model, reasoning effort and sandbox for both arms.
The runner refuses mismatched settings. Model execution is explicit and uses
the configured account. Ordinary CI never starts a paid model run.
Select permissions appropriate to the approved fixture environment. On the
tested CLI, `workspace-write` protects Git metadata and cannot complete the
required commits and branch transitions. Record that as a setup failure;
never combine timings from different sandbox settings into one comparison.

Path uses the standard lane, full review, no optional panel, and direct
integration to its local remote. It stops at owner approval gates. Review the
actual artifact before supplying a continuation file and the recorded thread
ID with `run --resume THREAD --prompt-file /absolute/approval.txt`. Do not
manufacture approvals, native child records, or milestone receipts.

Pin skill selection as well as installation. Before a live run, add the absolute
`path/repo/.agents/skills/gsd-path/SKILL.md` path to its prompt and require the
local bundle for every phase and child. A globally installed skill can otherwise
win selection even when the candidate was installed locally. Preserve the prompt
with the raw run evidence; installation alone does not prove bundle use.

Both arms receive the same product requirements and the owner's token budgets.
The independent acceptance checks live outside their repositories. Agents may
write their own tests but must not read the other arm or the evaluator's tests.
The oracle checks plain output, JSON output, integer type, flag placement,
negative counts, default count, and invalid-input errors.

`activity --arm PATH --category implementation|verification|review -- COMMAND
ARGS` measures an actual subprocess and preserves its exit code. Categories
are caller-declared. Durations are observed, not estimated. Unwrapped work is
unclassified; this instrumentation is not a complete account of thinking time.

`comparison.json` retains command results, revision identities, product checks,
raw host-reported usage, measured activities, and run timings. `comparison.md`
is the review surface. Agent elapsed time sums executions; delivery elapsed
time includes time between resumptions. Summed activities can overlap, so do
not subtract them from elapsed time or present them as exclusive percentages.
Missing usage and missing category measurements are unavailable, never zero.

Product correctness, measurement completeness, and pipeline trust are separate.
A zero CLI exit is not proof of a milestone or child dispatch. To validate a
Codex milestone receipt, pass `report --receipt /absolute/codex.md`; the runner
uses the existing receipt validator against the pinned candidate and manifest.
That is fixture-level proof only. Release trust still requires current tracked
receipts for every declared host through `npm run verify:release`.

## Verification changes in this candidate

- New ledger rows use `gsd-path/verify-ledger/v2` and preserve exact command
  text. The newline separating a task's command from its closing Markdown
  fence is excluded. Pass exactly that extracted text to record and lookup;
  meaningful whitespace differences intentionally miss the cache.
- Legacy rows cannot authorize new reuse or attestation. Historical
  attestations retain their legacy reader and archives are not rewritten.
- New attestations use `gsd-path/attestation/v2` with a JSON-encoded command.
- `isolate-verify --historical-task T###` admits only that task's
  recovery-proven landing. Default verification still requires current HEAD.

The targeted ledger, attestation, historical isolation, smoke-audit, oracle,
and measurement checks were each observed failing under a deliberate broken
implementation and passing after restoration. Ledger and audit regressions
also reproduced the original faults before their fixes. The source of proof
is executable test behavior, not the presence of contract text.

## Initial binding follow-up

`bind-initial` now admits only the exact untracked, validated initial state,
with no other reported changes or extra `.project` entries. It rejects staged
state, invalid or advanced state, symlinks, and hard links, and checks file
identity and bytes across binding. Existing base, branch, and worktree checks
remain in force. This proves validated content, not which process created it;
the rechecks do not make Git and state writes one atomic transaction.

The regression reproduced the former cleanliness error. The real initialize →
bind → interrupted resume → state transition now passes without a commit.
The full-cycle fixture now initializes after its published baseline rather than
committing state before binding. All 20 focused binding and full-cycle tests
passed. Bypassing state validation made nine rejection cases fail; restoring
validation passed. Simplification review retained one shared admission helper.
