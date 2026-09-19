# Fable review disposition

Date: 2026-09-19
Reviewer: `claude-fable-5-1`, confirmed by CLI response metadata.
Original verdict: approve with one small code fix.
Scope: complete helper, tests, reviewer procedures, implementation plan, and tracked distribution diff. Static review with no tools; no reviewer test execution.

[Original review](jev-fable-review.md) · [Model receipt](jev-fable-review-response.json) · [Input hashes](jev-fable-review-request.json)

## Reproduced and fixed

Deeply nested stdin and HTTP response JSON both raised uncaught `RecursionError`, exiting nonzero instead of returning an advisory `unavailable` receipt. The reproduction size comes from `sys.getrecursionlimit() + 1`; it adds no production payload limit.

Added `RecursionError` to the two JSON-boundary exception handlers in `scripts/jev_review.py`. Added nested payload variants to the existing invalid-input and invalid-response CLI tests in `tests/test_jev_review.py`. Synchronized the four generated helper copies. Ponytail review retained only the two exception-handler changes and the corresponding regression inputs.

RED command (before fix):

```sh
python3 -B -m unittest tests.test_jev_review.JevReviewTests.test_invalid_input_is_visible_without_request tests.test_jev_review.JevReviewTests.test_incomplete_or_invalid_responses_never_become_advice
```

Result: 2 tests, 2 failures; both CLI calls exited 1 with `RecursionError`.

GREEN command: `python3 -B -m unittest tests.test_jev_review` — 9 tests passed, including enabled/default-off behavior in all generated bundles.

Sabotage: temporarily removed both `RecursionError` catches, ran the RED command again, and observed the same 2 failures. Restored the catches and reran the Jev suite: 9 passed. `python3 -B scripts/sync_skill_resources.py --check` passed with 438 resources; `git diff --check` passed.

The original Fable verdict applies to the pre-fix input hashes. The parent reproduced and verified the fix; Fable did not re-review the updated version.

## Other comments

- Live API response compatibility: remains a disclosed limitation; no live inference call was made. Existing implementation follows the cited official wire contract.
- Proxy/TLS environment documentation: no demonstrated contract violation; no change.
- Test environment and scheduling robustness: no reproduced failure in this environment; no change.
- Reviewer-mode wording: no demonstrated violation of the wave/final screening contract; no change.
- Additional test variants: optional coverage suggestions without a demonstrated defect; no change.

No open reproduced defect remains from this review. No publication or installed-plugin update.

## R1: probability normalization

The later review finding is legitimate: the response boundary checked each probability and the selected maximum, but omitted the distribution total. The real CLI accepted all-zero, below-one, and above-one distributions as successful advice. This is a shared response-validation gap; callers need no separate handling.

Added one guard in `checked_response` using `math.fsum` and regenerated all four bundled helpers. The [provider contract](https://docs.typesafe.ai/api) requires probabilities to sum to one. The allowance is `sys.float_info.epsilon`, the floating-point spacing above one, rather than a provider rounding assumption or confidence threshold. For nonnegative probabilities totaling one, nearest-representation conversion contributes at most epsilon/2 in aggregate, and rounding their accurately accumulated sum near one contributes at most another epsilon/2. See [Python floating-point error](https://docs.python.org/3/tutorial/floatingpoint.html), [fsum](https://docs.python.org/3/library/math.html#math.fsum), and [float_info](https://docs.python.org/3/library/sys.html#sys.float_info).

Regression command:

```sh
python3 -B -m unittest tests.test_jev_review.JevReviewTests.test_probability_distributions_must_be_normalized
```

- RED before implementation: one test, 20 failing subtests. Four malformed distributions returned `ok` in the canonical helper and each of four bundles. Two valid nontrivial distributions remained accepted in every copy.
- Restored-original sabotage: temporarily replaced those five helpers with `HEAD:scripts/jev_review.py`, ran the same command, and reproduced all 20 failures. Restored every fixed file in a `finally` block.
- Final GREEN: `python3 -B -m unittest tests.test_jev_review` passed all 10 tests after restoration. The new test uses the real CLI and local HTTP boundary, checks unavailable receipts without answers, preserves revision/request hashes, rejects a total two epsilon above one, and preserves valid distributions unchanged.
- `python3 -B scripts/sync_skill_resources.py` regenerated 438 resources with zero warnings; its final `--check` passed. `git diff --check` passed for the code changes.
- Ponytail after edits and restoration: retained only the shared guard, executable regression, generated copies, and these records. No dependencies, refactor, new confidence policy, or altered fallback.

No live provider inference or semantic evaluation ran. Default-off behavior, advisory authority, credential protections, and ordinary-review fallback remain covered by the existing tests. Publication, CI, and installed-plugin changes remain outside this review phase.
