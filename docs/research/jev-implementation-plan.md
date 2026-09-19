# Optional Jev evidence screening

Status: implemented locally and verified; no publication or installed-plugin update.

## Contract

User requirement: "not everyone will have it, so has to be an option. but plan it, and lets grt it implemented"

Implement optional advisory evidence screening for wave and final reviewers. Default Path behavior needs no Jev account, key, SDK, request, or extra review artifact. Jev never controls acceptance, phase routing, retries, or publication.

## Design and scope

- Add a standalone Python standard-library helper, `scripts/jev_review.py`. It reads JSON from stdin only when explicitly enabled by `GSD_PATH_JEV=1`. An API key alone does not enable it.
- Enabled users supply `TYPESAFE_API_KEY` and a positive finite `GSD_PATH_JEV_TIMEOUT_SECONDS`. The owner chooses the timeout; there is no invented default. Use the documented version `jev-1.13.0` and official HTTPS endpoint. Do not follow redirects with credentials or retry automatically.
- Input: a full `reviewed_head` and nonempty `items` array of unique `id`, verbatim `criterion`, and selected `evidence` text. Empty evidence is valid and useful. This is caller-supplied material, not Git provenance verified by Jev.
- Ask a Choice per item: `supported`, `partial`, `unsupported`, or `unclear`. Each question identifies its item in its instructions because question IDs are not model input. Preserve probabilities without introducing an acceptance threshold.
- Output JSON is always advisory: `disabled`, `unavailable` with an explicit sanitized reason, or `ok` with the supplied revision, request hash, resolved model, answers, and usage. Optional failures do not stop ordinary review. Do not expose credentials or provider error bodies. Do not write project files.
- Add a conditional pointer to the reviewer role and a disclosed procedure for wave/final mode. Reviewer records advisory status in its already assigned artifact, independently checks relevant concerns, and retains all existing gates. Do not invoke for already-proven/reused reviews.
- Bundle helper and procedure into router, build, and ship skills, including the generated router alias; synchronize package metadata through the existing manifest.

## Blast radius

The helper and conditional reviewer procedure are additive. No state schema, workflow runtime, verifier, archive format, or installer dependency changes. Distribution manifest changes must prove the helper runs from each generated skill bundle. Remote screening sends only the explicitly selected input; enablement is consent to that transfer. It does not authorize extra uploads.

## Execution and proof

1. Add executable CLI tests and observe the enabled behavior fail against a disabled-only baseline.
2. Implement the helper and run focused tests using a local HTTP server at the external boundary. Cover default behavior, successful multi-item mapping, missing configuration, malformed input/responses, HTTP failures, redirects, and no project writes.
3. Add reviewer procedure and distribution entries; run the same CLI checks against generated bundles and the existing resource checks.
4. Temporarily sabotage opt-in and response validation; prove the relevant tests fail, restore, and run final focused verification. Apply Ponytail after each code change.

No paid/live API call is required to prove transport and fallback behavior. Model usefulness, calibration, and real service performance remain unmeasured until an owner enables evaluation on chosen data.

## Verification record

- RED: `python3 -B -m unittest tests.test_jev_review` against the disabled-only baseline ran 7 tests and failed on 30 assertions/subtests: enabled screening and unavailable reasons were absent. The disabled control passed. Later timeout and distribution checks also failed against that baseline (2 tests, 6 failing assertions/subtests), then the implementations were restored.
- GREEN: `python3 -B -m unittest tests.test_jev_review tests.test_sync_skill_resources` passed all 15 tests. The Jev tests execute the real CLI with a local HTTP server; the generated router, build, ship, and alias helpers each returned enabled advice and stayed disabled without opt-in. Existing sync tests cover resource repair and self-contained distribution.
- Sabotage: temporarily removed opt-in and ran `python3 -B -m unittest tests.test_jev_review.JevReviewTests.test_disabled_does_not_parse_input_or_send_request_even_with_key`: failed (3 subtests). Restored.
- Sabotage: temporarily bypassed response validation and ran `python3 -B -m unittest tests.test_jev_review.JevReviewTests.test_incomplete_or_invalid_responses_never_become_advice`: failed (10 subtests). Restored.
- Sabotage: temporarily removed redirect protection and ran `python3 -B -m unittest tests.test_jev_review.JevReviewTests.test_http_failure_and_redirect_are_visible_without_retries_or_secret_echo`: failed (2 assertions/subtests). Restored.
- Resource generation: `python3 -B scripts/sync_skill_resources.py` generated 438 resources with zero divergence warnings. After all sabotage restoration, `python3 -B -m unittest tests.test_jev_review` passed all 9 Jev tests; `python3 -B scripts/sync_skill_resources.py --check` passed (438 resources); `git diff --check` passed. Local documentation links resolved.
- Ponytail: retained a single stdlib HTTP helper and reused existing reviewer/distribution contracts. No SDK, service framework, new state fields, new gate, automatic retries, or extra project artifact.

Coverage mapping: `scripts/jev_review.py` and its four generated copies are exercised by `tests/test_jev_review.py`; `scripts/skill-resources.json` and generated `package.json` are covered by those bundle executions plus `tests/test_sync_skill_resources.py`. README and reviewer procedures are documentation; their source-relative links and generated copies were checked. No live agent review using Jev, provider inference, or measured model-quality claim is made.

## Sources

Normalization follow-up: R1 is fixed at the shared response boundary and in all generated helpers. The focused Jev suite now passes 10 tests; the new CLI/HTTP regression failed on the original implementation and again during restored-original sabotage. Full proof and the floating-point allowance derivation are in the [R1 disposition](jev-fable-review-disposition.md#r1-probability-normalization). No live inference or semantic evaluation was added.

- [Research](jev-integration.md)
- [Official HTTP contract](https://docs.typesafe.ai/api)
- [Models and limits](https://docs.typesafe.ai/models)
- [Reviewer role](../../skills/gsd-path/references/reviewer.md)
- [Distribution manifest](../../scripts/skill-resources.json)
